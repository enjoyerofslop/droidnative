"""dm/android/gpu_floor.h (the GPU clock floor's rules: DM_VK_GPU_FLOOR, the Android launcher's Keep the GPU clock up), built for the PC with the system's clang and driven
through ctypes against a stand-in for Qualcomm's kernel driver: which contexts get the floor (the Vulkan device's, not the ones the process's descriptors owned before), the
level each is sent where the GMU or the kernel decides the clock, a refusal, and no call at all when the setting is off. POSIX only: skipped on Windows, and without a C compiler."""
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
# The stand-in: descriptors 0-7, each owning the contexts k_own gives it. Like KGSL, the constraint call answers EINVAL for a context its descriptor doesn't own; a kernel
# that decides the clock itself (host DCVS) answers EINVAL to any level but the highest; k_refuse makes it refuse every level (EPERM)
SRC = '''#include "gpu_floor.h"
#define X __attribute__((visibility("default")))
enum { FDS = 8 };
static unsigned char own[FDS][GF_IDS]; static unsigned lvl[FDS][GF_IDS]; static int host, refuse, calls;
static int fake(int fd, unsigned id, unsigned type, unsigned level) {
    calls++;
    if (fd < 0 || fd >= FDS || id >= GF_IDS || !own[fd][id]) return -EINVAL;
    if (type == GF_CONSTRAINT_NONE) { lvl[fd][id] = 0; return 0; }
    if (refuse) return -EPERM;
    if (host && level != GF_LEVEL_MAX) return -EINVAL;
    lvl[fd][id] = level; return 0;
}
static gf_state s;
X void k_reset(void) { memset(own, 0, sizeof own); memset(lvl, 0, sizeof lvl); host = refuse = calls = 0; memset(&s, 0, sizeof s); }
X void k_own(int fd, unsigned id) { own[fd][id] = 1; }
X void k_mode(int h, int r) { host = h; refuse = r; }
X int k_calls(void) { return calls; }
X unsigned k_level(int fd, unsigned id) { return lvl[fd][id]; }
X int g_pct(const char *v) { return gf_pct(v); }
X unsigned g_level(int pct, int h) { return gf_level(pct, h); }
X void g_set_pct(int p) { s.pct = p; }
X void g_before(const int *fd, int n) { gf_before(&s, fake, fd, n); }
X int g_after(const int *fd, int n) { return gf_after(&s, fake, fd, n); }
X int g_apply(void) { return s.n ? gf_apply(&s, fake) : 0; }
X int g_host(void) { return s.host; }
X int g_last(void) { return s.last; }
X int g_ctx(int k, int *fd) { *fd = s.ctx[k].fd; return (int)s.ctx[k].id; }
X unsigned long long g_sent(void) { return s.sent; }
X unsigned long long g_refused(void) { return s.refused; }
'''
EINVAL, EPERM, MAX = 22, 1, 1


@unittest.skipIf(os.name == 'nt' or not CC[-1], 'a C compiler needed')
class GpuFloor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        (cls.tmp / 'g.c').write_text(SRC)
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', cls.tmp / 'g.c', '-o', cls.tmp / 'g.so'], check=True)
        L = cls.lib = ctypes.CDLL(str(cls.tmp / 'g.so'))
        L.g_pct.argtypes = [ctypes.c_char_p]
        L.g_level.restype = L.k_level.restype = ctypes.c_uint
        L.g_sent.restype = L.g_refused.restype = ctypes.c_ulonglong
        L.g_ctx.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int)]

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self): self.lib.k_reset()

    @staticmethod
    def fds(*fd): return (ctypes.c_int * max(len(fd), 1))(*fd), len(fd)

    def start(self, pct, before, after):   # the replay's steps around vkCreateDevice (gfx_vk_floor.inc): ownership before, the driver's new contexts, then the floor
        L = self.lib; L.g_set_pct(pct)
        for fd, ids in before.items():
            for i in ids: L.k_own(fd, i)
        L.g_before(*self.fds(*before))
        for fd, ids in after.items():
            for i in ids: L.k_own(fd, i)
        return L.g_after(*self.fds(*sorted(set(before) | set(after))))

    def ctxs(self):
        out = []
        for k in range(8):
            fd = ctypes.c_int(); i = self.lib.g_ctx(k, ctypes.byref(fd))
            if not i: break
            out.append((fd.value, i))
        return out

    def test_the_value_off_and_its_range(self):
        for v, want in [(None, 0), (b'', 0), (b'0', 0), (b'off', 0), (b'-5', 0), (b'100', 100), (b'250', 100), (b'60', 60), (b'1', 1)]:
            with self.subTest(v=v): self.assertEqual(self.lib.g_pct(v), want)

    def test_the_level_sent(self):
        self.assertEqual(self.lib.g_level(100, 0), MAX)      # the launcher's value: the highest clock, on either kind of GPU
        self.assertEqual(self.lib.g_level(100, 1), MAX)
        self.assertEqual(self.lib.g_level(60, 0), 60)        # a floor in % where the GMU takes one
        self.assertEqual(self.lib.g_level(60, 1), MAX)       # the highest clock where the kernel takes nothing else
        self.assertEqual(self.lib.g_level(1, 0), 2)          # never 1 (the highest) or 0 (the lowest) by accident

    def test_off_makes_no_call_at_all(self):
        self.assertEqual(self.start(0, {5: [1, 2]}, {5: [3]}), 0)
        self.assertEqual(self.lib.g_apply(), 0)
        self.assertEqual(self.lib.k_calls(), 0)

    def test_only_the_devices_new_contexts_get_the_floor(self):
        n = self.start(100, {5: [1, 2]}, {5: [7], 6: [9]})   # contexts 1 and 2 were the front end's before the device; 7 on the same descriptor and 9 on a new one are the device's
        self.assertEqual((n, self.ctxs()), (2, [(5, 7), (6, 9)]))
        self.assertEqual([self.lib.k_level(5, i) for i in (1, 2, 7)] + [self.lib.k_level(6, 9)], [0, 0, MAX, MAX])
        self.assertEqual((self.lib.g_last(), self.lib.g_host(), self.lib.g_sent()), (0, 0, 2))

    def test_a_gmu_takes_a_floor_in_percent(self):
        self.start(60, {}, {5: [4]})
        self.assertEqual((self.lib.g_host(), self.lib.k_level(5, 4), self.lib.g_last()), (0, 60, 0))

    def test_where_the_kernel_decides_the_clock_the_highest_is_sent(self):
        self.lib.k_mode(1, 0)
        self.start(60, {}, {5: [4]})
        self.assertEqual((self.lib.g_host(), self.lib.k_level(5, 4), self.lib.g_last()), (1, MAX, 0))

    def test_a_refusal_is_reported_and_counted(self):
        self.lib.k_mode(0, 1)
        self.assertEqual(self.start(100, {}, {5: [4]}), 1)
        self.assertEqual((self.lib.g_last(), self.lib.g_refused(), self.lib.g_sent()), (-EPERM, 1, 0))

    def test_no_context_of_the_devices_own_sends_nothing(self):
        self.assertEqual(self.start(100, {5: [1]}, {}), 0)
        calls = self.lib.k_calls(); self.assertEqual(self.lib.g_apply(), 0); self.assertEqual(self.lib.k_calls(), calls)
        self.assertEqual(self.lib.k_level(5, 1), 0)

    def test_the_floor_is_sent_again_to_the_same_contexts(self):   # every 30 presents (fl_poll): the GMU forgets a context's rule while it is not registered
        self.start(100, {}, {5: [4]})
        self.assertEqual(self.lib.g_apply(), 0)
        self.assertEqual((self.lib.g_sent(), self.lib.k_level(5, 4)), (2, MAX))


if __name__ == '__main__':
    unittest.main()
