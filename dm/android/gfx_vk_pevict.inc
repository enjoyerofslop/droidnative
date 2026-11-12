// ---------------- Pipelines no draw has bound for a while, destroyed (included by gfx_vk.c after gfx_vk_draw.inc) ----------------
// On Qualcomm's drivers a pipeline whose shader needs private memory holds a fixed 8 MiB of the driver's memory for as long as it exists: on a Moto Razr Plus 2023 (Adreno
// 730, V@0615.98) VK_EXT_device_memory_report shows one of Ocarina of Time's raw-memory compute shaders as 118 KB of code, one block of 8,388,608 bytes and 256 B, the same
// when the pipeline comes from the driver's cache in 8 ms, and nothing of the kind for a compute shader of 200 KB that needs no private memory. The game's start-up list
// makes about 1,500 pipelines at the title, which held 2.2 GB of such memory on an Ayn Odin 2 (Adreno 740, V@0676.32) whatever scene was drawn, and the 98 raw-memory
// pipelines that build once their pointers go through the table (gfx_vk_gmem_noptr.inc) add 0.63 GB more, past what the 12 GB phone had left: the low-memory killer ended
// the game at the Kokiri Forest load in 12 of 12 launches. The title has 3-6 GB to spare and the load none, so what matters is when: a pipeline destroyed by age went
// before the load and was made again in it (the Odin 2, 2026-11-12: killed as before). So here, where MemAvailable (/proc/meminfo) is under PEV_LOW_MIB at a present, the
// PEV_BATCH graphics or compute pipelines least recently bound (none bound in the last PEV_RECENT presents, and only once the chunk that last bound one has completed, its seq
// against g_seq_done) are destroyed, and again at every present while it stays under (MemAvailable is read every PEV_LOOK presents otherwise). An entry stays, marked, so the next draw that needs it makes it again (pipe_get,
// cpipe_get: from the driver's cache, in the background where the draw's pass allows it, as a first one is). The memo of the last draw's pipeline forgets it, and the bind
// filter too. A game turns this on in its android_defaults.txt: DM_VK_PIPE_EVICT_AGE=auto, where raw global memory goes through the table of pointers or the descriptor
// array (the drivers that hold the 8 MiB: Ocarina of Time on the Odin 2) and off elsewhere; =<presents>: a pipeline unused for that many presents goes whatever the memory,
// on any driver; =0 or unset: never. DM_VK_PIPE_EVICT_LOG=1 (env.txt): a line at every sweep that destroys something (the first six come anyway)
#define PEV_AGE 1800
#define PEV_EVERY 60   // the age mode's sweep, in presents
#define PEV_LOW_MIB 2048   // the pressure mode's line: MemAvailable (read every PEV_LOOK presents) under it, the least recently bound pipelines go, PEV_BATCH a sweep, a sweep
#define PEV_BATCH 256      // every present while it lasts (a scene's load takes MemAvailable from 2 GB to the killer's line within seconds on the Odin 2)
#define PEV_LOOK 10
#define PEV_RECENT 120   // a pipeline bound within this many presents stays whatever the pressure
static uint64_t g_pev_n[2], g_pev_sweeps, g_pev_low_sweeps;   // destroyed (graphics, compute), sweeps, sweeps under pressure (cumulative)
static int g_pev_low;   // the last sweep found MemAvailable under the line
static int pev_mode(void) {   // 0 never, 1 by age (DM_VK_PIPE_EVICT_AGE=<presents>), 2 under memory pressure (=auto, where raw memory goes through the table or the array)
    static int m = -1;
    if (m < 0) { const char *e = getenv("DM_VK_PIPE_EVICT_AGE"); m = !e ? 0 : !strcmp(e, "auto") ? (g_gm_np ? 2 : 0) : atol(e) > 0 ? 1 : 0;
        if (m == 1) LOG("[vk] pipelines no draw binds for %ld presents are destroyed, and made again when a draw needs them (DM_VK_PIPE_EVICT_AGE=0: never)", atol(e));
        if (m == 2) LOG("[vk] pipelines are destroyed when the device's MemAvailable falls under %d MiB, the least recently bound first, %d a sweep, and made again when a draw needs them (DM_VK_PIPE_EVICT_AGE=0: never)", PEV_LOW_MIB, PEV_BATCH); }
    return m;
}
static int64_t pev_age(void) { static int64_t a = -1; if (a < 0) { const char *e = getenv("DM_VK_PIPE_EVICT_AGE"); a = e ? atol(e) : 0; if (a <= 0) a = PEV_AGE; } return a; }
static int pev_log(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_PIPE_EVICT_LOG"); v = e && *e == '1'; } return v; }
static uint64_t pev_avail_mib(void) {   // /proc/meminfo's MemAvailable, in MiB (0 when unreadable)
    FILE *f = fopen("/proc/meminfo", "r"); if (!f) return 0;
    char line[128]; uint64_t kb = 0;
    while (fgets(line, sizeof line, f)) if (!strncmp(line, "MemAvailable:", 13)) { kb = strtoull(line + 13, NULL, 10); break; }
    fclose(f); return kb >> 10;
}
typedef struct { uint64_t last; void *e; int kind; } pev_cand;
static int pev_cmp(const void *a, const void *b) { uint64_t x = ((const pev_cand *)a)->last, y = ((const pev_cand *)b)->last; return x < y ? -1 : x > y; }
static void pev_kill(pev_cand *c, uint32_t *live) {
    if (c->kind == 0) { pipe_t *pp = c->e; vkDestroyPipeline(g_vk.dev, pp->p, NULL); vkDestroyPipelineLayout(g_vk.dev, pp->pl, NULL); pp->p = VK_NULL_HANDLE; pp->pl = VK_NULL_HANDLE; pp->ev = 1; }
    else { cpipe_t *cp = c->e; vkDestroyPipeline(g_vk.dev, cp->p, NULL); vkDestroyPipelineLayout(g_vk.dev, cp->pl, NULL); cp->p = VK_NULL_HANDLE; cp->pl = VK_NULL_HANDLE; cp->ev = 1; }
    g_pev_n[c->kind]++; live[c->kind]--;
}
static void pev_sweep(void) {   // mtl_present, under g_bk
    int mode = pev_mode(); if (!mode) return;
    uint64_t now = atomic_load(&g_presents); if (now % (mode == 1 ? PEV_EVERY : g_pev_low ? 1 : PEV_LOOK)) return;
    uint64_t avail = 0, floor = mode == 1 ? (uint64_t)pev_age() : PEV_RECENT;
    if (mode == 2) { avail = pev_avail_mib(); g_pev_low = avail && avail < PEV_LOW_MIB; if (!g_pev_low) return; }
    pthread_mutex_lock(&g_cmu); uint64_t done = g_seq_done; pthread_mutex_unlock(&g_cmu);
    uint64_t n0 = g_pev_n[0], n1 = g_pev_n[1]; uint32_t live[2] = {0, 0};
    static pev_cand *cand; static uint32_t ccap; uint32_t nc = 0;
    if (g_pipes.n + g_cpipes.n > ccap) { ccap = g_pipes.n + g_cpipes.n + 256; cand = realloc(cand, ccap * sizeof *cand); if (!cand) { ccap = 0; return; } }
    for (uint32_t i = 0; i < g_pipes.cap; i++) { pipe_t *pp = g_pipes.vals[i]; if (!pp || !pp->p) continue; live[0]++;   // (one being made has no pipeline yet: APQ_PENDING)
        if (pp->last + floor > now || pp->seq > done) continue; cand[nc++] = (pev_cand){pp->last, pp, 0}; }
    for (uint32_t i = 0; i < g_cpipes.cap; i++) { cpipe_t *cp = g_cpipes.vals[i]; if (!cp || !cp->p) continue; live[1]++;
        if (cp->last + floor > now || cp->seq > done) continue; cand[nc++] = (pev_cand){cp->last, cp, 1}; }
    if (mode == 2) { qsort(cand, nc, sizeof *cand, pev_cmp); if (nc > PEV_BATCH) nc = PEV_BATCH; g_pev_low_sweeps++; }   // the least recently bound first
    for (uint32_t i = 0; i < nc; i++) pev_kill(&cand[i], live);
    g_pev_sweeps++;
    if (g_pev_n[0] == n0 && g_pev_n[1] == n1) return;
    g_pso_m.pp = NULL; bf_reset();   // the memo's pipeline may be gone; a handle the driver gives again is no bind the command buffer holds
    static int said; if (pev_log() || said++ < 6 || (mode == 2 && g_pev_low_sweeps % 10 == 0))
        LOG("[vk] present %llu: %llu graphics and %llu compute pipelines destroyed (%s), %u and %u kept; made again so far %llu and %llu (DM_VK_PIPE_EVICT_AGE)", (unsigned long long)now,
            (unsigned long long)(g_pev_n[0] - n0), (unsigned long long)(g_pev_n[1] - n1), mode == 2 ? "the least recently bound, MemAvailable under the line" : "unused for the age", live[0], live[1],
            (unsigned long long)g_pev_back[0], (unsigned long long)g_pev_back[1]);
    if (mode == 2 && pev_log()) LOG("[vk]   MemAvailable %llu MiB before the sweep", (unsigned long long)avail);
}
static void pev_stat(void) {   // the periodic line (mtl_mem_stat)
    if (!pev_mode()) return;
    uint32_t live[2] = {0, 0};
    for (uint32_t i = 0; i < g_pipes.cap; i++) { const pipe_t *pp = g_pipes.vals[i]; live[0] += pp && pp->p; }
    for (uint32_t i = 0; i < g_cpipes.cap; i++) { const cpipe_t *cp = g_cpipes.vals[i]; live[1] += cp && cp->p; }
    LOG("[vk] pipelines: %u graphics and %u compute live; destroyed %llu and %llu, made again %llu and %llu, in %llu sweeps (%llu under memory pressure; cumulative; DM_VK_PIPE_EVICT_AGE)", live[0], live[1],
        (unsigned long long)g_pev_n[0], (unsigned long long)g_pev_n[1], (unsigned long long)g_pev_back[0], (unsigned long long)g_pev_back[1], (unsigned long long)g_pev_sweeps, (unsigned long long)g_pev_low_sweeps);
}
