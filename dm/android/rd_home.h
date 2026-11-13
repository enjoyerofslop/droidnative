// The home ranges of storage buffers that draws under rasterizer discard write (gfx_vk_draw.inc rd_bind_w) as plain functions, so dm/tools/tests/test_rd_home.py checks
// them on the host.
// Why: such a draw runs as a dispatch, and a later shader reads what it wrote on the GPU from its write-back's arena copy (fwd_find), but only from one write-back that
// covers every byte the shader binds. Xenoblade Chronicles 2 binds its bone matrix buffer differently on the two sides: each character's skinning draw from the
// character's own slot to the end of the 384,000-byte buffer, the character's draws the whole buffer from its start; a variant writes vertices that later draws read as
// streams bound 32 bytes on per attribute, past the written range. So every read met a write-back that did not cover it and the replay waited for the GPU, about 11
// times a frame on a Moto Razr Plus 2023 (24 instead of 30 fps). A read that meets a discarded draw's write-back it overlaps but is not covered by records the union
// of the two (rd_home_learn); from then on that draw's write takes a copy of the whole union, which the reads after it find whole.
#pragma once
#include <stddef.h>
#include <stdint.h>
enum { RD_HOME_N = 16 };
typedef struct { uintptr_t lo, hi; uint64_t t; } rd_home_ent;   // hi 0: unused; t: when last learned or used (the oldest goes first)
typedef struct { rd_home_ent e[RD_HOME_N]; uint64_t t; } rd_homes;
// [lo, hi) is one range: merged with every range it overlaps or touches. Refused (0) when the result would be over max bytes; 1 when a range was added or grew
static inline int rd_home_learn(rd_homes *h, uintptr_t lo, uintptr_t hi, size_t max) {
    if (hi <= lo) return 0;
    uintptr_t nl = lo, nh = hi; int grew = 1;
    for (int i = 0; i < RD_HOME_N; i++) { const rd_home_ent *x = &h->e[i]; if (x->hi && x->lo <= lo && hi <= x->hi) grew = 0; }
    for (int more = 1; more;) { more = 0;   // again while the union grows: it may reach a range the first one did not
        for (int i = 0; i < RD_HOME_N; i++) { const rd_home_ent *x = &h->e[i]; if (!x->hi || x->hi < nl || nh < x->lo) continue;
            if (x->lo < nl) { nl = x->lo; more = 1; }
            if (x->hi > nh) { nh = x->hi; more = 1; } } }
    if (nh - nl > max) return 0;
    int slot = -1;
    for (int i = 0; i < RD_HOME_N; i++) { rd_home_ent *x = &h->e[i]; if (x->hi && !(x->hi < nl || nh < x->lo)) { x->hi = 0; if (slot < 0) slot = i; } }   // the merged ones give up their slots
    if (slot < 0) for (int i = 0; i < RD_HOME_N; i++) if (!h->e[i].hi) { slot = i; break; }
    if (slot < 0) { slot = 0; for (int i = 1; i < RD_HOME_N; i++) if (h->e[i].t < h->e[slot].t) slot = i; }   // full: the one least recently learned or used
    h->e[slot] = (rd_home_ent){nl, nh, ++h->t};
    return grew;
}
// The range that holds all of [lo, hi): 1 and its bounds; 0 when none does (*hl, *hh are then lo and hi)
static inline int rd_home_find(rd_homes *h, uintptr_t lo, uintptr_t hi, uintptr_t *hl, uintptr_t *hh) {
    for (int i = 0; i < RD_HOME_N; i++) { rd_home_ent *x = &h->e[i]; if (x->hi && x->lo <= lo && hi <= x->hi) { x->t = ++h->t; *hl = x->lo; *hh = x->hi; return 1; } }
    *hl = lo; *hh = hi; return 0;
}
