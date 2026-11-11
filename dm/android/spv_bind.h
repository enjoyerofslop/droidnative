// Binding numbers compacted in a stage's set. The translator numbers some of NVN2's constant buffers far apart: Ocarina of Time's 4,823 shaders (of 42,848) that bind
// one at 1,048,576 or more (2,101,266 = 0x201012 in its Kokiri fragment shaders) use no numbers in between. Samsung's Xclipse driver (24.0.533) keeps 64 bytes per
// binding number up to a layout's highest, in every set layout and again in every pipeline layout made with it: 128 MB for one uniform buffer at 2,101,266 (0 at 7),
// and about 9 GB over Kokiri Forest's pipelines on a Galaxy Z Flip 7, before the game was killed. So each binding at SPV_BIND_FROM or past it gets a number in the
// order of the old ones, from just past the set's other bindings (and past the capture variant's feedback buffers at 100-103); the layout (sh_get) and the module's
// OpDecorate Binding (lm_code) take the same map, so nothing on disk changes. Self-contained (no libc) for dm/tools/tests/test_spv_bind.py.
#pragma once
#include <stddef.h>
#include <stdint.h>

#define SPV_BIND_FROM 1024u   // bindings at or past this are numbered again
#define SPV_BIND_BASE 128u    // the first new number, unless the set's own bindings reach past it
enum { SPV_BIND_MAX = 32 };   // a stage's constant and storage buffers, textures and images numbered again at most (more: the map is left empty)
typedef struct { uint32_t n; uint32_t from[SPV_BIND_MAX], to[SPV_BIND_MAX]; } spv_bmap;

// The map for a set with these bindings (any order, repeats allowed): returns its entries, 0 for none, -1 for more than SPV_BIND_MAX (then empty, nothing changes)
static int spv_bmap_make(const uint32_t *b, int nb, spv_bmap *m) {
    m->n = 0; uint32_t base = SPV_BIND_BASE;
    for (int i = 0; i < nb; i++) if (b[i] < SPV_BIND_FROM && b[i] + 1 > base) base = b[i] + 1;
    for (int i = 0; i < nb; i++) {
        uint32_t v = b[i], k = 0; if (v < SPV_BIND_FROM) continue;
        while (k < m->n && m->from[k] < v) k++;
        if (k < m->n && m->from[k] == v) continue;
        if (m->n == SPV_BIND_MAX) { m->n = 0; return -1; }
        for (uint32_t j = m->n; j > k; j--) m->from[j] = m->from[j - 1];
        m->from[k] = v; m->n++;
    }
    for (uint32_t k = 0; k < m->n; k++) m->to[k] = base + k;
    return (int)m->n;
}

// a binding's number in the map's set (itself when the map lacks it)
static uint32_t spv_bmap_get(const spv_bmap *m, uint32_t b) {
    for (uint32_t k = 0; m && k < m->n; k++) if (m->from[k] == b) return m->to[k];
    return b;
}

// In place: each OpDecorate Binding (the decorations come before the first function) whose number the map has gets its new one. Returns how many changed
static size_t spv_bind_remap(uint32_t *w, size_t n, const spv_bmap *m) {
    size_t c = 0;
    if (!m || !m->n || n < 5) return 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) break;
        if (op == 54) break;   // OpFunction
        if (op == 71 && len == 4 && w[i + 2] == 33) { uint32_t v = spv_bmap_get(m, w[i + 3]); if (v != w[i + 3]) { w[i + 3] = v; c++; } }   // OpDecorate id Binding b
        i += len;
    }
    return c;
}
