// Included by gfx_vk.c before gfx_vk_draw.inc (pipe_make). Vertex shaders whose position reads its constant buffer rows at run time (tools/spv_android.py pos_rows):
// the post-pass writes each such read's row as row + (on ? min(gl_InstanceIndex, 0) : 0), `on` a specialization constant (POS_ROWS_SPEC_ID) that is false unless
// the pipeline sets it. Qualcomm's Adreno 7xx driver (V@0676.32 on the Ayn Odin 2) bins a pass with a position-only copy of each vertex shader that has other
// outputs, and that copy read the clip matrix of Final Fantasy Resonance's flames (c3 rows 0-3, constant indices the driver loads ahead into constant registers)
// as garbage: the cards were binned nowhere. Read at a run-time row they come out right. Run-time rows cost GPU time, though (on in every vertex shader, Animal
// Crossing's island took 25% more on the Odin 2, Skyward Sword HD's Skyloft 10%), and no test yet tells which shaders the driver breaks, so they are on only
// for the vertex shaders a game's profile names (vk_pos_rows), and only on Qualcomm's own driver for an Adreno 7xx (Turnip names the GPU otherwise; the
// Adreno 6xx and 8xx are left alone). DM_VK_POS_ROWS=1 (env.txt) turns them on for every vertex shader on any GPU, to look for other draws the driver loses;
// =0 for none
#define POS_ROWS_SPEC_ID 7401   // spv_android.py POS_ROWS_SPEC
static int g_pr_mode = -1;   // 0: none, 1: the profile's vertex shaders, 2: every vertex shader
static const char g_pr_keys[] = DM_GAME_VK_POS_ROWS;   // the profile's vertex shaders, keys joined by commas
static void pos_rows_init(void) {
    if (g_pr_mode >= 0) return;
    const char *e = getenv("DM_VK_POS_ROWS");
    int q7 = g_vk.props.vendorID == 0x5143 && !strncmp(g_vk.props.deviceName, "Adreno (TM) 7", 13);
    g_pr_mode = e && *e == '0' ? 0 : e && *e == '1' ? 2 : q7 && g_pr_keys[0] != 0 ? 1 : 0;
    if (g_pr_mode == 2) LOG("[vk] DM_VK_POS_ROWS=1: every vertex shader's position reads its constant buffer rows at run time");
    else if (g_pr_mode) LOG("[vk] %s: the position of vertex shaders %s reads its constant buffer rows at run time (vk_pos_rows)", g_vk.props.deviceName, g_pr_keys);
}
static int pos_rows_for(const char *key) {   // key: the shader's 16 hex digits (not terminated)
    pos_rows_init();
    if (g_pr_mode != 1) return g_pr_mode == 2;
    for (const char *p = g_pr_keys; p && *p; p = strchr(p, ',') ? strchr(p, ',') + 1 : NULL)
        if (!strncmp(p, key, 16) && (p[16] == ',' || !p[16])) return 1;
    return 0;
}
static const VkSpecializationMapEntry g_pr_entry = {POS_ROWS_SPEC_ID, 0, sizeof(VkBool32)};
static const VkBool32 g_pr_on = VK_TRUE;
static const VkSpecializationInfo g_pr_spec = {1, &g_pr_entry, sizeof g_pr_on, &g_pr_on};
