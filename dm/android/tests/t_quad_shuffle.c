// t_quad_shuffle <vs.spv> <fs.spv>: whether a fragment shader's shuffles read the right lanes of each 2x2 quad on this GPU. Draws a full-screen triangle into a 64x64
// RGBA32UI image; the fragment shader (dm/tools/tests/test_spv_limits.py writes it, as translated and as spv_limits.h rewrites it) writes per pixel a hash of the
// coordinates of quad lane 0, of lane 3, of the horizontal neighbour and of the vertical one (Shuffle 0, Shuffle 3, ShuffleXor 1, ShuffleXor 2); checked here.
// Any 32 bits: the hashes include NaN and denormal patterns, which a float path that rounds or flushes would change. Exit 0 when every pixel is right.
// test_spv_limits.py builds and runs it on a device with DM_TEST_SERIAL=<adb serial>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define W 64
#define H 64
#define CK(x) do { VkResult r_ = (x); if (r_) { printf("%s = %d\n", #x, r_); return 1; } } while (0)
static uint32_t hash(uint32_t x, uint32_t y) { uint32_t h = x * 2654435761u ^ y * 2246822519u; h ^= h >> 15; h *= 739982445u; h ^= h >> 12; return h; }
static VkShaderModule mod(VkDevice d, const char *p) {
    FILE *f = fopen(p, "rb"); if (!f) return VK_NULL_HANDLE;
    static uint32_t buf[1 << 18]; size_t n = fread(buf, 1, sizeof buf, f); fclose(f);
    VkShaderModuleCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = n, .pCode = buf}; VkShaderModule m = VK_NULL_HANDLE;
    vkCreateShaderModule(d, &ci, NULL, &m); return m;
}
int main(int argc, char **argv) {
    if (argc < 3) return 2;
    VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
    VkInstance in; CK(vkCreateInstance(&ic, NULL, &in));
    uint32_t n = 1; VkPhysicalDevice pd; vkEnumeratePhysicalDevices(in, &n, &pd);
    VkPhysicalDeviceSubgroupProperties sg = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_PROPERTIES};
    VkPhysicalDeviceProperties2 p2 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &sg}; vkGetPhysicalDeviceProperties2(pd, &p2);
    printf("%s, subgroup size %u, stages %#x, ops %#x\n", p2.properties.deviceName, sg.subgroupSize, sg.supportedStages, sg.supportedOperations);
    float pri = 1; VkDeviceQueueCreateInfo qc = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &pri};
    VkDeviceCreateInfo dc = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qc};
    VkDevice d; CK(vkCreateDevice(pd, &dc, NULL, &d)); VkQueue q; vkGetDeviceQueue(d, 0, 0, &q);
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    VkImageCreateInfo imc = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_R32G32B32A32_UINT, .extent = {W, H, 1}, .mipLevels = 1,
                             .arrayLayers = 1, .samples = 1, .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT};
    VkImage img; CK(vkCreateImage(d, &imc, NULL, &img));
    VkMemoryRequirements mr; vkGetImageMemoryRequirements(d, img, &mr);
    uint32_t ti = 0; while (!(mr.memoryTypeBits & (1u << ti)) || !(mp.memoryTypes[ti].propertyFlags & VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)) ti++;
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = ti}; VkDeviceMemory im; CK(vkAllocateMemory(d, &ma, NULL, &im));
    CK(vkBindImageMemory(d, img, im, 0));
    VkBufferCreateInfo bc = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = W * H * 16, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT}; VkBuffer buf; CK(vkCreateBuffer(d, &bc, NULL, &buf));
    vkGetBufferMemoryRequirements(d, buf, &mr);
    ti = 0; while (!(mr.memoryTypeBits & (1u << ti)) || !(mp.memoryTypes[ti].propertyFlags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT) || !(mp.memoryTypes[ti].propertyFlags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) ti++;
    ma.allocationSize = mr.size; ma.memoryTypeIndex = ti; VkDeviceMemory bm; CK(vkAllocateMemory(d, &ma, NULL, &bm)); CK(vkBindBufferMemory(d, buf, bm, 0));
    VkImageViewCreateInfo vc = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = img, .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = imc.format, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    VkImageView iv; CK(vkCreateImageView(d, &vc, NULL, &iv));
    VkAttachmentDescription at = {.format = imc.format, .samples = 1, .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE, .stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE,
                                  .stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED, .finalLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL};
    VkAttachmentReference ar = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL}; VkSubpassDescription sp = {.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS, .colorAttachmentCount = 1, .pColorAttachments = &ar};
    VkRenderPassCreateInfo rc = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, .attachmentCount = 1, .pAttachments = &at, .subpassCount = 1, .pSubpasses = &sp}; VkRenderPass rp; CK(vkCreateRenderPass(d, &rc, NULL, &rp));
    VkFramebufferCreateInfo fc = {.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .renderPass = rp, .attachmentCount = 1, .pAttachments = &iv, .width = W, .height = H, .layers = 1}; VkFramebuffer fb; CK(vkCreateFramebuffer(d, &fc, NULL, &fb));
    VkPipelineLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO}; VkPipelineLayout pl; CK(vkCreatePipelineLayout(d, &lc, NULL, &pl));
    VkPipelineShaderStageCreateInfo st[2] = {{.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = mod(d, argv[1]), .pName = "main"},
                                             {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = mod(d, argv[2]), .pName = "main"}};
    if (!st[0].module || !st[1].module) { printf("no module\n"); return 1; }
    VkPipelineVertexInputStateCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia = {.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkViewport vp = {0, 0, W, H, 0, 1}; VkRect2D sc = {{0, 0}, {W, H}};
    VkPipelineViewportStateCreateInfo vs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount = 1, .pViewports = &vp, .scissorCount = 1, .pScissors = &sc};
    VkPipelineRasterizationStateCreateInfo rs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, .cullMode = VK_CULL_MODE_NONE, .lineWidth = 1};
    VkPipelineMultisampleStateCreateInfo ms = {.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, .rasterizationSamples = 1};
    VkPipelineColorBlendAttachmentState cb = {.colorWriteMask = 0xf}; VkPipelineColorBlendStateCreateInfo bs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, .attachmentCount = 1, .pAttachments = &cb};
    VkGraphicsPipelineCreateInfo gc = {.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .stageCount = 2, .pStages = st, .pVertexInputState = &vi, .pInputAssemblyState = &ia, .pViewportState = &vs,
                                       .pRasterizationState = &rs, .pMultisampleState = &ms, .pColorBlendState = &bs, .layout = pl, .renderPass = rp};
    VkPipeline p; printf("making the pipeline\n"); fflush(stdout); CK(vkCreateGraphicsPipelines(d, VK_NULL_HANDLE, 1, &gc, NULL, &p)); printf("made\n");
    VkCommandPoolCreateInfo cpc = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; VkCommandPool cp; CK(vkCreateCommandPool(d, &cpc, NULL, &cp));
    VkCommandBufferAllocateInfo ca = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = cp, .commandBufferCount = 1}; VkCommandBuffer c; CK(vkAllocateCommandBuffers(d, &ca, &c));
    VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; CK(vkBeginCommandBuffer(c, &bi));
    VkClearValue cv = {0}; VkRenderPassBeginInfo rb = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, .renderPass = rp, .framebuffer = fb, .renderArea = sc, .clearValueCount = 1, .pClearValues = &cv};
    vkCmdBeginRenderPass(c, &rb, VK_SUBPASS_CONTENTS_INLINE); vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_GRAPHICS, p); vkCmdDraw(c, 3, 1, 0, 0); vkCmdEndRenderPass(c);
    // the draw's writes before the copy reads them: without it the Pixel 9 Pro XL's Mali-G715 copied the cleared image (every channel 0), the Adreno happened not to
    VkMemoryBarrier wb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &wb, 0, NULL, 0, NULL);
    VkBufferImageCopy rg = {.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {W, H, 1}};
    vkCmdCopyImageToBuffer(c, img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buf, 1, &rg);
    VkMemoryBarrier mb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &mb, 0, NULL, 0, NULL);
    CK(vkEndCommandBuffer(c));
    VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &c}; CK(vkQueueSubmit(q, 1, &si, VK_NULL_HANDLE)); CK(vkQueueWaitIdle(q));
    uint32_t *px; CK(vkMapMemory(d, bm, 0, W * H * 16, 0, (void **)&px));
    int bad[4] = {0}; uint32_t shown = 0;
    for (uint32_t y = 0; y < H; y++) for (uint32_t x = 0; x < W; x++) {
        uint32_t x0 = x & ~1u, y0 = y & ~1u, want[4] = {hash(x0, y0), hash(x0 + 1, y0 + 1), hash(x ^ 1, y), hash(x, y ^ 1)};
        for (int k = 0; k < 4; k++) if (px[(y * W + x) * 4 + k] != want[k]) { bad[k]++; if (shown++ < 8) printf("(%u,%u) channel %d: %#x, want %#x (own %#x)\n", x, y, k, px[(y * W + x) * 4 + k], want[k], hash(x, y)); }
    }
    printf("%d pixels: wrong lane 0 %d, lane 3 %d, xor 1 %d, xor 2 %d\n", W * H, bad[0], bad[1], bad[2], bad[3]);
    return bad[0] || bad[1] || bad[2] || bad[3];
}
