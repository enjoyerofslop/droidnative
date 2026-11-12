// The range index of dirty-page tracking (nvn_dirty.c ix_*): every lookup by address finds exactly the ranges the old walk over every slot found.
// Thousands of pools are laid back to back at 4 KB, so on a 16 KB-page Mac neighbours share their first and last pages and one address falls in several ranges. Every pool is
// protected; then host writes (dm_guest_write_prepare, then the write) and guest writes (a store that faults) at random places must leave dirty exactly the pools whose rounded range
// covers a written page, and the others clean. The expected set comes from the pools' own bounds, not from the code under test. A third of the pools are then removed and new ones
// added at other places (slots reused, the index rebuilt), and the checks run again. A thread adding and removing pools while another writes protected pages checks that replacing the
// index under the fault path neither loses a fault nor frees an index a reader holds. The time of a host pre-write with every pool registered is printed (the walk's cost grew with
// the number of pools: thousands in Ocarina of Time, 98% of the Android replay's completion thread)
#include "../nvn/nvn_dirty.h"
#include "../../host/dm.h"
#include <sys/mman.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

module_t *g_mod;
int g_nmod;
module_t *module_of(const void *p) { (void)p; return NULL; }
void crash_install(void);

static int g_fail;
#define EXPECT(name, want, got) do { \
    long long want_ = (long long)(want), got_ = (long long)(got); \
    printf("%-60s expected %-6lld → got %-6lld %s\n", name, want_, got_, want_ == got_ ? "✓" : "✗"); \
    if (want_ != got_) g_fail++; \
} while (0)

enum { NPOOL = 3000, REGION = 128 << 20 };
typedef struct { uintptr_t mem; size_t size; int live; } pool;
static pool g_p[NPOOL + NPOOL / 3];
static int g_np;
static uint8_t *g_r;
static uintptr_t g_pg;
static uint64_t g_rng = 0x9E3779B97F4A7C15ull;
static uint64_t rnd(void) { g_rng ^= g_rng << 13; g_rng ^= g_rng >> 7; g_rng ^= g_rng << 17; return g_rng; }
static uintptr_t lo_pg(uintptr_t a) { return a & ~(g_pg - 1); }
static uintptr_t hi_pg(uintptr_t a) { return (a + g_pg - 1) & ~(g_pg - 1); }

static void protect_all(void) { for (int i = 0; i < g_np; i++) if (g_p[i].live) nvn_dirty_protect((void *)g_p[i].mem, g_p[i].size); }
// after writes to [w0, w1) (page-rounded unions are the caller's): every live pool dirty iff its rounded range meets a written page. → the pools that differ
static int check(const uintptr_t (*w)[2], int nw, uint64_t stamp, int *ndirty) {
    int bad = 0; *ndirty = 0;
    for (int i = 0; i < g_np; i++) {
        if (!g_p[i].live) continue;
        uintptr_t b = lo_pg(g_p[i].mem), e = hi_pg(g_p[i].mem + g_p[i].size); int want = 0;
        for (int k = 0; k < nw && !want; k++) want = lo_pg(w[k][0]) < e && b < hi_pg(w[k][1]);
        int got = nvn_dirty_since((void *)g_p[i].mem, g_p[i].size, stamp);
        *ndirty += got; if (got != want) { if (bad < 4) printf("  pool %d at %#lx+%#zx: dirty %d, expected %d\n", i, (unsigned long)g_p[i].mem, g_p[i].size, got, want); bad++; }
    }
    return bad;
}
static void round_of_writes(const char *what, int guest) {
    enum { NW = 64 };
    uintptr_t w[NW][2];
    protect_all();
    uint64_t stamp = nvn_dirty_now();
    for (int k = 0; k < NW; k++) {
        uintptr_t a = (uintptr_t)g_r + rnd() % (REGION - (64 << 10)); size_t len = guest ? 1 : 1 + rnd() % (48 << 10);
        w[k][0] = a; w[k][1] = a + len;
        if (guest) *(volatile uint8_t *)a = (uint8_t)k;   // faults into on_fault when the page is protected
        else { dm_guest_write_prepare((void *)a, len); memset((void *)a, k, len); }   // a protected page left read-only here would crash the memset
    }
    int nd, bad = check((const uintptr_t (*)[2])w, NW, stamp, &nd);
    char name[96]; snprintf(name, sizeof name, "%s: pools wrongly clean or dirty (%d dirty)", what, nd);
    EXPECT(name, 0, bad);
}
static void place(int i) {   // pool i at a random 4 KB-aligned place, its size 4 KB to 160 KB, not overlapping a live pool
    for (;;) {
        size_t size = (size_t)(1 + rnd() % 40) << 12; uintptr_t mem = (uintptr_t)g_r + ((rnd() % ((REGION - size) >> 12)) << 12); int ok = 1;
        for (int k = 0; k < g_np && ok; k++) if (g_p[k].live && k != i && g_p[k].mem < mem + size && mem < g_p[k].mem + g_p[k].size) ok = 0;
        if (ok) { g_p[i] = (pool){mem, size, 1}; nvn_dirty_add_range((void *)mem, size); return; }
    }
}

// The race: one thread replaces the index (adds and removes pools in a region of their own) while another writes protected pages of the main region
static _Atomic int g_stop; static uint8_t *g_r2;
static void *churn(void *arg) {
    (void)arg; uint64_t x = 12345; int n = 0;
    while (!atomic_load(&g_stop)) {
        x ^= x << 13; x ^= x >> 7; x ^= x << 17;
        uintptr_t mem = (uintptr_t)g_r2 + ((x % 4096) << 12);
        nvn_dirty_add_range((void *)mem, 4096); nvn_dirty_remove_range((void *)mem); n++;
    }
    return (void *)(intptr_t)n;
}

int main(void) {
    crash_install();
    g_pg = (uintptr_t)getpagesize();
    g_r = mmap(NULL, REGION, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0); g_r2 = mmap(NULL, 4096u << 12, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (g_r == MAP_FAILED || g_r2 == MAP_FAILED) { perror("mmap"); return 2; }
    // back to back from the region's start, 4 KB to 64 KB each: neighbours share host pages where pages are larger than 4 KB
    uintptr_t at = (uintptr_t)g_r;
    for (g_np = 0; g_np < NPOOL; g_np++) { size_t size = (size_t)(1 + rnd() % 16) << 12; g_p[g_np] = (pool){at, size, 1}; nvn_dirty_add_range((void *)at, size); at += size; }
    printf("%d pools back to back over %.1f MB, host pages of %lu KB\n", g_np, (at - (uintptr_t)g_r) / 1048576.0, (unsigned long)(g_pg >> 10));
    for (int r = 0; r < 3; r++) { round_of_writes("host writes", 0); round_of_writes("guest writes (faults)", 1); }

    for (int i = 0; i < g_np; i += 3) { nvn_dirty_remove_range((void *)g_p[i].mem); g_p[i].live = 0; }   // a third removed (slots freed), then new pools at random places
    for (int i = 0; i < g_np; i += 3) place(i);
    for (int k = 0; k < NPOOL / 3; k++) place(g_np++);
    { int live = 0; for (int i = 0; i < g_np; i++) live += g_p[i].live; printf("%d pools after a third were removed and new ones added at random places\n", live); }
    for (int r = 0; r < 3; r++) { round_of_writes("after churn, host writes", 0); round_of_writes("after churn, guest writes (faults)", 1); }

    { protect_all(); uint64_t stamp = nvn_dirty_now(); pthread_t th; pthread_create(&th, NULL, churn, NULL);
      uint64_t writes = 0; struct timespec t0, t1; clock_gettime(CLOCK_MONOTONIC, &t0);
      for (;;) { for (int i = 0; i < g_np; i++) if (g_p[i].live) { *(volatile uint8_t *)(g_p[i].mem + (rnd() % g_p[i].size)) = 1; writes++; }
                 protect_all(); clock_gettime(CLOCK_MONOTONIC, &t1); if (t1.tv_sec - t0.tv_sec >= 2) break; }
      atomic_store(&g_stop, 1); void *n; pthread_join(th, &n);
      int clean = 0; for (int i = 0; i < g_np; i++) if (g_p[i].live && !nvn_dirty_since((void *)g_p[i].mem, g_p[i].size, stamp)) clean++;
      printf("race: %llu guest writes into protected pages while %ld pools were added and removed\n", (unsigned long long)writes, (long)(intptr_t)n);
      EXPECT("race: pools left clean though written", 0, clean); }

    { struct timespec t0, t1; enum { N = 20000 }; clock_gettime(CLOCK_MONOTONIC, &t0);
      for (int k = 0; k < N; k++) dm_guest_write_prepare(g_r + ((rnd() % (REGION >> 12)) << 12), 4096);
      clock_gettime(CLOCK_MONOTONIC, &t1);
      printf("a host pre-write of 4 KB with %d pools registered: %.2f µs\n", g_np, ((t1.tv_sec - t0.tv_sec) * 1e9 + (t1.tv_nsec - t0.tv_nsec)) / N / 1e3); }

    printf(g_fail ? "t_dirty_index: %d FAILED\n" : "t_dirty_index: all passed\n", g_fail);
    return g_fail != 0;
}
