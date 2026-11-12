// t_vm_remap: vm_remap to a fixed destination on Android (plat_android.c), as a virtual memory pool asks for it (hle_nvn.c vpool_map): a duplication the kernel refuses
// (a private source) leaves the destination mapped as it was, with no hole a later mapping could land in, and a shareable source is aliased at the destination.
// Run on a device: adb push, then adb shell. Prints one line per check and "t_vm_remap: ok" or the count that failed.
#include <errno.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/syscall.h>
#include <unistd.h>
#ifndef MAP_FIXED_NOREPLACE
#define MAP_FIXED_NOREPLACE 0x100000
#endif
static int g_bad;
#define CHECK(x, what) do { int ok_ = (x); printf("%s  %s\n", ok_ ? "ok  " : "FAIL", what); g_bad += !ok_; } while (0)
// every page of [a, a + n) is mapped: a mapping that may not replace one is refused on each
static int mapped(const uint8_t *a, size_t n, size_t pg) {
    for (size_t o = 0; o < n; o += pg) {
        void *p = mmap((void *)(uintptr_t)(a + o), pg, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED_NOREPLACE, -1, 0);
        if (p != MAP_FAILED) { munmap(p, pg); return 0; }
    }
    return 1;
}
int main(void) {
    size_t pg = (size_t)getpagesize(), n = 64 * pg; vm_prot_t cur, max;
    uint8_t *res = mmap(NULL, 4 * n, PROT_NONE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE, -1, 0);   // a virtual pool's reservation
    uint8_t *priv = mmap(NULL, n, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);        // a physical pool's storage on Android: private memory
    if (res == MAP_FAILED || priv == MAP_FAILED) { printf("t_vm_remap: no memory\n"); return 2; }
    memset(priv, 0x5a, n);
    vm_address_t to = (vm_address_t)(res + n);
    kern_return_t kr = vm_remap(mach_task_self(), &to, n, 0, VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE, mach_task_self(), (vm_address_t)priv, FALSE, &cur, &max, VM_INHERIT_NONE);
    CHECK(kr != KERN_SUCCESS, "a private source is refused");
    CHECK(mapped(res, 4 * n, pg), "the reservation is whole after the refused request (no hole at the destination)");
    uint8_t *later = mmap(NULL, n, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);   // the next mapping anyone makes (the driver's, a heap's)
    CHECK(later != MAP_FAILED && (later + n <= res || later >= res + 4 * n), "a mapping made afterwards lies outside the reservation");
    CHECK(priv[0] == 0x5a && priv[n - 1] == 0x5a, "the source is untouched");

    int fd = (int)syscall(SYS_memfd_create, "t_vm_remap", 0);
    uint8_t *sh = fd >= 0 && !ftruncate(fd, (off_t)n) ? mmap(NULL, n, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0) : MAP_FAILED;
    if (sh == MAP_FAILED) { printf("t_vm_remap: no shared memory (errno %d)\n", errno); return 2; }
    memset(sh, 0xa5, n);
    to = (vm_address_t)(res + 2 * n);
    kr = vm_remap(mach_task_self(), &to, n, 0, VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE, mach_task_self(), (vm_address_t)sh, FALSE, &cur, &max, VM_INHERIT_NONE);
    CHECK(kr == KERN_SUCCESS && to == (vm_address_t)(res + 2 * n), "a shareable source is aliased at the destination");
    if (kr == KERN_SUCCESS) {
        uint8_t *al = (uint8_t *)to; al[1] = 7;
        CHECK(al[0] == 0xa5 && sh[1] == 7, "the alias and the source are the same memory");
    }
    CHECK(mapped(res, 4 * n, pg), "the reservation is whole after the alias");
    vm_address_t any = 0;
    kr = vm_remap(mach_task_self(), &any, n, 0, VM_FLAGS_ANYWHERE, mach_task_self(), (vm_address_t)sh, FALSE, &cur, &max, VM_INHERIT_NONE);
    CHECK(kr == KERN_SUCCESS && any && ((uint8_t *)any)[1] == 7, "a duplicate anywhere reads the source");
    if (g_bad) printf("t_vm_remap: %d failed\n", g_bad); else printf("t_vm_remap: ok\n");
    return g_bad != 0;
}
