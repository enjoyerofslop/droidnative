// The start-up list's guard against a pipeline whose compile never finishes. The list (<DM_PIPELINE_CACHE>.keys4, gfx_vk_draw.inc prewarm_thread) makes the pipelines of
// earlier sessions again at every start, so an entry the driver's shader compiler crashes on kills every start a few seconds in, and nothing a player can do clears it.
// Before each compile the prewarm writes the entry to a marker file (<cache>.making4) and empties the file after; a crash in that compile also flags it (pb_dump, the crash
// dump's graphics hook). An entry still in the marker at the next start goes to the skip list (<cache>.skip4), which the prewarm leaves out from then on.
// Plain POSIX file calls on whole records of the caller's size, for dm/tools/tests/test_pk_guard.py.
#pragma once
#include <fcntl.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

enum { PKG_BUSY = '0', PKG_CRASHED = 'C' };   // the byte after the record: being compiled; the crash hook's flag

// The marker of this session, emptied: its descriptor, or -1
static int pkg_open(const char *path) { return open(path, O_RDWR | O_CREAT | O_TRUNC | O_CLOEXEC, 0600); }

// An entry about to be compiled: its record, then the busy byte (a record without that byte, written by a start that ended between the two, counts as busy)
static void pkg_begin(int fd, const uint8_t *rec, size_t n) {
    if (fd < 0) return;
    char b = PKG_BUSY; if (pwrite(fd, rec, n, 0) == (ssize_t)n) (void)!pwrite(fd, &b, 1, (off_t)n);
}

// Its compile returned
static void pkg_end(int fd) { if (fd >= 0) (void)!ftruncate(fd, 0); }

// From the crash handler, on the compiling thread: one write, which is async-signal-safe
static void pkg_crashed(int fd, size_t n) { if (fd >= 0) { char b = PKG_CRASHED; (void)!pwrite(fd, &b, 1, (off_t)n); } }

// What an earlier start left in the marker: 1 with the record in rec (and *crashed when the crash hook flagged it), 0 when it was empty or held less than a record.
// The marker is removed either way, so one entry is taken once
static int pkg_take(const char *path, uint8_t *rec, size_t n, int *crashed) {
    *crashed = 0; int fd = open(path, O_RDONLY | O_CLOEXEC); if (fd < 0) return 0;
    char b = 0; ssize_t got = pread(fd, rec, n, 0); int whole = got == (ssize_t)n;
    if (whole && pread(fd, &b, 1, (off_t)n) == 1) *crashed = b == PKG_CRASHED;
    close(fd); unlink(path);
    return whole;
}

// The skip list's records (whole ones only), in a buffer the caller frees: their count
static size_t pkg_skip_load(const char *path, size_t n, uint8_t **out) {
    *out = NULL; int fd = open(path, O_RDONLY | O_CLOEXEC); if (fd < 0) return 0;
    off_t len = lseek(fd, 0, SEEK_END); size_t cnt = len > 0 ? (size_t)len / n : 0;
    if (cnt) { *out = malloc(cnt * n); if (!*out || pread(fd, *out, cnt * n, 0) != (ssize_t)(cnt * n)) { free(*out); *out = NULL; cnt = 0; } }
    close(fd); return cnt;
}

// A record added to the skip list unless it is there already: 1 when added. It goes after the last whole record, so a part record a start left at the end is overwritten
static int pkg_skip_add(const char *path, const uint8_t *rec, size_t n) {
    uint8_t *all; size_t cnt = pkg_skip_load(path, n, &all);
    for (size_t i = 0; i < cnt; i++) if (!memcmp(all + i * n, rec, n)) { free(all); return 0; }
    free(all);
    int fd = open(path, O_RDWR | O_CREAT | O_CLOEXEC, 0600); if (fd < 0) return 0;
    off_t at = (off_t)(cnt * n); int ok = ftruncate(fd, at) == 0 && pwrite(fd, rec, n, at) == (ssize_t)n; close(fd); return ok;
}
