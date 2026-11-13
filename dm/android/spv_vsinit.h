// Every vertex shader output starts as (0,0,0,1) before the translated body runs: on the hardware that is what an unwritten component reads, and the Mac's
// shaders get the same from dmsh_build.py vs_init. Vulkan leaves an output component the shader never writes undefined, and the Adreno 840 (Galaxy Z Fold 8)
// and the Mali-G715 (Pixel 9 Pro XL) read it as 0. Pokémon Legends: Arceus's full-screen vertex shaders write only x and y of their location 0 output, and its
// pixel shaders divide by w: a sky-light term came out NaN (239ba1a5a4270b1c, a 64x64 six-layer target) and the screen-space shadow mask fully lit
// (3be95ee5087724c5), so every outdoor scene was overexposed and shadowless (droidplay-core#310's follow-up). Link's Awakening cast no sun shadow on Android
// for the same reason (its Mac fault, which vs_init fixed in the MSL). spv_vsinit stores a vec4 constant (0,0,0,1) to each 32-bit float vec4 output with a
// Location (not a built-in) at the start of the vertex entry point's first block, after its local variables; components the body writes are overwritten as
// before. A module that is not a vertex shader, or has no such output, is left alone. Self-contained (no libc) for dm/tools/tests/test_spv_vsinit.py.
#pragma once
#include <stddef.h>
#include <stdint.h>

#define SPV_VSINIT_MAX 32u   // outputs initialized at most (the translator writes up to 32 attribute outputs)

// whether the module has a vertex entry point (the replay's pre-check: the entry points come right after the capabilities, extensions and memory model)
static int spv_vsinit_wanted(const uint32_t *w, size_t n) {
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        if (op == 15 && len >= 3) return w[i + 1] == 0;   // OpEntryPoint: execution model Vertex
        if (op != 17 && op != 10 && op != 11 && op != 14) return 0;   // past the capabilities, extensions, imports and the memory model
        i += len; }
    return 0;
}

// The module rewritten into o (cap words) → its length; 0 when nothing is done: not a vertex shader, no float vec4 output with a Location, more than one entry
// point, a malformed module, or o too small (it needs n + 15 + 3 * outputs words). scratch: 2 * bound bytes, as a byte per id (the caller's or o's tail is not used)
static size_t spv_vsinit(const uint32_t *w, size_t n, uint8_t *scratch, uint32_t *o, size_t cap) {
    if (n < 5 || w[0] != 0x07230203u) return 0;
    uint32_t bound = w[3]; uint8_t *loc = scratch, *ptr = scratch + bound;   // loc: 1 Location, 2 BuiltIn; ptr: 1 an Output pointer to the float vec4
    for (uint32_t k = 0; k < 2 * bound; k++) scratch[k] = 0;
    uint32_t entry = 0, nentry = 0, tf = 0, v4 = 0, outs[SPV_VSINIT_MAX], nout = 0;
    size_t first_fn = 0, at = 0;   // where the constants go (the first OpFunction) and the stores (in the entry point's first block, after its OpVariables)
    int in_entry = 0, in_fn = 0, seen_label = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        const uint32_t *a = w + i + 1;
        if (op == 15 && len >= 3) { nentry++; if (a[0] != 0) return 0; entry = a[1]; }   // OpEntryPoint: Vertex only
        else if (op == 71 && len >= 3 && a[0] < bound) { if (a[1] == 30) loc[a[0]] |= 1; else if (a[1] == 11) loc[a[0]] |= 2; }   // OpDecorate Location / BuiltIn
        else if (op == 22 && len == 3 && a[1] == 32 && !tf) tf = a[0];   // OpTypeFloat 32
        else if (op == 23 && len == 4 && tf && a[1] == tf && a[2] == 4 && !v4) v4 = a[0];   // OpTypeVector float 4
        else if (op == 32 && len == 4 && a[1] == 3 && v4 && a[2] == v4 && a[0] < bound) ptr[a[0]] = 1;   // OpTypePointer Output float vec4
        else if (op == 59 && len >= 4 && !in_fn && a[2] == 3 && a[0] < bound && ptr[a[0]] && a[1] < bound && loc[a[1]] == 1) {   // OpVariable Output with a Location
            if (nout == SPV_VSINIT_MAX) return 0;
            outs[nout++] = a[1];
        } else if (op == 54 && len >= 5) {   // OpFunction
            if (!first_fn) first_fn = i;
            in_fn = 1; in_entry = a[1] == entry; seen_label = 0;
        } else if (op == 56) { in_fn = 0; in_entry = 0; }   // OpFunctionEnd
        else if (in_entry && op == 248 && !seen_label) { seen_label = 1; at = i + len; }   // the first OpLabel
        else if (in_entry && seen_label && at == i && op == 59) at = i + len;   // the block's leading OpVariables stay first
        i += len;
    }
    if (nentry != 1 || !entry || !nout || !first_fn || !at || !tf || !v4 || bound > 0x3ffffff0u) return 0;
    size_t need = n + 4 + 4 + 7 + 3 * (size_t)nout; if (need > cap) return 0;
    uint32_t c0 = bound, c1 = bound + 1, cv = bound + 2;
    size_t k = 0;
    for (size_t i = 0; i < n; i++) {
        if (i == first_fn) {   // OpConstant float 0.0, 1.0; OpConstantComposite vec4 (0, 0, 0, 1)
            o[k++] = 4u << 16 | 43; o[k++] = tf; o[k++] = c0; o[k++] = 0;
            o[k++] = 4u << 16 | 43; o[k++] = tf; o[k++] = c1; o[k++] = 0x3f800000u;
            o[k++] = 7u << 16 | 44; o[k++] = v4; o[k++] = cv; o[k++] = c0; o[k++] = c0; o[k++] = c0; o[k++] = c1;
        }
        if (i == at) for (uint32_t q = 0; q < nout; q++) { o[k++] = 3u << 16 | 62; o[k++] = outs[q]; o[k++] = cv; }   // OpStore
        o[k++] = w[i];
    }
    o[3] = bound + 3;
    return k;
}
