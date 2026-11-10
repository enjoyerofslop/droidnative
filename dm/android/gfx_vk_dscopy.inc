// ---------------- Depth-stencil copies drawn (included by gfx_vk.c after gfx_vk_draw.inc) ----------------
// A copy between depth-stencil textures that a blit cannot make: the Adreno drivers give D32_SFLOAT_S8_UINT no BLIT_SRC / BLIT_DST, and vkCmdCopyImage neither scales
// nor changes format. Link's Awakening copies its 1280x720 depth-stencil target to half size every frame, and its ambient occlusion tests the copy's stencil (bit 1):
// skipped, the occlusion never drew. The copy is drawn into the destination as its depth-stencil attachment, as the Mac's copy_t2t_draw does: each fragment takes its
// source texel's depth as gl_FragDepth from a depth view of the source, and its stencil from a stencil view, written through VK_EXT_shader_stencil_export where the
// device has it (the Adreno 740 and 830). Without it, bit by bit: a first draw writes the depth and stencil 0, then a draw per bit discards where the source's bit is
// clear and writes that bit alone (write mask 1 << bit, reference 0xff). Nearest texels, as a depth copy must not filter; a mirrored copy reads its source backwards.
static const uint32_t k_dsc_vs[] =
#include "shaders/ds_copy.vert.inc"
;
static const uint32_t k_dsc_fs_export[] =
#include "shaders/ds_copy_export.frag.inc"
;
static const uint32_t k_dsc_fs_bits[] =
#include "shaders/ds_copy_bits.frag.inc"
;
typedef struct { float off[2], scale[2]; int32_t lo[2], hi[2]; int32_t bit; } dsc_map;   // the shaders' push constants: source texel = off + frag × scale, clamped to [lo, hi]
static VkDescriptorSetLayout g_dsc_dsl; static VkPipelineLayout g_dsc_pl; static VkSampler g_dsc_samp; static VkShaderModule g_dsc_vs, g_dsc_fs[2];   // fs: 0 export, 1 bits
static struct { VkRenderPass rp; int bits; VkPipeline p; } g_dsc_pipes[16]; static int g_dsc_np;

static VkShaderModule dsc_module(const uint32_t *words, size_t bytes) {
    VkShaderModuleCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = bytes, .pCode = words};
    VkShaderModule m = VK_NULL_HANDLE; return vkCreateShaderModule(g_vk.dev, &ci, NULL, &m) == VK_SUCCESS ? m : VK_NULL_HANDLE;
}
static int dsc_init(void) {   // the layouts, sampler and modules, once; 0 when they cannot be made (the copy is then skipped, as before)
    static int failed; if (g_dsc_pl) return 1; if (failed) return 0;
    g_dsc_vs = dsc_module(k_dsc_vs, sizeof k_dsc_vs);
    g_dsc_fs[0] = g_stencil_export ? dsc_module(k_dsc_fs_export, sizeof k_dsc_fs_export) : VK_NULL_HANDLE;
    g_dsc_fs[1] = dsc_module(k_dsc_fs_bits, sizeof k_dsc_fs_bits);
    VkDescriptorSetLayoutBinding b[2] = {{0, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL}, {1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, 1, VK_SHADER_STAGE_FRAGMENT_BIT, NULL}};
    VkDescriptorSetLayoutCreateInfo dl = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = 2, .pBindings = b};
    VkPushConstantRange pr = {VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof(dsc_map)};
    VkSamplerCreateInfo sc = {.sType = VK_STRUCTURE_TYPE_SAMPLER_CREATE_INFO, .magFilter = VK_FILTER_NEAREST, .minFilter = VK_FILTER_NEAREST, .mipmapMode = VK_SAMPLER_MIPMAP_MODE_NEAREST,
                              .addressModeU = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeV = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE, .addressModeW = VK_SAMPLER_ADDRESS_MODE_CLAMP_TO_EDGE};
    if (!g_dsc_vs || !g_dsc_fs[1] || (g_stencil_export && !g_dsc_fs[0]) || vkCreateDescriptorSetLayout(g_vk.dev, &dl, NULL, &g_dsc_dsl) != VK_SUCCESS
        || vkCreateSampler(g_vk.dev, &sc, NULL, &g_dsc_samp) != VK_SUCCESS) { failed = 1; RED_ONCE(140, "depth-stencil copy: its shaders, layout or sampler could not be made"); return 0; }
    VkPipelineLayoutCreateInfo pl = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &g_dsc_dsl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr};
    if (vkCreatePipelineLayout(g_vk.dev, &pl, NULL, &g_dsc_pl) != VK_SUCCESS) { failed = 1; RED_ONCE(140, "depth-stencil copy: its pipeline layout could not be made"); return 0; }
    LOG("[vk] depth-stencil copies a blit cannot make are drawn (%s)", g_stencil_export ? "stencil through VK_EXT_shader_stencil_export" : "stencil a bit at a time: no stencil export");
    return 1;
}
static VkPipeline dsc_pipe(VkRenderPass rp, int bits) {   // the copy's pipeline for the destination's pass
    for (int i = 0; i < g_dsc_np; i++) if (g_dsc_pipes[i].rp == rp && g_dsc_pipes[i].bits == bits) return g_dsc_pipes[i].p;
    if (g_dsc_np == (int)(sizeof g_dsc_pipes / sizeof *g_dsc_pipes)) return VK_NULL_HANDLE;
    VkPipelineShaderStageCreateInfo st[2] = {{.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_VERTEX_BIT, .module = g_dsc_vs, .pName = "main"},
                                             {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_FRAGMENT_BIT, .module = g_dsc_fs[bits], .pName = "main"}};
    VkPipelineVertexInputStateCreateInfo vi = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO};
    VkPipelineInputAssemblyStateCreateInfo ia = {.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO, .topology = VK_PRIMITIVE_TOPOLOGY_TRIANGLE_LIST};
    VkPipelineViewportStateCreateInfo vp = {.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO, .viewportCount = 1, .scissorCount = 1};
    VkPipelineRasterizationStateCreateInfo rs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO, .polygonMode = VK_POLYGON_MODE_FILL, .cullMode = VK_CULL_MODE_NONE, .lineWidth = 1};
    VkPipelineMultisampleStateCreateInfo ms = {.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO, .rasterizationSamples = VK_SAMPLE_COUNT_1_BIT};
    VkStencilOpState so = {VK_STENCIL_OP_KEEP, VK_STENCIL_OP_REPLACE, VK_STENCIL_OP_REPLACE, VK_COMPARE_OP_ALWAYS, 0xff, 0xff, 0};   // the depth test always passes: REPLACE writes
    VkPipelineDepthStencilStateCreateInfo ds = {.sType = VK_STRUCTURE_TYPE_PIPELINE_DEPTH_STENCIL_STATE_CREATE_INFO, .depthTestEnable = VK_TRUE, .depthWriteEnable = VK_TRUE,
                                                .depthCompareOp = VK_COMPARE_OP_ALWAYS, .stencilTestEnable = VK_TRUE, .front = so, .back = so};   // depth writes need the test on
    VkPipelineColorBlendStateCreateInfo cbs = {.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO};
    VkDynamicState dyn[] = {VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR, VK_DYNAMIC_STATE_STENCIL_WRITE_MASK, VK_DYNAMIC_STATE_STENCIL_REFERENCE};
    VkPipelineDynamicStateCreateInfo dy = {.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO, .dynamicStateCount = sizeof dyn / sizeof *dyn, .pDynamicStates = dyn};
    VkGraphicsPipelineCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO, .stageCount = 2, .pStages = st, .pVertexInputState = &vi, .pInputAssemblyState = &ia,
                                       .pViewportState = &vp, .pRasterizationState = &rs, .pMultisampleState = &ms, .pDepthStencilState = &ds, .pColorBlendState = &cbs,
                                       .pDynamicState = &dy, .layout = g_dsc_pl, .renderPass = rp};
    VkPipeline p = VK_NULL_HANDLE;
    if (vkCreateGraphicsPipelines(g_vk.dev, pcache(), 1, &ci, NULL, &p) != VK_SUCCESS) { RED_ONCE(141, "depth-stencil copy: its pipeline could not be made"); return VK_NULL_HANDLE; }
    g_dsc_pipes[g_dsc_np++] = (typeof(g_dsc_pipes[0])){rp, bits, p};
    return p;
}
static VkDescriptorSet dsc_set(VkImageView depth, VkImageView stencil) {   // one of the current chunk's own sets, written now: it is recorded, so the GPU reads none of its sets
    chunk *c = cur(); if (!c) return VK_NULL_HANDLE;
    if (c->dsc_used == c->ndsc) {
        VkDescriptorSet s = ds_alloc(g_dsc_dsl); if (!s) return VK_NULL_HANDLE;
        if (c->ndsc == c->cdsc) { c->cdsc = c->cdsc ? 2 * c->cdsc : 8; c->dsc = realloc(c->dsc, (size_t)c->cdsc * sizeof *c->dsc); }
        c->dsc[c->ndsc++] = s;
    }
    VkDescriptorSet set = c->dsc[c->dsc_used++];
    VkDescriptorImageInfo ii[2] = {{g_dsc_samp, depth, VK_IMAGE_LAYOUT_GENERAL}, {g_dsc_samp, stencil ? stencil : depth, VK_IMAGE_LAYOUT_GENERAL}};   // no stencil: unread
    VkWriteDescriptorSet w[2] = {{VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, set, 0, 0, 1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, &ii[0], NULL, NULL},
                                 {VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, NULL, set, 1, 0, 1, VK_DESCRIPTOR_TYPE_COMBINED_IMAGE_SAMPLER, &ii[1], NULL, NULL}};
    vkUpdateDescriptorSets(g_vk.dev, 2, w, 0, NULL);
    return set;
}
// The copy of c (a source level / layer sl, sz into dl, dz of a depth or depth-stencil destination), drawn; 0: not made (the caller reports it, as before)
static int ds_copy_draw(vtex *s, vtex *d, unsigned sl, unsigned sz, unsigned dl, unsigned dz, const p_copy_t2t *c) {
    if (!(s->aspect & VK_IMAGE_ASPECT_DEPTH_BIT) || !(d->aspect & VK_IMAGE_ASPECT_DEPTH_BIT) || s->samples > 1 || d->samples > 1 || s->type == VK_IMAGE_TYPE_3D || d->type == VK_IMAGE_TYPE_3D) return 0;
    if ((c->sr.depth ? c->sr.depth : 1) != 1 || (c->dr.depth ? c->dr.depth : 1) != 1 || (s == d && sl == dl && sz + c->sr.zoffset == dz + c->dr.zoffset)) return 0;
    if (c->sr.width <= 0 || c->sr.height <= 0 || c->dr.width <= 0 || c->dr.height <= 0 || !dsc_init()) return 0;
    int ss = (s->aspect & VK_IMAGE_ASPECT_STENCIL_BIT) != 0, dsn = (d->aspect & VK_IMAGE_ASPECT_STENCIL_BIT) != 0, bits = !(ss && dsn && g_stencil_export);
    VkImageView sdv = view_get(s, VK_IMAGE_VIEW_TYPE_2D, sl, 1, sz + (unsigned)c->sr.zoffset, 1, VK_IMAGE_ASPECT_DEPTH_BIT, NULL);
    VkImageView ssv = ss ? view_get(s, VK_IMAGE_VIEW_TYPE_2D, sl, 1, sz + (unsigned)c->sr.zoffset, 1, VK_IMAGE_ASPECT_STENCIL_BIT, NULL) : VK_NULL_HANDLE;
    g_view_slice = 1; VkImageView dv = view_get(d, VK_IMAGE_VIEW_TYPE_2D, dl, 1, dz + (unsigned)c->dr.zoffset, 1, d->aspect, NULL); g_view_slice = 0;
    if (!sdv || !dv || (ss && !ssv)) return 0;
    rp_key k; memset(&k, 0, sizeof k); k.depth = d->fmt; k.samples = 1;
    VkRenderPass rp = rp_get(&k); VkPipeline p = rp ? dsc_pipe(rp, bits) : VK_NULL_HANDLE; if (!p) return 0;
    uint32_t w = d->w >> dl ? d->w >> dl : 1, h = d->h >> dl ? d->h >> dl : 1;
    struct { VkImageView v[9]; uint32_t w, h, l; } fk; memset(&fk, 0, sizeof fk); fk.v[0] = dv; fk.w = w; fk.h = h; fk.l = 1;   // rp_start's key: its framebuffers go with their views
    VkFramebuffer fb = nvn_hm_get(&g_fbs, &fk);
    if (!fb) {
        VkFramebufferCreateInfo fc = {.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO, .renderPass = rp, .attachmentCount = 1, .pAttachments = &dv, .width = w, .height = h, .layers = 1};
        if (vkCreateFramebuffer(g_vk.dev, &fc, NULL, &fb) != VK_SUCCESS) return 0;
        nvn_hm_put(&g_fbs, &fk, fb);
    }
    VkDescriptorSet set = dsc_set(sdv, ssv); VkCommandBuffer cbuf = cb(); if (!set || !cbuf) return 0;   // cb ends the targets' pass
    int x0 = c->dr.xoffset < 0 ? 0 : c->dr.xoffset, y0 = c->dr.yoffset < 0 ? 0 : c->dr.yoffset;
    int x1 = c->dr.xoffset + c->dr.width > (int)w ? (int)w : c->dr.xoffset + c->dr.width, y1 = c->dr.yoffset + c->dr.height > (int)h ? (int)h : c->dr.yoffset + c->dr.height;
    if (x1 <= x0 || y1 <= y0) return 1;
    float kx = (float)c->sr.width / (float)c->dr.width, ky = (float)c->sr.height / (float)c->dr.height;
    dsc_map m = {{c->sr.xoffset - c->dr.xoffset * kx, c->sr.yoffset - c->dr.yoffset * ky}, {kx, ky}, {c->sr.xoffset, c->sr.yoffset},
                 {c->sr.xoffset + c->sr.width - 1, c->sr.yoffset + c->sr.height - 1}, -1};
    if (c->flags & NVN_COPY_FLAGS_MIRROR_X_BIT) { m.off[0] = c->sr.xoffset + c->sr.width + c->dr.xoffset * kx; m.scale[0] = -kx; }
    if (c->flags & NVN_COPY_FLAGS_MIRROR_Y_BIT) { m.off[1] = c->sr.yoffset + c->sr.height + c->dr.yoffset * ky; m.scale[1] = -ky; }
    cb_barrier();
    VkRenderPassBeginInfo bi = {.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO, .renderPass = rp, .framebuffer = fb, .renderArea = {{x0, y0}, {(uint32_t)(x1 - x0), (uint32_t)(y1 - y0)}}};
    vkCmdBeginRenderPass(cbuf, &bi, VK_SUBPASS_CONTENTS_INLINE); bf_reset();   // its pipeline and dynamic state are set behind the bind filter (bf_*)
    vkCmdBindPipeline(cbuf, VK_PIPELINE_BIND_POINT_GRAPHICS, p);
    vkCmdBindDescriptorSets(cbuf, VK_PIPELINE_BIND_POINT_GRAPHICS, g_dsc_pl, 0, 1, &set, 0, NULL); pool_disturb(VK_PIPELINE_BIND_POINT_GRAPHICS);   // its set 0 takes the pool set's place
    VkViewport v = {(float)x0, (float)y0, (float)(x1 - x0), (float)(y1 - y0), 0, 1}; VkRect2D sc = {{x0, y0}, {(uint32_t)(x1 - x0), (uint32_t)(y1 - y0)}};
    vkCmdSetViewport(cbuf, 0, 1, &v); vkCmdSetScissor(cbuf, 0, 1, &sc);
    vkCmdSetStencilWriteMask(cbuf, VK_STENCIL_FACE_FRONT_AND_BACK, dsn ? 0xff : 0); vkCmdSetStencilReference(cbuf, VK_STENCIL_FACE_FRONT_AND_BACK, 0);
    vkCmdPushConstants(cbuf, g_dsc_pl, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof m, &m);
    vkCmdDraw(cbuf, 3, 1, 0, 0);   // export: depth and stencil; bits: the depth, and stencil 0
    if (bits && ss && dsn) for (int b = 0; b < 8; b++) {   // each source bit set: written alone
        m.bit = b; vkCmdPushConstants(cbuf, g_dsc_pl, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof m, &m);
        vkCmdSetStencilWriteMask(cbuf, VK_STENCIL_FACE_FRONT_AND_BACK, 1u << b); vkCmdSetStencilReference(cbuf, VK_STENCIL_FACE_FRONT_AND_BACK, 0xff);
        vkCmdDraw(cbuf, 3, 1, 0, 0);
    }
    vkCmdEndRenderPass(cbuf); cb_barrier(); bf_reset();
    static int nlog; if (nlog++ < 2) LOG("[vk] depth-stencil copy drawn: s%llu %dx%d -> s%llu %dx%d (format %d%s)", (unsigned long long)s->serial, c->sr.width, c->sr.height,
                                        (unsigned long long)d->serial, c->dr.width, c->dr.height, (int)d->fmt, bits ? ", stencil a bit at a time" : "");
    return 1;
}
