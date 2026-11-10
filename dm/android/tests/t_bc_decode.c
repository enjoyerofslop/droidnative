// t_bc_decode <bc_decode.spv>: whether this GPU's decode of BC4 and BC5 blocks (dm/android/shaders/bc_decode.comp) gives the bytes the CPU decode gives (bcdec, as gfx_vk.c
// builds it: BCDEC_BC4BC5_PRECISE, -fsigned-char). Each case runs gfx_vk_bcdec.inc bcd_decode's commands: blocks uploaded into a shadow image of one texel a block (RGBA16UI
// for BC4, RGBA32UI for BC5), copied into a buffer, decoded by the compute shader into rows of whole blocks, and copied into the level of a decoded image (R8 / RG8,
// UNORM or SNORM) clipped to its size; a 3D case writes one depth plane and checks that the others stay zero. Blocks: random, plus every endpoint order, equal and
// -128 endpoints, and each index in every texel. Exit 0 when every byte is right. dm/tools/tests/test_bc_gpu_decode.py builds and runs it with DM_TEST_SERIAL=<serial>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define BCDEC_IMPLEMENTATION
#define BCDEC_STATIC
#define BCDEC_BC4BC5_PRECISE
#include "../../third_party/bcdec/bcdec.h"
#define CK(x) do { VkResult r_ = (x); if (r_) { printf("%s = %d\n", #x, r_); exit(1); } } while (0)
static VkDevice d; static VkQueue q; static VkPhysicalDeviceMemoryProperties mp; static VkCommandPool cp;
static uint32_t mem_type(uint32_t bits, VkMemoryPropertyFlags want) { for (uint32_t i = 0; i < mp.memoryTypeCount; i++) if ((bits >> i & 1) && (mp.memoryTypes[i].propertyFlags & want) == want) return i; printf("no memory type %#x\n", want); exit(1); }
static VkBuffer buffer(VkDeviceSize n, VkDeviceMemory *m, void **p) {   // host-visible, coherent: storage and both copy directions, as the replay's arena
    VkBufferCreateInfo bc = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = n, .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    VkBuffer b; CK(vkCreateBuffer(d, &bc, NULL, &b)); VkMemoryRequirements mr; vkGetBufferMemoryRequirements(d, b, &mr);
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = mem_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
    CK(vkAllocateMemory(d, &ma, NULL, m)); CK(vkBindBufferMemory(d, b, *m, 0)); CK(vkMapMemory(d, *m, 0, n, 0, p)); memset(*p, 0, n); return b;
}
static VkImage image(VkFormat f, VkImageType t, uint32_t w, uint32_t h, uint32_t z) {
    VkImageCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = t, .format = f, .extent = {w, h, z}, .mipLevels = 1, .arrayLayers = 1, .samples = 1,
                            .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT};
    VkImage i; CK(vkCreateImage(d, &ic, NULL, &i)); VkMemoryRequirements mr; vkGetImageMemoryRequirements(d, i, &mr);
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = mem_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    VkDeviceMemory m; CK(vkAllocateMemory(d, &ma, NULL, &m)); CK(vkBindImageMemory(d, i, m, 0)); return i;
}
static void barrier(VkCommandBuffer c) {   // gfx_vk.c cb_barrier
    VkMemoryBarrier mb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_MEMORY_WRITE_BIT, .dstAccessMask = VK_ACCESS_MEMORY_READ_BIT | VK_ACCESS_MEMORY_WRITE_BIT};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
}
static uint32_t rnd = 12345;
static uint32_t next(void) { rnd ^= rnd << 13; rnd ^= rnd >> 17; rnd ^= rnd << 5; return rnd; }
static void channel_block(uint8_t *b, uint32_t i) {   // block i of a case: the special ones first, then random
    uint64_t v = (uint64_t)next() << 32 | next();
    switch (i % 64) {
        case 0: v = (v & ~0xffffull) | 0x20c0; break;   // a0 > a1 (UNORM), a0 < a1 (signed: 0xc0 is -64)
        case 1: v = (v & ~0xffffull) | 0xc020; break;
        case 2: v = (v & ~0xffffull) | 0x7777; break;   // equal endpoints
        case 3: v = (v & ~0xffffull) | 0x8080; break;   // -128 twice: both read as -127
        case 4: v = (v & ~0xffffull) | 0x7f80; break;
        case 5: v = (v & ~0xffffull) | 0x00ff; break;
        default: break;
    }
    if (i % 64 >= 8 && i % 64 < 16) {   // texel t's index (t + i) % 8: each index in every texel, the one spanning the two words included
        uint64_t idx = 0; for (int t = 0; t < 16; t++) idx |= (uint64_t)((t + i) % 8) << (3 * t);
        v = (v & 0xffff) | idx << 16;
    }
    for (int k = 0; k < 8; k++) b[k] = (uint8_t)(v >> (8 * k));
}
static VkPipeline pipe; static VkPipelineLayout pl; static VkDescriptorSetLayout dsl; static VkDescriptorPool dp;
// one case: kind as the shader's (0 BC4, 1 BC4 signed, 2 BC5, 3 BC5 signed), a w x h level, 3D with depth z writing plane pz when z > 1
static int run_case(int kind, uint32_t w, uint32_t h, uint32_t z, uint32_t pz) {
    static const VkFormat dec[4] = {VK_FORMAT_R8_UNORM, VK_FORMAT_R8_SNORM, VK_FORMAT_R8G8_UNORM, VK_FORMAT_R8G8_SNORM};
    uint32_t bw = (w + 3) / 4, bh = (h + 3) / 4, bb = kind < 2 ? 8 : 16, px = kind < 2 ? 1 : 2;
    VkDeviceSize nblk = (VkDeviceSize)bw * bh * bb, nout = (VkDeviceSize)bw * 4 * bh * 4 * px, nimg = (VkDeviceSize)w * h * z * px;
    VkDeviceMemory m1, m2, m3, m4; uint8_t *blk, *img; void *pm, *po;
    VkBuffer up = buffer(nblk, &m1, (void **)&blk), mid = buffer(nblk, &m2, &pm), outb = buffer(nout, &m4, &po), rd = buffer(nimg, &m3, (void **)&img);   // mid, outb: the replay's two arena slices
    for (uint32_t i = 0; i < bw * bh; i++) { channel_block(blk + i * bb, i); if (bb == 16) channel_block(blk + i * bb + 8, i * 7 + 3); }
    VkImage sh = image(bb == 8 ? VK_FORMAT_R16G16B16A16_UINT : VK_FORMAT_R32G32B32A32_UINT, VK_IMAGE_TYPE_2D, bw, bh, 1), di = image(dec[kind], z > 1 ? VK_IMAGE_TYPE_3D : VK_IMAGE_TYPE_2D, w, h, z);
    VkDescriptorSetAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = dp, .descriptorSetCount = 1, .pSetLayouts = &dsl}; VkDescriptorSet set; CK(vkAllocateDescriptorSets(d, &ai, &set));
    VkDescriptorBufferInfo bi[2] = {{mid, 0, nblk}, {outb, 0, nout}};
    VkWriteDescriptorSet wr[2] = {{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, set, 0, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bi[0], NULL},
                                  {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, set, 1, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bi[1], NULL}};
    vkUpdateDescriptorSets(d, 2, wr, 0, NULL);
    VkCommandBufferAllocateInfo ca = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = cp, .commandBufferCount = 1}; VkCommandBuffer c; CK(vkAllocateCommandBuffers(d, &ca, &c));
    VkCommandBufferBeginInfo cbi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; CK(vkBeginCommandBuffer(c, &cbi));
    VkImageMemoryBarrier ib[2] = {{.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_GENERAL,
                                   .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = sh, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}}};
    ib[1] = ib[0]; ib[1].image = di;
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 2, ib);
    VkClearColorValue zero = {{0}}; VkImageSubresourceRange all = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1};
    vkCmdClearColorImage(c, di, VK_IMAGE_LAYOUT_GENERAL, &zero, 1, &all);   // fresh memory reads as 0 (vt_clear_new)
    VkBufferImageCopy r0 = {.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {bw, bh, 1}};
    vkCmdCopyBufferToImage(c, up, sh, VK_IMAGE_LAYOUT_GENERAL, 1, &r0); barrier(c);
    // bcd_decode from here
    VkBufferImageCopy r1 = {.bufferOffset = 0, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {bw, bh, 1}};
    vkCmdCopyImageToBuffer(c, sh, VK_IMAGE_LAYOUT_GENERAL, mid, 1, &r1); barrier(c);
    uint32_t pc[3] = {bw, bh, (uint32_t)kind};
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, pipe); vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 0, 1, &set, 0, NULL);
    vkCmdPushConstants(c, pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, pc); vkCmdDispatch(c, (bw + 7) / 8, (bh + 7) / 8, 1); barrier(c);
    VkBufferImageCopy r2 = {.bufferOffset = 0, .bufferRowLength = bw * 4, .bufferImageHeight = bh * 4, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1},
                            .imageOffset = {0, 0, z > 1 ? (int32_t)pz : 0}, .imageExtent = {w, h, 1}};
    vkCmdCopyBufferToImage(c, outb, di, VK_IMAGE_LAYOUT_GENERAL, 1, &r2); barrier(c);
    VkBufferImageCopy r3 = {.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {w, h, z}};
    vkCmdCopyImageToBuffer(c, di, VK_IMAGE_LAYOUT_GENERAL, rd, 1, &r3);
    VkMemoryBarrier hb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &hb, 0, NULL, 0, NULL);
    CK(vkEndCommandBuffer(c)); VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &c}; CK(vkQueueSubmit(q, 1, &si, VK_NULL_HANDLE)); CK(vkQueueWaitIdle(q));
    uint8_t *want = calloc(1, nimg), tile[4 * 4 * 2];   // gfx_vk.c bc_decode's calls, block by block
    for (uint32_t by = 0; by < bh; by++) for (uint32_t bx = 0; bx < bw; bx++) {
        const uint8_t *b = blk + (by * bw + bx) * bb;
        if (kind < 2) bcdec_bc4(b, tile, 4, kind == 1); else bcdec_bc5(b, tile, 8, kind == 3);
        for (uint32_t y = 0; y < 4 && by * 4 + y < h; y++) for (uint32_t x = 0; x < 4 && bx * 4 + x < w; x++) for (uint32_t k = 0; k < px; k++)
            want[(((size_t)(z > 1 ? pz : 0) * h + by * 4 + y) * w + bx * 4 + x) * px + k] = tile[(y * 4 + x) * px + k];
    }
    int bad = 0;
    for (VkDeviceSize i = 0; i < nimg; i++) if (img[i] != want[i]) { if (bad++ < 6) { size_t t = i / px; printf("  kind %d %ux%ux%u: texel (%zu,%zu,%zu) byte %zu = %#x, want %#x\n", kind, w, h, z, t % w, t / w % h, t / w / h, (size_t)(i % px), img[i], want[i]); } }
    printf("kind %d (%s), %ux%u%s: %u blocks, %d wrong bytes of %llu\n", kind, (const char *[]){"BC4", "BC4 signed", "BC5", "BC5 signed"}[kind], w, h, z > 1 ? " (3D plane)" : "", bw * bh, bad, (unsigned long long)nimg);
    free(want); return bad;
}
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    VkApplicationInfo ap = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ap}; VkInstance in; CK(vkCreateInstance(&ic, NULL, &in));
    uint32_t n = 1; VkPhysicalDevice pd; vkEnumeratePhysicalDevices(in, &n, &pd);
    VkPhysicalDeviceProperties pp; vkGetPhysicalDeviceProperties(pd, &pp); VkPhysicalDeviceFeatures pf; vkGetPhysicalDeviceFeatures(pd, &pf);
    printf("%s, driver %#x, BC textures %u\n", pp.deviceName, pp.driverVersion, pf.textureCompressionBC);
    vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    float pri = 1; VkDeviceQueueCreateInfo qc = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &pri};
    VkDeviceCreateInfo dc = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qc}; CK(vkCreateDevice(pd, &dc, NULL, &d)); vkGetDeviceQueue(d, 0, 0, &q);
    VkCommandPoolCreateInfo cpc = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; CK(vkCreateCommandPool(d, &cpc, NULL, &cp));
    FILE *f = fopen(argv[1], "rb"); if (!f) { printf("no %s\n", argv[1]); return 1; }
    static uint32_t code[1 << 16]; size_t cn = fread(code, 1, sizeof code, f); fclose(f);
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = cn, .pCode = code}; VkShaderModule sm; CK(vkCreateShaderModule(d, &mc, NULL, &sm));
    VkDescriptorSetLayoutBinding lb[2] = {{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}};
    VkDescriptorSetLayoutCreateInfo dl = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = lb}; CK(vkCreateDescriptorSetLayout(d, &dl, NULL, &dsl));
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 12};
    VkPipelineLayoutCreateInfo plc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &dsl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr}; CK(vkCreatePipelineLayout(d, &plc, NULL, &pl));
    VkComputePipelineCreateInfo cc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = pl, .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = sm, .pName = "main"}};
    CK(vkCreateComputePipelines(d, VK_NULL_HANDLE, 1, &cc, NULL, &pipe));
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 64}; VkDescriptorPoolCreateInfo dpc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 32, .poolSizeCount = 1, .pPoolSizes = &ps}; CK(vkCreateDescriptorPool(d, &dpc, NULL, &dp));
    int bad = 0;
    bad += run_case(0, 32, 32, 1, 0);    // Breath of the Wild's encoder target: a 32x32 level, 8x8 blocks
    bad += run_case(0, 32, 32, 32, 5);   // a depth plane of its 32x32x32 volume
    bad += run_case(0, 128, 64, 1, 0);   // more random blocks
    bad += run_case(1, 30, 18, 1, 0);    // edge blocks clipped on both sides
    bad += run_case(2, 12, 12, 1, 0);
    bad += run_case(3, 7, 5, 1, 0);
    bad += run_case(2, 64, 40, 4, 3);
    bad += run_case(1, 1, 1, 1, 0);      // a 1x1 mip level: one block, one texel kept
    printf("%s\n", bad ? "FAIL" : "all bytes match bcdec");
    return bad != 0;
}
