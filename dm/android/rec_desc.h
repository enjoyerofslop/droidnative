// A vkUpdateDescriptorSets call's writes packed into one block of bytes and read back as writes whose pointers lie in the block: how the command recorder carries a
// descriptor set's writes to its thread (gfx_vk_rec.inc R_UPDDS). Self-contained (Vulkan's headers alone): dm/tools/tests/test_rec_desc.py packs and unpacks on the PC.
// Each write is an rd_write followed by its descriptors: image infos, buffer infos or buffer views, by its type. All are multiples of 8 bytes, so a block that starts
// 8-byte aligned keeps every structure aligned.
#pragma once
#include <stddef.h>
#include <string.h>
#include <vulkan/vulkan.h>

typedef struct { VkDescriptorSet set; uint32_t binding, elem, count; VkDescriptorType type; } rd_write;
enum { RD_MAX = 128, RD_BYTES_MAX = 256 << 10 };   // the writes and bytes of one block: a call past either is made as it is (rd_size 0)

// bytes of one descriptor of the type in a block; 0: a type whose descriptors are in a pNext chain (inline uniform blocks, acceleration structures) or unknown here
static inline size_t rd_elem(VkDescriptorType t) {
    switch (t) {
        case VK_DESCRIPTOR_TYPE_SAMPLER: case VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER: case VK_DESCRIPTOR_TYPE_SAMPLED_IMAGE: case VK_DESCRIPTOR_TYPE_STORAGE_IMAGE:
        case VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT: return sizeof(VkDescriptorImageInfo);
        case VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER: case VK_DESCRIPTOR_TYPE_STORAGE_BUFFER: case VK_DESCRIPTOR_TYPE_UNIFORM_BUFFER_DYNAMIC:
        case VK_DESCRIPTOR_TYPE_STORAGE_BUFFER_DYNAMIC: return sizeof(VkDescriptorBufferInfo);
        case VK_DESCRIPTOR_TYPE_UNIFORM_TEXEL_BUFFER: case VK_DESCRIPTOR_TYPE_STORAGE_TEXEL_BUFFER: return sizeof(VkBufferView);
        default: return 0;
    }
}
static inline const void *rd_src(const VkWriteDescriptorSet *w) {   // the array the write's type reads
    size_t e = rd_elem(w->descriptorType);
    return e == sizeof(VkBufferView) ? (const void *)w->pTexelBufferView : w->descriptorType <= VK_DESCRIPTOR_TYPE_STORAGE_IMAGE || w->descriptorType == VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT
        ? (const void *)w->pImageInfo : (const void *)w->pBufferInfo;
}
// the block's bytes for these writes; 0: they cannot be packed (none, too many, too large, a pNext chain, a type rd_elem does not know, a missing array)
static inline size_t rd_size(uint32_t n, const VkWriteDescriptorSet *w) {
    if (!n || n > RD_MAX) return 0;
    size_t b = 0;
    for (uint32_t i = 0; i < n; i++) {
        size_t e = rd_elem(w[i].descriptorType);
        if (!e || w[i].pNext || (w[i].descriptorCount && !rd_src(&w[i]))) return 0;
        b += sizeof(rd_write) + e * w[i].descriptorCount;
        if (b > RD_BYTES_MAX) return 0;
    }
    return b;
}
static inline void rd_pack(uint8_t *d, uint32_t n, const VkWriteDescriptorSet *w) {   // d: rd_size's bytes
    for (uint32_t i = 0; i < n; i++) {
        rd_write h = {w[i].dstSet, w[i].dstBinding, w[i].dstArrayElement, w[i].descriptorCount, w[i].descriptorType};
        memcpy(d, &h, sizeof h); d += sizeof h;
        size_t b = rd_elem(h.type) * h.count; if (b) memcpy(d, rd_src(&w[i]), b); d += b;
    }
}
// out: n writes, their arrays in the block (which the caller keeps until it has made the call)
static inline void rd_unpack(const uint8_t *s, uint32_t n, VkWriteDescriptorSet *out) {
    for (uint32_t i = 0; i < n; i++) {
        const rd_write *h = (const rd_write *)(const void *)s; s += sizeof *h;
        size_t e = rd_elem(h->type);
        out[i] = (VkWriteDescriptorSet){VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, h->set, h->binding, h->elem, h->count, h->type, NULL, NULL, NULL};
        if (e == sizeof(VkBufferView)) out[i].pTexelBufferView = (const VkBufferView *)(const void *)s;
        else if (h->type <= VK_DESCRIPTOR_TYPE_STORAGE_IMAGE || h->type == VK_DESCRIPTOR_TYPE_INPUT_ATTACHMENT) out[i].pImageInfo = (const VkDescriptorImageInfo *)(const void *)s;
        else out[i].pBufferInfo = (const VkDescriptorBufferInfo *)(const void *)s;
        s += e * h->count;
    }
}
