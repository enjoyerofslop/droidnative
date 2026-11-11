// Whether a read-only storage buffer's copy, made earlier in the same chunk, can be bound again, decided from the dirty tracker's page generations instead of a compare
// (gfx_vk_sbcopy.inc). Self-contained: the tracker's calls come in as sbr_ops, so dm/tools/tests/test_sb_reuse.py drives it with a fake tracker.
// The order that makes it safe is sbr_stamp's: the stamp, then the pages protected, then the caller's copy. A write after the protect moves a page's generation past the
// stamp (the game's through the fault handler, the replay's own through dm_guest_write_prepare or the same fault), and a write before it is in the copy.
#pragma once
#include <stddef.h>
#include <stdint.h>

typedef struct {
    const void *(*span)(const void *addr, size_t n);                              // the tracked range holding [addr, addr + n), as a handle; NULL: untracked
    uint64_t (*now)(void);                                                        // the current generation
    void (*protect)(const void *addr, size_t n);                                  // the pages read-only, so the next write to each is seen
    int (*since)(const void *span, const void *addr, size_t n, uint64_t stamp);   // 1: a page was written after the stamp
} sbr_ops;

// buf / off: where the caller put the copy (its buffer handle and offset); seq: the chunk it is in
typedef struct { const void *src; size_t n; uint64_t seq, stamp; const void *span; uint64_t buf, off; } sbr_ent;

enum { SBR_UNTRACKED = 0, SBR_REUSE = 1, SBR_COPY = 2, SBR_WRITTEN = 3 };

static inline sbr_ent *sbr_slot(sbr_ent *tab, unsigned mask, const void *src, size_t n) {
    uintptr_t h = ((uintptr_t)src >> 4) ^ ((uintptr_t)src >> 14) ^ (uintptr_t)n * 0x9e37u;
    return &tab[h & mask];
}
// SBR_REUSE: e->buf / e->off hold this chunk's copy of the same bytes, no page written since. SBR_WRITTEN: that copy exists but a page was written since; SBR_COPY: no copy
// in this chunk. Both mean copy again, after sbr_stamp, with *span (found here) passed to it. SBR_UNTRACKED: no generations to go by
static inline int sbr_look(const sbr_ent *e, const sbr_ops *o, const void *src, size_t n, uint64_t seq, const void **span) {
    *span = NULL;
    if (!src || !n) return SBR_UNTRACKED;
    if (e->src == src && e->n == n && e->seq == seq && e->span) { *span = e->span; return o->since(e->span, src, n, e->stamp) ? SBR_WRITTEN : SBR_REUSE; }
    *span = o->span(src, n);
    return *span ? SBR_COPY : SBR_UNTRACKED;
}
// Before the copy is made
static inline void sbr_stamp(sbr_ent *e, const sbr_ops *o, const void *src, size_t n, uint64_t seq, const void *span) {
    e->src = NULL; e->stamp = o->now(); o->protect(src, n);
    e->src = src; e->n = n; e->seq = seq; e->span = span; e->buf = 0; e->off = 0;
}
// After it: where it is
static inline void sbr_done(sbr_ent *e, uint64_t buf, uint64_t off) { e->buf = buf; e->off = off; }
static inline void sbr_forget(sbr_ent *e) { e->src = NULL; }
