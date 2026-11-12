"""dm/android/wb_promote.h, whether a read of a draw's pending storage buffer write takes the write-back's copy on the GPU after a barrier (gfx_vk_draw.inc wb_promote)
instead of waiting for the chunk. Xenoblade Chronicles 3 writes 16 and 64 bytes from a draw that a later draw reads as a uniform buffer, twice a frame, and each wait made
the replay thread and the GPU take turns. Built with the system's C compiler and called through ctypes. Skipped without a C compiler."""
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
W = 0x6a4781d400   # XC3's 64-byte write


@unittest.skipIf(CC is None or os.name == 'nt', 'no C compiler')
class WbPromote(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert CC is not None   # (skipped without one; pyright doesn't follow skipIf)
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'p.c'
        src.write_text('#include "wb_promote.h"\n'
                       '__attribute__((visibility("default"))) int ok(uintptr_t lo, uintptr_t hi, uintptr_t dst, size_t n, size_t rows, int st, int fwd, int inpl, int lin, int ds, int copy)'
                       ' { return wb_promote_ok(lo, hi, dst, n, rows, st, fwd, inpl, lin, ds, copy); }\n')
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), str(src), '-o', str(cls.tmp / 'p.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'p.so'))
        cls.lib.ok.argtypes = [ctypes.c_size_t] * 5 + [ctypes.c_int] * 6
        cls.lib.ok.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def ok(self, lo=W, n=64, dst=W, wn=64, rows=1, st=-1, fwd=0, inpl=0, lin=0, ds=0, copy=0):
        return self.lib.ok(lo, lo + n, dst, wn, rows, st, fwd, inpl, lin, ds, copy)

    def test_a_draws_write_read_whole(self):
        self.assertEqual(self.ok(), 1)   # XC3's uniform buffer read of the 64 bytes a draw wrote
        self.assertEqual(self.ok(lo=W + 16, n=16), 1)   # a part of it

    def test_a_read_the_write_does_not_hold(self):
        self.assertEqual(self.ok(n=65), 0)
        self.assertEqual(self.ok(lo=W - 16, n=32), 0)

    def test_other_kinds_of_write(self):
        self.assertEqual(self.ok(fwd=1), 0)   # forwardable already: read as it is
        self.assertEqual(self.ok(st=0), 0)   # a staging slice (a texture readback)
        self.assertEqual(self.ok(rows=4), 0)
        self.assertEqual(self.ok(inpl=1), 0)
        self.assertEqual(self.ok(lin=1), 0)
        self.assertEqual(self.ok(ds=1), 0)
        self.assertEqual(self.ok(copy=1), 0)   # a queued copy writes into the range too


if __name__ == '__main__':
    unittest.main()
