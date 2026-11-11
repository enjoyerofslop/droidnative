// NVN2's texture and sampler pools read by ID (Ryujinx's handle fallback): a handle the translator cannot trace to one slot indexes arrays it sizes to the whole ID
// ranges, <stage>_t<type>_cb0_40000000 (2^20 images, one array per image type) and <stage>_s_cb0_40000000 (4096 samplers), the index clamped by UMin. The Mac reads
// them through pools it keeps per element type (dmsh_build.py pool_arrays, nvn_mtl.m pool_gpu). On Vulkan a set of 2^20 images per shader fits no descriptor pool, and
// every such draw was dropped (gfx_vk_draw.inc ds_fits): Ocarina of Time's Kokiri Forest drew its HUD over black, 1,017 of the 7,278 shaders the Mac plays reading them.
// spv_pool rewrites such a module for the replay's one pool set (gfx_vk_pool.inc), which every pool shader shares:
// - Every image pool variable goes to one binding of that set (b_img), the variables aliasing it whatever their image type: an element holds the view the shaders
//   ask of that ID. Its array is cfg n long (the game's texture pool, not 2^20), and each index is clamped to n - 1 again. The sampler pool goes to b_smp.
// - A sample with a depth reference takes its sampler from b_cmp, the same IDs made with comparison on: Vulkan compares only with a sampler made so, and the
//   translator's 2D shadow arrays and plain arrays read one sampler array.
// - Indices, the pointers and the values loaded through them are decorated NonUniform: a handle comes from memory, and the lanes of one subgroup may read different IDs.
// - Which IDs are read is known only on the GPU, as on the Mac, so each read sets a bit in a storage buffer (b_seen: one word per ID, a bit per view type): the
//   host makes the textures that were read, not every texture the game registered (Ocarina of Time registers about 33,000 and reads about 300). The word is read
//   first and stored only when the bit is clear, so nearly every read costs a load. In a loop header the block is not split (its merge instruction must stay in it),
//   and the bit is stored unconditionally. A fragment shader whose result the store cannot change (no discard, no depth or sample mask written, no stores of its own)
//   keeps its depth test before it runs (EarlyFragmentTests), as dmsh_build.py does on the Mac.
// - The bindings after the pool arrays in their own set move down by the arrays' lengths, which the translator left them past: Ocarina of Time's constant buffers
//   at 2,101,263 behind two image arrays and the sampler array. A driver may size a set layout by its highest binding: Mali's held 104 MB of native heap for one such
//   shader's layout and 16 MB for each pipeline layout over it, 6.6 GB at the title. gfx_vk_draw.inc sh_get moves the shader's bindings down the same way.
// A module with a use of a pool variable this does not cover (a whole array loaded, passed to a function) is left as it is (SPV_POOL_FAIL).
// Self-contained (no libc), like spv_limits.h, so that dm/tools/tests/test_spv_pool.py builds it alone and runs it over a game's shaders on the PC.
#pragma once
#include <stddef.h>
#include <stdint.h>

enum { SPV_POOL_IMG = 1, SPV_POOL_SMP = 2, SPV_POOL_CMP = 4, SPV_POOL_MARK = 8, SPV_POOL_EARLY = 16, SPV_POOL_LOOPMARK = 32, SPV_POOL_FAIL = 64 };
// n: the image binding's elements; set and bindings in the replay's pool set; mark: add the reads' marks (the GPU stores from fragment and compute shaders);
// mark_vtx: also from vertex, tessellation, geometry, task and mesh shaders (vertexPipelineStoresAndAtomics)
struct spv_pool_cfg { uint32_t n, set, b_img, b_smp, b_cmp, b_seen; int mark, mark_vtx; };
#define SPV_POOL_SCRATCH 11   // scratch words per id of the module's bound (w[3])

static size_t spv_pool_put(uint32_t *o, size_t k, uint32_t op, const uint32_t *a, uint32_t na) { o[k++] = (na + 1) << 16 | op; for (uint32_t q = 0; q < na; q++) o[k++] = a[q]; return k; }
#define SPV_POOL_PUT(op, ...) do { const uint32_t a_[] = {__VA_ARGS__}; k = spv_pool_put(o, k, (op), a_, (uint32_t)(sizeof a_ / sizeof *a_)); } while (0)
static size_t spv_pool_str(uint32_t *o, size_t k, uint32_t op, const char *s) {   // an instruction of one string operand (OpExtension)
    size_t n = 0; while (s[n]) n++;
    uint32_t nw = (uint32_t)(n / 4 + 1); o[k++] = (nw + 1) << 16 | op;
    for (uint32_t q = 0; q < nw; q++) { uint32_t v = 0; for (uint32_t b = 0; b < 4; b++) { size_t c = 4 * (size_t)q + b; if (c < n) v |= (uint32_t)(uint8_t)s[c] << (8 * b); } o[k++] = v; }
    return k;
}
static int spv_pool_streq(const uint32_t *w, uint32_t nw, const char *s) {   // a string operand of nw words equals s
    for (uint32_t c = 0;; c++) { if (c / 4 >= nw) return 0; uint8_t ch = (uint8_t)(w[c / 4] >> (8 * (c % 4))); if (ch != (uint8_t)s[c]) return 0; if (!ch) return 1; }
}
// The view type an image type is read as (VkImageViewType, 7 / 8 for multisample 2D / 2D arrays): the bit its reads set in the marks
static uint32_t spv_pool_code(uint32_t packed) {
    uint32_t dim = packed & 15, arr = (packed >> 8) & 1, ms = (packed >> 12) & 1;
    if (ms) return arr ? 8 : 7;
    return dim == 0 ? (arr ? 4 : 0) : dim == 2 ? 2 : dim == 3 ? (arr ? 6 : 3) : (arr ? 5 : 1);
}

// w[n]: the module. scratch: SPV_POOL_SCRATCH × bound words. o[cap]: the result. → its word count, or 0: *info 0 (no pool variable), SPV_POOL_FAIL (left as it is), or
// with *need set above cap (o too small; *need is the size to give). *info: what was done (SPV_POOL_*)
static size_t spv_pool(const uint32_t *w, size_t n, const struct spv_pool_cfg *cfg, uint32_t *scratch, uint32_t *o, size_t cap, size_t *need, int *info) {
    enum { F_PIMG = 1, F_PSMP = 2, F_ACI = 4, F_ACS = 8, F_LDI = 16, F_LDS = 32, F_NU = 64, F_LOOP = 128, F_SET = 256, F_BIND = 512, F_SMASK = 1024 };
    *info = 0; *need = 0;
    if (n < 5 || w[0] != 0x07230203) return 0;
    uint32_t bound = w[3], ver = w[1];
    uint32_t *def = scratch, *a1 = scratch + bound, *a2 = scratch + 2 * (size_t)bound, *fl = scratch + 3 * (size_t)bound, *x1 = scratch + 4 * (size_t)bound,
             *x2 = scratch + 5 * (size_t)bound, *x3 = scratch + 6 * (size_t)bound, *lab = scratch + 7 * (size_t)bound, *tmp = scratch + 8 * (size_t)bound,
             *bset = scratch + 9 * (size_t)bound, *bnum = scratch + 10 * (size_t)bound;   // each variable's DescriptorSet and Binding as the module has them
    for (size_t i = 0; i < SPV_POOL_SCRATCH * (size_t)bound; i++) scratch[i] = 0;
#define ID(x) ((x) && (x) < bound)
    // The module's globals: capabilities, extensions, the stage, decorations, types, constants, variables
    int has_nu = 0, has_sanu = 0, has_ext_di = 0, has_ext_sb = 0, frag = 0, vtxp = 0, early = 0, no_early = 0, npool = 0;
    uint32_t glsl = 0, tu = 0, ti = 0, tb = 0, fn0 = 0;   // fn0: the first function's word offset
    int tu_late = 0;   // the 32-bit unsigned type is declared after the first image pool variable (the new array lengths need it before)
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == 54) { fn0 = (uint32_t)i; break; }
        switch (op) {
            case 17: if (len > 1) { has_nu |= w[i + 1] == 5301; has_sanu |= w[i + 1] == 5307; } break;   // ShaderNonUniform, SampledImageArrayNonUniformIndexing
            case 10: has_ext_di |= spv_pool_streq(w + i + 1, len - 1, "SPV_EXT_descriptor_indexing"); has_ext_sb |= spv_pool_streq(w + i + 1, len - 1, "SPV_KHR_storage_buffer_storage_class"); break;
            case 11: if (len > 2 && ID(w[i + 1]) && spv_pool_streq(w + i + 2, len - 2, "GLSL.std.450")) glsl = w[i + 1]; break;
            case 15: if (len > 2) { uint32_t m = w[i + 1]; frag |= m == 4; vtxp |= m <= 3 || m == 5267 || m == 5268 || m == 5364 || m == 5365; } break;
            case 16: if (len > 2) { uint32_t m = w[i + 2]; early |= m == 9; no_early |= m == 12 || m == 14 || m == 15 || m == 16 || (m >= 5366 && m <= 5371) || m == 5027; } break;
            case 71: if (len > 2 && ID(w[i + 1])) {   // OpDecorate
                uint32_t t = w[i + 1], d = w[i + 2];
                if (d == 34) fl[t] |= F_SET; if (d == 33) fl[t] |= F_BIND;
                if (d == 34 && len > 3) bset[t] = w[i + 3]; if (d == 33 && len > 3) bnum[t] = w[i + 3];
                if (d == 11 && len > 3) { if (w[i + 3] == 22 || w[i + 3] == 5014) no_early = 1; if (w[i + 3] == 20) fl[t] |= F_SMASK; }   // FragDepth, FragStencilRefEXT; SampleMask
            } break;
            case 20: if (len > 1 && ID(w[i + 1])) { def[w[i + 1]] = op; if (!tb) tb = w[i + 1]; } break;
            case 21: if (len > 3 && ID(w[i + 1])) { def[w[i + 1]] = op; a1[w[i + 1]] = w[i + 2]; a2[w[i + 1]] = w[i + 3];
                         if (w[i + 2] == 32 && !w[i + 3] && !tu) { tu = w[i + 1]; tu_late = npool > 0; } if (w[i + 2] == 32 && w[i + 3] == 1 && !ti) ti = w[i + 1]; } break;
            case 25: if (len > 8 && ID(w[i + 1])) { def[w[i + 1]] = op; a1[w[i + 1]] = (w[i + 3] & 15) | (w[i + 4] & 15) << 4 | (w[i + 5] & 1) << 8 | (w[i + 6] & 1) << 12 | (w[i + 7] & 3) << 16; } break;
            case 26: if (len > 1 && ID(w[i + 1])) def[w[i + 1]] = op; break;
            case 28: case 32: if (len > 3 && ID(w[i + 1])) { def[w[i + 1]] = op; a1[w[i + 1]] = w[i + 2]; a2[w[i + 1]] = w[i + 3]; } break;   // OpTypeArray elem length; OpTypePointer class type
            case 43: if (len > 3 && ID(w[i + 2])) { def[w[i + 2]] = op; a1[w[i + 2]] = w[i + 1]; a2[w[i + 2]] = w[i + 3]; } break;   // OpConstant (its low word)
            case 59: if (len > 3 && ID(w[i + 2]) && ID(w[i + 1])) {
                uint32_t v = w[i + 2], t = w[i + 1], c = w[i + 3]; def[v] = op; a1[v] = t; a2[v] = c;
                if (c == 3 && (fl[v] & F_SMASK)) no_early = 1;   // the sample mask written
                if (c == 0 && def[t] == 32 && ID(a2[t]) && def[a2[t]] == 28) {
                    uint32_t arr = a2[t], el = a1[arr], ln = a2[arr], len_ = ID(ln) && def[ln] == 43 ? a2[ln] : 0;
                    if (ID(el) && def[el] == 25 && ((a1[el] >> 16) & 3) == 1 && (a1[el] & 15) != 5 && (a1[el] & 15) != 6 && len_ == 1u << 20) { fl[v] |= F_PIMG; npool++; }
                    if (ID(el) && def[el] == 26 && len_ == 4096) { fl[v] |= F_PSMP; npool++; }
                }
            } break;
            default: break;
        }
        i += len;
    }
    if (!npool) return 0;
    *info = SPV_POOL_FAIL;
    if (!fn0 || !tu || tu_late) return 0;
    for (uint32_t v = 1; v < bound; v++) if ((fl[v] & (F_PIMG | F_PSMP)) && (fl[v] & (F_SET | F_BIND)) != (F_SET | F_BIND)) return 0;   // the decorations it moves
    uint32_t pv[8], npv = 0;   // the pool variables, whose set and binding the bindings after them in that set move down past (their arrays' lengths)
    for (uint32_t v = 1; v < bound; v++) if (fl[v] & (F_PIMG | F_PSMP)) { if (npv == 8) return 0; pv[npv++] = v; }
    // The function bodies: the pool's access chains and loads, the samples that need the comparison samplers, what the fragment shader writes, loop headers
    int discard = 0, self_write = 0; uint32_t nac = 0, naci = 0, nredir = 0, nnu = 0, codes = 0, need_iu = 0, need_ii = 0, nb = bound, cur = 0, smpvar = 0;
    for (size_t i = fn0; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == 248 && len > 1 && ID(w[i + 1])) cur = w[i + 1];
        if (op == 246 && ID(cur)) fl[cur] |= F_LOOP;
        if (op == 252 || op == 4416 || op == 5380) discard = 1;   // OpKill, OpTerminateInvocation, OpDemoteToHelperInvocation
        if (op == 99 || (op >= 227 && op <= 242) || op == 6035 || op == 5614 || op == 5615) self_write = 1;   // image writes, atomics
        if ((op == 62 || op == 63 || op == 64) && len > 2 && ID(w[i + 1])) {   // a store or copy into a buffer: the shader's own
            uint32_t pt = a1[w[i + 1]]; if (ID(pt) && def[pt] == 32 && (a1[pt] == 2 || a1[pt] == 12)) self_write = 1; }
        // the uses of a pool variable other than an access chain's base
        if ((op == 61 || op == 83) && len > 3 && ID(w[i + 3]) && (fl[w[i + 3]] & (F_PIMG | F_PSMP))) return 0;   // the whole array loaded or copied
        if ((op == 57 || op == 245 || op == 169 || op == 67 || op == 62) && len > 1)
            for (uint32_t q = 1; q < len; q++) if (ID(w[i + q]) && (fl[w[i + q]] & (F_PIMG | F_PSMP)) && !(op == 57 && q < 4) && !(op == 245 && q % 2 == 0)) return 0;
        // result types, for the indices' and images' types (the instructions that make the values these meet)
        switch (op) {
            case 1: case 12: case 61: case 65: case 66: case 67: case 81: case 83: case 86: case 100: case 109: case 110: case 113: case 114: case 124: case 128: case 130: case 132:
            case 134: case 135: case 137: case 169: case 194: case 195: case 196: case 197: case 198: case 199: case 245:
                if (len > 2 && ID(w[i + 2])) a1[w[i + 2]] = w[i + 1]; break;
            default: break;
        }
        if ((op == 65 || op == 66) && len > 3 && ID(w[i + 2]) && ID(w[i + 3]) && (fl[w[i + 3]] & (F_PIMG | F_PSMP))) {
            uint32_t r = w[i + 2], base = w[i + 3];
            if (len != 5 || !ID(w[i + 4])) return 0;   // one index: the element
            uint32_t idx = w[i + 4], it = a1[idx];
            if (!(it == tu || (ti && it == ti))) return 0;
            x1[r] = idx; x2[r] = base; x3[r] = nb++; nac++;
            if (fl[base] & F_PIMG) { fl[r] |= F_ACI; naci++; need_iu |= it == tu; need_ii |= it == ti;
                codes |= 1u << spv_pool_code(a1[a1[a2[a1[base]]]]); }   // base → pointer → array → image
            else { fl[r] |= F_ACS; if (!smpvar) smpvar = base; }
            fl[r] |= F_NU; nnu++;
        }
        if (op == 61 && len > 3 && ID(w[i + 2]) && ID(w[i + 3]) && (fl[w[i + 3]] & (F_ACI | F_ACS))) {
            fl[w[i + 2]] |= (fl[w[i + 3]] & F_ACI ? F_LDI : F_LDS) | F_NU; x1[w[i + 2]] = w[i + 3]; nnu++; }
        if (op == 83 && len > 3 && ID(w[i + 2]) && ID(w[i + 3]) && (fl[w[i + 3]] & F_NU)) {   // a copy of a loaded image or sampler: the same
            fl[w[i + 2]] |= fl[w[i + 3]] & (F_NU | F_LDI | F_LDS); x1[w[i + 2]] = x1[w[i + 3]]; nnu++; }
        if (op == 86 && len > 4 && ID(w[i + 2])) {   // OpSampledImage type result image sampler
            uint32_t r = w[i + 2], img = w[i + 3], smp = w[i + 4];
            if ((ID(img) && (fl[img] & F_NU)) || (ID(smp) && (fl[smp] & F_NU))) { fl[r] |= F_NU; nnu++; }
            uint32_t itp = ID(img) ? a1[img] : 0;
            if (ID(smp) && (fl[smp] & F_LDS) && ID(itp) && def[itp] == 25 && ((a1[itp] >> 4) & 15) == 1 && !x3[r]) { x3[r] = nb; nb += 2; nredir++; }   // a depth image: compare
        }
        if (op == 100 && len > 3 && ID(w[i + 2]) && ID(w[i + 3]) && (fl[w[i + 3]] & F_NU)) { fl[w[i + 2]] |= F_NU; nnu++; }
        i += len;
    }
    int mark = cfg->mark && naci && (vtxp ? cfg->mark_vtx : 1);
    int add_early = frag && mark && !early && !discard && !self_write && !no_early;
    // the new ids
    uint32_t c_n = 0, nm1u = 0, nm1i = 0, u0 = 0, bits[9] = {0}, rta = 0, sst = 0, psst = 0, seen = 0, pu = 0, cmp = 0, tbool = tb;
    if (naci) { c_n = nb++; if (need_iu) nm1u = nb++; if (need_ii) nm1i = nb++; }
    if (mark) { u0 = nb++; for (int c = 0; c < 9; c++) if (codes >> c & 1) bits[c] = nb++; rta = nb++; sst = nb++; psst = nb++; seen = nb++; pu = nb++; if (!tbool) tbool = nb++; }
    if (nredir) cmp = nb++;
    size_t room = n + 64 * (size_t)nac + 16 * (size_t)nredir + 3 * (size_t)nnu + 6 * (size_t)nac + 256;
    if (cap < room) { *need = room; *info = 0; return 0; }
    // The module again, rewritten
    size_t k = 0; for (int q = 0; q < 5; q++) o[k++] = w[q];
    int caps_done = 0, exts_done = 0, glsl_done = glsl != 0, modes_done = 0, decos_done = 0, tail_done = 0, cn_done = 0, seen_entry = 0;
    if (!glsl) glsl = nb++;
    uint32_t orig = 0, curl = 0, inloop = 0, loopmarks = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!caps_done && op != 17) {
            if (!has_nu) SPV_POOL_PUT(17, 5301);
            if (!has_sanu) SPV_POOL_PUT(17, 5307);
            caps_done = 1;
        }
        if (!exts_done && op != 17 && op != 10) {
            if (!has_ext_di && ver < 0x00010500) k = spv_pool_str(o, k, 10, "SPV_EXT_descriptor_indexing");
            if (mark && !has_ext_sb && ver < 0x00010300) k = spv_pool_str(o, k, 10, "SPV_KHR_storage_buffer_storage_class");
            exts_done = 1;
        }
        if (!glsl_done && op != 17 && op != 10 && op != 11) {   // before OpMemoryModel
            o[k++] = 6u << 16 | 11; o[k++] = glsl; o[k++] = 0x4c534c47; o[k++] = 0x6474732e; o[k++] = 0x3035342e; o[k++] = 0; glsl_done = 1; }   // "GLSL.std.450"
        if (op == 15) seen_entry = 1;
        if (!modes_done && seen_entry && op != 15 && op != 16 && op != 331) {
            if (add_early) for (size_t j = 5; j < n; ) { uint32_t l2 = w[j] >> 16; if ((w[j] & 0xffff) == 15 && w[j + 1] == 4) SPV_POOL_PUT(16, w[j + 2], 9); if ((w[j] & 0xffff) == 54) break; j += l2; }
            modes_done = 1;
        }
        if (!decos_done && ((op >= 19 && op <= 39) || op == 41 || op == 42 || op == 43 || op == 44 || op == 45 || op == 46 || op == 59 || op == 1 || op == 54 || op == 322 || op == 4472)) {
            for (uint32_t v = 1; v < bound; v++) if (fl[v] & F_NU) SPV_POOL_PUT(71, v, 5300);
            for (uint32_t v = 1; v < bound; v++) { if (x3[v] && (fl[v] & (F_ACI | F_ACS))) SPV_POOL_PUT(71, x3[v], 5300); else if (x3[v]) { SPV_POOL_PUT(71, x3[v], 5300); SPV_POOL_PUT(71, x3[v] + 1, 5300); } }
            if (mark) { SPV_POOL_PUT(71, rta, 6, 4); SPV_POOL_PUT(71, sst, 2); SPV_POOL_PUT(72, sst, 0, 35, 0); SPV_POOL_PUT(71, seen, 34, cfg->set); SPV_POOL_PUT(71, seen, 33, cfg->b_seen); }
            if (cmp) { SPV_POOL_PUT(71, cmp, 34, cfg->set); SPV_POOL_PUT(71, cmp, 33, cfg->b_cmp); }
            decos_done = 1;
        }
        if (!tail_done && op == 54) {   // the end of the globals: the constants and types the rewrite uses
            if (mark) {
                if (!tb) SPV_POOL_PUT(20, tbool);
                SPV_POOL_PUT(43, tu, u0, 0);
                for (int c = 0; c < 9; c++) if (bits[c]) SPV_POOL_PUT(43, tu, bits[c], 1u << c);
                SPV_POOL_PUT(29, rta, tu); SPV_POOL_PUT(30, sst, rta); SPV_POOL_PUT(32, psst, 12, sst); SPV_POOL_PUT(59, psst, seen, 12); SPV_POOL_PUT(32, pu, 12, tu);
            }
            if (nm1u) SPV_POOL_PUT(43, tu, nm1u, cfg->n - 1);
            if (nm1i) SPV_POOL_PUT(43, ti, nm1i, cfg->n - 1);
            tail_done = 1;
        }
        if (op == 15 && ver >= 0x00010400 && (seen || cmp)) {   // SPIR-V 1.4: the interface lists every global variable the entry point uses
            uint32_t add = (seen ? 1u : 0u) + (cmp ? 1u : 0u);
            o[k++] = (len + add) << 16 | 15; for (uint32_t q = 1; q < len; q++) o[k++] = w[i + q];
            if (seen) o[k++] = seen; if (cmp) o[k++] = cmp;
            i += len; continue;
        }
        if (op == 71 && len > 3 && ID(w[i + 1]) && w[i + 2] == 33 && !(fl[w[i + 1]] & (F_PIMG | F_PSMP)) && (fl[w[i + 1]] & F_SET)) {   // another binding: below the arrays before it
            uint32_t t = w[i + 1], b = w[i + 3], sh = 0;
            for (uint32_t q = 0; q < npv; q++) if (bset[pv[q]] == bset[t] && bnum[pv[q]] < b) sh += (fl[pv[q]] & F_PIMG) ? 1u << 20 : 4096u;
            if (sh && sh <= b) { SPV_POOL_PUT(71, t, 33, b - sh); i += len; continue; }
        }
        if (op == 71 && len > 3 && ID(w[i + 1]) && (fl[w[i + 1]] & (F_PIMG | F_PSMP)) && (w[i + 2] == 34 || w[i + 2] == 33)) {   // a pool variable's set and binding
            SPV_POOL_PUT(71, w[i + 1], w[i + 2], w[i + 2] == 34 ? cfg->set : (fl[w[i + 1]] & F_PIMG) ? cfg->b_img : cfg->b_smp); i += len; continue; }
        if (op == 59 && i < fn0 && (fl[w[i + 2]] & F_PIMG)) {   // an image pool variable: an array cfg n long
            uint32_t el = a1[a2[a1[w[i + 2]]]];
            if (!cn_done) { SPV_POOL_PUT(43, tu, c_n, cfg->n); cn_done = 1; }
            if (!x2[el]) { uint32_t na = nb++, np = nb++; x2[el] = np; SPV_POOL_PUT(28, na, el, c_n); SPV_POOL_PUT(32, np, 0, na); }
            SPV_POOL_PUT(59, x2[el], w[i + 2], 0); i += len; continue;
        }
        if (op == 59 && i < fn0 && w[i + 2] == smpvar && cmp) {   // the comparison samplers beside the sampler pool
            for (uint32_t q = 0; q < len; q++) o[k++] = w[i + q];
            SPV_POOL_PUT(59, w[i + 1], cmp, 0); i += len; continue;
        }
        if (op == 248) { orig = curl = w[i + 1]; inloop = ID(orig) && (fl[orig] & F_LOOP); }
        if ((op == 65 || op == 66) && len == 5 && ID(w[i + 2]) && (fl[w[i + 2]] & (F_ACI | F_ACS))) {
            uint32_t r = w[i + 2], idx = x1[r], c = x3[r], it = a1[idx];
            if (fl[r] & F_ACS) SPV_POOL_PUT(83, it, c, idx);
            else {
                SPV_POOL_PUT(12, it, c, glsl, 38, idx, it == tu ? nm1u : nm1i);   // UMin
                if (mark) {
                    uint32_t bit = bits[spv_pool_code(a1[a1[a2[a1[x2[r]]]]])], u = c, p = nb++, wv = nb++, t = nb++, or_ = nb++;
                    if (it != tu) { u = nb++; SPV_POOL_PUT(124, tu, u, c); }
                    SPV_POOL_PUT(65, pu, p, seen, u0, u); SPV_POOL_PUT(61, tu, wv, p); SPV_POOL_PUT(199, tu, t, wv, bit);
                    if (!inloop) {
                        uint32_t z = nb++, mk = nb++, cont = nb++;
                        SPV_POOL_PUT(170, tbool, z, t, u0); SPV_POOL_PUT(247, cont, 0); SPV_POOL_PUT(250, z, mk, cont);
                        SPV_POOL_PUT(248, mk); SPV_POOL_PUT(197, tu, or_, wv, bit); SPV_POOL_PUT(62, p, or_); SPV_POOL_PUT(249, cont); SPV_POOL_PUT(248, cont);
                        curl = cont; if (ID(orig)) lab[orig] = cont;
                    } else { SPV_POOL_PUT(197, tu, or_, wv, bit); SPV_POOL_PUT(62, p, or_); loopmarks++; }
                }
            }
            SPV_POOL_PUT(op, w[i + 1], r, w[i + 3], c); i += len; continue;
        }
        if (op == 86 && len > 4 && ID(w[i + 2]) && x3[w[i + 2]]) {   // a depth image with a pool sampler: the same ID's comparison sampler
            uint32_t r = w[i + 2], smp = w[i + 4], ac = x1[smp], a = x3[r], l = a + 1;
            SPV_POOL_PUT(65, a1[ac], a, cmp, x3[ac]); SPV_POOL_PUT(61, a1[smp], l, a);
            o[k++] = w[i]; o[k++] = w[i + 1]; o[k++] = r; o[k++] = w[i + 3]; o[k++] = l; for (uint32_t q = 5; q < len; q++) o[k++] = w[i + q];
            i += len; continue;
        }
        for (uint32_t q = 0; q < len; q++) o[k++] = w[i + q];
        i += len;
    }
    (void)curl;
    if (!tail_done || !decos_done) return 0;
    for (size_t i = 5; i < k; ) {   // a block split by a mark: the phis of its successors name the block that now ends it
        uint32_t len = o[i] >> 16; if (!len) return 0;
        if ((o[i] & 0xffff) == 245) for (uint32_t q = 4; q < len; q += 2) if (ID(o[i + q]) && lab[o[i + q]]) o[i + q] = lab[o[i + q]];
        i += len;
    }
    o[3] = nb;
    *info = (naci ? SPV_POOL_IMG : 0) | (nac > naci ? SPV_POOL_SMP : 0) | (cmp ? SPV_POOL_CMP : 0) | (mark ? SPV_POOL_MARK : 0) | (add_early ? SPV_POOL_EARLY : 0) | (loopmarks ? SPV_POOL_LOOPMARK : 0);
    if (!naci && nac == 0) *info |= SPV_POOL_IMG;   // pool variables no instruction reads: moved all the same
#undef ID
    (void)tmp;
    return k;
}
#undef SPV_POOL_PUT
