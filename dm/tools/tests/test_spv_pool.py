"""dm/android/spv_pool.h (NVN2's texture and sampler pools by ID moved into the Vulkan replay's pool set, with the reads' marks), built for the PC with the Android NDK's
clang and run on modules assembled with its spirv-as; spirv-val checks the result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there with pool arrays (each result must pass spirv-val); DM_SPV_POOL_MAX caps how many."""
import ctypes
import faulthandler
import json
import os
import re
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

from test_spv_readonly import NDK, HOST, EXE   # noqa: E402

REPO = Path(__file__).resolve().parents[3]
SCRATCH = int(re.search(r'#define SPV_POOL_SCRATCH (\d+)', (REPO / 'dm/android/spv_pool.h').read_text()).group(1))   # scratch words per id, as spv_pool.h says
N = 65536
faulthandler.enable()   # a crash in the library prints the Python stack (the Linux runner's exit 139 said nothing more)

FS = '''OpCapability Shader
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %uv %out %hnd
OpExecutionMode %main OriginUpperLeft
OpDecorate %uv Location 0
OpDecorate %hnd Location 1
OpDecorate %hnd Flat
OpDecorate %out Location 0
OpDecorate %t2d DescriptorSet 1
OpDecorate %t2d Binding 13
OpDecorate %smp DescriptorSet 1
OpDecorate %smp Binding 1048589
OpDecorate %t2ds DescriptorSet 1
OpDecorate %t2ds Binding 1052685
OpDecorate %t2da DescriptorSet 1
OpDecorate %t2da Binding 2101261
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%v2 = OpTypeVector %f32 2
%v4 = OpTypeVector %f32 4
%u32 = OpTypeInt 32 0
%i32 = OpTypeInt 32 1
%bool = OpTypeBool
%c20 = OpConstant %u32 1048576
%c12 = OpConstant %u32 4096
%cmask = OpConstant %u32 1048575
%cmax = OpConstant %u32 4095
%csh = OpConstant %u32 20
%i0 = OpConstant %i32 0
%i1 = OpConstant %i32 1
%i4 = OpConstant %i32 4
%f0 = OpConstant %f32 0
%f05 = OpConstant %f32 0.5
%img = OpTypeImage %f32 2D 0 0 0 1 Unknown
%imga = OpTypeImage %f32 2D 0 1 0 1 Unknown
%imgd = OpTypeImage %f32 2D 1 0 0 1 Unknown
%simg = OpTypeSampledImage %img
%simga = OpTypeSampledImage %imga
%simgd = OpTypeSampledImage %imgd
%sam = OpTypeSampler
%aimg = OpTypeArray %img %c20
%aimga = OpTypeArray %imga %c20
%aimgd = OpTypeArray %imgd %c20
%asam = OpTypeArray %sam %c12
%paimg = OpTypePointer UniformConstant %aimg
%paimga = OpTypePointer UniformConstant %aimga
%paimgd = OpTypePointer UniformConstant %aimgd
%pasam = OpTypePointer UniformConstant %asam
%pimg = OpTypePointer UniformConstant %img
%pimga = OpTypePointer UniformConstant %imga
%pimgd = OpTypePointer UniformConstant %imgd
%psam = OpTypePointer UniformConstant %sam
%t2d = OpVariable %paimg UniformConstant
%t2da = OpVariable %paimga UniformConstant
%t2ds = OpVariable %paimgd UniformConstant
%smp = OpVariable %pasam UniformConstant
%pin2 = OpTypePointer Input %v2
%pinu = OpTypePointer Input %u32
%pout = OpTypePointer Output %v4
%v3 = OpTypeVector %f32 3
%uv = OpVariable %pin2 Input
%hnd = OpVariable %pinu Input
%out = OpVariable %pout Output
%main = OpFunction %void None %fn
%l0 = OpLabel
%h = OpLoad %u32 %hnd
%tid = OpBitwiseAnd %u32 %h %cmask
%sid0 = OpShiftRightLogical %u32 %h %csh
%tc = OpExtInst %u32 %glsl UMin %tid %cmask
%sc = OpExtInst %u32 %glsl UMin %sid0 %cmax
%ti = OpBitcast %i32 %tc
%si = OpBitcast %i32 %sc
%c = OpLoad %v2 %uv
%pa = OpAccessChain %pimg %t2d %ti
%ia = OpLoad %img %pa
%pb = OpAccessChain %psam %smp %si
%sb = OpLoad %sam %pb
%s1 = OpSampledImage %simg %ia %sb
%r1 = OpImageSampleImplicitLod %v4 %s1 %c
%pd = OpAccessChain %pimgd %t2ds %tc
%id = OpLoad %imgd %pd
%s2 = OpSampledImage %simgd %id %sb
%r2 = OpImageSampleDrefExplicitLod %f32 %s2 %c %f05 Lod %f0
%cond = OpFOrdLessThan %bool %r2 %f05
OpSelectionMerge %l2 None
OpBranchConditional %cond %l1 %l2
%l1 = OpLabel
%pc = OpAccessChain %pimga %t2da %ti
%ic = OpLoad %imga %pc
%s3 = OpSampledImage %simga %ic %sb
%c3 = OpCompositeConstruct %v3 %f0 %f0 %f0
%r3 = OpImageSampleImplicitLod %v4 %s3 %c3
%KILL%
OpBranch %l2
%l2 = OpLabel
%r = OpPhi %v4 %r1 %l0 %r3 %l1
OpBranch %lh
%lh = OpLabel
%i = OpPhi %i32 %i0 %l2 %inext %lc
%acc = OpPhi %v4 %r %l2 %acc2 %lc
%pl = OpAccessChain %pimg %t2d %i
%il = OpLoad %img %pl
%sl = OpSampledImage %simg %il %sb
%rl = OpImageSampleExplicitLod %v4 %sl %c Lod %f0
%lt = OpSLessThan %bool %i %i4
OpLoopMerge %lm %lc None
OpBranchConditional %lt %lb %lm
%lb = OpLabel
OpBranch %lc
%lc = OpLabel
%acc2 = OpFAdd %v4 %acc %rl
%inext = OpIAdd %i32 %i %i1
OpBranch %lh
%lm = OpLabel
OpStore %out %acc
OpReturn
OpFunctionEnd
'''


def words(data) -> list[int]:
    return list(struct.unpack(f'<{len(data) // 4}I', data))


def instrs(data):
    w = words(data); i = 5
    while i < len(w):
        n = w[i] >> 16; yield w[i] & 0xffff, w[i:i + n]; i += n


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvPool(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        bin_ = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'p.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text('#include "spv_pool.h"\n'
                       f'{export} size_t run(const uint32_t *w, size_t n, uint32_t nn, int mark, uint32_t *s, uint32_t *o, size_t cap, size_t *need, int *info) {{\n'
                       '    struct spv_pool_cfg c = {nn, 4, 0, 1, 2, 3, mark, 1}; return spv_pool(w, n, &c, s, o, cap, need, info); }\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone
            subprocess.run([bin_ / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-I', REPO / 'dm/android', '-c', src, '-o', cls.tmp / 'p.obj'], check=True)
            subprocess.run([bin_ / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "p.dll"}', str(cls.tmp / 'p.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'p.dll'))
        else:   # the system's clang, as test_spv_limits.py: on a Mac the NDK's makes x86_64 libraries without the macOS SDK to link them
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or bin_ / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'p.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'p.so'))
        u32p = ctypes.POINTER(ctypes.c_uint32)   # every argument typed: a size_t passed as an untyped Python int is a 32-bit int, its register's upper half garbage on x86-64 Linux
        cls.lib.run.argtypes = [u32p, ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int, u32p, u32p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_int)]
        cls.lib.run.restype = ctypes.c_size_t

    def run_on(self, data, mark=1):
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); bound = w[3]
        s = (ctypes.c_uint32 * (SCRATCH * bound))(); need = ctypes.c_size_t(); info = ctypes.c_int()
        k = self.lib.run(w, n, N, mark, s, None, 0, ctypes.byref(need), ctypes.byref(info))   # the size it asks for, then the rewrite
        if not need.value: return None, info.value
        o = (ctypes.c_uint32 * need.value)()
        k = self.lib.run(w, n, N, mark, s, o, need.value, ctypes.byref(need), ctypes.byref(info))
        return (bytes(o)[:4 * k] if k else None), info.value

    def val(self, data, name):
        p = self.tmp / name; p.write_bytes(data)
        env = 'vulkan1.1spv1.4' if words(data)[1] >= 0x10400 else 'vulkan1.1'   # a module the translator made SPIR-V 1.4 keeps its version
        r = subprocess.run([self.spv_val, '--target-env', env, p], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def asm(self, text, name):
        p = self.tmp / f'{name}.spvasm'; p.write_text(text)
        subprocess.run([self.spv_as, '--target-env', 'vulkan1.1', p, '-o', self.tmp / f'{name}.spv'], check=True)
        return (self.tmp / f'{name}.spv').read_bytes()

    def decor(self, data):   # id → {decoration: operand}
        out = {}
        for op, ins in instrs(data):
            if op == 71: out.setdefault(ins[1], {})[ins[2]] = ins[3] if len(ins) > 3 else True
        return out

    def test_fragment_shader(self):
        out, info = self.run_on(self.asm(FS.replace('%KILL%\n', ''), 'fs'))
        self.assertIsNotNone(out)
        self.assertEqual(info, 1 | 2 | 4 | 8 | 16 | 32)   # images, samplers, comparison samplers, marks, early tests, a mark in a loop header
        self.val(out, 'fs_out.spv')
        d = self.decor(out)
        sets = {(v[34], v[33]) for v in d.values() if 34 in v and 33 in v}
        self.assertEqual(sets, {(4, 0), (4, 1), (4, 2), (4, 3)})
        self.assertEqual(sum(1 for v in d.values() if v.get(34) == 4 and v.get(33) == 0), 3, 'the three image arrays alias binding 0')
        self.assertGreaterEqual(sum(1 for v in d.values() if 5300 in v), 12)
        modes = [ins[2] for op, ins in instrs(out) if op == 16]
        self.assertIn(9, modes)
        lens = {ins[3] for op, ins in instrs(out) if op == 43 and ins[3] in (N, N - 1)}
        self.assertEqual(lens, {N, N - 1})

    def test_discard_keeps_late_tests(self):
        out, info = self.run_on(self.asm(FS.replace('%KILL%\nOpBranch %l2\n', 'OpKill\n').replace('%r = OpPhi %v4 %r1 %l0 %r3 %l1', '%r = OpCopyObject %v4 %r1'), 'fsk'))
        self.assertIsNotNone(out); self.assertEqual(info & 16, 0); self.assertTrue(info & 8)
        self.val(out, 'fsk_out.spv')
        self.assertNotIn(9, [ins[2] for op, ins in instrs(out) if op == 16])

    def test_no_marks(self):
        out, info = self.run_on(self.asm(FS.replace('%KILL%\n', ''), 'fsn'), mark=0)
        self.assertIsNotNone(out); self.assertEqual(info & (8 | 16 | 32), 0)
        self.val(out, 'fsn_out.spv')

    def test_left_alone(self):
        data = self.asm(FS.replace('%KILL%\n', '').replace('%c20 = OpConstant %u32 1048576', '%c20 = OpConstant %u32 32').replace('%c12 = OpConstant %u32 4096', '%c12 = OpConstant %u32 32'), 'fs32')
        self.assertEqual(self.run_on(data), (None, 0), '32-element slot arrays are no pools')

    def test_whole_array_load_refused(self):
        data = self.asm(FS.replace('%KILL%\n', '%all = OpLoad %aimg %t2d\n'), 'fsall')
        self.assertEqual(self.run_on(data), (None, 64))

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR not set')
    def test_a_games_pool_shaders(self):
        d = Path(os.environ['DM_SPV_DIR']); cap = int(os.environ.get('DM_SPV_POOL_MAX', '0') or 0)
        n = ok = fail = early = loop = 0; refused = []
        for rj in sorted(d.glob('*.res.json')):
            r = json.loads(rj.read_text(encoding='utf-8'))
            if not any(t.get('handle') == 0x40000000 and t.get('array', 1) > 32 for t in r.get('textures', [])): continue
            for sp in (d / (rj.name[:-9] + '.spv'), d / (rj.name[:-9] + '.z.spv')):
                if not sp.is_file(): continue
                n += 1; out, info = self.run_on(sp.read_bytes())
                if not out: fail += 1; refused.append(sp.name); continue
                ok += 1; early += bool(info & 16); loop += bool(info & 32)
                with self.subTest(module=sp.name): self.val(out, 'game.spv')
            if cap and n >= cap: break
        print(f'{n} modules with pool arrays: {ok} rewritten ({early} with early tests added, {loop} with a mark in a loop header), {fail} left: {refused[:8]}')
        self.assertTrue(n); self.assertEqual(fail, 0)


if __name__ == '__main__':
    unittest.main()
