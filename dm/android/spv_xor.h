// Maxwell's butterfly shuffle (SHFL.BFLY) as OpGroupNonUniformShuffleXor. The translator (Ryujinx's, in dmsh_xlate) writes it as OpGroupNonUniformShuffle to the
// lane ID ^ the mask, through its helper's Function variables (the lane loaded, bitcast to float and stored; loaded, bitcast to int, XORed with the mask). The
// Adreno 730's driver (Qualcomm V@0615.98, Vulkan 1.1, the Moto Razr Plus 2023) returns garbage from that shuffle in compute shaders: Final Fantasy Resonance's
// particle simulation summed its live particles with it, an emitter's count came back as 0x21d1f071, and the indirect draw of its sprites asked for billions of
// instances and hung the GPU. ShuffleXor by the same mask reads the same lane (the invocation whose ID is the lane's ^ the mask) and is right there.
// The rewrite: a shuffle whose index is the lane ID ^ b becomes ShuffleXor by b (a uint: bitcast from a 32-bit int). The index is followed through OpBitcast,
// OpCopyObject and OpLoad of a Function variable stored once, earlier in the same block; the lane ID is an OpLoad of the SubgroupLocalInvocationId built-in;
// b must be a global, a function parameter or defined before the shuffle in its block. Every other shuffle is left as it is. Exact on any GPU. Run before
// spv_wide, which keeps a ShuffleXor by a mask under 32 within its 32-lane warp, as Maxwell's 5-bit lane operand always is. Self-contained (no libc), so that
// dm/tools/tests/test_spv_xor.py builds it alone.
#pragma once
#include <stddef.h>
#include <stdint.h>

// Whether the module may need spv_xor: a shuffle and the lane ID built-in. One pass over the instruction heads
static int spv_xor_wanted(const uint32_t *w, size_t n) {
    if (n < 5 || w[0] != 0x07230203) return 0;
    int sh = 0, lane = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == 345) sh = 1;
        else if (op == 71 && len >= 4 && w[i + 2] == 11 && w[i + 3] == 41) lane = 1;   // OpDecorate BuiltIn SubgroupLocalInvocationId
        i += len;
    }
    return sh && lane;
}

// A function-body instruction without a result id (its x[2] is no result): OpLine, OpStore, OpCopyMemory, OpImageWrite, barriers, OpAtomicStore, merges,
// branches, returns, OpKill, OpUnreachable, lifetimes, OpNoLine, the geometry stream ops, OpTerminateInvocation and OpDemoteToHelperInvocation
static int spv_xor_nores(uint32_t op) {
    return op == 8 || op == 62 || op == 63 || op == 99 || op == 224 || op == 225 || op == 228 || (op >= 246 && op <= 257) || op == 317 || (op >= 218 && op <= 221) ||
           op == 4416 || op == 5380;
}
enum { SPX_DEF, SPX_BLK, SPX_ST, SPX_STP, SPX_STB, SPX_N };   // the scratch's arrays, bound words each
#define SPV_XOR_MULTI 0xffffffffu   // a variable stored more than once (or with an initializer); the lane ID, as spv_xor_follow's result
// The id x stands for, followed through bitcasts, copies and Function variables stored once earlier in the same block; the lane ID: SPV_XOR_MULTI
static uint32_t spv_xor_follow(const uint32_t *w, uint32_t bound, const uint32_t *s, uint32_t lane, uint32_t x) {
    const uint32_t *def = s + SPX_DEF * bound, *blk = s + SPX_BLK * bound, *st = s + SPX_ST * bound, *stp = s + SPX_STP * bound, *stb = s + SPX_STB * bound;
    for (int step = 0; step < 32 && x < bound && def[x]; step++) {
        const uint32_t *d = w + def[x]; uint32_t op = d[0] & 0xffff, len = d[0] >> 16;
        if ((op == 124 || op == 83) && len == 4) { x = d[3]; continue; }   // OpBitcast, OpCopyObject
        if (op == 61 && len >= 4 && d[3] < bound) {   // OpLoad
            uint32_t p = d[3];
            if (p == lane) return SPV_XOR_MULTI;
            if (!st[p] || st[p] == SPV_XOR_MULTI || stp[p] >= def[x] || !blk[x] || stb[p] != blk[x]) return x;   // not stored once, earlier in this block
            x = st[p]; continue;
        }
        return x;
    }
    return x;
}
// The mask of shuffle x (at word i) when its index is the lane ID ^ the mask, else 0. i32: the 32-bit integer types
static uint32_t spv_xor_mask(const uint32_t *w, uint32_t bound, const uint32_t *s, uint32_t lane, const uint32_t *i32, const uint32_t *x) {
    const uint32_t *def = s + SPX_DEF * bound, *blk = s + SPX_BLK * bound;
    uint32_t t = spv_xor_follow(w, bound, s, lane, x[5]);
    if (t >= bound || !def[t]) return 0;
    const uint32_t *d = w + def[t];
    if ((d[0] & 0xffff) != 198 || (d[0] >> 16) != 5 || (d[1] != i32[0] && d[1] != i32[1])) return 0;   // OpBitwiseXor of a 32-bit integer
    uint32_t b = spv_xor_follow(w, bound, s, lane, d[3]) == SPV_XOR_MULTI ? d[4] : spv_xor_follow(w, bound, s, lane, d[4]) == SPV_XOR_MULTI ? d[3] : 0;
    if (!b || b >= bound || !def[b] || x[2] >= bound) return 0;
    if (blk[b] && (blk[b] != blk[x[2]] || def[b] >= def[x[2]])) return 0;   // defined in another block, or after the shuffle
    return b;
}

// w[n]: the module. scratch: SPX_N (5) × bound words (w[3]). o[cap]: the result.
// → the result's word count, or 0 when it is left as it is (no shuffle by the lane ID ^ a mask: *need 0), or o is NULL or smaller than *need (call again with
// that much). *nsites: the shuffles rewritten
static size_t spv_xor(const uint32_t *w, size_t n, uint32_t *scratch, uint32_t *o, size_t cap, size_t *need, int *nsites) {
    *need = 0; *nsites = 0;
    if (n < 5 || w[0] != 0x07230203) return 0;
    uint32_t bound = w[3], lane = 0, tu = 0, i32[2] = {0, 0}, cur = 0; int fn = 0;
    uint32_t *def = scratch + SPX_DEF * bound, *blk = scratch + SPX_BLK * bound, *st = scratch + SPX_ST * bound, *stp = scratch + SPX_STP * bound, *stb = scratch + SPX_STB * bound;
    for (uint32_t i = 0; i < SPX_N * bound; i++) scratch[i] = 0;
    // each value's instruction and block (function bodies, global constants and variables), the Function variables' stores, the lane ID variable, the 32-bit ints
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        const uint32_t *x = w + i; uint32_t r = 0;
        if (op == 54) fn = 1;   // OpFunction
        if (op == 248 && len == 2) cur = x[1];   // OpLabel
        else if (op == 56) cur = 0;   // OpFunctionEnd
        else if (op == 71 && len >= 4 && x[2] == 11 && x[3] == 41 && x[1] < bound) lane = x[1];   // OpDecorate BuiltIn SubgroupLocalInvocationId
        else if (op == 21 && len == 4 && x[2] == 32) { if (!x[3]) tu = x[1]; if (!i32[0]) i32[0] = x[1]; else if (!i32[1]) i32[1] = x[1]; }   // OpTypeInt 32
        else if (op == 62 && len >= 3 && x[1] < bound) {   // OpStore to a Function variable: its one value, or several
            uint32_t p = x[1];
            if (def[p] && (w[def[p]] & 0xffff) == 59 && st[p] != SPV_XOR_MULTI) { if (!st[p]) { st[p] = x[2]; stp[p] = (uint32_t)i; stb[p] = cur; } else st[p] = SPV_XOR_MULTI; }
        }
        else if (op == 59 && len >= 4) { r = x[2]; if (len >= 5 && r < bound) st[r] = SPV_XOR_MULTI; }   // OpVariable (an initializer: not followed)
        else if (!fn && (op == 41 || op == 42 || op == 43 || op == 44 || op == 46) && len >= 3) r = x[2];   // a global constant
        else if (fn && op != 54 && op != 56 && !spv_xor_nores(op) && len >= 3) r = x[2];   // a function-body value: type, result
        if (r && r < bound && !def[r]) { def[r] = (uint32_t)i; blk[r] = cur; }
        i += len;
    }
    if (!lane || !tu) return 0;
    int sites = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *x = w + i; i += len;
        if (op == 345 && len == 6 && x[5] < bound && spv_xor_mask(w, bound, scratch, lane, i32, x)) sites++;
    }
    if (!sites) return 0;
    *need = n + (size_t)sites * 4 + 8;
    if (!o || cap < *need) return 0;
    uint32_t nb = bound; size_t k = 0;
    for (size_t i = 0; i < 5; i++) o[k++] = w[i];
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *x = w + i; i += len;
        uint32_t b = op == 345 && len == 6 && x[5] < bound ? spv_xor_mask(w, bound, scratch, lane, i32, x) : 0;
        if (!b) { if (k + len > cap) return 0; for (uint32_t q = 0; q < len; q++) o[k++] = x[q]; continue; }
        if (k + 10 > cap) return 0;
        if (w[def[b] + 1] != tu) { uint32_t c = nb++; o[k++] = 4u << 16 | 124; o[k++] = tu; o[k++] = c; o[k++] = b; b = c; }   // OpBitcast to uint
        o[k++] = 6u << 16 | 346; o[k++] = x[1]; o[k++] = x[2]; o[k++] = x[3]; o[k++] = x[4]; o[k++] = b;   // OpGroupNonUniformShuffleXor type result scope value mask
    }
    o[3] = nb; *nsites = sites;
    return k;
}
#undef SPV_XOR_MULTI
