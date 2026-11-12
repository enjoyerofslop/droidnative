"""dm/android/spv_vsinit.h (every vertex shader output started as (0,0,0,1), as on the hardware: Pokémon Legends: Arceus's full-screen vertex shaders write
only x and y of their location 0 output and its pixel shaders divide by w, which read 0 on Android), built for the PC and run on modules assembled with the
NDK's spirv-as; spirv-val checks each result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there (each rewritten module must pass spirv-val)."""
import ctypes
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spv_readonly import NDK, HOST, EXE, REPO   # noqa: E402

# A full-screen vertex shader as the translator writes Arceus's (870ec52c811ec5f1): the position and x, y of location 0 from the vertex index, z and w of
# location 0 never written; location 1 written whole, and an int output at location 2 (not a float vec4: left alone)
VS = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %pos %o0 %o1 %o2 %vid
OpDecorate %pos BuiltIn Position
OpDecorate %vid BuiltIn VertexIndex
OpDecorate %o0 Location 0
OpDecorate %o1 Location 1
OpDecorate %o2 Location 2
OpDecorate %o2 Flat
%void = OpTypeVoid
%fn = OpTypeFunction %void
%int = OpTypeInt 32 1
%uint = OpTypeInt 32 0
%float = OpTypeFloat 32
%v4 = OpTypeVector %float 4
%pv4 = OpTypePointer Output %v4
%pf = OpTypePointer Output %float
%pint = OpTypePointer Output %int
%pin = OpTypePointer Input %int
%fpf = OpTypePointer Function %float
%pos = OpVariable %pv4 Output
%o0 = OpVariable %pv4 Output
%o1 = OpVariable %pv4 Output
%o2 = OpVariable %pint Output
%vid = OpVariable %pin Input
%u0 = OpConstant %uint 0
%u1 = OpConstant %uint 1
%one = OpConstant %float 1
%vec = OpConstantComposite %v4 %one %one %one %one
%main = OpFunction %void None %fn
%l = OpLabel
LOCALS%i = OpLoad %int %vid
%f = OpConvertSToF %float %i
%px = OpAccessChain %pf %pos %u0
OpStore %px %f
%x = OpAccessChain %pf %o0 %u0
OpStore %x %f
%y = OpAccessChain %pf %o0 %u1
OpStore %y %f
OpStore %o1 %vec
OpStore %o2 %i
OpReturn
OpFunctionEnd
'''
FS = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %i0 %c0
OpExecutionMode %main OriginUpperLeft
OpDecorate %i0 Location 0
OpDecorate %c0 Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%float = OpTypeFloat 32
%v4 = OpTypeVector %float 4
%pi = OpTypePointer Input %v4
%po = OpTypePointer Output %v4
%i0 = OpVariable %pi Input
%c0 = OpVariable %po Output
%main = OpFunction %void None %fn
%l = OpLabel
%v = OpLoad %v4 %i0
OpStore %c0 %v
OpReturn
OpFunctionEnd
'''


def words(data): return struct.unpack('<%dI' % (len(data) // 4), data)


def ops(data):   # [(opcode, operands)]
    w = words(data); i = 5; out = []
    while i < len(w):
        n = w[i] >> 16; out.append((w[i] & 0xffff, w[i + 1:i + n])); i += max(n, 1)
    return out


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvVsinit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'v.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_vsinit.h"\n{export} size_t run(const uint32_t *w, size_t n, uint8_t *s, uint32_t *o, size_t cap) {{ return spv_vsinit(w, n, s, o, cap); }}\n'
                       f'{export} int wanted(const uint32_t *w, size_t n) {{ return spv_vsinit_wanted(w, n); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone
            subprocess.run([cls.bin / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-Werror', '-I', REPO / 'dm/android', '-c', src,
                            '-o', cls.tmp / 'v.obj'], check=True)
            subprocess.run([cls.bin / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "v.dll"}', str(cls.tmp / 'v.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'v.dll'))
        else:   # the system's clang, as test_spv_limits.py explains
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or cls.bin / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'v.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'v.so'))
        cls.lib.run.restype = ctypes.c_size_t

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def asm(self, text, name):
        (self.tmp / f'{name}.spvasm').write_text(text)
        subprocess.run([self.spv_as, '--target-env', 'vulkan1.1', self.tmp / f'{name}.spvasm', '-o', self.tmp / f'{name}.spv'], check=True)
        return (self.tmp / f'{name}.spv').read_bytes()

    def valid(self, data, name):
        (self.tmp / f'{name}.out.spv').write_bytes(data)
        r = subprocess.run([self.spv_val, '--target-env', 'vulkan1.1', self.tmp / f'{name}.out.spv'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def run_on(self, data):   # → the rewritten module or None
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); cap = n + 15 + 3 * 32
        s = (ctypes.c_uint8 * (2 * words(data)[3]))(); o = (ctypes.c_uint32 * cap)()
        k = self.lib.run(w, n, s, o, cap)
        return bytes(o)[:4 * k] if k else None

    def wanted(self, data): n = len(data) // 4; return self.lib.wanted((ctypes.c_uint32 * n).from_buffer_copy(data), n)

    def check_started(self, src, name):
        data = self.asm(src, name); self.assertTrue(self.wanted(data))
        out = self.run_on(data); self.assertIsNotNone(out); assert out is not None
        self.valid(out, name)
        before, after = ops(data), ops(out)
        names = {x[1]: x[0] for op, x in before if op == 59}   # OpVariable: id → pointer type
        o0, o1 = (next(x[0] for op, x in before if op == 71 and x[1:] == (30, loc)) for loc in (0, 1))
        self.assertEqual(words(out)[3], words(data)[3] + 3)   # three new ids: 0.0, 1.0 and the vec4
        consts = [x for op, x in after if op in (43, 44) and x[1] >= words(data)[3]]
        self.assertEqual([c[2:] for c in consts], [(0,), (0x3f800000,), (words(data)[3],) * 3 + (words(data)[3] + 1,)])   # 0.0, 1.0, (0,0,0,1)
        lab = next(i for i, (op, _) in enumerate(after) if op == 248)   # the entry point's first OpLabel
        i = lab + 1
        while after[i][0] == 59: i += 1   # its local variables stay first
        stores = []
        while after[i][0] == 62: stores.append(after[i][1]); i += 1
        self.assertEqual(stores, [(o0, words(data)[3] + 2), (o1, words(data)[3] + 2)])   # locations 0 and 1, not the position, not the int at location 2
        self.assertEqual(len(after), len(before) + 5)
        self.assertIn(o0, names)
        return out

    def test_outputs_start_as_0001_before_the_body(self):
        self.check_started(VS.replace('LOCALS', ''), 'vs')

    def test_local_variables_stay_first_in_the_block(self):
        self.check_started(VS.replace('LOCALS', '%t = OpVariable %fpf Function\n%t2 = OpVariable %fpf Function\n'), 'vsloc')

    def test_a_fragment_shader_is_left_alone(self):
        data = self.asm(FS, 'fs'); self.assertFalse(self.wanted(data)); self.assertIsNone(self.run_on(data))

    def test_a_vertex_shader_without_attribute_outputs_is_left_alone(self):   # the position alone: nothing to start
        only_pos = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %pos
OpDecorate %pos BuiltIn Position
%void = OpTypeVoid
%fn = OpTypeFunction %void
%float = OpTypeFloat 32
%v4 = OpTypeVector %float 4
%pv4 = OpTypePointer Output %v4
%pos = OpVariable %pv4 Output
%one = OpConstant %float 1
%vec = OpConstantComposite %v4 %one %one %one %one
%main = OpFunction %void None %fn
%l = OpLabel
OpStore %pos %vec
OpReturn
OpFunctionEnd
'''
        data = self.asm(only_pos, 'pos'); self.assertTrue(self.wanted(data)); self.assertIsNone(self.run_on(data))

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR (a game\'s packed spv folder) not set')
    def test_a_games_shaders(self):   # each rewritten module must pass spirv-val
        d = Path(os.environ['DM_SPV_DIR']); n = 0
        for f in sorted(d.glob('*.spv')):
            data = f.read_bytes()
            if not self.wanted(data): continue
            out = self.run_on(data)
            if out is None: continue
            self.valid(out, f.stem); n += 1
        print(f'{n} modules rewritten in {d}')


if __name__ == '__main__':
    unittest.main()
