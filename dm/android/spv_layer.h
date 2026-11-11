// Layer and viewport output from a vertex shader on a GPU that can't take it. Maxwell's vertex (and tessellation) shaders may write the render target layer and the
// viewport index; the translator declares them as BuiltIn Layer and ViewportIndex with the ShaderViewportIndexLayerEXT capability and
// SPV_EXT_shader_viewport_index_layer. Vulkan 1.1 allows that only with VK_EXT_shader_viewport_index_layer (1.2: shaderOutputLayer / shaderOutputViewportIndex).
// The Adreno 730's driver V@0615.98 (a Moto Razr Plus 2023, Vulkan 1.1.128) has neither, and its compiler crashes on such a module (libllvm-qgl.so+0xd8a064,
// addr 0x48), at every boot of Brilliant Diamond, whose 12 vertex shaders that write the layer each crash it in turn. spv_layer makes each of those built-ins an
// ordinary output at a location after the module's highest, which no fragment shader reads, and drops the capability and extension: the draws go to layer 0
// and viewport 0 (a GPU without the extension has no multiViewport either on the phones here). A built-in that is a block member, not a variable of its own,
// is not rewritten (the translator never writes one); nor is a module without one. Self-contained (no libc) for dm/tools/tests/test_spv_layer.py.
#pragma once
#include <stddef.h>
#include <stdint.h>

static int spv_layer_cap(uint32_t c) { return c == 5254 || c == 69 || c == 70; }   // ShaderViewportIndexLayerEXT (= ...NV), ShaderLayer, ShaderViewportIndex (SPIR-V 1.5)
static int spv_layer_bi(uint32_t b) { return b == 9 || b == 10; }   // BuiltIn Layer, ViewportIndex

// whether the module declares a capability for layer or viewport output (the replay's pre-check: a cheap scan of the capabilities at the module's start)
static int spv_layer_wanted(const uint32_t *w, size_t n) {
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        if (op == 17 && len == 2 && spv_layer_cap(w[i + 1])) return 1;   // OpCapability
        if (op != 17 && op != 10 && op != 11 && op != 14) return 0;   // past the capabilities, extensions, imports and the memory model
        i += len; }
    return 0;
}

// whether OpExtension's literal (words s .. s + nw) is SPV_EXT_shader_viewport_index_layer, compared byte by byte (no libc)
static int spv_layer_ext(const uint32_t *s, uint32_t nw) {
    static const char e[] = "SPV_EXT_shader_viewport_index_layer";
    for (uint32_t k = 0; k < sizeof e; k++) { if (k / 4 >= nw) return 0; if ((char)(s[k / 4] >> (8 * (k % 4))) != e[k]) return 0; }
    return 1;
}

// The module without layer or viewport output, in out (cap words; it is never longer than the module): its word count, or 0 when it needs nothing or can't be
// rewritten (a built-in as a block member, or a module that does not parse).
static size_t spv_layer(const uint32_t *w, size_t n, uint32_t *out, size_t cap) {
    if (n < 5 || cap < n) return 0;
    uint32_t maxloc = 0; int any = 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        if (op == 71 && len >= 4 && w[i + 2] == 30 && w[i + 3] + 1 > maxloc) maxloc = w[i + 3] + 1;   // OpDecorate id Location l
        if (op == 71 && len == 4 && w[i + 2] == 11 && spv_layer_bi(w[i + 3])) any = 1;   // OpDecorate id BuiltIn Layer / ViewportIndex
        if (op == 72 && len >= 5 && w[i + 3] == 11 && spv_layer_bi(w[i + 4])) return 0;   // OpMemberDecorate type member BuiltIn: not rewritten
        i += len; }
    if (!any) return 0;
    size_t k = 0; for (; k < 5; k++) out[k] = w[k];
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (op == 17 && len == 2 && spv_layer_cap(w[i + 1])) { i += len; continue; }
        if (op == 10 && spv_layer_ext(w + i + 1, len - 1)) { i += len; continue; }
        for (uint32_t q = 0; q < len; q++) out[k + q] = w[i + q];
        if (op == 71 && len == 4 && w[i + 2] == 11 && spv_layer_bi(w[i + 3])) { out[k + 2] = 30; out[k + 3] = maxloc++; }   // BuiltIn → Location after the highest
        k += len; i += len; }
    return k;
}
