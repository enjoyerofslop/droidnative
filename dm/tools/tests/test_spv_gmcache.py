"""dm/android/spv_gmcache.h (the translator's raw global memory helpers keep their last pool table entry's range and delta in private words, so a hit reads no table
word), built for the PC and run on modules assembled with the NDK's spirv-as; spirv-val checks each result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there with physical pointers: each must be rewritten and pass spirv-val."""
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

FORM, ROOM, MANY = 1, 2, 3   # spv_gmcache.h's reasons
ENV = {0x10300: 'vulkan1.1', 0x10400: 'vulkan1.1spv1.4', 0x10500: 'vulkan1.2', 0x10600: 'vulkan1.3'}


def helper(search_steps=13, debug=True):
    """A compute shader with one raw-memory helper in the translator's form (GlobalToStorage.TryGenerateRawStorageOp, DebugMode: every value through a local): the entry
    block reads the last entry's start and end (4 table words) and branches; the hint block reads word 6 of the chunk's entry; the search block makes search_steps
    steps of two table words each; the found block stores the index, makes found = index * 8 and reads the entry's end; the chosen block reads the delta (words 4
    and 5), makes the pointer and loads through it. main calls it twice and stores the sum"""
    L = []
    def loc(ty, v):   # a value through a local, as DebugMode writes it
        if not debug: return v
        n = f'%l{len(L)}'; L.append((n, ty, v)); return n + '_v'
    body = []
    def emit(s): body.append(s)
    # the entry block
    emit('%hl = OpLabel'); emit('%VARS')
    emit('%a0 = OpLoad %uint %hp0'); emit('%a1 = OpLoad %uint %hp1')
    emit('%last = OpLoad %uint %lastw'); emit('%le = OpIMul %uint %last %u8')
    le = loc('%uint', '%le')
    for c, nm in ((1, 'shi'), (0, 'slo'), (3, 'ehi'), (2, 'elo')):
        emit(f'%{nm}i = OpIAdd %uint {le} %u{c}'); ii = loc('%uint', f'%{nm}i')
        emit(f'%{nm}p = OpAccessChain %psu %tab %i0 {ii}'); emit(f'%{nm} = OpLoad %uint %{nm}p')
    emit('%c1 = OpULessThan %bool %shi %a1'); emit('%c2 = OpIEqual %bool %shi %a1'); emit('%c3 = OpULessThanEqual %bool %slo %a0'); emit('%c4 = OpLogicalAnd %bool %c2 %c3'); emit('%atb = OpLogicalOr %bool %c1 %c4')
    emit('%c5 = OpULessThan %bool %a1 %ehi'); emit('%c6 = OpIEqual %bool %a1 %ehi'); emit('%c7 = OpULessThan %bool %a0 %elo'); emit('%c8 = OpLogicalAnd %bool %c6 %c7'); emit('%blw = OpLogicalOr %bool %c5 %c8')
    emit('%holds = OpLogicalAnd %bool %atb %blw'); emit('OpStore %sel %last'); emit('OpStore %inp %holds'); emit('%nh = OpLogicalNot %bool %holds')
    emit('OpSelectionMerge %m1 None'); emit('OpBranchConditional %nh %hint %m1')
    # the hint block
    emit('%hint = OpLabel'); emit('%ch1 = OpShiftLeftLogical %uint %a1 %u11'); emit('%ch2 = OpShiftRightLogical %uint %a0 %u21'); emit('%chunk = OpBitwiseOr %uint %ch1 %ch2')
    emit('%hm = OpBitwiseAnd %uint %chunk %u8191'); emit('%he = OpIMul %uint %hm %u8'); emit('%hi6 = OpIAdd %uint %he %u6'); hi6 = loc('%uint', '%hi6')
    emit(f'%hp = OpAccessChain %psu %tab %i0 {hi6}'); emit('%hw = OpLoad %uint %hp'); emit('%hidx = OpBitwiseAnd %uint %hw %u8191')
    emit('%h1 = OpINotEqual %bool %hidx %u0'); emit('%ht = OpShiftRightLogical %uint %hw %u13'); emit('%h2 = OpIEqual %bool %ht %chunk'); emit('%h3 = OpULessThan %bool %a1 %u256')
    emit('%h4 = OpLogicalAnd %bool %h1 %h2'); emit('%fits = OpLogicalAnd %bool %h4 %h3'); emit('OpStore %sel %hidx'); emit('%nf = OpLogicalNot %bool %fits')
    emit('OpSelectionMerge %found None'); emit('OpBranchConditional %nf %search %found')
    # the search block
    emit('%search = OpLabel'); idx = '%u0'
    for k in range(search_steps):
        step = 1 << (12 - k) if search_steps == 13 else 1 << (search_steps - 1 - k)
        emit(f'%cand{k} = OpIAdd %uint {idx} %u{step}'); emit(f'%ce{k} = OpIMul %uint %cand{k} %u8')
        ce = loc('%uint', f'%ce{k}')
        emit(f'%sh{k}i = OpIAdd %uint {ce} %u1'); shi = loc('%uint', f'%sh{k}i'); emit(f'%sh{k}p = OpAccessChain %psu %tab %i0 {shi}'); emit(f'%sh{k} = OpLoad %uint %sh{k}p')
        emit(f'%sl{k}i = OpIAdd %uint {ce} %u0'); sli = loc('%uint', f'%sl{k}i'); emit(f'%sl{k}p = OpAccessChain %psu %tab %i0 {sli}'); emit(f'%sl{k} = OpLoad %uint %sl{k}p')
        emit(f'%s1{k} = OpULessThan %bool %sh{k} %a1'); emit(f'%s2{k} = OpIEqual %bool %sh{k} %a1'); emit(f'%s3{k} = OpULessThanEqual %bool %sl{k} %a0'); emit(f'%s4{k} = OpLogicalAnd %bool %s2{k} %s3{k}'); emit(f'%s5{k} = OpLogicalOr %bool %s1{k} %s4{k}')
        emit(f'%idx{k} = OpSelect %uint %s5{k} %cand{k} {idx}'); idx = f'%idx{k}'
    emit(f'OpStore %sel {idx}'); emit('OpBranch %found')
    # the found block
    emit('%found = OpLabel'); emit('%selv = OpLoad %uint %sel'); emit('OpStore %lastw %selv'); emit('%fnd = OpIMul %uint %selv %u8'); fnd = loc('%uint', '%fnd')
    emit(f'%fehi_i = OpIAdd %uint {fnd} %u3'); fi = loc('%uint', '%fehi_i'); emit(f'%fehip = OpAccessChain %psu %tab %i0 {fi}'); emit('%fehi = OpLoad %uint %fehip')
    emit(f'%felo_i = OpIAdd %uint {fnd} %u2'); fi2 = loc('%uint', '%felo_i'); emit(f'%felop = OpAccessChain %psu %tab %i0 {fi2}'); emit('%felo = OpLoad %uint %felop')
    emit('%f5 = OpULessThan %bool %a1 %fehi'); emit('%f6 = OpIEqual %bool %a1 %fehi'); emit('%f7 = OpULessThan %bool %a0 %felo'); emit('%f8 = OpLogicalAnd %bool %f6 %f7'); emit('%fblw = OpLogicalOr %bool %f5 %f8')
    emit('OpStore %inp %fblw'); emit('OpBranch %m1')
    # the merge: in a pool (the last entry held it, or the hint's or the search's does), else 0
    emit('%m1 = OpLabel'); emit('%inpv = OpLoad %bool %inp'); emit('OpSelectionMerge %skip None'); emit('OpBranchConditional %inpv %chosen %skip')
    # the chosen block
    emit('%chosen = OpLabel'); emit('%sel2 = OpLoad %uint %sel'); emit('%fnd2 = OpIMul %uint %sel2 %u8'); fnd2 = loc('%uint', '%fnd2')
    emit(f'%dlo_i = OpIAdd %uint {fnd2} %u4'); di = loc('%uint', '%dlo_i'); emit(f'%dlop = OpAccessChain %psu %tab %i0 {di}'); emit('%dlo = OpLoad %uint %dlop')
    emit(f'%dhi_i = OpIAdd %uint {fnd2} %u5'); di2 = loc('%uint', '%dhi_i'); emit(f'%dhip = OpAccessChain %psu %tab %i0 {di2}'); emit('%dhi = OpLoad %uint %dhip')
    emit('%hlo = OpIAdd %uint %a0 %dlo'); emit('%cy = OpULessThan %bool %hlo %a0'); emit('%cyv = OpSelect %uint %cy %u1 %u0'); emit('%hh1 = OpIAdd %uint %a1 %dhi'); emit('%hhi = OpIAdd %uint %hh1 %cyv')
    emit('%hv = OpCompositeConstruct %v2uint %hlo %hhi'); emit('%ha = OpBitcast %ulong %hv'); emit('%hq = OpConvertUToPtr %ppu %ha'); emit('%w = OpLoad %uint %hq Aligned 4'); emit('OpReturnValue %w')
    emit('%skip = OpLabel'); emit('OpReturnValue %u0')
    # the locals: a variable each, stored once, loaded where used
    vars_, stores = ['%sel = OpVariable %pfu Function', '%inp = OpVariable %pfb Function'], {}
    for n, ty, v in L: vars_.append(f'{n} = OpVariable %pfu Function'); stores[v] = n
    out = []
    for s in body:
        if s == '%VARS': out += vars_; continue
        out.append(s)
        m = s.split(' = ')[0] if ' = ' in s else None
        if m in stores: out.append(f'OpStore {stores[m]} {m}'); out.append(f'{stores[m]}_v = OpLoad %uint {stores[m]}')
    steps = sorted({1 << (12 - k) if search_steps == 13 else 1 << (search_steps - 1 - k) for k in range(search_steps)} | {0, 1, 2, 3, 4, 5, 6, 8, 11, 13, 21, 256, 8191})
    consts = '\n'.join(f'%u{v} = OpConstant %uint {v}' for v in steps)
    return f'''OpCapability Shader
OpCapability PhysicalStorageBufferAddresses
OpCapability Int64
OpExtension "SPV_KHR_physical_storage_buffer"
OpExtension "SPV_KHR_storage_buffer_storage_class"
OpMemoryModel PhysicalStorageBuffer64 GLSL450
OpEntryPoint GLCompute %main "main" %lid
OpExecutionMode %main LocalSize 64 1 1
OpName %helper "raw_load"
OpDecorate %lid BuiltIn LocalInvocationId
OpDecorate %ra ArrayStride 4
OpMemberDecorate %ob 0 Offset 0
OpDecorate %ob Block
OpDecorate %o DescriptorSet 0
OpDecorate %o Binding 3
OpDecorate %tab DescriptorSet 0
OpDecorate %tab Binding 4
%void = OpTypeVoid
%fn = OpTypeFunction %void
%uint = OpTypeInt 32 0
%int = OpTypeInt 32 1
%bool = OpTypeBool
%v2uint = OpTypeVector %uint 2
%v3uint = OpTypeVector %uint 3
%pfu = OpTypePointer Function %uint
%pfb = OpTypePointer Function %bool
%hfn = OpTypeFunction %uint %pfu %pfu
%pv3 = OpTypePointer Input %v3uint
%lid = OpVariable %pv3 Input
%ra = OpTypeRuntimeArray %uint
%ob = OpTypeStruct %ra
%pob = OpTypePointer StorageBuffer %ob
%psu = OpTypePointer StorageBuffer %uint
%o = OpVariable %pob StorageBuffer
%tab = OpVariable %pob StorageBuffer
%ppu = OpTypePointer PhysicalStorageBuffer %uint
%ulong = OpTypeInt 64 0
%ppr = OpTypePointer Private %uint
%nul = OpConstantNull %uint
%lastw = OpVariable %ppr Private %nul
%i0 = OpConstant %int 0
{consts}
%main = OpFunction %void None %fn
%ml = OpLabel
%va = OpVariable %pfu Function
%vb = OpVariable %pfu Function
%lv = OpLoad %v3uint %lid
%x = OpCompositeExtract %uint %lv 0
%pa = OpAccessChain %psu %o %i0 %x
%lo = OpLoad %uint %pa
%pb = OpAccessChain %psu %o %i0 %u1
%hi = OpLoad %uint %pb
OpStore %va %lo
OpStore %vb %hi
%r = OpFunctionCall %uint %helper %va %vb
%r2 = OpFunctionCall %uint %helper %va %vb
%s = OpIAdd %uint %r %r2
OpStore %pa %s
OpReturn
OpFunctionEnd
%helper = OpFunction %uint None %hfn
%hp0 = OpFunctionParameter %pfu
%hp1 = OpFunctionParameter %pfu
''' + '\n'.join(out) + '\nOpFunctionEnd\n'


def words(data): return struct.unpack('<%dI' % (len(data) // 4), data)


def ops(data):   # [(opcode, operands)]
    w = words(data); i = 5; out = []
    while i < len(w):
        n = w[i] >> 16; out.append((w[i] & 0xffff, w[i + 1:i + n])); i += max(n, 1)
    return out


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvGmCache(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 't.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_gmcache.h"\n{export} size_t run(const uint32_t *w, size_t n, uint32_t *sc, uint32_t *o, size_t cap, int *why) {{ return spv_gmcache(w, n, sc, o, cap, why); }}\n'
                       f'{export} int wanted(const uint32_t *w, size_t n) {{ return spv_gmcache_wanted(w, n); }}\n')
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
        cls.lib.run.restype = ctypes.c_size_t; cls.lib.run.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
        cls.lib.wanted.argtypes = [ctypes.c_void_p, ctypes.c_size_t]

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def asm(self, text, name, env='vulkan1.1'):
        (self.tmp / f'{name}.spvasm').write_text(text)
        subprocess.run([self.spv_as, '--target-env', env, self.tmp / f'{name}.spvasm', '-o', self.tmp / f'{name}.spv'], check=True)
        return (self.tmp / f'{name}.spv').read_bytes()

    def valid(self, data, name, env='vulkan1.1'):
        (self.tmp / f'{name}.out.spv').write_bytes(data)
        r = subprocess.run([self.spv_val, '--target-env', env, self.tmp / f'{name}.out.spv'], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def wanted(self, data): n = len(data) // 4; return self.lib.wanted((ctypes.c_uint32 * n).from_buffer_copy(data), n)

    def run_on(self, data, cap=None):   # → (the rewritten module or None, why)
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); cap = cap or 2 * n + 4096; o = (ctypes.c_uint32 * cap)()
        sc = (ctypes.c_uint32 * (4 * words(data)[3]))(); why = ctypes.c_int(-1)
        k = self.lib.run(w, n, sc, o, cap, ctypes.byref(why))
        return (bytes(o)[:4 * k] if k else None), why.value

    def table_loads(self, o, tab):   # the loads through access chains on the table variable, by the chain's result
        chains = {x[1]: x for op, x in o if op == 65 and x[2] == tab}
        return [x for op, x in o if op == 61 and x[2] in chains]

    def check(self, data, name, env='vulkan1.1'):
        self.assertTrue(self.wanted(data))
        out, why = self.run_on(data); self.assertIsNotNone(out, why); assert out is not None
        self.valid(out, name, env)
        o, oi = ops(out), ops(data)
        tab = next(x[0] for op, x in oi if op == 71 and x[1] == 33 and x[2] == 4)   # the variable at binding 4
        before, after = self.table_loads(oi, tab), self.table_loads(o, tab)
        self.assertEqual(len(before), len(after))   # the entry block's 4 and the delta's 2 go; the fill's 6 come
        priv = [x for op, x in o if op == 59 and x[2] == 6]; self.assertEqual(len(priv), 1 + 6)   # the index word and the six new ones, each with a null initializer
        self.assertTrue(all(len(x) == 4 for x in priv))
        pv = {x[1] for x in priv}
        ploads = [x for op, x in o if op == 61 and x[2] in pv]; pstores = [x for op, x in o if op == 62 and x[0] in pv]
        self.assertEqual(len(ploads), 1 + 4 + 2)   # the index's own load, the four range words, the two delta words
        self.assertEqual(len(pstores), 1 + 6)   # the index recorded, the six filled
        self.assertEqual(len([x for op, x in o if op == 120]), 1)   # the pointer as before
        return o

    def test_helper_hits_read_no_table_word(self):
        data = self.asm(helper(), 'cs')
        o = self.check(data, 'cs')
        # the entry block: from the label to its branch, no table load
        tab = next(x[0] for op, x in o if op == 71 and x[1] == 33 and x[2] == 4)
        fn = [i for i, (op, x) in enumerate(o) if op == 54]; hl = next(i for i in range(fn[1], len(o)) if o[i][0] == 248); br = next(i for i in range(hl, len(o)) if o[i][0] == 250)
        chains = {x[1] for op, x in o[hl:br] if op == 65 and x[2] == tab}
        self.assertFalse(chains)

    def test_ssa_form_too(self):   # the values not through locals (a later translator, or an optimizer's output)
        data = self.asm(helper(debug=False), 'ssa'); self.check(data, 'ssa')

    def test_spirv_14_interface(self):   # from SPIR-V 1.4 the entry point lists every global it uses: the new words are added
        data = self.asm(helper().replace('"main" %lid', '"main" %lid %o %tab %lastw'), 'cs14', 'vulkan1.1spv1.4')
        o = self.check(data, 'cs14', 'vulkan1.1spv1.4')
        ep = next(x for op, x in o if op == 15); priv = [x[1] for op, x in o if op == 59 and x[2] == 6]
        self.assertTrue(all(p in ep for p in priv))

    def test_other_form_left(self):   # a helper whose entry block reads another count of table words is not the translator's: left as it is
        text = helper().replace('%ehi = OpLoad %uint %ehip', '%ehi = OpCopyObject %uint %u0')
        data = self.asm(text, 'other'); out, why = self.run_on(data); self.assertIsNone(out); self.assertEqual(why, FORM)

    def test_pointers_without_the_lookup_left(self):   # physical pointers without the table (test_spv_noptr's module): not the translator's helper
        from test_spv_noptr import CS
        data = self.asm(CS, 'noptr'); out, why = self.run_on(data); self.assertIsNone(out); self.assertEqual(why, FORM)

    def test_room(self):
        data = self.asm(helper(), 'room'); out, why = self.run_on(data, cap=len(data) // 4 + 8); self.assertIsNone(out); self.assertEqual(why, ROOM)

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR (a game\'s packed spv folder) not set')
    def test_game_modules(self):   # every module with physical pointers of a game's folder: rewritten (or left for a reason), and valid
        d = Path(os.environ['DM_SPV_DIR']); n = done = 0; left = {}; bad = []
        for p in sorted(d.glob('*.spv')):
            data = p.read_bytes()
            if len(data) < 20 or not self.wanted(data): continue
            n += 1; out, why = self.run_on(data)
            if out is None: left[why] = left.get(why, 0) + 1; continue
            done += 1; env = ENV.get(words(data)[1], 'vulkan1.1')
            (self.tmp / 'g.spv').write_bytes(out)
            r = subprocess.run([self.spv_val, '--target-env', env, self.tmp / 'g.spv'], capture_output=True, text=True)
            if r.returncode: bad.append(f'{p.name}: {(r.stdout + r.stderr).strip()[:200]}')
        print(f'\n{n} modules with physical pointers in {d}: {done} rewritten, left {left}, invalid {len(bad)}')
        self.assertFalse(bad, '\n'.join(bad[:10]))
        self.assertGreater(done, 0)


if __name__ == '__main__':
    unittest.main()
