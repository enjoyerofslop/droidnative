"""dm/android/spv_narrow.h (Maxwell's 32-lane warps on a GPU whose subgroups are narrower: each subgroup a warp of its own, as on the Pixel 9 Pro XL's
Mali-G715 with 16 lanes), built for the PC and run on modules assembled with the NDK's spirv-as; spirv-val checks each result, and a guard after the words it
asked for checks that it writes no further. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there with 16-lane fragment and compute subgroups (each result must pass spirv-val
wherever the module itself does).
With DM_TEST_SERIAL=<adb serial>, dm/android/tests/t_warp_reduce.c is built for Android and run on that device with a compute shader whose whole-warp reductions
are the translator's: rewritten for the device's subgroup size where it is under 32, its sum, minimum, maximum and OR must be the workgroup's; where it is 32 or
more, as translated."""
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

GUARD_, STEP, KEPT = 1, 2, 4   # SPV_NARROW_*
FRAG_COMP = 0x30
GUARD = 0xa5a5a5a5

# A compute shader as the translator writes a whole-warp reduction for a 32-lane host: Ryujinx's ShuffleXor helper (value, index, mask and the valid flag through
# Function pointers; the lane ID & the segment mask, valid up to the clamp), called with offsets 1, 2, 4, 8 and 16 and mask 31, each result combined with the
# value it shuffled; then lane 0 of each warp adds (mins, maxes, ORs) the warp's result into a storage buffer. The sum runs through an int variable and IAdd, the
# minimum through a uint variable, bitcasts and GLSL's UMin (as Final Fantasy Resonance's shaders do), the maximum and the OR side by side, each step's combine
# after the other's call, and the OR's last combine after an if
HEAD = '''OpCapability Shader
OpCapability GroupNonUniform
OpCapability GroupNonUniformShuffle
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main" %gi %lane
OpExecutionMode %main LocalSize 64 1 1
OpDecorate %gi BuiltIn LocalInvocationIndex
OpDecorate %lane BuiltIn SubgroupLocalInvocationId
OpDecorate %Blk Block
OpMemberDecorate %Blk 0 Offset 0
OpMemberDecorate %Blk 1 Offset 4
OpMemberDecorate %Blk 2 Offset 8
OpMemberDecorate %Blk 3 Offset 12
OpDecorate %buf DescriptorSet 0
OpDecorate %buf Binding 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%bool = OpTypeBool
%u32 = OpTypeInt 32 0
%i32 = OpTypeInt 32 1
%f32 = OpTypeFloat 32
%pu = OpTypePointer Input %u32
%gi = OpVariable %pu Input
%lane = OpVariable %pu Input
%Blk = OpTypeStruct %u32 %u32 %u32 %u32
%pBlk = OpTypePointer StorageBuffer %Blk
%buf = OpVariable %pBlk StorageBuffer
%psu = OpTypePointer StorageBuffer %u32
%pfi = OpTypePointer Function %i32
%pfu = OpTypePointer Function %u32
%hfn = OpTypeFunction %i32 %pfi %pfi %pfi %pfi
%i0 = OpConstant %i32 0
%i1 = OpConstant %i32 1
%i2 = OpConstant %i32 2
%i3 = OpConstant %i32 3
%i4 = OpConstant %i32 4
%i8 = OpConstant %i32 8
%i16 = OpConstant %i32 16
%i31 = OpConstant %i32 31
%in1 = OpConstant %i32 -1
%u0 = OpConstant %u32 0
%u1 = OpConstant %u32 1
%scope = OpConstant %u32 3
%k1 = OpConstant %u32 2654435761
%k3 = OpConstant %u32 739982445
%s15 = OpConstant %u32 15
%s12 = OpConstant %u32 12
%mask = OpConstant %u32 65535
%main = OpFunction %void None %fn
%l0 = OpLabel
%X = OpVariable %pfi Function
%Y = OpVariable %pfu Function
%Z = OpVariable %pfu Function
%W = OpVariable %pfi Function
'''
VARS = ''.join(f'%A{n} = OpVariable %pfi Function\n%B{n} = OpVariable %pfi Function\n%C{n} = OpVariable %pfi Function\n%P{n} = OpVariable %pfi Function\n'
               f'%R{n} = OpVariable %pfi Function\n' for n in range(20))
VALUE = '''%g0 = OpLoad %u32 %gi
%g = OpIAdd %u32 %g0 %u1
%h0 = OpIMul %u32 %g %k1
%t1 = OpShiftRightLogical %u32 %h0 %s15
%h1 = OpBitwiseXor %u32 %h0 %t1
%h2 = OpIMul %u32 %h1 %k3
%t2 = OpShiftRightLogical %u32 %h2 %s12
%h = OpBitwiseXor %u32 %h2 %t2
%v = OpBitwiseAnd %u32 %h %mask
%vi = OpBitcast %i32 %v
OpStore %X %vi
OpStore %Y %v
OpStore %Z %v
OpStore %W %vi
'''
OFFS = (1, 2, 4, 8, 16)
def call(n, var, b, uint):   # the value passed (a uint variable's through a bitcast), the call, its result stored
    v = (f'%a{n} = OpLoad %u32 %{var}\n%ab{n} = OpBitcast %i32 %a{n}\nOpStore %A{n} %ab{n}\n' if uint else f'%a{n} = OpLoad %i32 %{var}\nOpStore %A{n} %a{n}\n')
    return v + f'OpStore %B{n} %i{b}\nOpStore %C{n} %i31\n%r{n} = OpFunctionCall %i32 %bfly %A{n} %B{n} %C{n} %P{n}\nOpStore %R{n} %r{n}\n'
def combine(n, var, op, uint):   # the value again, the call's result, op(value, result) stored back
    if not uint: return f'%x{n} = OpLoad %i32 %{var}\n%y{n} = OpLoad %i32 %R{n}\n%z{n} = {op} %i32 %x{n} %y{n}\nOpStore %{var} %z{n}\n'
    return (f'%x{n} = OpLoad %u32 %{var}\n%y{n} = OpLoad %i32 %R{n}\n%yb{n} = OpBitcast %u32 %y{n}\n%z{n} = OpExtInst %u32 %glsl {op} %x{n} %yb{n}\n'
            f'OpStore %{var} %z{n}\n')
def body():
    s = ''
    for k, b in enumerate(OFFS): s += call(k, 'X', b, False) + combine(k, 'X', 'OpIAdd', False)   # the sum
    for k, b in enumerate(OFFS): s += call(5 + k, 'Y', b, True) + combine(5 + k, 'Y', 'UMin', True)   # the minimum
    for k, b in enumerate(OFFS):   # the maximum and the OR side by side, each combine after the other's call; the OR's last one after an if
        s += call(10 + k, 'Z', b, True) + call(15 + k, 'W', b, False) + combine(10 + k, 'Z', 'UMax', True)
        if b == 16: s += '%ln0 = OpLoad %u32 %lane\n%c0 = OpIEqual %bool %ln0 %u0\nOpSelectionMerge %m0 None\nOpBranchConditional %c0 %t0 %m0\n%t0 = OpLabel\nOpBranch %m0\n%m0 = OpLabel\n'
        s += combine(15 + k, 'W', 'OpBitwiseOr', False)
    return s
LEADER = '''%ln = OpLoad %u32 %lane
%lead = OpIEqual %bool %ln %u0
OpSelectionMerge %done None
OpBranchConditional %lead %write %done
%write = OpLabel
%sx = OpLoad %i32 %X
%sxu = OpBitcast %u32 %sx
%p0 = OpAccessChain %psu %buf %i0
%e0 = OpAtomicIAdd %u32 %p0 %u1 %u0 %sxu
%sy = OpLoad %u32 %Y
%p1 = OpAccessChain %psu %buf %i1
%e1 = OpAtomicUMin %u32 %p1 %u1 %u0 %sy
%sz = OpLoad %u32 %Z
%p2 = OpAccessChain %psu %buf %i2
%e2 = OpAtomicUMax %u32 %p2 %u1 %u0 %sz
%sw = OpLoad %i32 %W
%swu = OpBitcast %u32 %sw
%p3 = OpAccessChain %psu %buf %i3
%e3 = OpAtomicOr %u32 %p3 %u1 %u0 %swu
OpBranch %done
%done = OpLabel
OpReturn
OpFunctionEnd
'''
# Ryujinx's ShuffleXor helper for a 32-lane host (HelperFunctionManager): clamp = mask & 31, segment = (mask >> 8) & 31, the lane's segment's first and last lane,
# the source lane ^ index, valid up to the last; the valid flag through the fourth pointer; the shuffle's value, or the lane's own where not valid
HELPER = '''%bfly = OpFunction %i32 None %hfn
%pv = OpFunctionParameter %pfi
%pb = OpFunctionParameter %pfi
%pc = OpFunctionParameter %pfi
%pp = OpFunctionParameter %pfi
%hl = OpLabel
%c = OpLoad %i32 %pc
%clamp = OpBitwiseAnd %i32 %c %i31
%c8 = OpShiftRightLogical %i32 %c %i8
%seg = OpBitwiseAnd %i32 %c8 %i31
%hln = OpLoad %u32 %lane
%lni = OpBitcast %i32 %hln
%min = OpBitwiseAnd %i32 %lni %seg
%nseg = OpNot %i32 %seg
%cl = OpBitwiseAnd %i32 %clamp %nseg
%max = OpBitwiseOr %i32 %cl %min
%b = OpLoad %i32 %pb
%src = OpBitwiseXor %i32 %lni %b
%srcu = OpBitcast %u32 %src
%maxu = OpBitcast %u32 %max
%ok = OpULessThanEqual %bool %srcu %maxu
%oki = OpSelect %i32 %ok %in1 %i0
OpStore %pp %oki
%val = OpLoad %i32 %pv
%vf = OpBitcast %f32 %val
%sh = OpGroupNonUniformShuffle %f32 %scope %vf %srcu
%shi = OpBitcast %i32 %sh
%res = OpSelect %i32 %ok %shi %val
OpReturnValue %res
OpFunctionEnd
'''
CS = HEAD + VARS + VALUE + body() + LEADER + HELPER


def ops(data):
    w = [int.from_bytes(data[i:i + 4], 'little') for i in range(0, len(data), 4)]; i = 5; o = []
    while i < len(w): o.append(w[i] & 0xffff); i += w[i] >> 16
    return o


class SpvNarrow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if NDK is None: raise unittest.SkipTest('no Android NDK')
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'n.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_narrow.h"\n{export} size_t run(const uint32_t *w, size_t n, uint32_t sg, uint32_t size, uint32_t *s, size_t sm, uint32_t *o, size_t cap, '
                       f'size_t *need, int *what) {{ return spv_narrow(w, n, sg, size, s, sm, o, cap, need, what); }}\n'
                       f'{export} int wanted(const uint32_t *w, size_t n) {{ return spv_narrow_wanted(w, n); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone, as test_spv_wide
            subprocess.run([cls.bin / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-Werror', '-I', REPO / 'dm/android', '-c', src,
                            '-o', cls.tmp / 'n.obj'], check=True)
            subprocess.run([cls.bin / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "n.dll"}', str(cls.tmp / 'n.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'n.dll'))
        else:
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or cls.bin / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'n.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'n.so'))
        cls.lib.run.restype = ctypes.c_size_t

    def run_on(self, data, size=16, stages=FRAG_COMP):   # → (the rewritten module or None, SPV_NARROW_* bits)
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); sm = 1024
        s = (ctypes.c_uint32 * (9 * w[3] + 2 * sm))(); need = ctypes.c_size_t(); what = ctypes.c_int()
        self.assertEqual(self.lib.run(w, n, stages, size, s, sm, None, 0, ctypes.byref(need), ctypes.byref(what)), 0)
        if need.value or what.value: self.assertTrue(self.lib.wanted(w, n))   # the replay's pre-check never passes over a module that needs it
        if not need.value: return None, what.value
        cap = need.value; o = (ctypes.c_uint32 * (cap + 64))(*[GUARD] * (cap + 64))
        k = self.lib.run(w, n, stages, size, s, sm, o, cap, ctypes.byref(need), ctypes.byref(what))
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

    def test_reductions(self):
        data = self.asm(CS, 'cs')
        out, what = self.run_on(data)
        self.assertEqual(what, GUARD_ | STEP)
        self.val(out, 'cs_out.spv')
        o, i = ops(out), ops(data)
        self.assertEqual(o.count(345), i.count(345))   # the helper's one shuffle stays, its index guarded
        self.assertEqual(o.count(176), i.count(176) + 1)   # OpULessThan: index < size
        self.assertEqual(o.count(83) - i.count(83), 4)   # OpCopyObject: each reduction's 16-lane combine is its value (of the combine's type: no bitcast)
        self.assertEqual(o.count(124), i.count(124))
        self.assertEqual(i.count(128) - o.count(128), 1)   # one IAdd fewer: the sum's last step
        self.assertEqual(i.count(12) - o.count(12), 2)   # UMin and UMax
        self.assertEqual(i.count(197) - o.count(197), 1)   # one OR fewer

    def test_eight_lanes(self):   # on 8 lanes the steps by 8 and 16 have no partner
        out, what = self.run_on(self.asm(CS, 'cs8'), size=8)
        self.assertEqual(what, GUARD_ | STEP)
        self.val(out, 'cs8_out.spv')
        self.assertEqual(ops(self.asm(CS, 'cs8b')).count(128) - ops(out).count(128), 2)

    def test_left_as_translated(self):
        data = self.asm(CS, 'cs_kept')
        self.assertEqual(self.run_on(data, size=32), (None, 0))   # 32 lanes: not its work (the replay does not call it)
        self.assertEqual(self.run_on(data, stages=0x10), (None, 0))   # a stage that runs no subgroup operations: spv_limits'
        # the value written between its load and the call: the combine after the call reads another value, so the step is left (its index still guarded)
        moved = CS.replace('%a4 = OpLoad %i32 %X\nOpStore %A4 %a4\n', '%a4 = OpLoad %i32 %X\nOpStore %X %i0\nOpStore %A4 %a4\n')
        out, what = self.run_on(self.asm(moved, 'cs_moved'))
        self.assertEqual(what, GUARD_ | STEP | KEPT)
        self.val(out, 'cs_moved_out.spv')

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR not set')
    def test_a_games_modules(self):
        d = Path(os.environ['DM_SPV_DIR']); n = done = bad = 0
        for p in sorted(d.glob('*.spv')):
            if p.name.endswith('.z.spv'): continue
            data = p.read_bytes(); out, what = self.run_on(data)
            if out is None: continue
            n += 1; done += bool(what & STEP)
            if subprocess.run([self.spv_val, '--target-env', 'vulkan1.1', p], capture_output=True).returncode: continue   # the module itself fails: not this rewrite's
            q = self.tmp / 'game_out.spv'; q.write_bytes(out)
            r = subprocess.run([self.spv_val, '--target-env', 'vulkan1.1', q], capture_output=True, text=True)
            if r.returncode: bad += 1; print(p.name, r.stdout[:300])
        print(f'{n} modules rewritten, {done} with reduction steps made the value; {bad} failed spirv-val')
        self.assertEqual(bad, 0)

    @unittest.skipUnless(os.environ.get('DM_TEST_SERIAL'), 'DM_TEST_SERIAL not set')
    def test_reductions_on_a_device(self):
        serial = os.environ['DM_TEST_SERIAL']
        adb = shutil.which('adb') or str(Path(os.environ.get('ANDROID_HOME', '')) / 'platform-tools' / f'adb{EXE}')
        exe = self.tmp / 't_warp_reduce'
        cc = self.bin / ('aarch64-linux-android29-clang' + ('.cmd' if os.name == 'nt' else ''))
        subprocess.run([cc, '-O1', '-Wall', '-Werror', REPO / 'dm/android/tests/t_warp_reduce.c', '-lvulkan', '-o', exe], check=True)
        d = '/data/local/tmp/dm_warp_reduce'
        subprocess.run([adb, '-s', serial, 'shell', 'mkdir', '-p', d], check=True)
        data = self.asm(CS, 'dev_cs'); (self.tmp / 'cs_in.spv').write_bytes(data)
        for f in (exe, self.tmp / 'cs_in.spv'): subprocess.run([adb, '-s', serial, 'push', f, d], check=True, capture_output=True)
        def on_device(cs):
            r = subprocess.run([adb, '-s', serial, 'shell', f'cd {d} && chmod 755 t_warp_reduce && ./t_warp_reduce {cs}; echo "exit $?"'], capture_output=True, text=True)
            print(r.stdout.strip()); return r.stdout
        translated = on_device('cs_in.spv')
        m = re.search(r'subgroup size (\d+)', translated); assert m, translated
        size = int(m.group(1))
        if size < 32:
            out, what = self.run_on(data, size=size); self.assertTrue(what & STEP); assert out is not None
            (self.tmp / 'cs_out.spv').write_bytes(out); subprocess.run([adb, '-s', serial, 'push', self.tmp / 'cs_out.spv', d], check=True, capture_output=True)
            result = on_device('cs_out.spv')
        else: result = translated
        subprocess.run([adb, '-s', serial, 'shell', 'rm', '-r', d], capture_output=True)
        self.assertTrue(result.strip().endswith('exit 0'), result)


if __name__ == '__main__':
    unittest.main()
