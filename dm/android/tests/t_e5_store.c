// t_e5_store <comp.spv> <in.bin> <out.bin>: whether a compute shader rewritten by spv_e5.h stores RGB9E5 as Vulkan specifies, through an R32_UINT view of an
// E5B9G9R9 image (MUTABLE_FORMAT, EXTENDED_USAGE: storage for that view only), as the replay binds one (gfx_vk.c vt_storage_up). One workgroup of 16 x 16; in.bin
// holds its 256 vec4 texels (a storage buffer at binding 0), the image is at binding 1, and the image's 256 words are copied out to out.bin.
// dm/tools/tests/test_spv_e5.py builds and runs it on a device with DM_TEST_SERIAL=<adb serial>, and compares the words with the specification's conversion
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <vulkan/vulkan.h>
#define CK(x) do { VkResult r_ = (x); if (r_) { printf("%s = %d\n", #x, r_); return 1; } } while (0)
static uint32_t mem_type(VkPhysicalDeviceMemoryProperties *mp, uint32_t bits, VkMemoryPropertyFlags want) {
    for (uint32_t i = 0; i < mp->memoryTypeCount; i++) if ((bits & (1u << i)) && (mp->memoryTypes[i].propertyFlags & want) == want) return i;
    return 0;
}
int main(int argc, char **argv) {
    if (argc < 4) return 2;
    static uint32_t code[1 << 16]; static float in[256 * 4];
    FILE *f = fopen(argv[1], "rb"); if (!f) return 2; size_t nb = fread(code, 1, sizeof code, f); fclose(f);
    f = fopen(argv[2], "rb"); if (!f || fread(in, 1, sizeof in, f) != sizeof in) return 2; fclose(f);
    VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
    VkInstance inst; CK(vkCreateInstance(&ic, NULL, &inst));
    uint32_t n = 1; VkPhysicalDevice pd; vkEnumeratePhysicalDevices(inst, &n, &pd);
    VkPhysicalDeviceProperties pp; vkGetPhysicalDeviceProperties(pd, &pp);
    VkFormatProperties e5p, u32p; vkGetPhysicalDeviceFormatProperties(pd, VK_FORMAT_E5B9G9R9_UFLOAT_PACK32, &e5p); vkGetPhysicalDeviceFormatProperties(pd, VK_FORMAT_R32_UINT, &u32p);
    printf("%s, E5B9G9R9 storage %s, R32_UINT storage %s\n", pp.deviceName, e5p.optimalTilingFeatures & VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT ? "yes" : "no",
           u32p.optimalTilingFeatures & VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT ? "yes" : "no");
    float pri = 1; VkDeviceQueueCreateInfo qc = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &pri};
    VkDeviceCreateInfo dc = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qc};
    VkDevice d; CK(vkCreateDevice(pd, &dc, NULL, &d)); VkQueue q; vkGetDeviceQueue(d, 0, 0, &q);
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    const VkMemoryPropertyFlags host = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    VkBuffer bufs[2]; VkDeviceMemory bmem[2]; void *bp[2]; const VkDeviceSize bsz[2] = {sizeof in, 256 * 4};
    const VkBufferUsageFlags bu[2] = {VK_BUFFER_USAGE_STORAGE_BUFFER_BIT, VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    for (int i = 0; i < 2; i++) {   // the texels in, the image's words out
        VkBufferCreateInfo bc = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = bsz[i], .usage = bu[i]}; CK(vkCreateBuffer(d, &bc, NULL, &bufs[i]));
        VkMemoryRequirements mr; vkGetBufferMemoryRequirements(d, bufs[i], &mr);
        VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = mem_type(&mp, mr.memoryTypeBits, host)};
        CK(vkAllocateMemory(d, &ma, NULL, &bmem[i])); CK(vkBindBufferMemory(d, bufs[i], bmem[i], 0)); CK(vkMapMemory(d, bmem[i], 0, bsz[i], 0, &bp[i]));
    }
    memcpy(bp[0], in, sizeof in); memset(bp[1], 0xab, 256 * 4);
    VkImageCreateInfo imc = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .flags = VK_IMAGE_CREATE_MUTABLE_FORMAT_BIT | VK_IMAGE_CREATE_EXTENDED_USAGE_BIT, .imageType = VK_IMAGE_TYPE_2D,
        .format = VK_FORMAT_E5B9G9R9_UFLOAT_PACK32, .extent = {16, 16, 1}, .mipLevels = 1, .arrayLayers = 1, .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL,
        .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT | VK_IMAGE_USAGE_SAMPLED_BIT, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED};
    VkImage img; CK(vkCreateImage(d, &imc, NULL, &img));
    VkMemoryRequirements imr; vkGetImageMemoryRequirements(d, img, &imr);
    VkMemoryAllocateInfo ima = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = imr.size, .memoryTypeIndex = mem_type(&mp, imr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    VkDeviceMemory im; CK(vkAllocateMemory(d, &ima, NULL, &im)); CK(vkBindImageMemory(d, img, im, 0));
    VkImageViewUsageCreateInfo vu = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_USAGE_CREATE_INFO, .usage = VK_IMAGE_USAGE_STORAGE_BIT};
    VkImageViewCreateInfo vc = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .pNext = &vu, .image = img, .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = VK_FORMAT_R32_UINT,
        .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    VkImageView iv; CK(vkCreateImageView(d, &vc, NULL, &iv));
    VkDescriptorSetLayoutBinding lb[2] = {{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}};
    VkDescriptorSetLayoutCreateInfo dlc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = lb}; VkDescriptorSetLayout dl; CK(vkCreateDescriptorSetLayout(d, &dlc, NULL, &dl));
    VkPipelineLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &dl}; VkPipelineLayout pl; CK(vkCreatePipelineLayout(d, &lc, NULL, &pl));
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = nb, .pCode = code}; VkShaderModule m; CK(vkCreateShaderModule(d, &mc, NULL, &m));
    VkComputePipelineCreateInfo cc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT,
                                      .module = m, .pName = "main"}, .layout = pl};
    VkPipeline pipe; CK(vkCreateComputePipelines(d, VK_NULL_HANDLE, 1, &cc, NULL, &pipe));
    VkDescriptorPoolSize ps[2] = {{VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1}, {VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1}};
    VkDescriptorPoolCreateInfo dpc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1, .poolSizeCount = 2, .pPoolSizes = ps}; VkDescriptorPool dp; CK(vkCreateDescriptorPool(d, &dpc, NULL, &dp));
    VkDescriptorSetAllocateInfo dai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = dp, .descriptorSetCount = 1, .pSetLayouts = &dl}; VkDescriptorSet ds; CK(vkAllocateDescriptorSets(d, &dai, &ds));
    VkDescriptorBufferInfo bi = {bufs[0], 0, sizeof in}; VkDescriptorImageInfo ii = {VK_NULL_HANDLE, iv, VK_IMAGE_LAYOUT_GENERAL};
    VkWriteDescriptorSet wr[2] = {{.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = ds, .dstBinding = 0, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi},
                                  {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = ds, .dstBinding = 1, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, .pImageInfo = &ii}};
    vkUpdateDescriptorSets(d, 2, wr, 0, NULL);
    VkCommandPoolCreateInfo cpc = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; VkCommandPool cp; CK(vkCreateCommandPool(d, &cpc, NULL, &cp));
    VkCommandBufferAllocateInfo ca = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = cp, .commandBufferCount = 1}; VkCommandBuffer c; CK(vkAllocateCommandBuffers(d, &ca, &c));
    VkCommandBufferBeginInfo cbi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; CK(vkBeginCommandBuffer(c, &cbi));
    VkImageMemoryBarrier b0 = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .dstAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_GENERAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = img, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 0, NULL, 0, NULL, 1, &b0);
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, pipe); vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 0, 1, &ds, 0, NULL); vkCmdDispatch(c, 1, 1, 1);
    VkImageMemoryBarrier b1 = b0; b1.srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT; b1.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT; b1.oldLayout = b1.newLayout = VK_IMAGE_LAYOUT_GENERAL;
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT, 0, 0, NULL, 0, NULL, 1, &b1);
    VkBufferImageCopy r = {0, 0, 0, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {0, 0, 0}, {16, 16, 1}};
    vkCmdCopyImageToBuffer(c, img, VK_IMAGE_LAYOUT_GENERAL, bufs[1], 1, &r);
    VkMemoryBarrier hb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &hb, 0, NULL, 0, NULL);
    CK(vkEndCommandBuffer(c));
    VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &c}; CK(vkQueueSubmit(q, 1, &si, VK_NULL_HANDLE)); CK(vkQueueWaitIdle(q));
    f = fopen(argv[3], "wb"); if (!f) return 2; fwrite(bp[1], 4, 256, f); fclose(f);
    const uint32_t *w = bp[1]; printf("words 0-3: %08x %08x %08x %08x\n", w[0], w[1], w[2], w[3]);
    return 0;
}
