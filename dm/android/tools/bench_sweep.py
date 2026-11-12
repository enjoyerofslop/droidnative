"""Save sweeps for scripts/bench_android.py: scene routes that start from saves people downloaded (late-game places a scripted route from a new game never
reaches), run in one go per game, with one summary table per phone and a comparison against an earlier sweep.

A downloaded save usually comes as the archive it was shared in (JKSV, Checkpoint or EdiZon folders, or the save's files bare), kept as it is in the game's
saves/ folder. A route names the archive, and the folder inside it that holds the save's own files, after '//':
    saves/dl-100pct/<archive>.zip//<folder inside the archive>
It is unpacked into the run's output folder (zip by Python, or by Info-ZIP's unzip for Deflate64; other archives by bsdtar, macOS's and Windows 10's tar),
so the user's folder is only read.
Sweeps are for regressions, performance and coverage: a downloaded save never moves a game up a tier (dm/android/README.md, Save sweeps)."""
import fnmatch
import json
import re
import shutil
import subprocess
import zipfile
from pathlib import Path
from typing import Any

ARCHIVES = ('.zip', '.rar', '.7z', '.tar', '.tgz', '.gz')
FPS_DROP = 0.05   # a route's fps this much under the earlier sweep's is flagged


def pick_routes(routes, patterns):   # the routes whose names match any of the comma-separated shell patterns, in the file's order
    pats = [p.strip() for p in patterns.split(',') if p.strip()]
    return [r for r in routes if any(fnmatch.fnmatchcase(r['name'], p) for p in pats)]


def save_dir(spec, folder, cache):   # the folder of a route's save, beside the NSP folder or in its parent; an archive is unpacked into cache first
    path, _, inner = spec.partition('//')
    src = next((p for p in (Path(folder) / path, Path(folder).parent / path) if p.exists()), None)
    if src is None: raise FileNotFoundError(f'no save {path} beside {folder}')
    if src.is_dir():
        if inner: raise ValueError(f'save {spec}: a path inside is only for an archive')
        return src
    if src.suffix.lower() not in ARCHIVES: raise ValueError(f'save {spec}: not a folder or an archive ({", ".join(ARCHIVES)})')
    st = src.stat(); dst = Path(cache) / re.sub(r'[^\w.-]+', '_', f'{src.parent.name}-{src.stem}-{st.st_size}-{int(st.st_mtime)}')
    if not (dst / '.unpacked').exists():
        shutil.rmtree(dst, ignore_errors=True); dst.mkdir(parents=True)
        done = False
        if src.suffix.lower() == '.zip':
            with zipfile.ZipFile(src) as z:
                for m in z.infolist():   # no member may land outside dst
                    if Path(m.filename).is_absolute() or '..' in Path(m.filename).parts: raise ValueError(f'{src.name}: unsafe member {m.filename}')
                try: z.extractall(dst); done = True
                except NotImplementedError: shutil.rmtree(dst); dst.mkdir()   # a method zipfile lacks: Breath of the Wild's save is Deflate64, which bsdtar lacks too
            if not done and shutil.which('unzip'):   # Info-ZIP's unzip reads Deflate64 (macOS's, most Linux)
                subprocess.run(['unzip', '-q', '-o', str(src), '-d', str(dst)], check=True, capture_output=True); done = True
        if not done:
            tar = shutil.which('bsdtar') or shutil.which('tar')
            if not tar: raise FileNotFoundError(f'{src.name}: no bsdtar or tar to unpack it')
            subprocess.run([tar, '-xf', str(src), '-C', str(dst)], check=True, capture_output=True)
        (dst / '.unpacked').write_text(str(src), encoding='utf-8')
    out = dst / inner if inner else dst
    if not out.is_dir(): raise FileNotFoundError(f'save {spec}: no folder {inner or "."} in {src.name}')
    return out


def red_kinds(log_text):   # {kind: count}: the host log's red lines, with numbers and addresses made alike so one kind counts once however often it repeats
    kinds: dict[str, int] = {}
    for line in log_text.splitlines():
        if '[RED]' not in line: continue
        k = re.sub(r'0x[0-9a-fA-F]+|\b[0-9a-f]{12,16}\b|\d+(\.\d+)?', 'N', line.split('[RED]', 1)[1].strip())[:160]
        kinds[k] = kinds.get(k, 0) + 1
    return kinds


def summarize(results):   # one row per phone and route: its last measured run (a warm-up is kept only when it is all there is)
    rows: dict[tuple[str, str, str], dict[str, Any]] = {}
    for r in results:
        key = (r['serial'], r['game'], r['route'])
        if key not in rows or r['run'] >= rows[key]['run']: rows[key] = r
    return [{k: r.get(k) for k in ('serial', 'game', 'route', 'run', 'ready_s', 'first_frame_s', 'fps', 'frame_p50', 'frame_p95', 'gpu_p50', 'pss_mb', 'exit',
                                    'died_at_s', 'red_kinds', 'shot', 'dir')} for r in rows.values()]


def compare(rows, earlier, fps_drop=FPS_DROP):   # {(serial, game, route): [flags]} against an earlier sweep's rows: the fps fell, new red kinds, a crash or kill
    old = {(r['serial'], r['game'], r['route']): r for r in earlier}
    flags = {}
    for r in rows:
        key = (r['serial'], r['game'], r['route']); o = old.get(key); f = []
        if r.get('exit') and not (o or {}).get('exit'): f.append(f"ended: {r['exit']}")
        if o is None: f.append('new route')
        else:
            if r.get('fps') is not None and o.get('fps') and r['fps'] < o['fps'] * (1 - fps_drop): f.append(f"fps {o['fps']} → {r['fps']}")
            new = sorted(set(r.get('red_kinds') or {}) - set(o.get('red_kinds') or {}))
            if new: f.append(f'{len(new)} new red kind{"s" * (len(new) > 1)}')
        flags[key] = f
    return flags


def regressions(flags):   # the flags that call for a look ('new route' alone doesn't)
    return {k: v for k, v in flags.items() if [x for x in v if x != 'new route']}


def table(rows, names, flags=None, base=None):   # markdown: one table per phone; screenshot paths relative to base (sweep.md's folder) when inside it
    def f(v): return '–' if v is None else str(v)
    def shot(v):
        if v and base:
            try: return str(Path(v).relative_to(base))
            except ValueError: pass
        return f(v)
    out = []
    for serial in sorted({r['serial'] for r in rows}):
        out += [f'### {names.get(serial, serial)}', '',
                '| Route | Load to scene s | FPS | Frame p50 / p95 ms | GPU p50 ms | PSS MB | Red lines (kinds) | Ended | Flags | Screenshot |',
                '|---|---|---|---|---|---|---|---|---|---|']
        for r in sorted((r for r in rows if r['serial'] == serial), key=lambda r: (r['game'], r['route'])):
            reds = r.get('red_kinds') or {}
            fl = (flags or {}).get((r['serial'], r['game'], r['route']), [])
            out.append(f"| {r['route']} | {f(r.get('ready_s'))} | {f(r.get('fps'))} | "
                       f"{f(r.get('frame_p50'))} / {f(r.get('frame_p95'))} | {f(r.get('gpu_p50'))} | {f(r.get('pss_mb'))} | {sum(reds.values())} ({len(reds)}) | "
                       f"{r.get('exit') or 'ran'} | {'; '.join(fl) or '–'} | {shot(r.get('shot'))} |")
        out.append('')
    return '\n'.join(out)


def load(path):   # an earlier sweep's rows: its sweep.json, or the folder holding it
    p = Path(path); p = p / 'sweep.json' if p.is_dir() else p
    return json.loads(p.read_text(encoding='utf-8'))['rows']


def write(out, rows, names, earlier=None):   # sweep.json and sweep.md in out; → the regressions found against earlier
    flags = compare(rows, earlier) if earlier is not None else None
    Path(out, 'sweep.json').write_text(json.dumps({'rows': rows, 'flags': {'\t'.join(k): v for k, v in (flags or {}).items()}}, indent=1), encoding='utf-8')
    reg = regressions(flags) if flags else {}
    head = [f'# Save sweep', '', (f'{len(reg)} route(s) flagged against the earlier sweep.' if flags is not None else 'No earlier sweep to compare with.'), '']
    Path(out, 'sweep.md').write_text('\n'.join(head) + table(rows, names, flags, Path(out)) + '\n', encoding='utf-8')
    return reg
