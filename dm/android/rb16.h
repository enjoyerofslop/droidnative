// NVN's RGB-order 16-bit packed formats (RGBA4, RGB5, RGB5A1, RGB565: 0x39–0x3C) on Vulkan, as plain functions, so dm/tools/tests/test_rb16.py checks them on the host.
// NVN puts red at bit 0 (RGBA4: R, G, B, A from bit 0 up). nvn_fmt_to_mtl maps them by name to the Metal format with red and blue exchanged (RGBA4: all four nibbles
// reversed), saying so in its swizzle, and vk_of_mtl takes that Metal format's Vulkan twin: R5G6B5, A1R5G5B5, R4G4B4A4, with red at bit 11, 10 or 12. Vulkan has the
// guest's own orders only optionally or through extensions (B5G6R5; A1B5G5R5 needs VK_KHR_maintenance5, A4B4G4R4 VK_EXT_4444_formats). So, as nvn_mtl.m does on
// Metal (rb_packed_shift), every image of these formats holds the Vulkan format's order, as the GPU renders, clears and copies into it, and only guest memory holds the
// guest's: the bits are converted where they cross (gfx_vk.c: uploads, buffer → texture copies, and the write-backs of texture → buffer copies, ReadTexels and linear
// render targets). A view swizzle alone would read uploads right and swap whatever the GPU draws into such a target.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

// The exchange for a texture whose nvn_fmt_to_mtl gave Metal format mtl and swizzle swz: red's bit position in the Vulkan format (11 for RGB565, 10 for RGB5 and
// RGB5A1; blue is at bit 0), 4 for RGBA4 (its four nibbles reversed), 0 for every other format (the BGR family 0x95–0x98 is already in Vulkan's order)
static inline int rb16_shift(uint32_t mtl, const uint8_t swz[4]) {
    if (swz[0] == 2) return 0;   // NVN_SWZ_R: red is red, nothing to exchange
    return mtl == 40 ? 11 : mtl == 43 ? 10 : mtl == 42 ? 4 : 0;   // MTLPixelFormat B5G6R5Unorm, BGR5A1Unorm, ABGR4Unorm
}
// One texel the other way: 5-bit red and blue exchanged (green and alpha stay), or RGBA4's nibbles reversed. Its own inverse
static inline uint16_t rb16_texel(uint16_t q, int shift) {
    if (shift == 4) return (uint16_t)(q << 12 | (q & 0xf0u) << 4 | (q >> 4 & 0xf0u) | q >> 12);
    uint16_t m = (uint16_t)(31u | 31u << shift);
    return (uint16_t)((q & ~m) | (q & 31u) << shift | (q >> shift & 31u));
}
// A region of 16-bit texels in place: rows of wb bytes, row bytes apart. Both directions (guest → image and back) are the same exchange; shift 0 leaves it alone
static inline void rb16_rows(uint8_t *p, size_t wb, size_t rows, size_t row, int shift) {
    if (!shift) return;
    for (size_t y = 0; y < rows; y++) {
        uint8_t *r = p + y * row;
        for (size_t i = 0; i + 2 <= wb; i += 2) { uint16_t q; memcpy(&q, r + i, 2); q = rb16_texel(q, shift); memcpy(r + i, &q, 2); }
    }
}
