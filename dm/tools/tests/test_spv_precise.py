"""dm/android/spv_precise.h (Maxwell's FMUL and FADD kept unfused, NoContraction, in the shaders that place vertices: Super Mario Odyssey's Cap Kingdom ground
failed its G-buffer depth test in blocks on the Mali-G715, whose compiler fused different products in its depth pre-pass and G-buffer vertex shaders), built for
the PC and run on modules assembled with the NDK's spirv-as; spirv-val checks each result. Skipped without the NDK.
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

# A vertex shader as the translator writes a position: Maxwell's FMUL and FADD as OpFMul and OpFAdd, its FFMA as GLSL.std.450 Fma, and one result the module
# already decorates NoContraction
VS = '''OpCapability Shader
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %pos %in
OpName %main "main"
OpDecorate %pos BuiltIn Position
OpDecorate %pos Invariant
OpDecorate %in Location 0
OpDecorate %sub NoContraction
%void = OpTypeVoid
%fn = OpTypeFunction %void
%float = OpTypeFloat 32
%v4 = OpTypeVector %float 4
%pv4 = OpTypePointer Output %v4
%iv4 = OpTypePointer Input %v4
%pos = OpVariable %pv4 Output
%in = OpVariable %iv4 Input
%one = OpConstant %float 1
%half = OpConstant %float 0.5
%main = OpFunction %void None %fn
%l = OpLabel
%v = OpLoad %v4 %in
%x = OpCompositeExtract %float %v 0
%y = OpCompositeExtract %float %v 1
%mx = OpFMul %float %x %half
%my = OpFMul %float %y %half
%s = OpFAdd %float %mx %my
%sub = OpFSub %float %s %one
%neg = OpFNegate %float %sub
%f = OpExtInst %float %glsl Fma %x %half %neg
%vs = OpVectorTimesScalar %v4 %v %f
OpStore %pos %vs
OpReturn
OpFunctionEnd
'''
FS = VS.replace('OpEntryPoint Vertex %main "main" %pos %in', 'OpEntryPoint Fragment %main "main" %pos %in\nOpExecutionMode %main OriginUpperLeft').replace(
    'OpDecorate %pos BuiltIn Position\nOpDecorate %pos Invariant\n', 'OpDecorate %pos Location 0\n')


def words(data): return struct.unpack('<%dI' % (len(data) // 4), data)


def ops(data):   # [(opcode, operands)]
    w = words(data); i = 5; out = []
    while i < len(w):
        n = w[i] >> 16; out.append((w[i] & 0xffff, w[i + 1:i + n])); i += max(n, 1)
    return out


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvPrecise(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'p.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text('#include "spv_precise.h"\n'
                       f'{export} size_t run(const uint32_t *w, size_t n, uint32_t *s, uint32_t *o, size_t cap, size_t *need, int *marked) {{ return spv_precise(w, n, s, o, cap, need, marked); }}\n'
                       f'{export} int wanted(const uint32_t *w, size_t n) {{ return spv_precise_wanted(w, n); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone
            subprocess.run([cls.bin / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-Werror', '-I', REPO / 'dm/android', '-c', src,
                            '-o', cls.tmp / 'p.obj'], check=True)
            subprocess.run([cls.bin / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "p.dll"}', str(cls.tmp / 'p.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'p.dll'))
        else:   # the system's clang, as test_spv_limits.py explains
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or cls.bin / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'p.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'p.so'))
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

    def run_on(self, data):   # → (the rewritten module or None, results marked)
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); s = (ctypes.c_uint32 * (words(data)[3] // 32 + 1))()
        need, marked = ctypes.c_size_t(), ctypes.c_int()
        self.lib.run(w, n, s, None, 0, ctypes.byref(need), ctypes.byref(marked))
        if not need.value: return None, marked.value
        o = (ctypes.c_uint32 * need.value)()
        k = self.lib.run(w, n, s, o, need.value, ctypes.byref(need), ctypes.byref(marked))
        return (bytes(o)[:4 * k] if k else None), marked.value

    def wanted(self, data): n = len(data) // 4; return self.lib.wanted((ctypes.c_uint32 * n).from_buffer_copy(data), n)

    def test_a_vertex_shaders_mul_add_sub_negate_and_scale_are_marked(self):
        data = self.asm(VS, 'vs'); self.assertTrue(self.wanted(data))
        out, marked = self.run_on(data); self.assertIsNotNone(out); assert out is not None
        self.valid(out, 'vs')
        o, before = ops(out), ops(data)
        nc = sorted(x[0] for op, x in o if op == 71 and len(x) == 2 and x[1] == 42)
        res = {x[1]: op for op, x in o if op in (127, 129, 131, 133, 142, 12)}   # result id → opcode (12: OpExtInst)
        self.assertEqual(sorted(res[r] for r in nc), [127, 129, 131, 133, 133, 142])   # FNegate, FAdd, FSub (the module's own), both FMul, VectorTimesScalar
        self.assertEqual(marked, 5)   # the FSub was decorated already, so once
        self.assertNotIn(12, [res[r] for r in nc])   # the Fma (Maxwell's FFMA) is fused as written
        self.assertEqual([x for x in o if x[0] != 71], [x for x in before if x[0] != 71])   # nothing but decorations added

    def test_the_decorations_go_with_the_annotations(self):
        out, _ = self.run_on(self.asm(VS, 'vs2')); assert out is not None
        seq = [op for op, _ in ops(out)]
        last_ann = max(i for i, op in enumerate(seq) if op == 71); first_type = seq.index(19)   # OpTypeVoid
        self.assertLess(last_ann, first_type)

    def test_a_fragment_shader_is_left_alone(self):
        data = self.asm(FS, 'fs'); self.assertFalse(self.wanted(data)); self.assertIsNone(self.run_on(data)[0])

    def test_a_marked_module_is_not_marked_again(self):
        out, _ = self.run_on(self.asm(VS, 'vs3')); assert out is not None
        again, marked = self.run_on(out); self.assertIsNone(again); self.assertEqual(marked, 0)

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR (a game\'s packed spv folder) not set')
    def test_a_games_shaders(self):   # each rewritten module must pass spirv-val
        d = Path(os.environ['DM_SPV_DIR']); n = 0
        for f in sorted(d.glob('*.spv')):
            data = f.read_bytes()
            if not self.wanted(data): continue
            out, _ = self.run_on(data)
            if out is None: continue
            self.valid(out, f.stem); n += 1
        print(f'{n} modules rewritten in {d}')


if __name__ == '__main__':
    unittest.main()
