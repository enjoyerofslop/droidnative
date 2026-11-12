"""dm/android/rd_home.h, the home ranges of storage buffers that draws under rasterizer discard write (gfx_vk_draw.inc rd_bind_w), built with the system's C compiler and
called through ctypes: a read a write did not cover is learned with it as one range, ranges that meet are merged, a full table gives up its least recently used range,
and a write finds the range that holds it. The shapes are Xenoblade Chronicles 2's: a character's skinning draw writes its bone buffer from its own slot to the end,
the character's draws read the whole buffer, and vertex streams are read 32 bytes on per attribute, past the written range. Skipped without a C compiler."""
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
N = 16   # RD_HOME_N
MAX = 4 << 20   # RD_HOME_MAX in gfx_vk_draw.inc
BONES = 0x6583a71400   # a bone buffer's address, 384,000 bytes


@unittest.skipIf(CC is None or os.name == 'nt', 'no C compiler')
class RdHome(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert CC is not None   # (skipped without one; pyright doesn't follow skipIf)
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'h.c'
        src.write_text('#include "rd_home.h"\n'
                       '#define X __attribute__((visibility("default")))\n'
                       'static rd_homes g;\n'
                       'X void reset(void) { memset(&g, 0, sizeof g); }\n'
                       'X int learn(uintptr_t lo, uintptr_t hi, size_t max) { return rd_home_learn(&g, lo, hi, max); }\n'
                       'X int find(uintptr_t lo, uintptr_t hi, uintptr_t *hl, uintptr_t *hh) { return rd_home_find(&g, lo, hi, hl, hh); }\n'
                       'X int count(void) { int n = 0; for (int i = 0; i < RD_HOME_N; i++) n += g.e[i].hi != 0; return n; }\n')
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-include', 'string.h', '-I', str(REPO / 'dm/android'), str(src),
                        '-o', str(cls.tmp / 'h.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'h.so'))
        cls.lib.learn.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t]
        cls.lib.find.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_size_t)]

    def setUp(self):
        self.lib.reset()

    def find(self, lo, hi):   # (range or None, the bounds handed back)
        hl, hh = ctypes.c_size_t(), ctypes.c_size_t()
        got = self.lib.find(lo, hi, ctypes.byref(hl), ctypes.byref(hh))
        return ((hl.value, hh.value) if got else None), (hl.value, hh.value)

    def test_a_whole_buffer_read_learns_the_skinning_writes_range(self):
        w = (BONES + 0x5d90, BONES + 384000)   # a character's slot to the end
        self.assertEqual(self.find(*w), (None, w))   # nothing learned: the write's own range
        self.assertEqual(self.lib.learn(BONES, BONES + 384000, MAX), 1)   # the character's draw read the whole buffer (union with the write: the same)
        self.assertEqual(self.find(*w)[0], (BONES, BONES + 384000))
        self.assertEqual(self.find(BONES + 0x2d0, BONES + 384000)[0], (BONES, BONES + 384000))   # another character's slot
        self.assertEqual(self.lib.learn(BONES + 0x100, BONES + 0x200, MAX), 0)   # inside: nothing new
        self.assertEqual(self.lib.count(), 1)

    def test_streams_read_past_the_write_grow_the_range(self):
        verts = 0x65859fd000
        self.lib.learn(verts, verts + 320000 + 0x20, MAX)   # attribute 1's stream, 32 bytes on, as long as the buffer
        self.assertEqual(self.lib.learn(verts, verts + 320000 + 0xe0, MAX), 1)   # attribute 7's: the range grows
        self.assertEqual(self.lib.count(), 1)
        self.assertEqual(self.find(verts, verts + 320000)[0], (verts, verts + 320000 + 0xe0))   # the write finds it, with the streams' tail

    def test_ranges_that_meet_merge_in_a_chain(self):
        self.lib.learn(0x1000, 0x2000, MAX); self.lib.learn(0x3000, 0x4000, MAX); self.lib.learn(0x5000, 0x6000, MAX)
        self.assertEqual(self.lib.count(), 3)
        self.assertEqual(self.lib.learn(0x1800, 0x3000, MAX), 1)   # meets the first and touches the second: the three ...
        self.assertEqual(self.lib.count(), 2)
        self.assertEqual(self.lib.learn(0x3f00, 0x5100, MAX), 1)   # ... and with this one, all of them
        self.assertEqual(self.lib.count(), 1)
        self.assertEqual(self.find(0x1000, 0x6000)[0], (0x1000, 0x6000))

    def test_a_range_over_the_cap_is_refused(self):
        self.assertEqual(self.lib.learn(0x10000, 0x10000 + MAX + 1, MAX), 0)
        self.assertEqual(self.lib.count(), 0)
        self.lib.learn(0x10000, 0x10000 + MAX // 2, MAX)
        self.assertEqual(self.lib.learn(0x10000 + MAX // 4, 0x10000 + MAX + 0x100, MAX), 0)   # the union would pass the cap: refused, the first kept as it was
        self.assertEqual(self.find(0x10000, 0x10000 + MAX // 2)[0], (0x10000, 0x10000 + MAX // 2))

    def test_a_full_table_gives_up_the_least_recently_used_range(self):
        for i in range(N): self.lib.learn(0x100000 * (i + 1), 0x100000 * (i + 1) + 0x1000, MAX)
        self.find(0x100000, 0x100800)   # the first, used again
        self.lib.learn(0x9000000, 0x9001000, MAX)   # a seventeenth: the second goes
        self.assertEqual(self.lib.count(), N)
        self.assertIsNotNone(self.find(0x100000, 0x101000)[0])
        self.assertIsNone(self.find(0x200000, 0x201000)[0])
        self.assertIsNotNone(self.find(0x9000000, 0x9001000)[0])

    def test_a_write_not_inside_a_range_is_not_found(self):
        self.lib.learn(0x1000, 0x2000, MAX)
        self.assertIsNone(self.find(0x1800, 0x2800)[0])   # past its end
        self.assertIsNone(self.find(0x0800, 0x1800)[0])   # before its start
        self.assertEqual(self.lib.learn(0x2000, 0x1000, MAX), 0)   # an empty range


if __name__ == '__main__':
    unittest.main()
