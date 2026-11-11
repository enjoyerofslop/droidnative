"""dm/android/spv_bind.h (a stage set's far-apart binding numbers made dense, the same map for the module's OpDecorate Binding and the layout), built for the PC with
the Android NDK's clang and run on a module assembled with its spirv-as; spirv-val checks the result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there with the map sh_get makes from its res.json: no two of a set's resources may end up
at one number, and each module it changes must pass spirv-val."""
import ctypes
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spv_readonly import NDK, HOST, EXE, REPO   # noqa: E402

FROM, BASE, MAX = 1024, 128, 32   # SPV_BIND_FROM, SPV_BIND_BASE, SPV_BIND_MAX

# A fragment shader with two uniform buffers in its set (1) at the translator's far-apart numbers beside a small one, and a texture array in the pool set (4)
FS = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %col
OpExecutionMode %main OriginUpperLeft
OpDecorate %col Location 0
OpDecorate %blk Block
OpMemberDecorate %blk 0 Offset 0
OpDecorate %cb_big DescriptorSet 1
OpDecorate %cb_big Binding 2101266
OpDecorate %cb_big2 DescriptorSet 1
OpDecorate %cb_big2 Binding 2101267
OpDecorate %cb_small DescriptorSet 1
OpDecorate %cb_small Binding 5
OpDecorate %pool DescriptorSet 4
OpDecorate %pool Binding 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%blk = OpTypeStruct %v4
%pblk = OpTypePointer Uniform %blk
%cb_big = OpVariable %pblk Uniform
%cb_big2 = OpVariable %pblk Uniform
%cb_small = OpVariable %pblk Uniform
%img = OpTypeImage %f32 2D 0 0 0 1 Unknown
%u32 = OpTypeInt 32 0
%c8 = OpConstant %u32 8
%arr = OpTypeArray %img %c8
%parr = OpTypePointer UniformConstant %arr
%pool = OpVariable %parr UniformConstant
%pout = OpTypePointer Output %v4
%col = OpVariable %pout Output
%i32 = OpTypeInt 32 1
%c0 = OpConstant %i32 0
%pv4 = OpTypePointer Uniform %v4
%main = OpFunction %void None %fn
%l = OpLabel
%a = OpAccessChain %pv4 %cb_big %c0
%x = OpLoad %v4 %a
%b = OpAccessChain %pv4 %cb_big2 %c0
%y = OpLoad %v4 %b
%c = OpAccessChain %pv4 %cb_small %c0
%z = OpLoad %v4 %c
%s = OpFAdd %v4 %x %y
%t = OpFAdd %v4 %s %z
OpStore %col %t
OpReturn
OpFunctionEnd
'''


def bindings(data):   # {id: (set, binding)} from the module's decorations
    w = struct.unpack(f'<{len(data) // 4}I', data); i, out = 5, {}
    while i < len(w):
        n, op = w[i] >> 16, w[i] & 0xffff
        if op == 71 and n == 4 and w[i + 2] in (33, 34):
            s, b = out.get(w[i + 1], (0, None)); out[w[i + 1]] = (w[i + 3], b) if w[i + 2] == 34 else (s, w[i + 3])
        i += n
    return out


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvBind(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        bin_ = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'b.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text('#include "spv_bind.h"\n'
                       f'{export} int make(const uint32_t *b, int nb, uint32_t *from, uint32_t *to) {{ spv_bmap m; int n = spv_bmap_make(b, nb, &m);'
                       ' for (uint32_t k = 0; k < m.n; k++) { from[k] = m.from[k]; to[k] = m.to[k]; } return n; }\n'
                       f'{export} size_t remap(uint32_t *w, size_t n, const uint32_t *b, int nb) {{ spv_bmap m; if (spv_bmap_make(b, nb, &m) <= 0) return 0; return spv_bind_remap(w, n, &m); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone
            subprocess.run([bin_ / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-I', REPO / 'dm/android', '-c', src, '-o', cls.tmp / 'b.obj'], check=True)
            subprocess.run([bin_ / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "b.dll"}', str(cls.tmp / 'b.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'b.dll'))
        else:
            subprocess.run([bin_ / 'clang', '-shared', '-fPIC', '-O1', '-Wall', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'b.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'b.so'))
        cls.lib.make.restype = ctypes.c_int
        cls.lib.make.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_int, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_uint32)]
        cls.lib.remap.restype = ctypes.c_size_t
        cls.lib.remap.argtypes = [ctypes.POINTER(ctypes.c_uint32), ctypes.c_size_t, ctypes.POINTER(ctypes.c_uint32), ctypes.c_int]

    def make(self, b):
        a = (ctypes.c_uint32 * max(len(b), 1))(*b); f = (ctypes.c_uint32 * MAX)(); t = (ctypes.c_uint32 * MAX)()
        n = self.lib.make(a, len(b), f, t)
        return n, dict(zip(f[:max(n, 0)], t[:max(n, 0)]))

    def remap(self, data, b):
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); a = (ctypes.c_uint32 * max(len(b), 1))(*b)
        return self.lib.remap(w, n, a, len(b)), bytes(w)

    def asm(self, text, name):
        p = self.tmp / f'{name}.spvasm'; p.write_text(text)
        subprocess.run([self.spv_as, '--target-env', 'vulkan1.1', p, '-o', self.tmp / f'{name}.spv'], check=True)
        return (self.tmp / f'{name}.spv').read_bytes()

    def val(self, data, name, env='vulkan1.1', check=True):
        p = self.tmp / name; p.write_bytes(data)
        r = subprocess.run([self.spv_val, '--target-env', env, p], capture_output=True, text=True)
        if check: self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.returncode == 0

    def test_far_numbers_dense_in_order_past_the_small_ones(self):
        n, m = self.make([0, 1, 5, 2101267, 2101266, 12, 2101266, 100])
        self.assertEqual(n, 2); self.assertEqual(m, {2101266: BASE, 2101267: BASE + 1})

    def test_base_moves_past_a_small_binding_beyond_it(self):
        self.assertEqual(self.make([0, 500, 1048576, 1048591]), (2, {1048576: 501, 1048591: 502}))

    def test_nothing_far_no_map(self):
        self.assertEqual(self.make([0, 1, 2, 13, 100, 103]), (0, {}))

    def test_too_many_far_numbers_left_alone(self):
        self.assertEqual(self.make([FROM + i for i in range(MAX + 1)]), (-1, {}))

    def test_module_rewritten_and_valid(self):
        data = self.asm(FS, 'fs')
        k, out = self.remap(data, [0, 5, 2101266, 2101267])
        self.assertEqual(k, 2)
        self.assertEqual(sorted(bindings(out).values()), [(1, 5), (1, BASE), (1, BASE + 1), (4, 0)])
        self.assertEqual(len(out), len(data))
        self.val(out, 'fs_out.spv')

    def test_module_without_far_numbers_unchanged(self):
        data = self.asm(FS.replace('Binding 2101266', 'Binding 6').replace('Binding 2101267', 'Binding 7'), 'fs_small')
        self.assertEqual(self.remap(data, [0, 5, 6, 7]), (0, data))

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR not set')
    def test_a_games_modules(self):
        import json
        d = Path(os.environ['DM_SPV_DIR']); n = changed = invalid = 0
        for rj in sorted(d.glob('*.res.json')):
            r = json.loads(rj.read_text(encoding='utf-8')); key = rj.name[:-9]
            # sh_get's set: constant and storage buffers, textures (the pool's arrays, handle 0x40000000 in bank 0 longer than 32, go to the pool set) and images
            b = [x['binding'] for x in r.get('cbufs', []) + r.get('sbufs', []) + r.get('images', [])]
            b += [x['binding'] for x in r.get('textures', []) if not (x.get('handle') == 0x40000000 and x.get('cbuf_slot') == 0 and x.get('array', 1) > 32)]
            nm, m = self.make(b)
            for sp in (d / f'{key}.spv', d / f'{key}.z.spv', d / f'{key}.tf.spv'):
                if not sp.is_file(): continue
                n += 1
                if nm <= 0: continue
                data = sp.read_bytes(); k, out = self.remap(data, b)
                if not k: continue
                changed += 1
                after = [v for v in bindings(out).values() if v[1] is not None]
                self.assertEqual(len(after), len(set(after)), f'{sp.name}: two resources at one set and binding after the remap')
                # a game's modules are SPIR-V 1.4 or later; one the validator refuses as it is (its own fault) is only checked for clashes
                if self.val(data, 'game_in.spv', 'vulkan1.2', check=False): self.assertTrue(self.val(out, 'game.spv', 'vulkan1.2', check=False), f'{sp.name}: invalid after the remap')
                else: invalid += 1
        print(f'{n} modules, {changed} with binding numbers made dense ({invalid} of them invalid as they are, checked for clashes only)')
        self.assertTrue(n)


if __name__ == '__main__':
    unittest.main()
