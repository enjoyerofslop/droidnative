"""dm/android/spv_noptr.h (raw global memory without physical pointers: each OpConvertUToPtr of the translator's raw helper, and the loads, stores and atomics through it, made
accesses into a runtime array of storage buffers indexed by the address's high word, for drivers that reject OpConvertUToPtr: the Ayn Odin 2's Adreno 740, the Razr's 730),
built for the PC and run on modules assembled with the NDK's spirv-as; spirv-val checks each result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there that declares physical pointers: each must be rewritten and pass spirv-val."""
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

FORM, USE, TYPE = 1, 2, 3   # spv_noptr.h's reasons
ENV = {0x103: 'vulkan1.1', 0x104: 'vulkan1.1spv1.4', 0x105: 'vulkan1.2', 0x106: 'vulkan1.3'}   # spirv-val's environment for a module's SPIR-V version

# A compute shader in the translator's raw-memory form (Ocarina of Time's fog shader, local disassembly): a helper function adds the table entry's delta to the address in two
# 32-bit halves, builds a v2uint, bitcasts it to ulong and makes it a PhysicalStorageBuffer pointer, which it loads through (a uint, a uvec4, a vec4 stored back); main also
# stores and adds atomically through a pointer of its own, and keeps the results in a storage buffer at binding 3
CS = '''OpCapability Shader
OpCapability PhysicalStorageBufferAddresses
OpCapability Int64
OpExtension "SPV_KHR_physical_storage_buffer"
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel PhysicalStorageBuffer64 GLSL450
OpEntryPoint GLCompute %main "main" %lid
OpExecutionMode %main LocalSize 64 1 1
OpName %ppu "_ptr_PhysicalStorageBuffer_uint"
OpName %helper "raw_load"
OpDecorate %lid BuiltIn LocalInvocationId
OpDecorate %ra ArrayStride 4
OpMemberDecorate %ob 0 Offset 0
OpDecorate %ob Block
OpDecorate %o DescriptorSet 0
OpDecorate %o Binding 3
%void = OpTypeVoid
%fn = OpTypeFunction %void
%uint = OpTypeInt 32 0
%int = OpTypeInt 32 1
%float = OpTypeFloat 32
%bool = OpTypeBool
%v2uint = OpTypeVector %uint 2
%v3uint = OpTypeVector %uint 3
%v4uint = OpTypeVector %uint 4
%v4float = OpTypeVector %float 4
%pfu = OpTypePointer Function %uint
%hfn = OpTypeFunction %uint %pfu %pfu
%pv3 = OpTypePointer Input %v3uint
%lid = OpVariable %pv3 Input
%ra = OpTypeRuntimeArray %uint
%ob = OpTypeStruct %ra
%pob = OpTypePointer StorageBuffer %ob
%psu = OpTypePointer StorageBuffer %uint
%o = OpVariable %pob StorageBuffer
%ppu = OpTypePointer PhysicalStorageBuffer %uint
%ulong = OpTypeInt 64 0
%ppv4 = OpTypePointer PhysicalStorageBuffer %v4uint
%ppf4 = OpTypePointer PhysicalStorageBuffer %v4float
%i0 = OpConstant %int 0
%u0 = OpConstant %uint 0
%u1 = OpConstant %uint 1
%u2 = OpConstant %uint 2
%dev = OpConstant %uint 1
%sem = OpConstant %uint 0
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
%v = OpCompositeConstruct %v2uint %lo %hi
%a = OpBitcast %ulong %v
%p = OpConvertUToPtr %ppu %a
OpStore %p %r Aligned 4
%old = OpAtomicIAdd %uint %p %dev %sem %u1
%s = OpIAdd %uint %r %old
OpStore %pa %s
OpReturn
OpFunctionEnd
%helper = OpFunction %uint None %hfn
%hp0 = OpFunctionParameter %pfu
%hp1 = OpFunctionParameter %pfu
%hl = OpLabel
%a0 = OpLoad %uint %hp0
%a1 = OpLoad %uint %hp1
%d0 = OpIAdd %uint %a0 %u2
%cy = OpULessThan %bool %d0 %a0
%c = OpSelect %uint %cy %u1 %u0
%d1 = OpIAdd %uint %a1 %c
%hv = OpCompositeConstruct %v2uint %d0 %d1
%ha = OpBitcast %ulong %hv
%hq = OpConvertUToPtr %ppu %ha
%w = OpLoad %uint %hq Aligned 4
%hq4 = OpConvertUToPtr %ppv4 %ha
%w4 = OpLoad %v4uint %hq4 Aligned 4
%hf = OpConvertUToPtr %ppf4 %ha
%f4 = OpLoad %v4float %hf Aligned 4
OpStore %hf %f4 Aligned 4
%e = OpCompositeExtract %uint %w4 2
%sum = OpIAdd %uint %w %e
OpReturnValue %sum
OpFunctionEnd
'''


def words(data): return struct.unpack('<%dI' % (len(data) // 4), data)


def ops(data):   # [(opcode, operands)]
    w = words(data); i = 5; out = []
    while i < len(w):
        n = w[i] >> 16; out.append((w[i] & 0xffff, w[i + 1:i + n])); i += max(n, 1)
    return out


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvNoPtr(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 't.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_noptr.h"\n{export} size_t run(const uint32_t *w, size_t n, uint32_t *sc, uint32_t *o, size_t cap, int *why) {{ return spv_noptr(w, n, sc, o, cap, why); }}\n'
                       f'{export} int wanted(const uint32_t *w, size_t n) {{ return spv_noptr_wanted(w, n); }}\n')
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
        cls.lib.run.restype = ctypes.c_size_t

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
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); cap = cap or 4 * n + 1024; o = (ctypes.c_uint32 * cap)()
        sc = (ctypes.c_uint32 * (3 * words(data)[3]))(); why = ctypes.c_int(-1)
        k = self.lib.run(w, n, sc, o, cap, ctypes.byref(why))
        return (bytes(o)[:4 * k] if k else None), why.value

    def check_rewritten(self, out, nacc):   # what every rewritten module has
        o = ops(out)
        self.assertFalse([x for op, x in o if op == 120])   # no OpConvertUToPtr
        self.assertFalse([x for op, x in o if op == 32 and x[1] == 5349])   # nor PhysicalStorageBuffer pointers
        caps = {x[0] for op, x in o if op == 17}
        self.assertNotIn(5347, caps); self.assertTrue({5301, 5302, 5308} <= caps)
        self.assertEqual([x[0] for op, x in o if op == 14], [0])   # Logical addressing
        sets = {x[0]: x[2] for op, x in o if op == 71 and x[1] == 34}; binds = {x[0]: x[2] for op, x in o if op == 71 and x[1] == 33}
        pools = [v for v, s in sets.items() if s == 5]; self.assertEqual(len(pools), 1); self.assertEqual(binds[pools[0]], 0)   # set 5, binding 0
        nonuni = {x[0] for op, x in o if op == 71 and x[1] == 5300}
        acc = [x for op, x in o if op == 65 and x[2] == pools[0]]   # the accesses: pools[slot].d[word]
        self.assertEqual(len(acc), nacc)
        self.assertTrue(all(a[1] in nonuni and a[3] in nonuni for a in acc))   # each access and its slot NonUniform
        return o

    def test_pointer_accesses_become_descriptor_array_accesses(self):
        data = self.asm(CS, 'cs'); self.assertTrue(self.wanted(data))
        out, why = self.run_on(data); self.assertIsNotNone(out, why); assert out is not None
        self.valid(out, 'cs')
        # main: a store and an atomic (2); the helper: a uint load, a uvec4 load, a vec4 load and a vec4 store (1 + 4 + 4 + 4)
        o = self.check_rewritten(out, 2 + 1 + 4 + 4 + 4)
        self.assertNotIn(11, {x[0] for op, x in o if op == 17})   # Int64 goes with the bitcasts: the Odin 2's 740 has no shaderInt64
        self.assertFalse([x for op, x in o if op == 21 and x[1] == 64])
        self.assertNotIn(b'SPV_KHR_physical_storage_buffer', out); self.assertIn(b'SPV_EXT_descriptor_indexing', out)
        self.assertEqual(len([x for op, x in o if op == 234]), 1)   # the atomic stays, on the access
        self.assertEqual(len([x for op, x in o if op == 194]), 4)   # a word index per conversion (main's one, the helper's three)
        self.assertNotIn(b'_ptr_PhysicalStorageBuffer_uint', out); self.assertIn(b'raw_load', out)   # the pointer type's name goes with it, others stay

    def test_spirv_1_5_puts_the_array_in_the_interface(self):
        data = self.asm(CS.replace('"main" %lid', '"main" %lid %o'), 'cs15', 'vulkan1.2')   # (from SPIR-V 1.4 every global the entry point uses is in its interface)
        out, why = self.run_on(data); self.assertIsNotNone(out, why); assert out is not None
        self.valid(out, 'cs15', 'vulkan1.2')
        o = self.check_rewritten(out, 15)
        pools = [x[0] for op, x in o if op == 71 and x[1] == 34 and x[2] == 5]
        ep = [x for op, x in o if op == 15][0]; self.assertIn(pools[0], ep[3:])
        self.assertNotIn(b'SPV_EXT_descriptor_indexing', out)   # core from SPIR-V 1.5

    def test_ulong_used_elsewhere_keeps_int64(self):
        data = self.asm(CS.replace('%i0 = OpConstant %int 0\n', '%i0 = OpConstant %int 0\n%k = OpConstant %ulong 5\n').replace(
            '%s = OpIAdd %uint %r %old\n', '%kv = OpBitcast %v2uint %k\n%ke = OpCompositeExtract %uint %kv 0\n%s = OpIAdd %uint %ke %old\n'), 'keep64')
        out, why = self.run_on(data); self.assertIsNotNone(out, why); assert out is not None
        self.valid(out, 'keep64')
        o = self.check_rewritten(out, 15)
        self.assertIn(11, {x[0] for op, x in o if op == 17}); self.assertTrue([x for op, x in o if op == 21 and x[1] == 64])

    def test_a_pointer_used_otherwise_is_left(self):
        data = self.asm(CS.replace('OpStore %p %r Aligned 4\n', '%pc = OpCopyObject %ppu %p\nOpStore %pc %r Aligned 4\n'), 'copy')
        self.assertEqual(self.run_on(data), (None, USE))

    def test_a_pointer_bitcast_from_a_vector_is_left(self):   # GL_EXT_buffer_reference_uvec2's form, not the translator's
        data = self.asm(CS.replace('OpStore %p %r Aligned 4\n', '%pv = OpBitcast %ppu %v\nOpStore %pv %r Aligned 4\n'), 'bitcast')
        self.assertEqual(self.run_on(data), (None, USE))

    def test_a_64_bit_pointee_is_left(self):
        data = self.asm(CS.replace('%ppf4 = OpTypePointer PhysicalStorageBuffer %v4float\n', '%ppf4 = OpTypePointer PhysicalStorageBuffer %v4float\n%ppl = OpTypePointer PhysicalStorageBuffer %ulong\n').replace(
            'OpStore %hf %f4 Aligned 4\n', 'OpStore %hf %f4 Aligned 4\n%hl8 = OpConvertUToPtr %ppl %ha\n%l8 = OpLoad %ulong %hl8 Aligned 8\n'), 'u64')
        self.assertEqual(self.run_on(data), (None, TYPE))

    def test_out_too_small_is_refused(self):
        data = self.asm(CS, 'small')
        out, why = self.run_on(data, cap=len(data) // 4 + 8); self.assertIsNone(out); self.assertEqual(why, 4)

    def test_a_module_without_pointers_is_left(self):
        plain = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main"
OpExecutionMode %main LocalSize 1 1 1
%void = OpTypeVoid
%fn = OpTypeFunction %void
%main = OpFunction %void None %fn
%l = OpLabel
OpReturn
OpFunctionEnd
'''
        data = self.asm(plain, 'plain'); self.assertFalse(self.wanted(data)); self.assertEqual(self.run_on(data), (None, 0))

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR (a game\'s packed spv folder) not set')
    def test_a_games_shaders(self):   # each module with physical pointers is rewritten and passes spirv-val
        d = Path(os.environ['DM_SPV_DIR']); n = 0; left = {}; bad = []
        for f in sorted(d.glob('*.spv')):
            data = f.read_bytes()
            if not self.wanted(data): continue
            out, why = self.run_on(data)
            if out is None: left.setdefault(why, []).append(f.name); continue
            env = ENV.get(words(data)[1] >> 8 & 0xffff, 'vulkan1.3')   # the module's own SPIR-V version
            (self.tmp / 'g.spv').write_bytes(out)
            r = subprocess.run([self.spv_val, '--target-env', env, self.tmp / 'g.spv'], capture_output=True, text=True)
            if r.returncode: bad.append((f.name, (r.stdout + r.stderr).strip()[:300])); continue
            n += 1
        print(f'{n} modules with physical pointers rewritten and valid, left as they are: {dict((k, (len(v), v[:3])) for k, v in left.items())}, invalid: {len(bad)} {bad[:3]}', file=sys.stderr)
        self.assertFalse(left); self.assertFalse(bad)


if __name__ == '__main__':
    unittest.main()
