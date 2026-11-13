"""dm/android/tex_aspect.h, which aspect of its image a texture slot reads (gfx_vk_draw.inc tex_aspect): a depth-stencil texture its depth, its stencil in stencil mode
(set by a view, else by the texture's builder), as nvn_mtl.m's X32_Stencil8 views do. Xenoblade Chronicles 2's deferred lighting tests stencil bits through such a
view; read as depth, the bits followed the depth and a stipple of unlit pixels covered every lit surface. Built with the system's C compiler and called through ctypes.
Skipped without a C compiler."""
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
COLOR, DEPTH, STENCIL = 1, 2, 4   # VkImageAspectFlagBits


@unittest.skipIf(CC is None or os.name == 'nt', 'no C compiler')
class TexAspect(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert CC is not None   # (skipped without one; pyright doesn't follow skipIf)
        cls.tmp = Path(tempfile.mkdtemp())
        src = cls.tmp / 'a.c'
        src.write_text('#include "tex_aspect.h"\n'
                       '__attribute__((visibility("default"))) unsigned pick(unsigned img, int vs, int vst, int ts, int *missing) { return tex_aspect_pick(img, vs, vst, ts, missing); }\n')
        subprocess.run([*CC, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', str(REPO / 'dm/android'), str(src), '-o', str(cls.tmp / 'a.so')], check=True)
        cls.lib = ctypes.CDLL(str(cls.tmp / 'a.so'))
        cls.lib.pick.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_int)]
        cls.lib.pick.restype = ctypes.c_uint

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.tmp, ignore_errors=True)

    def pick(self, img, view_sets=0, view_stencil=0, tex_stencil=0):
        m = ctypes.c_int(-1); a = self.lib.pick(img, view_sets, view_stencil, tex_stencil, ctypes.byref(m)); return a, m.value

    def test_a_depth_stencil_texture_reads_depth(self):
        self.assertEqual(self.pick(DEPTH | STENCIL), (DEPTH, 0))
        self.assertEqual(self.pick(DEPTH | STENCIL, view_sets=1, view_stencil=0), (DEPTH, 0))   # a view in depth mode

    def test_stencil_mode_reads_the_stencil(self):
        self.assertEqual(self.pick(DEPTH | STENCIL, view_sets=1, view_stencil=1), (STENCIL, 0))   # XC2's lighting classification: the view sets it
        self.assertEqual(self.pick(DEPTH | STENCIL, tex_stencil=1), (STENCIL, 0))   # a texture built in stencil mode (Unreal Engine 4.27's stencil resources)

    def test_a_view_overrides_the_textures_mode(self):
        self.assertEqual(self.pick(DEPTH | STENCIL, view_sets=1, view_stencil=0, tex_stencil=1), (DEPTH, 0))
        self.assertEqual(self.pick(DEPTH | STENCIL, view_sets=1, view_stencil=1, tex_stencil=0), (STENCIL, 0))
        self.assertEqual(self.pick(DEPTH | STENCIL, view_sets=0, view_stencil=1, tex_stencil=0), (DEPTH, 0))   # a mode field the view does not set counts for nothing

    def test_stencil_mode_on_a_depth_only_image_reads_depth_and_says_so(self):
        self.assertEqual(self.pick(DEPTH, view_sets=1, view_stencil=1), (DEPTH, 1))
        self.assertEqual(self.pick(DEPTH, tex_stencil=1), (DEPTH, 1))

    def test_stencil_only_and_colour_images(self):
        self.assertEqual(self.pick(STENCIL), (STENCIL, 0))
        self.assertEqual(self.pick(COLOR, view_sets=1, view_stencil=1, tex_stencil=1), (COLOR, 0))


if __name__ == '__main__':
    unittest.main()
