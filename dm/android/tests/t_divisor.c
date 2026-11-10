// t_divisor: a vertex stream stepping once every 3 instances, drawn at base instance 5 as NVN numbers it (element = base instance + (instance - base instance) / divisor),
// two ways: from instance 0 with the base instance in the stream's offset, as gfx_vk_draw.inc inst_shift does where the divisor cannot start past instance 0
// (VK_KHR_vertex_attribute_divisor without supportsNonZeroFirstInstance: the Pixel 9 Pro XL's Mali-G715), and with the base instance as firstInstance, which only a
// device that supports it is held to. One point per instance into an 8x1 R32_UINT image, then read back. Exit 0 when the offset way is right everywhere, and the
// first-instance way too where the device supports it. Build: aarch64-linux-android29-clang -O1 -Wall t_divisor.c -lvulkan; run it on the device (adb push, adb shell).
// The shaders, compiled by glslc --target-env=vulkan1.1 -O -mfmt=c:
//   vertex:   layout(location = 0) in uint elem; layout(location = 0) flat out uint v; (GL_ARB_shader_draw_parameters)
//             void main() { int i = gl_InstanceIndex - gl_BaseInstanceARB; gl_Position = vec4((float(i) + 0.5) / 8.0 * 2.0 - 1.0, 0.0, 0.0, 1.0); gl_PointSize = 1.0; v = elem; }
//   fragment: layout(location = 0) flat in uint v; layout(location = 0) out uint o; void main() { o = v; }
#include <stdio.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define N 8
#define DIV 3
#define BASE 5
#define CK(x) do { VkResult r_ = (x); if (r_) { printf("%s = %d\n", #x, r_); return 1; } } while (0)
static const uint32_t vs_spv[] = {0x07230203,0x00010300,0x000d000a,0x00000032,
0x00000000,0x00020011,0x00000001,0x00020011,
0x0000114b,0x0006000b,0x00000001,0x4c534c47,
0x6474732e,0x3035342e,0x00000000,0x0003000e,
0x00000000,0x00000001,0x000a000f,0x00000000,
0x00000004,0x6e69616d,0x00000000,0x0000000a,
0x0000000c,0x00000016,0x0000002a,0x0000002c,
0x00040047,0x0000000a,0x0000000b,0x0000002b,
0x00040047,0x0000000c,0x0000000b,0x00001149,
0x00050048,0x00000014,0x00000000,0x0000000b,
0x00000000,0x00050048,0x00000014,0x00000001,
0x0000000b,0x00000001,0x00050048,0x00000014,
0x00000002,0x0000000b,0x00000003,0x00050048,
0x00000014,0x00000003,0x0000000b,0x00000004,
0x00030047,0x00000014,0x00000002,0x00030047,
0x0000002a,0x0000000e,0x00040047,0x0000002a,
0x0000001e,0x00000000,0x00040047,0x0000002c,
0x0000001e,0x00000000,0x00020013,0x00000002,
0x00030021,0x00000003,0x00000002,0x00040015,
0x00000006,0x00000020,0x00000001,0x00040020,
0x00000009,0x00000001,0x00000006,0x0004003b,
0x00000009,0x0000000a,0x00000001,0x0004003b,
0x00000009,0x0000000c,0x00000001,0x00030016,
0x0000000f,0x00000020,0x00040017,0x00000010,
0x0000000f,0x00000004,0x00040015,0x00000011,
0x00000020,0x00000000,0x0004002b,0x00000011,
0x00000012,0x00000001,0x0004001c,0x00000013,
0x0000000f,0x00000012,0x0006001e,0x00000014,
0x00000010,0x0000000f,0x00000013,0x00000013,
0x00040020,0x00000015,0x00000003,0x00000014,
0x0004003b,0x00000015,0x00000016,0x00000003,
0x0004002b,0x00000006,0x00000017,0x00000000,
0x0004002b,0x0000000f,0x0000001a,0x3f000000,
0x0004002b,0x0000000f,0x00000020,0x3f800000,
0x0004002b,0x0000000f,0x00000022,0x00000000,
0x00040020,0x00000024,0x00000003,0x00000010,
0x0004002b,0x00000006,0x00000026,0x00000001,
0x00040020,0x00000027,0x00000003,0x0000000f,
0x00040020,0x00000029,0x00000003,0x00000011,
0x0004003b,0x00000029,0x0000002a,0x00000003,
0x00040020,0x0000002b,0x00000001,0x00000011,
0x0004003b,0x0000002b,0x0000002c,0x00000001,
0x0004002b,0x0000000f,0x0000002f,0x3e800000,
0x0004002b,0x0000000f,0x00000031,0xbf800000,
0x00050036,0x00000002,0x00000004,0x00000000,
0x00000003,0x000200f8,0x00000005,0x0004003d,
0x00000006,0x0000000b,0x0000000a,0x0004003d,
0x00000006,0x0000000d,0x0000000c,0x00050082,
0x00000006,0x0000000e,0x0000000b,0x0000000d,
0x0004006f,0x0000000f,0x00000019,0x0000000e,
0x00050081,0x0000000f,0x0000001b,0x00000019,
0x0000001a,0x0008000c,0x0000000f,0x00000021,
0x00000001,0x00000032,0x0000001b,0x0000002f,
0x00000031,0x00070050,0x00000010,0x00000023,
0x00000021,0x00000022,0x00000022,0x00000020,
0x00050041,0x00000024,0x00000025,0x00000016,
0x00000017,0x0003003e,0x00000025,0x00000023,
0x00050041,0x00000027,0x00000028,0x00000016,
0x00000026,0x0003003e,0x00000028,0x00000020,
0x0004003d,0x00000011,0x0000002d,0x0000002c,
0x0003003e,0x0000002a,0x0000002d,0x000100fd,
0x00010038};
static const uint32_t fs_spv[] = {0x07230203,0x00010300,0x000d000a,0x0000000c,
0x00000000,0x00020011,0x00000001,0x0006000b,
0x00000001,0x4c534c47,0x6474732e,0x3035342e,
0x00000000,0x0003000e,0x00000000,0x00000001,
0x0007000f,0x00000004,0x00000004,0x6e69616d,
0x00000000,0x00000008,0x0000000a,0x00030010,
0x00000004,0x00000007,0x00040047,0x00000008,
0x0000001e,0x00000000,0x00030047,0x0000000a,
0x0000000e,0x00040047,0x0000000a,0x0000001e,
0x00000000,0x00020013,0x00000002,0x00030021,
0x00000003,0x00000002,0x00040015,0x00000006,
0x00000020,0x00000000,0x00040020,0x00000007,
0x00000003,0x00000006,0x0004003b,0x00000007,
0x00000008,0x00000003,0x00040020,0x00000009,
0x00000001,0x00000006,0x0004003b,0x00000009,
0x0000000a,0x00000001,0x00050036,0x00000002,
0x00000004,0x00000000,0x00000003,0x000200f8,
0x00000005,0x0004003d,0x00000006,0x0000000b,
0x0000000a,0x0003003e,0x00000008,0x0000000b,
0x000100fd,0x00010038};
static uint32_t mem_type(const VkPhysicalDeviceMemoryProperties *mp, uint32_t bits, VkMemoryPropertyFlags want) {
    for (uint32_t i = 0; i < mp->memoryTypeCount; i++) if ((bits >> i & 1) && (mp->memoryTypes[i].propertyFlags & want) == want) return i;
    return 0;
}
int main(void) {
    VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
    VkInstance in; CK(vkCreateInstance(&ic, NULL, &in));
    uint32_t n = 1; VkPhysicalDevice pd; vkEnumeratePhysicalDevices(in, &n, &pd);
    VkPhysicalDeviceProperties pp; vkGetPhysicalDeviceProperties(pd, &pp);
    uint32_t ne = 0; vkEnumerateDeviceExtensionProperties(pd, NULL, &ne, NULL); VkExtensionProperties ex[512]; if (ne > 512) ne = 512; vkEnumerateDeviceExtensionProperties(pd, NULL, &ne, ex);
    const char *ext = NULL; for (uint32_t i = 0; i < ne; i++) if (!strcmp(ex[i].extensionName, "VK_EXT_vertex_attribute_divisor")) ext = ex[i].extensionName;
    for (uint32_t i = 0; i < ne && !ext; i++) if (!strcmp(ex[i].extensionName, "VK_KHR_vertex_attribute_divisor")) ext = ex[i].extensionName;
    if (!ext) { printf("%s: no vertex attribute divisor extension\n", pp.deviceName); return 2; }
    int nonzero = 1;   // the EXT has no property for it
    if (!strcmp(ext, "VK_KHR_vertex_attribute_divisor")) {
        VkPhysicalDeviceVertexAttributeDivisorPropertiesKHR dp = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VERTEX_ATTRIBUTE_DIVISOR_PROPERTIES_KHR};
        VkPhysicalDeviceProperties2 p2 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &dp}; vkGetPhysicalDeviceProperties2(pd, &p2); nonzero = dp.supportsNonZeroFirstInstance;
    }
    printf("%s: %s, a non-zero first instance with a divisor %s\n", pp.deviceName, ext, nonzero ? "supported" : "not supported");
    VkPhysicalDeviceVertexAttributeDivisorFeaturesEXT dvf = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VERTEX_ATTRIBUTE_DIVISOR_FEATURES_EXT, .vertexAttributeInstanceRateDivisor = VK_TRUE};
    VkPhysicalDeviceShaderDrawParametersFeatures dpf = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_DRAW_PARAMETERS_FEATURES, .pNext = &dvf, .shaderDrawParameters = VK_TRUE};
    float pri = 1; VkDeviceQueueCreateInfo qc = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &pri};
    VkDeviceCreateInfo dc = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .pNext = &dpf, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qc, .enabledExtensionCount = 1, .ppEnabledExtensionNames = &ext};
    VkDevice d; CK(vkCreateDevice(pd, &dc, NULL, &d)); VkQueue q; vkGetDeviceQueue(d, 0, 0, &q);
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    VkImageCreateInfo imc = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_R32_UINT, .extent = {N, 1, 1}, .mipLevels = 1, .arrayLayers = 1,
                             .samples = 1, .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT};
    VkImage img; CK(vkCreateImage(d, &imc, NULL, &img)); VkMemoryRequirements mr; vkGetImageMemoryRequirements(d, img, &mr);
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = mem_type(&mp, mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    VkDeviceMemory im; CK(vkAllocateMemory(d, &ma, NULL, &im)); CK(vkBindImageMemory(d, img, im, 0));
    VkBufferCreateInfo bc = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = 256, .usage = VK_BUFFER_USAGE_VERTEX_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    VkBuffer buf; CK(vkCreateBuffer(d, &bc, NULL, &buf)); vkGetBufferMemoryRequirements(d, buf, &mr);
    ma.allocationSize = mr.size; ma.memoryTypeIndex = mem_type(&mp, mr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkDeviceMemory bm; CK(vkAllocateMemory(d, &ma, NULL, &bm)); CK(vkBindBufferMemory(d, buf, bm, 0));
    uint32_t *p; CK(vkMapMemory(d, bm, 0, 256, 0, (void **)&p)); for (int i = 0; i < 32; i++) p[i] = 100 + i;   // the stream: element k holds 100 + k; read back into words 32..39
    VkImageViewCreateInfo vc = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = img, .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = imc.format, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    VkImageView iv; CK(vkCreateImageView(d, &vc, NULL, &iv));
    VkAttachmentDescription at = {.format = imc.format, .samples = 1, .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE, .stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE,
                                  .stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED, .finalLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL};
    VkAttachmentReference ar = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL}; VkSubpassDescription sp = {.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS, .colorAttachmentCount = 1, .pColorAttachments = &ar};
    VkRenderPassCreateInfo rc = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, .attachmentCount = 1, .pAttachments = &at, .subpassCount = 1, .pSubpasses = &sp}; VkRenderPass rp; CK(vkCreateRenderPass(d, &rc, NULL, &rp));
    VkFramebufferCreateInfo fc = {.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .renderPass = rp, .attachmentCount = 1, .pAttachments = &iv, .width = N, .height = 1, .layers = 1}; VkFramebuffer fb; CK(vkCreateFramebuffer(d, &fc, NULL, &fb));
    VkPipelineLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO}; VkPipelineLayout pl; CK(vkCreatePipelineLayout(d, &lc, NULL, &pl));
    VkShaderModuleCreateInfo mv = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof vs_spv, .pCode = vs_spv}, mf = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof fs_spv, .pCode = fs_spv};
    VkShaderModule smv, smf; CK(vkCreateShaderModule(d, &mv, NULL, &smv)); CK(vkCreateShaderModule(d, &mf, NULL, &smf));
    VkPipelineShaderStageCreateInfo st[2] = {{.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = smv, .pName = "main"},
                                             {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = smf, .pName = "main"}};
    VkVertexInputBindingDescription vb = {0, 4, VK_VERTEX_INPUT_RATE_INSTANCE}; VkVertexInputAttributeDescription va = {0, 0, VK_FORMAT_R32_UINT, 0};
    VkVertexInputBindingDivisorDescriptionEXT vd = {0, DIV};
    VkPipelineVertexInputDivisorStateCreateInfoEXT vds = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_DIVISOR_STATE_CREATE_INFO_EXT, .vertexBindingDivisorCount = 1, .pVertexBindingDivisors = &vd};
    VkPipelineVertexInputStateCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO, .pNext = &vds, .vertexBindingDescriptionCount = 1, .pVertexBindingDescriptions = &vb,
                                               .vertexAttributeDescriptionCount = 1, .pVertexAttributeDescriptions = &va};
    VkPipelineInputAssemblyStateCreateInfo ia = {.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, .topology = VK_PRIMITIVE_TOPOLOGY_POINT_LIST};
    VkViewport vp = {0, 0, N, 1, 0, 1}; VkRect2D sc = {{0, 0}, {N, 1}};
    VkPipelineViewportStateCreateInfo vs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount = 1, .pViewports = &vp, .scissorCount = 1, .pScissors = &sc};
    VkPipelineRasterizationStateCreateInfo rs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, .cullMode = VK_CULL_MODE_NONE, .lineWidth = 1};
    VkPipelineMultisampleStateCreateInfo ms = {.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, .rasterizationSamples = 1};
    VkPipelineColorBlendAttachmentState cba = {.colorWriteMask = 0xf}; VkPipelineColorBlendStateCreateInfo bs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, .attachmentCount = 1, .pAttachments = &cba};
    VkGraphicsPipelineCreateInfo gc = {.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .stageCount = 2, .pStages = st, .pVertexInputState = &vi, .pInputAssemblyState = &ia, .pViewportState = &vs,
                                       .pRasterizationState = &rs, .pMultisampleState = &ms, .pColorBlendState = &bs, .layout = pl, .renderPass = rp};
    VkPipeline pipe; CK(vkCreateGraphicsPipelines(d, VK_NULL_HANDLE, 1, &gc, NULL, &pipe));
    VkCommandPoolCreateInfo cpc = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT}; VkCommandPool cp; CK(vkCreateCommandPool(d, &cpc, NULL, &cp));
    VkCommandBufferAllocateInfo ca = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = cp, .commandBufferCount = 1}; VkCommandBuffer c; CK(vkAllocateCommandBuffers(d, &ca, &c));
    int bad[2] = {0, 0};
    for (int way = 0; way < 2; way++) {   // 0: from instance 0, the base instance in the offset (inst_shift); 1: firstInstance = the base instance
        VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; CK(vkBeginCommandBuffer(c, &bi));
        VkClearValue cv = {.color = {.uint32 = {0xffffffffu}}}; VkRenderPassBeginInfo rb = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, .renderPass = rp, .framebuffer = fb, .renderArea = sc, .clearValueCount = 1, .pClearValues = &cv};
        vkCmdBeginRenderPass(c, &rb, VK_SUBPASS_CONTENTS_INLINE); vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pipe);
        VkDeviceSize off = way ? 0 : BASE * 4; vkCmdBindVertexBuffers(c, 0, 1, &buf, &off);
        vkCmdDraw(c, 1, N, 0, way ? BASE : 0); vkCmdEndRenderPass(c);
        VkMemoryBarrier wb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT};
        vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &wb, 0, NULL, 0, NULL);
        VkBufferImageCopy rg = {.bufferOffset = 128, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {N, 1, 1}};
        vkCmdCopyImageToBuffer(c, img, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, buf, 1, &rg);
        VkMemoryBarrier hb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &hb, 0, NULL, 0, NULL);
        CK(vkEndCommandBuffer(c));
        VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &c}; CK(vkQueueSubmit(q, 1, &si, VK_NULL_HANDLE)); CK(vkQueueWaitIdle(q));
        printf("%s:", way ? "firstInstance 5     " : "offset, instance 0  ");
        for (int i = 0; i < N; i++) { uint32_t want = 100 + BASE + i / DIV; printf(" %u", p[32 + i]); bad[way] += p[32 + i] != want; }
        printf("  (want"); for (int i = 0; i < N; i++) printf(" %u", 100 + BASE + i / DIV); printf("): %d wrong\n", bad[way]);
        CK(vkResetCommandBuffer(c, 0));
    }
    return bad[0] || (nonzero && bad[1]);
}
