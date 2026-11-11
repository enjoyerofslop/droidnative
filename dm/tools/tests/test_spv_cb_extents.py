"""How much of each constant buffer an Android shader reads: dm/android/tools/spv_android.py cb_extents (res.json cbufs[].ext) and the host's own scans in
dm/android/gfx_vk_draw.inc (spv_cb_ext, the old word match, and spv_cb_ext2, by operand), on modules assembled with spirv-as (the NDK's shader-tools, else one on PATH).
The host's scans are taken out of gfx_vk_draw.inc and built for the PC with its C compiler (cc; those checks skip without one). Skipped without spirv-as.
With DM_SPV_DIR=<a game's packed spv folder>, cb_extents also runs over every shader there, against the host's scan: never below it where both bound a binding."""
import ctypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import spv_android as sa   # noqa: E402  # pyright: ignore[reportMissingImports]  # dm/android/tools, put on the path above
from test_spv_readonly import NDK, HOST, EXE   # noqa: E402

SPV_AS = (NDK / 'shader-tools' / HOST / f'spirv-as{EXE}') if NDK else shutil.which('spirv-as')
CC = (shutil.which('cc') or shutil.which('clang')) if os.name != 'nt' else None   # the PC's own (the NDK's clang links no host library on macOS); none on Windows: those tests skip

# a vertex shader reading constant buffer binding 1 (vec4[4096], as the translator declares it); %BODY% is the entry point's code after its variables, which
# keep the translator's debug-mode form (every value in a Function variable). %u is an unknown float (the input), %fu its bits
HEAD = '''OpCapability Shader
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %in %out
OpDecorate %in Location 0
OpDecorate %out Location 0
OpDecorate %arr ArrayStride 16
OpDecorate %blk Block
OpMemberDecorate %blk 0 Offset 0
OpDecorate %19 DescriptorSet 0
OpDecorate %19 Binding 1
OpDecorate %other DescriptorSet 0
OpDecorate %other Binding 2
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%i32 = OpTypeInt 32 1
%u32 = OpTypeInt 32 0
%bool = OpTypeBool
%n4096 = OpConstant %u32 4096
%arr = OpTypeArray %v4 %n4096
%blk = OpTypeStruct %arr
%pblk = OpTypePointer Uniform %blk
%19 = OpVariable %pblk Uniform
%other = OpVariable %pblk Uniform
%pv4 = OpTypePointer Uniform %v4
%pin = OpTypePointer Input %f32
%in = OpVariable %pin Input
%pout = OpTypePointer Output %v4
%out = OpVariable %pout Output
%pfi = OpTypePointer Function %i32
%pfb = OpTypePointer Function %bool
%c0 = OpConstant %i32 0
%c1 = OpConstant %i32 1
%c2 = OpConstant %i32 2
%c3 = OpConstant %i32 3
%c4 = OpConstant %i32 4
%c5 = OpConstant %i32 5
%c8 = OpConstant %i32 8
%c9 = OpConstant %i32 9
%c19 = OpConstant %i32 19
%cn1 = OpConstant %i32 -1
%f0 = OpConstant %f32 0
%main = OpFunction %void None %fn
%entry = OpLabel
%i = OpVariable %pfi Function
%t = OpVariable %pfi Function
%k = OpVariable %pfi Function
%done = OpVariable %pfb Function
%u = OpLoad %f32 %in
%fu = OpBitcast %i32 %u
%cmp = OpFOrdLessThan %bool %u %f0
%BODY%
OpReturn
OpFunctionEnd
%EXTRA%'''

READ = '''%{n}p = OpAccessChain %pv4 %19 %c0 %{idx}
%{n}v = OpLoad %v4 %{n}p
OpStore %out %{n}v
'''

# a do-while whose exit test is a bool set in the body and branched on in the latch (Breath of the Wild's 5ee9a682fff60855): i = 2, 1; reads element 4 i + 8
DO_WHILE = '''OpStore %i %c2
OpBranch %head
%head = OpLabel
OpLoopMerge %exit %latch None
OpBranch %body
%body = OpLabel
%iv = OpLoad %i32 %i
OpStore %t %iv
%tv = OpLoad %i32 %t
%sh = OpShiftLeftLogical %i32 %tv %c2
%idx = OpIAdd %i32 %sh %c8
''' + READ.format(n='r', idx='idx') + '''OpSelectionMerge %skip None
OpBranchConditional %cmp %exit %skip
%skip = OpLabel
%tv2 = OpLoad %i32 %t
%le = OpSLessThanEqual %bool %tv2 %c1
OpStore %done %le
%dec = OpIAdd %i32 %tv2 %cn1
OpStore %i %dec
OpBranch %latch
%latch = OpLabel
%dn = OpLoad %bool %done
%again = OpLogicalNot %bool %dn
OpBranchConditional %again %head %exit
%exit = OpLabel'''


@unittest.skipIf(SPV_AS is None, 'no spirv-as')
class CbExtents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.lib = None
        if CC:   # the host's scans, out of gfx_vk_draw.inc
            src = (REPO / 'dm/android/gfx_vk_draw.inc').read_text(encoding='utf-8') + (REPO / 'dm/android/spv_lit.h').read_text(encoding='utf-8')   # spv_lit moved to its own header (#92)

            def fn(sig, one_line=False):
                a = src.index(sig); return src[a:src.index('\n', a) + 1] if one_line else src[a:src.index('\n}\n', a) + 3]
            c = ('#include <stdint.h>\n#include <stdlib.h>\n#include <string.h>\ntypedef struct { int binding, slot; uint32_t ext; } rb_cbuf;\n'
                 + fn('#define CB_MAX ', True) + fn('static int spv_lit(') + fn('static void spv_cb_ext(') + fn('static int cb_index(', True) + fn('static void spv_cb_ext2(')
                 + '__attribute__((visibility("default"))) void run(const uint32_t *w, size_t n, const int *b, int ncb, uint32_t *ext, int two) {\n'
                 '    rb_cbuf cb[CB_MAX]; for (int i = 0; i < ncb; i++) { cb[i].binding = b[i]; cb[i].slot = 0; cb[i].ext = 0; }\n'
                 '    if (two) spv_cb_ext2(w, n, cb, ncb, ext); else spv_cb_ext(w, n, cb, ncb, ext);\n}\n')
            (cls.tmp / 'scan.c').write_text(c, encoding='utf-8')
            subprocess.run([CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wno-unused-function', cls.tmp / 'scan.c', '-o', cls.tmp / 'scan.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'scan.so'))

    def asm(self, body, extra='', head=HEAD):
        p = self.tmp / 't.spvasm'; p.write_text(head.replace('%BODY%', body).replace('%EXTRA%', extra))
        subprocess.run([str(SPV_AS), '--target-env', 'vulkan1.1', '--preserve-numeric-ids', str(p), '-o', str(self.tmp / 't.spv')], check=True)
        return (self.tmp / 't.spv').read_bytes()

    def ext(self, data, why=None):
        return sa.cb_extents(sa.parse(data)[1], [1, 2], why)

    def host(self, data, two):
        if not self.lib: self.skipTest('no C compiler')
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); b = (ctypes.c_int * 2)(1, 2); e = (ctypes.c_uint32 * 18)()
        self.lib.run(w, n, b, 2, e, 1 if two else 0)
        return {1: e[0], 2: e[1]}

    def test_constant_reads_and_a_literal_equal_to_the_variables_id(self):
        # %c19's value is the buffer variable's id (19): the old word match keeps the whole buffer for it, by operand it is no use
        data = self.asm(READ.format(n='a', idx='c5') + READ.format(n='b', idx='c19'))
        self.assertEqual(self.ext(data), {1: 320, 2: 16})   # elements 5 and 19; binding 2 never read
        self.assertEqual(self.host(data, True), {1: 320, 2: 16})
        self.assertEqual(self.host(data, False)[1], 0)

    def test_a_private_register_starts_from_its_initializer(self):
        # a Private variable initialized with a constant: the run starts the entry point with that value as a set, as every other state value; it was a bare int, on which
        # the first instruction that used it (or a join of states) raised, and spv_android.py stopped the build (Frostpunk: 12 of its pixel shaders)
        head = HEAD.replace('%f0 = OpConstant %f32 0\n', '%f0 = OpConstant %f32 0\n%ppi = OpTypePointer Private %i32\n%priv = OpVariable %ppi Private %c4\n')
        data = self.asm('%pv = OpLoad %i32 %priv\n%pidx = OpIAdd %i32 %pv %c1\n' + READ.format(n='p', idx='pidx'), head=head)
        self.assertEqual(self.ext(data)[1], 16 * 6)   # element 4 + 1

    def test_do_while_counter_tested_in_the_latch(self):
        data = self.asm(DO_WHILE)
        self.assertEqual(self.ext(data)[1], 16 * 17)   # i = 2, 1: elements 16 and 12
        self.assertEqual(self.host(data, True)[1], 0)   # the scan keeps a computed index whole (the declared 4096 vec4)

    def test_loop_bounded_only_by_a_uniform_keeps_the_whole_buffer(self):
        body = DO_WHILE.replace('%le = OpSLessThanEqual %bool %tv2 %c1', '%le = OpFOrdGreaterThan %bool %u %f0')
        why = {}
        self.assertEqual(self.ext(self.asm(body), why)[1], 0)
        self.assertEqual(why[1], 'index unknown')

    def test_counter_below_zero_wraps_past_the_array(self):
        # i - 1 from 0 is -1: (-1 << 4) >> 4 (logical) is 0x0fffffff, past the 4096 elements: undefined, so the whole buffer, as before
        body = '''OpStore %i %c0
%a = OpLoad %i32 %i
%b = OpIAdd %i32 %a %cn1
%s = OpShiftLeftLogical %i32 %b %c4
%idx = OpShiftRightLogical %i32 %s %c4
''' + READ.format(n='r', idx='idx')
        why = {}
        self.assertEqual(self.ext(self.asm(body), why)[1], 0)
        self.assertEqual(why[1], 'index past the array')

    def test_unknown_value_masked_or_selected(self):
        body = '''%m = OpBitwiseAnd %i32 %fu %c3
''' + READ.format(n='a', idx='m') + '''%s = OpSelect %i32 %cmp %c5 %c9
''' + READ.format(n='b', idx='s')
        self.assertEqual(self.ext(self.asm(body))[1], 160)   # x & 3: elements 0-3; either 5 or 9

    def test_unknown_index_and_other_uses_keep_the_whole_buffer(self):
        why = {}
        self.assertEqual(self.ext(self.asm('%x = OpShiftRightLogical %i32 %fu %c4\n' + READ.format(n='a', idx='x')), why)[1], 0)
        self.assertEqual(why[1], 'index unknown')
        why = {}
        data = self.asm('%w = OpLoad %blk %19\n' + READ.format(n='a', idx='c1'))   # the whole block loaded
        self.assertEqual(self.ext(data, why)[1], 0)
        self.assertEqual(why[1], 'used other than by an access chain from member 0')
        self.assertEqual(self.host(data, True)[1], 0)

    def test_switch_on_a_known_selector_takes_its_case(self):
        # OpSwitch's words are [selector, default, literal, label, literal, label, ...]: a known selector goes to the label after its literal. One path stores t = 5 and
        # k = 19, the other leaves t unknown and k = 2; case 5 reads c[k]: the known 5 must reach it (element 19), else only the unknown path's k = 2 is seen there
        def switch(t_a, t_b, cases, case3):
            return '''OpStore %k %c2
OpSelectionMerge %m0 None
OpBranchConditional %cmp %a %b
%a = OpLabel
OpStore %k %c19
OpStore %t T_A
OpBranch %m0
%b = OpLabel
OpStore %t T_B
OpBranch %m0
%m0 = OpLabel
%s = OpLoad %i32 %t
OpSelectionMerge %m None
OpSwitch %s %def CASES
%case5 = OpLabel
%kk = OpLoad %i32 %k
'''.replace('T_A', t_a).replace('T_B', t_b).replace('CASES', cases) + READ.format(n='r', idx='kk') + '''OpBranch %m
''' + ('''%case3 = OpLabel
''' + case3 + '''OpBranch %m
''' if '%case3' in cases else '') + '''%def = OpLabel
OpBranch %m
%m = OpLabel'''
        for cases in ('5 %case5', '5 %case5 3 %case3', '3 %case3 5 %case5'):
            self.assertEqual(self.ext(self.asm(switch('%c5', '%fu', cases, '')))[1], 16 * 20, cases)
        # both known, each to its own case: 5 with k = 19 reads element 19, 3 with k = 2 reads k + 1 = 3 (were 5 sent to case 3 too, element 20)
        c3 = '%k3 = OpLoad %i32 %k\n%k3x = OpIAdd %i32 %k3 %c1\n' + READ.format(n='q', idx='k3x')
        for cases in ('5 %case5 3 %case3', '3 %case3 5 %case5'):
            self.assertEqual(self.ext(self.asm(switch('%c5', '%c3', cases, c3)))[1], 16 * 20, cases)
        # a known selector with no case takes the default: the cases' access chains never reached keep the buffer whole
        why = {}
        self.assertEqual(self.ext(self.asm(switch('%c9', '%c9', '5 %case5 3 %case3', c3)), why)[1], 0)
        self.assertEqual(why[1], 'index in a block the run never reached')

    def test_a_register_handed_to_a_function_is_unknown(self):
        # %t's pointer goes to a function that may store through it: its value after the call is not the 1 stored before
        body = '''OpStore %t %c1
%r = OpFunctionCall %void %set %t
%tv = OpLoad %i32 %t
''' + READ.format(n='a', idx='tv')
        extra = '''%set = OpFunction %void None %fnp
%p = OpFunctionParameter %pfi
%sl = OpLabel
OpStore %p %c9
OpReturn
OpFunctionEnd
'''
        data = self.asm(body, extra, HEAD.replace('%fn = OpTypeFunction %void', '%fn = OpTypeFunction %void\n%fnp = OpTypeFunction %void %pfi'))
        why = {}
        self.assertEqual(self.ext(data, why)[1], 0)
        self.assertEqual(why[1], 'index unknown')

    def test_value_rules_hold_for_concrete_values(self):
        # each rule for an unknown operand gives a set holding every result the op can have (sampled), and the 32-bit semantics of a few cases
        import random
        rnd = random.Random(1)
        cases = [([199, 0, 0, None, 'm'], lambda v, m: v & m), ([137, 0, 0, None, 'm'], lambda v, m: v % m if m else None),
                 ([194, 0, 0, None, 's'], lambda v, s: v >> s), ([203, 0, 0, None, 'o', 'n'], None)]
        for _ in range(300):
            m, s, o, n = rnd.choice([1, 3, 5, 12, 15, 0x30, 0xf0, 7]), rnd.randint(28, 31), rnd.randint(0, 28), rnd.randint(0, 4)
            consts = {'m': m, 's': s, 'o': o, 'n': n}
            for x, f in cases:
                ops = [None if w is None else frozenset((consts[w],)) for w in x[3:]]
                r = sa._cb_eval([x[0], 1, 2] + list(range(10, 10 + len(ops))), lambda w, ops=ops: ops[w - 10], set())
                if r is None: continue
                for _ in range(20):
                    v = rnd.getrandbits(32)
                    want = sa._cb_one([x[0], 1, 2], [v] + [consts[w] for w in x[4:]], set())
                    if want is not None: self.assertIn(want, r, (x, consts, v))
        neg = lambda v: v & 0xffffffff
        self.assertEqual(sa._bin(135, neg(-7), 2), neg(-3))   # OpSDiv rounds toward zero
        self.assertEqual(sa._bin(138, neg(-7), 2), neg(-1))   # OpSRem: the dividend's sign
        self.assertEqual(sa._bin(139, neg(-7), 2), 1)   # OpSMod: the divisor's sign
        self.assertEqual(sa._bin(139, 7, neg(-2)), neg(-1))
        self.assertEqual(sa._bin(195, 0x80000000, 4), 0xf8000000)   # arithmetic shift
        self.assertIsNone(sa._bin(196, 1, 32))   # a shift by the width is undefined

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR not set')
    def test_a_games_shaders(self):
        d = Path(os.environ['DM_SPV_DIR']); n = bounded = below = 0
        for rj in sorted(d.glob('*.res.json')):
            r = json.loads(rj.read_text(encoding='utf-8')); cb = [c['binding'] for c in r.get('cbufs') or []]
            sp = d / (rj.name[:-9] + '.spv')
            if not cb or not sp.is_file(): continue
            data = sp.read_bytes(); e = sa.cb_extents(sa.parse(data)[1], cb); n += len(cb); bounded += sum(1 for b in cb if e[b])
            if self.lib:
                nw = len(data) // 4; w = (ctypes.c_uint32 * nw).from_buffer_copy(data); bb = (ctypes.c_int * len(cb))(*cb); h = (ctypes.c_uint32 * 18)()
                self.lib.run(w, nw, bb, len(cb), h, 1)
                for i, b in enumerate(cb):
                    if h[i] and e[b] != h[i]: below += 1; print('differs from the host scan', rj.name, b, e[b], h[i])
        print(f'{n} constant buffer bindings, {bounded} bounded')
        self.assertTrue(n); self.assertEqual(below, 0)


if __name__ == '__main__':
    unittest.main()
