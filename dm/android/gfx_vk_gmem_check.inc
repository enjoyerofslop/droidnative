// ---------------- Raw global memory: its diagnostics (included at the end of gfx_vk_gmem.inc) ----------------
// DM_VK_RAW_GMEM_TEST=1 (a diagnostic): once the first table is built, a compute shader (shaders/gmem_test.comp) reads 16 bytes at 64 addresses in placed pieces through the table's
// deltas and physical pointers aligned as words, as the translator's raw vector loads do, and the CPU compares them with the same bytes: the placed map, the device addresses and
// the table's deltas checked on the GPU in one go. Run in a command buffer of its own and waited for. A byte the game rewrote between the two reads shows as a difference too
static const uint32_t k_gm_test_cs[] =
#include "shaders/gmem_test.comp.inc"
;
static const uint32_t k_gm_test_np_cs[] =   // without physical pointers: the pools' descriptor array at set 1 (gfx_vk_gmem_noptr.inc)
#include "shaders/gmem_test_noptr.comp.inc"
;
static const uint32_t k_gm_test_pt_cs[] =   // the table of pointers at set 1
#include "shaders/gmem_test_ptab.comp.inc"
;
static void gm_selftest(void) {
    const char *e = getenv("DM_VK_RAW_GMEM_TEST"); if (!e || *e != '1' || !g_ngm) return;
    uintptr_t addr[64]; uint32_t ent[64]; int n = 0;
    pthread_mutex_lock(&g_gm_mu);
    for (int k = 0; n < 64 && k < 64 * 4; k++) {   // spread over the pieces, the largest too: offsets aligned to 16 and, every other one, only to 4
        int i = (int)(((uint64_t)k * 2654435761u) % (uint64_t)g_ngm); if (i + 1 >= DMSH_GMEM_MAP_ENTRIES) continue;
        uint64_t len = g_gm[i].hi - g_gm[i].lo; if (len < 32) continue;
        uint64_t off = ((uint64_t)k * 0x9e3779b97f4a7c15ull >> 20) % (len - 16); off = n & 1 ? off & ~3ull : off & ~15ull;
        addr[n] = g_gm[i].lo + off; ent[n++] = (uint32_t)i + 1;
    }
    pthread_mutex_unlock(&g_gm_mu);
    int pt = g_gm_np && g_np_form == SPV_NOPTR_TABLE;
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = pt ? sizeof k_gm_test_pt_cs : g_gm_np ? sizeof k_gm_test_np_cs : sizeof k_gm_test_cs,
                                   .pCode = pt ? k_gm_test_pt_cs : g_gm_np ? k_gm_test_np_cs : k_gm_test_cs};
    VkDescriptorSetLayoutBinding lb[2] = {{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}};
    VkDescriptorSetLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = lb};
    VkDescriptorPoolSize ps = {VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 2}; VkDescriptorPoolCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_POOL_CREATE_INFO, .maxSets = 1, .poolSizeCount = 1, .pPoolSizes = &ps};
    VkShaderModule m = VK_NULL_HANDLE; VkDescriptorSetLayout dsl = VK_NULL_HANDLE; VkPipelineLayout pl = VK_NULL_HANDLE; VkPipeline pp = VK_NULL_HANDLE; VkDescriptorPool dp = VK_NULL_HANDLE;
    VkCommandPool cp = VK_NULL_HANDLE; VkFence f = VK_NULL_HANDLE; stg_t io = {0}; const char *why = NULL;
    if (vkCreateShaderModule(g_vk.dev, &mc, NULL, &m) || vkCreateDescriptorSetLayout(g_vk.dev, &lc, NULL, &dsl)) why = "module or set layout";
    VkDescriptorSetLayout pls[2] = {dsl, g_np_dsl};
    VkPipelineLayoutCreateInfo plc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = g_gm_np ? 2 : 1, .pSetLayouts = pls};
    if (!why && vkCreatePipelineLayout(g_vk.dev, &plc, NULL, &pl)) why = "pipeline layout";
    VkComputePipelineCreateInfo cc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = m, .pName = "main"}, .layout = pl};
    if (!why && vkCreateComputePipelines(g_vk.dev, VK_NULL_HANDLE, 1, &cc, NULL, &pp)) why = "pipeline";
    if (!why && !stg_new(&io, 64 * 32)) why = "buffer";
    VkDescriptorSet ds = VK_NULL_HANDLE; VkDescriptorSetAllocateInfo da = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_ALLOCATE_INFO, .descriptorSetCount = 1, .pSetLayouts = &dsl};
    if (!why && (vkCreateDescriptorPool(g_vk.dev, &pc, NULL, &dp) || (da.descriptorPool = dp, vkAllocateDescriptorSets(g_vk.dev, &da, &ds)))) why = "descriptor set";
    VkCommandPoolCreateInfo cpc = {.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO, .queueFamilyIndex = g_vk.qf}; VkCommandBuffer cb = VK_NULL_HANDLE;
    VkCommandBufferAllocateInfo ca = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO, .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY, .commandBufferCount = 1};
    VkFenceCreateInfo fc = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
    if (!why && (vkCreateCommandPool(g_vk.dev, &cpc, NULL, &cp) || (ca.commandPool = cp, vkAllocateCommandBuffers(g_vk.dev, &ca, &cb)) || vkCreateFence(g_vk.dev, &fc, NULL, &f))) why = "command buffer";
    if (!why) {
        uint32_t *req = (uint32_t *)io.p; memset(io.p, 0, 64 * 32);
        for (int i = 0; i < 64; i++) { int k = i < n ? i : 0; req[4 * i] = (uint32_t)addr[k]; req[4 * i + 1] = (uint32_t)((uint64_t)addr[k] >> 32); req[4 * i + 2] = ent[k]; }
        VkDescriptorBufferInfo bt = {g_gt.b, 0, GM_TAB_BYTES}, bio = {io.b, 0, 64 * 32};
        VkWriteDescriptorSet w[2] = {{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, ds, 0, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bt, NULL}, {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, ds, 1, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bio, NULL}};
        vkUpdateDescriptorSets(g_vk.dev, 2, w, 0, NULL);
        VkCommandBufferBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO, .flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT};
        vkBeginCommandBuffer(cb, &bi); vkCmdBindPipeline(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pp); vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 0, 1, &ds, 0, NULL);
        if (g_gm_np) vkCmdBindDescriptorSets(cb, VK_PIPELINE_BIND_POINT_COMPUTE, pl, 1, 1, &g_np_ds, 0, NULL);
        vkCmdDispatch(cb, 1, 1, 1);
        VkMemoryBarrier hb = {.sType = VK_STRUCTURE_TYPE_MEMORY_BARRIER, .srcAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .dstAccessMask = VK_ACCESS_HOST_READ_BIT};
        vkCmdPipelineBarrier(cb, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, VK_PIPELINE_STAGE_HOST_BIT, 0, 1, &hb, 0, NULL, 0, NULL);
        if (vkEndCommandBuffer(cb)) why = "recording";
        VkSubmitInfo si = {.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO, .commandBufferCount = 1, .pCommandBuffers = &cb};
        if (!why) { pthread_mutex_lock(&g_vk.qmu); VkResult r = vkQueueSubmit(g_vk.q, 1, &si, f); pthread_mutex_unlock(&g_vk.qmu); if (r || vkWaitForFences(g_vk.dev, 1, &f, VK_TRUE, 5000000000ull)) why = "submission"; }
    }
    if (!why) {
        const uint32_t *got = (const uint32_t *)io.p + 4 * 64; int bad = 0;
        for (int i = 0; i < n; i++) { uint32_t want[4]; memcpy(want, (const void *)addr[i], 16);
            if (memcmp(want, got + 4 * i, 16) && bad++ < 8) LOG("[RED] [vk] raw global memory self-test: %#lx (entry %u) read %08x %08x %08x %08x on the GPU, %08x %08x %08x %08x on the CPU", (unsigned long)addr[i], ent[i],
                got[4 * i], got[4 * i + 1], got[4 * i + 2], got[4 * i + 3], want[0], want[1], want[2], want[3]); }
        int nz = 0; for (int i = 0; i < n; i++) nz += (got[4 * i] | got[4 * i + 1] | got[4 * i + 2] | got[4 * i + 3]) != 0;
        LOG("%s[vk] raw global memory self-test (DM_VK_RAW_GMEM_TEST): %d of %d 16-byte reads through the pool table on the GPU match the CPU's bytes (%d of them not all zero)%s", bad ? "[RED] " : "", n - bad, n, nz,
            pt ? ", through the table of pointers" : g_gm_np ? ", through the pools' descriptor array" : "");
    } else LOG("[RED] [vk] raw global memory self-test (DM_VK_RAW_GMEM_TEST): not run, its %s failed", why);
    if (f) vkDestroyFence(g_vk.dev, f, NULL); if (cp) vkDestroyCommandPool(g_vk.dev, cp, NULL); if (dp) vkDestroyDescriptorPool(g_vk.dev, dp, NULL); stg_free(&io);
    if (pp) vkDestroyPipeline(g_vk.dev, pp, NULL); if (pl) vkDestroyPipelineLayout(g_vk.dev, pl, NULL); if (dsl) vkDestroyDescriptorSetLayout(g_vk.dev, dsl, NULL); if (m) vkDestroyShaderModule(g_vk.dev, m, NULL);
}
// DM_VK_RAW_GMEM_CHECK=1 (a diagnostic): the 64-bit words at the start of the storage buffers a shader that binds the table reads, which look like guest addresses (in a pool, or
// near one), each said once with where it lies: in a placed piece (raw loads reach it), in a pool not placed, or in none. The pointers the shader loads are usually there
static int gm_check_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_RAW_GMEM_CHECK"); v = e && *e == '1'; } return v; }
static void gm_check(const vshader *s, int slot, uint32_t off, uint64_t addr, size_t n) {
    static int nl; static uint64_t said[512]; static int nsaid;
    if (nl >= 200 || !addr) return;
    const uint64_t *w = (const uint64_t *)(uintptr_t)addr; size_t nw = (n < 512 ? n : 512) / 8;
    pthread_mutex_lock(&g_pool_mu); uintptr_t plo = g_npool ? (uintptr_t)g_pools[0].lo : 0, phi = 0; for (int i = 0; i < g_npool; i++) if ((uintptr_t)g_pools[i].hi > phi) phi = (uintptr_t)g_pools[i].hi; pthread_mutex_unlock(&g_pool_mu);
    for (size_t k = 0; k < nw && nl < 200; k++) {
        uint64_t v = w[k]; if (v < plo || v >= phi) continue;
        uint64_t tag = v ^ (uint64_t)(k << 1) ^ ((uint64_t)s->key[0] << 56); int dup = 0; for (int i = 0; i < nsaid && !dup; i++) dup = said[i] == tag; if (dup) continue; if (nsaid < 512) said[nsaid++] = tag;
        pthread_mutex_lock(&g_pool_mu); int pi = pool_find((const uint8_t *)(uintptr_t)v, 1); pool_rng pr = pi >= 0 ? g_pools[pi] : (pool_rng){0}; pthread_mutex_unlock(&g_pool_mu);
        pthread_mutex_lock(&g_gm_mu); int placed = 0; for (int i = 0; i < g_ngm && !placed; i++) placed = v >= g_gm[i].lo && v < g_gm[i].hi; pthread_mutex_unlock(&g_gm_mu);
        nl++;
        if (pi < 0) LOG("[vk] raw global memory check: shader %s, storage buffer c%d +%#x (%#llx), word %zu = %#llx: in no memory pool", s->key, slot, off, (unsigned long long)addr, k, (unsigned long long)v);
        else LOG("[vk] raw global memory check: shader %s, storage buffer c%d +%#x (%#llx), word %zu = %#llx: in pool %p+%#llx (%s), %s", s->key, slot, off, (unsigned long long)addr, k, (unsigned long long)v,
                 (const void *)pr.lo, (unsigned long long)(pr.hi - pr.lo), pr.how & 1 ? "a buffer's address taken" : pr.how & 2 ? "a texture's address taken" : "no address taken", placed ? "placed: raw loads reach it" : "NOT placed: raw loads read 0");
        if (pi >= 0 && v + 64 <= (uint64_t)(uintptr_t)pr.hi) { const float *f = (const float *)(uintptr_t)v; const uint32_t *u = (const uint32_t *)(uintptr_t)v;
            LOG("[vk] raw global memory check:   at %#llx: %08x %08x %08x %08x %08x %08x %08x %08x / as floats %g %g %g %g %g %g %g %g %g %g %g %g", (unsigned long long)v, u[0], u[1], u[2], u[3], u[4], u[5], u[6], u[7],
                f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[10], f[11]); }
    }
}
