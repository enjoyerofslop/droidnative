// ---------------- Images no draw has used for a while, evicted (included by gfx_vk.c after vt_drop_pool) ----------------
// The replay frees a GPU-made texture's image only when another description takes over its storage and no object resolves to it any more (share_take_over), or when
// the game finalizes its memory pool (vt_drop_pool); a packaged one when the game releases its object. On the console texture objects over the same memory are
// descriptors of that memory: aliases cost nothing. Here every description over a storage range is an image of its own, and Ocarina of Time keeps its objects and
// its pools for the whole game, so every scene's render targets stayed: on the Galaxy Z Fold 8 (11.3 GB) the start of its first story scene added 241 targets
// (365 MB) in 20 s, and Android's low-memory killer ended the game at 11 GB, 2.5 to 6 minutes in. Image memory is memory the system cannot page out, unlike the
// game's own. Two kinds go, every EV_EVERY presents, at a present, under g_bk:
// - Clean: an image whose content is still its storage's, so the next lookup makes it again as it was made: a packaged texture (uploaded from guest memory,
//   vt_upload) or a shared one filled from its storage when it was made (tex_init_fill). Nothing on the GPU wrote it since (vt_get_w: a pass's target, a copy's or
//   a clear's destination; an image slot), it was never read through the texture pool by ID (a view dropped from the pool set reads 0 until the sync after a draw
//   reads its ID again: pool_drop_view), and it had no lookup for DM_VK_IMAGE_EVICT_AGE presents (default EV_AGE).
// - Overwritten: a shared image that another shared image over its storage was written as since its last lookup, with no lookup for DM_VK_IMAGE_EVICT_ALIAS_AGE
//   presents (default EV_ALIAS_AGE). On the console that write landed in the same memory, so this image's content is gone there too; its next lookup makes it
//   again as a first one does (filled from its storage where tex_init_fill can, else zero).
// How either goes: as a pool's Finalize does it (vt_drop_pool): its objects stop resolving to it and the sharing table forgets it, so the next lookup goes the way
// a first one does (vt_create, then vt_upload or tex_init_fill); vt_destroy frees it when the chunks that may still use it have completed (dead_add), and g_vt_gen
// tells the draws' caches.
// DM_VK_IMAGE_EVICT=0 (env.txt): images stay until their storage is taken over or their pool goes, as before
#define EV_AGE 1800
#define EV_ALIAS_AGE 120
#define EV_EVERY 30
static int ev_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_IMAGE_EVICT"); v = !(e && *e == '0'); } return v; }
static uint64_t ev_env(const char *name, long def) { const char *e = getenv(name); return (uint64_t)(e && atol(e) > 0 ? atol(e) : def); }
static uint64_t ev_age(void) { static uint64_t a; if (!a) a = ev_env("DM_VK_IMAGE_EVICT_AGE", EV_AGE); return a; }
static uint64_t ev_alias_age(void) { static uint64_t a; if (!a) a = ev_env("DM_VK_IMAGE_EVICT_ALIAS_AGE", EV_ALIAS_AGE); return a; }
static uint64_t g_ev_n[2], g_ev_bytes[2], g_ev_back;   // images evicted and their bytes (clean, overwritten), evicted storage made again (cumulative)
static nvn_hmap g_ev_store = {.klen = 8};   // the storage of evicted images not made again yet: the lookup that makes one again counts it (ev_made)
static void ev_made(vtex *v) { uint64_t k = (uint64_t)(uintptr_t)v->store; if (k && g_ev_store.n && nvn_hm_del(&g_ev_store, &k)) g_ev_back++; }
static int ev_clean(const vtex *v, uint64_t now) {
    return v->img && !v->gpu_w && !v->pool_read && (v->pkg || (v->shared && v->filled)) && now - v->last_present >= ev_age();
}
// The shared images by pool and offset; each pair whose storage overlaps is looked at once (every later entry that starts before this one ends overlaps it)
typedef struct { uint64_t pool; int64_t lo, hi; vtex *v; } ev_ent;
static int ev_cmp(const void *a, const void *b) { const ev_ent *x = a, *y = b; return x->pool != y->pool ? (x->pool < y->pool ? -1 : 1) : x->lo != y->lo ? (x->lo < y->lo ? -1 : 1) : 0; }
static void ev_overwritten(uint64_t now) {
    if (!g_share.n) return;
    ev_ent *e = malloc((size_t)g_share.n * sizeof *e); if (!e) return;
    uint32_t n = 0;
    for (uint32_t i = 0; i < g_share.cap && n < g_share.n; i++) {
        vtex *v = g_share.vals[i]; if (!v) continue;
        share_key k; memcpy(&k, g_share.keys + (size_t)i * g_share.klen, sizeof k);
        nvn_texlayout L; nvn_tex_layout(&k.d, &L); e[n++] = (ev_ent){k.pool, k.off, k.off + (int64_t)(L.size ? L.size : 1), v};
    }
    qsort(e, n, sizeof *e, ev_cmp);
    for (uint32_t i = 0; i < n; i++) for (uint32_t j = i + 1; j < n && e[j].pool == e[i].pool && e[j].lo < e[i].hi; j++) {
        vtex *a = e[i].v, *b = e[j].v;
        if (b->last_w > a->last_present && now - a->last_present >= ev_alias_age() && !a->evict) a->evict = 3;
        if (a->last_w > b->last_present && now - b->last_present >= ev_alias_age() && !b->evict) b->evict = 3;
    }
    free(e);
}
static void vt_evict(void) {   // under g_bk, at a present
    static uint64_t last; uint64_t now = atomic_load(&g_presents);
    if (!ev_on() || now - last < EV_EVERY) return;
    last = now;
    for (uint32_t i = 0; i < g_share.cap; i++) { vtex *v = g_share.vals[i]; if (v && !v->evict && ev_clean(v, now)) v->evict = 1; }
    for (uint32_t i = 0; i < g_tex.cap; i++) { vtex *v = g_tex.vals[i]; if (v && !v->evict && ev_clean(v, now)) v->evict = 1; }
    ev_overwritten(now);
    size_t nt = 0, ns = 0;
    for (uint32_t i = 0; i < g_tex.cap; i++) { vtex *v = g_tex.vals[i]; if (v && v->evict) nt++; }
    for (uint32_t i = 0; i < g_share.cap; i++) { vtex *v = g_share.vals[i]; if (v && v->evict) ns++; }
    if (!nt && !ns) return;
    // the keys first, then the deletions: a deletion moves later entries of its probe chain (nvn_hm_del), so the tables are not walked while they change
    uint64_t *tk = nt ? malloc(nt * sizeof *tk) : NULL; share_key *sk = ns ? malloc(ns * sizeof *sk) : NULL;
    if ((nt && !tk) || (ns && !sk)) { free(tk); free(sk); for (uint32_t i = 0; i < g_tex.cap; i++) if (g_tex.vals[i]) ((vtex *)g_tex.vals[i])->evict = 0;
        for (uint32_t i = 0; i < g_share.cap; i++) if (g_share.vals[i]) ((vtex *)g_share.vals[i])->evict = 0; return; }
    size_t a = 0, b = 0;
    for (uint32_t i = 0; i < g_tex.cap && a < nt; i++) { vtex *v = g_tex.vals[i]; if (v && v->evict) memcpy(&tk[a++], g_tex.keys + (size_t)i * g_tex.klen, 8); }
    for (uint32_t i = 0; i < g_share.cap && b < ns; i++) { vtex *v = g_share.vals[i]; if (v && v->evict) memcpy(&sk[b++], g_share.keys + (size_t)i * g_share.klen, sizeof *sk); }
    #define EV_NOTE(v) do { if ((v)->evict == 1 || (v)->evict == 3) { int c_ = (v)->evict == 3; (v)->evict = 2; g_ev_n[c_]++; g_ev_bytes[c_] += (v)->mem_bytes; \
                                uint64_t k_ = (uint64_t)(uintptr_t)(v)->store; if (k_) nvn_hm_put(&g_ev_store, &k_, (void *)1); } } while (0)
    for (size_t j = 0; j < a; j++) { vtex *v = nvn_hm_del(&g_tex, &tk[j]); if (!v) continue; EV_NOTE(v); g_vt_gen++; vt_unref(v); }   // a packaged one goes with its last object
    for (size_t j = 0; j < b; j++) { vtex *v = nvn_hm_del(&g_share, &sk[j]); if (!v) continue; EV_NOTE(v); v->shared = 0; g_vt_gen++; if (v->refs <= 0) vt_destroy(v); }
    #undef EV_NOTE
    free(tk); free(sk);
}
static void ev_stat(void) {   // the periodic line (mtl_mem_stat)
    LOG("[vk] image memory: %llu images, %.0f MB; evicted clean %llu (%.0f MB, %llu presents without a lookup), overwritten %llu (%.0f MB, %llu presents), %llu of them made again (cumulative; DM_VK_IMAGE_EVICT%s)",
        (unsigned long long)g_im_n, g_im_live / 1048576.0, (unsigned long long)g_ev_n[0], g_ev_bytes[0] / 1048576.0, (unsigned long long)ev_age(), (unsigned long long)g_ev_n[1], g_ev_bytes[1] / 1048576.0,
        (unsigned long long)ev_alias_age(), (unsigned long long)g_ev_back, ev_on() ? "" : "=0: off");
}
