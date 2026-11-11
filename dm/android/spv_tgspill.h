// Compute shared memory past the GPU's limit, moved into a storage buffer. Maxwell gives a workgroup up to 48 KB of shared memory (an Ampere GPU up to 100 KB), and the
// translator declares it as Workgroup arrays of 32-bit words of their full size. A Vulkan device takes at most maxComputeSharedMemorySize bytes a module: 32 KB on
// Qualcomm's Adreno 830 driver (0x80320001). Mario Kart World's 168 DrivePassShaderDefault kernels declare 48 KB (shared uint[12288]); Qualcomm's compiler takes them,
// and one dispatch of 2a89b6d4df731b8d (a 24-bone skeleton's animation, one workgroup) ran in 0.2 ms alone, but in the game the dispatch never ended: three
// submissions cut short by the driver's hang recovery, then the device lost. Turnip and Samsung's Xclipse driver run the same module. spv_tgspill gives each Workgroup
// array a place in one storage buffer instead, the Mac's tg_spill (dmsh_build.py) for Vulkan: one region per workgroup, at the workgroup's index in the dispatch's
// grid (WorkgroupId and NumWorkgroups, computed once at the start of the entry point into a Private variable, so other functions take it too) times the words of
// all the module's arrays, each array at its own offset in it. Every access chain on an array becomes one on the buffer; barriers and atomics with Workgroup
// memory semantics take UniformMemory too, so they order the buffer's writes as they did the shared memory's. The replay binds a slice of its arena at
// SPV_TGS_BINDING for every dispatch, its size the groups times spv_tgs_bytes. Only arrays of 32-bit integers or floats, all of one type, used only through access
// chains of one index whose pointers are only loaded, stored or used by atomics, are rewritten; any other module is left as it is (spv_tgs_bytes says why).
// Self-contained (no libc) for dm/tools/tests/test_spv_tgspill.py.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include "spv_lit.h"

enum { SPV_TGS_BINDING = 110 };   // after the capture variant's feedback buffers (100-103)
enum { SPV_TGS_NONE = 0, SPV_TGS_TYPE = -1, SPV_TGS_USE = -2, SPV_TGS_FORM = -3 };   // spv_tgs_bytes when it can't: no Workgroup storage; another type; another use; the module

// The per-id tables in sc (4 * bound words): the defining opcode, two operands, a flag (1: a Workgroup array, 2: a pointer into one)
typedef struct { uint32_t *op, *a, *b, *fl; uint32_t bound; } spv_tgs_t;
static void spv_tgs_tables(const uint32_t *w, size_t n, uint32_t *sc, spv_tgs_t *t) {
    t->bound = w[3]; t->op = sc; t->a = sc + t->bound; t->b = sc + 2 * (size_t)t->bound; t->fl = sc + 3 * (size_t)t->bound;
    for (uint32_t i = 0; i < 4 * t->bound; i++) sc[i] = 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return;
        uint32_t r = 0, a = 0, b = 0;
        if ((op == 21 || op == 22) && len >= 3) { r = w[i + 1]; a = w[i + 2]; b = op == 21 && len >= 4 ? w[i + 3] : 0; }   // OpTypeInt width sign / OpTypeFloat width
        else if (op == 23 && len == 4) { r = w[i + 1]; a = w[i + 2]; b = w[i + 3]; }   // OpTypeVector component count
        else if (op == 28 && len == 4) { r = w[i + 1]; a = w[i + 2]; b = w[i + 3]; }   // OpTypeArray element length
        else if (op == 32 && len == 4) { r = w[i + 1]; a = w[i + 2]; b = w[i + 3]; }   // OpTypePointer class pointee
        else if (op == 43 && len == 4) { r = w[i + 2]; a = w[i + 1]; b = w[i + 3]; }   // OpConstant type value (32-bit)
        else if (op == 59 && len >= 4) { r = w[i + 2]; a = w[i + 1]; b = w[i + 3]; }   // OpVariable type class
        else if ((op == 65 || op == 66) && len >= 4) { r = w[i + 2]; a = w[i + 3]; b = len; }   // OpAccessChain / OpInBoundsAccessChain base, its length
        if (r && r < t->bound) { t->op[r] = op; t->a[r] = a; t->b[r] = b; }
        i += len; }
}
// the element type of the Workgroup array variable v, 0 when it is not an array of a 32-bit integer or float
static uint32_t spv_tgs_elem(const spv_tgs_t *t, uint32_t v, uint32_t *len) {
    uint32_t p = t->a[v]; if (p >= t->bound || t->op[p] != 32) return 0;
    uint32_t arr = t->b[p]; if (arr >= t->bound || t->op[arr] != 28) return 0;
    uint32_t e = t->a[arr], lc = t->b[arr]; if (e >= t->bound || lc >= t->bound || t->op[lc] != 43) return 0;
    if (!((t->op[e] == 21 || t->op[e] == 22) && t->a[e] == 32)) return 0;
    *len = t->b[lc]; return e;
}

// Bytes of Workgroup storage the module declares, if spv_tgspill can move it all (0: none), else SPV_TGS_TYPE / SPV_TGS_USE / SPV_TGS_FORM
static long long spv_tgs_bytes(const uint32_t *w, size_t n, uint32_t *sc) {
    if (n < 5 || w[0] != 0x07230203 || !w[3]) return SPV_TGS_FORM;
    spv_tgs_t t; spv_tgs_tables(w, n, sc, &t);
    long long bytes = 0; uint32_t elem = 0; int any = 0;
    for (uint32_t v = 1; v < t.bound; v++) {
        if (t.op[v] != 59 || t.b[v] != 4) continue;   // OpVariable Workgroup
        uint32_t len = 0, e = spv_tgs_elem(&t, v, &len); if (!e || !len) return SPV_TGS_TYPE;
        if (elem && e != elem) return SPV_TGS_TYPE;   // one element type for the buffer's runtime array
        elem = e; bytes += 4LL * len; t.fl[v] = 1; any = 1;
    }
    if (!any) return SPV_TGS_NONE;
    if (w[1] < 0x00010300) return SPV_TGS_FORM;   // StorageBuffer storage class: core from SPIR-V 1.3
    for (uint32_t v = 1; v < t.bound; v++) if (t.fl[v] == 0 && (t.op[v] == 65 || t.op[v] == 66) && t.a[v] < t.bound && t.fl[t.a[v]] == 1) { if (t.b[v] != 5) return SPV_TGS_USE; t.fl[v] = 2; }
    // every other use: an id operand of an instruction (spv_lit: not a literal) that is a Workgroup array or a pointer into one, in a place the rewrite does not take
    int fn = 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return SPV_TGS_FORM;
        if (op == 54) fn = 1;
        if (op == 5 || op == 6 || op == 71 || op == 72 || op == 15 || op == 16) { i += len; continue; }   // names, decorations, entry points, execution modes
        if (fn) for (uint32_t q = 1; q < len; q++) {
            uint32_t id = w[i + q]; if (id >= t.bound || !t.fl[id] || spv_lit(op, q)) continue;
            if (t.fl[id] == 1 && (op == 65 || op == 66) && q == 3) continue;   // the access chain's base
            if (t.fl[id] == 1 && op == 59 && q == 2) continue;
            if (t.fl[id] == 2 && ((op == 61 && q == 3) || (op == 62 && q == 1) || (op == 228 && q == 1) || ((op == 227 || (op >= 229 && op <= 242)) && q == 3))) continue;   // load, store, atomics
            if (t.fl[id] == 2 && (op == 65 || op == 66) && q == 2) continue;   // its own definition
            return SPV_TGS_USE;
        }
        i += len; }
    return bytes;
}

// The module with its Workgroup arrays in a storage buffer at binding (descriptor set 0), in out (cap words): its word count, 0 when spv_tgs_bytes says it can't or
// out is too small. sc: 4 * bound words. Mark Workgroup storage as Workgroup arrays read by spv_tgs_bytes first (it fills the tables)
static size_t spv_tgspill(const uint32_t *w, size_t n, uint32_t binding, uint32_t *sc, uint32_t *out, size_t cap) {
    long long bytes = spv_tgs_bytes(w, n, sc); if (bytes <= 0) return 0;
    spv_tgs_t t; t.bound = w[3]; t.op = sc; t.a = sc + t.bound; t.b = sc + 2 * (size_t)t.bound; t.fl = sc + 3 * (size_t)t.bound;   // as spv_tgs_bytes left them
    uint32_t elem = 0, words = (uint32_t)(bytes / 4);
    // what the module has already: a 32-bit unsigned integer type, a vector of three of it, an Input pointer to that, the WorkgroupId and NumWorkgroups variables
    uint32_t tu = 0, tv3 = 0, tpi = 0, vwid = 0, vnwg = 0, ep = 0;
    for (uint32_t v = 1; v < t.bound; v++) {
        if (t.op[v] == 21 && t.a[v] == 32 && t.b[v] == 0 && !tu) tu = v;
        if (t.fl[v] == 1 && !elem) { uint32_t l; elem = spv_tgs_elem(&t, v, &l); }
    }
    for (uint32_t v = 1; v < t.bound; v++) if (t.op[v] == 23 && t.a[v] == tu && t.b[v] == 3 && tu && !tv3) tv3 = v;
    for (uint32_t v = 1; v < t.bound; v++) if (t.op[v] == 32 && t.a[v] == 1 && t.b[v] == tv3 && tv3 && !tpi) tpi = v;
    size_t i_ann_end = 0, i_fn = 0, i_ep = 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (op == 15 && len >= 4 && w[i + 1] == 5 && !ep) { ep = w[i + 2]; i_ep = i; }   // OpEntryPoint GLCompute
        if (op == 71 && len == 4 && w[i + 2] == 11 && w[i + 1] < t.bound) { if (w[i + 3] == 26) vwid = w[i + 1]; if (w[i + 3] == 24) vnwg = w[i + 1]; }   // BuiltIn WorkgroupId / NumWorkgroups
        if (!i_ann_end && ((op >= 19 && op <= 39) || (op >= 41 && op <= 52) || op == 59 || op == 1)) i_ann_end = i;   // the first type, constant, global variable or undef
        if (op == 54 && !i_fn) i_fn = i;
        i += len; }
    if (!ep || !i_ann_end || !i_fn) return 0;
    if (vwid && (t.op[vwid] != 59 || t.a[vwid] != tpi || !tpi)) return 0;   // an existing WorkgroupId of another type (not uvec3): not rewritten
    if (vnwg && (t.op[vnwg] != 59 || t.a[vnwg] != tpi || !tpi)) return 0;
    uint32_t nb = t.bound;
    uint32_t nu = tu ? tu : nb++, nv3 = tv3 ? tv3 : nb++, npi = tpi ? tpi : nb++, nwid = vwid ? vwid : nb++, nnwg = vnwg ? vnwg : nb++;
    uint32_t rta = nb++, blk = nb++, pblk = nb++, pel = nb++, ppu = nb++, spill = nb++, base = nb++, c0 = nb++, cw = nb++;
    // the memory semantics constants with Workgroup memory, and their value with UniformMemory added: up to 16 kept
    uint32_t sem_old[16], sem_new[16], nsem = 0;
    size_t k = 0;
#define TGS_E(x) do { if (k >= cap) return 0; out[k++] = (uint32_t)(x); } while (0)
    for (int q = 0; q < 5; q++) TGS_E(w[q]);
    int fn = 0, in_main = 0, main_entry_done = 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (i == i_ann_end) {   // the new decorations, after the module's own
            TGS_E(4u << 16 | 71); TGS_E(rta); TGS_E(6); TGS_E(4);   // ArrayStride 4
            TGS_E(5u << 16 | 72); TGS_E(blk); TGS_E(0); TGS_E(35); TGS_E(0);   // member 0 Offset 0
            TGS_E(3u << 16 | 71); TGS_E(blk); TGS_E(2);   // Block
            TGS_E(4u << 16 | 71); TGS_E(spill); TGS_E(34); TGS_E(0);   // DescriptorSet 0
            TGS_E(4u << 16 | 71); TGS_E(spill); TGS_E(33); TGS_E(binding);   // Binding
            if (!vwid) { TGS_E(4u << 16 | 71); TGS_E(nwid); TGS_E(11); TGS_E(26); }
            if (!vnwg) { TGS_E(4u << 16 | 71); TGS_E(nnwg); TGS_E(11); TGS_E(24); }
        }
        if (i == i_fn) {   // the new types, constants and variables, after the module's own
            if (!tu) { TGS_E(4u << 16 | 21); TGS_E(nu); TGS_E(32); TGS_E(0); }
            if (!tv3) { TGS_E(4u << 16 | 23); TGS_E(nv3); TGS_E(nu); TGS_E(3); }
            if (!tpi) { TGS_E(4u << 16 | 32); TGS_E(npi); TGS_E(1); TGS_E(nv3); }
            TGS_E(3u << 16 | 29); TGS_E(rta); TGS_E(elem);   // OpTypeRuntimeArray
            TGS_E(3u << 16 | 30); TGS_E(blk); TGS_E(rta);   // OpTypeStruct
            TGS_E(4u << 16 | 32); TGS_E(pblk); TGS_E(12); TGS_E(blk);   // StorageBuffer pointer to the block
            TGS_E(4u << 16 | 32); TGS_E(pel); TGS_E(12); TGS_E(elem);   // and to an element
            TGS_E(4u << 16 | 32); TGS_E(ppu); TGS_E(6); TGS_E(nu);   // Private pointer to a uint
            TGS_E(4u << 16 | 43); TGS_E(nu); TGS_E(c0); TGS_E(0);
            TGS_E(4u << 16 | 43); TGS_E(nu); TGS_E(cw); TGS_E(words);
            // every Workgroup array's offset, and the semantics constants: made here, before the functions (their ids from nb)
            for (uint32_t v = 1, off = 0; v < t.bound; v++) if (t.fl[v] == 1) { uint32_t l; spv_tgs_elem(&t, v, &l); t.b[v] = off ? nb : 0; if (off) { TGS_E(4u << 16 | 43); TGS_E(nu); TGS_E(nb); TGS_E(off); nb++; } off += l; }
            for (size_t j = i_fn; j < n; ) { uint32_t lj = w[j] >> 16, oj = w[j] & 0xffff; if (!lj || j + lj > n) return 0;
                uint32_t s[2] = {0, 0}; int ns = 0;
                if (oj == 224 && lj == 4) s[ns++] = w[j + 3];
                else if (oj == 225 && lj == 3) s[ns++] = w[j + 2];
                else if (oj == 228 && lj >= 4 && w[j + 1] < t.bound && t.fl[w[j + 1]] == 2) s[ns++] = w[j + 3];
                else if ((oj == 227 || (oj >= 229 && oj <= 242)) && lj >= 6 && w[j + 3] < t.bound && t.fl[w[j + 3]] == 2) { s[ns++] = w[j + 5]; if ((oj == 230 || oj == 231) && lj >= 7) s[ns++] = w[j + 6]; }
                for (int q = 0; q < ns; q++) { uint32_t c = s[q]; if (c >= t.bound || t.op[c] != 43 || !(t.b[c] & 0x100) || (t.b[c] & 0x40)) continue;
                    uint32_t z = 0; while (z < nsem && sem_old[z] != c) z++;
                    if (z == nsem) { if (nsem == 16) return 0; sem_old[nsem] = c; sem_new[nsem] = nb; nsem++; TGS_E(4u << 16 | 43); TGS_E(t.a[c]); TGS_E(nb); TGS_E(t.b[c] | 0x40); nb++; } }
                j += lj; }
            TGS_E(4u << 16 | 59); TGS_E(pblk); TGS_E(spill); TGS_E(12);   // the buffer
            TGS_E(4u << 16 | 59); TGS_E(ppu); TGS_E(base); TGS_E(6);   // the workgroup's first word, Private
            if (!vwid) { TGS_E(4u << 16 | 59); TGS_E(npi); TGS_E(nwid); TGS_E(1); }
            if (!vnwg) { TGS_E(4u << 16 | 59); TGS_E(npi); TGS_E(nnwg); TGS_E(1); }
        }
        if (op == 54) { fn = 1; in_main = w[i + 2] == ep; main_entry_done = 0; }
        // the entry point's first block, past its variables: the workgroup's first word into base
        if (fn && in_main && !main_entry_done && op != 54 && op != 55 && op != 248 && op != 59 && op != 8 && op != 317) {
            uint32_t a = nb++, b2 = nb++, x = nb++, y = nb++, z = nb++, nx = nb++, ny = nb++, m1 = nb++, s1 = nb++, m2 = nb++, s2 = nb++, f = nb++;
            TGS_E(4u << 16 | 61); TGS_E(nv3); TGS_E(a); TGS_E(nwid);   // OpLoad WorkgroupId
            TGS_E(4u << 16 | 61); TGS_E(nv3); TGS_E(b2); TGS_E(nnwg);   // OpLoad NumWorkgroups
            TGS_E(5u << 16 | 81); TGS_E(nu); TGS_E(x); TGS_E(a); TGS_E(0);
            TGS_E(5u << 16 | 81); TGS_E(nu); TGS_E(y); TGS_E(a); TGS_E(1);
            TGS_E(5u << 16 | 81); TGS_E(nu); TGS_E(z); TGS_E(a); TGS_E(2);
            TGS_E(5u << 16 | 81); TGS_E(nu); TGS_E(nx); TGS_E(b2); TGS_E(0);
            TGS_E(5u << 16 | 81); TGS_E(nu); TGS_E(ny); TGS_E(b2); TGS_E(1);
            TGS_E(5u << 16 | 132); TGS_E(nu); TGS_E(m1); TGS_E(ny); TGS_E(z);    // ny * z
            TGS_E(5u << 16 | 128); TGS_E(nu); TGS_E(s1); TGS_E(m1); TGS_E(y);    // + y
            TGS_E(5u << 16 | 132); TGS_E(nu); TGS_E(m2); TGS_E(nx); TGS_E(s1);   // nx * (y + ny z)
            TGS_E(5u << 16 | 128); TGS_E(nu); TGS_E(s2); TGS_E(m2); TGS_E(x);    // + x: the workgroup's index in the grid
            TGS_E(5u << 16 | 132); TGS_E(nu); TGS_E(f); TGS_E(s2); TGS_E(cw);    // times the words of a region
            TGS_E(3u << 16 | 62); TGS_E(base); TGS_E(f);
            main_entry_done = 1;
        }
        // dropped: the Workgroup arrays, their names and decorations
        if (op == 59 && len >= 4 && w[i + 2] < t.bound && t.fl[w[i + 2]] == 1) { i += len; continue; }
        if ((op == 5 || op == 6 || op == 71 || op == 72) && len >= 2 && w[i + 1] < t.bound && t.fl[w[i + 1]] == 1) { i += len; continue; }
        if (op == 15 && i == i_ep) {   // the entry point's interface takes the new Input built-ins, without the arrays (SPIR-V 1.4 lists every global)
            size_t h = k; TGS_E(0);
            uint32_t q0 = 3; while (q0 < len && (w[i + q0] >> 24)) q0++;   // past the name: its last word ends in a zero byte
            q0++;
            for (uint32_t q = 1; q < len; q++) { uint32_t x = w[i + q]; if (q >= q0 && x < t.bound && t.fl[x] == 1) continue; TGS_E(x); }
            if (!vwid) TGS_E(nwid);
            if (!vnwg) TGS_E(nnwg);
            out[h] = (uint32_t)(k - h) << 16 | 15;
            i += len; continue;
        }
        if ((op == 65 || op == 66) && len == 5 && w[i + 3] < t.bound && t.fl[w[i + 3]] == 1) {   // an element of an array: one of the buffer's
            uint32_t r = w[i + 2], idx = w[i + 4], v = w[i + 3], l1 = nb++, a1 = nb++, a2 = t.b[v] ? nb++ : a1;
            TGS_E(4u << 16 | 61); TGS_E(nu); TGS_E(l1); TGS_E(base);
            TGS_E(5u << 16 | 128); TGS_E(nu); TGS_E(a1); TGS_E(l1); TGS_E(idx);
            if (t.b[v]) { TGS_E(5u << 16 | 128); TGS_E(nu); TGS_E(a2); TGS_E(a1); TGS_E(t.b[v]); }
            TGS_E(6u << 16 | 65); TGS_E(pel); TGS_E(r); TGS_E(spill); TGS_E(c0); TGS_E(a2);
            i += len; continue;
        }
        uint32_t at = k;
        for (uint32_t q = 0; q < len; q++) TGS_E(w[i + q]);
        // semantics operands with Workgroup memory: UniformMemory too
        int s1 = -1, s2 = -1;
        if (op == 224 && len == 4) s1 = 3; else if (op == 225 && len == 3) s1 = 2;
        else if (op == 228 && len >= 4 && w[i + 1] < t.bound && t.fl[w[i + 1]] == 2) s1 = 3;
        else if ((op == 227 || (op >= 229 && op <= 242)) && len >= 6 && w[i + 3] < t.bound && t.fl[w[i + 3]] == 2) { s1 = 5; if ((op == 230 || op == 231) && len >= 7) s2 = 6; }
        for (int q = 0; q < 2; q++) { int p = q ? s2 : s1; if (p < 0) continue; for (uint32_t z = 0; z < nsem; z++) if (out[at + p] == sem_old[z]) out[at + p] = sem_new[z]; }
        i += len; }
#undef TGS_E
    out[3] = nb;
    return k;
}
