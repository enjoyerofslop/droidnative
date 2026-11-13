// Whether a read of a draw's pending storage buffer write may take the write-back's copy on the GPU after a barrier (gfx_vk_draw.inc wb_promote), as a plain function, so
// dm/tools/tests/test_wb_promote.py checks it on the host.
// Why: a draw's storage buffer write is a write-back of its own that later shaders do not read on the GPU (draws in a pass have no barrier between them), so a draw reading
// it waited for the GPU to finish the chunk. Xenoblade Chronicles 3 writes 16 and 64 bytes from a draw that a later draw reads as a uniform buffer, twice a frame: each wait,
// with the GPU at its lowest clock, made the replay thread and the GPU take turns for the rest of the frame.
#pragma once
#include <stddef.h>
#include <stdint.h>
// The newest write of the chunk to [lo, hi): [dst, dst + n) on one row (rows), of the chunk's arena (st < 0), not forwardable yet (fwd), not written in place (inpl), not a linear
// target's (lin) nor a depth / stencil readback (ds); copy: a queued copy writes into the range. 1: the read may take it once the pass has ended and a barrier follows the draw
static inline int wb_promote_ok(uintptr_t lo, uintptr_t hi, uintptr_t dst, size_t n, size_t rows, int st, int fwd, int inpl, int lin, int ds, int copy) {
    return hi > lo && !copy && !fwd && st < 0 && rows == 1 && !inpl && !lin && !ds && lo >= dst && hi <= dst + n;
}
