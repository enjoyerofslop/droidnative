"""dm/android/rt_alias.h, the rules of render targets sharing one allocation (gfx_vk_rtalias.inc, DM_VK_RTALIAS), built with the system's C compiler and called
through ctypes: the key leaves out only the extent, which images may share, and how an allocation grows. Skipped without a C compiler."""
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
IMAGE_FLAG = 0x40   # a stand-in for NVN_TEXTURE_FLAGS_IMAGE: the header takes it as an argument


class Desc(ctypes.Structure):   # nvn_texdesc
    _fields_ = [('target', ctypes.c_int), ('format', ctypes.c_int), ('flags', ctypes.c_int), ('samples', ctypes.c_int), ('width', ctypes.c_uint32), ('height', ctypes.c_uint32),
                ('depth', ctypes.c_uint32), ('levels', ctypes.c_uint32), ('stride', ctypes.c_uint32), ('pkg_block_h', ctypes.c_int)]


@unittest.skipIf(CC is None or os.name == 'nt', 'no C compiler')
class RenderTargetAlias(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert CC is not None   # (skipped without one; pyright doesn't follow skipIf)
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'r.c'
        src.write_text('#include "rt_alias.h"\n'
                       '__attribute__((visibility("default"))) int same(uint64_t pa, int64_t oa, const nvn_texdesc *a, uint64_t pb, int64_t ob, const nvn_texdesc *b, int f) '
                       '{ ra_key x = ra_key_of(pa, oa, a, f), y = ra_key_of(pb, ob, b, f); return !memcmp(&x, &y, sizeof x); }\n'
                       '__attribute__((visibility("default"))) int elig(int m, int p, int k, int c, int t, int col, uint64_t b, uint64_t mn) { return ra_eligible(m, p, k, c, t, col, b, mn); }\n'
                       '__attribute__((visibility("default"))) uint64_t grow(uint64_t h, uint64_t n) { return ra_grow(h, n); }\n')
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), str(src), '-o', str(cls.tmp / 'r.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'r.so'))
        cls.lib.same.argtypes = [ctypes.c_uint64, ctypes.c_int64, ctypes.POINTER(Desc), ctypes.c_uint64, ctypes.c_int64, ctypes.POINTER(Desc), ctypes.c_int]
        cls.lib.elig.argtypes = [ctypes.c_int] * 6 + [ctypes.c_uint64] * 2
        cls.lib.grow.argtypes, cls.lib.grow.restype = [ctypes.c_uint64, ctypes.c_uint64], ctypes.c_uint64

    def same(self, a, b, pa=1, oa=4096, pb=1, ob=4096):
        return bool(self.lib.same(pa, oa, ctypes.byref(Desc(**a)), pb, ob, ctypes.byref(Desc(**b)), IMAGE_FLAG))

    def test_the_key_leaves_out_only_the_extent(self):
        d = dict(target=1, format=0x25, flags=0, samples=1, width=1280, height=720, depth=1, levels=1, stride=0, pkg_block_h=0)
        self.assertTrue(self.same(d, {**d, 'width': 1600, 'height': 900, 'stride': 6400}))   # the same target made again at another size
        self.assertTrue(self.same(d, {**d, 'flags': IMAGE_FLAG}))   # the image flag, as the sharing table leaves it out
        self.assertFalse(self.same(d, {**d, 'format': 0x26}))   # another format
        self.assertFalse(self.same(d, {**d, 'levels': 2}))
        self.assertFalse(self.same(d, {**d, 'samples': 4}))
        self.assertFalse(self.same(d, d, ob=8192))   # another storage start
        self.assertFalse(self.same(d, d, pb=2))   # another pool

    def test_which_images_may_share(self):
        kb = 1024
        self.assertTrue(self.lib.elig(1, 1, 0, 0, 1, 1, 512 * kb, 256 * kb))   # a colour target in a pool
        self.assertFalse(self.lib.elig(0, 1, 0, 0, 1, 1, 512 * kb, 256 * kb))   # off
        self.assertFalse(self.lib.elig(1, 1, 0, 0, 1, 0, 512 * kb, 256 * kb))   # depth at mode 1
        self.assertTrue(self.lib.elig(2, 1, 0, 0, 1, 0, 512 * kb, 256 * kb))   # depth at mode 2
        self.assertFalse(self.lib.elig(1, 0, 0, 0, 1, 1, 512 * kb, 256 * kb))   # not in a pool
        self.assertFalse(self.lib.elig(1, 1, 1, 0, 1, 1, 512 * kb, 256 * kb))   # packaged: uploaded from guest memory
        self.assertFalse(self.lib.elig(1, 1, 0, 1, 1, 1, 512 * kb, 256 * kb))   # decoded on the CPU
        self.assertFalse(self.lib.elig(1, 1, 0, 0, 0, 1, 512 * kb, 256 * kb))   # not a target
        self.assertFalse(self.lib.elig(1, 1, 0, 0, 1, 1, 128 * kb, 256 * kb))   # too small

    def test_an_allocation_grows_by_half(self):
        self.assertEqual(self.lib.grow(0, 1000), 1000)   # the first: its image's size
        self.assertEqual(self.lib.grow(1000, 1200), 1500)   # a little larger: half again
        self.assertEqual(self.lib.grow(1000, 4000), 4000)   # much larger: its size


if __name__ == '__main__':
    unittest.main()
