// ---------------- The GPU clock floor: DM_VK_GPU_FLOOR, the launcher's Keep the GPU clock up (a game setting, off by default) ----------------
// DM_VK_GPU_FLOOR=<pct> (0 or unset = off: no call at all): the device's own KGSL contexts get a power constraint, 100 (the launcher's) the highest clock, 2-99 a floor at that
// share of it where the GMU decides the clock (the highest clock elsewhere). Why: the Adreno's governor sizes the clock to the GPU's busy share, and a replay that keeps the
// GPU waiting for the CPU between chunks never shows it busy enough: Ocarina of Time's Kokiri Forest ran at 460-600 MHz of 1,300 on a Galaxy Z Fold 8 (21 fps), and at 26-29.5
// fps over 15 minutes with the floor, the battery 1 °C warmer against 1.2 °C cooler without it; a Galaxy S25 Edge gained nothing (its governor already ramps there) and ran
// 0.6 °C warmer. So it is the player's choice per game, never a default. The rules (which contexts, which level) are gpu_floor.h's; this file is the kernel's side: the
// process's /dev/kgsl-3d* descriptors (the driver's own, found in /proc/self/fd) and the ioctl. The rule reaches the GMU only while the context is registered with it (after
// its first submission, again after the GPU slept), so it is sent again every 30 presents. Written after BananaNative's vka_dev.c (MIT, Banana Native contributors), which does
// this through VK_QCOM_queue_perf_hint or this ioctl; neither the S25 Edge's nor the Fold 8's driver lists the extension. No root: the constraint is the process's own contexts'.
#include <dirent.h>
#include <sys/ioctl.h>
#include "gpu_floor.h"
struct fl_constraint { unsigned int type, context_id; void *data; size_t size; };     // kgsl_device_constraint
struct fl_prop { unsigned int type; void *value; size_t sizebytes; };                 // kgsl_device_getproperty
#define FL_IOCTL_SETPROPERTY _IOW(0x09, 0x32, struct fl_prop)
enum { FL_PROP_PWR_CONSTRAINT = 0x12 };
static gf_state g_fl;
static int fl_set(int fd, unsigned id, unsigned type, unsigned level) {
    unsigned lv = level; struct fl_constraint c = {type, id, &lv, sizeof lv}; struct fl_prop p = {FL_PROP_PWR_CONSTRAINT, &c, sizeof c};
    int r; do r = ioctl(fd, FL_IOCTL_SETPROPERTY, &p); while (r < 0 && (errno == EINTR || errno == EAGAIN));
    return r < 0 ? -errno : 0;
}
static int fl_fds(int *fd) {   // this process's descriptors on /dev/kgsl-3d*
    int n = 0; DIR *d = opendir("/proc/self/fd"); if (!d) return 0;
    struct dirent *de; char path[64], to[64];
    while ((de = readdir(d)) && n < GF_FDS) {
        int f = atoi(de->d_name); if (f <= 2) continue;
        snprintf(path, sizeof path, "/proc/self/fd/%d", f); ssize_t k = readlink(path, to, sizeof to - 1); if (k <= 0) continue; to[k] = 0;
        if (!strncmp(to, "/dev/kgsl-3d", 12)) fd[n++] = f;
    }
    closedir(d); return n;
}
static void fl_before_device(void) {
    g_fl.pct = gf_pct(getenv("DM_VK_GPU_FLOOR")); if (!g_fl.pct) return;
    int fd[GF_FDS], n = fl_fds(fd); gf_before(&g_fl, fl_set, fd, n);
}
static void fl_device_made(void) {   // the one line a report shows: taken, refused, or no context to constrain
    if (!g_fl.pct) return;
    int fd[GF_FDS], nfd = fl_fds(fd);
    if (!gf_after(&g_fl, fl_set, fd, nfd)) {
        LOG("[vk] GPU clock floor (DM_VK_GPU_FLOOR=%d): %s: no floor", g_fl.pct, nfd ? "no KGSL context of the device's own found" : "no descriptor on /dev/kgsl-3d0 (not Qualcomm's kernel GPU driver)");
        return;
    }
    char b[96]; size_t o = 0; b[0] = 0; for (int k = 0; k < g_fl.n && o < sizeof b; k++) o += (size_t)snprintf(b + o, sizeof b - o, "%s%u", k ? "," : "", g_fl.ctx[k].id);
    const char *kind = g_fl.host ? "the kernel decides the clock: the highest clock only" : "the GMU decides the clock: a floor in % of the highest";
    if (g_fl.last) LOG("[RED] [vk] GPU clock floor (DM_VK_GPU_FLOOR=%d): refused by the kernel (%d) on the device's KGSL context%s %s (%s): the governor keeps the clock", g_fl.pct, g_fl.last, g_fl.n > 1 ? "s" : "", b, kind);
    else LOG("[vk] GPU clock floor (DM_VK_GPU_FLOOR=%d): taken on the device's KGSL context%s %s (%s)", g_fl.pct, g_fl.n > 1 ? "s" : "", b, kind);
}
static void fl_poll(uint64_t presents) { if (g_fl.n && presents % 30 == 0) gf_apply(&g_fl, fl_set); }
static void fl_stats(void) { if (g_fl.n) LOG("[vk] GPU clock floor (DM_VK_GPU_FLOOR=%d): %llu constraints sent, %llu refused (cumulative)", g_fl.pct, (unsigned long long)g_fl.sent, (unsigned long long)g_fl.refused); }
