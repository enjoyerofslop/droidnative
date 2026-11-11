// The guest's memory in files on Android (DM_GUEST_FILE=1; hle_svc.c guest_file_init and guest_file_punch call these). The game's heap and alias region are anonymous memory
// otherwise, and Android 17's per-app MemoryLimiter on a Pixel 9 Pro XL (16 GB) killed Ocarina of Time before Kokiri Forest in 3 of 3 runs at 8 GiB resident and 4 GiB of swap
// ("MemoryLimiter:AnonSwap"), its 6.2 GB heap alone about 6.4 GB once touched; 12 GB phones end it under lmkd at 10.4-11.3 GB of total PSS with 4-6 GB of it in zram. Pages of a
// file mapped shared are page cache instead: the kernel writes dirty ones out and drops clean ones rather than swapping them. The cost is the writes: dirty pages go to flash
// after vm.dirty_expire_centisecs whatever the memory state (the 10-s line counts them).
// The files are made in DM_GUEST_FILE_DIR (front_android.c: the app's internal storage, guestmem; external storage is a FUSE mount, where shared writable mappings are slow
// or refused), unnamed (O_TMPFILE) or unlinked at once, sparse, and mapped over the reservation at the same addresses, as on the Mac and iPhone (hle_svc.c guest_files_map)
#include "../host/dm.h"
#include <errno.h>
#include <fcntl.h>
#include <linux/falloc.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <unistd.h>

static int gf_open(const char *dir, int k) {   // a new file of this process's own, nameless where the file system can (f2fs and ext4 can)
    int fd = open(dir, O_TMPFILE | O_RDWR | O_CLOEXEC, 0600);
    if (fd >= 0) return fd;
    char path[1100]; snprintf(path, sizeof path, "%s/guest-%d-%d.mem", dir, (int)getpid(), k);
    for (int i = 0; i < 2; i++) {
        fd = open(path, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (fd >= 0) { if (unlink(path)) { close(fd); return -1; } return fd; }
        if (errno != EEXIST) return -1;
        unlink(path);   // one a dead process with the same number left
    }
    return -1;
}
// n files of chunk bytes (the last one the rest of reserve) mapped PROT_NONE over [as, as + reserve): 1 with their descriptors in fds; 0 with why filled in, every file closed and
// the block anonymous PROT_NONE again, as reserved
int dm_android_guest_files_map(uint8_t *as, size_t reserve, size_t chunk, int n, int *fds, uint64_t min_free, char *why, size_t nwhy) {
    const char *dir = getenv("DM_GUEST_FILE_DIR"); const double G = 1073741824.0; int made = 0, ok = 1;
    if (!dir || !*dir) { snprintf(why, nwhy, "no DM_GUEST_FILE_DIR"); return 0; }
    struct statfs fs;
    if (statfs(dir, &fs)) { snprintf(why, nwhy, "cannot read %s's disk (errno %d)", dir, errno); return 0; }
    if ((double)fs.f_bavail * fs.f_bsize < (double)min_free) { snprintf(why, nwhy, "%.1f GB free in %s, under %.1f", (double)fs.f_bavail * fs.f_bsize / G, dir, min_free / G); return 0; }
    for (int k = 0; ok && k < n; k++) {
        size_t sz = k == n - 1 ? reserve - (size_t)k * chunk : chunk; uint8_t *at = as + (size_t)k * chunk;
        if ((fds[k] = gf_open(dir, k)) < 0) { snprintf(why, nwhy, "cannot make file %d in %s (errno %d)", k, dir, errno); ok = 0; break; }
        made++;
        if (ftruncate(fds[k], (off_t)sz)) { snprintf(why, nwhy, "cannot size file %d to %.2f GB (errno %d)", k, sz / G, errno); ok = 0; }
        else if (mmap(at, sz, PROT_NONE, MAP_SHARED | MAP_FIXED, fds[k], 0) != at) { snprintf(why, nwhy, "cannot map file %d (errno %d)", k, errno); ok = 0; }
    }
    if (ok) return 1;
    for (int k = 0; k < made; k++) close(fds[k]);
    if (mmap(as, reserve, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0) != as) die("reserve guest AS again after DM_GUEST_FILE (errno %d)", errno);
    return 0;
}
// The file's blocks under [off, off + len) given back to the disk; over a mapping that also drops its pages, which read 0 again. → 0, or errno
int dm_android_guest_file_punch(int fd, size_t off, size_t len) { return fallocate(fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, (off_t)off, (off_t)len) ? errno : 0; }

// ---- The watch: the disk's room every second, and every 10 s the alias region's sweep and one line of what the files and the app's memory cost ----
static const int *g_wf; static int g_wn; static uint64_t g_wmin; static void (*g_wsweep)(void); static _Atomic uint64_t *g_wpunched;
static char g_cg[512];   // the app's cgroup v2 folder (/proc/self/cgroup "0::<path>"), "" when none
static uint64_t kv(const char *path, const char *key) {   // "key value" lines (memory.stat, memory.events, /proc/self/io): the value, UINT64_MAX when missing
    FILE *f = fopen(path, "r"); if (!f) return UINT64_MAX;
    char line[256]; size_t kl = strlen(key); uint64_t v = UINT64_MAX;
    while (fgets(line, sizeof line, f)) if (!strncmp(line, key, kl) && (line[kl] == ' ' || line[kl] == ':')) { v = strtoull(line + kl + 1, NULL, 10); break; }
    fclose(f); return v;
}
static uint64_t one(const char *path) { FILE *f = fopen(path, "r"); if (!f) return UINT64_MAX; char b[64] = ""; uint64_t v = UINT64_MAX; if (fgets(b, sizeof b, f)) v = strncmp(b, "max", 3) ? strtoull(b, NULL, 10) : UINT64_MAX - 1; fclose(f); return v; }
static double gb(uint64_t v, double unit) { return v >= UINT64_MAX - 1 ? -1 : (double)v * unit / 1073741824.0; }
static void cg_find(void) {
    FILE *f = fopen("/proc/self/cgroup", "r"); char line[512];
    if (f) { while (fgets(line, sizeof line, f)) if (!strncmp(line, "0::", 3)) { line[strcspn(line, "\n")] = 0; snprintf(g_cg, sizeof g_cg, "/sys/fs/cgroup%s", line + 3); break; } fclose(f); }
}
static void *gf_watch(void *arg) {
    (void)arg; const double G = 1073741824.0; char p[600]; cg_find();
    uint64_t w0 = kv("/proc/self/io", "write_bytes"); struct timespec t0; clock_gettime(CLOCK_MONOTONIC, &t0);
    LOG("[mem] guest file: watching; cgroup %s", g_cg[0] ? g_cg : "(none found)");
    for (unsigned sec = 1;; sec++) {
        sleep(1);
        struct statfs fs; int fs_ok = !fstatfs(g_wf[0], &fs); double avail = fs_ok ? (double)fs.f_bavail * fs.f_bsize : -1;
        snprintf(p, sizeof p, "%s/memory.stat", g_cg); uint64_t dirty = g_cg[0] ? kv(p, "file_dirty") : UINT64_MAX;
        double need = dirty < UINT64_MAX ? (double)dirty : 0;   // what the dirty pages may still take when they are written out
        if (fs_ok && g_wmin && avail - need < (double)g_wmin) {
            LOG("[RED] [mem] guest file: %.1f GB free on its disk, %.1f GB of it still to be taken by dirty pages: under %.1f GB left, stopping the game", avail / G, need / G, g_wmin / G);
            _exit(87);
        }
        if (sec % 10) continue;
        if (g_wsweep) g_wsweep();
        double held = 0; struct stat st; for (int i = 0; i < g_wn; i++) if (!fstat(g_wf[i], &st)) held += (double)st.st_blocks * 512.0;
        uint64_t w = kv("/proc/self/io", "write_bytes"); struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t); double el = (double)(t.tv_sec - t0.tv_sec) + (t.tv_nsec - t0.tv_nsec) / 1e9;
        uint64_t anon = UINT64_MAX, file = UINT64_MAX, wb = UINT64_MAX, high = UINT64_MAX, mx = UINT64_MAX, cur = UINT64_MAX, swc = UINT64_MAX, hi_lim = UINT64_MAX, sw_lim = UINT64_MAX, sw_max = UINT64_MAX, swmaxev = UINT64_MAX;
        if (g_cg[0]) {
            snprintf(p, sizeof p, "%s/memory.stat", g_cg); anon = kv(p, "anon"); file = kv(p, "file"); wb = kv(p, "file_writeback");
            snprintf(p, sizeof p, "%s/memory.events", g_cg); high = kv(p, "high"); mx = kv(p, "max");
            snprintf(p, sizeof p, "%s/memory.current", g_cg); cur = one(p); snprintf(p, sizeof p, "%s/memory.swap.current", g_cg); swc = one(p);
            snprintf(p, sizeof p, "%s/memory.high", g_cg); hi_lim = one(p); snprintf(p, sizeof p, "%s/memory.swap.high", g_cg); sw_lim = one(p);
            snprintf(p, sizeof p, "%s/memory.swap.max", g_cg); sw_max = one(p); snprintf(p, sizeof p, "%s/memory.swap.events", g_cg); swmaxev = kv(p, "max");   // Android 17's cap is swap.max (4 GiB on a Pixel 9 Pro XL)
        }
        uint64_t pss = kv("/proc/self/smaps_rollup", "Pss"), pa = kv("/proc/self/smaps_rollup", "Pss_Anon"), pf = kv("/proc/self/smaps_rollup", "Pss_File"), sp = kv("/proc/self/smaps_rollup", "SwapPss");
        LOG("[mem] guest file: %.2f GB on disk, %.2f GB given back as holes; the process wrote %.2f GB (%.1f MB/s over %.0f s); PSS %.2f GB (anon %.2f, file %.2f, swap %.2f); cgroup: memory %.2f GB "
            "(high %.2f), swap %.2f GB (high %.2f, max %.2f; swap.max events %lld), anon %.2f, file %.2f (dirty %.2f, writeback %.2f), events high %lld max %lld; %.1f GB free on its disk",
            held / G, atomic_load(g_wpunched) / G, gb(w, 1), w0 < UINT64_MAX && w < UINT64_MAX && el > 0 ? (double)(w - w0) / el / 1048576.0 : -1, el, gb(pss, 1024), gb(pa, 1024), gb(pf, 1024), gb(sp, 1024),
            gb(cur, 1), gb(hi_lim, 1), gb(swc, 1), gb(sw_lim, 1), gb(sw_max, 1), swmaxev < UINT64_MAX ? (long long)swmaxev : -1, gb(anon, 1), gb(file, 1), gb(dirty, 1), gb(wb, 1), high < UINT64_MAX ? (long long)high : -1, mx < UINT64_MAX ? (long long)mx : -1, avail / G);
    }
    return NULL;
}
void dm_android_guest_file_watch(const int *fds, int n, uint64_t min_free, void (*sweep)(void), _Atomic uint64_t *punched) {
    g_wf = fds; g_wn = n; g_wmin = min_free; g_wsweep = sweep; g_wpunched = punched;
    pthread_t th; int rc = pthread_create(&th, NULL, gf_watch, NULL);
    if (!rc) pthread_detach(th);
    else LOG("[RED] [mem] guest file: no thread to watch it (error %d): no 10-s line, and nothing stops the game when its disk fills", rc);
}
