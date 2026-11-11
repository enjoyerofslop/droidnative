// A storage image of format E5B9G9R9 on a GPU that stores to no such image (the Adreno 830 and 840; Vulkan makes no shared-exponent format a storage format). The
// replay gives the image STORAGE for views in R32_UINT alone (EXTENDED_USAGE, vt_storage_up), binds it through such a view, and rewrites the shader's image to
// match: the variable bound there becomes an R32ui image, each OpImageWrite packs its texel into RGB9E5 as Vulkan specifies the conversion (Shared Exponent
// Formats: each channel clamped to [0, 65408], NaN to 0; the shared exponent from the largest channel, raised by one where that channel would round to 512; each
// mantissa rounded to nearest), and each OpImageRead unpacks the word into the floats it holds, alpha 1. So the texture keeps its format, and what the game's later
// reads, copies and the CPU see are the bits a GPU with that format would have written. A raw store (Maxwell's SUST.B, which the translator writes as
// vec4(the word's bits, 0, 0, 0)) carries a word the game packed itself: its bits are stored as they are. A module whose image has another use (a query of its format or order,
// a texel pointer for an atomic, a function argument) is left as it is.
// mask: the Binding numbers (under 64) of the storage images to rewrite. Self-contained (no libc, spv_lit.h only), so that dm/tools/tests/test_spv_e5.py builds it alone.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "spv_lit.h"

enum { SPV_E5_DONE = 1, SPV_E5_KEPT = 2 };   // rewritten; a use it cannot follow: as it is
#define SPV_E5_SITE 320u   // the most words one write (the pack, about 240) or read (the unpack, about 110) becomes
#define SPV_E5_DECL 256u   // the declarations at most: types, constants, the image types, pointers and variables made again
enum { SE5_VAR = 1, SE5_IMG, SE5_LOADED };   // the kinds of ids the scan follows

static size_t spv_e5_put(uint32_t *o, size_t k, size_t cap, int *full, uint32_t op, const uint32_t *a, uint32_t na) {
    if (*full || k + 1 + na > cap) { *full = 1; return k; }
    o[k++] = (na + 1) << 16 | op; for (uint32_t i = 0; i < na; i++) o[k++] = a[i]; return k;
}
#define SE5_PUT(op, ...) do { const uint32_t a_[] = {__VA_ARGS__}; k = spv_e5_put(o, k, cap, &full, (op), a_, (uint32_t)(sizeof a_ / sizeof *a_)); } while (0)

// w[n]: the module. scratch: 5 × bound words (w[3]). o[cap]: the result. → its word count, or 0 when it is left as it is (no image of the mask: *need 0;
// *what SPV_E5_KEPT), or o is NULL or smaller than *need (call again with that much)
static size_t spv_e5(const uint32_t *w, size_t n, uint64_t mask, uint32_t *scratch, uint32_t *o, size_t cap, size_t *need, int *what) {
    *what = 0; *need = 0;
    if (n < 5 || w[0] != 0x07230203 || !mask) return 0;
    uint32_t bound = w[3], *kind = scratch, *bnd = scratch + bound, *val = scratch + 2 * bound;   // val: an image type's pointee float; a pointer's pointee; a loaded image's variable
    uint32_t *fbc = scratch + 3 * bound, *raw = scratch + 4 * bound;   // fbc: a float made by OpBitcast (1), or a float constant (2); raw: a vec4 of such a float and three constants, + 1
    for (uint32_t i = 0; i < 5 * bound; i++) scratch[i] = 0;
    uint32_t tf = 0, tu = 0, ti = 0, tb = 0, tv4f = 0, tv4u = 0, glsl = 0, imgt[8] = {0}, nimgt = 0, vars[8], ptrt[8], nvar = 0;
    uint32_t r32[8][5], nr32 = 0, ucp[64][2], nucp = 0;   // the module's own R32ui storage image types (id, dim, depth, arrayed, ms) and UniformConstant pointers (id, pointee): used, not declared twice
    int bad = 0, sites = 0, fn = 0;
#define ID(x) ((x) < bound)
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *x = w + i;
        if (!len || i + len > n) return 0;
        if (op == 54) fn = 1;
        if (op == 71 && len == 4 && x[2] == 33 && ID(x[1])) bnd[x[1]] = x[3] + 1;   // OpDecorate Binding
        else if (op == 11 && len >= 3 && x[2] == 0x4c534c47 && x[3] == 0x6474732e && x[4] == 0x3035342e) glsl = x[1];   // OpExtInstImport "GLSL.std.450"
        else if (op == 22 && len == 3 && x[2] == 32) tf = x[1];   // OpTypeFloat 32
        else if (op == 21 && len == 4 && x[2] == 32) { if (x[3]) ti = x[1]; else tu = x[1]; }   // OpTypeInt 32
        else if (op == 20 && len == 2) tb = x[1];
        else if ((op == 43 || op == 46) && len >= 3 && tf && x[1] == tf && ID(x[2])) fbc[x[2]] = 2;   // a float constant (OpConstant, OpConstantNull)
        else if (fn && op == 124 && len == 4 && tf && x[1] == tf && ID(x[2])) fbc[x[2]] = 1;   // a float made of a word's bits
        else if (fn && op == 80 && len == 7 && tv4f && x[1] == tv4f && ID(x[2]) && ID(x[3]) && fbc[x[3]] == 1 && ID(x[4]) && ID(x[5]) && ID(x[6]) && fbc[x[4]] == 2 && fbc[x[5]] == 2 && fbc[x[6]] == 2)
            raw[x[2]] = x[3] + 1;   // vec4(the word's bits, 0, 0, 0): Maxwell's raw store (SUST.B) as the translator writes it, the game's own packed word
        else if (op == 23 && len == 4 && x[3] == 4) { if (tf && x[2] == tf) tv4f = x[1]; if (tu && x[2] == tu) tv4u = x[1]; }   // OpTypeVector 4
        else if (op == 25 && len == 9 && ID(x[1]) && tf && x[2] == tf && x[7] == 2) kind[x[1]] = SE5_IMG;   // OpTypeImage float ... sampled 2 (storage)
        else if (op == 25 && len == 9 && tu && x[2] == tu && x[7] == 2 && x[8] == 33 && nr32 < 8) { r32[nr32][0] = x[1]; r32[nr32][1] = x[3]; r32[nr32][2] = x[4]; r32[nr32][3] = x[5]; r32[nr32++][4] = x[6]; }   // one already R32ui
        else if (op == 32 && len == 4 && x[2] == 0 && ID(x[1]) && ID(x[3])) { val[x[1]] = x[3]; if (nucp < 64) { ucp[nucp][0] = x[1]; ucp[nucp++][1] = x[3]; } }   // OpTypePointer UniformConstant
        else if (op == 59 && !fn && len >= 4 && x[3] == 0 && ID(x[2]) && ID(x[1])) {   // OpVariable UniformConstant
            uint32_t b = bnd[x[2]], p = val[x[1]];
            if (b && b - 1 < 64 && (mask >> (b - 1) & 1) && ID(p) && kind[p] == SE5_IMG) {
                if (nvar == 8) { bad = 1; } else { kind[x[2]] = SE5_VAR; val[x[2]] = nvar; vars[nvar] = x[2]; ptrt[nvar++] = p; }
                int seen = 0; for (uint32_t q = 0; q < nimgt; q++) seen |= imgt[q] == p; if (!seen && nimgt < 8) imgt[nimgt++] = p;
            }
        }
        else if (fn && op == 61 && len >= 4 && ID(x[3]) && kind[x[3]] == SE5_VAR && ID(x[2])) { kind[x[2]] = SE5_LOADED; }   // OpLoad of one: the image it loads
        else if (fn && op == 99 && len >= 4 && ID(x[1]) && kind[x[1]] == SE5_LOADED) { sites++; if (!tv4f) bad = 1; }   // OpImageWrite image coordinate texel
        else if (fn && op == 98 && len >= 5 && ID(x[3]) && kind[x[3]] == SE5_LOADED) { sites++; if (!tv4f || x[1] != tv4f) bad = 1; }   // OpImageRead type result image coordinate
        else if (fn && op == 104 && len >= 4 && ID(x[3]) && kind[x[3]] == SE5_LOADED) {}   // OpImageQuerySize: an R32ui image of the same size
        else if (fn) for (uint32_t q = 1; q < len; q++) if (!spv_lit(op, q) && ID(x[q]) && (kind[x[q]] == SE5_LOADED || kind[x[q]] == SE5_VAR)) bad = 1;   // any other use (not a literal that happens to equal it)
        i += len;
    }
    if (!nvar) return 0;
    if (bad || !tu || !tf) { *what = SPV_E5_KEPT; return 0; }
    *what = SPV_E5_DONE;
    *need = n + SPV_E5_SITE * (size_t)sites + SPV_E5_DECL;
    if (!o || cap < *need) return 0;
    uint32_t nb = bound;
    uint32_t new_ti = ti ? 0 : nb++, new_tb = tb ? 0 : nb++, new_tv4u = tv4u ? 0 : nb++, new_glsl = glsl ? 0 : nb++;
    if (!ti) ti = new_ti; if (!tb) tb = new_tb; if (!tv4u) tv4u = new_tv4u; if (!glsl) glsl = new_glsl;
    uint32_t uimg[8], uptr[8];
    for (uint32_t q = 0; q < nimgt; q++) { uimg[q] = nb++; uptr[q] = nb++; }
    // constants: uint 0 9 18 23 27 511; int -16 16 24 1 127; float 0 0.5 512 65408 1
    uint32_t cu0 = nb++, cu9 = nb++, cu18 = nb++, cu23 = nb++, cu27 = nb++, cu511 = nb++, cim16 = nb++, ci16 = nb++, ci24 = nb++, ci1 = nb++, ci127 = nb++;
    uint32_t cf0 = nb++, cfh = nb++, cf512 = nb++, cfmax = nb++, cf1 = nb++;
    size_t k = 0; int full = 0, placed = 0; fn = 0;
    for (size_t i = 0; i < 5; i++) o[k++] = w[i];
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *x = w + i; size_t at = i; i += len;
        if (op == 59 && !fn && len >= 4 && ID(x[2]) && kind[x[2]] == SE5_VAR) continue;   // declared again below, with the R32ui image's pointer
        if (op == 14 && new_glsl) SE5_PUT(11, new_glsl, 0x4c534c47, 0x6474732e, 0x3035342e, 0);   // OpExtInstImport "GLSL.std.450" where the module had none, before OpMemoryModel
        if (op == 54 && !placed) {   // before the first function: what the rewrite uses
            placed = 1; fn = 1;
            if (new_ti) SE5_PUT(21, new_ti, 32, 1);
            if (new_tb) SE5_PUT(20, new_tb);
            if (new_tv4u) SE5_PUT(23, new_tv4u, tu, 4);
            for (uint32_t q = 0; q < nimgt; q++) {   // the image type again with a uint texel, sampled 2 and format R32ui (33); its dimension, depth, array and multisample as they were
                const uint32_t *t = NULL;
                for (size_t j = 5; j < n; ) { uint32_t l2 = w[j] >> 16; if ((w[j] & 0xffff) == 25 && w[j + 1] == imgt[q]) { t = w + j; break; } j += l2 ? l2 : 1; }
                if (!t) { *what = SPV_E5_KEPT; return 0; }
                int have = 0, haveptr = 0;
                for (uint32_t r = 0; r < nr32 && !have; r++) if (r32[r][1] == t[3] && r32[r][2] == t[4] && r32[r][3] == t[5] && r32[r][4] == t[6]) { uimg[q] = r32[r][0]; have = 1; }
                if (have) for (uint32_t r = 0; r < nucp && !haveptr; r++) if (ucp[r][1] == uimg[q]) { uptr[q] = ucp[r][0]; haveptr = 1; }
                if (!have) SE5_PUT(25, uimg[q], tu, t[3], t[4], t[5], t[6], 2, 33);
                if (!haveptr) SE5_PUT(32, uptr[q], 0, uimg[q]);
            }
            SE5_PUT(43, tu, cu0, 0); SE5_PUT(43, tu, cu9, 9); SE5_PUT(43, tu, cu18, 18); SE5_PUT(43, tu, cu23, 23); SE5_PUT(43, tu, cu27, 27); SE5_PUT(43, tu, cu511, 511);
            SE5_PUT(43, ti, cim16, 0xfffffff0u); SE5_PUT(43, ti, ci16, 16); SE5_PUT(43, ti, ci24, 24); SE5_PUT(43, ti, ci1, 1); SE5_PUT(43, ti, ci127, 127);
            SE5_PUT(43, tf, cf0, 0); SE5_PUT(43, tf, cfh, 0x3f000000u); SE5_PUT(43, tf, cf512, 0x44000000u); SE5_PUT(43, tf, cfmax, 0x477f8000u); SE5_PUT(43, tf, cf1, 0x3f800000u);
            for (uint32_t v = 0; v < nvar; v++) { uint32_t q = 0; while (q < nimgt && imgt[q] != ptrt[v]) q++; SE5_PUT(59, uptr[q], vars[v], 0); }
        }
        if (op == 61 && ID(x[3]) && kind[x[3]] == SE5_VAR) {   // the load: of the R32ui image
            uint32_t v = val[x[3]], q = 0; while (q < nimgt && imgt[q] != ptrt[v]) q++;
            uint32_t a[8]; uint32_t na = len - 1 < 8 ? len - 1 : 8; for (uint32_t j = 0; j < na; j++) a[j] = x[1 + j]; a[0] = uimg[q];
            k = spv_e5_put(o, k, cap, &full, op, a, na); continue;
        }
        if (op == 99 && ID(x[1]) && kind[x[1]] == SE5_LOADED && ID(x[3]) && raw[x[3]]) {   // a raw store: the game packed the word itself (RGB9E5's bits); stored as they are
            uint32_t u = nb++, tex = nb++; SE5_PUT(124, tu, u, raw[x[3]] - 1); SE5_PUT(80, tv4u, tex, u, cu0, cu0, cu0);
            uint32_t a[16]; uint32_t na = len - 1 < 16 ? len - 1 : 16; for (uint32_t j = 0; j < na; j++) a[j] = x[1 + j]; a[2] = tex;
            k = spv_e5_put(o, k, cap, &full, op, a, na); continue;
        }
        if (op == 99 && ID(x[1]) && kind[x[1]] == SE5_LOADED) {   // a formatted store: the texel packed into RGB9E5 (Vulkan's conversion)
            uint32_t t = x[3], c[3], cc[3], s[3];
            for (int j = 0; j < 3; j++) { c[j] = nb++; SE5_PUT(81, tf, c[j], t, (uint32_t)j); cc[j] = nb++; SE5_PUT(12, tf, cc[j], glsl, 81, c[j], cf0, cfmax); }   // NClamp: NaN 0
            uint32_t m1 = nb++, mx = nb++; SE5_PUT(12, tf, m1, glsl, 80, cc[0], cc[1]); SE5_PUT(12, tf, mx, glsl, 80, m1, cc[2]);   // NMax: the largest
            uint32_t bits = nb++, sh = nb++, ei = nb++, e = nb++, e2 = nb++, ep = nb++, nx = nb++, sc = nb++, sch = nb++, ms = nb++, big = nb++, ep1 = nb++, ex = nb++, nx2 = nb++;
            SE5_PUT(124, tu, bits, mx); SE5_PUT(194, tu, sh, bits, cu23); SE5_PUT(124, ti, ei, sh); SE5_PUT(130, ti, e, ei, ci127);   // floor(log2(max)) from its exponent bits
            SE5_PUT(12, ti, e2, glsl, 42, e, cim16); SE5_PUT(128, ti, ep, e2, ci16);   // exp' = max(-16, floor(log2(max))) + 16 (a denormal or 0 is under -16)
            SE5_PUT(130, ti, nx, ci24, ep); SE5_PUT(12, tf, sc, glsl, 53, mx, nx); SE5_PUT(129, tf, sch, sc, cfh); SE5_PUT(12, tf, ms, glsl, 8, sch);   // max_s = floor(max / 2^(exp' - 24) + 0.5)
            SE5_PUT(190, tb, big, ms, cf512); SE5_PUT(128, ti, ep1, ep, ci1); SE5_PUT(169, ti, ex, big, ep1, ep); SE5_PUT(130, ti, nx2, ci24, ex);   // max_s 512: exp' + 1
            for (int j = 0; j < 3; j++) { uint32_t a = nb++, b = nb++, f = nb++; s[j] = nb++;
                SE5_PUT(12, tf, a, glsl, 53, cc[j], nx2); SE5_PUT(129, tf, b, a, cfh); SE5_PUT(12, tf, f, glsl, 8, b); SE5_PUT(109, tu, s[j], f); }
            uint32_t g9 = nb++, b18 = nb++, exu = nb++, e27 = nb++, o1 = nb++, o2 = nb++, pk = nb++, tex = nb++;
            SE5_PUT(196, tu, g9, s[1], cu9); SE5_PUT(196, tu, b18, s[2], cu18); SE5_PUT(124, tu, exu, ex); SE5_PUT(196, tu, e27, exu, cu27);
            SE5_PUT(197, tu, o1, s[0], g9); SE5_PUT(197, tu, o2, o1, b18); SE5_PUT(197, tu, pk, o2, e27); SE5_PUT(80, tv4u, tex, pk, cu0, cu0, cu0);
            uint32_t a[16]; uint32_t na = len - 1 < 16 ? len - 1 : 16; for (uint32_t j = 0; j < na; j++) a[j] = x[1 + j]; a[2] = tex;
            k = spv_e5_put(o, k, cap, &full, op, a, na); continue;
        }
        if (op == 98 && ID(x[3]) && kind[x[3]] == SE5_LOADED) {   // a read: the word, unpacked into its three floats and alpha 1
            uint32_t rd = nb++, p = nb++, a[16]; uint32_t na = len - 1 < 16 ? len - 1 : 16; for (uint32_t j = 0; j < na; j++) a[j] = x[1 + j]; a[0] = tv4u; a[1] = rd;
            k = spv_e5_put(o, k, cap, &full, op, a, na);
            SE5_PUT(81, tu, p, rd, 0);
            uint32_t eu = nb++, ei = nb++, en = nb++, ch[3];
            SE5_PUT(194, tu, eu, p, cu27); SE5_PUT(124, ti, ei, eu); SE5_PUT(130, ti, en, ei, ci24);
            for (int j = 0; j < 3; j++) { uint32_t sh = j ? nb++ : p, m = nb++, f = nb++; ch[j] = nb++;
                if (j) SE5_PUT(194, tu, sh, p, j == 1 ? cu9 : cu18);
                SE5_PUT(199, tu, m, sh, cu511); SE5_PUT(112, tf, f, m); SE5_PUT(12, tf, ch[j], glsl, 53, f, en); }
            SE5_PUT(80, tv4f, x[2], ch[0], ch[1], ch[2], cf1);
            continue;
        }
        if (k + len > cap) { full = 1; break; }
        for (size_t j = 0; j < len; j++) o[k++] = w[at + j];
    }
#undef ID
    if (full || !placed) { *what = SPV_E5_KEPT; return 0; }
    o[3] = nb;
    return k;
}
#undef SE5_PUT
