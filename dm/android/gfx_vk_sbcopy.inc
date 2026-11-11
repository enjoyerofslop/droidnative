// ---- Read-only storage buffers outside placed pools: a chunk's copy bound again while the dirty tracker shows its pages unwritten (DM_VK_SB_DIRTY) ----
// A storage buffer a shader only reads, which sb_keep does not keep (past 8 MB, or written by the game or a write-back every frame) and which no placed pool holds, was copied
// into the arena once per chunk by ucopy, and compared whole with a shadow of that copy at every later bind in the chunk. Mario Kart World binds one 9.56 MB buffer about 370
// times a frame in a race: on a OnePlus Pad 3 (Adreno 830) those compares were 228 of the replay thread's 280 ms a frame (memcmp under ucopy, 81% of the thread), the copies to
// the arena and to the shadow 29 ms more.
// Here the copy is stamped and its pages protected before it is made (sb_reuse.h sbr_stamp), and a later bind in the same chunk takes it again unless a page was written since:
// - The game's writes fault and move the page's generation (nvn_dirty.c). So do the replay's own writes while it records (uniform buffer updates, small copies and fills:
//   mtl_sub_copy, mtl_sub_fill, OP_UPDATE_UB), which fault the same way, and write-backs and linear render targets landing on the completion thread, which go through
//   dm_guest_write_prepare. Any of them before the next bind means a new copy.
// - A dispatch's write still on the GPU is bound there before this is reached (sb_fwd), as before.
// - Memory the tracker does not cover (no pool holds the whole range) is copied and compared as before (ucopy).
// No shadow is kept, so the second memcpy goes too.
// DM_VK_SB_DIRTY=0 (env.txt): compared as before. DM_VK_SB_CHECK=1 (a diagnostic): a shadow is kept as well, each bind the tracker lets through is compared with it, and a
// difference is counted, logged (the first 8) and copied again, so a run shows whether a write got past the tracker.
static const void *sbc_span(const void *a, size_t n) { return nvn_dirty_span(a, n); }
static uint64_t sbc_now(void) { return nvn_dirty_now(); }
static void sbc_protect(const void *a, size_t n) { nvn_dirty_protect(a, n); }
static int sbc_since(const void *s, const void *a, size_t n, uint64_t st) { return nvn_dirty_since_span(s, a, n, st); }
static const sbr_ops g_sbc_ops = {sbc_span, sbc_now, sbc_protect, sbc_since};
static int sbc_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_SB_DIRTY"); v = !(e && *e == '0'); if (!v) LOG("[vk] DM_VK_SB_DIRTY=0: read-only storage buffers outside placed pools are compared at every bind, as before"); } return v; }
static int sbc_check(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_SB_CHECK"); v = e && *e == '1'; if (v) LOG("[vk] DM_VK_SB_CHECK=1: each read-only storage buffer bind the dirty tracker lets through is compared with a shadow too"); } return v; }
static sbr_ent g_sbc[1024]; static uint8_t *g_sbc_shadow[1024]; static size_t g_sbc_cap[1024];
static uint64_t g_sbc_reuse, g_sbc_copy, g_sbc_bytes, g_sbc_written, g_sbc_untracked, g_sbc_checked, g_sbc_differ;
static int sb_copy(const void *src, size_t n, size_t al, VkBuffer *b, VkDeviceSize *off) {
    if (!sbc_on() || !C || !src) return ucopy(src, n, al, b, off);
    sbr_ent *e = sbr_slot(g_sbc, 1023, src, n); size_t i = (size_t)(e - g_sbc); const void *span;
    int r = sbr_look(e, &g_sbc_ops, src, n, C->seq, &span);
    if (r == SBR_UNTRACKED) { g_sbc_untracked++; return ucopy(src, n, al, b, off); }
    if (r == SBR_REUSE && sbc_check() && g_sbc_shadow[i] && g_sbc_cap[i] >= n) {
        g_sbc_checked++;
        if (memcmp(src, g_sbc_shadow[i], n)) {
            size_t k = 0; while (k < n && ((const uint8_t *)src)[k] == g_sbc_shadow[i][k]) k++;
            if (g_sbc_differ++ < 8) LOG("[RED] [vk] DM_VK_SB_CHECK: storage buffer %p (%zu bytes) changed since its copy in chunk %llu with no page written after the stamp: first difference at byte %zu",
                                        src, n, (unsigned long long)C->seq, k);
            r = SBR_WRITTEN;
        }
    }
    if (r == SBR_REUSE) { *b = (VkBuffer)(uintptr_t)e->buf; *off = e->off; g_sbc_reuse++; return 1; }
    if (r == SBR_WRITTEN) g_sbc_written++;
    sbr_stamp(e, &g_sbc_ops, src, n, C->seq, span);
    uint8_t *d = ar_alloc(al, b, off); if (!d) { sbr_forget(e); return 0; }
    memcpy(d, src, n); if (al > n) memset(d + n, 0, al - n);
    sbr_done(e, (uint64_t)(uintptr_t)*b, *off); g_sbc_copy++; g_sbc_bytes += n;
    if (sbc_check()) {
        if (g_sbc_cap[i] < n) { free(g_sbc_shadow[i]); g_sbc_shadow[i] = malloc(n); g_sbc_cap[i] = g_sbc_shadow[i] ? n : 0; }
        if (g_sbc_shadow[i]) memcpy(g_sbc_shadow[i], src, n);   // from the source: the arena may be write-combined, slow to read (ar_mem_type)
    }
    return 1;
}
static void sbc_stat(void) {
    LOG("[vk] read-only storage buffers outside placed pools: %llu binds took their chunk's copy (no page written since), %llu copies made (%llu MB), %llu of them after a write, %llu binds untracked "
        "(compared as before)%s (cumulative; gfx_vk_sbcopy.inc)", (unsigned long long)g_sbc_reuse, (unsigned long long)g_sbc_copy, (unsigned long long)(g_sbc_bytes >> 20), (unsigned long long)g_sbc_written,
        (unsigned long long)g_sbc_untracked, sbc_on() ? "" : "; DM_VK_SB_DIRTY=0");
    if (sbc_check()) LOG("[vk] DM_VK_SB_CHECK: %llu binds compared with the shadow, %llu differed (cumulative)", (unsigned long long)g_sbc_checked, (unsigned long long)g_sbc_differ);
}
