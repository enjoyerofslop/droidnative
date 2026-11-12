// The rules of a freed image's memory kept as a spare (gfx_vk_spare.inc) as plain functions, so dm/tools/tests/test_img_spare.py checks them on the host
#pragma once
#include <stdint.h>
// A spare fits an image when its memory type is one the image allows and it holds the image with at most a quarter of the image's size left over (a larger
// spare would hold memory the image never uses, while a spare that size could serve a larger image)
static inline int spare_fits(uint64_t spare, uint32_t type, uint64_t need, uint32_t type_bits) {
    return type < 32 && (type_bits >> type & 1u) && spare >= need && spare - need <= need / 4;
}
// The spare to take for an image: the smallest that fits; -1: none
static inline int spare_pick(const uint64_t *size, const uint32_t *type, uint32_t n, uint64_t need, uint32_t type_bits) {
    int best = -1;
    for (uint32_t i = 0; i < n; i++) if (spare_fits(size[i], type[i], need, type_bits) && (best < 0 || size[i] < size[best])) best = (int)i;
    return best;
}
// Whether the sweep frees a spare: unused for age presents, or the list over its cap with this the oldest left (the caller frees oldest first while over)
static inline int spare_expired(uint64_t freed_present, uint64_t now, uint64_t age) { return now - freed_present >= age; }
