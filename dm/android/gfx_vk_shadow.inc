// ---------------- Shadows left out, a player's choice (DM_VK_SKIP_SHADOWS=1) ----------------
// Included by gfx_vk.c. For a game whose profile names its shadow maps (vk_shadow_rt: <W>x<H>, or square<N> for any square target of N or more), the draws of a pass with no
// colour target and a depth target of that shape are dropped at replay, before any of their work (shaders, pipelines, descriptor sets, the GPU's): the shadows are gone and
// the frame is cheaper. The game's own clears of the map still run, so it holds the value the game clears it to, and every lookup into it reads "nothing in front", whatever
// depth convention the game uses: the scene is lit as if nothing cast a shadow. A tester's patch for Divinity: Original Sin 2 (issue #113) matched every square depth pass of
// 512 or more in any game, colour targets or not, and cleared the map once per dropped draw. Decided once per set of render targets (OP_SET_RT), not per draw.
// DM_VK_SHADOW_RT=<W>x<H> | square<N> names the shape where the profile names none, or another one
static int g_sh_on = -1;   // −1: not looked at yet
static uint32_t g_sh_w, g_sh_h, g_sh_sq;   // the shadow map's size, or (g_sh_sq) the least side of a square one
static int g_sh_rt;   // the render targets set now are a shadow map's
static uint64_t g_sh_skipped, g_sh_sets;   // draws dropped, and the times a shadow map was set as the target
static int shadow_shape(const char *s, uint32_t *w, uint32_t *h, uint32_t *sq) {   // "<W>x<H>" or "square<N>"
    unsigned a, b; char tail;
    if (sscanf(s, "square%u%c", &a, &tail) == 1 && a) { *w = *h = 0; *sq = a; return 1; }
    if (sscanf(s, "%ux%u%c", &a, &b, &tail) == 2 && a && b) { *w = a; *h = b; *sq = 0; return 1; }
    return 0;
}
static void shadow_load(void) {
    const char *e = getenv("DM_VK_SKIP_SHADOWS"), *r = getenv("DM_VK_SHADOW_RT");
    g_sh_on = 0;
    if (!(e && *e == '1')) return;
    if (!shadow_shape(r ? r : DM_GAME_VK_SHADOW_RT, &g_sh_w, &g_sh_h, &g_sh_sq)) {
        LOG("[vk] DM_VK_SKIP_SHADOWS=1: shadows stay, as %s", r ? "DM_VK_SHADOW_RT is not <W>x<H> or square<N>" : "this game's profile names no shadow map (vk_shadow_rt)"); return; }
    g_sh_on = 1;
    LOG("[vk] DM_VK_SKIP_SHADOWS=1: the draws of depth-only passes on %s (%s) are left out: no shadows", r ? r : DM_GAME_VK_SHADOW_RT, r ? "DM_VK_SHADOW_RT" : "the game profile's shadow maps");
}
static int shadow_rt(const p_set_rt *rt) {   // OP_SET_RT, under the replay's lock
    if (g_sh_on < 0) shadow_load();
    if (!g_sh_on || !rt->depth) return 0;
    for (int i = 0; i < rt->n && i < 8; i++) if (rt->color[i]) return 0;
    vtex *v = vt_get(rt->depth); if (!v) return 0;
    uint32_t lv = rt->has_dview && rt->dview.set_levels ? rt->dview.base_level : 0, w = v->w >> lv ? v->w >> lv : 1, h = v->h >> lv ? v->h >> lv : 1;
    if (g_sh_sq ? w != h || w < g_sh_sq : w != g_sh_w || h != g_sh_h) return 0;
    static struct { uint32_t w, h; int f; } seen[4]; static int nseen;   // the first shapes caught, each logged once: a run's log names the game's shadow maps
    int known = 0; for (int i = 0; i < nseen; i++) known |= seen[i].w == w && seen[i].h == h && seen[i].f == (int)v->fmt;
    if (!known && nseen < 4) { seen[nseen].w = w; seen[nseen].h = h; seen[nseen].f = (int)v->fmt; nseen++;
        LOG("[vk] shadow map s%llu (%ux%u vk%d) set as the target: its draws are left out from here on", (unsigned long long)v->serial, w, h, v->fmt); }
    g_sh_sets++;
    return 1;
}
static int shadow_skips(void) { if (!g_sh_rt) return 0; g_sh_skipped++; return 1; }   // OP_DRAW / OP_DRAW_IDX: this draw is dropped
static void shadow_line(void) { if (g_sh_on > 0) LOG("[vk] shadow map draws left out: %llu, in %llu passes (cumulative)", (unsigned long long)g_sh_skipped, (unsigned long long)g_sh_sets); }
