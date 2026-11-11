// ---- Pools placed in chunks as they are used (DM_VK_RAW_GMEM_LAZY) ----
// Placed memory is committed when it is allocated and can't go to swap. Placing whole pools pinned the pages the game never touched: in Ocarina of Time's Kokiri Forest only
// 571 of the 1,967 MiB placed had been resident before, the game's own anonymous memory sat 4.1 GB deep in swap (dumpsys meminfo), and the low-memory killer ended 2 of 11
// runs on a Galaxy Z Fold 8 (PSS about 11.2 GB on 10.8 GB). A pool of GM_LAZY_MIN or more is now placed in chunks of GM_CHUNK, each when it is first used:
// - at the pool's first buffer address, the chunks the game has already written (a page present or swapped out: /proc/self/pagemap);
// - when a storage buffer in a chunk is bound (gm_inplace → gm_lazy_bind), the chunks it covers, as one allocation so that it binds in place;
// - every 200 ms or so at a submission's start (gm_lazy_tick), the chunks the game has written since, and those a binding wanted placed but which a pending
//   write kept back (the swap waits for it there; inside stage_set it may not).
// A chunk nothing has touched holds zeros, and a raw load of an address missing from the table reads 0, so leaving it out changes nothing until someone writes it. What the
// game writes into one later is seen by raw loads from the next scan on. Two gaps remain: raw stores into a chunk nothing has bound or written go nowhere (a GPU-only buffer
// reached only through pointers), and a buffer across a chunk placed earlier and one placed later is copied as before (two allocations).
// A chunk is placed while the game may be writing it, so the swap freezes it: read-only from the copy to the placed map, and a guest write meanwhile waits in gm_frz_hook, a
// host write in gm_frz_prep (a system call writing a read-only page fails rather than faults). This is the design of nx2android's lazy pool backing and its freeze window
// (vk_pool_of, nvn_dirty_freeze), written anew; it backs a chunk at its first GPU use as well, and backs every addressed pool once a shader uses raw memory, where this
// places on first use only, by binding or by the CPU's writes. DM_VK_RAW_GMEM_LAZY=0 (env.txt): whole pools at their first buffer address, as before
typedef struct { uintptr_t lo, hi; const void *pool; uint8_t *st; uint32_t nch; } gm_lz;   // st: each chunk's state (LZ_*)
enum { LZ_NO, LZ_WANT, LZ_PLACED, LZ_REFUSED };
static gm_lz *g_lz; static int g_nlz, g_clz;   // under g_gm_pl
static _Atomic int g_lz_any;
static uint64_t g_lz_pools, g_lz_bind, g_lz_res, g_lz_waited, g_lz_busy, g_lz_scans, g_lz_scan_ns, g_lz_refused, g_lz_cross;
static _Atomic uint64_t g_frz_waits, g_frz_preps;
static int gm_lazy_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_RAW_GMEM_LAZY"); v = !(e && *e == '0'); if (!v) LOG("[vk] DM_VK_RAW_GMEM_LAZY=0: memory pools are placed whole at their first buffer address"); } return v; }

// ---- The freeze window: one at a time (placements hold g_gm_pl) ----
static _Atomic uintptr_t g_frz_lo, g_frz_hi;
static int gm_frz_hook(void *addr, int is_write, void *uc) {   // a signal handler: atomics and sched_yield only
    (void)uc; uintptr_t a = (uintptr_t)addr, hi = atomic_load(&g_frz_hi);
    if (!is_write || !hi || a < atomic_load(&g_frz_lo) || a >= hi) return 0;
    atomic_fetch_add(&g_frz_waits, 1);
    while (atomic_load(&g_frz_hi) == hi) sched_yield();
    return 1;   // written again on the placed map (or on the anonymous pages, a failed swap having made them writable again)
}
static void gm_frz_prep(void *addr, size_t len) {   // the host is about to write guest memory itself
    uintptr_t a = (uintptr_t)addr, hi = atomic_load(&g_frz_hi);
    if (!hi || a + len <= atomic_load(&g_frz_lo) || a >= hi) return;
    atomic_fetch_add(&g_frz_preps, 1);
    while (atomic_load(&g_frz_hi) == hi) sched_yield();
}
static void gm_frz_register(void) { static int done; if (done++ || !gm_lazy_on()) return; dm_fault_hook_register(gm_frz_hook); dm_guest_write_prep_register(gm_frz_prep); }
static int gm_frz_begin(uintptr_t lo, uintptr_t hi) {   // inside nvn_dirty_open: the tracker's pages of the range are writable and its protection held off
    atomic_store(&g_frz_lo, lo); atomic_store(&g_frz_hi, hi);
    if (mprotect((void *)lo, hi - lo, PROT_READ)) { atomic_store(&g_frz_hi, 0); return 0; }
    return 1;
}
static void gm_frz_end(uintptr_t lo, uintptr_t hi) { (void)lo; (void)hi; atomic_store(&g_frz_hi, 0); }

// ---- The chunks (caller holds g_gm_pl) ----
static gm_lz *gm_lz_of(uintptr_t a) { for (int i = 0; i < g_nlz; i++) if (a >= g_lz[i].lo && a < g_lz[i].hi) return &g_lz[i]; return NULL; }
static uintptr_t gm_lz_end(const gm_lz *L, uint32_t c) { uintptr_t e = L->lo + (uintptr_t)(c + 1) * GM_CHUNK; return e < L->hi ? e : L->hi; }
// Whether a page of [a, z) was ever written: present or swapped out, from /proc/self/pagemap's bits 63 and 62 (mincore misses a swapped page, and under this memory pressure
// much of the game's anonymous memory is in zram). A page the game only read maps the zero page and counts too
static int g_pm_fd = -2;
static int gm_lz_touched(uintptr_t a, uintptr_t z) {
    if (g_pm_fd == -2) g_pm_fd = open("/proc/self/pagemap", O_RDONLY | O_CLOEXEC);
    if (g_pm_fd >= 0) {
        uint64_t e[512];
        for (uintptr_t p = a; p < z;) { size_t np = (z - p) >> 12; if (np > 512) np = 512;
            ssize_t r = pread(g_pm_fd, e, np * 8, (off_t)((p >> 12) * 8)); if (r <= 0) break;
            for (size_t i = 0; i < (size_t)r / 8; i++) if (e[i] >> 62) return 1;
            p += ((uintptr_t)r / 8) << 12; }
        return 0; }
    unsigned char v[512]; for (uintptr_t p = a; p < z; p += (uintptr_t)512 << 12) { size_t len = z - p < ((uintptr_t)512 << 12) ? z - p : (size_t)512 << 12;
        if (!mincore((void *)p, len, v)) for (size_t i = 0; i < (len >> 12); i++) if (v[i] & 1) return 1; }
    return 0;
}
static void gm_lz_scan(gm_lz *L) {   // the chunks not placed with a page written: wanted
    uint64_t t0 = gm_now();
    for (uint32_t c = 0; c < L->nch; c++) if (L->st[c] == LZ_NO && gm_lz_touched(L->lo + (uintptr_t)c * GM_CHUNK, gm_lz_end(L, c))) { L->st[c] = LZ_WANT; g_lz_res++; }
    g_lz_scans++; g_lz_scan_ns += gm_now() - t0;
}
// chunks [c, e), all wanted, as one swap. may_wait 0 (inside stage_set): when a pending write overlaps them they stay wanted, -1. → chunks placed
static int gm_lz_run(gm_lz *L, uint32_t c, uint32_t e, int live, int may_wait) {
    uintptr_t a = L->lo + (uintptr_t)c * GM_CHUNK; size_t n = gm_lz_end(L, e - 1) - a; int got = 0;
    if (g_gm_cap && g_gm_bytes + n > g_gm_cap) {
        for (uint32_t k = c; k < e; k++) L->st[k] = LZ_REFUSED; g_lz_refused += e - c; g_gm_capped++;
        RED_ONCE(162, "raw global memory: %.2f GiB placed and DM_VK_RAW_GMEM_MAX is %.2f GiB: chunks from %#lx+%#zx on stay anonymous, raw accesses to them read 0",
                 g_gm_bytes / 1073741824.0, g_gm_cap / 1073741824.0, (unsigned long)a, n);
        return 0; }
    gm_note fail = {0}, probe = {0};
    int r = gm_swap(L->pool, a, n, live, live, may_wait, &fail, &probe);
    if (r < 0) { g_lz_waited++; return -1; }   // wanted still: the next tick waits for the write
    uintptr_t done = a + (uintptr_t)r * (uintptr_t)g_gm_piece; if (done > a + n) done = a + n;
    for (uint32_t k = c; k < e; k++) { int in = gm_lz_end(L, k) <= done; L->st[k] = in ? LZ_PLACED : LZ_REFUSED; if (in) got++; else g_lz_refused++; }
    if (fail.what) gm_note_log(&fail);
    if (probe.what) gm_note_log(&probe);
    return got;
}
static int gm_lz_place(gm_lz *L, int live, int may_wait) {   // every run of wanted chunks. → chunks placed
    int got = 0;
    for (uint32_t c = 0; c < L->nch;) {
        if (L->st[c] != LZ_WANT) { c++; continue; }
        uint32_t e = c; while (e < L->nch && L->st[e] == LZ_WANT) e++;
        int r = gm_lz_run(L, c, e, live, may_wait); if (r > 0) got += r;
        c = e;
    }
    return got;
}
static void gm_lazy_add(const void *pool, uintptr_t lo, size_t size, int live) {   // gm_place, at the pool's first buffer address (or its Initialize)
    for (int i = 0; i < g_nlz; i++) if (g_lz[i].pool == pool) return;
    if (g_nlz == g_clz) { g_clz = g_clz ? 2 * g_clz : 32; g_lz = realloc(g_lz, (size_t)g_clz * sizeof *g_lz); if (!g_lz) die("raw global memory: the chunked pools"); }
    gm_lz *L = &g_lz[g_nlz]; memset(L, 0, sizeof *L);
    L->lo = lo; L->hi = lo + size; L->pool = pool; L->nch = (uint32_t)((size + GM_CHUNK - 1) / GM_CHUNK); L->st = calloc(L->nch, 1);
    if (!L->st) return;
    g_nlz++; g_lz_pools++; atomic_store(&g_lz_any, 1);
    gm_lz_scan(L);
    int got = gm_lz_place(L, live, 1);
    static int nl; if (nl++ < 4) LOG("[vk] raw global memory: memory pool %#lx+%#zx placed in chunks of %u MiB as they are used: %d of %u now (DM_VK_RAW_GMEM_LAZY=0: whole)",
                                     (unsigned long)lo, size, GM_CHUNK >> 20, got, L->nch);
}
static void gm_lazy_drop(const void *pool) {   // gm_unplace, the pool's Finalize (its placed chunks are segments of the pool and given back with them)
    for (int i = 0; i < g_nlz; i++) if (g_lz[i].pool == pool) { free(g_lz[i].st); g_lz[i] = g_lz[--g_nlz]; return; }
}
// the replay's thread, under g_bk, inside stage_set: a storage buffer [addr, addr + n) in no placed piece. → 1 when the chunks holding it were placed now (as one allocation)
static int gm_lazy_bind(uint64_t addr, size_t n) {
    if (!atomic_load(&g_lz_any)) return 0;
    if (pthread_mutex_trylock(&g_gm_pl)) { g_lz_busy++; return 0; }   // (lock order g_gm_pl before g_bk: a game thread placing a pool holds it and may wait for g_bk)
    gm_lz *L = gm_lz_of((uintptr_t)addr); int got = 0;
    if (L && addr + n <= L->hi) {
        uint32_t c0 = (uint32_t)((addr - L->lo) / GM_CHUNK), c1 = (uint32_t)((addr + n - 1 - L->lo) / GM_CHUNK); int ok = 1;
        for (uint32_t k = c0; k <= c1; k++) if (L->st[k] == LZ_PLACED || L->st[k] == LZ_REFUSED) ok = 0;
        if (!ok) g_lz_cross++;   // part of it placed already (an allocation of its own) or refused: copied
        else { for (uint32_t k = c0; k <= c1; k++) L->st[k] = LZ_WANT;
               int r = gm_lz_run(L, c0, c1 + 1, 1, 0); got = r > 0 ? r : 0;   // this run alone now: the pool's other wanted chunks wait for the tick
               g_lz_bind += (uint64_t)got; }
    }
    pthread_mutex_unlock(&g_gm_pl);
    return got > 0;
}
// mtl_sub_begin, the replay's thread under g_bk, between submissions: wanted chunks placed (waiting for pending writes if need be), and every 200 ms the chunks written since
static void gm_lazy_tick(void) {
    if (!atomic_load(&g_lz_any)) return;
    static uint64_t last; uint64_t now = gm_now(); int scan = now - last > 200000000ull;
    if (pthread_mutex_trylock(&g_gm_pl)) { g_lz_busy++; return; }
    for (int i = 0; i < g_nlz; i++) { if (scan) gm_lz_scan(&g_lz[i]); gm_lz_place(&g_lz[i], 1, 1); }
    if (scan) last = now;
    pthread_mutex_unlock(&g_gm_pl);
}
static void gm_lazy_stat(void) {
    if (!g_lz_pools) return;
    uint64_t placed = 0, all = 0; pthread_mutex_lock(&g_gm_pl);
    for (int i = 0; i < g_nlz; i++) for (uint32_t k = 0; k < g_lz[i].nch; k++) { uint64_t len = gm_lz_end(&g_lz[i], k) - (g_lz[i].lo + (uintptr_t)k * GM_CHUNK); all += len; if (g_lz[i].st[k] == LZ_PLACED) placed += len; }
    int n = g_nlz; pthread_mutex_unlock(&g_gm_pl);
    LOG("[vk] raw global memory in chunks: %d pools of %.1f MiB, %.1f MiB of them placed; chunks placed for a binding %llu, wanted for written pages %llu, kept back by a pending write %llu, "
        "refused %llu, bindings across a placed chunk %llu, placements put off (lock busy) %llu; %llu scans (%.2f ms in all); writes that waited for a swap %llu, host writes %llu (cumulative; gfx_vk_gmem_lazy.inc)",
        n, all / 1048576.0, placed / 1048576.0, (unsigned long long)g_lz_bind, (unsigned long long)g_lz_res, (unsigned long long)g_lz_waited, (unsigned long long)g_lz_refused,
        (unsigned long long)g_lz_cross, (unsigned long long)g_lz_busy, (unsigned long long)g_lz_scans, g_lz_scan_ns / 1e6,
        (unsigned long long)atomic_load(&g_frz_waits), (unsigned long long)atomic_load(&g_frz_preps));
}
