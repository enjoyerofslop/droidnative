// q190 diagnostic, not for commit: a CPU sampler on the thread that presents (the NVN queue replay thread), for devices where shell cannot open perf events.
// DM_CPUPROF=<seconds>[:<hz>] arms it; a file named cpuprof_now in $DM_CPUPROF_DIR starts it (looked for every 4 presents). A timer on the thread's own CPU clock sends it
// SIGPROF; the handler keeps the PC, LR and the frame-pointer chain. After <seconds> of wall time it writes cpuprof.bin and cpuprof_maps.txt to $DM_CPUPROF_DIR.
#include <signal.h>
#include <ucontext.h>
#include <dlfcn.h>
#include <sys/prctl.h>
enum { CPF_DEPTH = 24, CPF_MAX = 120000 };
static uint64_t *cpf_buf; static _Atomic uint32_t cpf_n; static timer_t cpf_timer; static int cpf_state; static uint64_t cpf_lo, cpf_hi, cpf_t0, cpf_c0, cpf_p0;
static double cpf_secs = 10; static int cpf_hz = 1000;
static void cpf_handler(int sig, siginfo_t *si, void *ucv) {
    (void)sig; (void)si; ucontext_t *uc = ucv;
    uint32_t i = atomic_fetch_add_explicit(&cpf_n, 1, memory_order_relaxed); if (i >= CPF_MAX) return;
    uint64_t *r = cpf_buf + (size_t)i * CPF_DEPTH; int k = 0;
    r[k++] = uc->uc_mcontext.pc; r[k++] = uc->uc_mcontext.regs[30];
    uint64_t fp = uc->uc_mcontext.regs[29];
    while (k < CPF_DEPTH && fp >= cpf_lo && fp + 16 <= cpf_hi && !(fp & 7)) { const uint64_t *f = (const uint64_t *)fp; r[k++] = f[1]; if (f[0] <= fp) break; fp = f[0]; }
    while (k < CPF_DEPTH) r[k++] = 0;
}
static uint64_t cpf_thread_ns(void) { struct timespec t; clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t); return (uint64_t)t.tv_sec * 1000000000ull + (uint64_t)t.tv_nsec; }
static void cpf_start(uint64_t presents) {
    const char *e = getenv("DM_CPUPROF"); if (e && *e) { cpf_secs = atof(e); const char *c = strchr(e, ':'); if (c) cpf_hz = atoi(c + 1); }
    if (cpf_hz < 10) cpf_hz = 10;
    if (!cpf_buf) cpf_buf = calloc((size_t)CPF_MAX * CPF_DEPTH, 8);
    if (!cpf_buf) { LOG("[cpuprof] no memory"); cpf_state = 3; return; }
    pthread_attr_t a; void *sa = NULL; size_t ss = 0;
    if (!pthread_getattr_np(pthread_self(), &a)) { pthread_attr_getstack(&a, &sa, &ss); pthread_attr_destroy(&a); }
    cpf_lo = (uint64_t)(uintptr_t)sa; cpf_hi = cpf_lo + ss;
    struct sigaction act; memset(&act, 0, sizeof act); act.sa_sigaction = cpf_handler; act.sa_flags = SA_SIGINFO | SA_RESTART; sigemptyset(&act.sa_mask);
    if (sigaction(SIGPROF, &act, NULL)) { LOG("[cpuprof] sigaction failed"); cpf_state = 3; return; }
    clockid_t cid = CLOCK_MONOTONIC;   // oot-clock: wall time, so the samples show where the thread blocks (the q190 original used pthread_getcpuclockid)
    struct sigevent sev; memset(&sev, 0, sizeof sev); sev.sigev_notify = SIGEV_THREAD_ID; sev.sigev_signo = SIGPROF; sev.sigev_notify_thread_id = gettid();
    if (timer_create(cid, &sev, &cpf_timer)) { LOG("[cpuprof] timer_create failed: %d", errno); cpf_state = 3; return; }
    atomic_store(&cpf_n, 0); cpf_t0 = now_ns(); cpf_c0 = cpf_thread_ns(); cpf_p0 = presents;
    long ns = 1000000000L / cpf_hz; struct itimerspec it = {{0, ns}, {0, ns}};
    if (timer_settime(cpf_timer, 0, &it, NULL)) { LOG("[cpuprof] timer_settime failed: %d", errno); timer_delete(cpf_timer); cpf_state = 3; return; }
    char name[32] = {0}; prctl(PR_GET_NAME, name, 0, 0, 0);
    cpf_state = 1; LOG("[cpuprof] sampling thread %d \"%s\" at %d Hz of wall time for %.1f s from present %llu (stack %#llx-%#llx)", gettid(), name, cpf_hz, cpf_secs, (unsigned long long)presents,
                       (unsigned long long)cpf_lo, (unsigned long long)cpf_hi);
}
static void cpf_finish(uint64_t presents) {
    timer_delete(cpf_timer); cpf_state = 2;
    uint64_t wall = now_ns() - cpf_t0, cpu = cpf_thread_ns() - cpf_c0; uint32_t n = atomic_load(&cpf_n); if (n > CPF_MAX) n = CPF_MAX;
    const char *dir = getenv("DM_CPUPROF_DIR"); char p[700];
    Dl_info di; memset(&di, 0, sizeof di); dladdr((void *)cpf_start, &di);
    snprintf(p, sizeof p, "%s/cpuprof.bin", dir); FILE *f = fopen(p, "wb");
    if (f) { uint64_t h[8] = {0x31666f727063ull, n, CPF_DEPTH, wall, cpu, presents - cpf_p0, (uint64_t)(uintptr_t)di.dli_fbase, (uint64_t)cpf_hz}; fwrite(h, 8, 8, f); fwrite(cpf_buf, 8, (size_t)n * CPF_DEPTH, f); fclose(f); }
    snprintf(p, sizeof p, "%s/cpuprof_maps.txt", dir); FILE *o = fopen(p, "w"), *m = fopen("/proc/self/maps", "r");
    if (o && m) { char l[1024]; while (fgets(l, sizeof l, m)) if (strstr(l, " r-xp ") || strstr(l, " r--p ")) fputs(l, o); }
    if (o) fclose(o); if (m) fclose(m);
    LOG("[cpuprof] %u samples over %.2f s wall, %.2f s of the thread's CPU, %llu presents; host base %p (%s); written to %s", n, wall / 1e9, cpu / 1e9, (unsigned long long)(presents - cpf_p0),
        di.dli_fbase, di.dli_fname ? di.dli_fname : "?", dir);
}
static void cpuprof_poll(uint64_t presents) {
    const char *dir = getenv("DM_CPUPROF_DIR"); if (!dir || cpf_state >= 2) { if (dir && cpf_state == 2) { char p[700]; snprintf(p, sizeof p, "%s/cpuprof_now", dir); if (!access(p, F_OK)) { unlink(p); cpf_state = 0; cpf_start(presents); } } return; }
    if (cpf_state == 1) { if (now_ns() - cpf_t0 >= (uint64_t)(cpf_secs * 1e9)) cpf_finish(presents); return; }
    if (presents % 4) return;
    char p[700]; snprintf(p, sizeof p, "%s/cpuprof_now", dir);
    if (!access(p, F_OK)) { unlink(p); cpf_start(presents); }
}
