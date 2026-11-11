// ---------------- Memory pools backed by a file (DM_VK_POOL_FILEBACK; included by gfx_vk_draw.inc after gfx_vk_gmem.inc) ----------------
// The guest's memory is anonymous: what the game keeps and doesn't touch goes to compressed swap, where it still takes RAM, and Android's lmkd ends the game when swap
// runs low while the device thrashes. Ocarina of Time keeps about 2 GB of texture pools, written once per area load and then read only when a texture is uploaded
// (the replay draws from its own images): BC data, which zram compresses poorly. Backed by a file, a written page goes to flash once and is then a clean page the
// kernel drops first and reads back when wanted, outside swap. BananaNative's "RAM saver" (DM_MEM_FILEBACK_KINDS, MIT) does this and, on a Galaxy S25 Edge, kept
// the game alive through Saria's scene with 1.3 GB less PSS and 1.9 GB less swap (plans/bananative-side-by-side-2026-11-11.md). Written anew here:
// - Which pools (pool_fileback.h fb_kind), at the pool's Initialize (mtl_pool_add, before the dirty tracker protects it): DM_VK_POOL_FILEBACK=texture (any pool of at
//   least DM_VK_POOL_FILEBACK_MB, default 64, not compressible, physical or virtual), shader (shader code), or both (shader,texture). Off by default.
// - The swap: writers held (the range read-only for the window, guest writes and host writes spin in fb_frz_hook / fb_frz_prep), the pages present or in swap and
//   not all zero copied into the file through a second mapping (/proc/self/pagemap), and that mapping moved over the range (mremap). The file is one unlinked file
//   in DM_TEMP (the app's own storage), its blocks reserved first (fallocate) so a full disk fails here instead of a SIGBUS later.
// - A range raw global memory places later is cut out of the file (gm_seg_insert → fb_placed: its blocks punched); a pool's Finalize gives its pieces back to
//   anonymous memory with their bytes and punches them (fb_gone). Whole-guest backing (android/guest-file, q150) wrote about 100 MB/s because the game keeps
//   rewriting its heap; pools written once per area load should cost a load's worth of writes.
#include "pool_fileback.h"   // the rules, checked on the host (dm/tools/tests/test_pool_fileback.py)
#include <sys/syscall.h>
static pthread_mutex_t g_fb_mu = PTHREAD_MUTEX_INITIALIZER;
static int g_fb_fd = -1, g_fb_pm = -1; static uint64_t g_fb_next;   // the file and the next offset in it (never reused); /proc/self/pagemap
static fb_piece *g_fb; static uint32_t g_fb_n, g_fb_cap;   // the file-backed pieces (under g_fb_mu)
static uint64_t g_fb_pools, g_fb_in, g_fb_copied, g_fb_cut, g_fb_back, g_fb_fail, g_fb_io0;   // pools taken, bytes in the file, copied in, punched for placement, given back; failures
static int fb_kinds(void) {
    static int v = -1;
    if (v < 0) { const char *e = getenv("DM_VK_POOL_FILEBACK"); v = 0;
                 if (e && *e && *e != '0') { v = strstr(e, "shader") ? 1 : 0; if (strstr(e, "texture") || !strcmp(e, "1")) v |= 2; if (!strcmp(e, "all")) v = 3; }
                 if (v) LOG("[vk] DM_VK_POOL_FILEBACK=%s: %s%s%s pools backed by a file in DM_TEMP", e, v & 1 ? "shader-code" : "", v == 3 ? " and " : "", v & 2 ? "texture" : ""); }
    return v;
}
static uint64_t fb_min(void) { static uint64_t m; if (!m) { const char *e = getenv("DM_VK_POOL_FILEBACK_MB"); long v = e ? atol(e) : 64; m = (uint64_t)(v > 0 ? v : 64) << 20; } return m; }
static uint64_t fb_io_written(void) {   // /proc/self/io write_bytes: what this process sent to storage
    int fd = open("/proc/self/io", O_RDONLY | O_CLOEXEC); char b[512]; ssize_t n = fd >= 0 ? read(fd, b, sizeof b - 1) : -1; if (fd >= 0) close(fd);
    if (n <= 0) return 0;
    b[n] = 0; const char *w = strstr(b, "\nwrite_bytes:"); return w ? strtoull(w + 13, NULL, 10) : 0;
}
// ---- The freeze window: one at a time (g_fb_mu) ----
static _Atomic uintptr_t g_fbz_lo, g_fbz_hi; static _Atomic uint64_t g_fbz_waits;
static int fb_frz_hook(void *addr, int is_write, void *uc) {   // a signal handler: atomics and sched_yield only
    (void)uc; uintptr_t a = (uintptr_t)addr, hi = atomic_load(&g_fbz_hi);
    if (!is_write || !hi || a < atomic_load(&g_fbz_lo) || a >= hi) return 0;
    atomic_fetch_add(&g_fbz_waits, 1);
    while (atomic_load(&g_fbz_hi) == hi) sched_yield();
    return 1;   // written again on the file's pages (or the anonymous ones, after a failed swap)
}
static void fb_frz_prep(void *addr, size_t len) {
    uintptr_t a = (uintptr_t)addr, hi = atomic_load(&g_fbz_hi);
    if (!hi || a + len <= atomic_load(&g_fbz_lo) || a >= hi) return;
    while (atomic_load(&g_fbz_hi) == hi) sched_yield();
}
static int fb_open(void) {   // under g_fb_mu
    if (g_fb_fd >= 0) return 1;
    const char *d = getenv("DM_TEMP"); if (!d || !*d) d = getenv("TMPDIR"); if (!d || !*d) { LOG("[RED] [vk] pool file backing: no DM_TEMP"); return 0; }
    int fd = open(d, O_TMPFILE | O_RDWR | O_CLOEXEC, 0600);
    if (fd < 0) { char p[512]; snprintf(p, sizeof p, "%s/poolfile_XXXXXX", d); fd = mkostemp(p, O_CLOEXEC); if (fd >= 0) unlink(p); }
    if (fd < 0) { LOG("[RED] [vk] pool file backing: no file in %s (errno %d)", d, errno); return 0; }
    g_fb_fd = fd; g_fb_pm = open("/proc/self/pagemap", O_RDONLY | O_CLOEXEC); g_fb_io0 = fb_io_written();
    dm_fault_hook_register(fb_frz_hook); dm_guest_write_prep_register(fb_frz_prep);
    LOG("[vk] pool file backing: one unlinked file in %s%s", d, g_fb_pm < 0 ? "; /proc/self/pagemap unreadable: every page not all zero is copied" : "");
    return 1;
}
static int fb_zero(const uint8_t *p) { const uint64_t *q = (const uint64_t *)p; for (int i = 0; i < 512; i++) if (q[i]) return 0; return 1; }
static int fb_overlaps_placed(uintptr_t lo, uintptr_t hi) {   // raw global memory holds part of the range
    int r = 0; pthread_mutex_lock(&g_gm_mu);
    for (int i = 0; i < g_ngm && !r; i++) if (g_gm[i].lo < hi && g_gm[i].hi > lo) r = 1;
    pthread_mutex_unlock(&g_gm_mu); return r;
}
// A pool at its Initialize: backed by the file when fb_kind says so (not under g_pool_mu: the copy takes a while)
static void fb_take(const void *mem, uint64_t size, int flags) {
    int kind = fb_kinds() ? fb_kind(flags, size, fb_kinds(), fb_min()) : 0;
    uintptr_t lo = (uintptr_t)mem, hi = lo + size;
    if (!kind || !size || ((lo | size) & 4095) || fb_overlaps_placed(lo, hi)) return;
    pthread_mutex_lock(&g_fb_mu);
    if (!fb_open() || (g_fb_n == g_fb_cap && !(g_fb = realloc(g_fb, (g_fb_cap = g_fb_cap ? 2 * g_fb_cap : 64) * sizeof *g_fb)))) { g_fb_fail++; pthread_mutex_unlock(&g_fb_mu); return; }
    uint64_t off = g_fb_next, t0 = clock_gettime_nsec_np(CLOCK_MONOTONIC), copied = 0, w0 = 0, w1 = 0, held0 = atomic_load(&g_fbz_waits); const char *why = NULL;
    void *f = MAP_FAILED;
    if (fallocate(g_fb_fd, 0, (off_t)off, (off_t)size)) why = "no room for it";
    else if ((f = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, g_fb_fd, (off_t)off)) == MAP_FAILED) why = "no mapping of the file";
    if (!why) {
        atomic_store(&g_fbz_lo, lo); atomic_store(&g_fbz_hi, hi); w0 = clock_gettime_nsec_np(CLOCK_MONOTONIC);
        if (mprotect((void *)lo, size, PROT_READ)) why = "the range not read-only";
        else {
            uint64_t pm[512]; size_t pages = size >> 12;
            for (size_t i = 0; i < pages; i += 512) {
                size_t k = pages - i < 512 ? pages - i : 512; int have = g_fb_pm >= 0 && pread(g_fb_pm, pm, k * 8, (off_t)(((lo >> 12) + i) * 8)) == (ssize_t)(k * 8);
                for (size_t j = 0; j < k; j++) {
                    if (have && !(pm[j] >> 62)) continue;   // never touched: reads 0, a hole in the file
                    const uint8_t *src = (const uint8_t *)(lo + ((i + j) << 12)); if (fb_zero(src)) continue;
                    memcpy((uint8_t *)f + ((i + j) << 12), src, 4096); copied += 4096;
                }
            }
            void *q = (void *)syscall(__NR_mremap, f, size, size, MREMAP_MAYMOVE | MREMAP_FIXED, (void *)lo);
            if (q != (void *)lo) { why = "the move over the range failed"; mprotect((void *)lo, size, PROT_READ | PROT_WRITE); }
            else f = MAP_FAILED;   // it is the range now
        }
        atomic_store(&g_fbz_hi, 0); w1 = clock_gettime_nsec_np(CLOCK_MONOTONIC);
    }
    if (f != MAP_FAILED) munmap(f, size);
    if (why) { fallocate(g_fb_fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, (off_t)off, (off_t)size); g_fb_fail++;
               static int nr; if (nr++ < 8) LOG("[RED] [vk] pool file backing: pool %p (%.0f MiB, flags %#x) stays anonymous: %s (errno %d)", mem, size / 1048576.0, flags, why, errno); }
    else {
        g_fb[g_fb_n++] = (fb_piece){lo, hi, off, mem}; g_fb_next += size; g_fb_pools++; g_fb_in += size; g_fb_copied += copied;
        sync_file_range(g_fb_fd, (off_t)off, (off_t)size, SYNC_FILE_RANGE_WRITE);   // to flash now, not in a burst under pressure
        static int nl; if (nl++ < 16) LOG("[vk] pool file backing: pool %p, %.0f MiB (%s, flags %#x): %.0f MiB of it copied to the file in %.0f ms; writers held for %.0f ms, %llu writes waited", mem, size / 1048576.0,
                                          kind == 1 ? "shader code" : "texture", flags, copied / 1048576.0, (clock_gettime_nsec_np(CLOCK_MONOTONIC) - t0) / 1e6, (w1 - w0) / 1e6,
                                          (unsigned long long)(atomic_load(&g_fbz_waits) - held0));
    }
    pthread_mutex_unlock(&g_fb_mu);
}
static void fb_placed(uintptr_t lo, uintptr_t hi) {   // raw global memory placed [lo, hi) (gm_seg_insert, g_gm_mu held): out of the file
    if (!g_fb_n) return;
    pthread_mutex_lock(&g_fb_mu);
    uint64_t poff[16], plen[16]; uint32_t np = 0;
    if (g_fb_n == g_fb_cap) { fb_piece *p = realloc(g_fb, (g_fb_cap + 64) * sizeof *g_fb); if (p) { g_fb = p; g_fb_cap += 64; } }
    g_fb_n = fb_cut(g_fb, g_fb_n, g_fb_cap, lo, hi, poff, plen, &np, 16);
    for (uint32_t i = 0; i < np; i++) { fallocate(g_fb_fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, (off_t)poff[i], (off_t)plen[i]); g_fb_cut += plen[i]; g_fb_in -= plen[i]; }
    pthread_mutex_unlock(&g_fb_mu);
}
// A pool's Finalize (mtl_pool_del, after gm_unplace): its pieces back to anonymous memory with their bytes, their blocks punched
static void fb_gone(const void *mem) {
    if (!g_fb_n) return;
    pthread_mutex_lock(&g_fb_mu);
    for (uint32_t i = 0; i < g_fb_n;) {
        fb_piece p = g_fb[i]; if (p.pool != mem) { i++; continue; }
        size_t n = p.hi - p.lo; void *a = mmap(NULL, n, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
        if (a == MAP_FAILED) { g_fb_fail++; i++; continue; }   // stays file-backed: its blocks stay too
        atomic_store(&g_fbz_lo, p.lo); atomic_store(&g_fbz_hi, p.hi); mprotect((void *)p.lo, n, PROT_READ);
        for (off_t d = lseek(g_fb_fd, (off_t)p.off, SEEK_DATA); d >= 0 && (uint64_t)d < p.off + n;) {   // only what the file holds: holes read 0 in fresh memory too
            off_t h = lseek(g_fb_fd, d, SEEK_HOLE); uint64_t e = h < 0 || (uint64_t)h > p.off + n ? p.off + n : (uint64_t)h;
            memcpy((uint8_t *)a + (d - (off_t)p.off), (const uint8_t *)(p.lo + (d - (off_t)p.off)), e - (uint64_t)d);
            d = lseek(g_fb_fd, (off_t)e, SEEK_DATA);
        }
        void *q = (void *)syscall(__NR_mremap, a, n, n, MREMAP_MAYMOVE | MREMAP_FIXED, (void *)p.lo);
        if (q != (void *)p.lo) { munmap(a, n); mprotect((void *)p.lo, n, PROT_READ | PROT_WRITE); atomic_store(&g_fbz_hi, 0); g_fb_fail++; i++; continue; }
        atomic_store(&g_fbz_hi, 0);
        fallocate(g_fb_fd, FALLOC_FL_PUNCH_HOLE | FALLOC_FL_KEEP_SIZE, (off_t)p.off, (off_t)n); g_fb_back += n; g_fb_in -= n;
        g_fb[i] = g_fb[--g_fb_n];
    }
    pthread_mutex_unlock(&g_fb_mu);
}
static void fb_stat(void) {   // the periodic line (mtl_mem_stat), when on
    if (!fb_kinds() || g_fb_fd < 0) return;
    struct stat st; uint64_t blocks = fstat(g_fb_fd, &st) ? 0 : (uint64_t)st.st_blocks * 512;
    pthread_mutex_lock(&g_fb_mu); uint32_t n = g_fb_n; uint64_t in = g_fb_in, cp = g_fb_copied, cut = g_fb_cut, back = g_fb_back, fail = g_fb_fail, pools = g_fb_pools; pthread_mutex_unlock(&g_fb_mu);
    LOG("[vk] pool file backing: %llu pools, %u pieces, %.0f MiB backed, %.0f MiB of blocks in the file; %.0f MiB copied in, %.0f MiB cut for placement, %.0f MiB given back; written to storage %.0f MiB since; %llu failures, %llu writes held",
        (unsigned long long)pools, n, in / 1048576.0, blocks / 1048576.0, cp / 1048576.0, cut / 1048576.0, back / 1048576.0, (fb_io_written() - g_fb_io0) / 1048576.0, (unsigned long long)fail,
        (unsigned long long)atomic_load(&g_fbz_waits));
}
