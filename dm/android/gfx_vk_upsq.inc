// ---------------- A game's upscaler network replaced by a bilinear scale and a signed square (included by gfx_vk.c after gfx_vk_bcdec.inc) ----------------
// Ocarina of Time upscales its 1440x810 scene to 1920x1080 with a neural network in one compute dispatch (agl's NDSR, fa3033d05c0a41d6: HMMA tiles through shared
// memory). It draws the picture right since its input is written (#193) and its warp operations fit 64-lane subgroups (#189), but it is the frame's slowest step: on the
// OnePlus Pad 3's Adreno 830 21 of a frame's 45 ms of GPU work (Kokiri Forest 10.4 fps, 15.8 replaced), on the Galaxy Z Fold 8's Adreno 840 GPU 73 against 41-48 ms (11.0
// fps, 16.0-17.8 replaced). DeathKhan's nx2android fork replaced it on the Odin 3's Adreno 830 (8569eeb); the idea is theirs, written anew here.
// - Which dispatches: with DM_VK_UPSCALER_SQUARE=1 (Ocarina of Time's android_defaults.txt), a compute shader with the network's interface: one combined 2D texture, one
//   2D storage image it loads and stores (no atomics), one read-only storage buffer, and nothing else. The game picks one of four networks by its dynamic resolution
//   (fa3033d05c0a41d6, 7c511cc23ff85d14, b106afba1a18faa9, d99fbeeb53d38847), all of that interface, as BananaNative matches them (ndsr_iface); so do 49 more of its compute
//   shaders, other networks. So a dispatch is replaced only when its input is E5B9G9R9 (a335c1db6270c355's square-root colour, the networks' input) and its output a larger
//   B10G11R11 image; any other runs as it is. DM_VK_UPSCALER_SQUARE_CS lists keys to replace besides (comma separated). stage_set notes the shader's first texture and first
//   image as it binds them (g_upsq_src, g_upsq_dst), and vk_dispatch records this in place of the network's dispatch.
// - What: shaders/upscale_square.comp samples the input bilinearly at each output texel's centre and writes x * |x| into an RGBA16F intermediate of the output's size,
//   which a blit converts into the output. The network's input holds square-root encoded colour and its output linear colour, so the square is the decode; only an
//   E5B9G9R9 input is that encoding (a B10G11R11 one is linear, as BananaNative found), so that input and a B10G11R11 output is the one pair replaced. A listed key with
//   another runs the network with a red line.
// DM_VK_UPSCALER_SQUARE=0 or DM_VK_UPSCALER_SQUARE_CS=0 (env.txt): every network runs, as the game made it
static const uint32_t k_upsq_cs[] =
#include "shaders/upscale_square.comp.inc"
;
static VkShaderModule g_upsq_m; static VkDescriptorSetLayout g_upsq_dsl; static VkPipelineLayout g_upsq_pl; static VkPipeline g_upsq_p; static VkSampler g_upsq_smp;
static struct { VkImage img; VkDeviceMemory mem; VkImageView iv; uint32_t w, h; } g_upsq_tmp;   // the RGBA16F intermediate, kept while the output's size stays
static uint64_t g_upsq_n;   // dispatches replaced
static int upsq_off(void) { const char *a = getenv("DM_VK_UPSCALER_SQUARE"), *b = getenv("DM_VK_UPSCALER_SQUARE_CS"); return (a && !strcmp(a, "0")) || (b && !strcmp(b, "0")); }
static int upsq_listed(const char *key) {   // whether DM_VK_UPSCALER_SQUARE_CS lists the compute shader key (16 hex digits)
    static char l[1024]; static int init;
    if (!init) { init = 1; const char *e = getenv("DM_VK_UPSCALER_SQUARE_CS"); snprintf(l, sizeof l, "%s", e && strcmp(e, "0") ? e : "");
        if (l[0]) LOG("[vk] upscaler networks replaced by a bilinear scale and a signed square: %s (DM_VK_UPSCALER_SQUARE_CS)", l); }
    for (const char *p = l; *p; ) { if (!strncmp(p, key, 16) && (p[16] == ',' || !p[16])) return 1; p = strchr(p, ','); if (!p) break; p++; }
    return 0;
}
// 1: a listed key; 2: the network's interface with DM_VK_UPSCALER_SQUARE=1 (the dispatch still checks its formats and sizes: upsq_run); 0: neither, or switched off
static int upsq_match(const vshader *s) {
    static int mode = -1;
    if (mode < 0) { const char *e = getenv("DM_VK_UPSCALER_SQUARE"); mode = upsq_off() ? 0 : e && *e == '1';
        if (upsq_off()) LOG("[vk] DM_VK_UPSCALER_SQUARE=0: a game's upscaler network runs as it is");
        else if (mode) LOG("[vk] DM_VK_UPSCALER_SQUARE=1: an upscaler network of the NDSR interface, square-root E5B9G9R9 colour in, is replaced by a bilinear scale and a signed square"); }
    if (s->stage != SH_CS || upsq_off()) return 0;
    if (upsq_listed(s->key)) return 1;
    if (!mode) return 0;
    return s->nsb == 1 && !(s->sb[0].flags & 1) && s->ntx == 1 && s->tx[0].type == 3 && s->tx[0].array <= 1 && !s->tx[0].separate
        && s->nim == 1 && s->im[0].type == 3 && s->im[0].array <= 1 && s->im[0].flags == 7 ? 2 : 0;   // images' flags 7: loaded and stored, no atomics
}
static int upsq_init(void) {   // the shader, sampler, layouts and pipeline, once; 0 when they cannot be made (the network then runs)
    static int failed; if (g_upsq_p) return 1; if (failed) return 0;
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof k_upsq_cs, .pCode = k_upsq_cs};
    VkSamplerCreateInfo sc = {.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_LINEAR, .minFilter = VK_FILTER_LINEAR, .mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST,
                              .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE};
    VkDescriptorSetLayoutBinding b[2] = {{0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}};
    VkDescriptorSetLayoutCreateInfo dl = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = b};
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 8};
    VkPipelineLayoutCreateInfo pl = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr};
    int ok = vkCreateShaderModule(g_vk.dev, &mc, NULL, &g_upsq_m) == VK_SUCCESS && vkCreateSampler(g_vk.dev, &sc, NULL, &g_upsq_smp) == VK_SUCCESS
          && vkCreateDescriptorSetLayout(g_vk.dev, &dl, NULL, &g_upsq_dsl) == VK_SUCCESS;
    pl.pSetLayouts = &g_upsq_dsl;
    ok = ok && vkCreatePipelineLayout(g_vk.dev, &pl, NULL, &g_upsq_pl) == VK_SUCCESS;
    VkComputePipelineCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = g_upsq_pl,
                                      .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = g_upsq_m, .pName = "main"}};
    ok = ok && vkCreateComputePipelines(g_vk.dev, pcache(), 1, &ci, NULL, &g_upsq_p) == VK_SUCCESS;
    if (!ok) { failed = 1; g_upsq_p = VK_NULL_HANDLE; RED_ONCE(126, "upscaler replacement: its shader, layouts or pipeline could not be made: the network runs"); }
    return ok;
}
static int upsq_tmp(uint32_t w, uint32_t h) {   // the intermediate at the output's size; the one it replaces goes when the current chunk completes
    if (g_upsq_tmp.img && g_upsq_tmp.w == w && g_upsq_tmp.h == h) return 1;
    VkImageCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_IMAGE_CREATE_INFO, .imageType = VK_IMAGE_TYPE_2D, .format = VK_FORMAT_R16G16B16A16_SFLOAT, .extent = {w, h, 1}, .mipLevels = 1, .arrayLayers = 1,
                            .samples = VK_SAMPLE_COUNT_1_BIT, .tiling = VK_IMAGE_TILING_OPTIMAL, .usage = VK_IMAGE_USAGE_STORAGE_BIT | VK_IMAGE_USAGE_TRANSFER_SRC_BIT,
                            .sharingMode = VK_SHARING_MODE_EXCLUSIVE, .initialLayout = VK_IMAGE_LAYOUT_UNDEFINED};
    VkImage img = VK_NULL_HANDLE; VkDeviceMemory mem = VK_NULL_HANDLE; VkImageView iv = VK_NULL_HANDLE; VkMemoryRequirements mr;
    int ok = vkCreateImage(g_vk.dev, &ic, NULL, &img) == VK_SUCCESS;
    if (ok) { vkGetImageMemoryRequirements(g_vk.dev, img, &mr); uint32_t mt = vkb_mem_type(mr.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT);
        VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr.size, .memoryTypeIndex = mt == UINT32_MAX ? vkb_mem_type(mr.memoryTypeBits, 0) : mt};
        ok = vkAllocateMemory(g_vk.dev, &ma, NULL, &mem) == VK_SUCCESS && vkBindImageMemory(g_vk.dev, img, mem, 0) == VK_SUCCESS; }
    VkImageViewCreateInfo vc = {.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO, .image = img, .viewType = VK_IMAGE_VIEW_TYPE_2D, .format = VK_FORMAT_R16G16B16A16_SFLOAT,
                                .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    ok = ok && vkCreateImageView(g_vk.dev, &vc, NULL, &iv) == VK_SUCCESS;
    VkCommandBuffer c = ok ? cb() : VK_NULL_HANDLE;
    if (!c) { if (iv) vkDestroyImageView(g_vk.dev, iv, NULL); if (img) vkDestroyImage(g_vk.dev, img, NULL); if (mem) vkFreeMemory(g_vk.dev, mem, NULL);
        RED_ONCE(127, "upscaler replacement: no %ux%u intermediate: the network runs", w, h); return 0; }
    VkImageMemoryBarrier b = {.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER, .dstAccessMask = VK_ACCESS_SHADER_WRITE_BIT, .oldLayout = VK_IMAGE_LAYOUT_UNDEFINED, .newLayout = VK_IMAGE_LAYOUT_GENERAL,
        .srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED, .image = img, .subresourceRange = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 1, 0, 1}};
    vkCmdPipelineBarrier(c, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_COMPUTE_SHADER_BIT, 0, 0, NULL, 0, NULL, 1, &b);
    if (g_upsq_tmp.img) { dead_add(1, (uint64_t)g_upsq_tmp.iv); dead_add(3, (uint64_t)g_upsq_tmp.img); dead_add(4, (uint64_t)g_upsq_tmp.mem); }
    g_upsq_tmp.img = img; g_upsq_tmp.mem = mem; g_upsq_tmp.iv = iv; g_upsq_tmp.w = w; g_upsq_tmp.h = h;
    return 1;
}
static VkDescriptorSet upsq_set(VkImageView src) {   // one of the current chunk's own sets, written now (as bcd_set)
    chunk *c = cur(); if (!c) return VK_NULL_HANDLE;
    if (c->ups_used == c->nups) {
        VkDescriptorSet s = ds_alloc(g_upsq_dsl); if (!s) return VK_NULL_HANDLE;
        if (c->nups == c->cups) { c->cups = c->cups ? 2 * c->cups : 4; c->ups = realloc(c->ups, (size_t)c->cups * sizeof *c->ups); }
        c->ups[c->nups++] = s;
    }
    VkDescriptorSet set = c->ups[c->ups_used++];
    VkDescriptorImageInfo ii[2] = {{g_upsq_smp, src, VK_IMAGE_LAYOUT_GENERAL}, {VK_NULL_HANDLE, g_upsq_tmp.iv, VK_IMAGE_LAYOUT_GENERAL}};
    VkWriteDescriptorSet w[2] = {{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, set, 0, 0, 1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, &ii[0], NULL, NULL},
                                 {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, set, 1, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_IMAGE, &ii[1], NULL, NULL}};
    vkUpdateDescriptorSets(g_vk.dev, 2, w, 0, NULL);
    return set;
}
// In place of a listed network's dispatch, with what stage_set noted: 1 when recorded, 0 when it cannot be (the caller dispatches the network)
static int upsq_run(const vshader *sh) {
    vtex *s = g_upsq_src, *d = g_upsq_dst; VkImageView siv = g_upsq_src_iv;
    if (!s || !d || !siv || s == d || s->conv || d->conv || s->samples > 1 || d->samples > 1 || d->type != VK_IMAGE_TYPE_2D || d->aspect != VK_IMAGE_ASPECT_COLOR_BIT || d->w < s->w || d->h < s->h) return 0;
    if (s->fmt != VK_FORMAT_E5B9G9R9_UFLOAT_PACK32 || d->fmt != VK_FORMAT_B10G11R11_UFLOAT_PACK32 || (d->w == s->w && d->h == s->h)) {   // not the NDSR networks' square-root input, or no upscale
        if (sh->upsq == 1) RED_ONCE(128, "upscaler replacement: input format %d and output format %d are not the pair it decodes (E5B9G9R9 square-root colour in, B10G11R11 out): the network runs", s->fmt, d->fmt);
        return 0; }
    VkFormatProperties ip, op, tp; vkGetPhysicalDeviceFormatProperties(g_vk.pd, s->fmt, &ip); vkGetPhysicalDeviceFormatProperties(g_vk.pd, d->fmt, &op);
    vkGetPhysicalDeviceFormatProperties(g_vk.pd, VK_FORMAT_R16G16B16A16_SFLOAT, &tp);
    if (!(ip.optimalTilingFeatures & VK_FORMAT_FEATURE_SAMPLED_IMAGE_FILTER_LINEAR_BIT) || !(op.optimalTilingFeatures & VK_FORMAT_FEATURE_BLIT_DST_BIT) || !(d->usage & VK_IMAGE_USAGE_TRANSFER_DST_BIT)
        || (tp.optimalTilingFeatures & (VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT | VK_FORMAT_FEATURE_BLIT_SRC_BIT)) != (VK_FORMAT_FEATURE_STORAGE_IMAGE_BIT | VK_FORMAT_FEATURE_BLIT_SRC_BIT)) {
        RED_ONCE(129, "upscaler replacement: the GPU cannot filter format %d, blit to format %d or store and blit RGBA16F: the network runs", s->fmt, d->fmt); return 0; }
    if (!upsq_init() || !upsq_tmp(d->w, d->h)) return 0;
    VkDescriptorSet set = upsq_set(siv); VkCommandBuffer c = cb(); if (!set || !c) return 0;
    uint32_t pc[2] = {d->w, d->h};
    cb_barrier();
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, g_upsq_p);
    vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, g_upsq_pl, 0, 1, &set, 0, NULL);
    vkCmdPushConstants(c, g_upsq_pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, pc);
    vkCmdDispatch(c, (d->w + 7) / 8, (d->h + 7) / 8, 1);
    cb_barrier();
    VkImageBlit bl = {{VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {{0, 0, 0}, {(int32_t)d->w, (int32_t)d->h, 1}}, {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, {{0, 0, 0}, {(int32_t)d->w, (int32_t)d->h, 1}}};
    vkCmdBlitImage(c, g_upsq_tmp.img, VK_IMAGE_LAYOUT_GENERAL, d->img, VK_IMAGE_LAYOUT_GENERAL, 1, &bl, VK_FILTER_NEAREST);
    cb_barrier(); bf_reset();   // the next draw or dispatch binds its own state again (a compute pipeline and push constants through another layout)
    crumb('c', "upscale_square", "", (d->w + 7) / 8, (d->h + 7) / 8);
    if (g_upsq_n++ < 4) LOG("[vk] upscaler network %s replaced (%s): s%llu %ux%u (vk%d) scaled to s%llu %ux%u (vk%d) by a bilinear filter and a signed square", sh->key,
                            sh->upsq == 1 ? "listed" : "by its interface", (unsigned long long)s->serial, s->w, s->h, s->fmt, (unsigned long long)d->serial, d->w, d->h, d->fmt);
    return 1;
}
