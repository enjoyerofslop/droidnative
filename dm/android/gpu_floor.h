// The GPU clock floor's rules (gfx_vk_floor.inc; DM_VK_GPU_FLOOR, the launcher's Keep the GPU clock up), apart from the kernel: which KGSL contexts are the Vulkan device's,
// the level each is sent, and when nothing is sent at all. The kernel lets a file descriptor constrain only the contexts it owns (kgsl_context_get_owner), so the device's
// contexts are the ones this process's /dev/kgsl-3d0 descriptors own after vkCreateDevice and did not own before it (the front end's and any other library's stay as they
// are). Ownership is asked with the same call and KGSL_CONSTRAINT_NONE, which changes nothing on a context without a constraint. A GPU whose clock the kernel decides (host
// DCVS: the Galaxy S25 Edge's Adreno 830) takes only the highest clock (KGSL_CONSTRAINT_PWR_MAX) and answers EINVAL to a scaled level; one whose GMU decides it (the Galaxy
// Z Fold 8's 840) takes a level in % of the highest clock too. The call is the caller's function, so dm/tools/tests/test_gpu_floor.py drives these rules with a stand-in for
// Qualcomm's kernel driver.
#pragma once
#include <errno.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

enum { GF_CONSTRAINT_NONE = 0, GF_CONSTRAINT_PWRLEVEL = 1, GF_LEVEL_MAX = 1, GF_PROBE = 50, GF_FDS = 4, GF_IDS = 1024, GF_CTX = 8 };

// One KGSL_PROP_PWR_CONSTRAINT on descriptor fd for context id: 0, or -errno
typedef int (*gf_set_fn)(int fd, unsigned id, unsigned type, unsigned level);

typedef struct { uint8_t bit[GF_IDS / 8]; } gf_ids;
typedef struct {
    int pct;                                   // 0 off, 100 the highest clock, 2-99 a floor at that share of it (where the GMU takes it)
    int host;                                  // the kernel took no scaled level: the highest clock is sent instead
    int nwas, wasfd[GF_FDS]; gf_ids was[GF_FDS];   // the descriptors before vkCreateDevice, and the contexts each owned then
    int n; struct { int fd; unsigned id; } ctx[GF_CTX];   // the device's contexts
    uint64_t sent, refused; int last;          // calls taken and refused, the last refusal's -errno
} gf_state;

// DM_VK_GPU_FLOOR's value: 0 (unset, empty, not a number, 0 or less) to 100
static int gf_pct(const char *v) {
    if (!v || !*v) return 0;
    char *end; long p = strtol(v, &end, 10); if (end == v) return 0;
    return p < 0 ? 0 : p > 100 ? 100 : (int)p;
}

// The level a context is sent: KGSL_CONSTRAINT_PWR_MAX for 100 or where only that is taken, else the share (at least 2: 1 would read as the maximum, 0 as the minimum)
static unsigned gf_level(int pct, int host) { return pct >= 100 || host ? GF_LEVEL_MAX : (unsigned)(pct < 2 ? 2 : pct); }

static int gf_has(const gf_ids *s, unsigned id) { return s->bit[id / 8] >> (id % 8) & 1; }

// The contexts descriptor fd owns
static void gf_owned(gf_set_fn set, int fd, gf_ids *own) {
    memset(own, 0, sizeof *own);
    for (unsigned id = 1; id < GF_IDS; id++) if (!set(fd, id, GF_CONSTRAINT_NONE, 0)) own->bit[id / 8] |= (uint8_t)(1u << (id % 8));
}

// Before vkCreateDevice: the process's KGSL descriptors (fd[0..nfd)) and what they own. Off (pct 0): nothing is asked
static void gf_before(gf_state *s, gf_set_fn set, const int *fd, int nfd) {
    s->nwas = 0; s->n = 0; if (!s->pct) return;
    for (int i = 0; i < nfd && i < GF_FDS; i++) { s->wasfd[s->nwas] = fd[i]; gf_owned(set, fd[i], &s->was[s->nwas]); s->nwas++; }
}

// The floor sent to every context of the device's: 0, or the last refusal's -errno
static int gf_apply(gf_state *s, gf_set_fn set) {
    int bad = 0; unsigned lv = gf_level(s->pct, s->host);
    for (int k = 0; k < s->n; k++) { int r = set(s->ctx[k].fd, s->ctx[k].id, GF_CONSTRAINT_PWRLEVEL, lv); if (r) { bad = r; s->refused++; } else s->sent++; }
    if (bad) s->last = bad;
    return bad;
}

// After vkCreateDevice: the contexts the descriptors own now and did not before, the level form the kernel takes (a scaled level on the first, then cleared), and the floor
// sent. → the device's contexts found (0: none, nothing sent); s->last says whether the kernel took it. Off: nothing is asked
static int gf_after(gf_state *s, gf_set_fn set, const int *fd, int nfd) {
    s->n = 0; s->host = 0; s->last = 0; if (!s->pct) return 0;
    for (int i = 0; i < nfd && i < GF_FDS; i++) {
        gf_ids now, *was = NULL; gf_owned(set, fd[i], &now);
        for (int j = 0; j < s->nwas; j++) if (s->wasfd[j] == fd[i]) was = &s->was[j];
        for (unsigned id = 1; id < GF_IDS && s->n < GF_CTX; id++)
            if (gf_has(&now, id) && !(was && gf_has(was, id))) { s->ctx[s->n].fd = fd[i]; s->ctx[s->n].id = id; s->n++; }
    }
    if (!s->n) return 0;
    s->host = set(s->ctx[0].fd, s->ctx[0].id, GF_CONSTRAINT_PWRLEVEL, GF_PROBE) == -EINVAL;
    set(s->ctx[0].fd, s->ctx[0].id, GF_CONSTRAINT_NONE, 0);
    gf_apply(s, set);
    return s->n;
}
