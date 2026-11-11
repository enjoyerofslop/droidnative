// The record of every start, whatever Vulkan driver runs the game: games/<title ID>/vk_start.txt in the external files, which DroidPlay for Windows reads over adb (the
// app isn't debuggable, so its internal files are out of reach). A pipeline the phone's own driver refuses leaves its draws out of the picture: Frostpunk's Generator on a
// Razr's Adreno 730 (54 pipelines on the way into its city; the log names only the first 16 of each kind), Ocarina of Time's characters on an Odin 2's 740. The desktop
// app reads the count back after a run and, when its pinned catalog has a driver tested
// for this game on this GPU, suggests that driver; it never switches one on by itself, and the system's driver stays every game's default. Lines:
//   driver=            system, or the DM_VK_DRIVER file that runs (after a fallback to the system's driver: system)
//   driver_id=         the driver's VkDriverId: 8 Qualcomm's own, 18 Mesa's Turnip; 0 when the driver doesn't say
//   gpu=               the device's name, as the driver gives it
//   pipelines_failed=  pipelines the game needed that the driver refused, graphics and compute (each counts once: a failed pipeline isn't made again)
//   failed_shaders=    the first 4 shader sets among them, comma-separated (one set often fails in several pipelines, with other state): a graphics pipeline's vertex and
//                      fragment shader keys joined by +, a compute pipeline's shader key
//   device_lost=       the VkResult when the GPU was lost, else empty
//   time=              the Unix time the device was made
// Written when the device is made (a start that ends before that leaves none: the previous start's is removed when the game's folder is known), again within 2 s of a
// change (vk_start_tick, from the front end's loop: a pipeline fails under the replay's lock, which a file write shouldn't hold up), and at once when the GPU is lost
#include <fcntl.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <string.h>
#include <time.h>
#include <unistd.h>
#include "dm.h"
#include "gfx_vk.h"

enum { KEYS = 4 };
static pthread_mutex_t g_mu = PTHREAD_MUTEX_INITIALIZER;   // everything below but the atomics
static char g_path[700], g_gpu[256], g_drv[256], g_keys[KEYS][40], g_lost[48];
static int g_id, g_nk;
static long long g_t;   // the device's creation; 0 until then (nothing is written)
static _Atomic unsigned g_failed;
static _Atomic int g_dirty;
static uint64_t g_last_ns;   // vk_start_tick's last write (the front end's thread only)

static uint64_t mono(void) { struct timespec ts; clock_gettime(CLOCK_MONOTONIC, &ts); return (uint64_t)ts.tv_sec * 1000000000ull + (uint64_t)ts.tv_nsec; }

static void cat(char *b, size_t n, size_t *k, const char *fmt, const char *s) {   // appends without running past the buffer
    if (*k + 1 >= n) return;
    int w = snprintf(b + *k, n - *k, fmt, s);
    *k = w < 0 ? *k : *k + (size_t)w >= n ? n - 1 : *k + (size_t)w;
}
static void write_rec(void) {
    char b[1400], path[sizeof g_path], num[64]; size_t k = 0;
    pthread_mutex_lock(&g_mu);
    if (!g_path[0] || !g_t) { pthread_mutex_unlock(&g_mu); return; }
    atomic_store(&g_dirty, 0);
    cat(b, sizeof b, &k, "driver=%s\n", g_drv);
    snprintf(num, sizeof num, "%d", g_id); cat(b, sizeof b, &k, "driver_id=%s\n", num);
    cat(b, sizeof b, &k, "gpu=%s\n", g_gpu);
    snprintf(num, sizeof num, "%u", atomic_load(&g_failed)); cat(b, sizeof b, &k, "pipelines_failed=%s\nfailed_shaders=", num);
    for (int i = 0; i < g_nk; i++) cat(b, sizeof b, &k, i ? ",%s" : "%s", g_keys[i]);
    cat(b, sizeof b, &k, "\ndevice_lost=%s\n", g_lost);
    snprintf(num, sizeof num, "%lld", g_t); cat(b, sizeof b, &k, "time=%s\n", num);
    snprintf(path, sizeof path, "%s", g_path);
    pthread_mutex_unlock(&g_mu);
    char tmp[sizeof path + 24]; snprintf(tmp, sizeof tmp, "%s.%d.new", path, (int)gettid());   // whole or not at all
    int fd = open(tmp, O_WRONLY | O_CREAT | O_TRUNC | O_CLOEXEC, 0666); if (fd < 0) return;
    int ok = write(fd, b, k) == (ssize_t)k;
    if (close(fd) || !ok || rename(tmp, path)) unlink(tmp);
}

void vk_start_game(const char *dir) {
    pthread_mutex_lock(&g_mu); snprintf(g_path, sizeof g_path, "%s/vk_start.txt", dir); pthread_mutex_unlock(&g_mu);
    unlink(g_path);
}
void vk_start_device(const char *gpu, int driver_id) {
    const char *d = vk_driver_name();
    pthread_mutex_lock(&g_mu);
    snprintf(g_gpu, sizeof g_gpu, "%s", gpu); snprintf(g_drv, sizeof g_drv, "%s", d ? d : "system"); g_id = driver_id;
    atomic_store(&g_failed, 0); g_nk = 0; g_lost[0] = 0; g_t = (long long)time(NULL);
    int first = g_path[0] != 0;
    pthread_mutex_unlock(&g_mu);
    write_rec();
    static int told; if (first && !told++) LOG("[vk] start record: %s (the driver, the GPU, pipelines it refuses, a lost device), read by the desktop app", g_path);
}
void vk_start_pipe_failed(const char *a, const char *b) {
    atomic_fetch_add(&g_failed, 1);
    char k[sizeof *g_keys]; snprintf(k, sizeof k, "%s%s%s", a ? a : "-", b ? "+" : "", b ? b : "");
    pthread_mutex_lock(&g_mu);
    int seen = 0; for (int i = 0; i < g_nk && !seen; i++) seen = !strcmp(g_keys[i], k);
    if (!seen && g_nk < KEYS) memcpy(g_keys[g_nk++], k, sizeof k);
    pthread_mutex_unlock(&g_mu);
    atomic_store(&g_dirty, 1);
}
void vk_start_lost(VkResult r) {
    pthread_mutex_lock(&g_mu); snprintf(g_lost, sizeof g_lost, "%s", vk_result_str(r)); pthread_mutex_unlock(&g_mu);
    write_rec();
}
void vk_start_tick(void) {
    if (!atomic_load(&g_dirty)) return;
    uint64_t now = mono(); if (now - g_last_ns < 2000000000ull) return;
    g_last_ns = now; write_rec();
}
