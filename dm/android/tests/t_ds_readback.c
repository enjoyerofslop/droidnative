// t_ds_readback: whether this GPU copies a depth / stencil image's aspects to a buffer as gfx_vk.c ds_wb reads them (each aspect a tightly packed plane: depth 2 or 4
// bytes a texel, stencil 1), and what ds_texels.h then makes of them in NVN's layouts. For each depth / stencil format the GPU has (D16, D32F, D24S8, D32FS8), an image of
// 7x3 texels is cleared to a depth and a stencil, its left 4 columns cleared again to others (vkCmdClearDepthStencilImage takes whole subresources, so a 4x3 image
// is copied over them), then a 5x2 region at (2, 1) is copied out aspect by aspect, as ds_wb does, and rebuilt (ds_slice, as wb_apply). Then the other way, as ds_up:
// texels that differ one from the next are split into the planes (ds_slice_up), copied into that region, read back and rebuilt. Exit 0 when every texel is right.
// test_ds_texels.py builds and runs it on a device with DM_TEST_SERIAL=<adb serial>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#include "../ds_texels.h"
#define CK(x) do { VkResult r_ = (x); if (r_) { printf("%s = %d\n", #x, r_); return 1; } } while (0)
static VkDevice d; static VkPhysicalDevice pd; static VkPhysicalDeviceMemoryProperties mp; static VkQueue q; static VkCommandPool cp;
static uint32_t mem_type(uint32_t bits, VkMemoryPropertyFlags want) { for (uint32_t i = 0; i < mp.memoryTypeCount; i++) if ((bits >> i & 1) && (mp.memoryTypes[i].propertyFlags & want) == want) return i; return ~0u; }
static int image(VkFormat f, uint32_t w, uint32_t h, VkImage *img, VkDeviceMemory *m) {
    VkImageCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = f, .extent = {w, h, 1}, .mipLevels = 1, .arrayLayers = 1,
                            .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_TRANSFER_DST_BIT | VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT};
    CK(vkCreateImage(d, &ic, NULL, img)); VkMemoryRequirements mr; vkGetImageMemoryRequirements(d, *img, &mr);
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = mem_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    CK(vkAllocateMemory(d, &ma, NULL, m)); CK(vkBindImageMemory(d, *img, *m, 0)); return 0;
}
static void to_general(VkCommandBuffer c, VkImage img, VkImageAspectFlags a) {
    VkImageMemoryBarrier b = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .srcAccessMask = 0, .dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT | VK_ACCESS_TRANSFER_READ_BIT,
                              .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_GENERAL, .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED,
                              .image = img, .subresourceRange = {a, 0, 1, 0, 1}};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &b);
}
static void transfer_barrier(VkCommandBuffer c) {
    VkMemoryBarrier b = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT | VK_ACCESS_TRANSFER_WRITE_BIT | VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT | VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &b, 0, NULL, 0, NULL);
}
static int run(VkCommandBuffer *c) {   // a command buffer begun; submit(): ended, run and waited for
    VkCommandBufferAllocateInfo ca = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = cp, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    CK(vkAllocateCommandBuffers(d, &ca, c));
    VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT}; CK(vkBeginCommandBuffer(*c, &bi)); return 0;
}
static int submit(VkCommandBuffer c) {
    CK(vkEndCommandBuffer(c));
    VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &c}; CK(vkQueueSubmit(q, 1, &si, VK_NULL_HANDLE)); CK(vkQueueWaitIdle(q));
    vkFreeCommandBuffers(d, cp, 1, &c); return 0;
}
// One format read as one NVN format: → the number of wrong texels (0: right), -1: the GPU lacks it. dkind: the image's depth aspect (DS_NONE: it has none, S8_UINT)
static int check(VkFormat f, const char *name, int dkind, int has_s, int nvn_format) {
    VkFormatProperties fp; vkGetPhysicalDeviceFormatProperties(pd, f, &fp);
    if (!(fp.optimalTilingFeatures & VK_FORMAT_FEATURE_DEPTH_STENCIL_ATTACHMENT_BIT) || !(fp.optimalTilingFeatures & VK_FORMAT_FEATURE_TRANSFER_SRC_BIT)) { printf("%s: not on this GPU\n", name); return -1; }
    enum { W = 7, H = 3, RX = 2, RY = 1, RW = 5, RH = 2 };
    VkImageAspectFlags all = (dkind ? VK_IMAGE_ASPECT_DEPTH_BIT : 0) | (has_s ? VK_IMAGE_ASPECT_STENCIL_BIT : 0);
    int rd = nvn_format == 0x31 ? DS_NONE : dkind, rs = has_s && (nvn_format == 0x31 || nvn_format == 0x35 || nvn_format == 0x36);   // the aspects this NVN format reads, as ds_wb
    VkImage img, left; VkDeviceMemory im, lm; if (image(f, W, H, &img, &im) || image(f, 4, H, &left, &lm)) return 1;
    size_t n = RW * RH, soff = ds_sten_off(rd, n), size = ds_slice_bytes(rd, rs, n);
    VkBufferCreateInfo bc = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = size + 64, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT}; VkBuffer buf; CK(vkCreateBuffer(d, &bc, NULL, &buf));
    VkMemoryRequirements mr; vkGetBufferMemoryRequirements(d, buf, &mr);
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = mem_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
    VkDeviceMemory bm; CK(vkAllocateMemory(d, &ma, NULL, &bm)); CK(vkBindBufferMemory(d, buf, bm, 0));
    uint8_t *p; CK(vkMapMemory(d, bm, 0, VK_WHOLE_SIZE, 0, (void **)&p)); memset(p, 0xcd, size + 64);
    VkCommandBuffer c; if (run(&c)) return 1;
    to_general(c, img, all); to_general(c, left, all);
    VkClearDepthStencilValue cv = {0.75f, 0x5a}, lv = {0.25f, 0xc3}; VkImageSubresourceRange sr = {all, 0, 1, 0, 1};
    vkCmdClearDepthStencilImage(c, img, VK_IMAGE_LAYOUT_GENERAL, &cv, 1, &sr); vkCmdClearDepthStencilImage(c, left, VK_IMAGE_LAYOUT_GENERAL, &lv, 1, &sr);
    transfer_barrier(c);
    VkImageCopy ic = {.srcSubresource = {all, 0, 0, 1}, .dstSubresource = {all, 0, 0, 1}, .extent = {4, H, 1}}; vkCmdCopyImage(c, left, VK_IMAGE_LAYOUT_GENERAL, img, VK_IMAGE_LAYOUT_GENERAL, 1, &ic);
    transfer_barrier(c);
    for (int a = 0; a < 2; a++) {   // as ds_wb: the depth plane, then the stencil plane
        if (a ? !rs : !rd) continue;
        VkBufferImageCopy rc = {.bufferOffset = a ? soff : 0, .imageSubresource = {a ? VK_IMAGE_ASPECT_STENCIL_BIT : VK_IMAGE_ASPECT_DEPTH_BIT, 0, 0, 1}, .imageOffset = {RX, RY, 0}, .imageExtent = {RW, RH, 1}};
        vkCmdCopyImageToBuffer(c, img, VK_IMAGE_LAYOUT_GENERAL, buf, 1, &rc);
    }
    transfer_barrier(c); if (submit(c)) return 1;
    int bad = 0; size_t tb = ds_texel_bytes(nvn_format); uint8_t tex[RH][RW * 8 + 3]; memset(tex, 0xee, sizeof tex);
    ds_slice(nvn_format, rd, rs, p, RW, RH, tex[0], sizeof tex[0]);   // as wb_apply
    for (int y = 0; y < RH; y++) {
        for (int x = 0; x < RW; x++) {
            int l = RX + x < 4; float want_d = l ? 0.25f : 0.75f; uint8_t want_s = l ? 0xc3 : 0x5a; const uint8_t *t = tex[y] + (size_t)x * tb; int ok = 1;
            switch (nvn_format) {
            case 0x31: ok = t[0] == want_s; break;
            case 0x32: { uint16_t v; memcpy(&v, t, 2); int e = (int)(want_d * 65535.0f + 0.5f); ok = v >= e - 1 && v <= e + 1; break; }   // (unorm rounding is the GPU's: within 1)
            case 0x33: { uint32_t v; memcpy(&v, t, 4); ok = v == ds_unorm24(want_d) || v + 1 == ds_unorm24(want_d) || v == ds_unorm24(want_d) + 1; break; }
            case 0x34: { float v; memcpy(&v, t, 4); ok = v == want_d; break; }
            case 0x35: { uint32_t v; memcpy(&v, t, 4); uint32_t dd = v & 0xffffff; ok = (v >> 24) == want_s && (dd == ds_unorm24(want_d) || dd + 1 == ds_unorm24(want_d) || dd == ds_unorm24(want_d) + 1); break; }
            case 0x36: { float v; memcpy(&v, t, 4); ok = (dkind == DS_D32F ? v == want_d : v > want_d - 1e-6f && v < want_d + 1e-6f) && t[4] == want_s && !t[5] && !t[6] && !t[7]; break; }
            }
            if (!ok) { if (bad < 4) { printf("%s as %#x: texel (%d, %d) wrong:", name, nvn_format, RX + x, RY + y); for (size_t i = 0; i < tb; i++) printf(" %02x", t[i]); printf("\n"); } bad++; }
        }
        for (size_t i = RW * tb; i < sizeof tex[y]; i++) if (tex[y][i] != 0xee) { printf("%s as %#x: row %d written past its texels\n", name, nvn_format, y); bad++; break; }
    }
    for (size_t i = size; i < size + 64; i++) if (p[i] != 0xcd) { printf("%s: the copy wrote past its planes (byte %zu)\n", name, i); bad++; break; }
    printf("%s as NVN %#x: %s\n", name, nvn_format, bad ? "WRONG" : "right");
    // The other way, as gfx_vk.c ds_up: texels that differ one from the next are split into the planes, copied into the region aspect by aspect, read back and rebuilt
    int up = 0;
    if (!(fp.optimalTilingFeatures & VK_FORMAT_FEATURE_TRANSFER_DST_BIT)) printf("%s: not a copy destination on this GPU (the upload is not checked)\n", name);
    else {
        uint8_t pat[RH][RW * 8], got[RH][RW * 8]; memset(pat, 0, sizeof pat); memset(got, 0xee, sizeof got);
        for (int i = 0; i < RW * RH; i++) {
            uint8_t *t = pat[i / RW] + (size_t)(i % RW) * tb, st = (uint8_t)(0x11 * i + 1); float fd = (float)i / (RW * RH - 1); uint32_t u = i == RW * RH - 1 ? 0xffffffu : 0x1b4e81u * (uint32_t)i & 0xffffffu; uint16_t h = (uint16_t)(0x1c71 * i);
            switch (nvn_format) {
            case 0x31: t[0] = st; break;
            case 0x32: memcpy(t, &h, 2); break;
            case 0x33: memcpy(t, &u, 4); break;
            case 0x34: memcpy(t, &fd, 4); break;
            case 0x35: u |= (uint32_t)st << 24; memcpy(t, &u, 4); break;
            case 0x36: memcpy(t, &fd, 4); t[4] = st; break;
            }
        }
        memset(p, 0, size); ds_slice_up(nvn_format, rd, rs, pat[0], sizeof pat[0], RW, RH, p);
        if (run(&c)) return 1;
        for (int a = 0; a < 2; a++) {
            if (a ? !rs : !rd) continue;
            VkBufferImageCopy rc = {.bufferOffset = a ? soff : 0, .imageSubresource = {a ? VK_IMAGE_ASPECT_STENCIL_BIT : VK_IMAGE_ASPECT_DEPTH_BIT, 0, 0, 1}, .imageOffset = {RX, RY, 0}, .imageExtent = {RW, RH, 1}};
            vkCmdCopyBufferToImage(c, buf, img, VK_IMAGE_LAYOUT_GENERAL, 1, &rc);
        }
        transfer_barrier(c); if (submit(c)) return 1;
        memset(p, 0xcd, size + 64); if (run(&c)) return 1;
        for (int a = 0; a < 2; a++) {
            if (a ? !rs : !rd) continue;
            VkBufferImageCopy rc = {.bufferOffset = a ? soff : 0, .imageSubresource = {a ? VK_IMAGE_ASPECT_STENCIL_BIT : VK_IMAGE_ASPECT_DEPTH_BIT, 0, 0, 1}, .imageOffset = {RX, RY, 0}, .imageExtent = {RW, RH, 1}};
            vkCmdCopyImageToBuffer(c, img, VK_IMAGE_LAYOUT_GENERAL, buf, 1, &rc);
        }
        transfer_barrier(c); if (submit(c)) return 1;
        ds_slice(nvn_format, rd, rs, p, RW, RH, got[0], sizeof got[0]);
        for (int i = 0; i < RW * RH; i++) {
            const uint8_t *w = pat[i / RW] + (size_t)(i % RW) * tb, *g = got[i / RW] + (size_t)(i % RW) * tb; int ok = !memcmp(w, g, tb);
            if (!ok && dkind == DS_D24 && (nvn_format == 0x34 || nvn_format == 0x36)) { float a, b; memcpy(&a, w, 4); memcpy(&b, g, 4); ok = b > a - 1e-6f && b < a + 1e-6f && (tb == 4 || !memcmp(w + 4, g + 4, 4)); }   // a float through 24 bits
            if (!ok) { if (up < 4) { printf("%s as %#x: uploaded texel %d came back wrong:", name, nvn_format, i); for (size_t k = 0; k < tb; k++) printf(" %02x", g[k]); printf(" (sent"); for (size_t k = 0; k < tb; k++) printf(" %02x", w[k]); printf(")\n"); } up++; }
        }
        printf("%s as NVN %#x, uploaded and read back: %s\n", name, nvn_format, up ? "WRONG" : "right");
    }
    vkUnmapMemory(d, bm); vkDestroyBuffer(d, buf, NULL); vkFreeMemory(d, bm, NULL);
    vkDestroyImage(d, img, NULL); vkFreeMemory(d, im, NULL); vkDestroyImage(d, left, NULL); vkFreeMemory(d, lm, NULL);
    return bad + up;
}
int main(void) {
    VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
    VkInstance in; CK(vkCreateInstance(&ic, NULL, &in));
    uint32_t n = 1; vkEnumeratePhysicalDevices(in, &n, &pd);
    VkPhysicalDeviceProperties pp; vkGetPhysicalDeviceProperties(pd, &pp); printf("%s, driver %#x\n", pp.deviceName, pp.driverVersion);
    vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    float pri = 1; VkDeviceQueueCreateInfo qc = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &pri};
    VkDeviceCreateInfo dc = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qc};
    CK(vkCreateDevice(pd, &dc, NULL, &d)); vkGetDeviceQueue(d, 0, 0, &q);
    VkCommandPoolCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = 0}; CK(vkCreateCommandPool(d, &pc, NULL, &cp));
    int bad = 0, r;
    struct { VkFormat f; const char *name; int dkind, s, nvn; } t[] = {
        {VK_FORMAT_S8_UINT, "S8_UINT", DS_NONE, 1, 0x31},
        {VK_FORMAT_D32_SFLOAT_S8_UINT, "D32_SFLOAT_S8_UINT", DS_D32F, 1, 0x31},
        {VK_FORMAT_D24_UNORM_S8_UINT, "D24_UNORM_S8_UINT", DS_D24, 1, 0x31},
        {VK_FORMAT_D32_SFLOAT, "D32_SFLOAT", DS_D32F, 0, 0x33},
        {VK_FORMAT_D16_UNORM, "D16_UNORM", DS_D16, 0, 0x32},
        {VK_FORMAT_D32_SFLOAT, "D32_SFLOAT", DS_D32F, 0, 0x34},
        {VK_FORMAT_D32_SFLOAT_S8_UINT, "D32_SFLOAT_S8_UINT", DS_D32F, 1, 0x36},
        {VK_FORMAT_D32_SFLOAT_S8_UINT, "D32_SFLOAT_S8_UINT", DS_D32F, 1, 0x35},
        {VK_FORMAT_D24_UNORM_S8_UINT, "D24_UNORM_S8_UINT", DS_D24, 1, 0x35},
        {VK_FORMAT_D24_UNORM_S8_UINT, "D24_UNORM_S8_UINT", DS_D24, 1, 0x36},
    };
    for (size_t i = 0; i < sizeof t / sizeof *t; i++) if ((r = check(t[i].f, t[i].name, t[i].dkind, t[i].s, t[i].nvn)) > 0) bad += r;
    printf("%d wrong\n", bad);
    return bad != 0;
}
