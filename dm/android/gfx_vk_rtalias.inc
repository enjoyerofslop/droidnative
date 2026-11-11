// ---------------- Render targets over one storage start share one allocation (DM_VK_RTALIAS; included by gfx_vk.c after im_out) ----------------
// On the console a texture is a description of memory: a game that makes a target again at another size over the same memory costs nothing. Here each description is
// an image with its own vkAllocateMemory (vt_create), and the old ones stay until their storage is taken over or #244's eviction finds them overwritten: Ocarina of
// Time's Saria scene held 1.5 GB of shared images over 0.7 GB of storage (q138). With DM_VK_RTALIAS=1 a render target the GPU gives its content is bound at offset 0
// of its key's allocation (rt_alias.h: the storage start and the description without its extent), made half again as large when a bigger one comes. An image that
// joins an allocation others hold is not cleared, only taken from UNDEFINED: its content is undefined, as the Switch's bytes read in its shape would be.
// - Off by default on every driver: BananaNative found Qualcomm's driver (Adreno 740) hung when several large images shared one zeroed allocation, and nothing here
//   has been run on Turnip, Mali or Xclipse yet. 1: colour targets; 2: depth and stencil targets too.
// - An allocation counts once in the image memory (g_im_live); the images on it count as images. vt_destroy drops its hold when the chunks that may use the image
//   complete (dead kind 6, on the completion thread: only the count); ra_sweep, under g_bk at each eviction scan, frees an allocation nobody holds once it is no
//   longer its key's, or after RA_SPARE presents unused (a target made again every present finds its memory still there), and a pool's Finalize retires its keys.
// The ideas of Anka Native's DM_VK_RTALIAS (vka_rtalias.h, MIT) and nx2android's e3b16fdf (a freed image keeps its memory as a spare), written anew for this replay
#include "rt_alias.h"   // the rules, checked on the host (dm/tools/tests/test_rt_alias.py)
#define RA_MIN_BYTES (256u << 10)
#define RA_SPARE 30
struct ralloc { VkDeviceMemory mem; uint64_t size, last_present; uint32_t type; _Atomic int refs; int current; ra_key key; struct ralloc *next; };   // (typedef at chunk_done)
static nvn_hmap g_ra = {.klen = sizeof(ra_key)};   // a key's current allocation (under g_bk)
static ralloc *g_ra_all;   // every allocation alive, current or not (under g_bk)
static uint64_t g_ra_joined, g_ra_join_bytes, g_ra_made, g_ra_grown;   // images that joined an allocation and the bytes they did not allocate, allocations made, of them grown (cumulative)
static int ra_mode(void) {
    static int v = -1;
    if (v < 0) { const char *e = getenv("DM_VK_RTALIAS"); v = e ? atoi(e) : 0; if (v < 0 || v > 2) v = 0;
                 if (v) LOG("[vk] DM_VK_RTALIAS=%d: render targets over one storage start share one allocation (%s)%s", v, v >= 2 ? "colour, depth and stencil" : "colour",
                            g_qcom_driver ? "; Qualcomm's driver hung with shared allocations in BananaNative's tests, watch for a device lost" : ""); }
    return v;
}
// Binds a new image to its key's allocation instead of one of its own. 0: not eligible or no memory (the caller allocates as before); 1: joined an allocation others
// hold (the caller does not clear it); 2: a new allocation (cleared as before). Under g_bk
static int ra_bind(vtex *v, const tex_t *t, const VkMemoryRequirements *mr, VkImageUsageFlags u) {
    int target = (u & (VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | VK_IMAGE_USAGE_DEPTH_STENCIL_ATTACHMENT_BIT)) != 0;
    if (!ra_eligible(ra_mode(), t->pool != NULL, is_packaged(t), v->conv != CONV_NONE, target, v->aspect == VK_IMAGE_ASPECT_COLOR_BIT, mr->size, RA_MIN_BYTES)) return 0;
    ra_key k = ra_key_of((uint64_t)(uintptr_t)t->pool, t->off, &t->d, NVN_TEXTURE_FLAGS_IMAGE);
    ralloc *a = nvn_hm_get(&g_ra, &k); uint64_t now = atomic_load(&g_presents);
    if (a && a->size >= mr->size && (mr->memoryTypeBits & (1u << a->type))) {
        if (vkBindImageMemory(g_vk.dev, v->img, a->mem, 0) != VK_SUCCESS) return 0;
        atomic_fetch_add(&a->refs, 1); a->last_present = now; v->mem = a->mem; v->ra = a; v->mem_bytes = 0; g_im_n++;
        g_ra_joined++; g_ra_join_bytes += mr->size;
        return 1;
    }
    uint64_t size = ra_grow(a ? a->size : 0, mr->size);
    uint32_t mt = vkb_mem_type(mr->memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT); if (mt == UINT32_MAX) mt = vkb_mem_type(mr->memoryTypeBits, 0);
    ralloc *n = calloc(1, sizeof *n); if (!n || mt == UINT32_MAX) { free(n); return 0; }
    VkMemoryAllocateInfo ma = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = size, .memoryTypeIndex = mt};
    if (vkAllocateMemory(g_vk.dev, &ma, NULL, &n->mem) != VK_SUCCESS) { free(n); return 0; }
    if (vkBindImageMemory(g_vk.dev, v->img, n->mem, 0) != VK_SUCCESS) { vkFreeMemory(g_vk.dev, n->mem, NULL); free(n); return 0; }
    n->size = size; n->type = mt; n->key = k; n->current = 1; n->last_present = now; atomic_store(&n->refs, 1); n->next = g_ra_all; g_ra_all = n;
    if (a) { a->current = 0; g_ra_grown++; }   // the old one goes once the images on it do (ra_sweep)
    nvn_hm_put(&g_ra, &k, n);
    v->mem = n->mem; v->ra = n; v->mem_bytes = 0; g_im_n++; g_im_live += size; g_ra_made++;
    return 2;
}
static void ra_release(ralloc *a) { if (a) atomic_fetch_sub(&a->refs, 1); }   // dead kind 6, on the completion thread
// The image's memory goes (vt_destroy, vt_storage_up): its own when the chunks complete, or its hold on its key's allocation
static void vt_mem_drop(vtex *v) {
    if (v->ra) { dead_add(6, (uint64_t)(uintptr_t)v->ra); im_out(v); v->ra = NULL; }
    else { dead_add(4, (uint64_t)v->mem); im_out(v); }
}
static void ra_sweep(uint64_t now) {   // under g_bk, at a present
    for (ralloc **pp = &g_ra_all; *pp;) {
        ralloc *a = *pp;
        if (atomic_load(&a->refs) > 0 || (a->current && now - a->last_present < RA_SPARE)) { pp = &a->next; continue; }
        if (a->current) nvn_hm_del(&g_ra, &a->key);
        vkFreeMemory(g_vk.dev, a->mem, NULL); g_im_live -= a->size;   // nothing holds it: every image on it went with a completed chunk
        *pp = a->next; free(a);
    }
}
static void ra_drop_pool(const void *pool) {   // under g_bk (vt_drop_pool): the pool's keys are not taken again
    for (ralloc *a = g_ra_all; a; a = a->next) if (a->current && a->key.pool == (uint64_t)(uintptr_t)pool) { nvn_hm_del(&g_ra, &a->key); a->current = 0; }
}
static void ra_stat(void) {   // the periodic line (mtl_mem_stat), when on
    if (!ra_mode()) return;
    uint32_t n = 0, held = 0; uint64_t b = 0;
    for (ralloc *a = g_ra_all; a; a = a->next) { n++; b += a->size; held += (uint32_t)atomic_load(&a->refs); }
    LOG("[vk] render targets sharing memory (DM_VK_RTALIAS=%d): %u allocations, %.0f MB, holding %u images; %llu images joined one (%.0f MB not allocated), %llu made, %llu of them grown (cumulative)",
        ra_mode(), n, b / 1048576.0, held, (unsigned long long)g_ra_joined, g_ra_join_bytes / 1048576.0, (unsigned long long)g_ra_made, (unsigned long long)g_ra_grown);
}
