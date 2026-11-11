// Maxwell's FMUL and FADD kept unfused in the shaders that place vertices. Maxwell rounds each FMUL and FADD on its own and fuses only where the program says FFMA;
// the translator writes them as OpFMul and OpFAdd (and FFMA as fma), which a Vulkan driver may contract into fused multiply-adds as it likes. Two vertex shaders
// that compute the same position then give different depths when the driver fuses different products in each: Super Mario Odyssey draws the Cap Kingdom ground
// in a depth pre-pass with one vertex shader and again into its G-buffer with another, the same matrix products added in another order, under a less-or-equal
// depth test, and on the Mali-G715 the second pass failed in square blocks, which kept the previous frame's picture (the Mac had the same blocks until its
// Metal compiles preserved invariance). Every OpFAdd, OpFSub, OpFMul, OpFNegate and OpVectorTimesScalar result of a module whose entry point is a vertex,
// tessellation, geometry or mesh stage is decorated NoContraction, which makes the driver round them as Maxwell does, and so alike in every shader. Fragment and
// compute shaders are left as translated. Self-contained (no libc), so that dm/tools/tests/test_spv_precise.py builds it alone.
#pragma once
#include <stddef.h>
#include <stdint.h>

static int spv_precise_op(uint32_t op) { return op == 127 || op == 129 || op == 131 || op == 133 || op == 142; }   // OpFNegate, OpFAdd, OpFSub, OpFMul, OpVectorTimesScalar
// a stage that places vertices: Vertex, TessellationControl, TessellationEvaluation, Geometry, MeshNV, MeshEXT
static int spv_precise_model(uint32_t m) { return m <= 3 || m == 5268 || m == 5365; }
// the module's opening run of instructions (capabilities, extensions, imports, memory model, entry points, execution modes, debug names, annotations): the
// decorations go at its end, after the module's own annotations and before its first type
static int spv_precise_head(uint32_t op) {
    return (op >= 2 && op <= 8) || op == 10 || op == 11 || op == 14 || op == 15 || op == 16 || op == 17 || op == 330 || op == 331 || (op >= 71 && op <= 75) || op == 332 ||
           op == 5632 || op == 5633;
}

// whether the module needs spv_precise: an entry point of a stage that places vertices (the entry points come before any arithmetic: one short scan)
static int spv_precise_wanted(const uint32_t *w, size_t n) {
    if (n < 5 || w[0] != 0x07230203) return 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == 15 && len >= 2 && spv_precise_model(w[i + 1])) return 1;   // OpEntryPoint
        if (!spv_precise_head(op)) return 0;
        i += len;
    }
    return 0;
}

// The module with NoContraction on each such result not decorated so already, into o (cap words). seen: scratch of (bound + 31) / 32 words. *need: the words the
// output takes; *marked: the results decorated. Returns the words written, or 0: a module that needs nothing, a malformed one, or o too small (o NULL: *need only)
static size_t spv_precise(const uint32_t *w, size_t n, uint32_t *seen, uint32_t *o, size_t cap, size_t *need, int *marked) {
    *need = 0; *marked = 0;
    if (n < 5 || w[0] != 0x07230203 || !spv_precise_wanted(w, n)) return 0;
    uint32_t bound = w[3];
    for (uint32_t k = 0; k < (bound + 31) / 32; k++) seen[k] = 0;
    size_t at = 0, i = 5; int head = 1, count = 0;
    while (i < n) {   // the end of the opening run, and the results already NoContraction (marked in seen)
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (head && !spv_precise_head(op)) { head = 0; at = i; }
        if (op == 71 && len >= 3 && w[i + 2] == 42 && w[i + 1] < bound) seen[w[i + 1] >> 5] |= 1u << (w[i + 1] & 31);   // OpDecorate NoContraction
        i += len;
    }
    if (head) return 0;   // no instruction past the opening run: no arithmetic
    for (i = at; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (spv_precise_op(op) && len >= 3) { uint32_t r = w[i + 2]; if (r < bound && !(seen[r >> 5] & (1u << (r & 31)))) count++; }   // SSA: each result once
        i += len;
    }
    if (!count) return 0;
    *need = n + 3 * (size_t)count; *marked = count;
    if (!o || cap < *need) return 0;
    for (i = 0; i < at; i++) o[i] = w[i];
    size_t q = at;
    for (i = at; i < n; ) {   // the decorations, in the order of their results; seen still holds only the module's own
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (spv_precise_op(op) && len >= 3) { uint32_t r = w[i + 2]; if (r < bound && !(seen[r >> 5] & (1u << (r & 31)))) { o[q++] = (3u << 16) | 71; o[q++] = r; o[q++] = 42; } }
        i += len;
    }
    for (i = at; i < n; i++) o[q++] = w[i];
    return q == *need ? q : 0;
}
