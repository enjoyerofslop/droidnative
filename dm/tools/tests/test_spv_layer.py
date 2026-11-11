"""dm/android/spv_layer.h (layer and viewport output from vertex shaders made ordinary outputs, for a GPU without VK_EXT_shader_viewport_index_layer: the
Adreno 730's driver V@0615.98, whose compiler crashed on Brilliant Diamond's), built for the PC and run on modules assembled with the NDK's spirv-as; spirv-val
checks each result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there (each rewritten module must pass spirv-val)."""
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

# A vertex shader as the translator writes one that sets the render target layer and the viewport index: each a variable of its own, BuiltIn Layer and
# ViewportIndex, beside two ordinary outputs at locations 0 and 2
VS = '''OpCapability Shader
OpCapability ShaderViewportIndexLayerEXT
OpExtension "SPV_EXT_shader_viewport_index_layer"
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %pos %layer %vp %o0 %o2
OpDecorate %pos BuiltIn Position
OpDecorate %layer BuiltIn Layer
OpDecorate %vp BuiltIn ViewportIndex
OpDecorate %o0 Location 0
OpDecorate %o2 Location 2
%void = OpTypeVoid
%fn = OpTypeFunction %void
%int = OpTypeInt 32 1
%float = OpTypeFloat 32
%v4 = OpTypeVector %float 4
%pv4 = OpTypePointer Output %v4
%pint = OpTypePointer Output %int
%pos = OpVariable %pv4 Output
%layer = OpVariable %pint Output
%vp = OpVariable %pint Output
%o0 = OpVariable %pv4 Output
%o2 = OpVariable %pv4 Output
%one = OpConstant %float 1
%i3 = OpConstant %int 3
%vec = OpConstantComposite %v4 %one %one %one %one
%main = OpFunction %void None %fn
%l = OpLabel
OpStore %pos %vec
OpStore %layer %i3
OpStore %vp %i3
OpStore %o0 %vec
OpStore %o2 %vec
OpReturn
OpFunctionEnd
'''
PLAIN = VS.replace('OpCapability ShaderViewportIndexLayerEXT\nOpExtension "SPV_EXT_shader_viewport_index_layer"\n', '').replace(
    'OpDecorate %layer BuiltIn Layer\nOpDecorate %vp BuiltIn ViewportIndex\n', 'OpDecorate %layer Location 3\nOpDecorate %vp Location 4\n')


def words(data): return struct.unpack('<%dI' % (len(data) // 4), data)


def ops(data):   # [(opcode, operands)]
    w = words(data); i = 5; out = []
    while i < len(w):
        n = w[i] >> 16; out.append((w[i] & 0xffff, w[i + 1:i + n])); i += max(n, 1)
    return out


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvLayer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'l.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text(f'#include "spv_layer.h"\n{export} size_t run(const uint32_t *w, size_t n, uint32_t *o, size_t cap) {{ return spv_layer(w, n, o, cap); }}\n'
                       f'{export} int wanted(const uint32_t *w, size_t n) {{ return spv_layer_wanted(w, n); }}\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone
            subprocess.run([cls.bin / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-Werror', '-I', REPO / 'dm/android', '-c', src,
                            '-o', cls.tmp / 'l.obj'], check=True)
            subprocess.run([cls.bin / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "l.dll"}', str(cls.tmp / 'l.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'l.dll'))
        else:   # the system's clang, as test_spv_limits.py explains
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or cls.bin / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'l.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'l.so'))
        cls.lib.run.restype = ctypes.c_size_t

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

    def run_on(self, data):   # → the rewritten module or None
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); o = (ctypes.c_uint32 * n)()
        k = self.lib.run(w, n, o, n)
        return bytes(o)[:4 * k] if k else None

    def wanted(self, data): n = len(data) // 4; return self.lib.wanted((ctypes.c_uint32 * n).from_buffer_copy(data), n)

    def test_layer_and_viewport_become_outputs_after_the_highest_location(self):
        data = self.asm(VS, 'vs'); self.assertTrue(self.wanted(data))
        out = self.run_on(data); self.assertIsNotNone(out); assert out is not None
        self.valid(out, 'vs')
        o = ops(out)
        self.assertNotIn((17, (5254,)), o)   # OpCapability ShaderViewportIndexLayerEXT
        self.assertFalse([x for op, x in o if op == 10])   # no OpExtension left
        self.assertFalse([x for op, x in o if op == 71 and len(x) == 3 and x[1] == 11 and x[2] in (9, 10)])   # no BuiltIn Layer / ViewportIndex
        self.assertEqual(sorted(x[2] for op, x in o if op == 71 and x[1] == 30), [0, 2, 3, 4])   # Location 3 and 4 after the highest, 2
        self.assertEqual(out, self.asm(PLAIN, 'plain'))   # word for word the module the translator would write without them

    def test_a_module_without_them_is_left_alone(self):
        data = self.asm(PLAIN, 'plain2')
        self.assertFalse(self.wanted(data)); self.assertIsNone(self.run_on(data))

    def test_a_block_member_layer_is_not_rewritten(self):
        blk = VS.replace('OpDecorate %layer BuiltIn Layer\n', 'OpMemberDecorate %blk 0 BuiltIn Layer\nOpDecorate %blk Block\n').replace(
            '%layer = OpVariable %pint Output\n', '%blk = OpTypeStruct %int\n%pblk = OpTypePointer Output %blk\n%layer = OpVariable %pblk Output\n%i0 = OpConstant %int 0\n').replace(
            'OpStore %layer %i3\n', '%lp = OpAccessChain %pint %layer %i0\nOpStore %lp %i3\n')
        data = self.asm(blk, 'blk'); self.assertTrue(self.wanted(data)); self.assertIsNone(self.run_on(data))

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR (a game\'s packed spv folder) not set')
    def test_a_games_shaders(self):   # each rewritten module must pass spirv-val
        d = Path(os.environ['DM_SPV_DIR']); n = 0
        for f in sorted(d.glob('*.spv')):
            data = f.read_bytes()
            if not self.wanted(data): continue
            out = self.run_on(data)
            if out is None: continue
            self.valid(out, f.stem); n += 1
        print(f'{n} modules rewritten in {d}')


if __name__ == '__main__':
    unittest.main()
