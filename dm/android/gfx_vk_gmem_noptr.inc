// ---------------- Raw global memory without physical pointers made from integers (included at the end of gfx_vk_gmem.inc) ----------------
// Drivers that reject OpConvertUToPtr reach the placed pieces through a table of pointers, or a descriptor array, instead (spv_noptr.h). The Ayn Odin 2's Adreno 740 driver
// (V@0676.32) logs "Instruction OpConvertUToPtr not supported" and fails the pipeline of every raw-memory shader with VK_ERROR_UNKNOWN (77 in a Kokiri Forest load: Ocarina
// of Time's characters dark); the Razr's 730 (V@0615) does the same to Frostpunk's buildings. Both take a pointer loaded from memory, and loads, stores and atomics through it.
// Either way each table entry's delta is (slot << 32) - start, so the translator's helper computes the slot and the offset where it computed the device address, and a slot is
// its piece's for as long as the piece is placed; pieces are given back only with the GPU idle (gm_unplace, gm_lz_merge).
// - The table of pointers (SPV_NOPTR_TABLE, the first choice): one host-visible storage buffer of DMSH_GMEM_MAP_ENTRIES device addresses, the piece's written at its slot as it is
//   placed, the sink's (slot 0) when it is given back. The shaders keep their physical addressing and load the slot's pointer. Nothing beyond bufferDeviceAddress is needed.
// - The descriptor array (SPV_NOPTR_ARRAY, where the driver refuses loaded pointers too): each placed piece's buffer is a slot of one storage-buffer array in a set of its own.
//   A new piece's slot is written into the set as it is placed: the set is update-after-bind and its slots partially bound and updated unused while pending, so the write
//   never waits for the draws already recorded. Slots are handed out round the array, so a freed one is the last to come back. Pieces are capped at maxStorageBufferRange
//   (128 MiB on the 740), each one descriptor. An atomic on an element of such an array does not link on the 740's or the 730's driver.
// - The set: SPV_NOPTR_SET (5), past the stages' sets (0-3) and the texture pool's (4), where the GPU binds 6 sets at once; SPV_NOPTR_SET_LOW (3) on a GPU that binds only
//   4 or 5, where a pipeline with a stage of set 3 that reads raw memory is refused (gm_np_layout). The array is as long as the table (8,192 slots) or as the GPU's
//   update-after-bind storage buffers a stage allow.
// - Chosen when the device is made: a probe pipeline (shaders/gmem_probe.comp, a pointer made by OpConvertUToPtr as the translator makes it) the driver refuses; then one
//   whose pointer is loaded from a buffer (shaders/gmem_probe_ldptr.comp) decides between the table and the array, on a device that has what the array needs (runtime
//   descriptor arrays, non-uniform storage-buffer indexing, update-after-bind storage buffers, partially bound slots).
//   DM_VK_RAW_GMEM_NOPTR=2 (env.txt): the table without the probes; =1: the array without the probes; =0: never, raw-memory shaders then fail on such a driver as before;
//   =auto (a profile's android_defaults.txt): the probes on a device with GM_NP_AUTO_GIB of RAM or more, never on a smaller one
static int g_gm_np_ok, g_np_can_arr;   // the device was made with what the table or the array needs (gm_np_take); the array's features are on
static int g_np_form = -1;   // SPV_NOPTR_TABLE or SPV_NOPTR_ARRAY once chosen (gm_np_made)
static VkDescriptorSetLayout g_np_dsl; static VkDescriptorPool g_np_dp; static VkDescriptorSet g_np_ds;
static stg_t g_np_tab;   // the table of pointers: g_np_n device addresses (SPV_NOPTR_TABLE)
static uint8_t *g_np_used; static uint32_t g_np_n, g_np_next = 1;   // slots in use; the array's or the table's length; where the next search starts (slot 0 is the sink's, DM_VK_RAW_GMEM_SINK)
static uint32_t g_np_set = SPV_NOPTR_SET;   // the array's set in every pipeline layout that has it
static uint64_t g_np_writes, g_np_full, g_np_binds;
static _Atomic uint64_t g_np_mods, g_np_left;   // modules rewritten by spv_noptr; modules with physical pointers it left (lm_code)
static const uint32_t k_gm_probe_cs[] =
#include "shaders/gmem_probe.comp.inc"
;
static const uint32_t k_gm_probe_ld_cs[] =   // a pointer loaded from a buffer, then a load through it
#include "shaders/gmem_probe_ldptr.comp.inc"
;
// DM_VK_RAW_GMEM_NOPTR_NU=0 (env.txt, a diagnostic): the accesses without NonUniform decorations, for telling what a driver's non-uniform indexing costs; wrong where the
// lanes of one draw reach different pieces. DM_VK_RAW_GMEM_NOPTR_SLOTS=<n> (a diagnostic): an array of at most n slots, for telling what its length costs.
// DM_VK_RAW_GMEM_NOPTR_SET=3 (a diagnostic): the array at SPV_NOPTR_SET_LOW on a GPU that binds 6 sets, to try what a GPU that binds 4 gets
static int gm_np_nu(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_RAW_GMEM_NOPTR_NU"); v = !(e && *e == '0'); if (!v) LOG("[vk] DM_VK_RAW_GMEM_NOPTR_NU=0: the pools' array is indexed without NonUniform decorations"); } return v; }
// DM_VK_RAW_GMEM_NOPTR: 2 the table without the probes, 1 the array, 0 neither, unset the probes; auto: the probes on a device with at least GM_NP_AUTO_GIB of RAM, neither on a
// smaller one. The raw-memory pipelines the table or the array bring back cost the driver's memory (8 MiB each where the shader needs private memory, gfx_vk_pevict.inc), and
// Ocarina of Time's 98 were what ended it on a 12 GB Ayn Odin 2 at the Kokiri Forest load (2026-11-12), while on a 16 GB phone they fit
#define GM_NP_AUTO_GIB 14
static uint64_t gm_np_memtotal_mib(void) {
    FILE *f = fopen("/proc/meminfo", "r"); if (!f) return 0;
    char line[128]; uint64_t kb = 0;
    while (fgets(line, sizeof line, f)) if (!strncmp(line, "MemTotal:", 9)) { kb = strtoull(line + 9, NULL, 10); break; }
    fclose(f); return kb >> 10;
}
static int gm_np_env(void) {
    static int v = -2;
    if (v == -2) { const char *e = getenv("DM_VK_RAW_GMEM_NOPTR"); v = e && *e == '2' ? 2 : e && *e == '1' ? 1 : e && *e == '0' ? 0 : -1;
        if (e && !strcmp(e, "auto")) { uint64_t mib = gm_np_memtotal_mib(); v = mib >= (uint64_t)GM_NP_AUTO_GIB * 1024 - 512 ? -1 : 0;
            if (!v) LOG("[vk] raw global memory: DM_VK_RAW_GMEM_NOPTR=auto and the device has %llu MiB of RAM, under %d GiB: on a driver that refuses the shaders' pointers they stay refused (the pipelines "
                        "they bring back do not fit; =2 in env.txt tries the table of pointers)", (unsigned long long)mib, GM_NP_AUTO_GIB); } }
    return v;
}
// After the device's features are read (vk_try): the table needs nothing more; whether the device has what the array needs (d: the descriptor indexing features, NULL where the
// driver has none), and VK_EXT_descriptor_indexing to enable when the driver lists it (core from Vulkan 1.2)
static int gm_np_take(const VkPhysicalDeviceDescriptorIndexingFeaturesEXT *d, int listed, const char **dext, uint32_t *nde) {
    if (gm_np_env() == 0) return 0;
    g_gm_np_ok = 1;
    if (!d || !d->runtimeDescriptorArray || !d->shaderStorageBufferArrayNonUniformIndexing || !d->descriptorBindingStorageBufferUpdateAfterBind || !d->descriptorBindingPartiallyBound ||
        !d->descriptorBindingUpdateUnusedWhilePending) {
        if (d) LOG("[vk] raw global memory: no descriptor array for the pools (runtime arrays %u, non-uniform storage-buffer indexing %u, update after bind %u, partially bound %u, unused while pending %u): "
                   "physical pointers, or the table of pointers", d->runtimeDescriptorArray, d->shaderStorageBufferArrayNonUniformIndexing, d->descriptorBindingStorageBufferUpdateAfterBind,
                   d->descriptorBindingPartiallyBound, d->descriptorBindingUpdateUnusedWhilePending);
        return 1; }
    int have = 0; for (uint32_t i = 0; i < *nde; i++) have |= !strcmp(dext[i], "VK_EXT_descriptor_indexing");
    if (listed && !have) dext[(*nde)++] = "VK_EXT_descriptor_indexing";
    return g_np_can_arr = 1;
}
static int gm_np_enable(VkPhysicalDeviceDescriptorIndexingFeaturesEXT *d) {   // into vkCreateDevice's chain; 0: nothing to enable
    if (!g_gm_np_ok || !g_np_can_arr) return 0;
    d->runtimeDescriptorArray = d->shaderStorageBufferArrayNonUniformIndexing = d->descriptorBindingStorageBufferUpdateAfterBind = VK_TRUE;
    d->descriptorBindingPartiallyBound = d->descriptorBindingUpdateUnusedWhilePending = VK_TRUE;
    return 1;
}
// A probe: VK_SUCCESS when the driver builds a pipeline whose shader makes a physical pointer with OpConvertUToPtr (k_gm_probe_cs), or loads one from a buffer (k_gm_probe_ld_cs,
// two bindings). Its own objects, no pipeline cache (a cache never holds a refusal)
static VkResult gm_np_probe(const uint32_t *code, size_t bytes, uint32_t nb) {
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = bytes, .pCode = code};
    VkDescriptorSetLayoutBinding lb[2] = {{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}};
    VkDescriptorSetLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = nb, .pBindings = lb};
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
static void gm_np_write(uint32_t slot, VkBuffer b, VkDeviceSize n) {   // the buffer at a slot (g_gm_mu held, or before any draw): its address in the table, or its descriptor in the array
    if (g_np_form == SPV_NOPTR_TABLE) { VkBufferDeviceAddressInfoKHR ai = {.sType = VK_STRUCTURE_TYPE_BUFFER_DEVICE_ADDRESS_INFO_KHR, .buffer = b}; ((uint64_t *)g_np_tab.p)[slot] = g_gm_bda(g_vk.dev, &ai); g_np_writes++; return; }
    VkDescriptorBufferInfo bi = {b, 0, n};
    VkWriteDescriptorSet wr = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = g_np_ds, .dstBinding = SPV_NOPTR_BINDING, .dstArrayElement = slot, .descriptorCount = 1,
                               .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi};
    vkUpdateDescriptorSets(g_vk.dev, 1, &wr, 0, NULL); g_np_writes++;
}
// gm_device_made, before any pool is placed: the probes, then the table or the array's set, and the pieces' cap
static void gm_np_made(void) {
    if (!g_gm_np_ok) return;
    int env = gm_np_env(); VkResult pr = VK_SUCCESS, pl = VK_SUCCESS;
    if (env == -1 && (pr = gm_np_probe(k_gm_probe_cs, sizeof k_gm_probe_cs, 1)) == VK_SUCCESS) { LOG("[vk] raw global memory: the driver builds physical pointers made by OpConvertUToPtr (the probe pipeline): pointers, as translated"); return; }
    int form = env == 2 ? SPV_NOPTR_TABLE : env == 1 ? SPV_NOPTR_ARRAY : (pl = gm_np_probe(k_gm_probe_ld_cs, sizeof k_gm_probe_ld_cs, 2)) == VK_SUCCESS ? SPV_NOPTR_TABLE : SPV_NOPTR_ARRAY;
    char probe[160];
    if (env > 0) snprintf(probe, sizeof probe, "DM_VK_RAW_GMEM_NOPTR=%d", env);
    else snprintf(probe, sizeof probe, "the driver refuses the probe's OpConvertUToPtr (VkResult %d) and %s a pointer loaded from a buffer%s", (int)pr, pl == VK_SUCCESS ? "builds" : "refuses",
                  pl == VK_SUCCESS ? "" : " too");
    if (form == SPV_NOPTR_ARRAY && !g_np_can_arr) { LOG("[RED] [vk] raw global memory: %s, and the device lacks what the pools' descriptor array needs: raw-memory shaders fail to build on this driver%s",
                                                       probe, pl == VK_SUCCESS ? " (DM_VK_RAW_GMEM_NOPTR=2 tries the table of pointers)" : ""); return; }
    const uint32_t sets = g_vk.props.limits.maxBoundDescriptorSets; uint32_t n = DMSH_GMEM_MAP_ENTRIES;
    g_np_set = sets > SPV_NOPTR_SET ? SPV_NOPTR_SET : SPV_NOPTR_SET_LOW;
    { const char *e = getenv("DM_VK_RAW_GMEM_NOPTR_SET"); if (e && atoi(e) == SPV_NOPTR_SET_LOW && g_np_set != SPV_NOPTR_SET_LOW) { g_np_set = SPV_NOPTR_SET_LOW; LOG("[vk] DM_VK_RAW_GMEM_NOPTR_SET=%d: the pools' table or array is at that set", SPV_NOPTR_SET_LOW); } }
    const char *why = sets <= SPV_NOPTR_SET_LOW ? "fewer than 4 descriptor sets bound at once" : NULL;
    if (form == SPV_NOPTR_TABLE) {
        LOG("[vk] raw global memory: %s; %u descriptor sets bound at once", probe, sets);
        VkDescriptorSetLayoutBinding b = {SPV_NOPTR_BINDING, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_ALL, NULL};
        VkDescriptorSetLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 1, .pBindings = &b};
        VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1};
        VkDescriptorPoolCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &ps};
        VkDescriptorSetAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorSetCount = 1, .pSetLayouts = &g_np_dsl};
        if (!why && (!stg_new(&g_np_tab, (VkDeviceSize)n * 8) || vkCreateDescriptorSetLayout(g_vk.dev, &lc, NULL, &g_np_dsl) != VK_SUCCESS || vkCreateDescriptorPool(g_vk.dev, &pc, NULL, &g_np_dp) != VK_SUCCESS ||
                     (ai.descriptorPool = g_np_dp, vkAllocateDescriptorSets(g_vk.dev, &ai, &g_np_ds)) != VK_SUCCESS)) why = "its table or descriptor set could not be made";
        if (why || !(g_np_used = calloc(n, 1))) { LOG("[RED] [vk] raw global memory: the table of pointers is not on (%s): raw-memory shaders fail to build on this driver", why ? why : "memory"); return; }
        memset(g_np_tab.p, 0, (size_t)n * 8);
        VkDescriptorBufferInfo bi = {g_np_tab.b, 0, (VkDeviceSize)n * 8};
        VkWriteDescriptorSet wr = {.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = g_np_ds, .dstBinding = SPV_NOPTR_BINDING, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi};
        vkUpdateDescriptorSets(g_vk.dev, 1, &wr, 0, NULL);
        g_np_n = n; g_np_form = SPV_NOPTR_TABLE; g_gm_np = 1;
        LOG("[vk] raw global memory through a table of pointers: placed pieces' addresses are at their slots in one storage buffer (set %u, %u slots), the shaders load the slot's pointer, "
            "and spv_noptr rewrites how their pointers are made (DM_VK_RAW_GMEM_NOPTR=0: off)", g_np_set, n);
        return;
    }
    VkPhysicalDeviceDescriptorIndexingPropertiesEXT dp = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DESCRIPTOR_INDEXING_PROPERTIES_EXT};
    VkPhysicalDeviceProperties2 p2 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_PROPERTIES_2, .pNext = &dp}; vkGetPhysicalDeviceProperties2(g_vk.pd, &p2);
    // a slot for each table entry where the GPU has room, beside a stage's own storage buffers (four stages' in a set's count) and resources
    const uint32_t own = 64;
    uint32_t lim = dp.maxPerStageDescriptorUpdateAfterBindStorageBuffers; if (dp.maxDescriptorSetUpdateAfterBindStorageBuffers / 4 < lim) lim = dp.maxDescriptorSetUpdateAfterBindStorageBuffers / 4;
    if (dp.maxPerStageUpdateAfterBindResources < lim) lim = dp.maxPerStageUpdateAfterBindResources;
    if (dp.maxUpdateAfterBindDescriptorsInAllPools < lim) lim = dp.maxUpdateAfterBindDescriptorsInAllPools;
    lim = lim > 4 * own ? lim - 4 * own : 0; if (n > lim) n = lim;
    { const char *e = getenv("DM_VK_RAW_GMEM_NOPTR_SLOTS"); uint32_t v = e ? (uint32_t)strtoul(e, NULL, 0) : 0; if (v >= 2 && v < n) { n = v; LOG("[vk] DM_VK_RAW_GMEM_NOPTR_SLOTS=%u: the pools' array is that long", n); } }
    LOG("[vk] raw global memory: %s; %u descriptor sets bound at once, update-after-bind storage buffers %u a stage and %u a set, resources %u a stage, descriptors %u in all pools, "
        "maxStorageBufferRange %u MiB", probe, sets, dp.maxPerStageDescriptorUpdateAfterBindStorageBuffers, dp.maxDescriptorSetUpdateAfterBindStorageBuffers, dp.maxPerStageUpdateAfterBindResources,
        dp.maxUpdateAfterBindDescriptorsInAllPools, g_vk.props.limits.maxStorageBufferRange >> 20);
    if (!why && n < 256 && !getenv("DM_VK_RAW_GMEM_NOPTR_SLOTS")) why = "too few update-after-bind storage buffers";
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
    if (why || !(g_np_used = calloc(n, 1))) { LOG("[RED] [vk] raw global memory: the pools' descriptor array is not on (%s): raw-memory shaders fail to build on this driver", why ? why : "memory"); return; }
    g_np_n = n; g_np_form = SPV_NOPTR_ARRAY;
    VkDeviceSize r = g_vk.props.limits.maxStorageBufferRange & ~(VkDeviceSize)(GM_CHUNK - 1); if (r && g_gm_piece > r) g_gm_piece = r;
    g_gm_np = 1;
    LOG("[vk] raw global memory without physical pointers: placed pieces are slots of a storage-buffer array (set %u, %u slots), pieces of up to %llu MiB, and spv_noptr rewrites the "
        "shaders' pointers (DM_VK_RAW_GMEM_NOPTR=0: off)", g_np_set, n, (unsigned long long)(g_gm_piece >> 20));
}
// A piece being listed (gm_seg_insert, g_gm_mu held, under g_gm_pl): its slot, its buffer written there. 0: every slot taken (the piece stays out of the table, raw accesses read 0)
static uint32_t gm_np_slot(VkBuffer b, VkDeviceSize n) {
    for (uint32_t q = 1; q < g_np_n; q++) {
        uint32_t s = g_np_next; g_np_next = s + 1 < g_np_n ? s + 1 : 1;
        if (!g_np_used[s]) { g_np_used[s] = 1; gm_np_write(s, b, n); return s; } }
    if (!g_np_full++) LOG("[RED] [vk] raw global memory: all %u slots of the pools' descriptor array are taken: pieces placed from here on are not reached", g_np_n - 1);
    return 0;
}
static void gm_np_free(uint32_t s) {   // a piece given back (the GPU idle; g_gm_pl held): its slot free, the table's pointer the sink's
    if (!g_gm_np || !s || s >= g_np_n) return;
    g_np_used[s] = 0; if (g_np_form == SPV_NOPTR_TABLE) ((uint64_t *)g_np_tab.p)[s] = ((const uint64_t *)g_np_tab.p)[0];
}
// The array's set into the sets of a pipeline layout whose shaders read raw memory (pipe_make, cpipe_make; the sets no stage has are g_empty_dsl). 0: a stage has that
// set itself (only where the array is at SPV_NOPTR_SET_LOW): no layout, so no pipeline
static int gm_np_layout(VkDescriptorSetLayout *sets, uint32_t *nset, VkDescriptorSetLayout empty) {
    if (sets[g_np_set] != empty) { RED_ONCE(180, "raw global memory: a shader that reads it has descriptor set %u itself, where this GPU's pools' array is (it binds %u sets at once): its pipelines are not made",
                                            g_np_set, g_vk.props.limits.maxBoundDescriptorSets); return 0; }
    sets[g_np_set] = g_np_dsl; if (*nset < g_np_set + 1) *nset = g_np_set + 1;
    return 1;
}
// A draw or dispatch whose shaders read raw memory, after its own sets: the array at its set
static void gm_np_bind(VkCommandBuffer c, VkPipelineBindPoint bp, VkPipelineLayout pl) {
    vkCmdBindDescriptorSets(c, bp, pl, g_np_set, 1, &g_np_ds, 0, NULL); g_np_binds++;
}
// lm_code: a module with physical pointers, rewritten (spv_noptr.h) into *out (to free). 0: nothing to rewrite, or left as it is (a red line, once a reason)
static size_t gm_np_code(const uint32_t *code, size_t nw, const char *what, int first, uint32_t **out) {
    *out = NULL;
    if (!g_gm_np || !spv_noptr_wanted(code, nw)) return 0;
    uint32_t *sc = malloc(3 * (size_t)code[3] * 4); size_t k = 0; int why = 0;
    for (size_t cap = 2 * nw + 4096; sc && !k && cap <= 16 * nw + 4096; cap *= 4) {   // a vector access becomes several: rarely past twice the words
        free(*out); *out = malloc(cap * 4); if (!*out) break;
        k = spv_noptr(code, nw, g_np_set, gm_np_nu(), g_np_form, sc, *out, cap, &why); if (why != SPV_NOPTR_ROOM) break; }
    free(sc);
    if (!k) { free(*out); *out = NULL; }
    if (!first) return k;
    if (k) atomic_fetch_add(&g_np_mods, 1);
    else if (why) { atomic_fetch_add(&g_np_left, 1); static _Atomic int said[5]; if (why > 0 && why < 5 && !atomic_exchange(&said[why], 1))
        LOG("[RED] [vk] %s: spv_noptr leaves its physical pointers as made (%s): the driver refuses it", what, why == SPV_NOPTR_FORM ? "a pointer not made from a bitcast v2uint" : why == SPV_NOPTR_USE ? "a pointer used another way"
            : why == SPV_NOPTR_TYPE ? "a pointee that is not 32-bit words" : "too large"); }
    return k;
}
static void gm_np_stat(void) {
    if (!g_gm_np) return;
    uint32_t used = 0; for (uint32_t i = 1; i < g_np_n; i++) used += g_np_used[i];
    LOG("[vk] raw global memory through %s: %u of %u slots in use, %llu written, %llu pieces without a slot; %llu modules rewritten by spv_noptr, %llu left; %llu bindings of its set (cumulative)",
        g_np_form == SPV_NOPTR_TABLE ? "the table of pointers" : "the pools' descriptor array", used, g_np_n - 1, (unsigned long long)g_np_writes, (unsigned long long)g_np_full, (unsigned long long)atomic_load(&g_np_mods), (unsigned long long)atomic_load(&g_np_left), (unsigned long long)g_np_binds);
}
