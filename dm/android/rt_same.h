// Whether two SetRenderTargets records name the same targets (gfx_vk.c OP_SET_RT), as a plain function, so dm/tools/tests/test_rt_same.py checks it on the host.
// Why: the Vulkan replay ended the open render pass at every OP_SET_RT, and a game that sets the targets it is drawing into again (Ocarina of Time does so between the draws
// of its scene passes) had its pass ended and begun again with the targets loaded and stored once more: on a tiler GPU the whole target through memory twice, and the pass's
// fixed cost again. The Metal replay keeps the pass open there (nvn_mtl.m "same-target continuation"). A record snapshots its texture objects (hle_nvn.c tex_snap), so two
// records of one texture hold two copies: the identity is the initialization serial, which the replay resolves textures by (vt_get_w), and the view's named fields, which
// are all the replay reads of a view (its two reserved bytes are not compared).
#pragma once
#include <stddef.h>
#include <string.h>
#include "nvn_obj.h"

static inline int rt_view_same(const view_t *a, const view_t *b) { return !memcmp(a, b, offsetof(view_t, _rsv)); }
static inline int rt_tex_same(const tex_t *a, const tex_t *b) { return a == b || (a && b && a->serial == b->serial); }
static inline int rt_same(const p_set_rt *a, const p_set_rt *b) {
    if (a->n != b->n || a->n < 0 || a->n > 8) return 0;
    for (int i = 0; i < a->n; i++) {
        if (!rt_tex_same(a->color[i], b->color[i]) || !a->has_cview[i] != !b->has_cview[i]) return 0;
        if (a->has_cview[i] && !rt_view_same(&a->cview[i], &b->cview[i])) return 0;
    }
    if (!rt_tex_same(a->depth, b->depth) || !a->has_dview != !b->has_dview) return 0;
    return !a->has_dview || rt_view_same(&a->dview, &b->dview);
}
