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

// Layer output less a base, for a GPU whose vertex shaders reach only the first layers of a layered framebuffer. Arm's Mali-G715 driver (a Pixel 9 Pro XL, 0xd803000)
// drops every primitive whose layer from a vertex shader is 8 or more, whatever the framebuffer's layer count (negative ones too); a geometry shader's layer reaches
// them all. Pokemon Legends: Z-A draws its 32x32x32 colour-grading LUT one instance per slice that way, so only slices 1-7 were written and the tone mapper drew the
// world nearly black. The replay draws such a draw once per 8 layers, into views that start at layer 8g (gfx_vk_draw.inc vs_layer_groups), so the vertex shader must
// write the layer less 8g, and a fragment shader that reads the layer (the LUT's computes its slice's colour from it) must add 8g back. In a Vertex entry point every
// OpStore to the BuiltIn Layer variable stores (value - base); in a Fragment one every OpLoad of it gives (value + base). base is the int at byte SPV_LBASE_PC of the
// push constant block (the alpha test's reference is at 0). The module in out (cap words): its word count, or 0 when it has no such access or can't be rewritten
// (another stage, a block member, no 32-bit integer layer, a push constant block already there); *need, when given, the words it takes. Self-contained (no libc)
// for test_spv_layer.py.
#define SPV_LBASE_PC 16
static size_t spv_layer_base(const uint32_t *w, size_t n, uint32_t *out, size_t cap, size_t *need) {
    if (need) *need = 0;
    if (n < 5) return 0;
    uint32_t lv = 0, pt = 0, it = 0, nacc = 0, bound = w[3]; int model = -1, v14 = w[1] >= 0x00010400u;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        if (op == 15 && len >= 3) { if (model >= 0 && (int)w[i + 1] != model) return 0; model = (int)w[i + 1]; }   // OpEntryPoint: one stage
        if (op == 71 && len == 4 && w[i + 2] == 11 && w[i + 3] == 9) lv = w[i + 1];   // OpDecorate id BuiltIn Layer
        if (op == 72 && len >= 5 && w[i + 3] == 11 && w[i + 4] == 9) return 0;   // a block member: not rewritten
        if (op == 59 && len >= 4 && w[i + 3] == 9) return 0;   // a push constant block already (one per entry point)
        i += len; }
    if ((model != 0 && model != 4) || !lv) return 0;   // Vertex, Fragment
    uint32_t acc = model == 0 ? 62 : 61;   // the vertex shader's OpStore to it, the fragment shader's OpLoad of it
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (op == 59 && len >= 4 && w[i + 2] == lv) pt = w[i + 1];   // OpVariable type id: the layer's pointer type
        if (acc == 62 && op == 62 && len >= 3 && w[i + 1] == lv) nacc++;   // OpStore %layer %v
        if (acc == 61 && op == 61 && len >= 4 && w[i + 3] == lv) nacc++;   // %r = OpLoad %int %layer
        i += len; }
    for (size_t i = 5; i < n && pt; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (op == 32 && len == 4 && w[i + 1] == pt) it = w[i + 3];   // OpTypePointer id Output/Input int
        i += len; }
    int i32 = 0;
    for (size_t i = 5; i < n && it; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (op == 21 && len == 4 && w[i + 1] == it && w[i + 2] == 32) i32 = 1;   // OpTypeInt 32
        i += len; }
    if (!i32 || !nacc) return 0;
    size_t want = n + 8 + 19 + (v14 ? 1 : 0) + 14 * (size_t)nacc;   // the decorations, the block's type, pointer, variable, member pointer and index; per access a load and an add
    if (need) *need = want;
    if (!out || cap < want) return 0;
    uint32_t st = bound, pst = bound + 1, pv = bound + 2, pi = bound + 3, c0 = bound + 4, nid = bound + 5;
    size_t k = 0; for (; k < 5; k++) out[k] = w[k];
    int types = 0;
    for (size_t i = 5; i < n; ) { uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (op == 54 && !types) {   // before the first OpFunction: the push constant block, its variable, and the member's pointer and index
            types = 1;
            out[k++] = 3u << 16 | 30; out[k++] = st; out[k++] = it;   // OpTypeStruct %st %int
            out[k++] = 4u << 16 | 32; out[k++] = pst; out[k++] = 9; out[k++] = st;   // OpTypePointer %pst PushConstant %st
            out[k++] = 4u << 16 | 59; out[k++] = pst; out[k++] = pv; out[k++] = 9;   // OpVariable %pst %pv PushConstant
            out[k++] = 4u << 16 | 32; out[k++] = pi; out[k++] = 9; out[k++] = it;   // OpTypePointer %pi PushConstant %int
            out[k++] = 4u << 16 | 43; out[k++] = it; out[k++] = c0; out[k++] = 0;   // OpConstant %int %c0 0
        }
        if (acc == 62 && op == 62 && len >= 3 && w[i + 1] == lv) {   // OpStore %layer %v: %v less the base
            uint32_t ac = nid++, ld = nid++, sub = nid++;
            out[k++] = 5u << 16 | 65; out[k++] = pi; out[k++] = ac; out[k++] = pv; out[k++] = c0;   // OpAccessChain %pi %ac %pv %c0
            out[k++] = 4u << 16 | 61; out[k++] = it; out[k++] = ld; out[k++] = ac;   // OpLoad %int %ld %ac
            out[k++] = 5u << 16 | 130; out[k++] = it; out[k++] = sub; out[k++] = w[i + 2]; out[k++] = ld;   // OpISub %int %sub %v %ld
            for (uint32_t q = 0; q < len; q++) out[k + q] = w[i + q];
            out[k + 2] = sub; k += len; i += len; continue;
        }
        if (acc == 61 && op == 61 && len >= 4 && w[i + 3] == lv) {   // %r = OpLoad %int %layer: loaded as %raw, %r = %raw + the base (the uses keep %r)
            uint32_t raw = nid++, ac = nid++, ld = nid++;
            for (uint32_t q = 0; q < len; q++) out[k + q] = w[i + q];
            out[k + 2] = raw; k += len;
            out[k++] = 5u << 16 | 65; out[k++] = pi; out[k++] = ac; out[k++] = pv; out[k++] = c0;   // OpAccessChain %pi %ac %pv %c0
            out[k++] = 4u << 16 | 61; out[k++] = it; out[k++] = ld; out[k++] = ac;   // OpLoad %int %ld %ac
            out[k++] = 5u << 16 | 128; out[k++] = w[i + 1]; out[k++] = w[i + 2]; out[k++] = raw; out[k++] = ld;   // OpIAdd %int %r %raw %ld
            i += len; continue;
        }
        for (uint32_t q = 0; q < len; q++) out[k + q] = w[i + q];
        if (op == 15 && v14) { out[k] += 1u << 16; out[k + len] = pv; k++; }   // SPIR-V 1.4 lists every global the entry point uses
        k += len;
        if (op == 71 && len == 4 && w[i + 1] == lv && w[i + 2] == 11) {   // after BuiltIn Layer: the block's decorations
            out[k++] = 3u << 16 | 71; out[k++] = st; out[k++] = 2;   // OpDecorate %st Block
            out[k++] = 5u << 16 | 72; out[k++] = st; out[k++] = 0; out[k++] = 35; out[k++] = SPV_LBASE_PC;   // OpMemberDecorate %st 0 Offset 16
        }
        i += len; }
    if (!types) return 0;
    out[3] = nid; return k;
}
