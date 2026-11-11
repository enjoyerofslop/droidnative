"""dm/android/pk_guard.h (the start-up list's marker and skip list: an entry whose compile never finishes is left out from the next start on), built for the PC with the
system's clang and driven through ctypes on records like the list's. POSIX only: skipped on Windows, and without a C compiler."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
REC = 96   # any record size: the list's (PK_REC) depends on the replay's key, and the header takes it as an argument

CC = ['xcrun', 'clang'] if sys.platform == 'darwin' and shutil.which('xcrun') else [shutil.which('clang') or shutil.which('cc') or '']
SRC = '''#include "pk_guard.h"
#define X __attribute__((visibility("default")))
X int g_open(const char *p) { return pkg_open(p); }
X void g_begin(int fd, const uint8_t *r, size_t n) { pkg_begin(fd, r, n); }
X void g_end(int fd) { pkg_end(fd); }
X void g_crashed(int fd, size_t n) { pkg_crashed(fd, n); }
X int g_take(const char *p, uint8_t *r, size_t n, int *crashed) { return pkg_take(p, r, n, crashed); }
X size_t g_load(const char *p, size_t n, uint8_t **out) { return pkg_skip_load(p, n, out); }
X int g_add(const char *p, const uint8_t *r, size_t n) { return pkg_skip_add(p, r, n); }
X void g_free(void *q) { free(q); }
'''


def rec(i):   # a record with its own bytes
    return bytes((i * 7 + j) & 0xff for j in range(REC))


@unittest.skipIf(os.name == 'nt' or not CC[-1], 'POSIX file calls and a C compiler needed')
class PkGuard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / 'g.c').write_text(SRC)
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', cls.tmp / 'g.c', '-o', cls.tmp / 'g.so'], check=True)
        L = cls.lib = ctypes.CDLL(str(cls.tmp / 'g.so'))
        L.g_load.restype = ctypes.c_size_t
        L.g_load.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.POINTER(ctypes.c_uint8))]
        L.g_take.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_int)]
        L.g_begin.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t]
        L.g_crashed.argtypes = [ctypes.c_int, ctypes.c_size_t]
        L.g_add.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t]
        L.g_open.argtypes = [ctypes.c_char_p]
        L.g_free.argtypes = [ctypes.c_void_p]

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        self.d = Path(tempfile.mkdtemp(dir=self.tmp)); self.mk = str(self.d / 'c.making4').encode(); self.sk = str(self.d / 'c.skip4').encode()

    def take(self):   # → (record or None, crashed)
        buf = ctypes.create_string_buffer(REC); cr = ctypes.c_int(-1)
        ok = self.lib.g_take(self.mk, buf, REC, ctypes.byref(cr))
        return (buf.raw if ok else None), cr.value

    def load(self):
        p = ctypes.POINTER(ctypes.c_uint8)(); n = self.lib.g_load(self.sk, REC, ctypes.byref(p))
        out = [bytes(p[i * REC:(i + 1) * REC]) for i in range(n)]
        self.lib.g_free(p); return out

    def start(self, crash_at=None, crashed=False, entries=5):   # a session's prewarm over entries 0..entries-1, ending (without pkg_end) at crash_at
        fd = self.lib.g_open(self.mk); self.assertGreaterEqual(fd, 0)
        for i in range(entries):
            self.lib.g_begin(fd, rec(i), REC)
            if i == crash_at:
                if crashed: self.lib.g_crashed(fd, REC)
                break
            self.lib.g_end(fd)
        os.close(fd)

    def test_a_start_that_finishes_its_compiles_leaves_nothing(self):
        self.start(); self.assertEqual(self.take(), (None, 0))

    def test_a_start_that_ends_in_a_compile_leaves_that_entry_once(self):
        self.start(crash_at=3)
        self.assertEqual(self.take(), (rec(3), 0))
        self.assertFalse(os.path.exists(self.mk)); self.assertEqual(self.take(), (None, 0))

    def test_the_crash_hooks_flag(self):
        self.start(crash_at=2, crashed=True); self.assertEqual(self.take(), (rec(2), 1))

    def test_a_record_without_its_busy_byte_counts_and_a_part_record_does_not(self):
        Path(self.mk.decode()).write_bytes(rec(4)); self.assertEqual(self.take(), (rec(4), 0))
        Path(self.mk.decode()).write_bytes(rec(4)[:REC - 1]); self.assertEqual(self.take(), (None, 0))

    def test_the_skip_list_holds_each_entry_once(self):
        self.assertEqual(self.load(), [])
        self.assertEqual(self.lib.g_add(self.sk, rec(1), REC), 1); self.assertEqual(self.lib.g_add(self.sk, rec(1), REC), 0)
        self.assertEqual(self.lib.g_add(self.sk, rec(2), REC), 1); self.assertEqual(self.load(), [rec(1), rec(2)])

    def test_a_part_record_at_the_skip_lists_end_is_overwritten(self):
        self.lib.g_add(self.sk, rec(1), REC)
        with open(self.sk.decode(), 'ab') as f: f.write(rec(9)[:10])   # a start that ended while it wrote
        self.lib.g_add(self.sk, rec(2), REC); self.assertEqual(self.load(), [rec(1), rec(2)])

    def test_the_next_start_leaves_out_the_entry_the_last_one_ended_in(self):   # the prewarm's own steps (gfx_vk_draw.inc pk_guard_init, prewarm_thread)
        self.start(crash_at=3, crashed=True)
        left, _ = self.take(); self.lib.g_add(self.sk, left, REC)
        skip = set(self.load()); listed = [rec(i) for i in range(5) if rec(i) not in skip]
        self.assertEqual(listed, [rec(0), rec(1), rec(2), rec(4)])
        self.start(entries=0); self.assertEqual(self.take(), (None, 0))   # the session after makes the rest and leaves nothing


if __name__ == '__main__':
    unittest.main()
