"""dm/android/pool_fileback.h, the rules of memory pools backed by a file (gfx_vk_fileback.inc, DM_VK_POOL_FILEBACK), built with the system's C compiler and called
through ctypes: which pools are backed, and how a range raw global memory places is cut out of the file's pieces. Skipped without a C compiler."""
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
SHADER, COMPRESSIBLE, PHYSICAL, VIRTUAL = 0x40, 0x80, 0x100, 0x200


class Piece(ctypes.Structure):   # fb_piece
    _fields_ = [('lo', ctypes.c_uint64), ('hi', ctypes.c_uint64), ('off', ctypes.c_uint64), ('pool', ctypes.c_void_p)]


@unittest.skipIf(CC is None or os.name == 'nt', 'no C compiler')
class PoolFileBacking(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert CC is not None   # (skipped without one; pyright doesn't follow skipIf)
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'f.c'
        src.write_text('#include "pool_fileback.h"\n'
                       '__attribute__((visibility("default"))) int kind(int f, uint64_t s, int k, uint64_t m) { return fb_kind(f, s, k, m); }\n'
                       '__attribute__((visibility("default"))) uint32_t cut(fb_piece *p, uint32_t n, uint32_t cap, uint64_t lo, uint64_t hi, uint64_t *po, uint64_t *pl, uint32_t *np) '
                       '{ return fb_cut(p, n, cap, lo, hi, po, pl, np, 16); }\n')
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), str(src), '-o', str(cls.tmp / 'f.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'f.so'))
        cls.lib.kind.argtypes = [ctypes.c_int, ctypes.c_uint64, ctypes.c_int, ctypes.c_uint64]
        cls.lib.cut.argtypes = [ctypes.POINTER(Piece), ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint64, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(ctypes.c_uint64),
                                ctypes.POINTER(ctypes.c_uint32)]
        cls.lib.cut.restype = ctypes.c_uint32

    def test_which_pools_are_backed(self):
        k = lambda f, mib, kinds=3: self.lib.kind(f, mib * MIB, kinds, 64 * MIB)
        self.assertEqual(k(0, 1737), 2)   # Ocarina of Time's large texture pool
        self.assertEqual(k(SHADER, 4), 1)   # shader code, any size
        self.assertEqual(k(0, 32), 0)   # under the minimum
        for f in (COMPRESSIBLE, PHYSICAL, VIRTUAL):
            self.assertEqual(k(f, 512), 0)
        self.assertEqual(k(0, 1737, kinds=1), 0)   # shader kind only
        self.assertEqual(k(SHADER, 4, kinds=2), 0)   # texture kind only
        self.assertEqual(k(0, 1737, kinds=0), 0)

    def cut(self, pieces, lo, hi):
        arr = (Piece * (len(pieces) + 1))(*[Piece(a, b, o, 1) for a, b, o in pieces]); po = (ctypes.c_uint64 * 16)(); pl = (ctypes.c_uint64 * 16)(); np = ctypes.c_uint32(0)
        n = self.lib.cut(arr, len(pieces), len(pieces) + 1, lo, hi, po, pl, ctypes.byref(np))
        return sorted((arr[i].lo, arr[i].hi, arr[i].off) for i in range(n)), sorted((po[i], pl[i]) for i in range(np.value))

    def test_a_placed_range_is_cut_out_of_the_file(self):
        p = [(0x10000, 0x50000, 0)]
        self.assertEqual(self.cut(p, 0x10000, 0x50000), ([], [(0, 0x40000)]))   # all of it
        self.assertEqual(self.cut(p, 0x10000, 0x20000), ([(0x20000, 0x50000, 0x10000)], [(0, 0x10000)]))   # its start
        self.assertEqual(self.cut(p, 0x40000, 0x60000), ([(0x10000, 0x40000, 0)], [(0x30000, 0x10000)]))   # its end, past it
        self.assertEqual(self.cut(p, 0x20000, 0x30000), ([(0x10000, 0x20000, 0), (0x30000, 0x50000, 0x20000)], [(0x10000, 0x10000)]))   # its middle: two pieces
        self.assertEqual(self.cut(p, 0x60000, 0x70000), (p, []))   # elsewhere
        two = [(0x10000, 0x20000, 0), (0x30000, 0x40000, 0x10000)]
        self.assertEqual(self.cut(two, 0x18000, 0x38000), ([(0x10000, 0x18000, 0), (0x38000, 0x40000, 0x18000)], [(0x8000, 0x8000), (0x10000, 0x8000)]))   # across two


if __name__ == '__main__':
    unittest.main()
