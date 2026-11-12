// ---- Small layered passes padded past the tile memory (layer_pad_on) ----
// Qualcomm's driver on the Retroid Pocket 5's Adreno 650 (Vulkan 1.1.128, driver 0x802ea000, built 2023-09-27) crashes in vkCreateFramebuffer for a layered
// framebuffer whose attachments fit in its tile memory. OCTOPATH TRAVELER draws its 32x32x32 colour-grading LUT (one A2B10G10R10 target) as 32 layers in its
// first frames, and every start died there: SIGSEGV reading 0x2f100000058 at vulkan.adreno.so+0x170020, in the tiling setup vkCreateFramebuffer runs.
// The game's layered pass just before it, four RGBA16F volumes of the same size, ran. With scratch slots added to the LUT's pass, 32x32x32 framebuffers of 4, 8,
// 12 and 20 bytes a texel (128 to 640 KB) crashed, and of 28 and 36 bytes (896 KB, 1.1 MB) ran, with three attachments or four: the size decides, not the count,
// the format or the 3D target (a real 2D array crashed the same). So on that driver a layered pass under 1 MB gets scratch colour slots after the game's (RGBA32F
// arrays; no fragment shader output reaches them, so their texels are left undefined) until its texels reach 1 MB. One that the 8 slots can't take that far is
// attached as it is (a red line). DM_VK_LAYER_PAD (env.txt): 1 on any GPU, 0 off; by default on Qualcomm's own driver on an Adreno 6xx (device ID 0x06xxxxxx,
// the Adreno 650's 0x6050002). The Moto Razr Plus 2023's Adreno 730, also on a Vulkan 1.1 driver (0x80267062), ran about 330,000 of Xenoblade Chronicles 2's
// layered passes without it, and the Ayn Odin 2's Adreno 740 draws Pokémon Legends: Z-A's 32x32x32 LUT layered
static int layer_pad_on(void) {
    static int v = -1;
    if (v < 0) { const char *e = getenv("DM_VK_LAYER_PAD");
                 v = e ? *e == '1' : g_qcom_driver && (g_vk.props.deviceID >> 24) == 0x06;
                 if (v) LOG("[vk] layered render passes under 1 MB of texels get scratch colour slots past that (DM_VK_LAYER_PAD)"); }
    return v;
}
enum { LPAD_BYTES = 1 << 20, LPAD_TEXEL = 16 };   // what a padded pass's texels reach; an RGBA32F slot's texel
static uint64_t g_layer_pads;   // passes padded (rp_prepare_)
static int lpad_bytes(VkFormat f) { int b = fmt_bytes(f); return b ? b : f == VK_FORMAT_D16_UNORM ? 2 : 4; }   // a texel's size; one not known here taken low (more padding, never less)
// scratch slot j's array, at least w x h x layers (an attachment may be larger than the framebuffer): made again larger when a pass is larger, the old ones kept, as
// cached framebuffers name their views; 4 sizes a slot at most
static vtex *lpad_scratch(int j, uint32_t w, uint32_t h, uint32_t layers) {
    static vtex *sv[8][4]; static int n[8];
    vtex *v = n[j] ? sv[j][n[j] - 1] : NULL;
    if (v && v->w >= w && v->h >= h && v->layers >= layers) return v;
    if (n[j] == 4) return NULL;
    tex_t t; memset(&t, 0, sizeof t); t.magic = MAGIC('T', 'E', 'X', 0); t.serial = ~0x30000ull - (uint64_t)j * 4 - (uint64_t)n[j];
    t.d.target = NVN_TEXTURE_TARGET_2D_ARRAY; t.d.format = NVN_FORMAT_RGBA32F; t.d.levels = 1;
    t.d.width = v && v->w > w ? v->w : w; t.d.height = v && v->h > h ? v->h : h; t.d.depth = v && v->layers > layers ? v->layers : layers;
    if (!(v = vt_create(&t))) return NULL;
    if (fmt_bytes(v->fmt) != LPAD_TEXEL || !(v->usage & VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT)) { vt_destroy(v); return NULL; }
    return sv[j][n[j]++] = v;
}
// the pass of key k, colour views cvw by slot and depth format k->depth, w x h x layers: scratch slots after the game's until its texels reach LPAD_BYTES (all or none)
static void layer_pad(rp_key *k, VkImageView cvw[8], uint32_t w, uint32_t h, uint32_t layers) {
    if (layers <= 1 || !layer_pad_on()) return;
    uint64_t px = (uint64_t)w * h * layers, per = k->depth ? (uint64_t)lpad_bytes(k->depth) : 0;
    for (uint32_t i = 0; i < k->ncolor; i++) if (cvw[i]) per += (uint64_t)lpad_bytes(k->color[i]);
    if (px * per >= LPAD_BYTES) return;
    uint64_t need = (LPAD_BYTES - px * per + px * LPAD_TEXEL - 1) / (px * LPAD_TEXEL);
    if (k->ncolor + need > 8) { RED_ONCE(186, "a layered pass of %ux%u x%u too small to pad past 1 MB of texels: attached as it is (layer_pad_on)", w, h, layers); return; }
    uint32_t n0 = k->ncolor;
    for (uint32_t j = 0; j < need; j++) {
        vtex *s = lpad_scratch((int)j, w, h, layers);
        VkImageView v = s ? view_get(s, VK_IMAGE_VIEW_TYPE_2D_ARRAY, 0, 1, 0, layers, VK_IMAGE_ASPECT_COLOR_BIT, NULL) : VK_NULL_HANDLE;
        if (!v) { for (uint32_t i = n0; i < k->ncolor; i++) { cvw[i] = VK_NULL_HANDLE; k->color[i] = VK_FORMAT_UNDEFINED; } k->ncolor = n0; return; }
        cvw[k->ncolor] = v; k->color[k->ncolor] = s->fmt; k->ncolor++;
    }
    g_layer_pads++;
    static int nlog; if (nlog++ < 4) LOG("[vk] layered pass %ux%u x%u of %llu bytes a texel padded with %llu scratch colour slots (layer_pad_on)", w, h, layers, (unsigned long long)per, (unsigned long long)need);
}
