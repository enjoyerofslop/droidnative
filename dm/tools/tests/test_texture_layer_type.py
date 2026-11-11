"""A sampled array texture's layer stays an integer through the locals the structured program copies it to (StructuredProgram.GetSourceVarType), using synthetic shaders only.

The layer of a 2D-array TEX is picked by a predicated MOV32I (2, or 1 under P0), so the translator joins the two values in a local. That local took the generic
type of a texture sample's sources, FP32: the layers became the float bit patterns 2 and 1 (denormals), bit-cast back to an integer at the sample. Ocarina of
Time's three lightmap layers all read layer 0 that way on an Adreno (DeathKhan/nx2android 5164b63).
Needs the translator:
  DMSH_TEST_XLATE=$PWD/dm/gfx/tools/dmsh_xlate_bin/dmsh_xlate python3 -m unittest discover -s dm/tools/tests -p test_texture_layer_type.py -v
No game inputs are used.
"""
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
TABLE = (ROOT / 'dm/third_party/ryujinx/src/Ryujinx.Graphics.Shader/Decoders/InstTable.cs').read_text()
SPIRV_CROSS = ROOT / 'dm/gfx/tools/spirv_cross_bin/spirv-cross'
DIM_2D_ARRAY = 3                                                # TexDim
SLOT_128, SAMPLER_1 = 0x168, 0x570                              # c[2] offsets of a separate texture and sampler
ONE_F = 0x3f800000                                              # 1.0f


def base(name):                                                 # the first form of the instruction in InstTable.cs (ISETP: the register form)
    match = re.search(r'Add\("([01x]{64})", InstName\.' + name + r'\s*,', TABLE)
    assert match, f'{name} is not in InstTable.cs'
    return int(match[1].replace('x', '0'), 2)


def ldc(rd, offset):                                            # LDC.32 Rd, c[2][offset], RZ
    return base('Ldc') | (4 << 48) | (2 << 36) | (offset << 20) | (7 << 16) | (255 << 8) | rd


def mov(rd, value, pred=7):                                     # [@Ppred] MOV32I Rd, value
    return base('Mov32i') | (value << 20) | (pred << 16) | (15 << 12) | rd


def isetp_eq_zero(pd, ra):                                      # ISETP.EQ.AND Ppd, PT, Ra, RZ, PT
    return base('Isetp') | (2 << 49) | (7 << 39) | (255 << 20) | (7 << 16) | (ra << 8) | (pd << 3) | 7


def sample(rd):                                                 # TEX.B.LZ Rd, red, 2D array: layer in R0, coordinates in R1, R2; handle in R6 (R10, R11 scratch)
    handle = [ldc(10, SLOT_128), ldc(11, SAMPLER_1), base('Lop') | (1 << 41) | (11 << 20) | (7 << 16) | (10 << 8) | 6]
    return handle + [base('TexB') | (1 << 37) | (1 << 31) | (DIM_2D_ARRAY << 28) | (6 << 20) | (7 << 16) | (0 << 8) | rd]


def keep(reg):                                                  # SUATOM.ADD on image slot 0 at R3: uses the register, so its read stays
    return base('Suatom') | (0x48 << 36) | (3 << 33) | (reg << 20) | (7 << 16) | (3 << 8) | 255


def shader(layer, u):
    """layer, u: (value, value under P0), with P0 = (c[2][0x100] == 0), a word the translator cannot know"""
    insts = [ldc(12, 0x100), isetp_eq_zero(0, 12), mov(0, layer[0]), mov(0, layer[1], pred=0), mov(1, u[0]), mov(1, u[1], pred=0), mov(2, 0), mov(3, 0)]
    insts += sample(9) + [keep(9), base('Exit') | (7 << 16) | 15]
    words = []
    for i, inst in enumerate(insts):
        if i % 3 == 0: words.append(0)                          # Maxwell scheduling word
        words.append(inst)
    return struct.pack('<%dQ' % len(words), *words)


@unittest.skipUnless(os.environ.get('DMSH_TEST_XLATE'), 'set DMSH_TEST_XLATE to the offline translator')
class ArrayLayerType(unittest.TestCase):
    def glsl(self, code):
        """The shader's GLSL, after spirv-val when it is on PATH"""
        with tempfile.TemporaryDirectory(prefix='layer_type_') as d:
            work = Path(d); (work / 'k.bin').write_bytes(code)
            job = dict(key='k', stage='cs', code=str(work / 'k.bin'), tex={}, img={'0': dict(type='2d', fmt='R32Uint')}, local=[1, 1, 1], debug=True)
            (work / 'jobs.json').write_text(json.dumps([job]))
            r = subprocess.run([os.environ['DMSH_TEST_XLATE'], str(work / 'jobs.json'), d], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            if shutil.which('spirv-val'): subprocess.run(['spirv-val', '--target-env', 'vulkan1.1', str(work / 'k.spv')], check=True)
            r = subprocess.run([str(SPIRV_CROSS), '--version', '450', '--vulkan-semantics', str(work / 'k.spv')], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            return r.stdout

    def test_the_layer_goes_through_integer_locals(self):
        out = self.glsl(shader(layer=(2, 1), u=(0, 0)))
        self.assertRegex(out, r'int _\d+ = 2;')
        self.assertRegex(out, r'_\d+ = 1;')
        self.assertNotIn('e-45', out, 'no layer held as a denormal float')
        self.assertNotIn('floatBitsToInt(_', out.split('textureLod')[0].split('== 0;')[1], 'no layer bit-cast back from a float local')

    def test_a_coordinate_stays_a_float(self):
        out = self.glsl(shader(layer=(2, 1), u=(0, ONE_F)))
        self.assertRegex(out, r'_\d+ = 1\.0;', 'the u coordinate copied as a float')
        self.assertRegex(out, r'int _\d+ = 2;')


if __name__ == '__main__':
    unittest.main()
