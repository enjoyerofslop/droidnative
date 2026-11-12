"""dm/android/stream_clip.h, where an indexed draw's vertex stream is looked up to among the forwardable write-backs (gfx_vk_draw.inc stream_clip). Xenoblade
Chronicles 3 binds each character's skinned vertices up to 1,120 bytes into the 576,000-byte buffer a draw under rasterizer discard writes, each binding as long as
the buffer. Looked up as bound, the range met the next buffer's write and the two were learned as one home range, whose second buffer sat off the storage buffer
alignment: every draw reading it waited for the GPU. A range that starts in a forwardable write-back, runs past its end and is no longer than it is looked up as far
as that end. Built with the system's C compiler and called through ctypes. Skipped without a C compiler."""
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
BUF = 576000   # XC3's skinned vertex buffer
A, B = 0x6a5e4c13d0, 0x6a5e54de00   # two of them, 0x30 apart


@unittest.skipIf(CC is None or os.name == 'nt', 'no C compiler')
class StreamClip(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert CC is not None   # (skipped without one; pyright doesn't follow skipIf)
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'c.c'
        src.write_text('#include "stream_clip.h"\n'
                       '__attribute__((visibility("default"))) uintptr_t clip(uintptr_t lo, uintptr_t hi, uintptr_t wl, size_t wn, int fwd) { return stream_clip_end(lo, hi, wl, wn, fwd); }\n')
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), str(src), '-o', str(cls.tmp / 'c.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'c.so'))
        cls.lib.clip.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_int]
        cls.lib.clip.restype = ctypes.c_size_t

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def clip(self, lo, n, wl=A, wn=BUF, fwd=1): return self.lib.clip(lo, lo + n, wl, wn, fwd)

    def test_xc3s_overrunning_streams_end_at_the_write_back(self):
        for off in (0xa0, 0x140, 0x460):   # the offsets XC3's draws bind its streams at, each with the buffer's size
            self.assertEqual(self.clip(A + off, BUF), A + BUF)
        self.assertEqual(self.clip(A + BUF - 16, BUF), A + BUF)   # starting in the last bytes

    def test_a_stream_inside_the_write_back_is_looked_up_as_bound(self):
        self.assertEqual(self.clip(A, BUF), 0)
        self.assertEqual(self.clip(A + 0x100, 0x1000), 0)

    def test_a_range_longer_than_the_write_back_is_looked_up_as_bound(self):
        self.assertEqual(self.clip(A + 0xa0, BUF + 1), 0)   # it may really fetch past the write-back: the wait stays
        self.assertEqual(self.clip(A, 2 * BUF + 0x30), 0)

    def test_only_a_forwardable_write_back_holding_the_first_byte(self):
        self.assertEqual(self.clip(A + 0xa0, BUF, fwd=0), 0)   # a draw's own write-back, or one of several rows
        self.assertEqual(self.clip(A - 16, BUF), 0)   # starts before it
        self.assertEqual(self.clip(A + BUF, BUF), 0)   # starts at its end: the next buffer's
        self.assertEqual(self.clip(B + 0xa0, BUF, wl=B), B + BUF)


if __name__ == '__main__':
    unittest.main()
