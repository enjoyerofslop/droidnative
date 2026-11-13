"""dm/android/apipe_rule.h, which draws the Vulkan replay may leave out while the pipeline they meet for the first time builds in the background (gfx_vk_draw.inc
apipe_ok), built with the system's C compiler and called through ctypes: targets drawn every frame let a draw wait, a target drawn for the first time, a linear render
target or a transform feedback capture do not, and a draw that tests depth EQUAL without writing it (a re-draw over a depth pre-pass, Skyrim's first-person hands)
builds at once unless DM_VK_ASYNC_EQUAL asks for the old rule. Skipped without a C compiler."""
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

NEVER, LESS, EQUAL, LEQUAL, GREATER, NOTEQUAL, GEQUAL, ALWAYS = range(1, 9)   # NVNdepthFunc


class Target(ctypes.Structure):   # apr_target
    _fields_ = [('runs', ctypes.c_int), ('linear', ctypes.c_int)]


@unittest.skipIf(CC is None or os.name == 'nt', 'no C compiler')
class AsyncPipelineRule(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert CC is not None   # (skipped without one; pyright doesn't follow skipIf)
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'a.c'
        src.write_text('#include "apipe_rule.h"\n'
                       '__attribute__((visibility("default"))) int leave(int tf, const apr_target *t, int n, int dt, int dw, int df, int too) '
                       '{ return apr_leave_out(tf, t, n, dt, dw, df, too); }\n'
                       '__attribute__((visibility("default"))) int redraw(int dt, int dw, int df) { return apr_redraw(dt, dw, df); }\n')
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), str(src), '-o', str(cls.tmp / 'a.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'a.so'))
        cls.lib.leave.argtypes = [ctypes.c_int, ctypes.POINTER(Target), ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        cls.lib.redraw.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def leave(self, targets, dt=1, dw=1, df=LEQUAL, tf=0, too=0):
        arr = (Target * max(1, len(targets)))(*[Target(r, lin) for r, lin in targets])
        return self.lib.leave(tf, arr, len(targets), dt, dw, df, too)

    def test_targets_drawn_every_frame_let_the_draw_wait(self):
        self.assertEqual(self.leave([(3, 0), (5, 0)]), 1)   # a colour target and the depth target, both drawn in the last three presents
        self.assertEqual(self.leave([(3, 0)], dt=0, dw=0, df=0), 1)   # no depth test at all

    def test_targets_new_linear_or_capture_build_at_once(self):
        self.assertEqual(self.leave([(3, 0), (2, 0)]), 0)   # the depth target drawn in two presents only: an environment map made at a load
        self.assertEqual(self.leave([(3, 1)]), 0)   # a linear render target the CPU reads back
        self.assertEqual(self.leave([(3, 0)], tf=1), 0)   # transform feedback
        self.assertEqual(self.leave([]), 0)   # no target

    def test_depth_equal_redraw_builds_at_once(self):
        # Skyrim's first-person colour pass: scene colour + the copy of the pre-pass's depth, depth EQUAL, no depth write
        self.assertEqual(self.leave([(3, 0), (3, 0)], dt=1, dw=0, df=EQUAL), 0)
        self.assertEqual(self.leave([(3, 0), (3, 0)], dt=1, dw=0, df=EQUAL, too=1), 1)   # DM_VK_ASYNC_EQUAL=1: the rule before
        self.assertEqual(self.leave([(3, 0)], dt=1, dw=1, df=EQUAL), 1)   # it writes depth: it lays the depth down itself
        self.assertEqual(self.leave([(3, 0)], dt=0, dw=0, df=EQUAL), 1)   # the test is off: the func is no promise
        self.assertEqual(self.leave([(3, 0)], dt=1, dw=0, df=LEQUAL), 1)   # blended effects over the scene: absent a few frames, no hole

    def test_redraw_predicate(self):
        self.assertEqual(self.lib.redraw(1, 0, EQUAL), 1)
        for dt, dw, df in ((0, 0, EQUAL), (1, 1, EQUAL), (1, 0, LEQUAL), (1, 0, LESS), (1, 0, ALWAYS), (1, 0, NOTEQUAL)):
            self.assertEqual(self.lib.redraw(dt, dw, df), 0, (dt, dw, df))


if __name__ == '__main__':
    unittest.main()
