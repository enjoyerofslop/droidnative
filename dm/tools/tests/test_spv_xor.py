"""dm/android/spv_xor.h (Maxwell's butterfly shuffle, the translator's Shuffle by the lane ID ^ a mask, as ShuffleXor by the mask: the Adreno 730's driver returns
garbage from that Shuffle), built for the PC and run on modules assembled with the NDK's spirv-as; spirv-val checks each result, and a guard after the words it
asked for checks that it writes no further. spv_wide must still rewrite a module after it. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there: each rewritten one must pass spirv-val, and no module spv_wide rewrote as
translated may be one it leaves after spv_xor."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spv_readonly import NDK, HOST, EXE, REPO   # noqa: E402
from test_spv_wide import FS, HEAD, TAIL, idx, ADRENO_830, DONE, KEPT   # noqa: E402

GUARD = 0xa5a5a5a5
SPX_N = 5   # the scratch's arrays (spv_xor.h)

# A compute shader as the translator writes SHFL.BFLY: a helper that loads the lane ID, bitcasts it to float and keeps it in a Function variable, loads it back as
# an int, XORs it with the mask parameter, keeps that in another variable and shuffles to it (Final Fantasy Resonance's particle simulation, f3c5ced35cb619d0)
COMPUTE = '''OpCapability Shader
OpCapability GroupNonUniform
OpCapability GroupNonUniformShuffle
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main" %lane %gid
OpExecutionMode %main LocalSize 64 1 1
OpDecorate %lane BuiltIn SubgroupLocalInvocationId
OpDecorate %gid BuiltIn GlobalInvocationId
OpDecorate %ra ArrayStride 4
OpMemberDecorate %ob 0 Offset 0
OpDecorate %ob Block
OpDecorate %out DescriptorSet 0
OpDecorate %out Binding 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%u32 = OpTypeInt 32 0
%i32 = OpTypeInt 32 1
%v3u = OpTypeVector %u32 3
%pu = OpTypePointer Input %u32
%pv3u = OpTypePointer Input %v3u
%pfi = OpTypePointer Function %i32
%pff = OpTypePointer Function %f32
%bft = OpTypeFunction %i32 %pfi %pfi
%ra = OpTypeRuntimeArray %i32
%ob = OpTypeStruct %ra
%pob = OpTypePointer StorageBuffer %ob
%psi = OpTypePointer StorageBuffer %i32
%lane = OpVariable %pu Input
%gid = OpVariable %pv3u Input
%out = OpVariable %pob StorageBuffer
%scope = OpConstant %u32 3
%i0 = OpConstant %i32 0
%i1 = OpConstant %i32 1
%i2 = OpConstant %i32 2
%main = OpFunction %void None %fn
%ml = OpLabel
%a = OpVariable %pfi Function
%m1 = OpVariable %pfi Function
%a2 = OpVariable %pfi Function
%m2 = OpVariable %pfi Function
%g = OpLoad %v3u %gid
%gx = OpCompositeExtract %u32 %g 0
%gi = OpBitcast %i32 %gx
OpStore %a %gi
OpStore %m1 %i1
%r1 = OpFunctionCall %i32 %bf %a %m1
%s1 = OpIAdd %i32 %gi %r1
OpStore %a2 %s1
OpStore %m2 %i2
%r2 = OpFunctionCall %i32 %bf %a2 %m2
%s2 = OpIAdd %i32 %s1 %r2
%p = OpAccessChain %psi %out %i0 %gx
OpStore %p %s2
OpReturn
OpFunctionEnd
%bf = OpFunction %i32 None %bft
%pv = OpFunctionParameter %pfi
%pb = OpFunctionParameter %pfi
%bl = OpLabel
%vl = OpVariable %pff Function
%vs = OpVariable %pfi Function
%l0 = OpLoad %u32 %lane
%l1 = OpBitcast %f32 %l0
OpStore %vl %l1
%l2 = OpLoad %f32 %vl
%l3 = OpBitcast %i32 %l2
%b0 = OpLoad %i32 %pb
%x0 = OpBitwiseXor %i32 %l3 %b0
OpStore %vs %x0
%v0 = OpLoad %i32 %pv
%v1 = OpBitcast %f32 %v0
%t0 = OpLoad %i32 %vs
%t1 = OpBitcast %u32 %t0
%sh = OpGroupNonUniformShuffle %f32 %scope %v1 %t1
%rr = OpBitcast %i32 %sh
OpReturnValue %rr
OpFunctionEnd
'''
# The same with the lane variable stored a second time (it might hold another value at the load): left as it is
TWO_STORES = COMPUTE.replace('OpStore %vl %l1\n', 'OpStore %vl %l1\n%l1b = OpBitcast %f32 %l0\nOpStore %vl %l1b\n')
# The mask loaded in the block before the shuffle's (the helper split in two): left as it is, as spv_xor only uses a mask from the shuffle's own block
OTHER_BLOCK = COMPUTE.replace('%b0 = OpLoad %i32 %pb\n%x0 = OpBitwiseXor %i32 %l3 %b0\n', '%b0 = OpLoad %i32 %pb\nOpBranch %b2\n%b2 = OpLabel\n%x0 = OpBitwiseXor %i32 %l3 %b0\n')
# The index the lane ID + the mask (Maxwell's SHFL.DOWN as written directly): no XOR, left as it is
DOWN = COMPUTE.replace('%x0 = OpBitwiseXor %i32 %l3 %b0', '%x0 = OpIAdd %i32 %l3 %b0')
# test_spv_wide's fragment shader with SHFL.IDX alone (no butterfly): nothing for spv_xor
IDX_ONLY = HEAD + idx(0, 0) + idx(1, 3) + idx(2, 1) + idx(3, 2) + TAIL


@unittest.skipUnless(NDK, 'the NDK is not installed')
class SpvXor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val, cls.spv_dis = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}', tools / f'spirv-dis{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'x.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_xor.h"\n#include "spv_wide.h"\n'
                       f'{export} size_t run(const uint32_t *w, size_t n, uint32_t *s, uint32_t *o, size_t cap, size_t *need, int *ns) {{ return spv_xor(w, n, s, o, cap, need, ns); }}\n'
                       f'{export} int wanted(const uint32_t *w, size_t n) {{ return spv_xor_wanted(w, n); }}\n'
                       f'{export} size_t wide(const uint32_t *w, size_t n, uint32_t sg, uint32_t *s, uint32_t *o, size_t cap, size_t *need, int *what) '
                       f'{{ return spv_wide(w, n, sg, s, o, cap, need, what); }}\n'
                       f'{export} uint32_t wide_wanted(const uint32_t *w, size_t n, uint32_t sg) {{ return spv_wide_wanted(w, n, sg); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone, as test_spv_wide
            subprocess.run([cls.bin / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-Werror', '-I', REPO / 'dm/android', '-c', src,
                            '-o', cls.tmp / 'x.obj'], check=True)
            subprocess.run([cls.bin / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "x.dll"}', str(cls.tmp / 'x.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'x.dll'))
        else:   # the system's clang, as test_spv_wide
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or cls.bin / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'x.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'x.so'))
        cls.lib.run.restype = ctypes.c_size_t; cls.lib.wide.restype = ctypes.c_size_t

    def asm(self, text, name):
        p = self.tmp / f'{name}.spvasm'; p.write_text(text)
        subprocess.run([self.spv_as, '--target-env', 'vulkan1.1', p, '-o', self.tmp / f'{name}.spv'], check=True)
        return (self.tmp / f'{name}.spv').read_bytes()

    def valid(self, data, name):
        p = self.tmp / f'{name}.out.spv'; p.write_bytes(data)
        r = subprocess.run([self.spv_val, '--target-env', 'vulkan1.1', p], capture_output=True, text=True)
        return r.returncode == 0, r.stderr

    def dis(self, data, name):
        p = self.tmp / f'{name}.d.spv'; p.write_bytes(data)
        return subprocess.run([self.spv_dis, '--raw-id', p], capture_output=True, text=True, check=True).stdout

    def xor(self, data):   # → (the rewritten module or None, the shuffles rewritten)
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data)
        s = (ctypes.c_uint32 * (SPX_N * w[3]))(); need = ctypes.c_size_t(); ns = ctypes.c_int()
        self.assertEqual(self.lib.run(w, n, s, None, 0, ctypes.byref(need), ctypes.byref(ns)), 0)
        if not need.value: return None, 0
        self.assertTrue(self.lib.wanted(w, n))   # the replay's pre-check never passes over a module that needs it
        cap = need.value; o = (ctypes.c_uint32 * (cap + 64))(*[GUARD] * (cap + 64))
        k = self.lib.run(w, n, s, o, cap, ctypes.byref(need), ctypes.byref(ns))
        self.assertTrue(0 < k <= cap)
        self.assertTrue(all(o[i] == GUARD for i in range(cap, cap + 64)))
        return bytes(o)[:4 * k], ns.value

    def wide(self, data, stages=ADRENO_830):   # → spv_wide's SPV_WIDE_* bits, and its result
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data)
        s = (ctypes.c_uint32 * (2 * w[3]))(); need = ctypes.c_size_t(); what = ctypes.c_int()
        self.lib.wide(w, n, stages, s, None, 0, ctypes.byref(need), ctypes.byref(what))
        if not need.value: return what.value, None
        o = (ctypes.c_uint32 * need.value)(); k = self.lib.wide(w, n, stages, s, o, need.value, ctypes.byref(need), ctypes.byref(what))
        return what.value, bytes(o)[:4 * k] if k else None

    def test_translated_helper_becomes_shufflexor(self):
        out, ns = self.xor(self.asm(COMPUTE, 'compute'))
        self.assertIsNotNone(out); self.assertEqual(ns, 1)
        ok, err = self.valid(out, 'compute'); self.assertTrue(ok, err)
        d = self.dis(out, 'compute')
        self.assertNotIn('OpGroupNonUniformShuffle ', d); self.assertIn('OpGroupNonUniformShuffleXor', d)
        # the mask is the helper's own parameter, loaded as an int and bitcast to uint
        lines = d.split('\n'); sx = next(x for x in lines if 'OpGroupNonUniformShuffleXor' in x); mask = sx.split()[-1]
        cast = next(x for x in lines if x.strip().startswith(f'{mask} = OpBitcast'))
        src = cast.split()[-1]; self.assertTrue(any(x.strip().startswith(f'{src} = OpLoad') for x in lines))

    def test_direct_butterfly_with_a_uint_mask(self):   # test_spv_wide's: the lane ID loaded as a uint and XORed with a constant, no cast needed
        out, ns = self.xor(self.asm(FS, 'fs'))
        self.assertIsNotNone(out); self.assertEqual(ns, 1)
        ok, err = self.valid(out, 'fs'); self.assertTrue(ok, err)
        d = self.dis(out, 'fs'); self.assertEqual(d.count('OpGroupNonUniformShuffleXor'), 1); self.assertEqual(d.count('OpGroupNonUniformShuffle '), 1)   # the IDX one stays

    def test_spv_wide_still_rewrites_after_it(self):   # a ShuffleXor is no reason for spv_wide to leave the module: its lanes 32 and up must still be fixed
        before, _ = self.wide(self.asm(FS, 'fsw'))
        self.assertEqual(before, DONE)
        out, _ = self.xor(self.asm(FS, 'fsw2'))
        after, res = self.wide(out)
        self.assertEqual(after, DONE); self.assertIsNotNone(res)
        ok, err = self.valid(res, 'fsw2'); self.assertTrue(ok, err)
        self.assertIn('OpGroupNonUniformShuffleXor', self.dis(res, 'fsw2'))

    def test_left_as_translated(self):
        for name, text in (('two_stores', TWO_STORES), ('other_block', OTHER_BLOCK), ('down', DOWN), ('idx', IDX_ONLY)):
            with self.subTest(name):
                out, ns = self.xor(self.asm(text, name))
                self.assertIsNone(out); self.assertEqual(ns, 0)

    def test_a_games_modules(self):   # DM_SPV_DIR: each rewritten module passes spirv-val; spv_wide leaves none after it that it rewrote before
        d = os.environ.get('DM_SPV_DIR')
        if not d: self.skipTest('DM_SPV_DIR is not set')
        n = done = sites = bad = lost = 0
        for p in sorted(Path(d).glob('*.spv')):
            data = p.read_bytes()
            if len(data) % 4 or len(data) < 20: continue
            n += 1; out, ns = self.xor(data)
            if not out: continue
            done += 1; sites += ns
            ok, err = self.valid(out, 'corpus')
            if not ok: bad += 1; print(p.name, err[:200]); continue
            if self.wide(data)[0] == DONE and self.wide(out)[0] == KEPT: lost += 1; print(p.name, 'spv_wide left it after spv_xor')
        print(f'{n} modules, {done} rewritten ({sites} butterfly shuffles), {bad} invalid, {lost} left by spv_wide after it')
        self.assertEqual(bad, 0); self.assertEqual(lost, 0)


if __name__ == '__main__':
    unittest.main()
