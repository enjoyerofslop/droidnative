// ---------------- Raw global memory without physical pointers (included at the end of gfx_vk_gmem.inc) ----------------
// Drivers that reject OpConvertUToPtr reach the placed pieces through a descriptor array instead (spv_noptr.h). The Ayn Odin 2's Adreno 740 driver (V@0676.32) logs
// "Instruction OpConvertUToPtr not supported" and fails the pipeline of every raw-memory shader with VK_ERROR_UNKNOWN (77 in a Kokiri Forest load: Ocarina of Time's characters
// dark); the Razr's 730 (V@0615) does the same to Frostpunk's buildings. Here each placed piece's buffer is a slot of one storage-buffer array, set SPV_NOPTR_SET, and each
// table entry's delta is (slot << 32) - start, so the translator's helper computes the slot and the offset where it computed the device address.
// - One set serves every table: a slot is its piece's for as long as the piece is placed, and pieces are given back only with the GPU idle (gm_unplace, gm_lz_merge). A new
//   piece's slot is written into the set as it is placed: the set is update-after-bind and its slots partially bound and updated unused while pending, so the write
//   never waits for the draws already recorded. Slots are handed out round the array, so a freed one is the last to come back.
// - Pieces are capped at maxStorageBufferRange (128 MiB on the 740), each one descriptor; an offset into one fits the low word.
// - Chosen when the device is made: a probe pipeline (shaders/gmem_probe.comp, a pointer made by OpConvertUToPtr as the translator makes it) the driver refuses, on a device
//   that has what the array needs (runtime descriptor arrays, non-uniform storage-buffer indexing, update-after-bind storage buffers, partially bound slots).
//   DM_VK_RAW_GMEM_NOPTR=1 (env.txt): on without the probe; =0: never, raw-memory shaders then fail on such a driver as before
static int g_gm_np_ok;   // the device was made with what the array needs (gm_np_take)
static VkDescriptorSetLayout g_np_dsl; static VkDescriptorPool g_np_dp; static VkDescriptorSet g_np_ds;
static uint8_t *g_np_used; static uint32_t g_np_n, g_np_next = 1;   // slots in use; the array's length; where the next search starts (slot 0 is the sink's, DM_VK_RAW_GMEM_SINK)
static uint64_t g_np_writes, g_np_full, g_np_binds;
static _Atomic uint64_t g_np_mods, g_np_left;   // modules rewritten by spv_noptr; modules with physical pointers it left (lm_code)
static const uint32_t k_gm_probe_cs[] =
#include "shaders/gmem_probe.comp.inc"
;
static int gm_np_env(void) { static int v = -2; if (v == -2) { const char *e = getenv("DM_VK_RAW_GMEM_NOPTR"); v = e && *e == '1' ? 1 : e && *e == '0' ? 0 : -1; } return v; }
// After the device's features are read (vk_try): whether it has what the array needs, and VK_EXT_descriptor_indexing to enable when the driver lists it (core from Vulkan 1.2)
static int gm_np_take(const VkPhysicalDeviceDescriptorIndexingFeaturesEXT *d, int listed, const char **dext, uint32_t *nde) {
    if (gm_np_env() == 0) return 0;
    if (!d->runtimeDescriptorArray || !d->shaderStorageBufferArrayNonUniformIndexing || !d->descriptorBindingStorageBufferUpdateAfterBind || !d->descriptorBindingPartiallyBound ||
        !d->descriptorBindingUpdateUnusedWhilePending) {
        LOG("[vk] raw global memory: no descriptor array for the pools (runtime arrays %u, non-uniform storage-buffer indexing %u, update after bind %u, partially bound %u, unused while pending %u): "
            "physical pointers only", d->runtimeDescriptorArray, d->shaderStorageBufferArrayNonUniformIndexing, d->descriptorBindingStorageBufferUpdateAfterBind, d->descriptorBindingPartiallyBound,
            d->descriptorBindingUpdateUnusedWhilePending);
        return 0; }
    int have = 0; for (uint32_t i = 0; i < *nde; i++) have |= !strcmp(dext[i], "VK_EXT_descriptor_indexing");
    if (listed && !have) dext[(*nde)++] = "VK_EXT_descriptor_indexing";
    return g_gm_np_ok = 1;
}
static int gm_np_enable(VkPhysicalDeviceDescriptorIndexingFeaturesEXT *d) {   // into vkCreateDevice's chain; 0: nothing to enable
    if (!g_gm_np_ok) return 0;
    d->runtimeDescriptorArray = d->shaderStorageBufferArrayNonUniformIndexing = d->descriptorBindingStorageBufferUpdateAfterBind = VK_TRUE;
    d->descriptorBindingPartiallyBound = d->descriptorBindingUpdateUnusedWhilePending = VK_TRUE;
    return 1;
}
// The probe: VK_SUCCESS when the driver builds a pipeline whose shader makes a physical pointer with OpConvertUToPtr. Its own objects, no pipeline cache (a cache never holds a refusal)
static VkResult gm_np_probe(void) {
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof k_gm_probe_cs, .pCode = k_gm_probe_cs};
    VkDescriptorSetLayoutBinding lb = {0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL};
    VkDescriptorSetLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 1, .pBindings = &lb};
    VkShaderModule m = VK_NULL_HANDLE; VkDescriptorSetLayout dsl = VK_NULL_HANDLE; VkPipelineLayout pl = VK_NULL_HANDLE; VkPipeline p = VK_NULL_HANDLE;
    VkResult r = vkCreateShaderModule(g_vk.dev, &mc, NULL, &m);
    if (r == VK_SUCCESS) r = vkCreateDescriptorSetLayout(g_vk.dev, &lc, NULL, &dsl);
    VkPipelineLayoutCreateInfo plc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &dsl};
    if (r == VK_SUCCESS) r = vkCreatePipelineLayout(g_vk.dev, &plc, NULL, &pl);
    VkComputePipelineCreateInfo cc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = pl,
        .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main"}};
    if (r == VK_SUCCESS) r = vkCreateComputePipelines(g_vk.dev, VK_NULL_HANDLE, 1, &cc, NULL, &p);
    if (p) vkDestroyPipeline(g_vk.dev, p, NULL); if (pl) vkDestroyPipelineLayout(g_vk.dev, pl, NULL);
    if (dsl) vkDestroyDescriptorSetLayout(g_vk.dev, dsl, NULL); if (m) vkDestroyShaderModule(g_vk.dev, m, NULL);
    return r;
}
static void gm_np_write(uint32_t slot, VkBuffer b, VkDeviceSize n) {   // the buffer at a slot (g_gm_mu held, or before any draw)
    VkDescriptorBufferInfo bi = {b, 0, n};
    VkWriteDescriptorSet wr = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = g_np_ds, .dstBinding = SPV_NOPTR_BINDING, .dstArrayElement = slot, .descriptorCount = 1,
                               .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi};
    vkUpdateDescriptorSets(g_vk.dev, 1, &wr, 0, NULL); g_np_writes++;
}
// gm_device_made, before any pool is placed: the probe, then the array's set and the pieces' cap
static void gm_np_made(void) {
    if (!g_gm_np_ok) return;
    VkResult pr = VK_SUCCESS;
    if (gm_np_env() != 1 && (pr = gm_np_probe()) == VK_SUCCESS) { LOG("[vk] raw global memory: the driver builds physical pointers made by OpConvertUToPtr (the probe pipeline): pointers, as translated"); return; }
    VkPhysicalDeviceDescriptorIndexingPropertiesEXT dp = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_INDEXING_PROPERTIES_EXT};
    VkPhysicalDeviceProperties2 p2 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &dp}; vkGetPhysicalDeviceProperties2(g_vk.pd, &p2);
    const uint32_t n = DMSH_GMEM_MAP_ENTRIES, own = 64;   // a slot for each table entry; room for a stage's own storage buffers beside it, four stages' in a set's count
    const char *why = g_vk.props.limits.maxBoundDescriptorSets <= SPV_NOPTR_SET ? "fewer than 6 descriptor sets bound at once"
                    : dp.maxPerStageDescriptorUpdateAfterBindStorageBuffers < n + own || dp.maxDescriptorSetUpdateAfterBindStorageBuffers < n + 4 * own ? "too few update-after-bind storage buffers"
                    : dp.maxPerStageUpdateAfterBindResources < n + 256 ? "too few update-after-bind resources per stage" : NULL;
    VkDescriptorSetLayoutBinding b = {SPV_NOPTR_BINDING, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, n, VK_SHADER_STAGE_ALL, NULL};
    VkDescriptorBindingFlagsEXT bf = VK_DESCRIPTOR_BINDING_UPDATE_AFTER_BIND_BIT_EXT | VK_DESCRIPTOR_BINDING_PARTIALLY_BOUND_BIT_EXT | VK_DESCRIPTOR_BINDING_UPDATE_UNUSED_WHILE_PENDING_BIT_EXT;
    VkDescriptorSetLayoutBindingFlagsCreateInfoEXT fc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_BINDING_FLAGS_CREATE_INFO_EXT, .bindingCount = 1, .pBindingFlags = &bf};
    VkDescriptorSetLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .pNext = &fc, .flags = VK_DESCRIPTOR_SET_LAYOUT_CREATE_UPDATE_AFTER_BIND_POOL_BIT_EXT,
                                          .bindingCount = 1, .pBindings = &b};
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, n};
    VkDescriptorPoolCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .flags = VK_DESCRIPTOR_POOL_CREATE_UPDATE_AFTER_BIND_BIT_EXT, .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &ps};
    VkDescriptorSetAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorSetCount = 1, .pSetLayouts = &g_np_dsl};
    if (!why && (vkCreateDescriptorSetLayout(g_vk.dev, &lc, NULL, &g_np_dsl) != VK_SUCCESS || vkCreateDescriptorPool(g_vk.dev, &pc, NULL, &g_np_dp) != VK_SUCCESS ||
                 (ai.descriptorPool = g_np_dp, vkAllocateDescriptorSets(g_vk.dev, &ai, &g_np_ds)) != VK_SUCCESS)) why = "its descriptor set could not be made";
    if (why || !(g_np_used = calloc(n, 1))) {
        LOG("[RED] [vk] raw global memory: the driver refuses physical pointers made by OpConvertUToPtr (the probe: VkResult %d), and the pools' descriptor array is not on (%s): "
            "raw-memory shaders fail to build", (int)pr, why ? why : "memory");
        return; }
    g_np_n = n;
    VkDeviceSize r = g_vk.props.limits.maxStorageBufferRange & ~(VkDeviceSize)(GM_CHUNK - 1); if (r && g_gm_piece > r) g_gm_piece = r;
    g_gm_np = 1;
    if (gm_np_env() == 1) LOG("[vk] raw global memory without physical pointers (DM_VK_RAW_GMEM_NOPTR=1): placed pieces are slots of a storage-buffer array (set %d, %u slots), pieces of up to %llu MiB",
                              SPV_NOPTR_SET, n, (unsigned long long)(g_gm_piece >> 20));
    else LOG("[vk] raw global memory without physical pointers: the driver refuses OpConvertUToPtr (the probe pipeline: VkResult %d), so placed pieces are slots of a storage-buffer array "
             "(set %d, %u slots), pieces of up to %llu MiB (maxStorageBufferRange), and spv_noptr rewrites the shaders' pointers (DM_VK_RAW_GMEM_NOPTR=0: off)", (int)pr, SPV_NOPTR_SET, n,
             (unsigned long long)(g_gm_piece >> 20));
}
// A piece being listed (gm_seg_insert, g_gm_mu held, under g_gm_pl): its slot, its buffer written there. 0: every slot taken (the piece stays out of the table, raw accesses read 0)
static uint32_t gm_np_slot(VkBuffer b, VkDeviceSize n) {
    for (uint32_t q = 1; q < g_np_n; q++) {
        uint32_t s = g_np_next; g_np_next = s + 1 < g_np_n ? s + 1 : 1;
        if (!g_np_used[s]) { g_np_used[s] = 1; gm_np_write(s, b, n); return s; } }
    if (!g_np_full++) LOG("[RED] [vk] raw global memory: all %u slots of the pools' descriptor array are taken: pieces placed from here on are not reached", g_np_n - 1);
    return 0;
}
static void gm_np_free(uint32_t s) { if (g_gm_np && s && s < g_np_n) g_np_used[s] = 0; }   // a piece given back (the GPU idle; g_gm_pl held)
// A draw or dispatch whose shaders read raw memory (any[k]: a stage's gm), after its own sets: the array at SPV_NOPTR_SET, which its pipeline's layout has (pipe_make, cpipe_make)
static void gm_np_bind(VkCommandBuffer c, VkPipelineBindPoint bp, VkPipelineLayout pl) {
    vkCmdBindDescriptorSets(c, bp, pl, SPV_NOPTR_SET, 1, &g_np_ds, 0, NULL); g_np_binds++;
}
// lm_code: a module with physical pointers, rewritten (spv_noptr.h) into *out (to free). 0: nothing to rewrite, or left as it is (a red line, once a reason)
static size_t gm_np_code(const uint32_t *code, size_t nw, const char *what, int first, uint32_t **out) {
    *out = NULL;
    if (!g_gm_np || !spv_noptr_wanted(code, nw)) return 0;
    uint32_t *sc = malloc(3 * (size_t)code[3] * 4); size_t k = 0; int why = 0;
    for (size_t cap = 2 * nw + 4096; sc && !k && cap <= 16 * nw + 4096; cap *= 4) {   // a vector access becomes several: rarely past twice the words
        free(*out); *out = malloc(cap * 4); if (!*out) break;
        k = spv_noptr(code, nw, sc, *out, cap, &why); if (why != SPV_NOPTR_ROOM) break; }
    free(sc);
    if (!k) { free(*out); *out = NULL; }
    if (!first) return k;
    if (k) atomic_fetch_add(&g_np_mods, 1);
    else if (why) { atomic_fetch_add(&g_np_left, 1); static _Atomic int said[5]; if (why > 0 && why < 5 && !atomic_exchange(&said[why], 1))
        LOG("[RED] [vk] %s: spv_noptr leaves its physical pointers (%s): the driver refuses it", what, why == SPV_NOPTR_FORM ? "a pointer not made from a bitcast v2uint" : why == SPV_NOPTR_USE ? "a pointer used another way"
            : why == SPV_NOPTR_TYPE ? "a pointee that is not 32-bit words" : "too large"); }
    return k;
}
static void gm_np_stat(void) {
    if (!g_gm_np) return;
    uint32_t used = 0; for (uint32_t i = 1; i < g_np_n; i++) used += g_np_used[i];
    LOG("[vk] raw global memory without physical pointers: %u of %u slots in use, %llu written, %llu pieces without a slot; %llu modules rewritten by spv_noptr, %llu left; %llu bindings of the array (cumulative)",
        used, g_np_n - 1, (unsigned long long)g_np_writes, (unsigned long long)g_np_full, (unsigned long long)atomic_load(&g_np_mods), (unsigned long long)atomic_load(&g_np_left), (unsigned long long)g_np_binds);
}
