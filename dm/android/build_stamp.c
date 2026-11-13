// The commit and version this host is built from, for the build: line it logs at start (main.c): Android has no Info.plist to carry it, as the Mac app's DMCommit does.
// The header is written at every build by tools/build_stamp.py, only when it changes, so only this file recompiles for a new commit
#include "build_stamp.h"
const char *dm_build_commit(void) { return DM_BUILD_COMMIT; }
