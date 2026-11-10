"""dm/android/shaders/bc_decode.comp, the Vulkan replay's BC4 / BC5 decode on the GPU (gfx_vk_bcdec.inc: a GPU block encoder's blocks drawn into a BC texture that a GPU
without BC textures holds decoded). The shader is compiled with the Android NDK's glslc as the host build compiles it, and spirv-val checks it; skipped without the NDK.
With DM_TEST_SERIAL=<adb serial>, dm/android/tests/t_bc_decode.c is built for Android and run on that device: the GPU's bytes must equal bcdec's (the CPU decode) for
every case, edge blocks clipped and a 3D depth plane included."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from test_spv_readonly import NDK, HOST, EXE, REPO   # noqa: E402

SHADER = REPO / 'dm/android/shaders/bc_decode.comp'


@unittest.skipIf(NDK is None, 'no Android NDK')
class BcGpuDecode(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST
        cls.glslc, cls.spv_val = tools / f'glslc{EXE}', tools / f'spirv-val{EXE}'
        cls.bin = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        cls.spv = cls.tmp / 'bc_decode.spv'
        subprocess.run([cls.glslc, '--target-env=vulkan1.1', '-O', SHADER, '-o', cls.spv], check=True)   # CMakeLists.txt's flags, as SPIR-V words rather than C

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_shader_is_valid_spirv(self):
        r = subprocess.run([self.spv_val, '--target-env', 'vulkan1.1', self.spv], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_host_build_compiles_it(self):   # gfx_vk_bcdec.inc includes the words CMakeLists.txt makes from it
        cm = (REPO / 'dm/android/CMakeLists.txt').read_text(encoding='utf-8')
        m = re.search(r'^foreach\(s ([^)]*)\)\n  add_custom_command\(OUTPUT \$\{GEN\}/shaders/\$\{s\}\.inc', cm, re.M)
        self.assertIsNotNone(m); assert m is not None
        self.assertIn('bc_decode.comp', m.group(1).split())
        self.assertIn('#include "shaders/bc_decode.comp.inc"', (REPO / 'dm/android/gfx_vk_bcdec.inc').read_text(encoding='utf-8'))

    def test_push_constants_match_the_host(self):   # the shader's three uints and bcd_pc
        src, inc = SHADER.read_text(encoding='utf-8'), (REPO / 'dm/android/gfx_vk_bcdec.inc').read_text(encoding='utf-8')
        self.assertIn('uniform Pc { uint bw, bh, kind; } pc;', src)
        self.assertIn('typedef struct { uint32_t bw, bh, kind; } bcd_pc;', inc)

    @unittest.skipUnless(os.environ.get('DM_TEST_SERIAL'), 'DM_TEST_SERIAL not set')
    def test_decode_on_a_device(self):
        serial = os.environ['DM_TEST_SERIAL']
        adb = shutil.which('adb') or str(Path(os.environ.get('ANDROID_HOME', '')) / 'platform-tools' / f'adb{EXE}')
        exe = self.tmp / 't_bc_decode'
        cc = self.bin / ('aarch64-linux-android29-clang' + ('.cmd' if os.name == 'nt' else ''))
        # -fsigned-char as the host (CMakeLists.txt): bcdec reads signed endpoints through a plain char, unsigned on arm64 otherwise
        subprocess.run([cc, '-O1', '-Wall', '-Werror', '-Wno-unused-function', '-fsigned-char', REPO / 'dm/android/tests/t_bc_decode.c', '-lvulkan', '-o', exe], check=True)
        d = '/data/local/tmp/dm_bc_decode'
        subprocess.run([adb, '-s', serial, 'shell', 'mkdir', '-p', d], check=True)
        for f in (exe, self.spv): subprocess.run([adb, '-s', serial, 'push', f, d], check=True, capture_output=True)
        r = subprocess.run([adb, '-s', serial, 'shell', f'cd {d} && chmod 755 t_bc_decode && ./t_bc_decode bc_decode.spv; echo "exit $?"'], capture_output=True, text=True)
        subprocess.run([adb, '-s', serial, 'shell', 'rm', '-r', d], capture_output=True)
        print(r.stdout.strip())
        self.assertTrue(r.stdout.strip().endswith('exit 0'), r.stdout + r.stderr)


if __name__ == '__main__':
    unittest.main()
