"""dm/android/spv_e5.h (an E5B9G9R9 storage image stored through an R32_UINT view, the compute shader packing RGB9E5), built for the PC and run on modules
assembled with the NDK's spirv-as; spirv-val checks each result, and a guard after the words it asked for checks that it writes no further. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every compute module there with a storage image, each of its storage image bindings in turn (each
result must pass spirv-val).
With DM_TEST_SERIAL=<adb serial>, dm/android/tests/t_e5_store.c is built for Android and run on that device: the rewritten shader stores chosen floats (0,
denormals, NaN, infinities, the largest value, the 511 / 512 rounding edges, and random ones) into an E5B9G9R9 image through its R32_UINT view, and every word
must be what Vulkan's shared exponent conversion makes of them (e5_ref below)."""
import ctypes
import math
import os
from pathlib import Path
import random
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spv_readonly import NDK, HOST, EXE, REPO   # noqa: E402
from test_spv_limits import instructions   # noqa: E402

DONE, KEPT = 1, 2   # SPV_E5_*
GUARD = 0xa5a5a5a5
N_TEXELS = 256   # t_e5_store's 16 x 16 image


def e5_ref(r, g, b):   # Vulkan's conversion of three floats to E5B9G9R9 (Shared Exponent Formats): N 9, B 15, Emax 31
    top = 511 / 512 * 2.0 ** 16
    def clamp(c): return 0.0 if c != c else max(0.0, min(top, c))
    rc, gc, bc = clamp(r), clamp(g), clamp(b)
    m = max(rc, gc, bc)
    e = math.frexp(m)[1] - 1 if m > 0 else -1000   # floor(log2(m)), exactly
    exp = max(-16, e) + 16
    if math.floor(m / 2.0 ** (exp - 24) + 0.5) == 512: exp += 1
    def s(c): return math.floor(c / 2.0 ** (exp - 24) + 0.5)
    return s(rc) | s(gc) << 9 | s(bc) << 18 | exp << 27


def f32(x): return struct.unpack('<f', struct.pack('<f', x))[0]


def texels():   # the device test's inputs, as float32
    edge = [0.0, 1.0, 0.5, 65408.0, 65409.0, 1e9, float('inf'), float('-inf'), float('nan'), -1.0, -0.0, 1e-45, 1e-40, 2.0 ** -16, 2.0 ** -17, 2.0 ** -24, 2.0 ** -25,
            511.0, 511.5, 511.49997, 1023.0, 1023.5, 1.0 / 3.0, 3.14159, 255.75, 0.00001]
    rnd = random.Random(5)
    out = []
    for i in range(N_TEXELS):
        if i < len(edge) * 3:   # each edge value as the largest channel and beside other values
            a = edge[i // 3]; v = [(a, 0.25, 0.125), (0.5, a, 1.0), (a, a * 0.5 if a == a else a, 2.0 ** -20)][i % 3]
        else:
            v = tuple(rnd.uniform(0, 2.0 ** rnd.uniform(-20, 16)) for _ in range(3))
        out.append(tuple(f32(c) for c in v) + (1.0,))
    return out


# A compute shader as the translator writes an image store: a float storage image of unknown format (binding 1), the texel read from a storage buffer (binding 0)
CS = '''OpCapability Shader
OpCapability StorageImageWriteWithoutFormat
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main" %gid
OpExecutionMode %main LocalSize 16 16 1
OpDecorate %gid BuiltIn GlobalInvocationId
OpDecorate %arr ArrayStride 16
OpMemberDecorate %blk 0 Offset 0
OpDecorate %blk Block
OpDecorate %buf DescriptorSet 0
OpDecorate %buf Binding 0
OpDecorate %img DescriptorSet 0
OpDecorate %img Binding 1
%void = OpTypeVoid
%fn = OpTypeFunction %void
%u32 = OpTypeInt 32 0
%i32 = OpTypeInt 32 1
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%v3u = OpTypeVector %u32 3
%v2i = OpTypeVector %i32 2
%arr = OpTypeRuntimeArray %v4
%blk = OpTypeStruct %arr
%pbuf = OpTypePointer StorageBuffer %blk
%buf = OpVariable %pbuf StorageBuffer
%pv4 = OpTypePointer StorageBuffer %v4
%pgid = OpTypePointer Input %v3u
%gid = OpVariable %pgid Input
%imt = OpTypeImage %f32 2D 0 0 0 2 Unknown
%pim = OpTypePointer UniformConstant %imt
%img = OpVariable %pim UniformConstant
%u0 = OpConstant %u32 0
%u16 = OpConstant %u32 16
%main = OpFunction %void None %fn
%l = OpLabel
%g = OpLoad %v3u %gid
%x = OpCompositeExtract %u32 %g 0
%y = OpCompositeExtract %u32 %g 1
%row = OpIMul %u32 %y %u16
%idx = OpIAdd %u32 %row %x
%p = OpAccessChain %pv4 %buf %u0 %idx
%v = OpLoad %v4 %p
%xi = OpBitcast %i32 %x
%yi = OpBitcast %i32 %y
%c = OpCompositeConstruct %v2i %xi %yi
%im = OpLoad %imt %img
OpImageWrite %im %c %v
OpReturn
OpFunctionEnd
'''
# The same with a read of the image back before the store (its texel added), and an image size query
CS_READ = (CS.replace('OpCapability StorageImageWriteWithoutFormat\n', 'OpCapability StorageImageWriteWithoutFormat\nOpCapability StorageImageReadWithoutFormat\nOpCapability ImageQuery\n')
           .replace('%im = OpLoad %imt %img\nOpImageWrite %im %c %v\n',
                    '%im = OpLoad %imt %img\n%old = OpImageRead %v4 %im %c\n%sz = OpImageQuerySize %v2i %im\n%sum = OpFAdd %v4 %old %v\nOpImageWrite %im %c %sum\n'))

# A raw store (Maxwell's SUST.B) as the translator writes it: the word the game packed itself, as the bits of a float, and three zeros
CS_RAW = (CS.replace('%u16 = OpConstant %u32 16\n', '%u16 = OpConstant %u32 16\n%f0 = OpConstant %f32 0\n')
          .replace('%im = OpLoad %imt %img\nOpImageWrite %im %c %v\n',
                   '%vx = OpCompositeExtract %f32 %v 0\n%wd = OpBitcast %u32 %vx\n%bc = OpBitcast %f32 %wd\n%t = OpCompositeConstruct %v4 %bc %f0 %f0 %f0\n%im = OpLoad %imt %img\nOpImageWrite %im %c %t\n'))


def raw_words():   # the raw device test's words: RGB9E5 words of texels(), and words whose bits read as a float NaN or infinity (exponent 31, blue's top bits set)
    rnd = random.Random(7)
    return [e5_ref(*t[:3]) for t in texels()[:200]] + [0x7f800000 | rnd.getrandbits(23) for _ in range(28)] + [0xff800000 | rnd.getrandbits(23) for _ in range(28)]


def ops(data): return [op for op, _ in instructions(data)]


@unittest.skipUnless(NDK, 'needs the Android NDK (shader-tools)')
class SpvE5(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'e.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_e5.h"\n{export} size_t run(const uint32_t *w, size_t n, uint64_t mask, uint32_t *s, uint32_t *o, size_t cap, size_t *need, int *what) '
                       f'{{ return spv_e5(w, n, mask, s, o, cap, need, what); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone, as test_spv_limits
            subprocess.run([cls.bin / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-Werror', '-I', REPO / 'dm/android', '-c', src,
                            '-o', cls.tmp / 'e.obj'], check=True)
            subprocess.run([cls.bin / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "e.dll"}', str(cls.tmp / 'e.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'e.dll'))
        else:
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or cls.bin / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'e.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'e.so'))
        p32 = ctypes.POINTER(ctypes.c_uint32)   # every argument typed: an untyped size_t or uint64 is passed as an int (test_spv_pool's segfault on the Linux runner)
        cls.lib.run.argtypes = [p32, ctypes.c_size_t, ctypes.c_uint64, p32, p32, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_int)]
        cls.lib.run.restype = ctypes.c_size_t

    def run_on(self, data, mask):   # → (the rewritten module or None, SPV_E5_* bits)
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data)
        s = (ctypes.c_uint32 * (5 * w[3]))(); need = ctypes.c_size_t(); what = ctypes.c_int()
        self.assertEqual(self.lib.run(w, n, mask, s, None, 0, ctypes.byref(need), ctypes.byref(what)), 0)
        if not need.value: return None, what.value
        cap = need.value; o = (ctypes.c_uint32 * (cap + 64))(*[GUARD] * (cap + 64))
        k = self.lib.run(w, n, mask, s, o, cap, ctypes.byref(need), ctypes.byref(what))
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

    def r32ui_images(self, data): return [x for op, x in instructions(data) if op == 25 and x[6] == 2 and x[7] == 33]   # OpTypeImage ... sampled 2, R32ui

    def test_store_packed(self):
        out, what = self.run_on(self.asm(CS, 'cs'), 1 << 1)
        self.assertEqual(what, DONE)
        self.val(out, 'cs_out.spv')
        self.assertEqual(len(self.r32ui_images(out)), 1)
        o = ops(out)
        self.assertEqual(o.count(99), 1)   # the store stays one store
        self.assertEqual(o.count(12), 3 + 2 + 1 + 1 + 1 + 2 * 3)   # GLSL: NClamp 3, NMax 2, SMax, Ldexp and Floor for the exponent, Ldexp and Floor per channel
        self.assertGreaterEqual(o.count(196), 3)   # the shifts into place: green 9, blue 18, exponent 27

    def test_read_unpacked(self):
        out, what = self.run_on(self.asm(CS_READ, 'csr'), 1 << 1)
        self.assertEqual(what, DONE)
        self.val(out, 'csr_out.spv')
        o = ops(out)
        self.assertEqual((o.count(98), o.count(99), o.count(104)), (1, 1, 1))   # the read, the store and the size query stay
        self.assertGreaterEqual(o.count(112), 3)   # OpConvertUToF: the three mantissas

    def test_raw_store_kept_as_bits(self):   # no packing: the word goes to the R32ui image as it is
        out, what = self.run_on(self.asm(CS_RAW, 'csraw'), 1 << 1)
        self.assertEqual(what, DONE)
        self.val(out, 'csraw_out.spv')
        o = ops(out)
        self.assertEqual((o.count(99), o.count(12)), (1, 0))   # one store, no GLSL instruction (no clamp, exponent or rounding)
        self.assertEqual(len(self.r32ui_images(out)), 1)

    def test_other_binding_left(self):
        self.assertEqual(self.run_on(self.asm(CS, 'cs_other'), 1 << 0 | 1 << 2), (None, 0))

    def test_other_use_kept(self):   # a format query has no answer for an R32ui image that stands for E5B9G9R9
        text = CS.replace('OpCapability StorageImageWriteWithoutFormat\n', 'OpCapability StorageImageWriteWithoutFormat\nOpCapability Kernel\n') \
                 .replace('OpImageWrite %im %c %v\n', 'OpImageWrite %im %c %v\n%qf = OpImageQueryFormat %u32 %im\n')
        p = self.tmp / 'cs_q.spvasm'; p.write_text(text)
        subprocess.run([self.spv_as, '--target-env', 'vulkan1.1', p, '-o', self.tmp / 'cs_q.spv'], check=True)   # not a valid Vulkan module (a Kernel query): scanned only
        self.assertEqual(self.run_on((self.tmp / 'cs_q.spv').read_bytes(), 1 << 1), (None, KEPT))

    def test_reference(self):   # e5_ref against values worked by hand from the specification
        self.assertEqual(e5_ref(0, 0, 0), 0)
        self.assertEqual(e5_ref(1.0, 0, 0), 256 | 16 << 27)   # 1 = 256 × 2^(16 - 24)
        self.assertEqual(e5_ref(65408.0, 0, 0), 511 | 31 << 27)   # the largest
        self.assertEqual(e5_ref(1e9, float('nan'), -1.0), 511 | 31 << 27)   # clamped; NaN and negatives 0
        self.assertEqual(e5_ref(511.99, 0, 0), 256 | 25 << 27)   # rounds to 512 at exponent 24: one more, 256 × 2
        self.assertEqual(e5_ref(2.0 ** -17, 0, 0), 128)   # under the smallest exponent: exponent 0, mantissa 2^-17 / 2^-24

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR not set')
    def test_packed_shaders(self):
        n = done = bad = 0
        for p in sorted(Path(os.environ['DM_SPV_DIR']).glob('*.spv')):
            data = p.read_bytes()
            if len(data) < 20 or not any(op == 15 and x[0] == 5 for op, x in instructions(data)): continue   # compute modules only
            imgs = {x[0] for op, x in instructions(data) if op == 25 and x[6] == 2}
            ptrs = {x[0] for op, x in instructions(data) if op == 32 and x[1] == 0 and x[2] in imgs}
            vars_ = {x[1] for op, x in instructions(data) if op == 59 and x[0] in ptrs}
            for b in sorted({x[2] for op, x in instructions(data) if op == 71 and x[1] == 33 and x[0] in vars_}):
                if b >= 64: continue
                n += 1; out, what = self.run_on(data, 1 << b)
                if out is None: continue
                done += 1; q = self.tmp / 'pk.spv'; q.write_bytes(out)
                r = subprocess.run([self.spv_val, '--target-env', 'vulkan1.1', q], capture_output=True, text=True)
                if r.returncode: bad += 1; print(p.name, b, r.stdout[:300])
        print(f'{n} storage image bindings of compute modules; {done} rewritten; {bad} failed spirv-val')
        self.assertEqual(bad, 0)

    @unittest.skipUnless(os.environ.get('DM_TEST_SERIAL'), 'DM_TEST_SERIAL not set')
    def test_store_on_a_device(self):
        serial = os.environ['DM_TEST_SERIAL']
        adb = shutil.which('adb') or str(Path(os.environ.get('ANDROID_HOME', '')) / 'platform-tools' / f'adb{EXE}')
        exe = self.tmp / 't_e5_store'
        cc = self.bin / ('aarch64-linux-android29-clang' + ('.cmd' if os.name == 'nt' else ''))
        subprocess.run([cc, '-O1', '-Wall', '-Werror', REPO / 'dm/android/tests/t_e5_store.c', '-lvulkan', '-o', exe], check=True)
        out, what = self.run_on(self.asm(CS, 'dev_cs'), 1 << 1); self.assertEqual(what, DONE); assert out is not None
        (self.tmp / 'cs.spv').write_bytes(out)
        tx = texels(); (self.tmp / 'in.bin').write_bytes(b''.join(struct.pack('<4f', *t) for t in tx))
        d = '/data/local/tmp/dm_e5_store'
        subprocess.run([adb, '-s', serial, 'shell', 'mkdir', '-p', d], check=True)
        for f in (exe, self.tmp / 'cs.spv', self.tmp / 'in.bin'): subprocess.run([adb, '-s', serial, 'push', f, d], check=True, capture_output=True)
        r = subprocess.run([adb, '-s', serial, 'shell', f'cd {d} && chmod 755 t_e5_store && ./t_e5_store cs.spv in.bin out.bin; echo "exit $?"'], capture_output=True, text=True)
        print(r.stdout.strip())
        subprocess.run([adb, '-s', serial, 'pull', f'{d}/out.bin', self.tmp / 'out.bin'], check=True, capture_output=True)
        subprocess.run([adb, '-s', serial, 'shell', 'rm', '-r', d], capture_output=True)
        self.assertTrue(r.stdout.strip().endswith('exit 0'), r.stdout)
        got = struct.unpack(f'<{N_TEXELS}I', (self.tmp / 'out.bin').read_bytes()[:4 * N_TEXELS])
        wrong = [(i, tx[i][:3], hex(got[i]), hex(e5_ref(*tx[i][:3]))) for i in range(N_TEXELS) if got[i] != e5_ref(*tx[i][:3])]
        self.assertEqual(wrong[:8], [], f'{len(wrong)} of {N_TEXELS} words differ from the specification')
        # a raw store: each word back exactly, those whose bits read as NaN too
        out, what = self.run_on(self.asm(CS_RAW, 'dev_raw'), 1 << 1); self.assertEqual(what, DONE); assert out is not None
        rw = raw_words(); (self.tmp / 'raw.spv').write_bytes(out); (self.tmp / 'rin.bin').write_bytes(b''.join(struct.pack('<4I', x, 0, 0, 0) for x in rw))
        subprocess.run([adb, '-s', serial, 'shell', 'mkdir', '-p', d], check=True)
        for f in (exe, self.tmp / 'raw.spv', self.tmp / 'rin.bin'): subprocess.run([adb, '-s', serial, 'push', f, d], check=True, capture_output=True)
        r = subprocess.run([adb, '-s', serial, 'shell', f'cd {d} && chmod 755 t_e5_store && ./t_e5_store raw.spv rin.bin rout.bin; echo "exit $?"'], capture_output=True, text=True)
        print(r.stdout.strip())
        subprocess.run([adb, '-s', serial, 'pull', f'{d}/rout.bin', self.tmp / 'rout.bin'], check=True, capture_output=True)
        subprocess.run([adb, '-s', serial, 'shell', 'rm', '-r', d], capture_output=True)
        self.assertTrue(r.stdout.strip().endswith('exit 0'), r.stdout)
        got = struct.unpack(f'<{N_TEXELS}I', (self.tmp / 'rout.bin').read_bytes()[:4 * N_TEXELS])
        wrong = [(i, hex(rw[i]), hex(got[i])) for i in range(N_TEXELS) if got[i] != rw[i]]
        self.assertEqual(wrong[:8], [], f'{len(wrong)} of {N_TEXELS} raw words changed')


if __name__ == '__main__':
    unittest.main()
