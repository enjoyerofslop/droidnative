// The rules of memory pools backed by a file (gfx_vk_fileback.inc) as plain functions, so dm/tools/tests/test_pool_fileback.py checks them on the host
#pragma once
#include <stdint.h>
// Which pools: by NVN's flags, at the pool's Initialize. 1: shader code (the replay translates it once and never reads it again); 2: any other pool of at least
// min_bytes that isn't compressible, physical or virtual: on Ocarina of Time the texture pools, which the replay reads only to upload a texture. kinds is a mask
// of the two (bit 0 shader, bit 1 texture); 0: neither
#define FB_SHADER_CODE 0x40
#define FB_COMPRESSIBLE 0x80
#define FB_PHYSICAL 0x100
#define FB_VIRTUAL 0x200
static inline int fb_kind(int flags, uint64_t size, int kinds, uint64_t min_bytes) {
    if (flags & FB_SHADER_CODE) return kinds & 1 ? 1 : 0;
    if (flags & (FB_COMPRESSIBLE | FB_PHYSICAL | FB_VIRTUAL)) return 0;
    return kinds & 2 && size >= min_bytes ? 2 : 0;
}
// A file-backed piece: the guest range, where it starts in the file, its pool
typedef struct { uintptr_t lo, hi; uint64_t off; const void *pool; } fb_piece;
// Cuts [lo, hi) out of the pieces (a range raw global memory placed): each overlap goes to the punch list (its file offset and length), a piece split in two by a cut
// in its middle takes another entry (while n < cap). Returns the new count
static inline uint32_t fb_cut(fb_piece *p, uint32_t n, uint32_t cap, uintptr_t lo, uintptr_t hi, uint64_t *poff, uint64_t *plen, uint32_t *np, uint32_t pcap) {
    for (uint32_t i = n; i-- > 0;) {
        uintptr_t a = lo > p[i].lo ? lo : p[i].lo, b = hi < p[i].hi ? hi : p[i].hi;
        if (a >= b) continue;
        if (*np < pcap) { poff[*np] = p[i].off + (a - p[i].lo); plen[*np] = b - a; (*np)++; }
        if (a == p[i].lo && b == p[i].hi) { p[i] = p[--n]; continue; }   // all of it
        if (a == p[i].lo) { p[i].off += b - p[i].lo; p[i].lo = b; continue; }   // its start
        if (b == p[i].hi) { p[i].hi = a; continue; }   // its end
        if (n < cap) { p[n] = (fb_piece){b, p[i].hi, p[i].off + (b - p[i].lo), p[i].pool}; n++; }   // its middle: the end becomes a piece of its own
        p[i].hi = a;
    }
    return n;
}
