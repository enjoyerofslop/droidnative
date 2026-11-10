// ---------------- The pacing grid on the display's vsyncs (VK_GOOGLE_display_timing) ----------------
// Included by gfx_vk.c. The host paces the game on a grid of the present period (mtl_present_pace), and the FIFO swapchain shows each frame at the first vsync whose latch it
// makes, about a refresh before the vsync. With the grid on the host's own clock, where it fell against the vsyncs decided how often a frame's work crossed a latch: 30 fps
// at 60 Hz showed 7 to 190 frames in about 600 a vsync early or late (1 + 3 pairs), from run to run of the same scene (Divinity, Breath of the Wild, OnePlus Pad 3). A schedule
// of present times kept apart from the grid (#131's first version) stopped early frames, but its slots sat after the latch, so for some phases more frames missed it.
// Where a frame spans a whole number k ≥ 2 of refreshes, the grid now starts each frame VS_AFTER past a vsync the swapchain reported (front_vsync), and the frame is given
// the time to be shown: the first vsync at least its period after its start, half a refresh early (vkb_frame.show_at, VkPresentTimesInfoGOOGLE). A frame whose work and
// copy fit its period less one refresh is shown on that vsync whatever the work took, one refresh later than the earliest it could have been; a later one at the next. At one
// refresh FIFO already shows a frame each vsync (a schedule there made frames that came a little late miss theirs: 60 fps at 60 Hz showed 91 of 500 twice), and with no
// whole number the frames fall between vsyncs whatever their times, so neither is touched. A late frame starts the next at once, as before. DM_VK_PRESENT_TIMING=0: as before
#define VS_AFTER 1000000ull   // ns past the vsync a frame's work starts at
uint64_t front_vsync(uint64_t *refresh);   // front_android.c: a vsync the swapchain reported and the refresh period (0 = not known)
static uint64_t g_vs_start;   // where the frame being replayed started its work on the grid (0 = not locked); the replay thread's
static int vs_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_PRESENT_TIMING"); v = g_vk.has_display_timing && !(e && *e == '0'); } return v; }
// A refresh under VS_MIN_R is a variable-rate panel's vsync timeline, not its refresh: the Pixel 9 Pro XL reports 4.17 ms (240 Hz) and shows a frame when it is ready, at
// least 8.33 ms after the last. Locked to that timeline, Divinity's 30 fps there showed 52 frames off-beat in 496 against 46 in 495 without, and 60 fps (4 "refreshes")
// was locked too. Such a panel is left as before
#define VS_MIN_R 8000000ull
static uint64_t vs_k(uint64_t T, uint64_t R) {   // the refreshes a frame spans, when a whole number of 2 or more (else 0)
    if (!R || !T || R < VS_MIN_R) return 0;
    uint64_t k = (T + R / 2) / R, off = T > k * R ? T - k * R : k * R - T;
    return k >= 2 && off <= R / 8 ? k : 0;
}
// mtl_present_pace, before its sleep: next on the grid of vsyncs (the one nearest it), or unchanged; whether it is locked
static int vs_snap(uint64_t *next, uint64_t T) {
    uint64_t R = 0, V = vs_on() ? front_vsync(&R) : 0, k = vs_k(T, R);
    static uint64_t was = ~0ull;
    if (k != was && vs_on() && R) { was = k;
        if (k) LOG("[vk] frames start on the display's vsyncs, %llu refreshes apart (%.3f ms)", (unsigned long long)k, T / 1e6);
        else if (R < VS_MIN_R) LOG("[vk] frames paced on the host's clock: the display reports a vsync every %.3f ms, a variable-rate panel's timeline", R / 1e6);
        else LOG("[vk] frames paced on the host's clock: the period %.3f ms is not 2 or more whole refreshes of %.3f ms", T / 1e6, R / 1e6); }
    if (!k || !V || !*next) return 0;
    int64_t m = (int64_t)llround(((double)(int64_t)(*next - VS_AFTER) - (double)(int64_t)V) / (double)R);
    *next = (uint64_t)((int64_t)V + m * (int64_t)R) + VS_AFTER;
    return 1;
}
// mtl_present, for the frame presented now: when it is to be shown (0 = as soon as drawn)
static uint64_t vs_show_time(uint64_t T) {
    uint64_t R = 0, V = front_vsync(&R);
    if (!g_vs_start || !V || !R || !vs_k(T, R)) return 0;
    uint64_t t = g_vs_start + T, e = t > V ? V + (t - V + R - 1) / R * R : V;   // the first vsync at least the period after the start
    return e - R / 2;
}
