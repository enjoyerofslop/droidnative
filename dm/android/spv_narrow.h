// Maxwell's warp instructions on a GPU whose subgroups are narrower than its 32-lane warp: 16 lanes on the Pixel 9 Pro XL's Mali-G715 (fragment and compute,
// subgroupSize 16, which VK_EXT_subgroup_size_control cannot raise). The translator (Ryujinx's) writes SHFL as helpers that take the lane ID's low five bits and
// shuffle to the lane they compute, valid up to the clamp (spv_wide.h); on 16 lanes a source lane 16 or more lanes away does not exist, and the shuffle's value is
// undefined. Each subgroup then runs as a warp of its own, as wide as the GPU's (every lane ID, ballot and mask the game reads is already the subgroup's):
// - Every shuffle reads the lane's own value where its source lane is past the subgroup, as Maxwell's SHFL does for a lane outside its segment:
//   index < size ? index : lane.
// - A whole-warp reduction step whose partner is outside the subgroup for every lane: a call of the SHFL.BFLY or SHFL.DOWN helper with a constant offset of the
//   subgroup size or more and a constant mask of 31 (clamp 31, no segments), whose result the next instructions combine with the value it shuffled, op(x, r).
//   On a narrower warp that step has no partner, so the combine is the value itself, x, whatever the op: a reduction then gives each subgroup's own result, and
//   the game's per-warp leader (a lane ID of 0, or a ballot's lowest or highest lane, both the subgroup's) combines the subgroups through its atomics or shared
//   memory as it combines its warps. Final Fantasy Resonance reduces with UMax, UMin, Or and IAdd this way (309 compute shaders), its leaders atomics into
//   workgroup memory; left as translated, its IAdd sums counted each subgroup twice or took an undefined value.
// A step whose result is used otherwise is left as translated, with its index guarded (SPV_NARROW_KEPT). Changes nothing on 32 lanes or more (not called).
// Self-contained (no libc), so that dm/tools/tests/test_spv_narrow.py builds it alone.
#pragma once
#include <stddef.h>
#include <stdint.h>

enum { SPV_NARROW_GUARD = 1, SPV_NARROW_STEP = 2, SPV_NARROW_KEPT = 4 };   // shuffles guarded; reduction steps made the value itself; steps past the subgroup left
enum { SNK_SHUF = 1, SNK_XOR = 2, SNK_ADD = 4 };   // what a function holds: a shuffle, an xor (SHFL.BFLY's source lane), an add (SHFL.DOWN's)
static uint32_t spv_narrow_stage(uint32_t model) { return model <= 5 ? 1u << model : model == 5267 || model == 5364 ? 0x40 : model == 5268 || model == 5365 ? 0x80 : 0; }
// the binary ops a reduction step combines with: OpIAdd, OpFAdd, OpISub, OpFSub, OpIMul, OpFMul, OpBitwiseOr, OpBitwiseXor, OpBitwiseAnd
static int spv_narrow_binop(uint32_t op) { return op == 128 || op == 129 || op == 130 || op == 131 || op == 132 || op == 133 || op == 197 || op == 198 || op == 199; }
// GLSL.std.450 FMin, UMin, SMin, FMax, UMax, SMax, NMin, NMax
static int spv_narrow_extop(uint32_t e) { return (e >= 37 && e <= 42) || e == 79 || e == 80; }

// Whether the module has a shuffle at all: one pass over the instruction heads, so that the modules that have none cost next to nothing
static int spv_narrow_wanted(const uint32_t *w, size_t n) {
    if (n < 5 || w[0] != 0x07230203) return 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16; if (!len || i + len > n) return 0; if ((w[i] & 0xffff) == 345) return 1; i += len; }
    return 0;
}
// w[n]: the module. sg_stages: subgroupSupportedStages. size: the subgroup size, a power of two from 4 to 16. scratch: 9 × bound words (w[3]) and 2 words a site
// after them, sites of them at most. o[cap]: the result. → its word count, or 0 when it is left as it is: its stage runs no subgroup operations, it has no shuffle,
// or o is NULL or smaller than *need (call again with that much). *what: SPV_NARROW_* of what it did and left
static size_t spv_narrow(const uint32_t *w, size_t n, uint32_t sg_stages, uint32_t size, uint32_t *scratch, size_t sites_max, uint32_t *o, size_t cap, size_t *need, int *what) {
    *what = 0; *need = 0;
    if (n < 5 || w[0] != 0x07230203 || size < 4 || size >= 32 || (size & (size - 1))) return 0;
    uint32_t bound = w[3];
    uint32_t *fkind = scratch, *cval = scratch + bound, *isc = scratch + 2 * (size_t)bound, *srcv = scratch + 3 * (size_t)bound, *rtype = scratch + 4 * (size_t)bound,
             *last = scratch + 5 * (size_t)bound, *lastb = scratch + 6 * (size_t)bound, *lpos = scratch + 7 * (size_t)bound, *spos = scratch + 8 * (size_t)bound,
             *site = scratch + 9 * (size_t)bound;   // lpos: where an id was loaded; spos: where a variable was last stored; site: word offset of a combine, the operand it becomes
    for (size_t i = 0; i < 9 * (size_t)bound; i++) scratch[i] = 0;
    uint32_t model = 99, tu = 0, tb = 0, lane = 0, lanept = 0, tpu = 0, glsl = 0, cur = 0; int neps = 0, shufs = 0, kept = 0, laneok = 1; size_t nsite = 0;
#define ID(x) ((x) < bound)
    // pass 1: types, constants, the lane ID, and which functions hold a shuffle and of what kind
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        const uint32_t *x = w + i;
        if (op == 15 && len >= 3) { neps++; model = x[1]; }
        else if (op == 11 && len >= 3) { const char *s = (const char *)(x + 2); if (s[0] == 'G' && s[1] == 'L' && s[2] == 'S' && s[3] == 'L' && s[4] == '.') glsl = x[1]; }   // OpExtInstImport "GLSL.std.450"
        else if (op == 71 && len >= 4 && x[2] == 11 && x[3] == 41) lane = x[1];   // OpDecorate BuiltIn SubgroupLocalInvocationId
        else if (op == 20 && len == 2) tb = x[1];
        else if (op == 21 && len == 4 && x[2] == 32 && !x[3]) tu = x[1];
        else if (op == 32 && len == 4 && tu && x[2] == 1 && x[3] == tu) tpu = x[1];   // OpTypePointer Input uint
        else if (op == 59 && len >= 4 && lane && x[2] == lane) lanept = x[1];   // the lane ID's variable: its pointer type
        else if (op == 43 && len == 4 && ID(x[2])) { cval[x[2]] = x[3]; isc[x[2]] = 1; }   // OpConstant, one word
        else if (op == 54 && len >= 3) cur = x[2];   // OpFunction: result type, result
        else if (op == 56) cur = 0;   // OpFunctionEnd
        else if (cur && ID(cur)) {
            if (op == 345) { shufs++; fkind[cur] |= SNK_SHUF; }   // OpGroupNonUniformShuffle
            else if (op == 198) fkind[cur] |= SNK_XOR;
            else if (op == 128) fkind[cur] |= SNK_ADD;
        }
        i += len;
    }
    if (neps != 1 || !(sg_stages & spv_narrow_stage(model)) || !shufs || !tu || !tb) return 0;
    if (!lane || (lanept && lanept != tpu)) laneok = 0;   // no lane ID to fall back on (or not a uint): shuffles keep their index
    // pass 2: reduction steps past the subgroup, in the translator's pattern
    //   OpStore %A %v; OpStore %B %b; OpStore %C %c; %r = OpFunctionCall %int %helper %A %B %C %P; OpStore %R %r; ... OpLoad %X, OpLoad %R (bitcast) ...; %z = op(x, r)
    // with %v loaded from %X (bitcast too); each id's variable through loads and bitcasts in srcv, the last value stored to each variable in this block in last
    cur = 0; uint32_t blk = 0;
#define SPV_NARROW_HELPER(f) ((fkind[f] & SNK_SHUF) && (fkind[f] & (SNK_XOR | SNK_ADD)) != (SNK_XOR | SNK_ADD) && (fkind[f] & (SNK_XOR | SNK_ADD)))   // a SHFL.BFLY or SHFL.DOWN helper
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *x = w + i;
        if (op == 54) cur = 1;
        if (!cur) { i += len; continue; }
        if (op == 248) blk++;   // OpLabel: a new block, where no store is known yet
        else if (op == 61 && len >= 4 && ID(x[2]) && ID(x[3])) { srcv[x[2]] = x[3]; rtype[x[2]] = x[1]; lpos[x[2]] = (uint32_t)i; }   // OpLoad: the variable it reads
        else if (op == 124 && len == 4 && ID(x[2]) && ID(x[3])) { srcv[x[2]] = srcv[x[3]]; rtype[x[2]] = x[1]; lpos[x[2]] = lpos[x[3]]; }   // OpBitcast: its operand's
        else if (op == 62 && len >= 3 && ID(x[1])) { last[x[1]] = x[2]; lastb[x[1]] = blk; spos[x[1]] = (uint32_t)i; }   // OpStore
        else if (op == 57 && len >= 8 && ID(x[3]) && SPV_NARROW_HELPER(x[3]) && ID(x[5]) && ID(x[6]) && ID(x[4])) {
            uint32_t bv = lastb[x[5]] == blk ? last[x[5]] : 0, cv = lastb[x[6]] == blk ? last[x[6]] : 0, vv = lastb[x[4]] == blk ? last[x[4]] : 0;
            if (ID(bv) && isc[bv] && cval[bv] >= size && cval[bv] < 32 && ID(cv) && isc[cv] && cval[cv] == 31) {   // every lane's partner past the subgroup
                uint32_t X = ID(vv) ? srcv[vv] : 0, R = 0, xid = 0, rid = 0; size_t j = i + len, done = 0;
                if (X && ID(X) && lastb[X] == blk && spos[X] > lpos[vv]) X = 0;   // written after the value the shuffle took was loaded: a load of it after the call is another value
                if (j < n && (w[j] & 0xffff) == 62 && (w[j] >> 16) >= 3 && w[j + 2] == x[2]) { R = w[j + 1]; j += w[j] >> 16; }   // OpStore %R %r
                for (int q = 0; R && X && q < 160 && j < n && !done; q++) {   // the combine can follow another reduction's call and combine (two run side by side), or an if
                    uint32_t l2 = w[j] >> 16, o2 = w[j] & 0xffff; const uint32_t *y = w + j;
                    if (!l2) break;
                    if (o2 == 61 && l2 >= 4 && ID(y[2])) { if (y[3] == R) rid = y[2]; else if (y[3] == X) xid = y[2]; srcv[y[2]] = y[3]; rtype[y[2]] = y[1]; }
                    else if (o2 == 124 && l2 == 4 && ID(y[2]) && ID(y[3])) { if (y[3] == rid) rid = y[2]; else if (y[3] == xid) xid = y[2]; srcv[y[2]] = srcv[y[3]]; rtype[y[2]] = y[1]; }
                    else if ((spv_narrow_binop(o2) && l2 == 5) || (o2 == 12 && l2 == 7 && y[3] == glsl && glsl && spv_narrow_extop(y[4]))) {
                        uint32_t a = o2 == 12 ? y[5] : y[3], b = o2 == 12 ? y[6] : y[4], keep = 0;
                        if (xid && rid && a == xid && b == rid) keep = a; else if (xid && rid && a == rid && b == xid) keep = b;
                        if (keep && ID(keep) && nsite < sites_max) { site[2 * nsite] = (uint32_t)j; site[2 * nsite + 1] = keep; nsite++; done = 1; }
                    }
                    else if (o2 == 62 && l2 >= 3 && (y[1] == X || y[1] == R)) break;   // either written again first
                    else if (o2 == 57) { int touches = 0; for (uint32_t q2 = 4; q2 < l2; q2++) touches |= y[q2] == X || y[q2] == R; if (touches) break; }   // a call given either
                    else if (o2 == 246 || (o2 >= 252 && o2 <= 255)) break;   // a loop (whose back edge may write them after the combine), a return or kill. An if's blocks come
                                                                                 // before its merge, so a store to either in them is seen above
                    j += l2;
                }
                if (!done) kept++;
            }
        }
        i += len;
    }
    for (size_t a = 1; a < nsite; a++) for (size_t b = a; b && site[2 * b - 2] > site[2 * b]; b--) {   // in module order, for the output pass
        uint32_t t0 = site[2 * b - 2], t1 = site[2 * b - 1]; site[2 * b - 2] = site[2 * b]; site[2 * b - 1] = site[2 * b + 1]; site[2 * b] = t0; site[2 * b + 1] = t1; }
    *what = (laneok ? SPV_NARROW_GUARD : 0) | (nsite ? SPV_NARROW_STEP : 0) | (kept ? SPV_NARROW_KEPT : 0);
    if (!laneok && !nsite) return 0;
    *need = n + 16 * (size_t)shufs + 16;
    if (!o || cap < *need) return 0;
    uint32_t nb = bound, csz = laneok ? nb++ : 0;
    size_t k = 0, s = 0; int placed = 0, full = 0;
    for (size_t i = 0; i < 5; i++) o[k++] = w[i];
#define SPV_NARROW_PUT(...) do { const uint32_t a_[] = {__VA_ARGS__}; size_t na_ = sizeof a_ / sizeof *a_; if (k + na_ > cap) full = 1; else for (size_t q_ = 0; q_ < na_; q_++) o[k++] = a_[q_]; } while (0)
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *x = w + i; size_t at = i; i += len;
        if (op == 54 && !placed) { placed = 1; if (csz) SPV_NARROW_PUT(4u << 16 | 43, tu, csz, size); }   // before the first function: the subgroup size as a constant
        if (s < nsite && at == site[2 * s]) {   // a reduction step's combine: the value itself
            uint32_t keep = site[2 * s + 1]; s++;
            SPV_NARROW_PUT(4u << 16 | (rtype[keep] == x[1] ? 83u : 124u), x[1], x[2], keep);   // OpCopyObject, or OpBitcast to the combine's type
            continue;
        }
        if (op == 345 && len == 6 && csz) {   // a shuffle: its own lane where the source is past the subgroup
            uint32_t l = nb++, in = nb++, id = nb++;
            SPV_NARROW_PUT(4u << 16 | 61, tu, l, lane); SPV_NARROW_PUT(5u << 16 | 176, tb, in, x[5], csz); SPV_NARROW_PUT(6u << 16 | 169, tu, id, in, x[5], l);   // OpLoad, OpULessThan, OpSelect
            SPV_NARROW_PUT(6u << 16 | 345, x[1], x[2], x[3], x[4], id);
            continue;
        }
        if (k + len > cap) { full = 1; continue; }
        for (uint32_t q = 0; q < len; q++) o[k++] = x[q];
    }
#undef SPV_NARROW_PUT
#undef SPV_NARROW_HELPER
#undef ID
    if (full || s != nsite) { *what |= SPV_NARROW_KEPT; return 0; }
    o[3] = nb;
    return k;
}
