// A frame timeline for the GPU clock question (oot-clock, q262; a test switch, not for the product): when a file named gap_now lies beside $DM_DUMP_DIR, the next
// DM_VK_GAP_FRAMES presents (4) record every event of the pipeline into a ring, with no lock, and the ring is written to the log at the window's end as "[gap]" lines:
// the game thread's submits, presents, acquires and blocking sync waits; the replay's submissions, presents, pacing sleeps, waits for a free chunk and recorder drains; each
// chunk's vkQueueSubmit (the recorder's or the replay's), the completion thread's fence return with the chunk's GPU timestamps, and its retirement. A calibration pair
// (VK_EXT_calibrated_timestamps: the GPU's tick and CLOCK_MONOTONIC at one instant) puts the GPU timestamps on the CPU's clock, so the script (tools/gap.py) sees where
// the GPU idled between chunks and whether the next chunk had been submitted by then. Each event costs one clock read and a ring slot
enum { GAP_MAX = 1 << 16 };
enum { GAP_G_SUBMIT = 1, GAP_G_PRESENT, GAP_G_SYNC0, GAP_G_SYNC1, GAP_G_ACQ, GAP_R_SUB0, GAP_R_SUB1, GAP_R_PRES0, GAP_R_PRES1, GAP_R_PACE, GAP_R_CWAIT0, GAP_R_CWAIT1,
       GAP_R_DRAIN0, GAP_R_DRAIN1, GAP_Q_SUBMIT, GAP_D_FENCE, GAP_D_DONE, GAP_CALIB, GAP_D_WAIT0, GAP_G_FENCE };
typedef struct { uint64_t t; uint32_t kind, tid; uint64_t a, b, c; } gap_ev_t;
static gap_ev_t *g_gap; static _Atomic uint32_t g_gap_n; static _Atomic int g_gap_on;   // g_gap_on: presents left in the window (0: off)
static PFN_vkGetCalibratedTimestampsEXT g_gap_calib;   // VK_EXT_calibrated_timestamps enabled; NULL: the script calibrates from the fence returns
static inline void gap_ev3(int kind, uint64_t a, uint64_t b, uint64_t c) {
    if (!atomic_load_explicit(&g_gap_on, memory_order_relaxed)) return;
    uint32_t i = atomic_fetch_add_explicit(&g_gap_n, 1, memory_order_relaxed);
    if (i < GAP_MAX) g_gap[i] = (gap_ev_t){clock_gettime_nsec_np(CLOCK_MONOTONIC), (uint32_t)kind, (uint32_t)gettid(), a, b, c};
}
static inline void gap_ev(int kind, uint64_t a, uint64_t b) { gap_ev3(kind, a, b, 0); }
void mtl_gap_ev(int kind, uint64_t a, uint64_t b) { gap_ev3(kind, a, b, 0); }   // hle_nvn.c: the game thread's events
static void gap_calib(void) {
    if (!g_gap_calib) return;
    VkCalibratedTimestampInfoEXT inf[2] = {{.sType = VK_STRUCTURE_TYPE_CALIBRATED_TIMESTAMP_INFO_EXT, .timeDomain = VK_TIME_DOMAIN_DEVICE_EXT},
                                           {.sType = VK_STRUCTURE_TYPE_CALIBRATED_TIMESTAMP_INFO_EXT, .timeDomain = VK_TIME_DOMAIN_CLOCK_MONOTONIC_EXT}};
    uint64_t ts[2] = {0, 0}, dev = 0;
    if (g_gap_calib(g_vk.dev, 2, inf, ts, &dev) == VK_SUCCESS) gap_ev3(GAP_CALIB, ts[0], ts[1], dev);
}
static void gap_dump(void) {
    uint32_t n = atomic_load(&g_gap_n); if (n > GAP_MAX) n = GAP_MAX;
    LOG("[gap] window: %u events, timestamp period %.4f ns, calibration %s", n, (double)g_vk.props.limits.timestampPeriod, g_gap_calib ? "VK_EXT_calibrated_timestamps" : "none (from the fence returns)");
    uint64_t t0 = n ? g_gap[0].t : 0;
    for (uint32_t i = 0; i < n; i++) { const gap_ev_t *e = &g_gap[i];
        LOG("[gap] %llu %u %u %llu %llu %llu", (unsigned long long)(e->t - t0), e->kind, e->tid, (unsigned long long)e->a, (unsigned long long)e->b, (unsigned long long)e->c); }
    LOG("[gap] end");
}
static void gap_poll(uint64_t presents) {   // mtl_present, once a present
    int on = atomic_load(&g_gap_on);
    if (on > 0) { if (on == 1) { atomic_store(&g_gap_on, 0); gap_dump(); } else { atomic_store(&g_gap_on, on - 1); gap_calib(); } return; }
    const char *dir = getenv("DM_DUMP_DIR"); if (!dir || presents % 10) return;
    char p[700]; snprintf(p, sizeof p, "%s/../gap_now", dir);
    if (access(p, F_OK)) return;
    int frames = 4; FILE *f = fopen(p, "r"); if (f) { int v = 0; if (fscanf(f, "%d", &v) == 1 && v > 0 && v < 64) frames = v; fclose(f); }
    unlink(p);
    if (!g_gap) g_gap = calloc(GAP_MAX, sizeof *g_gap);
    if (!g_gap) return;
    atomic_store(&g_gap_n, 0); atomic_store(&g_gap_on, frames + 1);
    LOG("[gap] gap_now seen at present %llu: the next %d frames are recorded", (unsigned long long)presents, frames);
    gap_calib();
}
