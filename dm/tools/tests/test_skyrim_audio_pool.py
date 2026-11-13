"""Skyrim 1.1.404's audio pool cuts (dm/games/01000A10041EA000/patches.py): the four deque functions run under the pool mutex.

Checks the rows' layout, then runs each wrapper on ARM64 without game files: LockMutex and UnlockMutex and the original function's body
are hooks, the function's first instruction (moved into the wrapper) is the real one.
Optional dependency: unicorn. On macOS its JIT needs execution outside the sandbox.
"""
import importlib.util
from typing import Any, cast
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    import unicorn as uc   # pyright: ignore[reportMissingImports]  (optional; lint's environment has no unicorn)
    from unicorn import arm64_const as arm   # pyright: ignore[reportMissingImports]  (optional; lint's environment has no unicorn)
except ImportError:
    uc = arm = cast(Any, None)   # Any, so pyright reads the unicorn calls below, which run only when it imported (skipIf)

spec = importlib.util.spec_from_file_location('skyrim_patches', Path(__file__).resolve().parents[2] / 'games/01000A10041EA000/patches.py')
assert spec and spec.loader
patch = importlib.util.module_from_spec(spec); spec.loader.exec_module(patch)

TEXT_END, RO_OFF, BSS_USED_END, BSS_END = 0x1265968, 0x1266000, 0x3a857d0, 0x3a86000
STP_FRAME = 0xa9807bfd   # stp x29, x30, [sp, #imm]! with the immediate masked out (0xffc07fff)


def pool_rows():
    return [r for r in patch.CUTS[patch.build] if r[3].startswith('audio pool')]


class Layout(unittest.TestCase):
    def test_every_entry_branches_to_its_own_wrapper(self):
        rows = pool_rows()
        entries = {e: first for e, first, _ in patch.pool_functions}
        wrappers = [(at, len(new) // 2) for at, old, new, _ in rows if at not in entries]
        self.assertEqual(len(wrappers), 4)
        for at, old, new, _ in rows:
            if at in entries:
                self.assertEqual(old, entries[at])
                self.assertEqual(int.from_bytes(bytes.fromhex(old), 'little') & 0xffc07fff, STP_FRAME)
                w = int.from_bytes(bytes.fromhex(new), 'little')
                self.assertEqual(w & 0xfc000000, 0x14000000)
                target = at + ((w & 0x3ffffff) - ((w & 0x2000000) << 1)) * 4
                self.assertIn(target, [a for a, _ in wrappers])

    def test_wrappers_stay_in_the_text_padding_and_the_mutex_past_the_used_bss(self):
        ends = []
        for at, old, new, _ in pool_rows():
            if at >= TEXT_END:
                self.assertEqual(old, '00' * (len(new) // 2))
                self.assertEqual(at % 16, 0)
                self.assertLessEqual(at + len(new) // 2, RO_OFF)
                ends.append((at, at + len(new) // 2))
        ends.sort()
        self.assertTrue(all(a[1] <= b[0] for a, b in zip(ends, ends[1:])), 'wrappers overlap')
        self.assertGreaterEqual(patch.pool_mutex, BSS_USED_END)
        self.assertLessEqual(patch.pool_mutex + 0x20, BSS_END)   # nn::os::MutexType is 0x20 bytes


@unittest.skipIf(uc is None, 'optional ARM64 execution dependency: unicorn')
class Wrapper(unittest.TestCase):
    stack, stop = 0x6000000, 0x7000000

    def setUp(self):
        self.u = uc.Uc(uc.UC_ARCH_ARM64, uc.UC_MODE_ARM)
        for a, n in ((0xabd000, 0x1000), (0x1263000, 0x3000), (patch.pool_mutex & ~0xfff, 0x1000), (self.stack, 0x10000), (self.stop, 0x1000)):
            self.u.mem_map(a, n)
        for at, old, new, _ in pool_rows():
            self.u.mem_write(at, bytes.fromhex(new))
        self.events = []
        self.u.hook_add(uc.UC_HOOK_CODE, self.lock, begin=patch.lock_mutex, end=patch.lock_mutex)
        self.u.hook_add(uc.UC_HOOK_CODE, self.unlock, begin=patch.unlock_mutex, end=patch.unlock_mutex)
        for entry, first, _ in patch.pool_functions:
            self.u.hook_add(uc.UC_HOOK_CODE, self.body, begin=entry + 4, end=entry + 4, user_data=entry)

    def x(self, n): return self.u.reg_read(getattr(arm, f'UC_ARM64_REG_X{n}'))
    def setx(self, n, v): self.u.reg_write(getattr(arm, f'UC_ARM64_REG_X{n}'), v)
    def word(self): return struct.unpack('<I', self.u.mem_read(patch.pool_mutex + 0x18, 4))[0]   # the critical section's word

    def ret(self, u):
        u.reg_write(arm.UC_ARM64_REG_PC, u.reg_read(arm.UC_ARM64_REG_X30))

    def clobber(self):   # what a call may do to the caller-saved registers
        for n in list(range(4)) + list(range(9, 18)): self.setx(n, 0xdead0000 + n)

    def lock(self, u, address, size, data):
        self.events.append(('lock', self.x(0), self.word()))
        u.mem_write(self.x(0) + 0x18, struct.pack('<I', 1)); self.clobber(); self.ret(u)

    def unlock(self, u, address, size, data):
        self.events.append(('unlock', self.x(0), self.word()))
        u.mem_write(self.x(0) + 0x18, struct.pack('<I', 0)); self.clobber(); self.ret(u)

    def body(self, u, address, size, entry):
        # The function after its first instruction: x29 / x30 are on the stack where that instruction put them
        sp = u.reg_read(arm.UC_ARM64_REG_SP)
        frame = {0xabd548: 0x30}.get(entry, 0x20)
        self.events.append(('body', entry, tuple(self.x(n) for n in range(4)), self.word()))
        fp, lr = struct.unpack('<QQ', u.mem_read(sp, 16))
        self.setx(0, sum(self.x(n) for n in range(3)) & (1 << 64) - 1); self.clobber_after()
        u.reg_write(arm.UC_ARM64_REG_SP, sp + frame); self.setx(29, fp); self.setx(30, lr)
        u.reg_write(arm.UC_ARM64_REG_PC, lr)

    def clobber_after(self):
        for n in range(9, 18): self.setx(n, 0xbeef0000 + n)

    def call(self, entry, args):
        sp0 = self.stack + 0x8000
        self.u.reg_write(arm.UC_ARM64_REG_SP, sp0)
        for n, v in enumerate(args): self.setx(n, v)
        for n in range(19, 30): self.setx(n, 0x1900 + n)
        self.setx(30, self.stop)
        self.u.emu_start(entry, self.stop, count=200)
        self.assertEqual(self.u.reg_read(arm.UC_ARM64_REG_PC), self.stop)
        self.assertEqual(self.u.reg_read(arm.UC_ARM64_REG_SP), sp0)
        for n in range(19, 30): self.assertEqual(self.x(n), 0x1900 + n)
        return self.x(0)

    def test_each_function_runs_once_inside_the_mutex(self):
        for entry, first, _ in patch.pool_functions:
            self.events.clear()
            args = (0x7d07600020, 0x7d0786d1d0, 0x1000, 0x2000)
            result = self.call(entry, args)
            self.assertEqual(result, sum(args[:3]))
            self.assertEqual(self.events, [('lock', patch.pool_mutex, 0), ('body', entry, args, 1), ('unlock', patch.pool_mutex, 1)])
            self.assertEqual(self.word(), 0)

    def test_a_null_result_comes_back_as_null(self):
        # AllocBuffer returns null when the pool is empty or the size is over 4 KB; the wrapper must hand that back, not the mutex address
        result = self.call(0xabd548, (0, 0, 0, 0))
        self.assertEqual(result, 0)


if __name__ == '__main__':
    unittest.main()
