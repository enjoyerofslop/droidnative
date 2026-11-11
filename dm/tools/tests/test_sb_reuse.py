"""dm/android/sb_reuse.h (whether a read-only storage buffer's copy made earlier in the chunk can be bound again, from the dirty tracker's page generations:
gfx_vk_sbcopy.inc), built for the PC with the system's clang and driven through ctypes with a fake tracker. As nvn_dirty.c does, the fake stamps a page only when
it is written while protected. Needs no NDK."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
PAGE = 4096
UNTRACKED, REUSE, COPY, WRITTEN = 0, 1, 2, 3

HARNESS = r'''
#include "sb_reuse.h"
#define EXPORT __attribute__((visibility("default")))
enum { NP = 64 };
static unsigned char mem[NP * 4096] __attribute__((aligned(4096)));
static uint64_t gen[NP], now_ = 1; static int prot[NP], lo = 0, hi = NP, protects;
static uintptr_t pg(const void *a) { return ((uintptr_t)a - (uintptr_t)mem) / 4096; }
static const void *f_span(const void *a, size_t n) { return pg(a) >= (uintptr_t)lo && pg((const char *)a + n - 1) < (uintptr_t)hi ? (const void *)mem : 0; }
static uint64_t f_now(void) { return now_; }
static void f_protect(const void *a, size_t n) { for (uintptr_t p = pg(a); p <= pg((const char *)a + n - 1); p++) prot[p] = 1; protects++; }
static int f_since(const void *s, const void *a, size_t n, uint64_t st) { (void)s; for (uintptr_t p = pg(a); p <= pg((const char *)a + n - 1); p++) if (gen[p] > st) return 1; return 0; }
static const sbr_ops ops = {f_span, f_now, f_protect, f_since};
static sbr_ent tab[16]; static uint64_t next_buf = 1;
EXPORT void reset(void) { for (int i = 0; i < NP; i++) { gen[i] = 0; prot[i] = 0; } for (int i = 0; i < 16; i++) tab[i].src = 0; now_ = 1; lo = 0; hi = NP; protects = 0; next_buf = 1; }
EXPORT void track(int l, int h) { lo = l; hi = h; }
EXPORT void write_page(int p) { if (prot[p]) { gen[p] = ++now_; prot[p] = 0; } }   /* the fault handler: stamped and writable again; a write to a writable page leaves no trace */
EXPORT int protects_n(void) { return protects; }
EXPORT int is_protected(int p) { return prot[p]; }
/* sb_copy's flow: look, then reuse the entry's copy or stamp, copy (a new buffer id here) and note where */
EXPORT int bind(size_t off, size_t n, uint64_t seq, uint64_t *buf) {
    const void *src = mem + off, *span; sbr_ent *e = sbr_slot(tab, 15, src, n);
    int r = sbr_look(e, &ops, src, n, seq, &span);
    if (r == SBR_REUSE) { *buf = e->buf; return r; }
    if (r == SBR_UNTRACKED) { *buf = 0; return r; }
    sbr_stamp(e, &ops, src, n, seq, span); sbr_done(e, next_buf++, off); *buf = e->buf; return r;
}
'''


def compiler():
    if os.name == 'nt': return None
    if sys.platform == 'darwin': return ['xcrun', 'clang']
    cc = shutil.which('clang') or shutil.which('cc')
    return [cc] if cc else None


@unittest.skipUnless(compiler(), 'no C compiler')
class SbReuse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'h.c'; src.write_text(HARNESS)
        subprocess.run([*compiler(), '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'h.so'], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'h.so'))
        cls.lib.bind.argtypes = [ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64)]

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self): self.lib.reset()

    def bind(self, off, n, seq):   # → (result, the copy's buffer id)
        b = ctypes.c_uint64(0)
        return self.lib.bind(off, n, seq, ctypes.byref(b)), b.value

    def test_a_second_bind_in_the_chunk_takes_the_copy(self):   # Mario Kart World's 9.56 MB buffer, bound about 370 times a frame: copied once per chunk
        self.assertEqual(self.bind(PAGE, 10 * PAGE, 1), (COPY, 1))
        for _ in range(5): self.assertEqual(self.bind(PAGE, 10 * PAGE, 1), (REUSE, 1))
        self.assertEqual(self.lib.protects_n(), 1)

    def test_the_copy_protects_every_page_it_read(self):
        self.bind(PAGE + 100, 3 * PAGE, 1)
        self.assertEqual([self.lib.is_protected(p) for p in range(6)], [0, 1, 1, 1, 1, 0])

    def test_a_write_since_the_copy_makes_a_new_one(self):   # the game's write, or the replay's own update or a write-back landing
        self.bind(PAGE, 10 * PAGE, 1)
        self.lib.write_page(7)
        self.assertEqual(self.bind(PAGE, 10 * PAGE, 1), (WRITTEN, 2))
        self.assertEqual(self.bind(PAGE, 10 * PAGE, 1), (REUSE, 2))   # stamped and protected again, so unchanged since

    def test_a_write_elsewhere_changes_nothing(self):
        self.bind(PAGE, 4 * PAGE, 1)
        self.lib.write_page(20)
        self.assertEqual(self.bind(PAGE, 4 * PAGE, 1), (REUSE, 1))

    def test_a_new_chunk_copies_again(self):   # the arena copy lives as long as its chunk
        self.bind(PAGE, 4 * PAGE, 1)
        self.assertEqual(self.bind(PAGE, 4 * PAGE, 2), (COPY, 2))

    def test_another_size_at_the_same_address_is_another_copy(self):
        self.bind(PAGE, 4 * PAGE, 1)
        self.assertEqual(self.bind(PAGE, 2 * PAGE, 1)[0], COPY)
        self.assertEqual(self.bind(PAGE, 4 * PAGE, 1)[0], COPY)   # it took the slot, or another one; either way no stale reuse
        self.assertEqual(self.bind(PAGE, 4 * PAGE, 1)[0], REUSE)

    def test_untracked_memory_is_left_to_the_compare(self):   # no pool holds the whole range: ucopy as before
        self.lib.track(0, 8)
        self.assertEqual(self.bind(6 * PAGE, 4 * PAGE, 1), (UNTRACKED, 0))
        self.assertEqual(self.bind(2 * PAGE, 4 * PAGE, 1)[0], COPY)

    def test_a_write_to_a_page_already_written_is_still_seen_after_the_next_copy(self):
        self.bind(0, 2 * PAGE, 1); self.lib.write_page(1)          # the page is writable now, its write stamped
        self.assertEqual(self.bind(0, 2 * PAGE, 1)[0], WRITTEN)    # copied again, the page protected again
        self.lib.write_page(1)
        self.assertEqual(self.bind(0, 2 * PAGE, 1)[0], WRITTEN)


if __name__ == '__main__':
    unittest.main()
