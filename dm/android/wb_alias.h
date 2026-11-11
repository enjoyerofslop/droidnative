// Whether a shader's binding of guest memory [addr, addr + n) can be bound on the GPU copy of a write-back the same draw or dispatch made for another binding
// (gfx_vk_draw.inc own_alias): the write-back is an arena copy of one row (a storage buffer's or a buffer image's), the binding lies inside it, and its offset
// there keeps the GPU's alignment for the binding (al; 0: none). On the Switch two bindings of the same memory are one buffer, so a write through one is what
// the other reads; bound to copies of their own, each saw only its own writes, and the two write-backs, with one snapshot, landed byte by byte over each other.
// Self-contained (no libc), so that dm/tools/tests/test_wb_alias.py builds it alone.
#pragma once
#include <stddef.h>
#include <stdint.h>

// arena: the write-back reads the chunk's arena (wb_t.st < 0); rows, dst, row_bytes, off: its wb_t fields. → 1 and *at, the binding's offset in that arena
// block; else 0
static int wb_alias_at(int arena, size_t rows, uintptr_t dst, size_t row_bytes, size_t off, uint64_t addr, uint64_t n, uint64_t al, uint64_t *at) {
    if (!arena || rows != 1 || !n || addr < dst || addr - dst > row_bytes || n > row_bytes - (addr - dst)) return 0;
    uint64_t o = (uint64_t)off + (addr - dst);
    if (al && o % al) return 0;
    *at = o;
    return 1;
}
