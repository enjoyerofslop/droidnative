// Raw global memory without physical pointers (gfx_vk_gmem_noptr.inc). The translator reaches memory at an address it read from memory through the raw pool table and a
// physical pointer: its helper finds the table entry holding the address, adds the entry's 64-bit delta in two 32-bit halves with the carry, makes the sum a pointer
// (OpCompositeConstruct v2uint, OpBitcast ulong, OpConvertUToPtr into PhysicalStorageBuffer) and loads, stores or does an atomic through it. Older Qualcomm drivers refuse
// that: the Ayn Odin 2's Adreno 740 (V@0676.32) and the Razr's 730 (V@0615) reject OpConvertUToPtr, and the 740 has no shaderInt64 though it offers buffer device
// addresses. Every raw-memory shader failed to build there: Ocarina of Time's characters and water went dark, Frostpunk's buildings were invisible.
// So on such a driver each table entry's delta carries a slot instead of the piece's device address minus its start ((slot << 32) - start, gm_table): the helper's own sum
// comes out as the slot in the high word and the offset into the piece in the low word, and its code stays as translated. spv_noptr replaces only the end: each
// OpConvertUToPtr of a bitcast v2uint, and every load, store or atomic through its result, by an access into a runtime array of storage buffers, pools[high word].d[low word >> 2]
// (a vector as its components, each its own access, bitcast where they are not uint), decorated NonUniform as each invocation may reach another piece. The replay binds
// each placed piece's buffer at its slot (SPV_NOPTR_SET, SPV_NOPTR_BINDING). The pointer types, the capability, the extension and the memory model's addressing go, and
// Int64 too when nothing else needs it. It needs runtimeDescriptorArray and shaderStorageBufferArrayNonUniformIndexing (the Odin 2's 740 has both). A module whose pointers
// are made or used any other way is left as it is. Self-contained (no libc) for dm/tools/tests/test_spv_noptr.py.
#pragma once
#include <stddef.h>
#include <stdint.h>

enum { SPV_NOPTR_SET = 5, SPV_NOPTR_BINDING = 0 };   // after the texture pool's set (gfx_vk_pool.inc POOL_SET 4); the Odin 2's 740 binds up to 7 sets
enum { SPV_NOPTR_FORM = 1, SPV_NOPTR_USE = 2, SPV_NOPTR_TYPE = 3, SPV_NOPTR_ROOM = 4 };   // why a module was left: a malformed module or a pointer not made from a bitcast
                                                                                        // v2uint; a pointer used otherwise; a pointee that is not 32-bit words; out too small

// Whether the module goes through physical pointers (OpCapability PhysicalStorageBufferAddresses)
static int spv_noptr_wanted(const uint32_t *w, size_t n) {
    if (n < 5 || w[0] != 0x07230203) return 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        if (op == 17 && len == 2 && w[i + 1] == 5347) return 1;
        if (op != 17 && op != 10 && op != 11) return 0;   // past the capabilities, extensions and imports
        i += len; }
    return 0;
}
static int spv_noptr_str(const uint32_t *a, uint32_t nw, const char *s) {   // a literal string's words hold s
    const char *p = (const char *)a; uint32_t i = 0;
    for (; i < nw * 4 && s[i]; i++) if (p[i] != s[i]) return 0;
    return i < nw * 4 && !s[i] && p[i] == 0;
}
static size_t spv_noptr_put_str(uint32_t *out, size_t k, uint32_t op, const char *s) {   // an instruction of one literal string at out + k → its words
    uint32_t len = 0; while (s[len]) len++;
    uint32_t nw = len / 4 + 1; out[k] = (1 + nw) << 16 | op;
    for (uint32_t q = 0; q < nw; q++) { uint32_t v = 0; for (uint32_t b = 0; b < 4; b++) { uint32_t c = q * 4 + b < len ? (uint8_t)s[q * 4 + b] : 0; v |= c << (8 * b); } out[k + 1 + q] = v; }
    return 1 + nw;
}
// The atomics, their pointer at word 3 (result type, result, pointer), OpAtomicStore's at word 1
static int spv_noptr_atomic(uint32_t op) { return op >= 227 && op <= 242; }
// Instructions with a result type and a result id at words 1 and 2 that may make the address vector or the pointee's parts
static int spv_noptr_typed(uint32_t op) {
    switch (op) { case 1: case 41: case 42: case 43: case 44: case 46: case 50: case 55: case 57: case 59: case 61: case 79: case 80: case 81: case 82: case 83: case 120: case 124:
                  case 128: case 130: case 132: case 169: case 194: case 195: case 196: case 197: case 199: case 245: return 1;
                  default: return 0; }
}
// The capabilities, extensions, imports, memory model, entry points, execution modes, debug and annotation instructions: before the types
static int spv_noptr_pre(uint32_t op) {
    switch (op) { case 0: case 3: case 4: case 5: case 6: case 7: case 10: case 11: case 14: case 15: case 16: case 17: case 71: case 72: case 73: case 74: case 75: case 330: case 331:
                  case 332: case 5632: case 5633: return 1;
                  default: return 0; }
}
// Whether word q of an instruction is a literal (or a string), never an id this looks for
static int spv_noptr_lit(uint32_t op, uint32_t q) {
    switch (op) {
    case 3: case 4: case 7: case 10: case 11: case 14: case 15: case 16: case 17: case 330: case 331: return 1;
    case 5: case 6: case 8: case 21: case 22: case 71: case 72: case 247: return q >= 2;   // names, OpLine, int and float widths, decorations' literals, OpSelectionMerge
    case 43: case 50: case 62: case 246: case 251: return q >= 3;   // constants' values, OpStore's memory operands, OpLoopMerge's control, OpSwitch's cases
    case 61: case 81: return q >= 4;   // OpLoad's memory operands, OpCompositeExtract's indexes
    case 79: case 82: return q >= 5;   // OpVectorShuffle's components, OpCompositeInsert's indexes
    case 12: return q == 4;   // OpExtInst's instruction
    case 23: case 24: case 32: case 54: case 59: return q == (op == 32 ? 2u : 3u);   // component counts, a pointer's storage class, function control, a variable's storage class
    case 25: return q >= 3;
    default: return 0;
    }
}

// The rewrite. sc: 3 * bound words of scratch. → words written to out (0: left as it is; *why says why, 0 when it has no pointers to rewrite)
static size_t spv_noptr(const uint32_t *w, size_t n, uint32_t *sc, uint32_t *out, size_t cap, int *why) {
    *why = 0;
    if (n < 5 || w[0] != 0x07230203) { *why = SPV_NOPTR_FORM; return 0; }
    uint32_t bound = w[3], ver = w[1];
    uint32_t *def = sc, *fl = sc + bound, *nid = sc + 2 * (size_t)bound;   // def: the instruction defining an id; fl: 1 a pointer to rewrite, 2 a bitcast that goes, 4 a pointer type
    for (size_t i = 0; i < 3 * (size_t)bound; i++) sc[i] = 0;                // that goes; nid: a pointer's slot id (its word index is that id + 2)
    uint32_t tu = 0, tl = 0, have = 0;   // the 32-bit unsigned int type, the 64-bit one; have: 1, 2, 4 the descriptor indexing capabilities, 8 its extension, 16 the storage
    int n64 = 0, nconv = 0;              // buffer class's; n64: 64-bit int types
    size_t i_ty = 0, i_fn = 0;           // the first type and the first function
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) { *why = SPV_NOPTR_FORM; return 0; }
        const uint32_t *x = w + i;
        if (!i_ty && !spv_noptr_pre(op)) i_ty = i;
        if (op == 54 && !i_fn) i_fn = i;
        if (op == 39) { *why = SPV_NOPTR_USE; return 0; }   // a forward pointer: a pointer kept in a structure
        if (op >= 19 && op <= 38) { if (len >= 2 && x[1] < bound) def[x[1]] = (uint32_t)i; }
        else if (spv_noptr_typed(op) && len >= 3 && x[2] < bound) def[x[2]] = (uint32_t)i;
        if (op == 21 && len == 4 && x[2] == 64) n64++;
        if (op == 21 && len == 4 && x[3] == 0) { if (x[2] == 32 && !tu) tu = x[1]; if (x[2] == 64 && !tl) tl = x[1]; }
        if (op == 32 && len == 4 && x[2] == 5349 && x[1] < bound) fl[x[1]] |= 4;
        if (op == 17 && len == 2) have |= x[1] == 5302 ? 1u : x[1] == 5301 ? 2u : x[1] == 5308 ? 4u : 0u;
        if (op == 10) have |= spv_noptr_str(x + 1, len - 1, "SPV_EXT_descriptor_indexing") ? 8u : spv_noptr_str(x + 1, len - 1, "SPV_KHR_storage_buffer_storage_class") ? 16u : 0u;
        if (op == 120) nconv++;
        i += len; }
    if (!nconv) return 0;
    if (!tu || !tl || !i_ty || !i_fn || bound < 2) { *why = SPV_NOPTR_FORM; return 0; }
    // each conversion: a pointer type's, of a bitcast to ulong of a v2uint; its pointee 32-bit words (an int or float, or a vector of them)
    for (size_t i = i_fn; i < n; i += w[i] >> 16) { const uint32_t *x = w + i; if ((x[0] & 0xffff) != 120) continue;
        if ((x[0] >> 16) != 4 || x[1] >= bound || x[2] >= bound || x[3] >= bound || !(fl[x[1]] & 4)) { *why = SPV_NOPTR_FORM; return 0; }
        uint32_t bc = def[x[3]];
        if (!bc || (w[bc] & 0xffff) != 124 || (w[bc] >> 16) != 4 || w[bc + 1] != tl || w[bc + 3] >= bound) { *why = SPV_NOPTR_FORM; return 0; }
        uint32_t vd = def[w[bc + 3]], vt = vd ? w[vd + 1] : 0;
        if (!vt || vt >= bound || !def[vt] || (w[def[vt]] & 0xffff) != 23 || w[def[vt] + 2] != tu || w[def[vt] + 3] != 2) { *why = SPV_NOPTR_FORM; return 0; }
        uint32_t T = w[def[x[1]] + 3], ct = T; const uint32_t *td = T < bound && def[T] ? w + def[T] : 0;
        if (td && (td[0] & 0xffff) == 23) { if (td[3] < 2 || td[3] > 4) td = 0; else { ct = td[2]; td = ct < bound && def[ct] ? w + def[ct] : 0; } }
        if (!td || ((td[0] & 0xffff) != 21 && (td[0] & 0xffff) != 22) || td[2] != 32) { *why = SPV_NOPTR_TYPE; return 0; }
        fl[x[2]] |= 1; fl[x[3]] |= 2;
    }
    // every use of a pointer is a load's, a store's or an atomic's pointer; of a bitcast that goes, a conversion's operand; of a pointer type that goes, a conversion's type.
    // Int64 stays when anything else names the ulong type (or another 64-bit int type is declared)
    int keep64 = 0;
    for (size_t i = 5; i < n; i += w[i] >> 16) { const uint32_t *x = w + i; uint32_t len = x[0] >> 16, op = x[0] & 0xffff;
        int goes = (op == 21 && x[1] == tl) || (op == 124 && x[2] < bound && (fl[x[2]] & 2)) || (op == 32 && x[1] < bound && (fl[x[1]] & 4)) || op == 5 || op == 6 || op == 71 || op == 72;
        for (uint32_t q = 1; q < len; q++) { if (spv_noptr_lit(op, q)) continue; uint32_t id = x[q];
            if (id == tl && !goes) keep64 = 1;
            if (id >= bound || !fl[id]) continue;
            if ((op == 32 && q == 1) || ((op == 120 || op == 124) && q == 2) || ((op == 5 || op == 6 || op == 71 || op == 72) && q == 1)) continue;   // its definition, names, decorations
            int ok = ((fl[id] & 1) && ((op == 61 && q == 3) || (op == 62 && q == 1) || (spv_noptr_atomic(op) && q == (op == 228 ? 1u : 3u))))
                  || ((fl[id] & 2) && op == 120 && q == 3) || ((fl[id] & 4) && op == 120 && q == 1);
            if (!ok) { *why = SPV_NOPTR_USE; return 0; } }
    }
    for (size_t i = i_fn; i < n; i += w[i] >> 16) { const uint32_t *x = w + i; uint32_t op = x[0] & 0xffff;   // an atomic only on uint words (an int one would want a pointer to int)
        uint32_t pp = op == 228 ? x[1] : spv_noptr_atomic(op) ? x[3] : 0;
        if (pp && pp < bound && (fl[pp] & 1) && w[def[w[def[pp] + 1]] + 3] != tu) { *why = SPV_NOPTR_TYPE; return 0; } }
    int drop_tl = !keep64, drop64 = drop_tl && n64 == 1;
    uint32_t nb = bound;
    const uint32_t rta = nb++, blk = nb++, rtb = nb++, prtb = nb++, pu = nb++, var = nb++, c0 = nb++, c1 = nb++, c2 = nb++, c3 = nb++;
    size_t k = 0, ann = 0; uint32_t nnu = 0;   // ann: where the NonUniform decorations go; they are listed at the top of out meanwhile, out[cap - 1 - j]
#define NP_E(v) do { if (k + nnu >= cap) { *why = SPV_NOPTR_ROOM; return 0; } out[k++] = (uint32_t)(v); } while (0)
#define NP_NU(id) do { if (k + nnu + 1 >= cap) { *why = SPV_NOPTR_ROOM; return 0; } out[cap - 1 - nnu++] = (id); } while (0)
#define NP_ROOM(m) do { if (k + nnu + (m) >= cap) { *why = SPV_NOPTR_ROOM; return 0; } } while (0)
    for (int q = 0; q < 5; q++) NP_E(w[q]);
    int caps_done = 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; const uint32_t *x = w + i;
        if (!caps_done && op != 17) {   // after the capabilities: descriptor indexing's, and the extensions this SPIR-V version needs for them
            if (!(have & 1)) { NP_E(2u << 16 | 17); NP_E(5302); }   // RuntimeDescriptorArray
            if (!(have & 2)) { NP_E(2u << 16 | 17); NP_E(5301); }   // ShaderNonUniform
            if (!(have & 4)) { NP_E(2u << 16 | 17); NP_E(5308); }   // StorageBufferArrayNonUniformIndexing
            NP_ROOM(32);
            if (ver < 0x10500 && !(have & 8)) k += spv_noptr_put_str(out, k, 10, "SPV_EXT_descriptor_indexing");
            if (ver < 0x10300 && !(have & 16)) k += spv_noptr_put_str(out, k, 10, "SPV_KHR_storage_buffer_storage_class");
            caps_done = 1; }
        if (i == i_ty) {   // the array's decorations (the NonUniform ones are put here at the end)
            NP_E(4u << 16 | 71); NP_E(rta); NP_E(6); NP_E(4);   // ArrayStride 4
            NP_E(5u << 16 | 72); NP_E(blk); NP_E(0); NP_E(35); NP_E(0);   // member 0 Offset 0
            NP_E(3u << 16 | 71); NP_E(blk); NP_E(2);   // Block
            NP_E(4u << 16 | 71); NP_E(var); NP_E(34); NP_E(SPV_NOPTR_SET);   // DescriptorSet
            NP_E(4u << 16 | 71); NP_E(var); NP_E(33); NP_E(SPV_NOPTR_BINDING);   // Binding
            ann = k; }
        if (i == i_fn) {   // its types, the constants the accesses take and the variable
            NP_E(3u << 16 | 29); NP_E(rta); NP_E(tu);   // uint[]
            NP_E(3u << 16 | 30); NP_E(blk); NP_E(rta);   // struct { uint d[]; }
            NP_E(3u << 16 | 29); NP_E(rtb); NP_E(blk);   // pools[]
            NP_E(4u << 16 | 32); NP_E(prtb); NP_E(12); NP_E(rtb);   // StorageBuffer pointers
            NP_E(4u << 16 | 32); NP_E(pu); NP_E(12); NP_E(tu);
            const uint32_t cs[4] = {c0, c1, c2, c3};
            for (uint32_t q = 0; q < 4; q++) { NP_E(4u << 16 | 43); NP_E(tu); NP_E(cs[q]); NP_E(q); }
            NP_E(4u << 16 | 59); NP_E(prtb); NP_E(var); NP_E(12); }
        // what goes: the capability (and Int64 when nothing else needs it), the extension, the pointer types, the ulong type unless used, the bitcasts, their names and decorations
        if (op == 17 && len == 2 && (x[1] == 5347 || (x[1] == 11 && drop64))) { i += len; continue; }
        if (op == 10 && spv_noptr_str(x + 1, len - 1, "SPV_KHR_physical_storage_buffer")) { i += len; continue; }
        if (op == 32 && len == 4 && x[1] < bound && (fl[x[1]] & 4)) { i += len; continue; }
        if (op == 21 && x[1] == tl && drop_tl) { i += len; continue; }
        if (op == 124 && len >= 3 && x[2] < bound && (fl[x[2]] & 2)) { i += len; continue; }
        if ((op == 5 || op == 6 || op == 71 || op == 72) && len >= 2 && ((x[1] < bound && fl[x[1]]) || (x[1] == tl && drop_tl))) { i += len; continue; }
        if (op == 14 && len == 3) { NP_E(w[i]); NP_E(x[1] == 5348 ? 0u : x[1]); NP_E(x[2]); i += len; continue; }   // OpMemoryModel: Logical addressing
        if (op == 15 && ver >= 0x10400) { NP_E((len + 1) << 16 | 15); for (uint32_t q = 1; q < len; q++) NP_E(x[q]); NP_E(var); i += len; continue; }   // the variable in the interface
        if (op == 120) {   // the conversion: the address vector's high word is the slot (NonUniform), its low word >> 2 the word in the piece
            uint32_t v = w[def[x[3]] + 3], idx = nb, off = nb + 1, wi = nb + 2; nb += 3; nid[x[2]] = idx;
            NP_E(5u << 16 | 81); NP_E(tu); NP_E(idx); NP_E(v); NP_E(1);   // OpCompositeExtract
            NP_E(5u << 16 | 81); NP_E(tu); NP_E(off); NP_E(v); NP_E(0);
            NP_E(5u << 16 | 194); NP_E(tu); NP_E(wi); NP_E(off); NP_E(c2);   // OpShiftRightLogical
            NP_NU(idx);
            i += len; continue; }
        uint32_t pp = op == 61 && len >= 4 ? x[3] : op == 62 && len >= 3 ? x[1] : op == 228 ? x[1] : spv_noptr_atomic(op) && len >= 4 ? x[3] : 0;
        if (pp && pp < bound && (fl[pp] & 1)) {   // a load, store or atomic through it: an access per 32-bit component
            uint32_t T = w[def[w[def[pp] + 1]] + 3], idx = nid[pp], wi = idx + 2; const uint32_t *td = w + def[T];
            int isv = (td[0] & 0xffff) == 23; uint32_t nc = isv ? td[3] : 1, ct = isv ? td[2] : T, comp[4] = {0, 0, 0, 0};
            for (uint32_t j = 0; j < nc; j++) {
                uint32_t wj = wi;
                if (j) { wj = nb++; NP_E(5u << 16 | 128); NP_E(tu); NP_E(wj); NP_E(wi); NP_E(j == 1 ? c1 : j == 2 ? c2 : c3); }   // OpIAdd
                uint32_t ac = nb++;
                NP_E(7u << 16 | 65); NP_E(pu); NP_E(ac); NP_E(var); NP_E(idx); NP_E(c0); NP_E(wj);   // OpAccessChain pools[idx].d[wj]
                NP_NU(ac);
                if (op == 61) {   // the word, then as the component's type
                    uint32_t ld = !isv && ct == tu ? x[2] : nb++;
                    NP_E(4u << 16 | 61); NP_E(tu); NP_E(ld); NP_E(ac);
                    comp[j] = ld;
                    if (ct != tu) { comp[j] = isv ? nb++ : x[2]; NP_E(4u << 16 | 124); NP_E(ct); NP_E(comp[j]); NP_E(ld); }
                } else if (op == 62) {   // the component, as a word
                    uint32_t c = x[2];
                    if (isv) { c = nb++; NP_E(5u << 16 | 81); NP_E(ct); NP_E(c); NP_E(x[2]); NP_E(j); }
                    if (ct != tu) { uint32_t b = nb++; NP_E(4u << 16 | 124); NP_E(tu); NP_E(b); NP_E(c); c = b; }
                    NP_E(3u << 16 | 62); NP_E(ac); NP_E(c);
                } else {   // the atomic itself on the access (on uint words only: checked above)
                    NP_ROOM(len); out[k++] = w[i]; for (uint32_t q = 1; q < len; q++) out[k++] = q == (op == 228 ? 1u : 3u) ? ac : x[q];
                }
            }
            if (op == 61 && isv) { NP_E((3 + nc) << 16 | 80); NP_E(T); NP_E(x[2]); for (uint32_t j = 0; j < nc; j++) NP_E(comp[j]); }   // the vector of them
            i += len; continue; }
        NP_ROOM(len); for (uint32_t q = 0; q < len; q++) out[k++] = w[i + q];
        i += len; }
    // the NonUniform decorations, at the end of the annotations
    size_t add = 3 * (size_t)nnu;
    if (!ann || k + add + nnu > cap) { *why = SPV_NOPTR_ROOM; return 0; }
    for (size_t q = k; q > ann; q--) out[q - 1 + add] = out[q - 1];
    for (uint32_t q = 0; q < nnu; q++) { out[ann + 3 * q] = 3u << 16 | 71; out[ann + 3 * q + 1] = out[cap - 1 - q]; out[ann + 3 * q + 2] = 5300; }   // NonUniform
    k += add;
    out[3] = nb;
#undef NP_E
#undef NP_NU
#undef NP_ROOM
    return k;
}
