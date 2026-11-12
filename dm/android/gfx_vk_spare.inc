// ---------------- A freed image's memory kept as a spare (DM_VK_IMAGE_SPARE; included by gfx_vk.c after im_out) ----------------
// Every image here has its own vkAllocateMemory (vt_create), and a game that makes its render targets again keeps paying for it: Ocarina of Time moves its targets
// within one pool every frame, so about one image over 2 MB is made again each present, and vkAllocateMemory took 1.7 ms each on an Ayn Odin 3 (nx2android's
// e3b16fdf). With the frame bound by the replay's CPU, that is frame time. So a freed image's memory goes to a spare list once the chunks that may still use it
// have completed (dead kind 7, on the completion thread), and a new image takes the smallest spare of a memory type it allows that holds it with at most a quarter
// to spare (img_spare.h spare_pick), else allocates. A spare has one image at a time: nothing is aliased. vt_clear_new clears a reused spare as it does a new one.
// Spares unused for SPARE_AGE presents go at the next present, and the oldest while the list is over DM_VK_IMAGE_SPARE_MB (default 256). DM_VK_IMAGE_SPARE=0: freed as
// before. The periodic memory line gives image allocations and their time, and the spares taken, kept and let go. nx2android's e3b16fdf's idea, written anew
#include "img_spare.h"   // the rules, checked on the host (dm/tools/tests/test_img_spare.py)
#define SPARE_AGE 120
#define SPARE_MIN (256u << 10)
struct spare_mem { VkDeviceMemory mem; uint64_t size, freed_present; uint32_t type; };   // (typedef at chunk_done)
static pthread_mutex_t g_spare_mu = PTHREAD_MUTEX_INITIALIZER;   // the list: pushed on the completion thread, taken and swept under g_bk
static spare_mem **g_spare; static uint32_t g_spare_n, g_spare_cap; static uint64_t g_spare_bytes, g_spare_taken, g_spare_taken_bytes, g_spare_expired;   // (under g_spare_mu)
static uint64_t g_ia_n, g_ia_ns;   // images' vkAllocateMemory calls and their time (under g_bk)
static int spare_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_IMAGE_SPARE"); v = !(e && *e == '0'); } return v; }
static uint64_t spare_cap(void) { static uint64_t c; if (!c) { const char *e = getenv("DM_VK_IMAGE_SPARE_MB"); long m = e ? atol(e) : 256; c = (uint64_t)(m > 0 ? m : 256) << 20; } return c; }
// An image's memory: a spare that fits, else vkAllocateMemory (timed). The memory, its size and type through the pointers; VK_NULL_HANDLE when none could be had
static VkDeviceMemory img_mem(const VkMemoryRequirements *mr, uint64_t *size, uint32_t *type) {
    if (spare_on() && mr->size >= SPARE_MIN) {
        pthread_mutex_lock(&g_spare_mu);
        uint64_t sz[64]; uint32_t ty[64]; uint32_t n = 0; int pick = -1;
        for (uint32_t base = 0; base < g_spare_n; base += n) {   // in blocks of 64 (no array on the stack grows with the list), the smallest fit of all
            n = g_spare_n - base < 64 ? g_spare_n - base : 64;
            for (uint32_t i = 0; i < n; i++) { sz[i] = g_spare[base + i]->size; ty[i] = g_spare[base + i]->type; }
            int p = spare_pick(sz, ty, n, mr->size, mr->memoryTypeBits);
            if (p >= 0 && (pick < 0 || g_spare[base + p]->size < g_spare[pick]->size)) pick = (int)base + p;
        }
        spare_mem *s = pick >= 0 ? g_spare[pick] : NULL;
        if (s) { g_spare[pick] = g_spare[--g_spare_n]; g_spare_bytes -= s->size; g_spare_taken++; g_spare_taken_bytes += s->size; }
        pthread_mutex_unlock(&g_spare_mu);
        if (s) { VkDeviceMemory m = s->mem; *size = s->size; *type = s->type; free(s); return m; }
    }
    uint32_t mt = vkb_mem_type(mr->memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT); if (mt == UINT32_MAX) mt = vkb_mem_type(mr->memoryTypeBits, 0);
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = mr->size, .memoryTypeIndex = mt};
    VkDeviceMemory m = VK_NULL_HANDLE; uint64_t t0 = clock_gettime_nsec_np(CLOCK_MONOTONIC);
    VkResult r = vkAllocateMemory(g_vk.dev, &ma, NULL, &m);
    g_ia_n++; g_ia_ns += clock_gettime_nsec_np(CLOCK_MONOTONIC) - t0;
    if (r != VK_SUCCESS) return VK_NULL_HANDLE;
    *size = mr->size; *type = mt; return m;
}
static void spare_put(spare_mem *s) {   // dead kind 7, on the completion thread: nothing uses the memory any more
    if (!s) return;
    pthread_mutex_lock(&g_spare_mu);
    if (g_spare_n == g_spare_cap) { uint32_t c = g_spare_cap ? 2 * g_spare_cap : 64; spare_mem **a = realloc(g_spare, c * sizeof *a); if (!a) { pthread_mutex_unlock(&g_spare_mu); vkFreeMemory(g_vk.dev, s->mem, NULL); free(s); return; } g_spare = a; g_spare_cap = c; }
    g_spare[g_spare_n++] = s; g_spare_bytes += s->size;
    pthread_mutex_unlock(&g_spare_mu);
}
// The image's memory goes (vt_destroy, vt_storage_up) when the chunks that may use it complete: to the spare list, or freed
static void vt_mem_drop(vtex *v) {
    spare_mem *s = spare_on() && v->mem && v->mem_bytes >= SPARE_MIN && v->mem_type < 32 ? malloc(sizeof *s) : NULL;
    if (s) { *s = (spare_mem){v->mem, v->mem_bytes, atomic_load(&g_presents), v->mem_type}; dead_add(7, (uint64_t)(uintptr_t)s); }
    else dead_add(4, (uint64_t)v->mem);
    im_out(v);
}
static void spare_sweep(uint64_t now) {   // under g_bk, at a present: spares unused for SPARE_AGE presents, then the oldest while over the cap
    if (!g_spare_n) return;
    pthread_mutex_lock(&g_spare_mu);
    for (uint32_t i = 0; i < g_spare_n;) {
        if (!spare_expired(g_spare[i]->freed_present, now, SPARE_AGE)) { i++; continue; }
        spare_mem *s = g_spare[i]; g_spare[i] = g_spare[--g_spare_n]; g_spare_bytes -= s->size; g_spare_expired++; vkFreeMemory(g_vk.dev, s->mem, NULL); free(s);
    }
    while (g_spare_bytes > spare_cap() && g_spare_n) {
        uint32_t o = 0; for (uint32_t i = 1; i < g_spare_n; i++) if (g_spare[i]->freed_present < g_spare[o]->freed_present) o = i;
        spare_mem *s = g_spare[o]; g_spare[o] = g_spare[--g_spare_n]; g_spare_bytes -= s->size; g_spare_expired++; vkFreeMemory(g_vk.dev, s->mem, NULL); free(s);
    }
    pthread_mutex_unlock(&g_spare_mu);
}
static void spare_stat(void) {   // the periodic line (mtl_mem_stat)
    pthread_mutex_lock(&g_spare_mu); uint32_t n = g_spare_n; uint64_t b = g_spare_bytes, tk = g_spare_taken, tb = g_spare_taken_bytes, ex = g_spare_expired; pthread_mutex_unlock(&g_spare_mu);
    LOG("[vk] image allocations: %llu, %.1f ms in all (%.2f ms each); spares taken %llu (%.0f MB), kept %u (%.0f MB), let go %llu (cumulative; DM_VK_IMAGE_SPARE%s)", (unsigned long long)g_ia_n,
        g_ia_ns / 1e6, g_ia_n ? g_ia_ns / 1e6 / g_ia_n : 0.0, (unsigned long long)tk, tb / 1048576.0, n, b / 1048576.0, (unsigned long long)ex, spare_on() ? "" : "=0: off");
}
