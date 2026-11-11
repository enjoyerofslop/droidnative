// The rules of render targets sharing one allocation (gfx_vk_rtalias.inc) as plain functions, so dm/tools/tests/test_rt_alias.py checks them on the host
#pragma once
#include <stdint.h>
#include <string.h>
#include "../gfx/nvn/nvn_tex.h"
// The key: the storage start (the pool and the offset in it) and the description without its extent. A target the game makes again at another size over the same
// start (Ocarina of Time resizes some every frame) is the same key; another format, target type, level or layer count, sample count or packaged layout is another
typedef struct { uint64_t pool; int64_t off; nvn_texdesc d; } ra_key;
static inline ra_key ra_key_of(uint64_t pool, int64_t off, const nvn_texdesc *d, int image_flag) {
    ra_key k; memset(&k, 0, sizeof k); k.pool = pool; k.off = off; k.d = *d;
    k.d.width = k.d.height = k.d.depth = 0; k.d.stride = 0; k.d.flags &= ~image_flag;   // the image flag as the sharing table leaves it out (gfx_vk.c share_of)
    return k;
}
// Which images may share: a render target (colour, or depth / stencil only at mode 2) the GPU gives its content (not a packaged texture uploaded from guest memory,
// not one the CPU decodes), in a memory pool, of at least min_bytes (small ones are not worth a table entry)
static inline int ra_eligible(int mode, int in_pool, int packaged, int converted, int target, int colour, uint64_t bytes, uint64_t min_bytes) {
    return mode > 0 && in_pool && !packaged && !converted && target && (colour || mode >= 2) && bytes >= min_bytes;
}
// The size of a new allocation for a key whose current one (have bytes; 0: none) is too small for need: half again as large, so a target that grows a little at a
// time takes a few allocations, not one per size
static inline uint64_t ra_grow(uint64_t have, uint64_t need) { uint64_t g = have + have / 2; return g > need ? g : need; }
