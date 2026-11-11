// A depth / stencil texture read back by the CPU (gfx_vk.c mtl_read_texels, copy_t2b), or written from a buffer (copy_b2t): Vulkan copies an image's depth and stencil aspects to a buffer one aspect at a time,
// each tightly packed whatever the combined format: depth 2 bytes a texel (D16_UNORM) or 4 (D32_SFLOAT; D24_UNORM_S8_UINT's depth in the low 24 bits of 4, the top 8
// undefined), stencil 1 byte. NVN's texels are rebuilt from those planes here, in the layouts its formats have in memory (Maxwell's):
//   STENCIL8 (0x31)            the stencil byte
//   DEPTH16 (0x32)             16-bit unorm
//   DEPTH24 (0x33)             24-bit unorm in the low 24 bits of 4 bytes, the top 8 zero (kept as D32_SFLOAT here: nvn_fmt_mtl.c)
//   DEPTH32F (0x34)            the float
//   DEPTH24_STENCIL8 (0x35)    24-bit unorm depth in the low 24 bits, the stencil in the top 8 (kept as D32_SFLOAT_S8_UINT, or D24_UNORM_S8_UINT)
//   DEPTH32F_STENCIL8 (0x36)   the float, the stencil byte, 3 zero bytes: 8 bytes (Maxwell's ZF32_X24S8; kept as D32_SFLOAT_S8_UINT, or D24_UNORM_S8_UINT)
// A buffer → texture copy goes the other way (ds_planes, ds_slice_up): what was read out goes back in as it was, a 24-bit unorm depth kept as a float included
// (ds_float24 and ds_unorm24 are each other's inverse over all 2^24 values).
// Self-contained (no Vulkan headers) so that dm/tools/tests/test_ds_texels.py builds it alone on the PC.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

enum { DS_NONE, DS_D16, DS_D32F, DS_D24 };   // how the image's depth aspect is copied out: none, 2-byte unorm, 4-byte float, 24-bit unorm in 4 bytes

static inline size_t ds_depth_bytes(int dkind) { return dkind == DS_D16 ? 2 : dkind ? 4 : 0; }
static inline size_t ds_texel_bytes(int nvn_format) {   // a texel of an NVN depth / stencil format in memory; 0: not one
    return nvn_format == 0x31 ? 1 : nvn_format == 0x32 ? 2 : nvn_format == 0x36 ? 8 : nvn_format >= 0x33 && nvn_format <= 0x35 ? 4 : 0;
}

static inline uint32_t ds_unorm24(float x) {   // a depth in [0, 1] as 24-bit unorm (NaN and below 0: 0), rounded to nearest in double (in float, values near 1 came out one off)
    if (!(x > 0)) return 0;
    if (x >= 1) return 0xffffffu;
    return (uint32_t)((double)x * 16777215.0 + 0.5);
}
static inline float ds_float24(uint32_t u) { return (float)((double)(u & 0xffffffu) / 16777215.0); }   // 24-bit unorm as the nearest float: ds_unorm24 gives u back
// One slice's planes in a buffer: the depth plane first (w × h texels of the depth kind's bytes), then the stencil plane (1 byte a texel) at ds_sten_off, a multiple of 4
// (Vulkan's rule for a depth / stencil copy's bufferOffset). STENCIL8 has no depth plane, so its stencil plane is at 0: whether there is one is a flag, never the offset
static inline size_t ds_sten_off(int dkind, size_t n) { return (n * ds_depth_bytes(dkind) + 3) & ~(size_t)3; }
static inline size_t ds_slice_bytes(int dkind, int sten, size_t n) { return ((sten ? ds_sten_off(dkind, n) + n : n * ds_depth_bytes(dkind)) + 3) & ~(size_t)3; }

// n texels of one row: dep (dkind's bytes a texel, NULL: the image has no depth aspect, read 0) and sten (1 byte a texel, NULL: no stencil, read 0) into out, in
// nvn_format's layout. → the bytes written (n × the format's texel size), 0 for a format that is not depth or stencil
static size_t ds_texels(int nvn_format, int dkind, const uint8_t *dep, const uint8_t *sten, size_t n, uint8_t *out) {
    size_t db = ds_depth_bytes(dkind), tb = ds_texel_bytes(nvn_format);
    if (!tb) return 0;
    for (size_t i = 0; i < n; i++) {
        uint32_t raw = 0; if (dep && db) memcpy(&raw, dep + db * i, db);
        float f = 0; uint32_t u24 = 0;   // the depth as a float and as 24-bit unorm
        if (dep && dkind == DS_D32F) { memcpy(&f, &raw, 4); u24 = ds_unorm24(f); }
        else if (dep && dkind == DS_D24) { u24 = raw & 0xffffffu; f = ds_float24(u24); }
        uint8_t st = sten ? sten[i] : 0; uint8_t *o = out + tb * i;
        switch (nvn_format) {
        case 0x31: o[0] = st; break;
        case 0x32: { uint16_t d = (uint16_t)(dkind == DS_D16 ? raw : 0); memcpy(o, &d, 2); break; }
        case 0x33: memcpy(o, &u24, 4); break;
        case 0x34: { uint32_t b; memcpy(&b, &f, 4); memcpy(o, &b, 4); break; }
        case 0x35: { uint32_t w = u24 | (uint32_t)st << 24; memcpy(o, &w, 4); break; }
        case 0x36: memcpy(o, &f, 4); o[4] = st; o[5] = o[6] = o[7] = 0; break;
        }
    }
    return tb * n;
}
// The other way: n texels of one row in nvn_format's layout into the planes an image of dkind takes (dep: dkind's bytes a texel; sten: 1 byte a texel; NULL: not wanted)
static inline void ds_planes(int nvn_format, int dkind, const uint8_t *in, size_t n, uint8_t *dep, uint8_t *sten) {
    size_t db = ds_depth_bytes(dkind), tb = ds_texel_bytes(nvn_format);
    if (!tb) return;
    int isf = nvn_format == 0x34 || nvn_format == 0x36, is24 = nvn_format == 0x33 || nvn_format == 0x35;
    for (size_t i = 0; i < n; i++) {
        const uint8_t *t = in + tb * i; uint32_t w = 0; memcpy(&w, t, tb < 4 ? tb : 4);
        uint32_t raw = 0;   // the depth as the image's aspect holds it
        if (dkind == DS_D16) raw = nvn_format == 0x32 ? w : 0;
        else if (dkind == DS_D32F) { if (isf) raw = w; else if (is24) { float f = ds_float24(w); memcpy(&raw, &f, 4); } }
        else if (dkind == DS_D24) { if (is24) raw = w & 0xffffffu; else if (isf) { float f; memcpy(&f, &w, 4); raw = ds_unorm24(f); } }
        if (dep && db) memcpy(dep + db * i, &raw, db);
        if (sten) sten[i] = nvn_format == 0x31 ? t[0] : nvn_format == 0x35 ? (uint8_t)(w >> 24) : nvn_format == 0x36 ? t[4] : 0;
    }
}
// A slice of w × h texels: its planes (above) into rows of NVN texels pitch bytes apart (a readback), and such rows into its planes (an upload)
static inline void ds_slice(int nvn_format, int dkind, int sten, const uint8_t *planes, size_t w, size_t h, uint8_t *dst, size_t pitch) {
    size_t db = ds_depth_bytes(dkind), soff = ds_sten_off(dkind, w * h);
    for (size_t y = 0; y < h; y++) ds_texels(nvn_format, dkind, db ? planes + y * w * db : NULL, sten ? planes + soff + y * w : NULL, w, dst + y * pitch);
}
static inline void ds_slice_up(int nvn_format, int dkind, int sten, const uint8_t *src, size_t pitch, size_t w, size_t h, uint8_t *planes) {
    size_t db = ds_depth_bytes(dkind), soff = ds_sten_off(dkind, w * h);
    for (size_t y = 0; y < h; y++) ds_planes(nvn_format, dkind, src + y * pitch, w, db ? planes + y * w * db : NULL, sten ? planes + soff + y * w : NULL);
}
