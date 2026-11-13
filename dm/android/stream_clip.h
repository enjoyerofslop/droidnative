// Where an indexed draw's vertex stream is looked up to among the forwardable write-backs (gfx_vk_draw.inc stream_clip), as a plain function, so
// dm/tools/tests/test_stream_clip.py checks it on the host.
// Why: an indexed draw's stream is looked up as bound (which vertices it fetches is not known), and games bind a stream at its first vertex or attribute with the whole
// buffer's size, so the range runs past the buffer. Xenoblade Chronicles 3 binds each character's skinned vertices (a 576,000-byte buffer that a draw under rasterizer
// discard writes) up to 1,120 bytes in, each binding as long as the buffer. Looked up whole, such a range met the next buffer's write too, and the two were learned as one
// home range (rd_home.h). In that range's copy the second buffer sat 48 bytes off the storage buffer alignment, so every draw reading it as a storage buffer waited for the GPU.
#pragma once
#include <stddef.h>
#include <stdint.h>
// [lo, hi): the stream's bound range; [wl, wl + wn): the newest write-back holding lo; fwd: it is forwardable and one row. The end to look the stream up to: the write-back's
// end when the range runs past it and is no longer than it (a binding into the written buffer, with that buffer's size). An index past the vertices the write-back holds
// would read bytes nothing wrote, on the Switch as here. 0: look it up as bound
static inline uintptr_t stream_clip_end(uintptr_t lo, uintptr_t hi, uintptr_t wl, size_t wn, int fwd) {
    uintptr_t we = wl + wn;
    if (!fwd || lo < wl || lo >= we || hi <= we || hi - lo > wn) return 0;
    return we;
}
