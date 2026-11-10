// ---------------- BC blocks a GPU encoder drew, decoded on the GPU (included by gfx_vk.c after gfx_vk_dscopy.inc) ----------------
// On a GPU without BC textures (Mali, Xclipse: textureCompressionBC false) vt_create keeps a BC texture decoded (bc_target), and only the CPU decoded it: uploads and
// buffer copies go through bcdec. A GPU block encoder draws the blocks themselves, through a one-block-per-texel view (bcrt_shadow): Breath of the Wild's BC4 encoder
// (agl, 8e2cc2671cae6020) writes a 32x32x32 BC4 volume a depth plane per pass through an RGBA16UI view. bcrt_shadow left decoded images out (it copies blocks in and out
// with vkCmdCopyImage, and a decoded image holds texels), so the pass drew its uint blocks straight into the R8 image, as R8, and what the game later sampled there was
// never the encoded volume. Now the pass draws into the shadow as on a GPU with BC, and its end decodes the shadow's blocks into the image: the blocks copied into an
// arena buffer, a compute pass (shaders/bc_decode.comp) writing the bytes bcdec's precise decoder gives, and those copied into the level and layer (or depth plane) the
// pass drew. The shadow keeps the blocks between passes, so a pass that draws only some blocks keeps the others from its last pass (zeros before the first: a texture
// the CPU filled and an encoder then partly redrew would lose the CPU's blocks; no game is known to do that). BC4 and BC5 only, in both signednesses: an encoder of
// another BC format keeps the old behaviour, with a red line. A GPU with BC textures never decodes (v->conv is 0), so nothing here runs there.
// DM_VK_BC_GPU_DECODE=0 (env.txt): decoded images left out of bcrt_shadow, as before
static const uint32_t k_bcd_cs[] =
#include "shaders/bc_decode.comp.inc"
;
static VkShaderModule g_bcd_m; static VkDescriptorSetLayout g_bcd_dsl; static VkPipelineLayout g_bcd_pl; static VkPipeline g_bcd_p;
static uint64_t g_bcd_n;   // shadows decoded into their images
typedef struct { uint32_t bw, bh, kind; } bcd_pc;   // the shader's push constants: blocks wide and high, the format (bcd_kind)
static int bcd_on(void) {
    static int v = -1;
    if (v < 0) { const char *e = getenv("DM_VK_BC_GPU_DECODE"); v = !(e && *e == '0'); if (!v) LOG("[vk] DM_VK_BC_GPU_DECODE=0: a GPU block encoder's pass into a BC texture decoded on the CPU draws into the decoded image, as before"); }
    return v;
}
static int bcd_kind(int conv) {   // the shader's format number for a decoded image's conv; -1: not one it decodes
    switch (conv) { case CONV_BC4: return 0; case CONV_BC4S: return 1; case CONV_BC5: return 2; case CONV_BC5S: return 3; default: return -1; }
}
// whether bcrt_shadow may shadow decoded image b (bcd_decode then decodes the shadow after the pass)
static int bcd_takes(const vtex *b) {
    if (!bcd_on()) return 0;
    if (bcd_kind(b->conv) >= 0) return 1;
    RED_ONCE(175, "a GPU block encoder draws into a BC texture decoded on the CPU (format %d): only BC4 and BC5 are decoded on the GPU, the pass draws into the decoded image", b->nvfmt);
    return 0;
}
static int bcd_init(void) {   // the shader, layouts and pipeline, once; 0 when they cannot be made (the shadow is then left undecoded)
    static int failed; if (g_bcd_p) return 1; if (failed) return 0;
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof k_bcd_cs, .pCode = k_bcd_cs};
    VkDescriptorSetLayoutBinding b[2] = {{0, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, VK_SHADER_STAGE_COMPUTE_BIT, NULL}};
    VkDescriptorSetLayoutCreateInfo dl = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = b};
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof(bcd_pc)};
    VkPipelineLayoutCreateInfo pl = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr};
    int ok = vkCreateShaderModule(g_vk.dev, &mc, NULL, &g_bcd_m) == VK_SUCCESS && vkCreateDescriptorSetLayout(g_vk.dev, &dl, NULL, &g_bcd_dsl) == VK_SUCCESS;
    pl.pSetLayouts = &g_bcd_dsl;
    ok = ok && vkCreatePipelineLayout(g_vk.dev, &pl, NULL, &g_bcd_pl) == VK_SUCCESS;
    VkComputePipelineCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = g_bcd_pl,
                                      .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = g_bcd_m, .pName = "main"}};
    ok = ok && vkCreateComputePipelines(g_vk.dev, pcache(), 1, &ci, NULL, &g_bcd_p) == VK_SUCCESS;
    if (!ok) { failed = 1; g_bcd_p = VK_NULL_HANDLE; RED_ONCE(176, "BC decode on the GPU: its shader, layouts or pipeline could not be made: encoders' blocks stay undecoded"); return 0; }
    LOG("[vk] BC4 / BC5 blocks a GPU encoder draws into a BC texture decoded on the CPU are decoded on the GPU after its pass");
    return 1;
}
static VkDescriptorSet bcd_set(VkBuffer ib, VkDeviceSize io, VkDeviceSize in, VkBuffer ob, VkDeviceSize oo, VkDeviceSize on) {   // one of the current chunk's own sets, written now
    chunk *c = cur(); if (!c) return VK_NULL_HANDLE;
    if (c->bcd_used == c->nbcd) {
        VkDescriptorSet s = ds_alloc(g_bcd_dsl); if (!s) return VK_NULL_HANDLE;
        if (c->nbcd == c->cbcd) { c->cbcd = c->cbcd ? 2 * c->cbcd : 8; c->bcd = realloc(c->bcd, (size_t)c->cbcd * sizeof *c->bcd); }
        c->bcd[c->nbcd++] = s;
    }
    VkDescriptorSet set = c->bcd[c->bcd_used++];
    VkDescriptorBufferInfo bi[2] = {{ib, io, in}, {ob, oo, on}};
    VkWriteDescriptorSet w[2] = {{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, set, 0, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bi[0], NULL},
                                 {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, set, 1, 0, 1, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, NULL, &bi[1], NULL}};
    vkUpdateDescriptorSets(g_vk.dev, 2, w, 0, NULL);
    return set;
}
// After the pass (rp_end, outside it): shadow s's blocks decoded into decoded image b's level lv, layer (or depth plane) ly; 0 when not made (the image keeps what it held)
static int bcd_decode(vtex *b, vtex *s, uint32_t lv, uint32_t ly) {
    int kind = bcd_kind(b->conv); if (kind < 0 || !bcd_init()) return 0;
    uint32_t lw = b->w >> lv ? b->w >> lv : 1, lh = b->h >> lv ? b->h >> lv : 1, bw = s->w, bh = s->h;   // the shadow is blocks x blocks of the level
    VkDeviceSize nin = (VkDeviceSize)bw * bh * (kind < 2 ? 8 : 16), nout = (VkDeviceSize)bw * 4 * bh * 4 * (VkDeviceSize)b->px;
    VkBuffer ib, ob; VkDeviceSize io, oo;
    if (!ar_alloc(nin, &ib, &io) || !ar_alloc(nout, &ob, &oo)) return 0;   // offsets aligned to 256: storage buffer offsets and both copies' texel sizes
    VkDescriptorSet set = bcd_set(ib, io, nin, ob, oo, nout); VkCommandBuffer c = cb(); if (!set || !c) return 0;
    VkBufferImageCopy in = {.bufferOffset = io, .imageSubresource = {VK_IMAGE_ASPECT_COLOR_BIT, 0, 0, 1}, .imageExtent = {bw, bh, 1}};
    VkBufferImageCopy out = {.bufferOffset = oo, .bufferRowLength = bw * 4, .bufferImageHeight = bh * 4, .imageSubresource = bcrt_sub(b, lv, ly), .imageOffset = bcrt_off(b, ly), .imageExtent = {lw, lh, 1}};
    bcd_pc pc = {bw, bh, (uint32_t)kind};
    cb_barrier();
    vkCmdCopyImageToBuffer(c, s->img, VK_IMAGE_LAYOUT_GENERAL, ib, 1, &in);
    cb_barrier();
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, g_bcd_p);
    vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, g_bcd_pl, 0, 1, &set, 0, NULL);
    vkCmdPushConstants(c, g_bcd_pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, sizeof pc, &pc);
    vkCmdDispatch(c, (bw + 7) / 8, (bh + 7) / 8, 1);
    cb_barrier();
    vkCmdCopyBufferToImage(c, ob, b->img, VK_IMAGE_LAYOUT_GENERAL, 1, &out);
    cb_barrier(); bf_reset();   // the next draw binds its own state again (push constants set through another layout)
    crumb('c', "bc_decode", "", (bw + 7) / 8, (bh + 7) / 8);
    static int nlog; if (nlog++ < 4) LOG("[vk] compressed render target s%llu (vk%d decoded to vk%d, %ux%u level %u layer %u): its %ux%u blocks decoded on the GPU after the pass",
                                        (unsigned long long)b->serial, b->nvfmt, b->fmt, b->w, b->h, lv, ly, bw, bh);
    g_bcd_n++;
    return 1;
}
