"""dm/android/spv_tffrag.h (transform feedback captured in the fragment stage, for a GPU without vertex-stage storage writes: the Mali-G715), built for the PC and
run on modules assembled with the NDK's spirv-as; spirv-val checks each result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every vertex shader there, and the fragment shader made for each one with a feedback layout."""
import ctypes
import json
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

# A vertex shader as the translator writes one with a feedback layout: gl_PerVertex as a block (Position, PointSize, ClipDistance, CullDistance), generic outputs
# vec4 at locations 0-2, and no gl_VertexIndex
VS = '''OpCapability Shader
OpCapability ClipDistance
OpCapability CullDistance
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %in0 %o0 %o1 %o2 %pv
OpDecorate %in0 Location 0
OpDecorate %o0 Location 0
OpDecorate %o1 Location 1
OpDecorate %o2 Location 2
OpDecorate %blk Block
OpMemberDecorate %blk 0 BuiltIn Position
OpMemberDecorate %blk 1 BuiltIn PointSize
OpMemberDecorate %blk 2 BuiltIn ClipDistance
OpMemberDecorate %blk 3 BuiltIn CullDistance
%void = OpTypeVoid
%fn = OpTypeFunction %void
%float = OpTypeFloat 32
%v4 = OpTypeVector %float 4
%int = OpTypeInt 32 1
%i0 = OpConstant %int 0
%u1 = OpConstant %int 1
%arr = OpTypeArray %float %u1
%blk = OpTypeStruct %v4 %float %arr %arr
%pblk = OpTypePointer Output %blk
%pv4o = OpTypePointer Output %v4
%pv4i = OpTypePointer Input %v4
%in0 = OpVariable %pv4i Input
%o0 = OpVariable %pv4o Output
%o1 = OpVariable %pv4o Output
%o2 = OpVariable %pv4o Output
%pv = OpVariable %pblk Output
%main = OpFunction %void None %fn
%l = OpLabel
%a = OpLoad %v4 %in0
OpStore %o0 %a
OpStore %o1 %a
OpStore %o2 %a
%pp = OpAccessChain %pv4o %pv %i0
OpStore %pp %a
OpReturn
OpFunctionEnd
'''
# Position a variable of its own, no point size, gl_VertexIndex declared (as uint), and an early return on a branch
VS2 = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %pos %vid %o1
OpDecorate %pos BuiltIn Position
OpDecorate %vid BuiltIn VertexIndex
OpDecorate %o1 Location 1
%void = OpTypeVoid
%fn = OpTypeFunction %void
%float = OpTypeFloat 32
%v4 = OpTypeVector %float 4
%uint = OpTypeInt 32 0
%bool = OpTypeBool
%u0 = OpConstant %uint 0
%f1 = OpConstant %float 1
%vec = OpConstantComposite %v4 %f1 %f1 %f1 %f1
%pv4o = OpTypePointer Output %v4
%pui = OpTypePointer Input %uint
%pos = OpVariable %pv4o Output
%vid = OpVariable %pui Input
%o1 = OpVariable %pv4o Output
%main = OpFunction %void None %fn
%l = OpLabel
OpStore %o1 %vec
%v = OpLoad %uint %vid
%z = OpIEqual %bool %v %u0
OpSelectionMerge %m None
OpBranchConditional %z %early %m
%early = OpLabel
OpReturn
%m = OpLabel
OpStore %pos %vec
OpReturn
OpFunctionEnd
'''
ARCEUS = [[[[0, 3]], 12], [[[1, 1]], 4], [[[2, 1]], 4], []]   # Pokémon Legends: Arceus's layout (a3fe02b2f67c772e)


class Layout(ctypes.Structure):
    _fields_ = [('stride', ctypes.c_uint32 * 4), ('nout', ctypes.c_uint32 * 4), ('loc', (ctypes.c_uint8 * 32) * 4), ('ncomp', (ctypes.c_uint8 * 32) * 4)]


def layout(tf):   # res.json "tf" → spv_tff_layout, as gfx_vk_draw.inc sh_get reads it
    L = Layout()
    for b, e in enumerate(tf[:4]):
        if not e: continue
        L.stride[b] = e[1]; L.nout[b] = len(e[0])
        for q, (o, n) in enumerate(e[0][:32]): L.loc[b][q] = o; L.ncomp[b][q] = n
    return L


def words(data): return struct.unpack('<%dI' % (len(data) // 4), data)


def ops(data):   # [(opcode, operands)]
    w = words(data); i = 5; out = []
    while i < len(w):
        n = w[i] >> 16; out.append((w[i] & 0xffff, w[i + 1:i + n])); i += max(n, 1)
    return out


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvTfFrag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 't.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_tffrag.h"\n'
                       f'{export} size_t vs(const uint32_t *w, size_t n, uint32_t *o, size_t cap) {{ return spv_tff_vs(w, n, o, cap); }}\n'
                       f'{export} size_t fs(uint32_t v, const spv_tff_layout *l, uint32_t outs, uint32_t *o, size_t cap) {{ return spv_tff_fs(v, l, outs, o, cap); }}\n'
                       f'{export} uint32_t outs(const uint32_t *w, size_t n) {{ return spv_tff_outs(w, n); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone
            subprocess.run([cls.bin / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-Werror', '-I', REPO / 'dm/android', '-c', src,
                            '-o', cls.tmp / 't.obj'], check=True)
            subprocess.run([cls.bin / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "t.dll"}', str(cls.tmp / 't.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 't.dll'))
        else:   # the system's clang, as test_spv_limits.py explains
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or cls.bin / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 't.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 't.so'))
        cls.lib.vs.restype = cls.lib.fs.restype = ctypes.c_size_t; cls.lib.outs.restype = ctypes.c_uint32

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def asm(self, text, name):
        (self.tmp / f'{name}.spvasm').write_text(text)
        subprocess.run([self.spv_as, '--target-env', 'vulkan1.1', self.tmp / f'{name}.spvasm', '-o', self.tmp / f'{name}.spv'], check=True)
        return (self.tmp / f'{name}.spv').read_bytes()

    def valid(self, data, name, env='vulkan1.1'):
        (self.tmp / f'{name}.out.spv').write_bytes(data)
        r = subprocess.run([self.spv_val, '--target-env', env, self.tmp / f'{name}.out.spv'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def vs(self, data):   # → the wrapped module or None
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); cap = n + 400; o = (ctypes.c_uint32 * cap)()
        k = self.lib.vs(w, n, o, cap)
        return bytes(o)[:4 * k] if k else None

    def outs(self, data): n = len(data) // 4; return self.lib.outs((ctypes.c_uint32 * n).from_buffer_copy(data), n)

    def fs(self, tf, outs, version=0x00010300):
        o = (ctypes.c_uint32 * 1024)(); L = layout(tf)
        k = self.lib.fs(version, ctypes.byref(L), outs, o, 1024)
        return bytes(o)[:4 * k] if k else None

    def test_the_wrapper_places_each_vertex_on_its_pixel(self):
        data = self.asm(VS, 'vs'); out = self.vs(data); self.assertIsNotNone(out); assert out is not None
        self.valid(out, 'vs')
        o = ops(out)
        entry = [x for op, x in o if op == 15][0]
        orig = [x for op, x in ops(data) if op == 15][0][1]
        self.assertNotEqual(entry[1], orig)   # the entry point is the wrapper
        self.assertTrue([x for op, x in o if op == 57 and x[2] == orig])   # which calls the shader
        self.assertIn(42, [x[2] for op, x in o if op == 71 and x[1] == 11])   # gl_VertexIndex declared
        self.assertTrue([x for op, x in o if op == 43 and x[2] == 0x3b000000])   # 1/512
        self.assertEqual(sum(1 for op, x in o if op == 62), 4 + 2)   # the shader's 4, then position and point size
        self.assertFalse(self.distance_chains(out))   # the clip and cull distances it never writes stay unwritten (9 of them would pass the GPU's 8)

    def distance_chains(self, data):   # access chains into gl_PerVertex members 2 and 3 (clip, cull) of the block variable, by constant index
        o = ops(data); consts = {x[1]: x[2] for op, x in o if op == 43}
        blk = [x[0] for op, x in o if op == 72 and x[2] == 11 and x[3] == 0]
        ptrs = {x[0] for op, x in o if op == 32 and blk and x[2] == blk[0]}
        var = [x[1] for op, x in o if op == 59 and x[0] in ptrs]
        return [x for op, x in o if op == 65 and var and x[2] == var[0] and len(x) >= 4 and consts.get(x[3]) in (2, 3)]

    def test_a_clip_distance_the_shader_writes_is_made_1(self):
        vs = VS.replace('OpStore %pp %a\n', 'OpStore %pp %a\n%f0 = OpCompositeExtract %float %a 0\n%cd = OpAccessChain %pfo %pv %i2 %i0\nOpStore %cd %f0\n').replace(
            '%i0 = OpConstant %int 0\n', '%i0 = OpConstant %int 0\n%i2 = OpConstant %int 2\n').replace('%pv4i = OpTypePointer Input %v4\n', '%pv4i = OpTypePointer Input %v4\n%pfo = OpTypePointer Output %float\n')
        out = self.vs(self.asm(vs, 'vsclip')); self.assertIsNotNone(out); assert out is not None
        self.valid(out, 'vsclip')
        consts = {x[1]: x[2] for op, x in ops(out) if op == 43}
        self.assertEqual(sorted(consts.get(x[3], -1) for x in self.distance_chains(out)), [2, 2])   # the shader's clip distance and the wrapper's; no cull distance

    def test_a_position_variable_an_early_return_and_no_point_size(self):
        data = self.asm(VS2, 'vs2'); out = self.vs(data); self.assertIsNotNone(out); assert out is not None
        self.valid(out, 'vs2')
        o = ops(out)
        self.assertIn(1, [x[2] for op, x in o if op == 71 and x[1] == 11])   # a PointSize variable added
        self.assertEqual(sum(1 for op, x in o if op == 71 and x[1] == 11 and x[2] == 42), 1)   # gl_VertexIndex kept, not declared again
        self.assertEqual(len([x for op, x in o if op == 15][0]) - len([x for op, x in ops(data) if op == 15][0]), 1)   # the interface grows by the point size

    def test_a_fragment_shader_is_not_wrapped(self):
        fs = self.fs(ARCEUS, 7)
        assert fs is not None
        self.assertIsNone(self.vs(fs))

    def test_the_outputs_mask(self):
        self.assertEqual(self.outs(self.asm(VS, 'vs3')), 0b111)
        self.assertEqual(self.outs(self.asm(VS2, 'vs4')), 0b10)

    def test_arceus_fragment_shader(self):
        fs = self.fs(ARCEUS, 0b111); self.assertIsNotNone(fs); assert fs is not None
        self.valid(fs, 'fs')
        o = ops(fs)
        self.assertEqual(sorted(x[2] for op, x in o if op == 71 and x[1] == 33), [100, 101, 102])   # bindings 100 + buffer
        self.assertEqual(sum(1 for op, x in o if op == 71 and x[1] == 14), 3)   # three flat inputs
        self.assertEqual(sum(1 for op, x in o if op == 62), 5)   # 3 + 1 + 1 words a vertex

    def test_an_output_the_shader_lacks_stores_zero(self):
        fs = self.fs(ARCEUS, 0b001); self.assertIsNotNone(fs); assert fs is not None
        self.valid(fs, 'fs0')
        o = ops(fs)
        self.assertEqual(sum(1 for op, x in o if op == 71 and x[1] == 30), 1)   # only location 0 is an input
        self.assertEqual(sum(1 for op, x in o if op == 62), 5)

    def test_interleaved_outputs_and_spirv_1_4(self):   # Xenoblade-like: several outputs in one buffer; 1.4 lists the buffers in the interface
        tf = [[[[0, 4], [3, 2], [5, 1]], 28], [], [], [[[1, 4]], 16]]
        fs = self.fs(tf, 0b101011, 0x00010500); self.assertIsNotNone(fs); assert fs is not None
        self.valid(fs, 'fs14', 'vulkan1.2')
        self.assertEqual(sum(1 for op, x in ops(fs) if op == 62), 7 + 4)

    def test_too_many_words_a_vertex(self):
        self.assertIsNone(self.fs([[[[0, 4]] * 33, 528], [], [], []], 1))

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR (a game\'s packed spv folder) not set')
    def test_a_games_shaders(self):   # every wrapped vertex shader and every capture fragment shader must pass spirv-val
        d = Path(os.environ['DM_SPV_DIR']); nv = nf = 0; lim = int(os.environ.get('DM_SPV_LIMIT', '0') or 0)
        for f in sorted(d.glob('*.res.json')):
            res = json.loads(f.read_text(encoding='utf-8'))
            if res.get('stage', 'vs') != 'vs': continue
            key = f.name[:-len('.res.json')]; data = (d / f'{key}.spv').read_bytes()
            tf = res.get('tf')
            if not tf and lim and nv >= lim: continue
            out = self.vs(data); self.assertIsNotNone(out, key); assert out is not None
            self.valid(out, key); nv += 1
            if tf:
                fs = self.fs(tf, self.outs(data), words(data)[1]); self.assertIsNotNone(fs, key); assert fs is not None
                self.valid(fs, key + '.tff'); nf += 1
        print(f'{nv} vertex shaders wrapped, {nf} capture fragment shaders made in {d}')


if __name__ == '__main__':
    unittest.main()
