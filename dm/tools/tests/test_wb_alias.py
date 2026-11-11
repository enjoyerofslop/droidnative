"""dm/android/wb_alias.h (whether a shader's binding of guest memory can be bound on the GPU copy of a write-back the same draw or dispatch made for another
binding: gfx_vk_draw.inc own_alias), built for the PC with the system's clang and called through ctypes. Needs no NDK."""
import ctypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
DST, ROW, OFF = 0x60cc587e00, 8192, 0x1200   # Final Fantasy Resonance's counts buffer, and a 256-aligned arena offset


def compiler():
    if os.name == 'nt': return None
    if sys.platform == 'darwin': return ['xcrun', 'clang']
    cc = shutil.which('clang') or shutil.which('cc')
    return [cc] if cc else None


@unittest.skipUnless(compiler(), 'no C compiler')
class WbAlias(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'a.c'
        src.write_text('#include "wb_alias.h"\n__attribute__((visibility("default"))) int at(int arena, size_t rows, uintptr_t dst, size_t rb, size_t off, uint64_t addr, '
                       'uint64_t n, uint64_t al, uint64_t *o) { return wb_alias_at(arena, rows, dst, rb, off, addr, n, al, o); }\n')
        subprocess.run([*compiler(), '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'a.so'], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'a.so'))
        cls.lib.at.argtypes = [ctypes.c_int, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_uint64, ctypes.c_uint64, ctypes.c_uint64,
                               ctypes.POINTER(ctypes.c_uint64)]

    def at(self, addr, n, al=64, arena=1, rows=1, dst=DST, rb=ROW, off=OFF):   # → the offset in the arena block, or None
        o = ctypes.c_uint64(0xdead)
        return o.value if self.lib.at(arena, rows, dst, rb, off, addr, n, al, ctypes.byref(o)) else None

    def test_the_same_range_again(self):   # the argument shader's second binding of its counts buffer: the first binding's copy, at its offset
        self.assertEqual(self.at(DST, ROW), OFF)

    def test_a_range_inside(self):   # a smaller binding inside the written range: the same copy, further in
        self.assertEqual(self.at(DST + 0x100, 0x200), OFF + 0x100)
        self.assertEqual(self.at(DST + ROW - 4, 4, al=4), OFF + ROW - 4)   # the last word

    def test_a_range_not_inside(self):   # partly outside, past the end, before the start: a copy of its own, as before
        self.assertIsNone(self.at(DST + ROW - 4, 8, al=4))
        self.assertIsNone(self.at(DST + ROW, 4, al=4))
        self.assertIsNone(self.at(DST - 4, 8, al=4))
        self.assertIsNone(self.at(DST + 0x100, ROW, al=4))

    def test_the_gpus_alignment(self):   # an offset the binding cannot take (minStorageBufferOffsetAlignment, minTexelBufferOffsetAlignment): its own copy
        self.assertIsNone(self.at(DST + 0x10, 0x100, al=64))
        self.assertEqual(self.at(DST + 0x40, 0x100, al=64), OFF + 0x40)
        self.assertEqual(self.at(DST + 0x10, 0x100, al=0), OFF + 0x10)

    def test_only_one_row_arena_copies(self):   # a staging buffer's (a texture copy) or a linear render target's rows are no buffer to bind
        self.assertIsNone(self.at(DST, ROW, arena=0))
        self.assertIsNone(self.at(DST, 0x100, rows=4))

    def test_an_empty_binding(self):
        self.assertIsNone(self.at(DST, 0))

    def test_no_wraparound(self):   # an address and size whose sum wraps past 2^64 is not inside
        self.assertIsNone(self.at(DST + 0x100, (1 << 64) - 0x80))


if __name__ == '__main__':
    unittest.main()
