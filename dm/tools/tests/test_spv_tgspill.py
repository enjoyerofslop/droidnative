"""dm/android/spv_tgspill.h (compute shared memory past the GPU's limit moved into a storage buffer: Mario Kart World's 48 KB kernels on Qualcomm's Adreno 830 driver,
which takes 32 KB), built for the PC and run on modules assembled with the NDK's spirv-as; spirv-val checks each result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every compute module there that declares more than 32 KB (each rewritten module must pass spirv-val)."""
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

# A compute shader as the translator writes one with Maxwell's shared memory: a Workgroup array of uint the size the program declared (48 KB), written through
# access chains, a barrier with Workgroup memory semantics, an atomic on an element, and a second small array; the result goes to a storage buffer at binding 7
CS = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main" %wid %lid
OpExecutionMode %main LocalSize 64 1 1
OpName %sh "_44"
OpDecorate %wid BuiltIn WorkgroupId
OpDecorate %lid BuiltIn LocalInvocationId
OpDecorate %rt ArrayStride 4
OpMemberDecorate %ob 0 Offset 0
OpDecorate %ob Block
OpDecorate %o DescriptorSet 0
OpDecorate %o Binding 7
%void = OpTypeVoid
%fn = OpTypeFunction %void
%uint = OpTypeInt 32 0
%int = OpTypeInt 32 1
%v3 = OpTypeVector %uint 3
%pv3 = OpTypePointer Input %v3
%wid = OpVariable %pv3 Input
%lid = OpVariable %pv3 Input
%n = OpConstant %uint 12288
%n2 = OpConstant %uint 16
%arr = OpTypeArray %uint %n
%arr2 = OpTypeArray %uint %n2
%parr = OpTypePointer Workgroup %arr
%parr2 = OpTypePointer Workgroup %arr2
%pwu = OpTypePointer Workgroup %uint
%sh = OpVariable %parr Workgroup
%sh2 = OpVariable %parr2 Workgroup
%rt = OpTypeRuntimeArray %uint
%ob = OpTypeStruct %rt
%pob = OpTypePointer StorageBuffer %ob
%psu = OpTypePointer StorageBuffer %uint
%o = OpVariable %pob StorageBuffer
%i0 = OpConstant %int 0
%u1 = OpConstant %uint 1
%u2 = OpConstant %uint 2
%sem = OpConstant %uint 264
%c5 = OpConstant %int 5
%main = OpFunction %void None %fn
%l = OpLabel
%lv = OpLoad %v3 %lid
%x = OpCompositeExtract %uint %lv 0
%p = OpAccessChain %pwu %sh %x
OpStore %p %x
%q = OpAccessChain %pwu %sh2 %c5
OpStore %q %u1
OpControlBarrier %u2 %u2 %sem
%y = OpLoad %uint %p
%z = OpAtomicIAdd %uint %p %u2 %sem %u1
%r = OpLoad %uint %q
%s = OpIAdd %uint %y %r
%op = OpAccessChain %psu %o %i0 %x
OpStore %op %s
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
class SpvTgSpill(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 't.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_tgspill.h"\n{export} size_t run(const uint32_t *w, size_t n, uint32_t b, uint32_t *sc, uint32_t *o, size_t cap) {{ return spv_tgspill(w, n, b, sc, o, cap); }}\n'
                       f'{export} long long bytes(const uint32_t *w, size_t n, uint32_t *sc) {{ return spv_tgs_bytes(w, n, sc); }}\n')
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
        cls.lib.run.restype = ctypes.c_size_t; cls.lib.bytes.restype = ctypes.c_longlong

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

    def sc(self, data): return (ctypes.c_uint32 * (4 * words(data)[3]))()

    def bytes_of(self, data): n = len(data) // 4; return self.lib.bytes((ctypes.c_uint32 * n).from_buffer_copy(data), n, self.sc(data))

    def run_on(self, data, binding=110):   # → the rewritten module or None
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); cap = 4 * n + 1024; o = (ctypes.c_uint32 * cap)()
        k = self.lib.run(w, n, binding, self.sc(data), o, cap)
        return bytes(o)[:4 * k] if k else None

    def test_a_task_or_mesh_shaders_compute_form_spills(self):
        # spv_meshemu.py's compute form of a task / mesh kernel (a GPU without VK_EXT_mesh_shader runs it, gfx_vk_meshemu.inc) keeps the kernel's stage memory a
        # Workgroup array that only its access chains reach, so a kernel past the GPU's limit gets the storage buffer as a compute shader does
        import test_spv_mesh as tm, test_spv_meshemu as te   # their kernel, assembled with the same spirv-as
        for n, info in enumerate((tm.mesh_info(False, False), tm.mesh_info(True, False), {'kind': 'ts', 'threads': 32, 'payload': 256})):   # a mesh shader without and with a task, a task shader
            with self.subTest(kind=info['kind'], n=n):
                data, lay = te.kernel(info)
                out, keep = te.me.compute(data, info, lay)
                hdr, ins = te.sa.process(out, 'cs', None, keep)[:2]; cs = te.sa.emit(hdr, ins)
                self.assertGreater(self.bytes_of(cs), 0)
                sp = self.run_on(cs); self.assertIsNotNone(sp); assert sp is not None
                self.valid(sp, f'memu_{n}')
                self.assertFalse([x for op, x in ops(sp) if op == 59 and x[2] == 4])   # no Workgroup variable left

    def test_shared_memory_becomes_a_storage_buffer_region_per_workgroup(self):
        data = self.asm(CS, 'cs')
        self.assertEqual(self.bytes_of(data), (12288 + 16) * 4)
        out = self.run_on(data); self.assertIsNotNone(out); assert out is not None
        self.valid(out, 'cs')
        o = ops(out)
        self.assertFalse([x for op, x in o if op == 59 and x[2] == 4])   # no Workgroup variable left
        sb = [x[1] for op, x in o if op == 59 and x[2] == 12]   # StorageBuffer variables: binding 7's and the new one
        binds = {x[0]: x[2] for op, x in o if op == 71 and x[1] == 33}
        self.assertEqual(sorted(binds[v] for v in sb), [7, 110])
        nwg = [x[0] for op, x in o if op == 71 and x[1:] == (11, 24)]   # BuiltIn NumWorkgroups, made and in the entry point's interface
        self.assertEqual(len(nwg), 1)
        ep = [x for op, x in o if op == 15][0]; self.assertIn(nwg[0], ep[3:])
        consts = {x[1]: x[2] for op, x in o if op == 43 and len(x) == 3}
        bar = [x for op, x in o if op == 224][0]; self.assertEqual(consts[bar[2]], 264 | 0x40)   # the barrier orders the buffer too (UniformMemory)
        atom = [x for op, x in o if op == 234][0]; self.assertEqual(consts[atom[4]], 264 | 0x40)   # and so does the atomic
        self.assertIn(12304, consts.values())   # the region: 12,288 + 16 words a workgroup
        self.assertIn(12288, consts.values())   # the second array at its offset after the first
        self.assertFalse([x for op, x in o if op == 5 and x[0] in {y[1] for p, y in ops(data) if p == 59 and y[2] == 4}])   # nor their names

    def test_other_bindings_are_kept(self):
        out = self.run_on(self.asm(CS, 'cs2'), binding=200); assert out is not None
        o = ops(out); self.assertIn(200, {x[2] for op, x in o if op == 71 and x[1] == 33})

    def test_a_module_without_shared_memory_is_left_alone(self):
        plain = CS.replace('%sh = OpVariable %parr Workgroup\n%sh2 = OpVariable %parr2 Workgroup\n', '').replace('%p = OpAccessChain %pwu %sh %x\nOpStore %p %x\n', '').replace(
            '%q = OpAccessChain %pwu %sh2 %c5\nOpStore %q %u1\n', '').replace('%y = OpLoad %uint %p\n%z = OpAtomicIAdd %uint %p %u2 %sem %u1\n%r = OpLoad %uint %q\n%s = OpIAdd %uint %y %r\n',
            '%s = OpIAdd %uint %x %x\n').replace('OpName %sh "_44"\n', '')
        data = self.asm(plain, 'plain')
        self.assertEqual(self.bytes_of(data), 0); self.assertIsNone(self.run_on(data))

    def test_an_array_of_vectors_is_not_rewritten(self):
        vec = CS.replace('%arr2 = OpTypeArray %uint %n2\n', '%v4 = OpTypeVector %uint 4\n%arr2 = OpTypeArray %v4 %n2\n').replace(
            '%q = OpAccessChain %pwu %sh2 %c5\nOpStore %q %u1\n', '').replace('%r = OpLoad %uint %q\n%s = OpIAdd %uint %y %r\n', '%s = OpIAdd %uint %y %y\n')
        data = self.asm(vec, 'vec')
        self.assertEqual(self.bytes_of(data), -1); self.assertIsNone(self.run_on(data))

    def test_a_whole_array_use_is_not_rewritten(self):
        whole = CS.replace('OpReturn\n', '%all = OpLoad %arr2 %sh2\nOpReturn\n')
        data = self.asm(whole, 'whole')
        self.assertEqual(self.bytes_of(data), -2); self.assertIsNone(self.run_on(data))

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR (a game\'s packed spv folder) not set')
    def test_a_games_shaders(self):   # each compute module past 32 KB is rewritten and passes spirv-val
        d = Path(os.environ['DM_SPV_DIR']); n = 0; left = []
        for f in sorted(d.glob('*.spv')):
            data = f.read_bytes(); b = self.bytes_of(data)
            if b <= 32768: continue
            out = self.run_on(data)
            if out is None: left.append(f.name); continue
            self.valid(out, f.stem); n += 1
        print(f'{n} modules past 32 KB rewritten and valid, {len(left)} left as they are: {left[:5]}', file=sys.stderr)
        self.assertFalse(left)


if __name__ == '__main__':
    unittest.main()
