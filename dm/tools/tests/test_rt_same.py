"""dm/android/rt_same.h (whether two SetRenderTargets records name the same targets, so the Vulkan replay keeps its render pass open at the second: gfx_vk.c OP_SET_RT),
built for the PC with the system's clang against dm/gfx/nvn's record structs and called through ctypes. Needs no NDK."""
import ctypes
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
VIEW = 16   # sizeof(view_t)


def compiler():
    if os.name == 'nt': return None
    if sys.platform == 'darwin': return ['xcrun', 'clang']
    cc = shutil.which('clang') or shutil.which('cc')
    return [cc] if cc else None


def view(bits=0x1, target=0, base_level=0, nlevels=1, fmt=0, min_layer=0, nlayers=1, swz=(0, 1, 2, 3), rsv=0):   # view_t's bytes: bits, target, base_level, nlevels, format, min_layer, nlayers, swz[4], _rsv
    return struct.pack('<BBBBHHH4BH', bits, target, base_level, nlevels, fmt, min_layer, nlayers, *swz, rsv)


@unittest.skipUnless(compiler(), 'no C compiler')
class RtSame(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'a.c'
        # two records built from their serials (0: no texture at that slot), view flags and view bytes (9 x 16: the colour slots, then the depth view)
        src.write_text('#include "rt_same.h"\n'
                       'static tex_t T[2][9];\n'
                       'static void fill(p_set_rt *r, tex_t *t, int n, const uint64_t *ser, const uint8_t *has, const uint8_t *views) {\n'
                       '    memset(r, 0x5a, sizeof *r); r->n = n;\n'   # 0x5a: the padding bytes differ between the two, as two records in command memory may
                       '    for (int i = 0; i < 8; i++) { t[i].serial = ser[i]; r->color[i] = ser[i] ? &t[i] : NULL; r->has_cview[i] = has[i]; memcpy(&r->cview[i], views + 16 * i, 16); }\n'
                       '    t[8].serial = ser[8]; r->depth = ser[8] ? &t[8] : NULL; r->has_dview = has[8]; memcpy(&r->dview, views + 16 * 8, 16);\n'
                       '}\n'
                       '__attribute__((visibility("default"))) int same(int n0, const uint64_t *s0, const uint8_t *h0, const uint8_t *v0, int n1, const uint64_t *s1, const uint8_t *h1, const uint8_t *v1) {\n'
                       '    p_set_rt a, b; memset(T, 0, sizeof T); fill(&a, T[0], n0, s0, h0, v0); fill(&b, T[1], n1, s1, h1, v1); return rt_same(&a, &b);\n'
                       '}\n')
        subprocess.run([*compiler(), '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', '-I', REPO / 'dm/android', '-I', REPO / 'dm/gfx/nvn',
                        '-I', REPO / 'dm/gfx/nvn/include', src, '-o', cls.tmp / 'a.so'], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'a.so'))
        u8 = ctypes.POINTER(ctypes.c_uint8)
        cls.lib.same.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint64), u8, u8, ctypes.c_int, ctypes.POINTER(ctypes.c_uint64), u8, u8]
        cls.lib.same.restype = ctypes.c_int

    def same(self, a, b):   # a record: (n, serials[9], has_view[9], views[9])
        def args(r):
            n, ser, has, views = r
            return (ctypes.c_int(n), (ctypes.c_uint64 * 9)(*ser), (ctypes.c_uint8 * 9)(*has), (ctypes.c_uint8 * (9 * VIEW))(*b''.join(views)))
        return self.lib.same(*args(a), *args(b))

    @staticmethod
    def rec(n=1, color=(101,), depth=200, cviews=None, dview=None):
        ser = [0] * 9; has = [0] * 9; views = [view()] * 9
        for i, s in enumerate(color): ser[i] = s
        ser[8] = depth
        for i, v in enumerate(cviews or []):
            if v is not None: has[i] = 1; views[i] = v
        if dview is not None: has[8] = 1; views[8] = dview
        return n, ser, has, views

    def test_the_same_targets_from_two_records(self):   # Ocarina of Time: the scene's colour and depth targets set again between draws
        self.assertEqual(self.same(self.rec(), self.rec()), 1)
        a = self.rec(2, (101, 102), 200, [view(fmt=7), view(base_level=1)], view(bits=0x3, nlayers=1))
        self.assertEqual(self.same(a, a), 1)

    def test_another_texture_or_count(self):
        self.assertEqual(self.same(self.rec(color=(101,)), self.rec(color=(103,))), 0)
        self.assertEqual(self.same(self.rec(depth=200), self.rec(depth=201)), 0)
        self.assertEqual(self.same(self.rec(depth=200), self.rec(depth=0)), 0)   # no depth target at all
        self.assertEqual(self.same(self.rec(1, (101,)), self.rec(2, (101, 0))), 0)   # a second, empty slot is another record
        self.assertEqual(self.same(self.rec(1, (0,)), self.rec(1, (0,))), 1)   # both slots empty

    def test_a_view_present_on_one_side(self):
        self.assertEqual(self.same(self.rec(cviews=[view()]), self.rec()), 0)
        self.assertEqual(self.same(self.rec(dview=view()), self.rec()), 0)

    def test_a_view_that_differs(self):
        for other in (view(fmt=7), view(base_level=1), view(min_layer=1), view(nlayers=6), view(bits=0x5), view(swz=(0, 1, 2, 0))):
            self.assertEqual(self.same(self.rec(cviews=[view()]), self.rec(cviews=[other])), 0)
            self.assertEqual(self.same(self.rec(dview=view()), self.rec(dview=other)), 0)

    def test_the_reserved_bytes_are_not_compared(self):   # the replay reads none of them: a view with other reserved bytes names the same target
        self.assertEqual(self.same(self.rec(cviews=[view(rsv=0)]), self.rec(cviews=[view(rsv=0xbeef)])), 1)
        self.assertEqual(self.same(self.rec(dview=view(rsv=1)), self.rec(dview=view(rsv=2))), 1)

    def test_an_unset_view_is_not_compared(self):   # has_cview 0: the view bytes are whatever the record holds
        self.assertEqual(self.same(self.rec(cviews=[None]), (1, [101, 0, 0, 0, 0, 0, 0, 0, 200], [0] * 9, [view(fmt=9)] * 9)), 1)


if __name__ == '__main__':
    unittest.main()
