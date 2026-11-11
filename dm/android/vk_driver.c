// The Vulkan driver behind gfx_vk.h's vk* pointers.
//   By default the system's: libvulkan.so, opened when the replay makes its device (vkb), as linking it did before.
//   DM_VK_DRIVER=<file> (env.txt) runs another driver, such as a build of Mesa's Turnip for Adreno GPUs, as players of Switch emulators use: a .so the player puts on the
//   device, named relative to the folder env.txt is in (or by an absolute path). Android loads no library from shared storage, so it is copied into the app's internal files
//   (vk_driver/<name>), and opened through libadrenotools (dm/third_party/libadrenotools): a second copy of the system's libvulkan.so in a linker namespace of its own, where
//   a hook loads the player's driver in place of the vendor's. The loader in that copy still makes the window surface and the swapchain, which Turnip on Android lacks.
//   A driver that cannot be copied or opened, or that offers no GPU, logs one [RED] line, and the system's driver runs. So does one that opens and then fails to make the
//   instance, find the GPU's graphics queue or the window extensions, or make the device (gfx_vk.c vk_create, through vk_driver_fallback), or the first window's surface
//   or swapchain (front_android.c vk_window_first): a player's choice of driver must never leave a game without a picture. On a phone without an Adreno GPU, DM_VK_DRIVER is not opened at all.
#include <dlfcn.h>
#include <stdatomic.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/sysmacros.h>
#include "dm.h"
#include "gfx_vk.h"
#include "../third_party/libadrenotools/include/adrenotools/driver.h"   // the type of adrenotools_open_libvulkan, opened with dlsym: the host does not link it

#define VKB_DEF(f) PFN_##f f;
VKB_FNS_GLOBAL(VKB_DEF) VKB_FNS(VKB_DEF)
static PFN_vkGetInstanceProcAddr g_gipa;
static char g_ext[512], g_int[512], g_name[256];   // vk_driver_dirs; g_name: the DM_VK_DRIVER file running

void vk_driver_dirs(const char *ext, const char *internal) { snprintf(g_ext, sizeof g_ext, "%s", ext); snprintf(g_int, sizeof g_int, "%s", internal); }
const char *vk_driver_name(void) { return g_name[0] ? g_name : NULL; }
#define DRV_RED(drv, fmt, ...) LOG("[RED] [vk] DM_VK_DRIVER %s: " fmt, drv, ##__VA_ARGS__)

// src → <dir><name> (dir: <internal>/vk_driver/), unless the copy there has src's size and time already. Read-only once written, as Android 14 asks of code an app loads
// from its own files. → 0 with errno set
static int copy_in(const char *src, const char *dir, const char *name) {
    struct stat s, d; char dst[800], tmp[810];
    if (stat(src, &s)) return 0;
    if (!S_ISREG(s.st_mode)) { errno = EISDIR; return 0; }
    if (mkdir(dir, 0700) && errno != EEXIST) return 0;
    snprintf(dst, sizeof dst, "%s%s", dir, name); snprintf(tmp, sizeof tmp, "%s.part", dst);
    if (!stat(dst, &d) && d.st_size == s.st_size && d.st_mtime == s.st_mtime) return 1;
    int in = open(src, O_RDONLY | O_CLOEXEC); if (in < 0) return 0;
    unlink(tmp); int out = open(tmp, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (out < 0) { int e = errno; close(in); errno = e; return 0; }
    static char buf[1 << 16]; ssize_t k = 0; int ok = 1;
    while (ok && (k = read(in, buf, sizeof buf)) > 0) for (ssize_t w = 0, n; w < k; w += n) if ((n = write(out, buf + w, (size_t)(k - w))) <= 0) { ok = 0; break; }
    struct timespec ts[2] = {s.st_atim, s.st_mtim};
    ok = ok && k == 0 && !fchmod(out, 0500) && !futimens(out, ts);
    int e = errno; close(in); if (close(out)) ok = 0;
    if (ok) { unlink(dst); ok = !rename(tmp, dst); e = errno; }
    if (!ok) unlink(tmp);
    errno = e; return ok;
}

// Whether the file at path is mapped in this process: when adrenotools' hook cannot put the player's driver in place, it opens the vendor's instead and says so only in
// logcat. By device and inode, as /proc/self/maps lists them (its path column may name the file through another mount, /data/data for /data/user/0). (Not
// dl_iterate_phdr: <link.h> clashes with dm.h's ELF types)
static int mapped(const char *path) {
    struct stat st; if (stat(path, &st)) return 0;
    FILE *f = fopen("/proc/self/maps", "re"); if (!f) return 0;
    char line[1024]; unsigned maj, mnr; unsigned long long ino; int found = 0;
    while (!found && fgets(line, sizeof line, f))
        found = sscanf(line, "%*s %*s %*s %x:%x %llu", &maj, &mnr, &ino) == 3 && ino == (unsigned long long)st.st_ino && maj == major(st.st_dev) && mnr == minor(st.st_dev);
    fclose(f); return found;
}

// The GPU a driver offers, on an instance made for the question: a Turnip built for another Adreno generation opens and then has none
static int first_gpu(PFN_vkGetInstanceProcAddr g, VkPhysicalDeviceProperties *pr) {
    PFN_vkCreateInstance create = (PFN_vkCreateInstance)g(NULL, "vkCreateInstance");
    VkApplicationInfo ai = {.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO, .pApplicationName = "nxnative", .apiVersion = VK_API_VERSION_1_1};
    VkInstanceCreateInfo ic = {.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO, .pApplicationInfo = &ai};
    VkInstance in; if (!create || create(&ic, NULL, &in) != VK_SUCCESS) return 0;
    PFN_vkEnumeratePhysicalDevices gpus = (PFN_vkEnumeratePhysicalDevices)g(in, "vkEnumeratePhysicalDevices");
    PFN_vkGetPhysicalDeviceProperties props = (PFN_vkGetPhysicalDeviceProperties)g(in, "vkGetPhysicalDeviceProperties");
    PFN_vkDestroyInstance destroy = (PFN_vkDestroyInstance)g(in, "vkDestroyInstance");
    uint32_t n = 1; VkPhysicalDevice pd; VkResult r = gpus ? gpus(in, &n, &pd) : VK_ERROR_INITIALIZATION_FAILED;
    int ok = (r == VK_SUCCESS || r == VK_INCOMPLETE) && n && props;
    if (ok) props(pd, pr);
    if (destroy) destroy(in, NULL);
    return ok;
}

// DM_VK_DRIVER's driver → its vkGetInstanceProcAddr, NULL (and one [RED] line) when it cannot run
static PFN_vkGetInstanceProcAddr open_custom(const char *drv) {
    char src[700], dir[600]; const char *name;
    if (drv[0] == '/' || !g_ext[0]) snprintf(src, sizeof src, "%s", drv); else snprintf(src, sizeof src, "%s/%s", g_ext, drv);
    name = strrchr(src, '/') ? strrchr(src, '/') + 1 : src;
    if (!*name || strlen(name) >= sizeof g_name) { DRV_RED(drv, "not a file name; the system's driver instead"); return NULL; }
    if (g_int[0]) {   // the app: copied in
        snprintf(dir, sizeof dir, "%s/vk_driver/", g_int);
        if (!copy_in(src, dir, name)) { DRV_RED(drv, "%s: %s; the system's driver instead", src, strerror(errno)); return NULL; }
    } else {          // the command-line host (adb shell): loaded where it lies, which must be a folder that allows code (/data/local/tmp, not /sdcard)
        if (access(src, R_OK)) { DRV_RED(drv, "%s: %s; the system's driver instead", src, strerror(errno)); return NULL; }
        snprintf(dir, sizeof dir, "%.*s/", name > src ? (int)(name - src - 1) : 1, name > src ? src : ".");
    }
    // adrenotools' hooks (libhook_impl.so, libmain_hook.so) are looked for where the host lies: the app's native library folder, extracted (AndroidManifest extractNativeLibs)
    Dl_info di; char libs[600] = "";
    if (dladdr((void *)open_custom, &di) && di.dli_fname && strrchr(di.dli_fname, '/'))
        snprintf(libs, sizeof libs, "%.*s/", (int)(strrchr(di.dli_fname, '/') - di.dli_fname), di.dli_fname);
    void *at = dlopen("libadrenotools.so", RTLD_NOW | RTLD_LOCAL);
    __typeof__(adrenotools_open_libvulkan) *open_vk = at ? (__typeof__(adrenotools_open_libvulkan) *)dlsym(at, "adrenotools_open_libvulkan") : NULL;
    if (!open_vk) { DRV_RED(drv, "libadrenotools.so is not in this app (%s): pack the app again; the system's driver instead", dlerror()); return NULL; }
    void *lib = open_vk(RTLD_NOW | RTLD_LOCAL, ADRENOTOOLS_DRIVER_CUSTOM, NULL, libs, dir, name, NULL, NULL);
    PFN_vkGetInstanceProcAddr g = lib ? (PFN_vkGetInstanceProcAddr)dlsym(lib, "vkGetInstanceProcAddr") : NULL;
    if (!g) { DRV_RED(drv, "libadrenotools could not open it (adb logcat -s hook_impl says why); the system's driver instead"); return NULL; }
    // (a driver that opened and is not used stays loaded: drivers do not always unload cleanly)
    VkPhysicalDeviceProperties pr; char path[900]; snprintf(path, sizeof path, "%s%s", dir, name);
    if (!first_gpu(g, &pr)) { DRV_RED(drv, "it offers no GPU (a build for another GPU?); the system's driver instead"); return NULL; }
    if (!mapped(path)) {
        DRV_RED(drv, "libadrenotools opened the system's driver in its place (adb logcat -s hook_impl says why); the system's driver instead"); return NULL; }
    snprintf(g_name, sizeof g_name, "%s", name);
    LOG("[vk] driver: %s (DM_VK_DRIVER, through libadrenotools), not the system's: %s, Vulkan %u.%u.%u, driver version %#x", path, pr.deviceName,
        VK_API_VERSION_MAJOR(pr.apiVersion), VK_API_VERSION_MINOR(pr.apiVersion), VK_API_VERSION_PATCH(pr.apiVersion), pr.driverVersion);
    return g;
}

#define VKB_LOAD_GLOBAL(f) f = (PFN_##f)g_gipa(NULL, #f);
static int open_system(void) {
    void *lib = dlopen("libvulkan.so", RTLD_NOW | RTLD_LOCAL);
    if (!lib || !(g_gipa = (PFN_vkGetInstanceProcAddr)dlsym(lib, "vkGetInstanceProcAddr"))) { LOG("[RED] [vk] no Vulkan: libvulkan.so: %s", dlerror()); return 0; }
    VKB_FNS_GLOBAL(VKB_LOAD_GLOBAL)
    if (!vkCreateInstance || !vkEnumerateInstanceExtensionProperties) { LOG("[RED] [vk] no Vulkan: the driver has no vkCreateInstance"); return 0; }
    return 1;
}
// Turnip, like every driver libadrenotools loads, drives Qualcomm's kernel GPU driver, KGSL. Without its device node (a Mali or Xclipse phone) such a driver has nothing to
// run on, and libadrenotools.so's constructor (liblinkernsbypass) would patch the linker for nothing. Only a missing node counts: one SELinux keeps from a stat is still there
static int adreno(void) { struct stat st; return !stat("/dev/kgsl-3d0", &st) || errno != ENOENT; }

int vk_driver_load(void) {
    const char *drv = getenv("DM_VK_DRIVER");
    if (drv && *drv && !adreno()) LOG("[vk] DM_VK_DRIVER %s: not used, this GPU is not an Adreno (no /dev/kgsl-3d0) and Turnip drivers are for Adreno GPUs only: the system's driver runs", drv);
    else if (drv && *drv) g_gipa = open_custom(drv);
    if (g_gipa) {
        VKB_FNS_GLOBAL(VKB_LOAD_GLOBAL)
        if (vkCreateInstance && vkEnumerateInstanceExtensionProperties) return 1;
        DRV_RED(g_name, "it has no vkCreateInstance; the system's driver instead"); g_name[0] = 0;
    }
    return open_system();
}

// DM_VK_DRIVER_FAIL=<step> (env.txt, a test): that step fails while the DM_VK_DRIVER driver runs, as if the driver had failed it, so the fallback can be tried on a phone
// whose driver works. Steps: instance, gpu, queue, extensions, device (gfx_vk.c vk_try), swapchain (the first window's, front_android.c vk_window_up). The system's driver
// it falls back to is left alone
int vk_driver_fail(const char *step) {
    const char *e = getenv("DM_VK_DRIVER_FAIL");
    return g_name[0] && e && !strcmp(e, step);
}
// The DM_VK_DRIVER driver failed after the probe: the system's driver from now on, with one [RED] line saying why. 0: none was running, or the system's has no Vulkan
int vk_driver_fallback(const char *why) {
    if (!g_name[0]) return 0;
    DRV_RED(g_name, "%s; the system's driver instead", why);
    g_name[0] = 0; g_gipa = NULL;   // (its library stays loaded, as after a failed probe)
    return open_system();
}

const char *vk_result_str(VkResult r) {
    switch (r) {
#define VKR(x) case x: return #x;
        VKR(VK_SUCCESS) VKR(VK_INCOMPLETE) VKR(VK_ERROR_OUT_OF_HOST_MEMORY) VKR(VK_ERROR_OUT_OF_DEVICE_MEMORY) VKR(VK_ERROR_INITIALIZATION_FAILED) VKR(VK_ERROR_DEVICE_LOST)
        VKR(VK_ERROR_LAYER_NOT_PRESENT) VKR(VK_ERROR_EXTENSION_NOT_PRESENT) VKR(VK_ERROR_FEATURE_NOT_PRESENT) VKR(VK_ERROR_INCOMPATIBLE_DRIVER) VKR(VK_ERROR_TOO_MANY_OBJECTS)
        VKR(VK_ERROR_FORMAT_NOT_SUPPORTED) VKR(VK_ERROR_UNKNOWN) VKR(VK_ERROR_SURFACE_LOST_KHR) VKR(VK_ERROR_NATIVE_WINDOW_IN_USE_KHR) VKR(VK_ERROR_OUT_OF_DATE_KHR)
#undef VKR
        default: { static _Thread_local char b[24]; snprintf(b, sizeof b, "VkResult %d", (int)r); return b; }
    }
}

// The floating-point environment of the driver's compiler. The replay and its pipeline threads run on threads the game's NVN calls started, or on the game's own, so
// they carry the game's FPCR: 0x1000000 (flush-to-zero) for Ocarina of Time. Qualcomm's compiler, run on the CPU inside vkCreate*Pipelines (Samsung's in
// vkCreateShaderModule), then folds constants with denormals flushed and makes different code: Swap2-Native measured Ocarina of Time's scene about 2^12 too bright
// at the bloom pass on driver 891.11, and BananaNative sets FPCR 0 around these calls (vka_fpenv.h). So the calls that compile (device, module, pipelines, and a
// submit, where a driver may compile what it deferred) run with FPCR 0 and give the caller's back after; the game's own threads keep theirs. The pipeline cache's
// file is named apart (gfx_vk_draw.inc pcache), so pipelines compiled under flush-to-zero are not taken from it. DM_VK_FP_HOST=0 (env.txt): the caller's FPCR, as before
#if defined(__aarch64__)
static int fp_host_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_FP_HOST"); v = !(e && *e == '0'); if (!v) LOG("[vk] DM_VK_FP_HOST=0: the driver compiles with the calling thread's FPCR"); } return v; }
static inline uint64_t fp_enter(void) {
    uint64_t v; __asm__ volatile("mrs %0, fpcr" : "=r"(v));
    if (v && fp_host_on()) {
        static _Atomic int told; if (!atomic_exchange(&told, 1)) LOG("[vk] the calling thread's FPCR is %#llx: the driver compiles with FPCR 0 (DM_VK_FP_HOST=0: as it is)", (unsigned long long)v);
        __asm__ volatile("msr fpcr, %0" :: "r"((uint64_t)0)); return v;
    }
    return 0;
}
static inline void fp_leave(uint64_t v) { if (v) __asm__ volatile("msr fpcr, %0" :: "r"(v)); }
#else
static inline uint64_t fp_enter(void) { return 0; }
static inline void fp_leave(uint64_t v) { (void)v; }
#endif
int vk_fp_host(void) {   // 1: compiles run with FPCR 0 (the pipeline cache's file is named for it)
#if defined(__aarch64__)
    return fp_host_on();
#else
    return 0;
#endif
}
static PFN_vkCreateDevice d_create_device; static PFN_vkCreateShaderModule d_create_module; static PFN_vkCreateGraphicsPipelines d_create_gp;
static PFN_vkCreateComputePipelines d_create_cp; static PFN_vkQueueSubmit d_submit;
static VKAPI_ATTR VkResult VKAPI_CALL fp_create_device(VkPhysicalDevice pd, const VkDeviceCreateInfo *ci, const VkAllocationCallbacks *a, VkDevice *d) {
    uint64_t f = fp_enter(); VkResult r = d_create_device(pd, ci, a, d); fp_leave(f); return r; }
static VKAPI_ATTR VkResult VKAPI_CALL fp_create_module(VkDevice d, const VkShaderModuleCreateInfo *ci, const VkAllocationCallbacks *a, VkShaderModule *m) {
    uint64_t f = fp_enter(); VkResult r = d_create_module(d, ci, a, m); fp_leave(f); return r; }
static VKAPI_ATTR VkResult VKAPI_CALL fp_create_gp(VkDevice d, VkPipelineCache c, uint32_t n, const VkGraphicsPipelineCreateInfo *ci, const VkAllocationCallbacks *a, VkPipeline *p) {
    uint64_t f = fp_enter(); VkResult r = d_create_gp(d, c, n, ci, a, p); fp_leave(f); return r; }
static VKAPI_ATTR VkResult VKAPI_CALL fp_create_cp(VkDevice d, VkPipelineCache c, uint32_t n, const VkComputePipelineCreateInfo *ci, const VkAllocationCallbacks *a, VkPipeline *p) {
    uint64_t f = fp_enter(); VkResult r = d_create_cp(d, c, n, ci, a, p); fp_leave(f); return r; }
static VKAPI_ATTR VkResult VKAPI_CALL fp_submit(VkQueue q, uint32_t n, const VkSubmitInfo *si, VkFence fe) {
    uint64_t f = fp_enter(); VkResult r = d_submit(q, n, si, fe); fp_leave(f); return r; }

void vk_driver_instance(VkInstance inst) {
#define VKB_LOAD(f) f = (PFN_##f)g_gipa(inst, #f);
    VKB_FNS(VKB_LOAD)
    if (vkCreateDevice) { d_create_device = vkCreateDevice; vkCreateDevice = fp_create_device; }   // through the FPCR guard (above)
    if (vkCreateShaderModule) { d_create_module = vkCreateShaderModule; vkCreateShaderModule = fp_create_module; }
    if (vkCreateGraphicsPipelines) { d_create_gp = vkCreateGraphicsPipelines; vkCreateGraphicsPipelines = fp_create_gp; }
    if (vkCreateComputePipelines) { d_create_cp = vkCreateComputePipelines; vkCreateComputePipelines = fp_create_cp; }
    if (vkQueueSubmit) { d_submit = vkQueueSubmit; vkQueueSubmit = fp_submit; }
}
