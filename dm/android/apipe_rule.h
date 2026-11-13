// Which draws may be left out while the pipeline they meet for the first time builds in the background (gfx_vk_draw.inc apipe_ok, DM_VK_ASYNC_PIPE). A left-out draw is
// meant to show a few frames late on a target the game draws every frame, so every target of its pass must have been drawn into in this present and the two before
// (runs >= 3), and not be a linear render target (the CPU reads it back) or a transform feedback capture (later draws read what it writes).
// A draw that tests depth EQUAL without writing it re-draws geometry an earlier pass laid the depth down for (a depth pre-pass, or a copy of its depth): left out, it does
// not show late, because that depth keeps every other draw out of its pixels and the target's clear colour shows there instead. The Elder Scrolls V: Skyrim draws its
// first-person hands and weapons into its depth with a depth-only pipeline it has, copies that depth, and draws them in colour against the copy with depth EQUAL; left out
// for the frames its pipeline took to build, a new hand or weapon showed as a flat silhouette of the scene's clear colour (droidplay-core#444). Such a draw builds at once.
// Self-contained (no Vulkan headers), so that dm/tools/tests/test_apipe_rule.py builds it alone.
#pragma once

enum { APR_DEPTH_FUNC_EQUAL = 3 };   // NVN_DEPTH_FUNC_EQUAL

typedef struct { int runs, linear; } apr_target;   // a target of the draw's pass: presents in a row it was drawn in (vtex rt_runs), a linear render target

// a draw that re-draws geometry whose depth is in its depth attachment already: depth tested EQUAL, not written
static inline int apr_redraw(int depth_test, int depth_write, int depth_func) { return depth_test && !depth_write && depth_func == APR_DEPTH_FUNC_EQUAL; }

// 1 = the draw may be left out while its pipeline builds in the background; 0 = the pipeline builds at once. tf: a transform feedback capture; t: its pass's colour
// targets and depth target (n of them); redraw_too: depth-equal re-draws are left out as well (DM_VK_ASYNC_EQUAL=1, the rule before #444)
static inline int apr_leave_out(int tf, const apr_target *t, int n, int depth_test, int depth_write, int depth_func, int redraw_too) {
    if (tf || n <= 0) return 0;
    for (int i = 0; i < n; i++) if (t[i].runs < 3 || t[i].linear) return 0;
    return redraw_too || !apr_redraw(depth_test, depth_write, depth_func);
}
