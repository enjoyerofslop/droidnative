// Descriptor arrays longer than the replay writes. Ryujinx's texture array from a buffer is as long as a 64 KB uniform buffer's 8-byte handles (Program.cs
// QueryTextureArrayLengthFromBuffer: 8,192 elements), its index clamped to the last by UMin; the Mac reads such an array through a pointer with a run-time bound
// (dmsh_build.py pool_arrays). The Vulkan replay writes at most the first TEX_ARR_MAX (1,024) elements of a stage's array (gfx_vk_draw.inc stage_set), but a set
// layout must hold as many descriptors as the module's array is long, so every set of such a shader reserved 8,192 combined image samplers: two sets filled a
// descriptor pool (16,384 of them, 12.4 MB on the Adreno 830). Paper Mario: The Thousand-Year Door's 75 reflection shaders (a light's texture per handle in c14)
// took the Galaxy S25 Edge's pools to 6.7 GB in the prologue's sea scene, where the low-memory killer ended the game.
// spv_harr shortens each such array, outside the descriptor set skip (the pool set, spv_pool.h's), to len elements, and clamps every index into it to len - 1 again
// (GLSL.std.450 UMin), as the translator clamped it to its own last element. An index past what is written read an unwritten descriptor before (undefined); it reads
// the last written element now. A module with another use of such an array (loaded whole, passed to a function, a pointer access chain) is left as it is
// (SPV_HARR_FAIL), and its layout keeps the full count.
// Self-contained (no libc), like spv_pool.h, so that dm/tools/tests/test_spv_harr.py builds it alone and runs it over a game's shaders on the PC.
#pragma once
#include <stddef.h>
#include <stdint.h>

enum { SPV_HARR_SHRUNK = 1, SPV_HARR_FAIL = 2 };
#define SPV_HARR_SCRATCH 7   // scratch words per id of the module's bound (w[3])

static size_t spv_harr_put(uint32_t *o, size_t k, uint32_t op, const uint32_t *a, uint32_t na) { o[k++] = (na + 1) << 16 | op; for (uint32_t q = 0; q < na; q++) o[k++] = a[q]; return k; }
#define SPV_HARR_PUT(op, ...) do { const uint32_t a_[] = {__VA_ARGS__}; k = spv_harr_put(o, k, (op), a_, (uint32_t)(sizeof a_ / sizeof *a_)); } while (0)
static int spv_harr_glsl(const uint32_t *w, uint32_t nw) {   // a string operand of nw words is "GLSL.std.450"
    static const char s[] = "GLSL.std.450";
    for (uint32_t c = 0; c < sizeof s; c++) { if (c / 4 >= nw) return 0; if ((uint8_t)(w[c / 4] >> (8 * (c % 4))) != (uint8_t)s[c]) return 0; }
    return 1;
}
// Operand q of an instruction in a function body that is a literal, not an id: those a use of an array variable is not looked for in
static int spv_harr_literal(uint32_t op, uint32_t q, uint32_t len) {
    switch (op) {
        case 12: return q == 4;                     // OpExtInst: the instruction number
        case 61: return q >= 4;                     // OpLoad: memory operands
        case 62: return q >= 3;                     // OpStore: memory operands
        case 79: case 82: return q >= 5;            // OpVectorShuffle components, OpCompositeInsert indices
        case 81: return q >= 4;                     // OpCompositeExtract indices
        case 246: return q >= 3;                    // OpLoopMerge: the control mask and its operands
        case 247: return q == 2;                    // OpSelectionMerge: the control mask
        case 251: return q >= 3 && q % 2 == 1;      // OpSwitch: the case literals
        case 8: return 1;                           // OpLine
        default: (void)len; return 0;
    }
}

// w[n]: the module. skip: a descriptor set whose arrays are left alone. len: the new length of every UniformConstant array of images, samplers or sampled images
// longer than it. scratch: SPV_HARR_SCRATCH × bound words. o[cap]: the result. → its word count, or 0: *info 0 (no such array), SPV_HARR_FAIL (left as it is),
// or with *need set above cap (o too small; *need is the size to give). *info: SPV_HARR_SHRUNK when rewritten
static size_t spv_harr(const uint32_t *w, size_t n, uint32_t skip, uint32_t len, uint32_t *scratch, uint32_t *o, size_t cap, size_t *need, int *info) {
    enum { F_ARR = 1, F_AC = 2, F_NU = 4 };
    *info = 0; *need = 0;
    if (n < 5 || w[0] != 0x07230203 || len < 1) return 0;
    uint32_t bound = w[3];
    uint32_t *def = scratch, *a1 = scratch + bound, *a2 = scratch + 2 * (size_t)bound, *fl = scratch + 3 * (size_t)bound, *x1 = scratch + 4 * (size_t)bound,
             *x2 = scratch + 5 * (size_t)bound, *set = scratch + 6 * (size_t)bound;
    for (size_t i = 0; i < SPV_HARR_SCRATCH * (size_t)bound; i++) scratch[i] = 0;
#define ID(x) ((x) && (x) < bound)
    // The globals: the GLSL.std.450 import, decorations, the 32-bit integer types, image types, arrays, pointers, constants and the arrays' variables
    uint32_t glsl = 0, tu = 0, ti = 0, fn0 = 0, narr = 0; int tu_late = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t l = w[i] >> 16, op = w[i] & 0xffff;
        if (!l || i + l > n) return 0;
        if (op == 54) { fn0 = (uint32_t)i; break; }
        switch (op) {
            case 11: if (l > 2 && ID(w[i + 1]) && spv_harr_glsl(w + i + 2, l - 2)) glsl = w[i + 1]; break;
            case 71: if (l > 2 && ID(w[i + 1])) { uint32_t t = w[i + 1], d = w[i + 2];
                         if (d == 34 && l > 3) set[t] = w[i + 3] + 1;   // DescriptorSet, + 1 so that 0 is none
                         if (d == 5300) fl[t] |= F_NU; } break;
            case 21: if (l > 3 && ID(w[i + 1])) { def[w[i + 1]] = op;
                         if (w[i + 2] == 32 && !w[i + 3] && !tu) { tu = w[i + 1]; tu_late = narr > 0; } if (w[i + 2] == 32 && w[i + 3] == 1 && !ti) ti = w[i + 1]; } break;
            case 25: case 26: case 27: if (l > 1 && ID(w[i + 1])) def[w[i + 1]] = op; break;
            case 28: case 32: if (l > 3 && ID(w[i + 1])) { def[w[i + 1]] = op; a1[w[i + 1]] = w[i + 2]; a2[w[i + 1]] = w[i + 3]; } break;   // OpTypeArray elem length; OpTypePointer class type
            case 43: if (l > 3 && ID(w[i + 2])) { def[w[i + 2]] = op; a1[w[i + 2]] = w[i + 1]; a2[w[i + 2]] = w[i + 3]; } break;   // OpConstant type id value (its low word)
            case 59: if (l > 3 && ID(w[i + 1]) && ID(w[i + 2]) && w[i + 3] == 0) {   // a UniformConstant variable
                uint32_t v = w[i + 2], pt = w[i + 1];
                if (def[pt] == 32 && ID(a2[pt]) && def[a2[pt]] == 28) {
                    uint32_t arr = a2[pt], el = a1[arr], ln = a2[arr];
                    if (ID(el) && (def[el] == 25 || def[el] == 26 || def[el] == 27) && ID(ln) && def[ln] == 43 && a1[ln] == tu && a2[ln] > len && !(set[v] && set[v] - 1 == skip)) {
                        fl[v] |= F_ARR; x1[v] = el; narr++; }
                }
            } break;
            default: break;
        }
        i += l;
    }
    if (!narr) return 0;
    *info = SPV_HARR_FAIL;
    if (!fn0 || !tu || tu_late) return 0;   // the new length is a constant of the 32-bit unsigned type, declared before the first such variable
    // The function bodies: each use of such a variable must be the base of an access chain with one index of a 32-bit integer type
    uint32_t nb = bound, nac = 0, nnu = 0; int need_iu = 0, need_ii = 0;
    for (size_t i = fn0; i < n; ) {
        uint32_t l = w[i] >> 16, op = w[i] & 0xffff;
        if (!l || i + l > n) return 0;
        switch (op) {   // result types, for the indices' types (spv_pool.h's list)
            case 1: case 12: case 61: case 65: case 66: case 67: case 81: case 83: case 86: case 100: case 109: case 110: case 113: case 114: case 124: case 128: case 130: case 132:
            case 134: case 135: case 137: case 169: case 194: case 195: case 196: case 197: case 198: case 199: case 245:
                if (l > 2 && ID(w[i + 2])) a1[w[i + 2]] = w[i + 1]; break;
            default: break;
        }
        int chain = (op == 65 || op == 66) && l > 3 && ID(w[i + 3]) && (fl[w[i + 3]] & F_ARR);
        for (uint32_t q = 1; q < l; q++)
            if (ID(w[i + q]) && (fl[w[i + q]] & F_ARR) && !(chain && q == 3) && !spv_harr_literal(op, q, l)) return 0;
        if (chain) {
            uint32_t r = w[i + 2];
            if (l != 5 || !ID(w[i + 4]) || !ID(r)) return 0;   // one index: the element
            uint32_t idx = w[i + 4], it = a1[idx];
            if (!(it == tu || (ti && it == ti))) return 0;
            fl[r] |= F_AC; x1[r] = idx; x2[r] = nb++; nac++;
            if (fl[idx] & F_NU) nnu++;
            need_iu |= it == tu; need_ii |= it == ti;
        }
        i += l;
    }
    uint32_t c_len = nb++, nm1u = need_iu ? nb++ : 0, nm1i = need_ii ? nb++ : 0, new_glsl = glsl ? 0 : nb++;
    if (!glsl) glsl = new_glsl;
    size_t room = n + 8 * (size_t)nac + 3 * (size_t)nnu + 8 * (size_t)narr + 32;   // a UMin of 7 words before each chain, a decoration of 3 per NonUniform index
    if (cap < room) { *need = room; *info = 0; return 0; }
    // The module again, rewritten
    size_t k = 0; for (int q = 0; q < 5; q++) o[k++] = w[q];
    int glsl_done = !new_glsl, decos_done = 0, tail_done = 0, len_done = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t l = w[i] >> 16, op = w[i] & 0xffff;
        if (!glsl_done && op != 17 && op != 10 && op != 11) {   // before OpMemoryModel
            o[k++] = 6u << 16 | 11; o[k++] = glsl; o[k++] = 0x4c534c47; o[k++] = 0x6474732e; o[k++] = 0x3035342e; o[k++] = 0; glsl_done = 1; }   // "GLSL.std.450"
        if (!decos_done && ((op >= 19 && op <= 39) || op == 41 || op == 42 || op == 43 || op == 44 || op == 45 || op == 46 || op == 59 || op == 1 || op == 54 || op == 322 || op == 4472)) {
            for (uint32_t v = 1; v < bound; v++) if ((fl[v] & F_AC) && (fl[x1[v]] & F_NU)) SPV_HARR_PUT(71, x2[v], 5300);   // a NonUniform index's clamp: NonUniform too
            decos_done = 1;
        }
        if (!tail_done && op == 54) {   // the end of the globals: the clamps' constants
            if (nm1u) SPV_HARR_PUT(43, tu, nm1u, len - 1);
            if (nm1i) SPV_HARR_PUT(43, ti, nm1i, len - 1);
            tail_done = 1;
        }
        if (op == 59 && i < fn0 && l == 4 && (fl[w[i + 2]] & F_ARR)) {   // such a variable: an array len long of the same element
            uint32_t el = x1[w[i + 2]];
            if (!len_done) { SPV_HARR_PUT(43, tu, c_len, len); len_done = 1; }
            if (!a2[el]) { uint32_t na = nb++, np = nb++; a2[el] = np; SPV_HARR_PUT(28, na, el, c_len); SPV_HARR_PUT(32, np, 0, na); }   // (a2 of an image type is free)
            SPV_HARR_PUT(59, a2[el], w[i + 2], 0); i += l; continue;
        }
        if ((op == 65 || op == 66) && l == 5 && ID(w[i + 2]) && (fl[w[i + 2]] & F_AC)) {
            uint32_t r = w[i + 2], idx = x1[r], c = x2[r], it = a1[idx];
            SPV_HARR_PUT(12, it, c, glsl, 38, idx, it == tu ? nm1u : nm1i);   // UMin
            SPV_HARR_PUT(op, w[i + 1], r, w[i + 3], c); i += l; continue;
        }
        for (uint32_t q = 0; q < l; q++) o[k++] = w[i + q];
        i += l;
    }
    if (!tail_done || !decos_done || !len_done) return 0;
    o[3] = nb;
    *info = SPV_HARR_SHRUNK;
#undef ID
    return k;
}
#undef SPV_HARR_PUT
