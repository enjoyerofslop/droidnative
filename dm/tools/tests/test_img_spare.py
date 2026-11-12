"""dm/android/img_spare.h, the rules of a freed image's memory kept as a spare (gfx_vk_spare.inc, DM_VK_IMAGE_SPARE), built with the system's C compiler and called
through ctypes: which spare fits an image, which one it takes, and when the sweep lets one go. Skipped without a C compiler."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
CC = (['xcrun', 'clang'] if sys.platform == 'darwin' and shutil.which('xcrun') else
      [c] if (c := shutil.which('clang') or shutil.which('cc') or shutil.which('gcc')) else None)
MIB = 1 << 20


@unittest.skipIf(CC is None or os.name == 'nt', 'no C compiler')
class ImageSpare(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert CC is not None   # (skipped without one; pyright doesn't follow skipIf)
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 's.c'
        src.write_text('#include "img_spare.h"\n'
                       '__attribute__((visibility("default"))) int fits(uint64_t s, uint32_t t, uint64_t n, uint32_t b) { return spare_fits(s, t, n, b); }\n'
                       '__attribute__((visibility("default"))) int pick(const uint64_t *s, const uint32_t *t, uint32_t n, uint64_t need, uint32_t b) { return spare_pick(s, t, n, need, b); }\n'
                       '__attribute__((visibility("default"))) int expired(uint64_t f, uint64_t now, uint64_t age) { return spare_expired(f, now, age); }\n')
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), str(src), '-o', str(cls.tmp / 's.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 's.so'))
        cls.lib.fits.argtypes = [ctypes.c_uint64, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32]
        cls.lib.pick.argtypes = [ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint32]
        cls.lib.expired.argtypes = [ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64]

    def test_a_spare_fits_with_at_most_a_quarter_to_spare(self):
        self.assertTrue(self.lib.fits(8 * MIB, 2, 8 * MIB, 1 << 2))   # the same size
        self.assertTrue(self.lib.fits(10 * MIB, 2, 8 * MIB, 1 << 2))   # a quarter larger
        self.assertFalse(self.lib.fits(10 * MIB + 1, 2, 8 * MIB, 1 << 2))   # more than a quarter
        self.assertFalse(self.lib.fits(8 * MIB - 1, 2, 8 * MIB, 1 << 2))   # too small
        self.assertFalse(self.lib.fits(8 * MIB, 3, 8 * MIB, 1 << 2))   # a memory type the image doesn't allow
        self.assertFalse(self.lib.fits(8 * MIB, 40, 8 * MIB, 0xffffffff))   # (no such type)

    def pick(self, spares, need, bits=0xffffffff):
        sz = (ctypes.c_uint64 * len(spares))(*[s * MIB for s, _ in spares]); ty = (ctypes.c_uint32 * len(spares))(*[t for _, t in spares])
        return self.lib.pick(sz, ty, len(spares), need * MIB, bits)

    def test_an_image_takes_the_smallest_spare_that_fits(self):
        spares = [(16, 1), (9, 1), (8, 0), (10, 1), (4, 1)]   # (MiB, memory type)
        self.assertEqual(self.pick(spares, 8), 2)   # 8 MiB of type 0: exact
        self.assertEqual(self.pick(spares, 8, bits=1 << 1), 1)   # type 1 only: 9 MiB, the smallest of 9 and 10
        self.assertEqual(self.pick(spares, 13, bits=1 << 1), 0)   # 16 holds 13 within a quarter (3.25)
        self.assertEqual(self.pick(spares, 12, bits=1 << 1), -1)   # 16 is a third too large, 10 too small
        self.assertEqual(self.pick([], 8), -1)

    def test_the_sweep_lets_old_spares_go(self):
        self.assertFalse(self.lib.expired(1000, 1119, 120))
        self.assertTrue(self.lib.expired(1000, 1120, 120))


if __name__ == '__main__':
    unittest.main()
