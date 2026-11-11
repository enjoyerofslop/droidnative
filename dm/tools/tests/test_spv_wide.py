"""dm/android/spv_wide.h (Maxwell's 32-lane warps as 32-lane parts of a wider subgroup: fragment and compute shaders on the Adreno 830, whose subgroups have 64
lanes; mesh and task modules are left), built for the PC and run on modules assembled with the NDK's spirv-as; spirv-val checks each result, and a guard
after the words it asked for checks that it writes no further. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there with the Adreno 830's stages (each result must pass spirv-val).
With DM_TEST_SERIAL=<adb serial>, dm/android/tests/t_quad_shuffle.c is built for Android and run on that device with a fragment shader whose quad shuffles are
the translator's SHFL helpers: rewritten, every pixel must read the right lanes of its quad; as translated, on a subgroup over 32 lanes, the pixels of lanes
32 and up must not (what the rewrite is for). It also runs dm/android/tests/t_warp_reduce.c with test_spv_narrow's compute shader of whole-warp
reductions: rewritten, its sum, minimum, maximum and OR must be the workgroup's; as translated, on a subgroup over 32 lanes, not all of them."""
import ctypes
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spv_readonly import NDK, HOST, EXE, REPO   # noqa: E402
from test_spv_limits import DEV_VS, instructions   # noqa: E402

DONE, KEPT, STAGE = 1, 2, 4   # SPV_WIDE_*
FRAGMENT, COMPUTE, MESH = 0x10, 0x20, 0x80   # stage bits, as spv_wide_wanted gives them
ADRENO_650, ADRENO_830, FOLD = 0x20, 0x30, 0xf0   # subgroupSupportedStages: compute; fragment and compute; fragment, compute, task and mesh (the Z Fold's)
GUARD = 0xa5a5a5a5

# A fragment shader as the translator writes Maxwell's warp instructions for a 32-lane host: SHFL.IDX and SHFL.BFLY within the quad (mask 0x1c03) as Ryujinx's
# Shuffle and ShuffleXor helpers (the lane ID & the segment mask, valid up to the clamp), BALLOT as the ballot's first word, a mask's component 0 through an
# access chain (an int constant, as Ryujinx's Load), VOTE as all / any / all-equal of a predicate, and the subgroup size
HEAD = '''OpCapability Shader
OpCapability GroupNonUniform
OpCapability GroupNonUniformBallot
OpCapability GroupNonUniformShuffle
OpCapability GroupNonUniformVote
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %fc %lane %lt %size %out
OpExecutionMode %main OriginUpperLeft
OpDecorate %fc BuiltIn FragCoord
OpDecorate %lane BuiltIn SubgroupLocalInvocationId
OpDecorate %lane Flat
OpDecorate %lt BuiltIn SubgroupLtMask
OpDecorate %lt Flat
OpDecorate %size BuiltIn SubgroupSize
OpDecorate %size Flat
OpDecorate %out Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%bool = OpTypeBool
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%u32 = OpTypeInt 32 0
%i32 = OpTypeInt 32 1
%v4u = OpTypeVector %u32 4
%pi = OpTypePointer Input %v4
%pu = OpTypePointer Input %u32
%pv4u = OpTypePointer Input %v4u
%fc = OpVariable %pi Input
%lane = OpVariable %pu Input
%lt = OpVariable %pv4u Input
%size = OpVariable %pu Input
%po = OpTypePointer Output %v4u
%out = OpVariable %po Output
%scope = OpConstant %u32 3
%u0 = OpConstant %u32 0
%u1 = OpConstant %u32 1
%u2 = OpConstant %u32 2
%u3 = OpConstant %u32 3
%u8 = OpConstant %u32 8
%u31 = OpConstant %u32 31
%quad = OpConstant %u32 7171
%i0 = OpConstant %i32 0
%k1 = OpConstant %u32 2654435761
%k2 = OpConstant %u32 2246822519
%k3 = OpConstant %u32 739982445
%s15 = OpConstant %u32 15
%s12 = OpConstant %u32 12
%main = OpFunction %void None %fn
%l = OpLabel
%c = OpLoad %v4 %fc
%cx = OpCompositeExtract %f32 %c 0
%cy = OpCompositeExtract %f32 %c 1
%x = OpConvertFToU %u32 %cx
%y = OpConvertFToU %u32 %cy
%a = OpIMul %u32 %x %k1
%b = OpIMul %u32 %y %k2
%h0 = OpBitwiseXor %u32 %a %b
%t1 = OpShiftRightLogical %u32 %h0 %s15
%h1 = OpBitwiseXor %u32 %h0 %t1
%h2 = OpIMul %u32 %h1 %k3
%t2 = OpShiftRightLogical %u32 %h2 %s12
%h = OpBitwiseXor %u32 %h2 %t2
%f = OpBitcast %f32 %h
%L = OpLoad %u32 %lane
%clamp = OpBitwiseAnd %u32 %quad %u31
%m8 = OpShiftRightLogical %u32 %quad %u8
%seg = OpBitwiseAnd %u32 %m8 %u31
%nseg = OpNot %u32 %seg
%min = OpBitwiseAnd %u32 %L %seg
%cl = OpBitwiseAnd %u32 %clamp %nseg
%max = OpBitwiseOr %u32 %cl %min
'''
# Shuffle (SHFL.IDX) of quad lane j, or ShuffleXor (SHFL.BFLY) by j, into %r<n>
def idx(n, j): return (f'%ix{n} = OpBitwiseAnd %u32 %u{j} %nseg\n%src{n} = OpBitwiseOr %u32 %ix{n} %min\n%ok{n} = OpULessThanEqual %bool %src{n} %max\n'
                       f'%sh{n} = OpGroupNonUniformShuffle %f32 %scope %f %src{n}\n%r{n} = OpSelect %f32 %ok{n} %sh{n} %f\n%o{n} = OpBitcast %u32 %r{n}\n')
def bfly(n, j): return (f'%src{n} = OpBitwiseXor %u32 %L %u{j}\n%ok{n} = OpULessThanEqual %bool %src{n} %max\n'
                        f'%sh{n} = OpGroupNonUniformShuffle %f32 %scope %f %src{n}\n%r{n} = OpSelect %f32 %ok{n} %sh{n} %f\n%o{n} = OpBitcast %u32 %r{n}\n')
TAIL = '%o = OpCompositeConstruct %v4u %o0 %o1 %o2 %o3\nOpStore %out %o\nOpReturn\nOpFunctionEnd\n'
# t_quad_shuffle's four: quad lane 0, quad lane 3, the horizontal neighbour, the vertical one
DEV_FS = (HEAD.replace(' %lt %size %out', ' %out').replace('OpDecorate %lt BuiltIn SubgroupLtMask\nOpDecorate %lt Flat\nOpDecorate %size BuiltIn SubgroupSize\nOpDecorate %size Flat\n', '')
          .replace('%lt = OpVariable %pv4u Input\n%size = OpVariable %pu Input\n', '') + idx(0, 0) + idx(1, 3) + bfly(2, 1) + bfly(3, 2) + TAIL)
VOTES = '''%p = OpULessThan %bool %L %u2
%bal = OpGroupNonUniformBallot %v4u %scope %p
%bw = OpCompositeExtract %u32 %bal 0
%ltp = OpAccessChain %pu %lt %i0
%ltw = OpLoad %u32 %ltp
%below = OpBitwiseAnd %u32 %bw %ltw
%al = OpGroupNonUniformAll %bool %scope %p
%an = OpGroupNonUniformAny %bool %scope %p
%eq = OpGroupNonUniformAllEqual %bool %scope %p
%v0 = OpSelect %u32 %al %u1 %u0
%v1 = OpSelect %u32 %an %u2 %u0
%v2 = OpSelect %u32 %eq %u3 %u0
%v01 = OpBitwiseOr %u32 %v0 %v1
%v = OpBitwiseOr %u32 %v01 %v2
%sz = OpLoad %u32 %size
%o2 = OpBitwiseOr %u32 %below %sz
%o3 = OpBitwiseOr %u32 %v %L
'''
FS = HEAD + idx(0, 0) + bfly(1, 1) + VOTES + TAIL
# The ballot, a mask and the votes alone: as translated they read no lane ID, which the rewrite then adds
BALLOT_FS = '''OpCapability Shader
OpCapability GroupNonUniform
OpCapability GroupNonUniformBallot
OpCapability GroupNonUniformVote
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %fc %lt %out
OpExecutionMode %main OriginUpperLeft
OpDecorate %fc BuiltIn FragCoord
OpDecorate %lt BuiltIn SubgroupLtMask
OpDecorate %lt Flat
OpDecorate %out Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%bool = OpTypeBool
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%u32 = OpTypeInt 32 0
%v4u = OpTypeVector %u32 4
%pi = OpTypePointer Input %v4
%pu = OpTypePointer Input %u32
%pv4u = OpTypePointer Input %v4u
%fc = OpVariable %pi Input
%lt = OpVariable %pv4u Input
%po = OpTypePointer Output %v4u
%out = OpVariable %po Output
%scope = OpConstant %u32 3
%u0 = OpConstant %u32 0
%u1 = OpConstant %u32 1
%half = OpConstant %f32 64
%main = OpFunction %void None %fn
%l = OpLabel
%c = OpLoad %v4 %fc
%cx = OpCompositeExtract %f32 %c 0
%p = OpFOrdLessThan %bool %cx %half
%bal = OpGroupNonUniformBallot %v4u %scope %p
%bw = OpCompositeExtract %u32 %bal 0
%ltp = OpAccessChain %pu %lt %u0
%ltw = OpLoad %u32 %ltp
%an = OpGroupNonUniformAny %bool %scope %p
%v = OpSelect %u32 %an %u1 %u0
%o = OpCompositeConstruct %v4u %bw %ltw %v %u0
OpStore %out %o
OpReturn
OpFunctionEnd
'''


# Votes alone, AllEqual the most: each becomes the most words a use can (SPV_WIDE_SITE), in a module that lacks every declaration the rewrite adds (the
# ballot capability, uvec4, the lane ID and its pointer type): the largest result for its input
VOTES_HEAD = '''OpCapability Shader
OpCapability GroupNonUniform
OpCapability GroupNonUniformVote
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %fc %out
OpExecutionMode %main OriginUpperLeft
OpDecorate %fc BuiltIn FragCoord
OpDecorate %out Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%bool = OpTypeBool
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%u32 = OpTypeInt 32 0
%pi = OpTypePointer Input %v4
%fc = OpVariable %pi Input
%po = OpTypePointer Output %u32
%out = OpVariable %po Output
%scope = OpConstant %u32 3
%u0 = OpConstant %u32 0
%u1 = OpConstant %u32 1
%half = OpConstant %f32 64
%main = OpFunction %void None %fn
%l = OpLabel
%c = OpLoad %v4 %fc
%cx = OpCompositeExtract %f32 %c 0
%p = OpFOrdLessThan %bool %cx %half
%a0 = OpGroupNonUniformAny %bool %scope %p
%s0 = OpSelect %u32 %a0 %u1 %u0
'''
def votes_fs(n): return (VOTES_HEAD + ''.join(f'%e{i} = OpGroupNonUniformAllEqual %bool %scope %p\n%q{i} = OpSelect %u32 %e{i} %u1 %u0\n'
                                              f'%s{i + 1} = OpIAdd %u32 %s{i} %q{i}\n' for i in range(n)) + f'OpStore %out %s{n}\nOpReturn\nOpFunctionEnd\n')
# A compute shader's warp-aggregated count as the translator writes it for a 32-lane host (as Ocarina of Time's 21d9f83e6027c565 does): BALLOT as the ballot's first word,
# the lane's rank from the LT mask's component 0, and SHFL.IDX from the warp's leader
AGG_CS = '''OpCapability Shader
OpCapability GroupNonUniform
OpCapability GroupNonUniformBallot
OpCapability GroupNonUniformShuffle
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main" %lane %lt
OpExecutionMode %main LocalSize 64 1 1
OpDecorate %lane BuiltIn SubgroupLocalInvocationId
OpDecorate %lt BuiltIn SubgroupLtMask
%void = OpTypeVoid
%fn = OpTypeFunction %void
%bool = OpTypeBool
%u32 = OpTypeInt 32 0
%i32 = OpTypeInt 32 1
%v4u = OpTypeVector %u32 4
%pu = OpTypePointer Input %u32
%pv4u = OpTypePointer Input %v4u
%lane = OpVariable %pu Input
%lt = OpVariable %pv4u Input
%scope = OpConstant %u32 3
%u31 = OpConstant %u32 31
%i0 = OpConstant %i32 0
%true = OpConstantTrue %bool
%main = OpFunction %void None %fn
%l = OpLabel
%L = OpLoad %u32 %lane
%bal = OpGroupNonUniformBallot %v4u %scope %true
%bx = OpCompositeExtract %u32 %bal 0
%ltp = OpAccessChain %pu %lt %i0
%ltm = OpLoad %u32 %ltp
%below = OpBitwiseAnd %u32 %bx %ltm
%rank = OpBitCount %u32 %below
%lead = OpBitwiseAnd %u32 %bx %u31
%s = OpGroupNonUniformShuffle %u32 %scope %rank %lead
OpReturn
OpFunctionEnd
'''
# A compute shader with SHFL.BFLY by 1 as the translator writes it for a 32-lane host
COMPUTE_CS = '''OpCapability Shader
OpCapability GroupNonUniform
OpCapability GroupNonUniformShuffle
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main" %lane
OpExecutionMode %main LocalSize 64 1 1
OpDecorate %lane BuiltIn SubgroupLocalInvocationId
%void = OpTypeVoid
%fn = OpTypeFunction %void
%u32 = OpTypeInt 32 0
%pu = OpTypePointer Input %u32
%lane = OpVariable %pu Input
%scope = OpConstant %u32 3
%u1 = OpConstant %u32 1
%main = OpFunction %void None %fn
%l = OpLabel
%L = OpLoad %u32 %lane
%x = OpBitwiseXor %u32 %L %u1
%s = OpGroupNonUniformShuffle %u32 %scope %L %x
OpReturn
OpFunctionEnd
'''


def ops(data): return [op for op, _ in instructions(data)]
def builtins(data): return {x[0]: x[2] for op, x in instructions(data) if op == 71 and len(x) >= 3 and x[1] == 11}
def interface(data): return next(x for op, x in instructions(data) if op == 15)


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvWide(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'w.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_wide.h"\n{export} size_t run(const uint32_t *w, size_t n, uint32_t sg, uint32_t *s, uint32_t *o, size_t cap, size_t *need, int *what) '
                       f'{{ return spv_wide(w, n, sg, s, o, cap, need, what); }}\n'
                       f'{export} uint32_t wanted(const uint32_t *w, size_t n, uint32_t sg) {{ return spv_wide_wanted(w, n, sg); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone, as test_spv_limits
            subprocess.run([cls.bin / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-Werror', '-I', REPO / 'dm/android', '-c', src,
                            '-o', cls.tmp / 'w.obj'], check=True)
            subprocess.run([cls.bin / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "w.dll"}', str(cls.tmp / 'w.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'w.dll'))
        else:   # the system's clang, as test_spv_limits
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or cls.bin / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'w.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'w.so'))
        cls.lib.run.restype = ctypes.c_size_t; cls.lib.wanted.restype = ctypes.c_uint32

    def run_on(self, data, stages=ADRENO_830):   # → (the rewritten module or None, SPV_WIDE_* bits)
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data)
        s = (ctypes.c_uint32 * (2 * w[3]))(); need = ctypes.c_size_t(); what = ctypes.c_int()
        self.assertEqual(self.lib.run(w, n, stages, s, None, 0, ctypes.byref(need), ctypes.byref(what)), 0)
        if need.value or what.value: self.assertTrue(self.lib.wanted(w, n, stages))   # the replay's pre-check never passes over a module that needs it
        if not need.value: return None, what.value
        cap = need.value; o = (ctypes.c_uint32 * (cap + 64))(*[GUARD] * (cap + 64))
        k = self.lib.run(w, n, stages, s, o, cap, ctypes.byref(need), ctypes.byref(what))
        self.assertTrue(0 < k <= cap)
        self.assertEqual(list(o[cap:]), [GUARD] * 64, 'written past the words it asked for')
        return bytes(o)[:4 * k], what.value

    def val(self, data, name):
        p = self.tmp / name; p.write_bytes(data)
        r = subprocess.run([self.spv_val, '--target-env', 'vulkan1.1', p], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def asm(self, text, name):
        p = self.tmp / f'{name}.spvasm'; p.write_text(text)
        subprocess.run([self.spv_as, '--target-env', 'vulkan1.1', p, '-o', self.tmp / f'{name}.spv'], check=True)
        data = (self.tmp / f'{name}.spv').read_bytes(); self.val(data, f'{name}_in.spv')
        return data

    def test_translators_warp_instructions(self):
        data = self.asm(FS, 'fs')
        out, what = self.run_on(data)
        self.assertEqual(what, DONE)
        self.val(out, 'fs_out.spv')
        o = ops(out)
        self.assertEqual(o.count(345), 2)   # the two shuffles stay shuffles
        self.assertEqual([op for op in o if op in (334, 335, 336)], [])   # the votes are made from ballots: the one there was, each vote's, All's and AllEqual's active lanes
        self.assertEqual(o.count(339), 1 + 3 + 2)
        self.assertEqual(o.count(77), 1 + 3 + 2)   # OpVectorExtractDynamic: their words of the warp
        size = next(i for i, b in builtins(out).items() if b == 36)
        self.assertEqual([x for op, x in instructions(out) if op == 61 and x[2] == size], [])   # the subgroup size is 32: its variable stays, unread
        words = {x[1]: (op, x) for op, x in instructions(out) if len(x) >= 2 and op not in (5, 6, 71, 72, 15, 16, 17)}
        lane = next(x[0] for op, x in instructions(out) if op == 71 and x[1:3] == (11, 41))
        const = {x[1]: x[2] for op, x in instructions(out) if op == 43}
        for op, x in instructions(out):   # each shuffle's index is ORed with the lane's own warp bits, lane & ~31
            if op != 345: continue
            oop, ox = words[x[4]]
            self.assertEqual(oop, 197)
            aop, ax = words[ox[3]]
            self.assertEqual((aop, const[ax[3]]), (199, 0xffffffe0))
            self.assertEqual(words[ax[2]][0], 61); self.assertEqual(words[ax[2]][1][2], lane)
        lane_loads = [x[1] for op, x in instructions(out) if op == 61 and x[2] == lane]
        users = [(op, x) for op, x in instructions(out) if op == 199 and x[2] in lane_loads]
        self.assertTrue(users and all(const[x[3]] in (31, 0xffffffe0) for op, x in users))   # the lane within its warp, or its warp bits
        self.assertEqual(sum(op == 194 and x[2] in lane_loads for op, x in instructions(out)), 1 + 1 + 3)   # lane >> 5: the ballot word, the mask, the votes

    def test_ballot_alone_gets_the_lane_id(self):
        out, what = self.run_on(self.asm(BALLOT_FS, 'ballot'))
        self.assertEqual(what, DONE)
        self.val(out, 'ballot_out.spv')
        lane = [i for i, b in builtins(out).items() if b == 41]
        self.assertEqual(len(lane), 1)
        self.assertIn(lane[0], interface(out))
        self.assertIn((lane[0], 14), {(x[0], x[1]) for op, x in instructions(out) if op == 71})   # Flat, as the translator declares it

    def test_stage_without_subgroups_or_narrow_gpu_left(self):   # the Adreno 650's fragment shaders are spv_limits'
        data = self.asm(FS, 'fs_650')
        self.assertEqual(self.run_on(data, ADRENO_650), (None, 0))
        w = (ctypes.c_uint32 * (len(data) // 4)).from_buffer_copy(data)
        self.assertEqual((self.lib.wanted(w, len(w), ADRENO_650), self.lib.wanted(w, len(w), ADRENO_830)), (0, FRAGMENT))

    def test_votes_fit_the_words_asked(self):   # AllEqual becomes 44 words: ten of them once went 51 words past what the rewrite asked for
        for n in (1, 3, 10, 40):
            out, what = self.run_on(self.asm(votes_fs(n), f'votes{n}'))
            self.assertEqual(what, DONE)
            self.val(out, f'votes{n}_out.spv')
            self.assertEqual([op for op in ops(out) if op in (334, 335, 336)], [])

    def test_compute_rewritten(self):   # a warp-aggregated count: lanes 32-63 in their own warp's ballot word, mask word and leader
        data = self.asm(AGG_CS, 'agg')
        w = (ctypes.c_uint32 * (len(data) // 4)).from_buffer_copy(data)
        self.assertEqual((self.lib.wanted(w, len(w), ADRENO_830), self.lib.wanted(w, len(w), FRAGMENT)), (COMPUTE, 0))
        out, what = self.run_on(data)
        self.assertEqual(what, DONE)
        self.val(out, 'agg_out.spv')
        o = ops(out)
        self.assertEqual((o.count(339), o.count(345)), (1, 1))   # the ballot and the shuffle stay
        self.assertEqual(o.count(77), 1)   # OpVectorExtractDynamic: the ballot's word of the lane's warp
        self.assertEqual(o.count(194), 2)   # lane >> 5, the warp: for that word and for the LT mask's access chain
        out, what = self.run_on(self.asm(COMPUTE_CS, 'cs'))
        self.assertEqual(what, DONE)
        self.val(out, 'cs_out.spv')

    def test_mesh_left(self):   # only fragment and compute shaders were checked on a device
        data = self.asm(COMPUTE_CS, 'cs_mesh')
        w = (ctypes.c_uint32 * (len(data) // 4)).from_buffer_copy(data)
        ep = next(i for i in range(5, len(w)) if w[i] & 0xffff == 15 and w[i] >> 16 >= 3)   # its entry point as MeshEXT's (not a valid mesh shader: scanned only)
        w[ep + 1] = 5365
        self.assertEqual((self.lib.wanted(w, len(w), FOLD), self.lib.wanted(w, len(w), ADRENO_830)), (MESH, 0))
        self.assertEqual(self.run_on(bytes(w), FOLD), (None, STAGE))

    def test_module_without_subgroup_use_left(self):
        text = HEAD[:HEAD.index('%L = OpLoad')] + 'OpReturn\nOpFunctionEnd\n'
        self.assertEqual(self.run_on(self.asm(text, 'fs_none')), (None, 0))

    def test_operation_not_covered_left(self):   # the translator writes SHFL as Shuffle only; a relative shuffle or an arithmetic one is not Maxwell's
        text = FS.replace('OpCapability GroupNonUniformVote\n', 'OpCapability GroupNonUniformVote\nOpCapability GroupNonUniformShuffleRelative\n') \
                 .replace('%sh1 = OpGroupNonUniformShuffle %f32 %scope %f %src1\n', '%sh1 = OpGroupNonUniformShuffleXor %f32 %scope %f %u1\n')
        self.assertEqual(self.run_on(self.asm(text, 'fs_xor')), (None, KEPT))
        text = FS.replace('OpCapability GroupNonUniformVote\n', 'OpCapability GroupNonUniformVote\nOpCapability GroupNonUniformArithmetic\n') \
                 .replace('%sz = OpLoad %u32 %size\n', '%sz = OpGroupNonUniformIAdd %u32 %scope Reduce %L\n')
        self.assertEqual(self.run_on(self.asm(text, 'fs_add')), (None, KEPT))

    def test_lane_id_of_another_type_left(self):
        text = FS.replace('%lane = OpVariable %pu Input', '%pi32 = OpTypePointer Input %i32\n%lane = OpVariable %pi32 Input').replace('%L = OpLoad %u32 %lane', '%Li = OpLoad %i32 %lane\n%L = OpBitcast %u32 %Li')
        self.assertEqual(self.run_on(self.asm(text, 'fs_int_lane')), (None, KEPT))

    def valid(self, data, name):
        p = self.tmp / name; p.write_bytes(data)
        return subprocess.run([self.spv_val, '--target-env', 'vulkan1.1', p], capture_output=True).returncode == 0

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR not set')
    def test_a_games_shaders(self):   # each rewritten module that spirv-val takes as translated must pass after
        d = Path(os.environ['DM_SPV_DIR']); n = invalid = 0; got: dict[int, int] = {}
        for sp in sorted(d.glob('*.spv')):
            n += 1; data = sp.read_bytes(); out, what = self.run_on(data)
            got[what] = got.get(what, 0) + 1
            if not out: continue
            if not self.valid(data, 'game_in.spv'): invalid += 1; continue
            self.val(out, f'game_{sp.stem}.spv')
        print(f'{n} modules; by what was done (SPV_WIDE_* bits): {dict(sorted(got.items()))}; {invalid} rewritten ones invalid as translated, not checked')
        self.assertTrue(n)

    @unittest.skipUnless(os.environ.get('DM_TEST_SERIAL'), 'DM_TEST_SERIAL not set')
    def test_quad_shuffles_on_a_device(self):
        serial = os.environ['DM_TEST_SERIAL']
        adb = shutil.which('adb') or str(Path(os.environ.get('ANDROID_HOME', '')) / 'platform-tools' / f'adb{EXE}')
        exe = self.tmp / 't_quad_shuffle'
        cc = self.bin / ('aarch64-linux-android29-clang' + ('.cmd' if os.name == 'nt' else ''))
        subprocess.run([cc, '-O1', '-Wall', '-Werror', REPO / 'dm/android/tests/t_quad_shuffle.c', '-lvulkan', '-o', exe], check=True)
        data = self.asm(DEV_FS, 'dev_fs'); out, what = self.run_on(data); self.assertEqual(what, DONE); assert out is not None
        (self.tmp / 'fs_in.spv').write_bytes(data); (self.tmp / 'fs.spv').write_bytes(out); (self.tmp / 'vs.spv').write_bytes(self.asm(DEV_VS, 'dev_vs'))
        d = '/data/local/tmp/dm_quad_shuffle_wide'
        subprocess.run([adb, '-s', serial, 'shell', 'mkdir', '-p', d], check=True)
        for f in (exe, self.tmp / 'vs.spv', self.tmp / 'fs.spv', self.tmp / 'fs_in.spv'): subprocess.run([adb, '-s', serial, 'push', f, d], check=True, capture_output=True)
        def on_device(fs):
            r = subprocess.run([adb, '-s', serial, 'shell', f'cd {d} && chmod 755 t_quad_shuffle && ./t_quad_shuffle vs.spv {fs}; echo "exit $?"'], capture_output=True, text=True)
            print(r.stdout.strip()); return r.stdout
        rewritten, translated = on_device('fs.spv'), on_device('fs_in.spv')
        subprocess.run([adb, '-s', serial, 'shell', 'rm', '-r', d], capture_output=True)
        self.assertTrue(rewritten.strip().endswith('exit 0'), rewritten)
        m = re.search(r'subgroup size (\d+)', rewritten); assert m
        if int(m.group(1)) > 32: self.assertFalse(translated.strip().endswith('exit 0'), translated)   # lanes 32 and up read the first 32 lanes' quads, or themselves

    @unittest.skipUnless(os.environ.get('DM_TEST_SERIAL'), 'DM_TEST_SERIAL not set')
    def test_warp_reductions_on_a_device(self):   # compute: test_spv_narrow's whole-warp reductions (SHFL.BFLY by 1 to 16, lane 0 of each warp adds its result)
        from test_spv_narrow import CS as REDUCE_CS
        serial = os.environ['DM_TEST_SERIAL']
        adb = shutil.which('adb') or str(Path(os.environ.get('ANDROID_HOME', '')) / 'platform-tools' / f'adb{EXE}')
        exe = self.tmp / 't_warp_reduce'
        cc = self.bin / ('aarch64-linux-android29-clang' + ('.cmd' if os.name == 'nt' else ''))
        subprocess.run([cc, '-O1', '-Wall', '-Werror', REPO / 'dm/android/tests/t_warp_reduce.c', '-lvulkan', '-o', exe], check=True)
        data = self.asm(REDUCE_CS, 'dev_cs'); out, what = self.run_on(data); self.assertEqual(what, DONE); assert out is not None
        self.val(out, 'dev_cs_out.spv'); (self.tmp / 'cs_in.spv').write_bytes(data); (self.tmp / 'cs.spv').write_bytes(out)
        d = '/data/local/tmp/dm_warp_reduce_wide'
        subprocess.run([adb, '-s', serial, 'shell', 'mkdir', '-p', d], check=True)
        for f in (exe, self.tmp / 'cs.spv', self.tmp / 'cs_in.spv'): subprocess.run([adb, '-s', serial, 'push', f, d], check=True, capture_output=True)
        def on_device(cs):
            r = subprocess.run([adb, '-s', serial, 'shell', f'cd {d} && chmod 755 t_warp_reduce && ./t_warp_reduce {cs}; echo "exit $?"'], capture_output=True, text=True)
            print(r.stdout.strip()); return r.stdout
        rewritten, translated = on_device('cs.spv'), on_device('cs_in.spv')
        subprocess.run([adb, '-s', serial, 'shell', 'rm', '-r', d], capture_output=True)
        self.assertTrue(rewritten.strip().endswith('exit 0'), rewritten)
        m = re.search(r'subgroup size (\d+)', rewritten); assert m
        if int(m.group(1)) > 32: self.assertFalse(translated.strip().endswith('exit 0'), translated)   # the second warp's steps keep its own value, and lane 32 never adds


if __name__ == '__main__':
    unittest.main()
