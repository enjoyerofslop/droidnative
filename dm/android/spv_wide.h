// Maxwell's warp instructions on a GPU whose subgroups are wider than its 32-lane warp. The translator (Ryujinx's, in dmsh_xlate) runs before the GPU is known,
// with Ryujinx's default host subgroup size, 32, which Apple's SIMD-groups have: SHFL becomes a helper that keeps the lane ID's low five bits (the lane & the
// segment mask, the result valid up to lane 31 only) and shuffles to that lane, S2R SR_LANEID and the lane masks read the built-ins as they are, BALLOT takes
// the ballot's first 32 bits and VOTE is the whole subgroup's. On 64-lane subgroups (the Adreno 830's fragment and compute shaders: subgroupSize 64, its minimum
// and maximum) lanes 32-63 then read lanes 0-31, or keep their own value where Maxwell's derivative idiom (SHFL within the 2x2 quad, fwidth) wants a neighbour's: half
// of each wave's pixels get a wrong derivative, and a compute shader's warp-aggregated atomic (BALLOT, the lane masks and a SHFL from the warp's leader) leaves
// lanes 32-63 out of every count. spv_wide rewrites such a fragment or compute shader into what Ryujinx makes for a host subgroup over 32 (QueryHostSubgroupSize
// in HelperFunctionManager, InstEmitMove, InstEmitWarp), each 32 lanes of the subgroup one warp:
// - the lane ID: lane & 31, the lane within its warp;
// - OpGroupNonUniformShuffle: the index | (lane & ~31), the lane of its own warp;
// - a ballot's first component and a mask's component 0: its warp's component, lane >> 5;
// - All, Any and AllEqual (of a predicate): from its warp's ballot, as Ryujinx's EmitVote;
// - the subgroup size: 32.
// Exact on any subgroup of 32 lanes or more (on 32, lane & ~31 and lane >> 5 are 0). A module with other subgroup operations or other uses of the built-ins
// is left as it is, and so is one of another stage (SPV_WIDE_STAGES). spv_limits.h has the stages that run none. Self-contained (no libc), so that
// dm/tools/tests/test_spv_wide.py builds it alone.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "spv_lit.h"

enum { SPV_WIDE_DONE = 1, SPV_WIDE_KEPT = 2, SPV_WIDE_STAGE = 4 };   // rewritten; uses it cannot rewrite: as it is; of a stage it leaves: as it is
// The stages spv_wide rewrites: fragment shaders, whose quad shuffles (Maxwell's derivatives) t_quad_shuffle checks on a device, and compute shaders, whose
// whole-warp reductions t_warp_reduce checks (on the Adreno 840, as translated, the second warp's steps keep its own values and its lane 32 never adds its result).
// A mesh or task module's shuffles and votes are left as translated, its stage named by spv_wide_wanted for the replay's log, until a device test covers that stage
#define SPV_WIDE_STAGES 0x30u
// The most words one use becomes: AllEqual's 44 (two ballots, the lane's load and shift, two extracts, two compares, an OR). A shuffle becomes 20, a lane load 9
#define SPV_WIDE_SITE 48u
// The kinds of ids the scan follows: the built-in variables, a pointer to a mask's component 0, a ballot's result; 32-bit integer types and constants, the
// Input uint pointer types; bool values
enum { SWK_LANE = 1, SWK_SIZE, SWK_MASK, SWK_MPTR, SWK_BALLOT, SWK_OTHER, SWK_I32, SWK_CONST, SWK_PU, SWK_BOOL = 0x100 };
static int spv_wide_sgop(uint32_t op) { return (op >= 333 && op <= 366) || op == 4421 || op == 4422 || (op >= 4428 && op <= 4432) || op == 5296; }
static uint32_t spv_wide_bi(uint32_t b) {   // BuiltIn → its kind: SubgroupLocalInvocationId, SubgroupSize, Eq / Ge / Gt / Le / Lt masks, NumSubgroups and SubgroupId
    switch (b) { case 41: return SWK_LANE; case 36: return SWK_SIZE; case 38: case 40: return SWK_OTHER; default: return b >= 4416 && b <= 4420 ? SWK_MASK : 0; }
}
static int spv_wide_k(uint32_t k) { k &= 0xff; return k >= SWK_LANE && k <= SWK_OTHER; }
// An execution model's stage bit (VkShaderStageFlagBits): vertex 0x1 .. compute 0x20, task 0x40 and mesh 0x80 (EXT's and NV's); 0 for any other
static uint32_t spv_wide_stage(uint32_t model) { return model <= 5 ? 1u << model : model == 5267 || model == 5364 ? 0x40 : model == 5268 || model == 5365 ? 0x80 : 0; }
// o[k..]: the instruction op with its na operands, when it fits in cap words; else *full, and nothing (the result is then dropped)
static size_t spv_wide_put(uint32_t *o, size_t k, size_t cap, int *full, uint32_t op, const uint32_t *a, uint32_t na) {
    if (k + 1 + na > cap) { *full = 1; return k; }
    o[k++] = (na + 1) << 16 | op; for (uint32_t q = 0; q < na; q++) o[k++] = a[q];
    return k;
}
#define SPV_WIDE_PUT(op, ...) do { const uint32_t a_[] = {__VA_ARGS__}; k = spv_wide_put(o, k, cap, &full, (op), a_, (uint32_t)(sizeof a_ / sizeof *a_)); } while (0)
#define SPV_WIDE_COPY() (k = spv_wide_put(o, k, cap, &full, op, x + 1, len - 1))   // the instruction as it is

// The module's stage bit when it may need spv_wide: a subgroup instruction or built-in in a module whose stage (its entry points') runs them; else 0. spv_wide
// rewrites SPV_WIDE_STAGES only: of another, the caller says what it leaves. One pass over the instruction heads, without the scratch, so that the modules that
// use none cost next to nothing
static uint32_t spv_wide_wanted(const uint32_t *w, size_t n, uint32_t sg_stages) {
    if (n < 5 || w[0] != 0x07230203) return 0;
    uint32_t st = 0; int any = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == 15 && len >= 3) {   // OpEntryPoint: of a stage that runs none (spv_limits'), of no shader stage or of two stages, none
            uint32_t s = spv_wide_stage(w[i + 1]);
            if (!(sg_stages & s) || (st && st != s)) return 0;
            st = s;
        }
        if (spv_wide_sgop(op) || (op == 71 && len >= 4 && w[i + 2] == 11 && spv_wide_bi(w[i + 3]))) any = 1;
        i += len;
    }
    return any ? st : 0;
}

// w[n]: the module. sg_stages: subgroupSupportedStages. scratch: 2 × bound words (w[3]). o[cap]: the result.
// → the result's word count, or 0 when it is left as it is: its stage runs no subgroup operations or it uses none (*need 0), *what SPV_WIDE_KEPT or
// SPV_WIDE_STAGE, or o is NULL or smaller than *need, the words a rewrite takes at most (call again with that much)
static size_t spv_wide(const uint32_t *w, size_t n, uint32_t sg_stages, uint32_t *scratch, uint32_t *o, size_t cap, size_t *need, int *what) {
    *what = 0; *need = 0;
    if (n < 5 || w[0] != 0x07230203) return 0;
    uint32_t bound = w[3], *kind = scratch, *val = scratch + bound, model = 99, tu = 0, tb = 0, tv4u = 0, tpu = 0, lane = 0;
    for (uint32_t i = 0; i < 2 * bound; i++) scratch[i] = 0;
    int neps = 0, fn = 0, used = 0, bad = 0, sites = 0, votes = 0, ballotcap = 0; size_t ep = 0;
#define ID(x) ((x) < bound)
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        const uint32_t *x = w + i;
        if (op == 54) fn = 1;   // the functions come after every global declaration
        if (len >= 3 && tb && x[1] == tb && ID(x[2]) && op != 5 && op != 6 && op != 71 && op != 72) kind[x[2]] |= SWK_BOOL;   // a result of type bool
        if (op == 17 && len == 2 && x[1] == 64) ballotcap = 1;   // OpCapability GroupNonUniformBallot
        else if (op == 15 && len >= 3) { neps++; model = x[1]; ep = i; }   // OpEntryPoint model function "name" interface...
        else if (op == 71 && len >= 4 && x[2] == 11 && ID(x[1]) && spv_wide_bi(x[3])) {   // OpDecorate BuiltIn
            kind[x[1]] = spv_wide_bi(x[3]); if (x[3] == 41) lane = x[1];
        }
        else if (op >= 73 && op <= 75) bad = 1;   // decoration groups: not followed
        else if (op == 20 && len == 2) tb = x[1];   // OpTypeBool
        else if (op == 21 && len == 4 && x[2] == 32 && ID(x[1])) { kind[x[1]] = SWK_I32; if (!x[3]) tu = x[1]; }   // OpTypeInt 32
        else if (op == 23 && len == 4 && tu && x[2] == tu && x[3] == 4) tv4u = x[1];   // OpTypeVector uint 4
        else if (op == 32 && len == 4 && tu && x[2] == 1 && x[3] == tu && ID(x[1])) { tpu = x[1]; kind[x[1]] = SWK_PU; }   // OpTypePointer Input uint
        else if (op == 59 && !fn && len >= 4 && lane && x[2] == lane && !(ID(x[1]) && kind[x[1]] == SWK_PU)) bad = 1;   // the lane ID of another type: loaded as a uint below
        else if (op == 43 && len == 4 && ID(x[1]) && kind[x[1]] == SWK_I32 && ID(x[2])) { kind[x[2]] = SWK_CONST; val[x[2]] = x[3]; }   // OpConstant, 32-bit integer
        else if (fn && spv_wide_sgop(op)) {
            used = 1; sites++;
            int ok = 0;
            if (op == 345) ok = len == 6;   // Shuffle: type result scope value id
            else if (op == 339) { ok = len == 5 && tv4u && x[1] == tv4u && ID(x[2]); if (ok) kind[x[2]] = SWK_BALLOT; }   // Ballot: type result scope predicate
            else if (op >= 334 && op <= 336) { ok = len == 5 && tb && x[1] == tb && ID(x[4]) && (kind[x[4]] & SWK_BOOL); votes++; }   // All, Any, AllEqual of a predicate
            if (!ok) bad = 1;
        }
        else if (fn && op == 61 && len >= 4 && ID(x[3]) && spv_wide_k(kind[x[3]])) {   // OpLoad of the lane ID, the size or a mask's component 0
            uint32_t kd = kind[x[3]] & 0xff; used = 1; sites++;
            if ((kd != SWK_LANE && kd != SWK_SIZE && kd != SWK_MPTR) || !ID(x[1]) || kind[x[1]] != SWK_I32 || (kd == SWK_SIZE && x[1] != tu)) bad = 1;
        }
        else if (fn && (op == 65 || op == 66) && len >= 4 && ID(x[3]) && (kind[x[3]] & 0xff) == SWK_MASK) {   // an access chain to a mask's component
            if (len == 5 && ID(x[2]) && ID(x[4]) && kind[x[4]] == SWK_CONST && !val[x[4]]) { kind[x[2]] = SWK_MPTR; used = 1; sites++; } else bad = 1;
        }
        else if (fn && op == 81 && len >= 4 && ID(x[3]) && (kind[x[3]] & 0xff) == SWK_BALLOT) {   // a ballot's component
            if (len == 5 && !x[4] && x[1] == tu) sites++; else bad = 1;
        }
        else if (fn) for (uint32_t q = 1; q < len; q++) if (!spv_lit(op, q) && ID(x[q]) && spv_wide_k(kind[x[q]])) bad = 1;   // any other use of one: not followed
        i += len;
    }
    if (!used || neps != 1 || !(sg_stages & spv_wide_stage(model))) return 0;
    if (!(spv_wide_stage(model) & SPV_WIDE_STAGES)) { *what = SPV_WIDE_STAGE; return 0; }
    if (bad || !tu) { *what = SPV_WIDE_KEPT; return 0; }
    *what = SPV_WIDE_DONE;
    *need = n + SPV_WIDE_SITE * (size_t)sites + 64;   // each use at its most, and the 45 words of declarations at most
    if (!o || cap < *need) return 0;
    uint32_t nb = bound, new_lane = 0, new_tpu = 0, new_v4u = 0;
    if (!lane) { lane = new_lane = nb++; if (!tpu) tpu = new_tpu = nb++; }   // the ballot, the masks and the votes read no lane ID as translated
    if (votes && !tv4u) tv4u = new_v4u = nb++;
    uint32_t c31 = nb++, cn31 = nb++, c5 = nb++, c32 = nb++, c0 = nb++, ct = votes ? nb++ : 0;
    size_t k = 0; int capped = 0, decorated = 0, placed = 0, full = 0; fn = 0;
    for (size_t i = 0; i < 5; i++) o[k++] = w[i];
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        const uint32_t *x = w + i;
        size_t at = i; i += len;
        if (op != 17 && !capped) { capped = 1; if (votes && !ballotcap) SPV_WIDE_PUT(17, 64); }   // OpCapability GroupNonUniformBallot, last of the capabilities
        if (!decorated && new_lane && ((op >= 19 && op <= 52) || op == 59)) {   // OpDecorate BuiltIn SubgroupLocalInvocationId (Flat in a fragment shader), last of the annotations
            decorated = 1; SPV_WIDE_PUT(71, lane, 11, 41); if (model == 4) SPV_WIDE_PUT(71, lane, 14);
        }
        if (op == 15 && at == ep && new_lane) {   // the entry point with the lane ID in its interface
            if (k + len + 1 > cap) { full = 1; continue; }
            size_t s = k; for (uint32_t q = 0; q < len; q++) o[k++] = x[q];
            o[k++] = lane; o[s] = (uint32_t)(k - s) << 16 | op;
            continue;
        }
        if (op == 54 && !placed) {   // before the first function: the types, constants and variable it lacks
            placed = 1; fn = 1;
            if (new_v4u) SPV_WIDE_PUT(23, tv4u, tu, 4);
            if (new_tpu) SPV_WIDE_PUT(32, tpu, 1, tu);
            SPV_WIDE_PUT(43, tu, c31, 31); SPV_WIDE_PUT(43, tu, cn31, 0xffffffe0u); SPV_WIDE_PUT(43, tu, c5, 5); SPV_WIDE_PUT(43, tu, c32, 32); SPV_WIDE_PUT(43, tu, c0, 0);
            if (ct) SPV_WIDE_PUT(41, tb, ct);
            if (new_lane) SPV_WIDE_PUT(59, tpu, lane, 1);
        }
        if (!fn) { SPV_WIDE_COPY(); continue; }
        uint32_t l = nb, wv = nb + 1;   // the subgroup's lane ID, loaded where each use is, and its warp (lane >> 5)
        if (op == 345) {   // Shuffle: to the lane of its own warp
            uint32_t hi = nb + 1, id = nb + 2; nb += 3;
            SPV_WIDE_PUT(61, tu, l, lane); SPV_WIDE_PUT(199, tu, hi, l, cn31); SPV_WIDE_PUT(197, tu, id, x[5], hi);   // OpLoad, OpBitwiseAnd, OpBitwiseOr
            SPV_WIDE_PUT(345, x[1], x[2], x[3], x[4], id);
            continue;
        }
        if (op >= 334 && op <= 336) {   // All, Any, AllEqual: from the warp's ballot
            uint32_t b = nb + 2, m = nb + 3, bt = nb + 4, mt = nb + 5, e1 = nb + 6, e0 = nb + 7; nb += 8;
            SPV_WIDE_PUT(339, tv4u, b, x[3], x[4]); SPV_WIDE_PUT(61, tu, l, lane); SPV_WIDE_PUT(194, tu, wv, l, c5); SPV_WIDE_PUT(77, tu, m, b, wv);   // OpShiftRightLogical, OpVectorExtractDynamic
            if (op == 335) { SPV_WIDE_PUT(171, tb, x[2], m, c0); continue; }   // Any: OpINotEqual 0
            SPV_WIDE_PUT(339, tv4u, bt, x[3], ct); SPV_WIDE_PUT(77, tu, mt, bt, wv);   // the warp's active lanes
            if (op == 334) { SPV_WIDE_PUT(170, tb, x[2], m, mt); continue; }   // All: OpIEqual
            SPV_WIDE_PUT(170, tb, e1, m, mt); SPV_WIDE_PUT(170, tb, e0, m, c0); SPV_WIDE_PUT(166, tb, x[2], e1, e0);   // AllEqual: all or none, OpLogicalOr
            continue;
        }
        if (op == 61 && ID(x[3]) && (kind[x[3]] == SWK_LANE || kind[x[3]] == SWK_SIZE)) {
            nb += 1;
            if (kind[x[3]] == SWK_SIZE) SPV_WIDE_PUT(83, x[1], x[2], c32);   // OpCopyObject 32
            else { SPV_WIDE_PUT(61, tu, l, lane); SPV_WIDE_PUT(199, x[1], x[2], l, c31); }   // the lane within its warp
            continue;
        }
        if ((op == 65 || op == 66) && ID(x[2]) && kind[x[2]] == SWK_MPTR) {   // a mask's component: its warp's
            nb += 2; SPV_WIDE_PUT(61, tu, l, lane); SPV_WIDE_PUT(194, tu, wv, l, c5); SPV_WIDE_PUT(op, x[1], x[2], x[3], wv);
            continue;
        }
        if (op == 81 && ID(x[3]) && (kind[x[3]] & 0xff) == SWK_BALLOT) {   // a ballot's first component: its warp's
            nb += 2; SPV_WIDE_PUT(61, tu, l, lane); SPV_WIDE_PUT(194, tu, wv, l, c5); SPV_WIDE_PUT(77, x[1], x[2], x[3], wv);
            continue;
        }
        SPV_WIDE_COPY();
    }
#undef ID
    if (full) { *what = SPV_WIDE_KEPT; return 0; }   // past *need, which counts each use at its most: as translated rather than past the buffer
    o[3] = nb;
    return k;
}
#undef SPV_WIDE_PUT
#undef SPV_WIDE_COPY
