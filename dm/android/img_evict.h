// The image eviction rules (gfx_vk_evict.inc) as plain functions of what the replay knows about an image, so dm/tools/tests/test_img_evict.py checks them on the host
#pragma once
#include <stdint.h>
#include <stdlib.h>
// Clean: its content is still its storage's (a packaged texture, or a shared one filled from its storage when made), nothing on the GPU wrote it, the texture pool by
// ID never read it (a view dropped from the pool set reads 0 until the sync after a draw reads its ID again), and no lookup for age presents
static inline int ie_clean(int gpu_w, int pool_read, int pkg, int shared, int filled, uint64_t last_present, uint64_t now, uint64_t age) {
    return !gpu_w && !pool_read && (pkg || (shared && filled)) && now - last_present >= age;
}
// A shared image: its pool, its storage range there, the presents of its last lookup and of its last write by the GPU (0: none), and the caller's own pointer for it
typedef struct { uint64_t pool; int64_t lo, hi; uint64_t last_present, last_w; void *p; } ie_ent;
// a was overwritten by b: b was written after a's last lookup and covers at least half of a's storage (layouts are padded: an image another one only clips at its
// edge kept its content on the console), and a had no lookup for age presents
static inline int ie_overwritten(const ie_ent *a, const ie_ent *b, uint64_t now, uint64_t age) {
    int64_t lo = a->lo > b->lo ? a->lo : b->lo, hi = a->hi < b->hi ? a->hi : b->hi;
    return a->pool == b->pool && hi > lo && b->last_w > a->last_present && now - a->last_present >= age && 2 * (hi - lo) >= a->hi - a->lo;
}
static inline int ie_cmp(const void *x, const void *y) {
    const ie_ent *a = x, *b = y;
    return a->pool != b->pool ? (a->pool < b->pool ? -1 : 1) : a->lo != b->lo ? (a->lo < b->lo ? -1 : 1) : 0;
}
// Sorts e by pool and offset and marks each entry another one overwrote (mark[i] for e[i] after the sort). Every pair whose storage overlaps is looked at once:
// sorted by offset, the entries that overlap e[i] from after it are exactly those that start before it ends
static inline void ie_sweep(ie_ent *e, uint32_t n, uint64_t now, uint64_t age, uint8_t *mark) {
    qsort(e, n, sizeof *e, ie_cmp);
    for (uint32_t i = 0; i < n; i++) mark[i] = 0;
    for (uint32_t i = 0; i < n; i++) for (uint32_t j = i + 1; j < n && e[j].pool == e[i].pool && e[j].lo < e[i].hi; j++) {
        if (ie_overwritten(&e[i], &e[j], now, age)) mark[i] = 1;
        if (ie_overwritten(&e[j], &e[i], now, age)) mark[j] = 1;
    }
}
