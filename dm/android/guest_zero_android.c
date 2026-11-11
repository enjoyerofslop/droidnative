// DM_GUEST_ZERO (a test): the guest heap's resident pages that hold only zeros. Games zero memory they hand out and give back, and those pages stay committed: on a Mac about
// 770 MB of Ocarina of Time's dirty heap read all 0 (docs/reference/memory.md, "Guest files keep the blocks…"). On a phone they are anonymous memory, which lmkd's swap and
// Android 17's per-app limits (memory.swap.max 4 GiB on a Pixel 9 Pro XL) count like any other; zram stores a zero page in nothing, but its swap slot still counts.
// =1 counts them every DM_GUEST_ZERO_SEC (default 30) seconds and logs the total: the size of the win, with no risk. =2 also gives them to the kernel with MADV_FREE, which drops
// such a page only under memory pressure (never swapping it) and keeps it when it is written again first. A write landing between the check and the MADV_FREE would be cleared
// with it, so each page is read again right after and, if it is no longer all 0, written in place (an atomic add of 0) to keep it; a reclaim inside that microsecond would still
// lose the write, so =2 is for measuring, not for play. Only the heap's anonymous, private, writable mappings are scanned (/proc/self/maps): never a pool the dirty tracker holds
// read-only, a placed pool (a device mapping) or the guest's files (DM_GUEST_FILE). Present pages only (/proc/self/pagemap): reading a swapped-out one would swap it in.
// Pages are read through process_vm_readv, which fails where the game unmapped a range since the maps were read instead of faulting this thread
#include "../host/dm.h"
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/uio.h>
#include <unistd.h>

void dm_guest_heap_range(uint64_t *base, size_t *open_len);   // hle_svc.c

static int zero_page(const uint64_t *p, size_t words) { uint64_t o = 0; for (size_t i = 0; i < words && !o; i += 8) o = p[i] | p[i + 1] | p[i + 2] | p[i + 3] | p[i + 4] | p[i + 5] | p[i + 6] | p[i + 7]; return !o; }
static void *zero_thread(void *arg) {
    int drop = (int)(intptr_t)arg; const char *s = getenv("DM_GUEST_ZERO_SEC"); unsigned sec = s && atoi(s) > 0 ? (unsigned)atoi(s) : 30;
    size_t pg = (size_t)getpagesize(), words = pg / 8; int pm = open("/proc/self/pagemap", O_RDONLY | O_CLOEXEC);
    if (pm < 0) { LOG("[RED] [mem] guest zero pages: no /proc/self/pagemap (errno %d): off", errno); return NULL; }
    uint64_t *ent = malloc(512 * sizeof *ent); uint8_t *buf = malloc(512 * pg); struct iovec *rio = malloc(512 * sizeof *rio); uintptr_t *at = malloc(512 * sizeof *at); uint64_t *chk = malloc(pg);
    if (!ent || !buf || !rio || !at || !chk) return NULL;
    pid_t me = getpid();
    const double M = 1048576.0; uint64_t freed_all = 0, kept_all = 0;
    LOG("[mem] guest zero pages: %s every %u s (DM_GUEST_ZERO=%d)", drop ? "counted and given to the kernel (MADV_FREE)" : "counted", sec, drop ? 2 : 1);
    for (;;) {
        sleep(sec);
        uint64_t base; size_t len; dm_guest_heap_range(&base, &len); if (!base || !len) continue;
        struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
        uint64_t present = 0, zeros = 0, freed = 0, kept = 0, vmas = 0;
        FILE *f = fopen("/proc/self/maps", "r"); if (!f) continue;
        char line[512];
        while (fgets(line, sizeof line, f)) {
            unsigned long a, b, ino; char perm[8] = "";
            if (sscanf(line, "%lx-%lx %7s %*s %*s %lu", &a, &b, perm, &ino) != 4) continue;
            if (b <= base || a >= base + len || strcmp(perm, "rw-p") || ino) continue;   // anonymous, private, writable: the heap's own pages
            const char *path = strchr(line, '/'); if (path) continue;   // (a named file mapping)
            uintptr_t lo = a > base ? a : base, hi = b < base + len ? b : base + len; vmas++;
            for (uintptr_t x = lo; x < hi; x += 512 * pg) {
                size_t n = (hi - x) / pg < 512 ? (hi - x) / pg : 512;
                if (pread(pm, ent, n * 8, (off_t)((x / pg) * 8)) != (ssize_t)(n * 8)) break;
                size_t m = 0;
                for (size_t i = 0; i < n; i++) if (ent[i] >> 63 & 1) { at[m] = x + i * pg; rio[m].iov_base = (void *)at[m]; rio[m].iov_len = pg; m++; }   // present (not never-touched, not swapped out)
                if (!m) continue;
                struct iovec lio = {buf, m * pg}; ssize_t got = process_vm_readv(me, &lio, 1, rio, m, 0);
                size_t ok = got > 0 ? (size_t)got / pg : 0; present += ok;
                for (size_t j = 0; j < ok; j++) {
                    if (!zero_page((const uint64_t *)(buf + j * pg), words)) continue;
                    zeros++;
                    if (!drop) continue;
                    uint64_t *p = (uint64_t *)at[j];
                    if (madvise(p, pg, MADV_FREE)) continue;
                    struct iovec l1 = {chk, pg}, r1 = {p, pg};
                    if (process_vm_readv(me, &l1, 1, &r1, 1, 0) == (ssize_t)pg && zero_page(chk, words)) freed++;
                    else { __atomic_fetch_add(&p[0], 0, __ATOMIC_SEQ_CST); kept++; }   // written meanwhile: dirtied again, so the kernel keeps it
                }
            }
        }
        fclose(f);
        clock_gettime(CLOCK_MONOTONIC, &t1); freed_all += freed; kept_all += kept;
        LOG("[mem] guest zero pages: heap %.0f MB open, %.0f MB of it resident in %llu writable mappings, %.0f MB of that all 0%s (%.0f ms to scan)",
            len / M, present * pg / M, (unsigned long long)vmas, zeros * pg / M, drop ? "" : "; not given back (DM_GUEST_ZERO=1)",
            (t1.tv_sec - t0.tv_sec) * 1e3 + (t1.tv_nsec - t0.tv_nsec) / 1e6);
        if (drop) LOG("[mem] guest zero pages: %.0f MB given to the kernel this pass, %.0f MB in all; %llu pages written between the check and the free, kept", freed * pg / M, freed_all * pg / M, (unsigned long long)kept_all);
    }
    return NULL;
}
void dm_android_guest_zero_start(void) {   // front_android.c, before the game starts
    const char *e = getenv("DM_GUEST_ZERO"); int v = e ? atoi(e) : 0; if (v <= 0) return;
    const char *gf = getenv("DM_GUEST_FILE"); if (gf && atoi(gf) > 0) { LOG("[RED] [mem] guest zero pages: off with DM_GUEST_FILE=1 (the heap is file pages, which MADV_FREE does not give back)"); return; }
    pthread_t th; if (!pthread_create(&th, NULL, zero_thread, (void *)(intptr_t)(v >= 2))) pthread_detach(th);
}
