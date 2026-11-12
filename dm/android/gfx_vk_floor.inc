// ---------------- A GPU clock floor through the kernel driver (KGSL): a test switch (oot-clock, q262) ----------------
// DM_VK_GPU_FLOOR=<pct> (env.txt; 0 = off, the default): the device's own KGSL contexts get a power constraint, 100 = the highest clock, 2-99 = a floor at that share of it. The
// Adreno's governor sizes the clock to the GPU's busy share, and a replay that keeps the GPU waiting for the CPU between chunks never shows it busy enough: Ocarina of Time's
// Kokiri Forest ran at 460-600 MHz of 1,300 on a Galaxy Z Fold 8. The kernel lets a file descriptor constrain only the contexts it owns (kgsl_context_get_owner), so the
// contexts are the ones this process's /dev/kgsl-3d0 descriptors own after vkCreateDevice and did not own before; the ownership test is the same ioctl with KGSL_CONSTRAINT_NONE,
// which changes nothing on a context without a constraint. The rule reaches the GMU only while the context is registered with it (after its first submission, again after
// the GPU slept), so it is sent again every 30 presents. On a GPU whose clock the kernel decides (host DCVS, older Adrenos) only the highest clock (level 1) is taken: a
// scaled level answers EINVAL, which the first call finds out. Written after BananaNative's vka_dev.c (MIT, Banana Native contributors), which does this through
// VK_QCOM_queue_perf_hint or this ioctl; neither the Galaxy S25 Edge's nor the Fold 8's driver lists the extension. No root: the constraint is the process's own contexts'.
#include <dirent.h>
#include <sys/ioctl.h>
struct fl_constraint { unsigned int type, context_id; void *data; size_t size; };     // kgsl_device_constraint
struct fl_prop { unsigned int type; void *value; size_t sizebytes; };                 // kgsl_device_getproperty
#define FL_IOCTL_SETPROPERTY _IOW(0x09, 0x32, struct fl_prop)
enum { FL_PROP_PWR_CONSTRAINT = 0x12, FL_CONSTRAINT_NONE = 0, FL_CONSTRAINT_PWRLEVEL = 1, FL_FDS = 4, FL_IDS = 1024, FL_CTX = 8 };
static int g_fl_fd[FL_FDS], g_fl_nfd; static uint8_t g_fl_own[FL_FDS][FL_IDS / 8], g_fl_was[FL_FDS][FL_IDS / 8]; static int g_fl_wasfd[FL_FDS], g_fl_wasn;
static struct { int fd; unsigned id; } g_fl[FL_CTX]; static int g_fl_n, g_fl_host, g_fl_pct = -1; static uint64_t g_fl_sent, g_fl_failed;
static int fl_pct(void) { if (g_fl_pct < 0) { const char *e = getenv("DM_VK_GPU_FLOOR"); int v = e ? atoi(e) : 0; g_fl_pct = v < 0 ? 0 : v > 100 ? 100 : v; } return g_fl_pct; }
static int fl_set(int fd, unsigned id, unsigned type, unsigned level) {
    unsigned lv = level; struct fl_constraint c = {type, id, &lv, sizeof lv}; struct fl_prop p = {FL_PROP_PWR_CONSTRAINT, &c, sizeof c};
    int r; do r = ioctl(fd, FL_IOCTL_SETPROPERTY, &p); while (r < 0 && (errno == EINTR || errno == EAGAIN));
    return r < 0 ? -errno : 0;
}
static void fl_scan(void) {   // this process's descriptors on /dev/kgsl-3d0, and the context ids each owns
    g_fl_nfd = 0; DIR *d = opendir("/proc/self/fd"); if (!d) return;
    struct dirent *de; char path[64], to[64];
    while ((de = readdir(d)) && g_fl_nfd < FL_FDS) {
        int fd = atoi(de->d_name); if (fd <= 2) continue;
        snprintf(path, sizeof path, "/proc/self/fd/%d", fd); ssize_t n = readlink(path, to, sizeof to - 1); if (n <= 0) continue; to[n] = 0;
        if (!strncmp(to, "/dev/kgsl-3d", 12)) g_fl_fd[g_fl_nfd++] = fd;
    }
    closedir(d);
    for (int i = 0; i < g_fl_nfd; i++) { memset(g_fl_own[i], 0, sizeof g_fl_own[i]); for (unsigned id = 1; id < FL_IDS; id++) if (!fl_set(g_fl_fd[i], id, FL_CONSTRAINT_NONE, 0)) g_fl_own[i][id / 8] |= (uint8_t)(1u << (id % 8)); }
}
static void fl_before_device(void) { if (!fl_pct()) return; fl_scan(); g_fl_wasn = g_fl_nfd; memcpy(g_fl_wasfd, g_fl_fd, sizeof g_fl_fd); memcpy(g_fl_was, g_fl_own, sizeof g_fl_own); }
static int fl_apply(void) {   // the floor on the device's contexts; 0 = every call taken
    int pct = fl_pct(), bad = 0;
    for (int k = 0; k < g_fl_n; k++) { int r = fl_set(g_fl[k].fd, g_fl[k].id, FL_CONSTRAINT_PWRLEVEL, pct >= 100 || g_fl_host ? 1u : (unsigned)(pct < 2 ? 2 : pct)); if (r) { bad = r; g_fl_failed++; } else g_fl_sent++; }
    return bad;
}
static void fl_device_made(void) {
    if (!fl_pct()) return;
    fl_scan(); g_fl_n = 0;
    for (int i = 0; i < g_fl_nfd; i++) {
        int w = -1; for (int j = 0; j < g_fl_wasn; j++) if (g_fl_wasfd[j] == g_fl_fd[i]) w = j;
        for (unsigned id = 1; id < FL_IDS && g_fl_n < FL_CTX; id++)
            if ((g_fl_own[i][id / 8] >> (id % 8) & 1) && !(w >= 0 && (g_fl_was[w][id / 8] >> (id % 8) & 1))) { g_fl[g_fl_n].fd = g_fl_fd[i]; g_fl[g_fl_n].id = id; g_fl_n++; }
    }
    if (!g_fl_n) { LOG("[vk] DM_VK_GPU_FLOOR=%d: no KGSL context of the device's own found (%d descriptor%s on /dev/kgsl-3d0): no floor", fl_pct(), g_fl_nfd, g_fl_nfd == 1 ? "" : "s"); return; }
    int r = fl_set(g_fl[0].fd, g_fl[0].id, FL_CONSTRAINT_PWRLEVEL, 50); g_fl_host = r == -EINVAL; fl_set(g_fl[0].fd, g_fl[0].id, FL_CONSTRAINT_NONE, 0);   // the level form the kernel takes
    char b[96]; size_t o = 0; b[0] = 0; for (int k = 0; k < g_fl_n && o < sizeof b; k++) o += (size_t)snprintf(b + o, sizeof b - o, "%s%u", k ? "," : "", g_fl[k].id);
    int a = fl_apply();
    LOG("[vk] DM_VK_GPU_FLOOR=%d: a KGSL power constraint on the device's context%s %s (%d descriptor%s on /dev/kgsl-3d0; %s; a scaled level answered %d): %s", fl_pct(), g_fl_n > 1 ? "s" : "", b, g_fl_nfd, g_fl_nfd == 1 ? "" : "s",
        g_fl_host ? "host DCVS: the highest clock only" : "GMU DCVS: a floor in % of the highest clock", r, a ? "refused" : "taken");
    if (a) LOG("[RED] [vk] DM_VK_GPU_FLOOR: the kernel refused the constraint: %d", a);
}
static void fl_poll(uint64_t presents) { if (g_fl_n && presents % 30 == 0) fl_apply(); }   // sent again: the GMU holds a context's rule only while the context is registered
static void fl_stats(void) { if (g_fl_n) LOG("[vk] GPU clock floor (KGSL, DM_VK_GPU_FLOOR=%d): %llu constraints sent, %llu refused (cumulative)", fl_pct(), (unsigned long long)g_fl_sent, (unsigned long long)g_fl_failed); }
