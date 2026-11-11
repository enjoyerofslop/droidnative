"""dm/android/prev_file.h (the previous start's log and dumps kept as <name>.prev<extensions> before a new start truncates them), built for the PC with the system's clang
and driven through ctypes on real files. POSIX only: skipped on Windows, and without a C compiler."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
CC = ['xcrun', 'clang'] if sys.platform == 'darwin' and shutil.which('xcrun') else [shutil.which('clang') or shutil.which('cc') or '']
SRC = '''#include "prev_file.h"
#define X __attribute__((visibility("default")))
X int g_name(const char *p, char *out, size_t n) { return prev_name(p, out, n); }
X int g_keep(const char *p) { return keep_prev(p); }
'''


@unittest.skipIf(os.name == 'nt' or not CC[-1], 'POSIX file calls and a C compiler needed')
class PrevFile(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp()); (cls.tmp / 'p.c').write_text(SRC)
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', cls.tmp / 'p.c', '-o', cls.tmp / 'p.so'], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'p.so'))
        cls.lib.g_name.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t]; cls.lib.g_keep.argtypes = [ctypes.c_char_p]

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def name(self, p, n=1024):
        buf = ctypes.create_string_buffer(n); ok = self.lib.g_name(p.encode(), buf, n)
        return buf.value.decode() if ok else None

    def test_prev_goes_before_the_first_dot_of_the_file_name(self):
        self.assertEqual(self.name('/data/files/log.txt'), '/data/files/log.prev.txt')
        self.assertEqual(self.name('/data/files/bench_frames.tsv'), '/data/files/bench_frames.prev.tsv')
        self.assertEqual(self.name('/sd/a.b/audio.raw.1'), '/sd/a.b/audio.prev.raw.1')   # an output's numbered dump; a dot in a folder's name is not the file's
        self.assertEqual(self.name('/sd/dump'), '/sd/dump.prev')
        self.assertEqual(self.name('log.txt'), 'log.prev.txt')

    def test_a_name_that_does_not_fit_is_refused(self):
        self.assertIsNone(self.name('/data/files/log.txt', 10))

    def test_the_previous_runs_file_is_kept_over_an_older_one(self):
        d = Path(tempfile.mkdtemp(dir=self.tmp)); log, prev = d / 'log.txt', d / 'log.prev.txt'
        prev.write_text('two starts ago'); log.write_text('the killed run')
        self.assertEqual(self.lib.g_keep(str(log).encode()), 1)
        self.assertFalse(log.exists()); self.assertEqual(prev.read_text(), 'the killed run')

    def test_nothing_to_keep(self):
        d = Path(tempfile.mkdtemp(dir=self.tmp))
        self.assertEqual(self.lib.g_keep(str(d / 'log.txt').encode()), 0)   # a first start
        self.assertEqual(self.lib.g_keep(b''), 0); self.assertEqual(self.lib.g_keep(None), 0)   # a dump switch that is not set
        (d / 'sub.d').mkdir(); self.assertEqual(self.lib.g_keep(str(d / 'sub.d').encode()), 0)   # only files are moved
        self.assertTrue((d / 'sub.d').is_dir())


if __name__ == '__main__':
    unittest.main()
