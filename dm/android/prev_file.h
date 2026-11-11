// The previous start's log and dumps, kept beside the new ones. A start truncates log.txt (front_android.c log_reader) and the files DM_NVN_TSV and DM_AUDIO_DUMP name
// (hle_nvn.c, hle_audio.c open them "w"), and a start that follows a kill (lmkd, a crash, Android recreating the game's task) took the killed run's evidence with it:
// Ocarina of Time on a Galaxy Z Fold 8, killed for memory and opened again by the launcher. So before they are opened, each goes to <name>.prev<extensions>
// (log.txt → log.prev.txt, bench_frames.tsv → bench_frames.prev.tsv), over the one before. Plain libc, for dm/tools/tests/test_prev_file.py.
#pragma once
#include <stdio.h>
#include <string.h>
#include <sys/stat.h>

// path's previous-run name in out: ".prev" before the first dot of the file name, or at its end when it has none. 0 when out is too small
static int prev_name(const char *path, char *out, size_t n) {
    const char *base = strrchr(path, '/'); base = base ? base + 1 : path;
    const char *dot = strchr(base, '.'); size_t at = dot ? (size_t)(dot - path) : strlen(path);
    int k = snprintf(out, n, "%.*s.prev%s", (int)at, path, path + at);
    return k > 0 && (size_t)k < n;
}

// path moved to its previous-run name when it exists (an older one there is replaced): 1 when moved
static int keep_prev(const char *path) {
    struct stat st; char prev[1024];
    if (!path || !*path || stat(path, &st) || !S_ISREG(st.st_mode) || !prev_name(path, prev, sizeof prev)) return 0;
    return rename(path, prev) == 0;
}
