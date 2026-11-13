"""dm/android/rb16.h: NVN's RGB-order 16-bit formats (RGBA4, RGB5, RGB5A1, RGB565) held in the Vulkan format's order on Android, their bits exchanged where they
cross guest memory (gfx_vk.c vt_upload_, copy_b2t and the write-backs in chunk_done). Built for the PC with the host's cc together with the real format table
(dm/gfx/tex/nvn_fmt_mtl.c) and checked against hand-made texels. Pokémon: Let's Go, Pikachu!'s party and bag sprites are RGB5A1: without the exchange Pikachu's
yellow sampled as cyan (droidplay-core#417). Synthetic data only."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]

CHECK = r'''
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "nvn_fmt_mtl.h"
#include "rb16.h"
static int shift_of(int f) { uint32_t m = 0; uint8_t sw[4] = {0}; nvn_fmt_to_mtl(f, &m, sw); return rb16_shift(m, sw); }
int main(void) {
    // which formats take it, from the real table: only RGBA4, RGB5, RGB5A1 and RGB565; the BGR family (0x95-0x98) and every other format are as they are
    for (int f = 0; f <= 0x9c; f++) {
        int want = f == 0x39 ? 4 : f == 0x3a || f == 0x3b ? 10 : f == 0x3c ? 11 : 0;
        if (shift_of(f) != want) { printf("format %#x: shift %d, want %d\n", f, shift_of(f), want); return 1; }
    }
    // RGB565 (red at bit 0) -> R5G6B5_UNORM_PACK16 (red at bit 11): red and blue exchange, green stays
    assert(rb16_texel(0x001f, 11) == 0xf800 && rb16_texel(0xf800, 11) == 0x001f && rb16_texel(0x07e0, 11) == 0x07e0);
    // RGB5A1 -> A1R5G5B5_UNORM_PACK16 (red at bit 10): alpha (bit 15) and green stay. Pikachu's yellow (red 31, green 31, alpha 1) reads as yellow, not cyan
    assert(rb16_texel(0x801f, 10) == 0xfc00 && rb16_texel(0x7c00, 10) == 0x001f && rb16_texel(0x83e0, 10) == 0x83e0);
    { uint16_t y = rb16_texel(0x83ff, 10); assert((y >> 10 & 31) == 31 && (y >> 5 & 31) == 31 && (y & 31) == 0 && (y >> 15)); }
    // RGBA4 (R, G, B, A from bit 0) -> R4G4B4A4_UNORM_PACK16 (R in the top nibble): every nibble moves
    assert(rb16_texel(0x8421, 4) == 0x1248 && rb16_texel(0x0f00, 4) == 0x00f0 && rb16_texel(0xf000, 4) == 0x000f);
    // the same exchange both ways: every texel comes back
    static const int shifts[3] = {4, 10, 11};
    for (int k = 0; k < 3; k++) for (uint32_t q = 0; q <= 0xffffu; q++)
        if (rb16_texel(rb16_texel((uint16_t)q, shifts[k]), shifts[k]) != q) { printf("shift %d: %#x does not come back\n", shifts[k], q); return 1; }
    // a region: rows of wb bytes at a wider pitch, at an odd address; the bytes between rows stay, shift 0 leaves it alone
    { uint8_t buf[1 + 2 * 8]; memset(buf, 0xee, sizeof buf); uint16_t t[2] = {0x001f, 0x07e0};
      for (int y = 0; y < 2; y++) memcpy(buf + 1 + y * 8, t, 4);
      rb16_rows(buf + 1, 4, 2, 8, 0); { uint16_t q; memcpy(&q, buf + 1, 2); assert(q == 0x001f); }
      rb16_rows(buf + 1, 4, 2, 8, 11);
      for (int y = 0; y < 2; y++) { uint16_t q[2]; memcpy(q, buf + 1 + y * 8, 4); assert(q[0] == 0xf800 && q[1] == 0x07e0); assert(buf[1 + y * 8 + 4] == 0xee && buf[1 + y * 8 + 7] == 0xee); }
      assert(buf[0] == 0xee); }
    puts("rb16 ok"); return 0;
}
'''


@unittest.skipUnless(shutil.which('cc'), 'a host C compiler (cc) is required')
class Rb16(unittest.TestCase):
    def test_rgb_order_16_bit_formats_exchanged_both_ways(self):
        with tempfile.TemporaryDirectory() as tmp:
            src, exe = Path(tmp) / 'check.c', Path(tmp) / 'check'
            src.write_text(CHECK, encoding='utf-8')
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), '-I', str(REPO / 'dm/gfx/tex'),
                            str(src), str(REPO / 'dm/gfx/tex/nvn_fmt_mtl.c'), '-o', str(exe)], check=True)
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            self.assertIn('rb16 ok', r.stdout)


if __name__ == '__main__':
    unittest.main()
