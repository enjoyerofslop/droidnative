// t_warp_reduce <comp.spv>: whether a compute shader's whole-warp reductions, as the translator writes Maxwell's (SHFL.BFLY by 1, 2, 4, 8 and 16 lanes, clamp 31,
// then lane 0 of each warp adds its result into memory with an atomic), give the workgroup's sum, minimum, maximum and OR on this GPU. One workgroup of 64
// invocations; invocation i holds hash(i + 1) & 0xffff; the shader (dm/tools/tests/test_spv_narrow.py writes it, as translated and as spv_narrow.h rewrites it) adds,
// mins, maxes and ORs its warp's into a storage buffer of 4 words. Exit 0 when all four are right.
// test_spv_narrow.py builds and runs it on a device with DM_TEST_SERIAL=<adb serial>
#include <stdio.h>
#include <stdlib.h>
#include <vulkan/vulkan.h>
#define CK(x) do { VkResult r_ = (x); if (r_) { printf("%s = %d\n", #x, r_); return 1; } } while (0)
static uint32_t hash(uint32_t x) { uint32_t h = x * 2654435761u; h ^= h >> 15; h *= 739982445u; h ^= h >> 12; return h; }   // test_spv_narrow.py's, in the shader
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    FILE *f = fopen(argv[1], "rb"); if (!f) return 2;
    static uint32_t code[1 << 16]; size_t nb = fread(code, 1, sizeof code, f); fclose(f);
    VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
    VkInstance in; CK(vkCreateInstance(&ic, NULL, &in));
    uint32_t n = 1; VkPhysicalDevice pd; vkEnumeratePhysicalDevices(in, &n, &pd);
    VkPhysicalDeviceSubgroupProperties sg = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SUBGROUP_PROPERTIES};
    VkPhysicalDeviceProperties2 p2 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &sg}; vkGetPhysicalDeviceProperties2(pd, &p2);
    printf("%s, subgroup size %u, stages %#x\n", p2.properties.deviceName, sg.subgroupSize, sg.supportedStages);
    float pri = 1; VkDeviceQueueCreateInfo qc = {.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO, .queueFamilyIndex = 0, .queueCount = 1, .pQueuePriorities = &pri};
    VkDeviceCreateInfo dc = {.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO, .queueCreateInfoCount = 1, .pQueueCreateInfos = &qc};
    VkDevice d; CK(vkCreateDevice(pd, &dc, NULL, &d)); VkQueue q; vkGetDeviceQueue(d, 0, 0, &q);
    VkPhysicalDeviceMemoryProperties mp; vkGetPhysicalDeviceMemoryProperties(pd, &mp);
    VkBufferCreateInfo bc = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = 16, .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT}; VkBuffer buf; CK(vkCreateBuffer(d, &bc, NULL, &buf));
    VkMemoryRequirements mr; vkGetBufferMemoryRequirements(d, buf, &mr);
    uint32_t ti = 0; while (!(mr.memoryTypeBits & (1u << ti)) || (mp.memoryTypes[ti].propertyFlags & (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) !=
                                                                      (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) ti++;
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = ti}; VkDeviceMemory bm; CK(vkAllocateMemory(d, &ma, NULL, &bm));
    CK(vkBindBufferMemory(d, buf, bm, 0));
    uint32_t *p; CK(vkMapMemory(d, bm, 0, 16, 0, (void **)&p)); p[0] = 0; p[1] = 0xffffffffu; p[2] = 0; p[3] = 0;   // sum, min, max, OR
    VkDescriptorSetLayoutBinding lb = {0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL};
    VkDescriptorSetLayoutCreateInfo dlc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 1, .pBindings = &lb}; VkDescriptorSetLayout dl; CK(vkCreateDescriptorSetLayout(d, &dlc, NULL, &dl));
    VkPipelineLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &dl}; VkPipelineLayout pl; CK(vkCreatePipelineLayout(d, &lc, NULL, &pl));
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = nb, .pCode = code}; VkShaderModule m; CK(vkCreateShaderModule(d, &mc, NULL, &m));
    VkComputePipelineCreateInfo cc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT,
                                      .module = m, .pName = "main"}, .layout = pl};
    VkPipeline pipe; CK(vkCreateComputePipelines(d, VK_NULL_HANDLE, 1, &cc, NULL, &pipe));
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1};
    VkDescriptorPoolCreateInfo dpc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &ps}; VkDescriptorPool dp; CK(vkCreateDescriptorPool(d, &dpc, NULL, &dp));
    VkDescriptorSetAllocateInfo dai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorPool = dp, .descriptorSetCount = 1, .pSetLayouts = &dl}; VkDescriptorSet ds; CK(vkAllocateDescriptorSets(d, &dai, &ds));
    VkDescriptorBufferInfo bi = {buf, 0, 16};
    VkWriteDescriptorSet wr = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = ds, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi};
    vkUpdateDescriptorSets(d, 1, &wr, 0, NULL);
    VkCommandPoolCreateInfo cpc = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO}; VkCommandPool cp; CK(vkCreateCommandPool(d, &cpc, NULL, &cp));
    VkCommandBufferAllocateInfo ca = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .commandPool = cp, .commandBufferCount = 1}; VkCommandBuffer c; CK(vkAllocateCommandBuffers(d, &ca, &c));
    VkCommandBufferBeginInfo cbi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO}; CK(vkBeginCommandBuffer(c, &cbi));
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, pipe); vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 0, 1, &ds, 0, NULL); vkCmdDispatch(c, 1, 1, 1);
    VkMemoryBarrier hb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &hb, 0, NULL, 0, NULL);
    CK(vkEndCommandBuffer(c));
    VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &c}; CK(vkQueueSubmit(q, 1, &si, VK_NULL_HANDLE)); CK(vkQueueWaitIdle(q));
    uint32_t want[4] = {0, 0xffffffffu, 0, 0};
    for (uint32_t i = 0; i < 64; i++) { uint32_t v = hash(i + 1) & 0xffff; want[0] += v; if (v < want[1]) want[1] = v; if (v > want[2]) want[2] = v; want[3] |= v; }
    static const char *name[4] = {"sum", "min", "max", "or"}; int bad = 0;
    for (int k = 0; k < 4; k++) { printf("%s %#x, want %#x%s\n", name[k], p[k], want[k], p[k] == want[k] ? "" : "  WRONG"); bad += p[k] != want[k]; }
    return bad != 0;
}
