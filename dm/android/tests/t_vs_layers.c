// t_vs_layers: a vertex shader's layer into a layered framebuffer of 32 layers, as Pokemon Legends: Z-A builds its 32x32x32 colour-grading LUT (b29f08619f379a83, an
// instance per slice into a 3D image through a 2D_ARRAY view), drawn two ways: once, and once per 8 layers into views starting at layer 8g with the shader's layer
// less 8g from the push constant at byte 16, as gfx_vk_draw.inc vs_layer_groups and spv_layer.h spv_layer_base do where g_vs_layers is 8 (Arm's Mali driver). Arm's
// Mali-G715 driver (a Pixel 9 Pro XL, 0xd803000) drops every primitive whose layer from a vertex shader is 8 or more: the single draw reaches slices 0-7 alone there.
// Prints the slices each way reached; exit 0 when the per-group way puts every instance in its own slice. Build: aarch64-linux-android29-clang -O1 -Wall
// t_vs_layers.c -lvulkan; run it on the device (adb push, adb shell). The shaders, compiled by glslc --target-env=vulkan1.1 -O -mfmt=c:
//   vertex:   layout(push_constant) uniform P { layout(offset = 16) int base; } pc; layout(location = 0) flat out int inst; (GL_ARB_shader_draw_parameters,
//             GL_ARB_shader_viewport_layer_array) void main() { int i = gl_InstanceIndex - gl_BaseInstanceARB, v = gl_VertexIndex;
//             gl_Position = vec4(float((v >> 1) * 4 - 1), float(1 - (v & 1) * 4), 0.0, 1.0); gl_Layer = i - pc.base; inst = i; }
//   fragment: layout(location = 0) flat in int inst; layout(location = 0) out vec4 o; void main() { o = vec4(float(inst + 1) / 64.0, 0.0, 0.0, 1.0); }
#include <stdio.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define L 32
#define S 32
#define GROUP 8
#define CK(x) do { VkResult r_ = (x); if (r_) { printf("%s = %d\n", #x, r_); return 1; } } while (0)
static const uint32_t vs_spv[] = {0x07230203,0x00010300,0x000d000a,0x00000037,
0x00000000,0x00020011,0x00000001,0x00020011,
0x0000114b,0x00020011,0x00001486,0x000a000a,
0x5f565053,0x5f545845,0x64616873,0x765f7265,
0x70776569,0x5f74726f,0x65646e69,0x616c5f78,
0x00726579,0x0006000b,0x00000001,0x4c534c47,
0x6474732e,0x3035342e,0x00000000,0x0003000e,
0x00000000,0x00000001,0x000b000f,0x00000000,
0x00000004,0x6e69616d,0x00000000,0x0000000a,
0x0000000c,0x00000010,0x00000019,0x0000002d,
0x00000036,0x00040047,0x0000000a,0x0000000b,
0x0000002b,0x00040047,0x0000000c,0x0000000b,
0x00001149,0x00040047,0x00000010,0x0000000b,
0x0000002a,0x00050048,0x00000017,0x00000000,
0x0000000b,0x00000000,0x00050048,0x00000017,
0x00000001,0x0000000b,0x00000001,0x00050048,
0x00000017,0x00000002,0x0000000b,0x00000003,
0x00050048,0x00000017,0x00000003,0x0000000b,
0x00000004,0x00030047,0x00000017,0x00000002,
0x00040047,0x0000002d,0x0000000b,0x00000009,
0x00050048,0x0000002f,0x00000000,0x00000023,
0x00000010,0x00030047,0x0000002f,0x00000002,
0x00030047,0x00000036,0x0000000e,0x00040047,
0x00000036,0x0000001e,0x00000000,0x00020013,
0x00000002,0x00030021,0x00000003,0x00000002,
0x00040015,0x00000006,0x00000020,0x00000001,
0x00040020,0x00000009,0x00000001,0x00000006,
0x0004003b,0x00000009,0x0000000a,0x00000001,
0x0004003b,0x00000009,0x0000000c,0x00000001,
0x0004003b,0x00000009,0x00000010,0x00000001,
0x00030016,0x00000012,0x00000020,0x00040017,
0x00000013,0x00000012,0x00000004,0x00040015,
0x00000014,0x00000020,0x00000000,0x0004002b,
0x00000014,0x00000015,0x00000001,0x0004001c,
0x00000016,0x00000012,0x00000015,0x0006001e,
0x00000017,0x00000013,0x00000012,0x00000016,
0x00000016,0x00040020,0x00000018,0x00000003,
0x00000017,0x0004003b,0x00000018,0x00000019,
0x00000003,0x0004002b,0x00000006,0x0000001a,
0x00000000,0x0004002b,0x00000006,0x0000001c,
0x00000001,0x0004002b,0x00000006,0x0000001e,
0x00000004,0x0004002b,0x00000012,0x00000027,
0x00000000,0x0004002b,0x00000012,0x00000028,
0x3f800000,0x00040020,0x0000002a,0x00000003,
0x00000013,0x00040020,0x0000002c,0x00000003,
0x00000006,0x0004003b,0x0000002c,0x0000002d,
0x00000003,0x0003001e,0x0000002f,0x00000006,
0x00040020,0x00000030,0x00000009,0x0000002f,
0x0004003b,0x00000030,0x00000031,0x00000009,
0x00040020,0x00000032,0x00000009,0x00000006,
0x0004003b,0x0000002c,0x00000036,0x00000003,
0x00050036,0x00000002,0x00000004,0x00000000,
0x00000003,0x000200f8,0x00000005,0x0004003d,
0x00000006,0x0000000b,0x0000000a,0x0004003d,
0x00000006,0x0000000d,0x0000000c,0x00050082,
0x00000006,0x0000000e,0x0000000b,0x0000000d,
0x0004003d,0x00000006,0x00000011,0x00000010,
0x000500c3,0x00000006,0x0000001d,0x00000011,
0x0000001c,0x00050084,0x00000006,0x0000001f,
0x0000001d,0x0000001e,0x00050082,0x00000006,
0x00000020,0x0000001f,0x0000001c,0x0004006f,
0x00000012,0x00000021,0x00000020,0x000500c7,
0x00000006,0x00000023,0x00000011,0x0000001c,
0x00050084,0x00000006,0x00000024,0x00000023,
0x0000001e,0x00050082,0x00000006,0x00000025,
0x0000001c,0x00000024,0x0004006f,0x00000012,
0x00000026,0x00000025,0x00070050,0x00000013,
0x00000029,0x00000021,0x00000026,0x00000027,
0x00000028,0x00050041,0x0000002a,0x0000002b,
0x00000019,0x0000001a,0x0003003e,0x0000002b,
0x00000029,0x00050041,0x00000032,0x00000033,
0x00000031,0x0000001a,0x0004003d,0x00000006,
0x00000034,0x00000033,0x00050082,0x00000006,
0x00000035,0x0000000e,0x00000034,0x0003003e,
0x0000002d,0x00000035,0x0003003e,0x00000036,
0x0000000e,0x000100fd,0x00010038};
static const uint32_t fs_spv[] = {0x07230203,0x00010300,0x000d000a,0x00000017,
0x00000000,0x00020011,0x00000001,0x0006000b,
0x00000001,0x4c534c47,0x6474732e,0x3035342e,
0x00000000,0x0003000e,0x00000000,0x00000001,
0x0007000f,0x00000004,0x00000004,0x6e69616d,
0x00000000,0x00000009,0x0000000c,0x00030010,
0x00000004,0x00000007,0x00040047,0x00000009,
0x0000001e,0x00000000,0x00030047,0x0000000c,
0x0000000e,0x00040047,0x0000000c,0x0000001e,
0x00000000,0x00020013,0x00000002,0x00030021,
0x00000003,0x00000002,0x00030016,0x00000006,
0x00000020,0x00040017,0x00000007,0x00000006,
0x00000004,0x00040020,0x00000008,0x00000003,
0x00000007,0x0004003b,0x00000008,0x00000009,
0x00000003,0x00040015,0x0000000a,0x00000020,
0x00000001,0x00040020,0x0000000b,0x00000001,
0x0000000a,0x0004003b,0x0000000b,0x0000000c,
0x00000001,0x0004002b,0x0000000a,0x0000000e,
0x00000001,0x0004002b,0x00000006,0x00000013,
0x00000000,0x0004002b,0x00000006,0x00000014,
0x3f800000,0x0004002b,0x00000006,0x00000016,
0x3c800000,0x00050036,0x00000002,0x00000004,
0x00000000,0x00000003,0x000200f8,0x00000005,
0x0004003d,0x0000000a,0x0000000d,0x0000000c,
0x00050080,0x0000000a,0x0000000f,0x0000000d,
0x0000000e,0x0004006f,0x00000006,0x00000010,
0x0000000f,0x00050085,0x00000006,0x00000012,
0x00000010,0x00000016,0x00070050,0x00000007,
0x00000015,0x00000012,0x00000013,0x00000013,
0x00000014,0x0003003e,0x00000009,0x00000015,
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
    VkPhysicalDeviceShaderDrawParametersFeatures dpf = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SHADER_DRAW_PARAMETERS_FEATURES, .shaderDrawParameters = VK_TRUE};
    float pri = 1; VkDeviceQueueCreateInfo qc = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &pri};
    VkDeviceCreateInfo dc = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .pNext = &dpf, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qc};
    VkDevice d; CK(vkCreateDevice(pd, &dc, NULL, &d)); VkQueue q; vkGetDeviceQueue(d, 0, 0, &q);
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    VkFormat fmt = VK_FORMAT_A2B10G10R10_UNORM_PACK32;
    VkImageCreateInfo imc = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .flags = VK_IMAGE_CREATE_2D_ARRAY_COMPATIBLE_BIT, .imageType = VK_IMAGE_TYPE_3D, .format = fmt,
                             .extent = {S, S, L}, .mipLevels = 1, .arrayLayers = 1, .samples = 1, .tiling = VK_IMAGE_TILING_OPTIMAL,
                             .usage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT};
    VkImage img; CK(vkCreateImage(d, &imc, NULL, &img)); VkMemoryRequirements mr; vkGetImageMemoryRequirements(d, img, &mr);
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = mem_type(&mp, mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    VkDeviceMemory im; CK(vkAllocateMemory(d, &ma, NULL, &im)); CK(vkBindImageMemory(d, img, im, 0));
    VkBufferCreateInfo bc = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = S * S * L * 4, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    VkBuffer buf; CK(vkCreateBuffer(d, &bc, NULL, &buf)); vkGetBufferMemoryRequirements(d, buf, &mr);
    ma.allocationSize = mr.size; ma.memoryTypeIndex = mem_type(&mp, mr.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT);
    VkDeviceMemory bm; CK(vkAllocateMemory(d, &ma, NULL, &bm)); CK(vkBindBufferMemory(d, buf, bm, 0));
    uint32_t *p; CK(vkMapMemory(d, bm, 0, bc.size, 0, (void **)&p));
    // the first pass clears every slice; the per-group passes keep what the ones before drew
    VkAttachmentDescription at = {.format = fmt, .samples = 1, .loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR, .storeOp = VK_ATTACHMENT_STORE_OP_STORE, .stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE,
                                  .stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED, .finalLayout = VK_IMAGE_LAYOUT_GENERAL};
    VkAttachmentReference ar = {0, VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL}; VkSubpassDescription sp = {.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS, .colorAttachmentCount = 1, .pColorAttachments = &ar};
    VkRenderPassCreateInfo rc = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO, .attachmentCount = 1, .pAttachments = &at, .subpassCount = 1, .pSubpasses = &sp};
    VkRenderPass rp[2]; CK(vkCreateRenderPass(d, &rc, NULL, &rp[0])); at.loadOp = VK_ATTACHMENT_LOAD_OP_LOAD; at.initialLayout = VK_IMAGE_LAYOUT_GENERAL; CK(vkCreateRenderPass(d, &rc, NULL, &rp[1]));
    VkFramebuffer fb[L / GROUP];   // views from layer GROUP * g to the last
    for (int g = 0; g < L / GROUP; g++) {
        VkImageViewCreateInfo vc = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = img, .viewType = VK_IMAGE_VIEW_TYPE_2D_ARRAY, .format = fmt,
                                    .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, (uint32_t)(GROUP * g), (uint32_t)(L - GROUP * g)}};
        VkImageView iv; CK(vkCreateImageView(d, &vc, NULL, &iv));
        VkFramebufferCreateInfo fc = {.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .renderPass = rp[0], .attachmentCount = 1, .pAttachments = &iv, .width = S, .height = S, .layers = (uint32_t)(L - GROUP * g)};
        CK(vkCreateFramebuffer(d, &fc, NULL, &fb[g]));
    }
    VkPushConstantRange pr = {VK_SHADER_STAGE_VERTEX_BIT, 16, 4};
    VkPipelineLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr}; VkPipelineLayout pl; CK(vkCreatePipelineLayout(d, &lc, NULL, &pl));
    VkShaderModuleCreateInfo mv = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof vs_spv, .pCode = vs_spv}, mf = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof fs_spv, .pCode = fs_spv};
    VkShaderModule smv, smf; CK(vkCreateShaderModule(d, &mv, NULL, &smv)); CK(vkCreateShaderModule(d, &mf, NULL, &smf));
    VkPipelineShaderStageCreateInfo st[2] = {{.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = smv, .pName = "main"},
                                             {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = smf, .pName = "main"}};
    VkPipelineVertexInputStateCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia = {.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkViewport vp = {0, 0, S, S, 0, 1}; VkRect2D sc = {{0, 0}, {S, S}};
    VkPipelineViewportStateCreateInfo vs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount = 1, .pViewports = &vp, .scissorCount = 1, .pScissors = &sc};
    VkPipelineRasterizationStateCreateInfo rs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, .cullMode = VK_CULL_MODE_NONE, .lineWidth = 1};
    VkPipelineMultisampleStateCreateInfo ms = {.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, .rasterizationSamples = 1};
    VkPipelineColorBlendAttachmentState cba = {.colorWriteMask = 0xf}; VkPipelineColorBlendStateCreateInfo bs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO, .attachmentCount = 1, .pAttachments = &cba};
    VkGraphicsPipelineCreateInfo gc = {.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .stageCount = 2, .pStages = st, .pVertexInputState = &vi, .pInputAssemblyState = &ia, .pViewportState = &vs,
                                       .pRasterizationState = &rs, .pMultisampleState = &ms, .pColorBlendState = &bs, .layout = pl, .renderPass = rp[0]};
    VkPipeline pipe; CK(vkCreateGraphicsPipelines(d, VK_NULL_HANDLE, 1, &gc, NULL, &pipe));
    VkCommandPoolCreateInfo cpc = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT}; VkCommandPool cp; CK(vkCreateCommandPool(d, &cpc, NULL, &cp));
    VkCommandBufferAllocateInfo ca = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = cp, .commandBufferCount = 1}; VkCommandBuffer c; CK(vkAllocateCommandBuffers(d, &ca, &c));
    int good[2] = {0, 0};
    for (int way = 0; way < 2; way++) {   // 0: one draw; 1: the draw again per GROUP layers, as vs_layer_groups
        VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; CK(vkBeginCommandBuffer(c, &bi));
        VkClearValue cv = {.color = {.float32 = {0, 0, 0, 0}}};
        for (int g = 0; g < (way ? L / GROUP : 1); g++) {
            VkRenderPassBeginInfo rb = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, .renderPass = rp[g > 0], .framebuffer = fb[g], .renderArea = sc, .clearValueCount = 1, .pClearValues = &cv};
            vkCmdBeginRenderPass(c, &rb, VK_SUBPASS_CONTENTS_INLINE); vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pipe);
            int32_t base = GROUP * g; vkCmdPushConstants(c, pl, VK_SHADER_STAGE_VERTEX_BIT, 16, 4, &base);
            vkCmdDraw(c, 3, L, 0, 0); vkCmdEndRenderPass(c);
        }
        VkMemoryBarrier wb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT, .dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT};
        vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 1, &wb, 0, NULL, 0, NULL);
        VkBufferImageCopy rg = {.imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {S, S, L}};
        vkCmdCopyImageToBuffer(c, img, VK_IMAGE_LAYOUT_GENERAL, buf, 1, &rg);
        VkMemoryBarrier hb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &hb, 0, NULL, 0, NULL);
        CK(vkEndCommandBuffer(c));
        VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &c}; CK(vkQueueSubmit(q, 1, &si, VK_NULL_HANDLE)); CK(vkQueueWaitIdle(q));
        printf("%s:", way ? "per 8 layers" : "one draw    ");
        for (int z = 0; z < L; z++) {   // the instance each slice holds (red = (instance + 1) / 64), - for none
            uint32_t r = p[(size_t)z * S * S + (S / 2) * S + S / 2] & 1023; int i = r ? (int)(r * 64.0 / 1023 + 0.5) - 1 : -1;
            if (i < 0) printf(" -"); else printf(" %d", i);
            good[way] += i == z;
        }
        printf("  (%d of %d slices)\n", good[way], L);
        CK(vkResetCommandBuffer(c, 0));
    }
    printf("%s: a vertex shader's layer reaches %d of %d layers in one draw, %d drawn per %d\n", pp.deviceName, good[0], L, good[1], GROUP);
    return good[1] != L;
}
