#!/usr/bin/env python3
# The commit and version the Android host is built from, for the line it logs at start (dm/host/main.c, through dm/android/build_stamp.c):
# `build: commit c6920f36abcd (v0.8.4), shader chain …`. Android has no Info.plist to carry the Mac's DMCommit, so every Android log said "commit not recorded"
# and a report's version had to be dated from its times (droidplay-core#389).
# CMake runs this at every build (dm/android/CMakeLists.txt, build_stamp), and it rewrites the header only when the stamp changes, so only build_stamp.c recompiles.
# A checkout asks git: HEAD's short hash, +dirty with uncommitted changes to tracked files (as dm/mac/pack_app.py stamps DMCommit), and git describe. A release's
# source archive (release-assets.yml) or DroidPlay for Windows' staged tree (stage.ps1) has no .git: it carries VERSION, and build_commit beside this script,
# which git archive fills in with the commit (export-subst in .gitattributes here).
# Usage: build_stamp.py <header>
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ARCHIVED = Path('dm/android/tools/build_commit')   # `$Format:%H$` in a checkout, the commit in an archive made by git archive


def git(repo, *args):   # git's output in repo, or None (no git, not a checkout, or a checkout git refuses)
    try: r = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, text=True, timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired): return None
    return r.stdout.strip() if r.returncode == 0 else None


def stamp(repo=REPO):   # '<12-hex commit>[+dirty] (<version>)', either part alone, or 'not recorded'
    v = (repo / 'VERSION').read_text(encoding='utf-8', errors='replace').strip() if (repo / 'VERSION').is_file() else ''
    version = ('v' + v.removeprefix('v')) if v else None   # a release's VERSION is 0.8.4, its tag v0.8.4
    archived = (repo / ARCHIVED).read_text(encoding='utf-8', errors='replace').strip() if (repo / ARCHIVED).is_file() else ''
    if re.fullmatch(r'[0-9a-f]{40}', archived): commit = archived[:12]   # an archive: the commit it was made from
    elif (top := git(repo, 'rev-parse', '--show-toplevel')) and Path(top).resolve() == repo.resolve():   # this folder's checkout, not one it was unpacked into
        commit = git(repo, 'rev-parse', '--short=12', 'HEAD')
        if commit and git(repo, 'status', '--porcelain', '--untracked-files=no'): commit += '+dirty'
        version = version or git(repo, 'describe', '--tags')   # v0.8.4 on the tag, v0.8.4-12-g<hash> after it; none without tags (a shallow clone)
    else: commit = None
    s = f'{commit} ({version})' if commit and version else commit or (f'not recorded ({version})' if version else 'not recorded')
    return re.sub(r'[^0-9A-Za-z .+()_/-]', '?', s)   # the header's C string: no quotes or backslashes from a tag's name


def header(s):
    return f'// Written at every build by dm/android/tools/build_stamp.py: the commit and version this host is built from\n#define DM_BUILD_COMMIT "{s}"\n'


def main(argv):
    if len(argv) != 2: print('usage: build_stamp.py <header>', file=sys.stderr); return 2
    out = Path(argv[1]); text = header(stamp())
    if not out.is_file() or out.read_text(encoding='utf-8', errors='replace') != text:   # unchanged: left alone, so nothing recompiles
        out.parent.mkdir(parents=True, exist_ok=True); out.write_text(text, encoding='utf-8', newline='\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
