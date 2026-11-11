"""dm/android/ds_texels.h: a depth / stencil readback rebuilt in NVN's layouts from the planes Vulkan copies each aspect into (gfx_vk.c ds_wb), built for the PC
with the host's cc and checked against hand-made texels. Synthetic data only.
With DM_TEST_SERIAL=<adb serial>, dm/android/tests/t_ds_readback.c is built for Android with the NDK and run on that device: each depth / stencil format the GPU has
is cleared, copied out aspect by aspect as gfx_vk.c ds_wb copies it, and rebuilt by ds_texels.h; then texels that differ one from the next are copied in as ds_up copies
them and read back. Every texel must be right."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))

CHECK = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "ds_texels.h"
int main(void) {
    float df[3] = {0.25f, 1.0f, 0.0f}; uint8_t st[3] = {7, 0xff, 0x80}, out[24];
    // DEPTH32F_STENCIL8 from D32_SFLOAT_S8_UINT: the float, the stencil byte, 3 zero bytes, 8 bytes a texel
    memset(out, 0xee, sizeof out); assert(ds_texels(0x36, DS_D32F, (const uint8_t *)df, st, 3, out) == 24);
    for (int i = 0; i < 3; i++) { float x; memcpy(&x, out + 8 * i, 4); assert(x == df[i] && out[8 * i + 4] == st[i] && !out[8 * i + 5] && !out[8 * i + 6] && !out[8 * i + 7]); }
    // DEPTH24_STENCIL8 from D32_SFLOAT_S8_UINT (nvn_fmt_mtl.c keeps it so): 24-bit unorm depth, the stencil in the top byte
    uint32_t w[4]; assert(ds_texels(0x35, DS_D32F, (const uint8_t *)df, st, 3, (uint8_t *)w) == 12);
    assert(w[0] == (0x07000000u | 0x400000u) && w[1] == 0xffffffffu && w[2] == 0x80000000u);
    // DEPTH24_STENCIL8 from D24_UNORM_S8_UINT (the fallback without D32S8 attachments): the copy's top byte is undefined and is not kept
    uint32_t d24[3] = {0x00123456, 0xff000001, 0x00ffffff}; ds_texels(0x35, DS_D24, (const uint8_t *)d24, st, 3, (uint8_t *)w);
    assert(w[0] == 0x07123456 && w[1] == 0xff000001 && w[2] == 0x80ffffff);
    // DEPTH32F_STENCIL8 from the D24S8 fallback: the depth back as a float
    ds_texels(0x36, DS_D24, (const uint8_t *)d24, st, 3, out); { float x; memcpy(&x, out + 16, 4); assert(x == 1.0f && out[20] == 0x80); memcpy(&x, out, 4); assert(x > 0.0711f && x < 0.0712f); }
    // DEPTH24 kept as D32_SFLOAT: 24-bit unorm, top byte 0; out of range and NaN clamp
    float dx[4] = {0.5f, 1.5f, -1.0f, 0.0f / 0.0f}; ds_texels(0x33, DS_D32F, (const uint8_t *)dx, NULL, 4, (uint8_t *)w);
    assert(w[0] == 0x800000 && w[1] == 0xffffff && !w[2] && !w[3]);
    // DEPTH16, DEPTH32F: as copied
    uint16_t d16[2] = {0x1234, 0xfedc}, o16[2]; assert(ds_texels(0x32, DS_D16, (const uint8_t *)d16, NULL, 2, (uint8_t *)o16) == 4); assert(o16[0] == 0x1234 && o16[1] == 0xfedc);
    ds_texels(0x34, DS_D32F, (const uint8_t *)df, NULL, 3, (uint8_t *)w); assert(!memcmp(w, df, sizeof df));
    // STENCIL8: the stencil alone, from an S8 image or a combined one
    memset(out, 0, sizeof out); assert(ds_texels(0x31, DS_NONE, NULL, st, 3, out) == 3); assert(!memcmp(out, st, 3) && !out[3]);
    // an aspect the image lacks reads 0; a colour format is not one of these
    memset(out, 0xee, sizeof out); ds_texels(0x36, DS_D32F, NULL, NULL, 1, out); assert(!out[0] && !out[4] && !out[7]);
    assert(ds_texels(0x25, DS_D32F, (const uint8_t *)df, st, 3, out) == 0 && ds_texel_bytes(0x25) == 0 && ds_texel_bytes(0x36) == 8);
    // a slice of STENCIL8 (gfx_vk.c wb_apply): there is no depth plane, so the stencil plane is at offset 0 and must still be read (it was taken for "no stencil")
    { uint8_t pl[8] = {1, 2, 3, 4, 5, 6, 0xaa, 0xaa}, o[2 * 5]; memset(o, 0xee, sizeof o); assert(ds_sten_off(DS_NONE, 6) == 0 && ds_slice_bytes(DS_NONE, 1, 6) == 8);
      ds_slice(0x31, DS_NONE, 1, pl, 3, 2, o, 5); assert(o[0] == 1 && o[2] == 3 && o[3] == 0xee && o[5] == 4 && o[7] == 6);
      uint8_t back[8] = {0}; ds_slice_up(0x31, DS_NONE, 1, o, 5, 3, 2, back); assert(!memcmp(back, pl, 6)); }
    // a slice of DEPTH32F_STENCIL8, 3 x 2: the stencil plane after the depth plane, at a multiple of 4; split again, the planes are as they were
    { uint8_t pl[32], o[2 * 24], back[32]; float d6[6] = {0.0f, 0.125f, 0.25f, 0.5f, 0.75f, 1.0f}; memcpy(pl, d6, 24); for (int i = 0; i < 6; i++) pl[24 + i] = (uint8_t)(0x10 + i);
      assert(ds_sten_off(DS_D32F, 6) == 24 && ds_slice_bytes(DS_D32F, 1, 6) == 32 && ds_sten_off(DS_D16, 3) == 8 && ds_slice_bytes(DS_D16, 0, 3) == 8);
      ds_slice(0x36, DS_D32F, 1, pl, 3, 2, o, 24); { float x; memcpy(&x, o + 24 + 8, 4); assert(x == 0.75f && o[24 + 12] == 0x14); }
      ds_slice_up(0x36, DS_D32F, 1, o, 24, 3, 2, back); assert(!memcmp(back, pl, 30)); }
    // every 24-bit depth survives being kept as a float (DEPTH24 and DEPTH24_STENCIL8 on D32_SFLOAT): read back, uploaded, read back
    for (uint32_t u = 0; u <= 0xffffffu; u++) if (ds_unorm24(ds_float24(u)) != u) { printf("%#x does not come back\n", u); return 1; }
    // texels → planes → texels, each format on each depth kind that holds it exactly
    { uint32_t t35[3] = {0x07123456, 0xff000001, 0x80ffffff}, o35[3]; uint8_t dp[12], sp[3];
      ds_planes(0x35, DS_D32F, (const uint8_t *)t35, 3, dp, sp); { float x; memcpy(&x, dp + 8, 4); assert(x == 1.0f && sp[0] == 7 && sp[2] == 0x80); }
      ds_texels(0x35, DS_D32F, dp, sp, 3, (uint8_t *)o35); assert(!memcmp(o35, t35, 12));
      ds_planes(0x35, DS_D24, (const uint8_t *)t35, 3, dp, sp); { uint32_t x; memcpy(&x, dp, 4); assert(x == 0x123456); } ds_texels(0x35, DS_D24, dp, sp, 3, (uint8_t *)o35); assert(!memcmp(o35, t35, 12));
      uint32_t t33[2] = {0x00800000, 0x00000001}, o33[2]; ds_planes(0x33, DS_D32F, (const uint8_t *)t33, 2, dp, NULL); ds_texels(0x33, DS_D32F, dp, NULL, 2, (uint8_t *)o33); assert(!memcmp(o33, t33, 8));
      uint16_t t32[2] = {0x1234, 0xfedc}, o32[2]; ds_planes(0x32, DS_D16, (const uint8_t *)t32, 2, dp, NULL); ds_texels(0x32, DS_D16, dp, NULL, 2, (uint8_t *)o32); assert(!memcmp(o32, t32, 4));
      uint8_t t36[16] = {0}, o36[16]; float a = 0.25f, b = 1.0f; memcpy(t36, &a, 4); t36[4] = 9; memcpy(t36 + 8, &b, 4); t36[12] = 0xf0;
      ds_planes(0x36, DS_D32F, t36, 2, dp, sp); ds_texels(0x36, DS_D32F, dp, sp, 2, o36); assert(!memcmp(o36, t36, 16));
      ds_planes(0x36, DS_D24, t36, 2, dp, sp); { uint32_t x; memcpy(&x, dp, 4); assert(x == 0x400000); memcpy(&x, dp + 4, 4); assert(x == 0xffffff); } }
    puts("ds_texels ok"); return 0;
}
'''


@unittest.skipUnless(shutil.which('cc'), 'a host C compiler (cc) is required')
class DepthStencilTexels(unittest.TestCase):
    def test_nvn_layouts_from_aspect_planes(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, exe = Path(tmp) / 'check.c', Path(tmp) / 'check'
            src.write_text(CHECK, encoding='utf-8')
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), str(src), '-o', str(exe)], check=True)
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn('ds_texels ok', r.stdout)


@unittest.skipUnless(os.environ.get('DM_TEST_SERIAL'), 'DM_TEST_SERIAL not set')
class DepthStencilOnDevice(unittest.TestCase):
    def test_aspect_planes_on_a_device(self):
        from test_spv_readonly import NDK, HOST, EXE   # noqa: E402 (the NDK, found as the other device tests find it)
        if not NDK:
            self.skipTest('the NDK is required')
        serial = os.environ['DM_TEST_SERIAL']
        adb = shutil.which('adb') or str(Path(os.environ.get('ANDROID_HOME', '')) / 'platform-tools' / f'adb{EXE}')
        cc = Path(NDK) / 'toolchains/llvm/prebuilt' / HOST / 'bin' / ('aarch64-linux-android29-clang' + ('.cmd' if os.name == 'nt' else ''))
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / 't_ds_readback'
            subprocess.run([cc, '-O1', '-Wall', '-Werror', REPO / 'dm/android/tests/t_ds_readback.c', '-lvulkan', '-o', exe], check=True)
            d = '/data/local/tmp/dm_ds_readback'
            subprocess.run([adb, '-s', serial, 'shell', 'mkdir', '-p', d], check=True)
            subprocess.run([adb, '-s', serial, 'push', exe, d], check=True, capture_output=True)
            r = subprocess.run([adb, '-s', serial, 'shell', f'cd {d} && chmod 755 t_ds_readback && ./t_ds_readback; echo "exit $?"'], capture_output=True, text=True)
            print(r.stdout.strip())
            subprocess.run([adb, '-s', serial, 'shell', 'rm', '-r', d], capture_output=True)
            self.assertTrue(r.stdout.strip().endswith('exit 0'), r.stdout)


if __name__ == '__main__':
    unittest.main()
