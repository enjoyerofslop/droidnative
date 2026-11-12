// Transform feedback captured in the fragment stage, for a GPU without vertex-stage storage writes. The replay captures a vertex shader's feedback outputs with
// its .tf.spv variant, which stores them into storage buffers from the vertex stage (tools/spv_android.py tf_variant, gfx_vk_draw.inc tf_capture). Vulkan allows
// that only with vertexPipelineStoresAndAtomics, which Arm's Mali drivers lack (the Pixel 9 Pro XL's Mali-G715, driver 0xd803000); so Pokémon Legends: Arceus,
// which skins its characters and Pokémon with transform feedback, drew none of them there. (That driver lists VK_EXT_transform_feedback, which the replay doesn't
// use: it captures whole output variables, where NVN's layouts take the first components of each; this capture needs only fragment-stage stores.)
// Mali does have fragmentStoresAndAtomics. So the capture draws the vertex shader as points, one pixel each: spv_tff_vs wraps the shader's entry point so that,
// once the shader has run, vertex v's position is the centre of pixel (v & 1023, v >> 10) of a 1024 × 1024 grid and its point size 1; the clip and cull distances
// it writes become 1 (a vertex its own clip distances would cut still has its record written), and those it doesn't write stay unwritten: the translator declares
// 8 clip and 1 cull distance in every vertex shader, past the 8 the phones take in all (maxCombinedClipAndCullDistances), and writing all 9 aborted Qualcomm's
// V@0615 compiler (the Adreno 730) on Arceus's capture. The layer and viewport are made 0 only where the shader writes them. The feedback outputs travel as they are to a fragment shader
// spv_tff_fs makes from the feedback layout alone: its inputs are those outputs, flat, and it stores their bits where the vertex variant would have, vertex v at
// v × stride from the write offset, v read back from gl_FragCoord. A point covers exactly the pixel whose centre it sits on, so each record is written once; a
// vertex shading scheme that runs a vertex more than once (Mali's IDVS shades positions first) cannot write it twice, as a vertex-stage store could.
// The fragment shader is made at run time on the phone, so no game needs building again. Self-contained (no libc) for dm/tools/tests/test_spv_tffrag.py.
#pragma once
#include <stddef.h>
#include <stdint.h>

#define SPV_TFF_SHIFT 10                                // the grid is 1 << SPV_TFF_SHIFT pixels wide and high
#define SPV_TFF_MAX_VERTS (1u << (2 * SPV_TFF_SHIFT))   // vertices one capture can take
#define SPV_TFF_MAX_OUT 32
// The feedback layout (res.json "tf"): per buffer its stride in bytes (0: unused) and its outputs in order, generic output loc[i] with its first ncomp[i] components
typedef struct { uint32_t stride[4], nout[4]; uint8_t loc[4][SPV_TFF_MAX_OUT], ncomp[4][SPV_TFF_MAX_OUT]; } spv_tff_layout;

static int spv_tff_emit(uint32_t *o, size_t *k, size_t cap, uint32_t op, const uint32_t *a, uint32_t na) {
    if (*k + 1 + na > cap) return 0;
    o[(*k)++] = (na + 1) << 16 | op; for (uint32_t i = 0; i < na; i++) o[(*k)++] = a[i];
    return 1;
}
#define SPV_TFF_PUT(op, ...) do { const uint32_t a_[] = {__VA_ARGS__}; if (!spv_tff_emit(o, &k, cap, (op), a_, (uint32_t)(sizeof a_ / 4))) return 0; } while (0)
#define SPV_TFF_PUT0(op) do { if (!spv_tff_emit(o, &k, cap, (op), NULL, 0)) return 0; } while (0)

// The instruction that defines id: a type (its result first), a constant or a variable (result after the type); NULL when there is none
static const uint32_t *spv_tff_def(const uint32_t *w, size_t n, uint32_t id) {
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return NULL;
        if (op >= 19 && op <= 39 && len >= 2 && w[i + 1] == id) return w + i;
        if ((op == 43 || op == 59) && len >= 3 && w[i + 2] == id) return w + i;   // OpConstant, OpVariable
        i += len; }
    return NULL;
}
static int spv_tff_isf32(const uint32_t *w, size_t n, uint32_t t) { const uint32_t *d = spv_tff_def(w, n, t); return d && (d[0] & 0xffff) == 22 && d[2] == 32; }
static int spv_tff_isv4f(const uint32_t *w, size_t n, uint32_t t) { const uint32_t *d = spv_tff_def(w, n, t); return d && (d[0] & 0xffff) == 23 && d[3] == 4 && spv_tff_isf32(w, n, d[2]); }
static uint32_t spv_tff_pointee(const uint32_t *w, size_t n, uint32_t ptr) { const uint32_t *d = spv_tff_def(w, n, ptr); return d && (d[0] & 0xffff) == 32 ? d[3] : 0; }
// Whether the shader writes base (a built-in's variable; member >= 0: that member of the block variable base): an access chain into it, its first index the
// constant member, or a store or copy to the variable itself. Reads count too, which a vertex shader does not make of its outputs
static int spv_tff_written(const uint32_t *w, size_t n, uint32_t base, int member) {
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *a = w + i + 1; if (!len || i + len > n) return 0;
        if ((op == 65 || op == 66) && len >= 4 && a[2] == base) {   // OpAccessChain, OpInBoundsAccessChain
            if (member < 0) return 1;
            const uint32_t *c = len >= 5 ? spv_tff_def(w, n, a[3]) : NULL;
            if (c && (c[0] & 0xffff) == 43 && c[3] == (uint32_t)member) return 1; }
        if ((op == 62 || op == 63) && len >= 3 && a[0] == base) return 1;   // OpStore, OpCopyMemory to it (the whole block counts as every member)
        i += len; }
    return 0;
}
static uint32_t spv_tff_arraylen(const uint32_t *w, size_t n, uint32_t t) {   // an OpTypeArray of 32-bit float: its length (a constant), else 0
    const uint32_t *d = spv_tff_def(w, n, t); if (!d || (d[0] & 0xffff) != 28 || !spv_tff_isf32(w, n, d[2])) return 0;
    const uint32_t *c = spv_tff_def(w, n, d[3]); return c && (c[0] & 0xffff) == 43 && c[3] <= 8 ? c[3] : 0;
}

// Bit l: the module has an Output variable at location l that is a vec4 of 32-bit float (the outputs the fragment shader can take; the translator declares every
// generic output so). A feedback output that is not one is captured as zeros, as tf_variant stores it
static uint32_t spv_tff_outs(const uint32_t *w, size_t n) {
    if (n < 5 || w[0] != 0x07230203u) return 0;
    uint32_t mask = 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        if (op == 71 && len >= 4 && w[i + 2] == 30 && w[i + 3] < 32) {   // OpDecorate id Location l
            const uint32_t *v = spv_tff_def(w, n, w[i + 1]);
            if (v && (v[0] & 0xffff) == 59 && v[3] == 3 && spv_tff_isv4f(w, n, spv_tff_pointee(w, n, v[1]))) mask |= 1u << w[i + 3]; }
        i += len; }
    return mask;
}

// The vertex shader w[n] with its entry point wrapped as the file header says, into o[cap] (n + 400 words is enough): its word count, or 0 when it is not a vertex
// shader or has no vec4 position. The input is left untouched
static size_t spv_tff_vs(const uint32_t *w, size_t n, uint32_t *o, size_t cap) {
    if (n < 5 || w[0] != 0x07230203u || cap < n) return 0;
    enum { POS, PSIZE, CLIP, CULL, LAYER, VPORT, NBI };
    static const uint32_t BI[NBI] = {0, 1, 3, 4, 9, 10};   // BuiltIn Position, PointSize, ClipDistance, CullDistance, Layer, ViewportIndex
    uint32_t entry = 0, fnres = 0, fntype = 0, vidx = 0, blk = 0, blkvar = 0, tf = 0, tu = 0, ti = 0;
    uint32_t var[NBI] = {0}, mem[NBI]; int inblk[NBI] = {0};
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *a = w + i + 1; if (!len || i + len > n) return 0;
        if (op == 15 && len >= 3 && a[0] == 0 && !entry) entry = a[1];   // OpEntryPoint Vertex
        if (op == 71 && len >= 4 && a[1] == 11) { if (a[2] == 42) vidx = a[0]; for (int b = 0; b < NBI; b++) if (a[2] == BI[b]) var[b] = a[0]; }   // OpDecorate id BuiltIn
        if (op == 72 && len >= 5 && a[2] == 11) for (int b = 0; b < NBI; b++) if (a[3] == BI[b]) { blk = a[0]; mem[b] = a[1]; inblk[b] = 1; }   // OpMemberDecorate
        if (op == 22 && len >= 3 && a[1] == 32 && !tf) tf = a[0];
        if (op == 21 && len >= 4 && a[1] == 32) { if (a[2]) { if (!ti) ti = a[0]; } else if (!tu) tu = a[0]; }
        i += len; }
    if (!entry || !tf) return 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *a = w + i + 1;
        if (op == 54 && len >= 5 && a[1] == entry) { fnres = a[0]; fntype = a[3]; }
        if (op == 59 && len >= 4 && a[2] == 3 && blk && spv_tff_pointee(w, n, a[0]) == blk) blkvar = a[1];   // the Output block of built-ins
        i += len; }
    if (!fnres || (blk && !blkvar)) return 0;
    const uint32_t *st = blk ? spv_tff_def(w, n, blk) : NULL;
    uint32_t ty[NBI] = {0}, alen[NBI] = {0};   // each built-in's type, and a clip or cull distance array's length
    for (int b = 0; b < NBI; b++) {
        if (inblk[b]) { if (!st || 2 + mem[b] >= (st[0] >> 16)) return 0; ty[b] = st[2 + mem[b]]; }
        else if (var[b]) { const uint32_t *v = spv_tff_def(w, n, var[b]); if (!v || (v[0] & 0xffff) != 59 || v[3] != 3) { var[b] = 0; continue; } ty[b] = spv_tff_pointee(w, n, v[1]); }
        if (b == CLIP || b == CULL) alen[b] = spv_tff_written(w, n, inblk[b] ? blkvar : var[b], inblk[b] ? (int)mem[b] : -1) ? spv_tff_arraylen(w, n, ty[b]) : 0;   // only what it writes
    }
    if (!(inblk[POS] || var[POS]) || !spv_tff_isv4f(w, n, ty[POS])) return 0;
    if ((inblk[PSIZE] || var[PSIZE]) && !spv_tff_isf32(w, n, ty[PSIZE])) return 0;
    uint32_t vt = 0;   // gl_VertexIndex's type
    if (vidx) { const uint32_t *v = spv_tff_def(w, n, vidx); vt = v && (v[0] & 0xffff) == 59 && v[3] == 1 ? spv_tff_pointee(w, n, v[1]) : 0; if (!vt) return 0; }
    // the pointer types the code needs, found or declared (only non-pointer types must be unique, but reusing keeps the module as small)
    uint32_t id = w[3], newu = 0, newi = 0, pov4 = 0, pof = 0, pin = 0, newpov4 = 0, newpof = 0, newpin = 0, newvidx = 0, newps = 0;
    if (!tu) tu = newu = id++;
    if (!vidx) { if (!ti) ti = newi = id++; vt = ti; }
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *a = w + i + 1;
        if (op == 32 && len >= 4 && a[1] == 3 && a[2] == ty[POS]) pov4 = a[0];
        if (op == 32 && len >= 4 && a[1] == 3 && a[2] == tf) pof = a[0];
        if (op == 32 && len >= 4 && a[1] == 1 && a[2] == vt) pin = a[0];
        i += len; }
    if (!pov4) pov4 = newpov4 = id++;
    if (!pof) pof = newpof = id++;
    if (!vidx) { if (!pin) pin = newpin = id++; vidx = newvidx = id++; }
    if (!inblk[PSIZE] && !var[PSIZE]) var[PSIZE] = newps = id++;
    uint32_t c1023 = id++, csh = id++, cinv = id++, cbias = id++, chalf = id++, cone = id++, cidx[8], cmem[NBI], czero[NBI] = {0};
    for (int e = 0; e < 8; e++) cidx[e] = id++;
    for (int b = 0; b < NBI; b++) cmem[b] = inblk[b] ? id++ : 0;
    for (int b = LAYER; b <= VPORT; b++) if (var[b] && !inblk[b] && ty[b] && spv_tff_written(w, n, var[b], -1)) czero[b] = id++;
    uint32_t wrap = id++;
    size_t k = 0; int decos = 0, globs = 0;
    for (int q = 0; q < 5; q++) o[k++] = w[q];
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *a = w + i + 1;
        if (!decos && (op == 71 || op == 72)) { decos = 1;   // the new built-ins' decorations, before the first
            if (newvidx) SPV_TFF_PUT(71, newvidx, 11, 42);
            if (newps) SPV_TFF_PUT(71, newps, 11, 1); }
        if (!globs && op == 54) { globs = 1;   // the new types, constants and variables, before the first function
            if (newu) SPV_TFF_PUT(21, newu, 32, 0);
            if (newi) SPV_TFF_PUT(21, newi, 32, 1);
            if (newpov4) SPV_TFF_PUT(32, newpov4, 3, ty[POS]);
            if (newpof) SPV_TFF_PUT(32, newpof, 3, tf);
            if (newpin) SPV_TFF_PUT(32, newpin, 1, vt);
            SPV_TFF_PUT(43, tu, c1023, (1u << SPV_TFF_SHIFT) - 1); SPV_TFF_PUT(43, tu, csh, SPV_TFF_SHIFT);
            SPV_TFF_PUT(43, tf, cinv, 0x3b000000u); SPV_TFF_PUT(43, tf, cbias, 0xbf7fc000u);   // 1/512 and -1023/1024: column c's centre at (2c + 1) / 1024 - 1, exact in float
            SPV_TFF_PUT(43, tf, chalf, 0x3f000000u); SPV_TFF_PUT(43, tf, cone, 0x3f800000u);
            for (int e = 0; e < 8; e++) SPV_TFF_PUT(43, tu, cidx[e], (uint32_t)e);
            for (int b = 0; b < NBI; b++) if (cmem[b]) SPV_TFF_PUT(43, tu, cmem[b], mem[b]);
            for (int b = LAYER; b <= VPORT; b++) if (czero[b]) SPV_TFF_PUT(43, ty[b], czero[b], 0);
            if (newvidx) SPV_TFF_PUT(59, pin, newvidx, 1);
            if (newps) SPV_TFF_PUT(59, pof, newps, 3); }
        if (op == 15 && len >= 3 && a[0] == 0 && a[1] == entry) {   // the entry point is the wrapper now, with the new built-ins in its interface
            uint32_t add = (newvidx != 0) + (newps != 0); if (k + len + add > cap) return 0;
            o[k++] = (len + add) << 16 | op; o[k++] = a[0]; o[k++] = wrap; for (uint32_t q = 2; q + 1 < len; q++) o[k++] = a[q];
            if (newvidx) o[k++] = newvidx;
            if (newps) o[k++] = newps;
            i += len; continue; }
        if (k + len > cap) return 0;
        for (uint32_t q = 0; q < len; q++) o[k++] = w[i + q];
        if (op == 16 && len >= 2 && a[0] == entry) o[k - len + 1] = wrap;   // OpExecutionMode
        i += len;
    }
    if (!decos || !globs) return 0;
    // the wrapper: the shader runs, then the point is placed on vertex v's pixel
    uint32_t lbl = id++, call = id++, vi = id++, vu = id++, col = id++, row = id++, cf = id++, rf = id++, xm = id++, x = id++, ym = id++, y = id++, pos = id++;
    SPV_TFF_PUT(54, fnres, wrap, 0, fntype); SPV_TFF_PUT(248, lbl); SPV_TFF_PUT(57, fnres, call, entry);
    SPV_TFF_PUT(61, vt, vi, vidx);
    if (vt == tu) vu = vi; else SPV_TFF_PUT(124, tu, vu, vi);
    SPV_TFF_PUT(199, tu, col, vu, c1023); SPV_TFF_PUT(194, tu, row, vu, csh);
    SPV_TFF_PUT(112, tf, cf, col); SPV_TFF_PUT(112, tf, rf, row);
    SPV_TFF_PUT(133, tf, xm, cf, cinv); SPV_TFF_PUT(129, tf, x, xm, cbias); SPV_TFF_PUT(133, tf, ym, rf, cinv); SPV_TFF_PUT(129, tf, y, ym, cbias);
    SPV_TFF_PUT(80, ty[POS], pos, x, y, chalf, cone);
    if (inblk[POS]) { uint32_t p = id++; SPV_TFF_PUT(65, pov4, p, blkvar, cmem[POS]); SPV_TFF_PUT(62, p, pos); } else SPV_TFF_PUT(62, var[POS], pos);
    if (inblk[PSIZE]) { uint32_t p = id++; SPV_TFF_PUT(65, pof, p, blkvar, cmem[PSIZE]); SPV_TFF_PUT(62, p, cone); } else SPV_TFF_PUT(62, var[PSIZE], cone);
    for (int b = CLIP; b <= CULL; b++) for (uint32_t e = 0; e < alen[b]; e++) {
        uint32_t p = id++;
        if (inblk[b]) SPV_TFF_PUT(65, pof, p, blkvar, cmem[b], cidx[e]); else if (var[b]) SPV_TFF_PUT(65, pof, p, var[b], cidx[e]); else continue;
        SPV_TFF_PUT(62, p, cone); }
    for (int b = LAYER; b <= VPORT; b++) if (czero[b]) SPV_TFF_PUT(62, var[b], czero[b]);
    SPV_TFF_PUT0(253); SPV_TFF_PUT0(56);
    o[3] = id;
    return k;
}

// The capture's fragment shader for layout L, its inputs the generic outputs in outs (spv_tff_outs of the vertex shader): o[cap] (1024 words is enough for any
// layout); its word count, or 0 (a buffer of more than 128 words a vertex). SPIR-V 1.3 at least (version: the vertex shader's), for the StorageBuffer class;
// buffer b at set 0, binding 100 + b, as tf_variant's
static size_t spv_tff_fs(uint32_t version, const spv_tff_layout *L, uint32_t outs, uint32_t *o, size_t cap) {
    enum { MAXW = 128 };
    if (version < 0x00010300u) version = 0x00010300u;
    uint32_t used = 0, nw = 0;   // the inputs read; the most words a vertex writes to one buffer
    for (int b = 0; b < 4; b++) { if (!L->stride[b]) continue; uint32_t at = 0;
        for (uint32_t q = 0; q < L->nout[b] && q < SPV_TFF_MAX_OUT; q++) { if (L->loc[b][q] < 32) used |= (outs >> L->loc[b][q] & 1u) << L->loc[b][q]; at += L->ncomp[b][q]; }
        if (at > MAXW) return 0;
        if (at > nw) nw = at; }
    uint32_t id = 1, tvoid = id++, tfn = id++, tfl = id++, tv4 = id++, tu = id++, pin = id++, rta = id++, sst = id++, psb = id++, psu = id++, csh = id++;
    uint32_t fmain = id++, fc = id++, in[32], buf[4] = {0, 0, 0, 0}, cst[4] = {0, 0, 0, 0}, cat[MAXW + 1];
    for (int l = 0; l < 32; l++) in[l] = 0;   // loops, not = {0}: a freestanding build has no memset to call
    for (uint32_t j = 0; j <= nw; j++) cat[j] = id++;   // the word offsets within a record (cat[0] is also the 0 an unreadable output stores)
    for (int l = 0; l < 32; l++) if (used >> l & 1) in[l] = id++;
    for (int b = 0; b < 4; b++) if (L->stride[b]) { buf[b] = id++; cst[b] = id++; }
    size_t k = 0; if (cap < 5) return 0;
    o[k++] = 0x07230203u; o[k++] = version; o[k++] = 0; o[k++] = 0; o[k++] = 0;
    SPV_TFF_PUT(17, 1);   // OpCapability Shader
    SPV_TFF_PUT(14, 0, 1);   // OpMemoryModel Logical GLSL450
    { uint32_t ep[4 + 1 + 32 + 4]; uint32_t ne = 0; ep[ne++] = 4; ep[ne++] = fmain; ep[ne++] = 0x6e69616du; ep[ne++] = 0;   // Fragment, "main"
      ep[ne++] = fc; for (int l = 0; l < 32; l++) if (in[l]) ep[ne++] = in[l];
      if (version >= 0x00010400u) for (int b = 0; b < 4; b++) if (buf[b]) ep[ne++] = buf[b];   // 1.4 lists every global the entry point uses
      if (!spv_tff_emit(o, &k, cap, 15, ep, ne)) return 0; }
    SPV_TFF_PUT(16, fmain, 7);   // OriginUpperLeft
    SPV_TFF_PUT(71, fc, 11, 15);   // BuiltIn FragCoord
    for (int l = 0; l < 32; l++) if (in[l]) { SPV_TFF_PUT(71, in[l], 30, (uint32_t)l); SPV_TFF_PUT(71, in[l], 14); }   // Location l, Flat: the bits as the vertex wrote them
    SPV_TFF_PUT(71, rta, 6, 4); SPV_TFF_PUT(71, sst, 2); SPV_TFF_PUT(72, sst, 0, 35, 0);
    for (int b = 0; b < 4; b++) if (buf[b]) { SPV_TFF_PUT(71, buf[b], 34, 0); SPV_TFF_PUT(71, buf[b], 33, 100u + (uint32_t)b); }
    SPV_TFF_PUT(19, tvoid); SPV_TFF_PUT(33, tfn, tvoid); SPV_TFF_PUT(22, tfl, 32); SPV_TFF_PUT(23, tv4, tfl, 4); SPV_TFF_PUT(21, tu, 32, 0);
    SPV_TFF_PUT(32, pin, 1, tv4); SPV_TFF_PUT(29, rta, tu); SPV_TFF_PUT(30, sst, rta); SPV_TFF_PUT(32, psb, 12, sst); SPV_TFF_PUT(32, psu, 12, tu);
    SPV_TFF_PUT(43, tu, csh, SPV_TFF_SHIFT);
    for (uint32_t j = 0; j <= nw; j++) SPV_TFF_PUT(43, tu, cat[j], j);
    for (int b = 0; b < 4; b++) if (buf[b]) SPV_TFF_PUT(43, tu, cst[b], L->stride[b] / 4);
    SPV_TFF_PUT(59, pin, fc, 1);
    for (int l = 0; l < 32; l++) if (in[l]) SPV_TFF_PUT(59, pin, in[l], 1);
    for (int b = 0; b < 4; b++) if (buf[b]) SPV_TFF_PUT(59, psb, buf[b], 12);
    uint32_t lbl = id++, c = id++, fx = id++, fy = id++, ux = id++, uy = id++, rs = id++, v = id++, val[32];
    for (int l = 0; l < 32; l++) val[l] = 0;
    SPV_TFF_PUT(54, tvoid, fmain, 0, tfn); SPV_TFF_PUT(248, lbl);
    SPV_TFF_PUT(61, tv4, c, fc); SPV_TFF_PUT(81, tfl, fx, c, 0); SPV_TFF_PUT(81, tfl, fy, c, 1);
    SPV_TFF_PUT(109, tu, ux, fx); SPV_TFF_PUT(109, tu, uy, fy); SPV_TFF_PUT(196, tu, rs, uy, csh); SPV_TFF_PUT(197, tu, v, rs, ux);   // v = row << 10 | column
    for (int l = 0; l < 32; l++) if (in[l]) { val[l] = id++; SPV_TFF_PUT(61, tv4, val[l], in[l]); }
    for (int b = 0; b < 4; b++) if (buf[b]) {
        uint32_t base = id++, at = 0; SPV_TFF_PUT(132, tu, base, v, cst[b]);   // vertex v's record: v × stride / 4 words in
        for (uint32_t q = 0; q < L->nout[b] && q < SPV_TFF_MAX_OUT; q++) {
            uint32_t l = L->loc[b][q], nc = L->ncomp[b][q];
            for (uint32_t e = 0; e < nc; e++, at++) {
                uint32_t bits = cat[0], idx = id++, p = id++;
                if (l < 32 && val[l] && e < 4) { uint32_t f = id++; bits = id++; SPV_TFF_PUT(81, tfl, f, val[l], e); SPV_TFF_PUT(124, tu, bits, f); }   // else 0, as tf_variant stores it
                SPV_TFF_PUT(128, tu, idx, base, cat[at]); SPV_TFF_PUT(65, psu, p, buf[b], cat[0], idx); SPV_TFF_PUT(62, p, bits);
            }
        }
    }
    SPV_TFF_PUT0(253); SPV_TFF_PUT0(56);
    o[3] = id;
    return k;
}
