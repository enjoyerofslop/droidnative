#!/usr/bin/env python3
# Baseline runs of games on Android devices over adb: the same save, the same scripted input and the same measuring window on every device, so devices and builds
# compare. The Android counterpart of scripts/bench.py (the Mac host's).
#   python3 scripts/bench_android.py <NSP folder> [<NSP folder> ...] [-s <serial> ...] [--route <name>] [--runs N] [--install [-k <prod.keys>]] [--out <folder>] [--env KEY=VALUE]
#   An NSP folder is the one build_android_from_nsp.py packed (it holds <title ID>_build). Without -s, every device adb lists as ready. --install copies the app and the
#   game to each device first (build_android_from_nsp.py --push-only). Games run in turn, each on every device in turn, each run --runs times (default 2),
#   after a warm-up run with --warmup (run 0, reported apart: the first launch after an install builds the driver's pipelines). Install before a run, never during one.
# A route is a line of the game's dm/games/<id>/bench_android.tsv (the first by default; without the file, `boot`: no input, no save, measured from 20 to 50 s):
#   name <TAB> DM_KEYS or - <TAB> save or - <TAB> window start s <TAB> window length s <TAB> ready pattern or - <TAB> description
#   save: a save folder beside the NSP folder or in its parent (the game's folder); each run gets a fresh copy in the app's external files (DM_SAVE points there), so
#   the device's own saves are not touched. ready: a regular expression on the host's log whose first match marks the game ready (its title, say); its time is reported.
# Each run: cool down (thermal status 0 and the battery at or under --cool-temp, up to --cool-max s), env.txt with DM_SAVE, DM_KEYS and per-frame timing (DM_NVN_TSV), the
# game started from the launcher, screenshots at the window's start and end, and the game stopped. env.txt as it was is put back after the run.
# Devices stay awake: every 45 s each one gets KEYCODE_WAKEUP (wakes a screen that went dark, does nothing to one that is on, and never turns it off, unlike POWER),
# and the lock screen is dismissed before each start. A PIN or pattern lock cannot be dismissed over adb: set the test devices' screen lock to None or Swipe.
# Out: <out>/<device>/<title ID>_<route>_r<N>/ (logcat.txt, log.txt, frames.tsv, the screenshots, result.json), and results.json and results.md for all runs.
# Default <out>: bench/<date-time> in build_android_from_nsp.py's data folder (~/.local/share/nxnative/android on a Mac or Linux), beside its builds journal.
import argparse, datetime, json, math, os, re, shutil, subprocess, sys, threading, time
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PKG = 'org.nxnative.android'
EXT = f'/storage/emulated/0/Android/data/{PKG}/files'
GAME_PROC = PKG + ':game'
TSV = f'{EXT}/bench_frames.tsv'   # the per-frame timing (DM_NVN_TSV)
ADB = shutil.which('adb') or str(Path(os.environ.get('ANDROID_HOME', Path.home() / 'Library/Android/sdk')) / 'platform-tools/adb')
TIMING = ('@t_s', '@frame_ms', '@gpu_ms', '@work_ms', '@draws')


def data_dir():   # build_android_from_nsp.py's: the library of game hosts, its builds journal, and these results
    base = Path(os.environ['LOCALAPPDATA']) if os.name == 'nt' and os.environ.get('LOCALAPPDATA') else Path.home() / '.local/share'
    return base / 'nxnative' / 'android'


def adb_bytes(serial, *args, timeout=120) -> bytes:
    return subprocess.run([ADB, '-s', serial, *args], capture_output=True, timeout=timeout).stdout


def adb(serial, *args, timeout=120) -> str:
    return adb_bytes(serial, *args, timeout=timeout).decode(errors='replace')


def sh(serial, cmd, timeout=60) -> str:
    return adb(serial, 'shell', cmd, timeout=timeout)


def ready_devices():
    out = subprocess.run([ADB, 'devices'], capture_output=True, text=True).stdout.splitlines()[1:]
    return [line.split()[0] for line in out if len(line.split()) > 1 and line.split()[1] == 'device']


def device_info(serial):
    props = dict(re.findall(r'^\[([^\]]+)\]: \[([^\]]*)\]', sh(serial, 'getprop'), re.M))
    mem = re.search(r'MemTotal:\s+(\d+)', sh(serial, 'cat /proc/meminfo'))
    gles = re.search(r'GLES: ([^\n]+)', sh(serial, 'dumpsys SurfaceFlinger | grep -m1 GLES:'))
    return {'serial': serial, 'maker': props.get('ro.product.manufacturer', ''), 'model': props.get('ro.product.model', ''),
            'soc': props.get('ro.soc.model') or props.get('ro.board.platform', ''), 'android': props.get('ro.build.version.release', ''),
            'sdk': props.get('ro.build.version.sdk', ''), 'ram_gb': round(int(mem.group(1)) / 1048576, 1) if mem else None,
            'gles': gles.group(1).strip() if gles else ''}


def thermal(serial):   # → (thermal status, battery °C)
    st = re.search(r'Thermal Status: (\d+)', sh(serial, 'dumpsys thermalservice'))
    bt = re.search(r'temperature: (\d+)', sh(serial, 'dumpsys battery'))
    return (int(st.group(1)) if st else None, int(bt.group(1)) / 10 if bt else None)


def cool_down(serial, temp, most):   # → seconds waited
    t0 = time.time()
    while time.time() - t0 < most:
        st, bt = thermal(serial)
        if (st or 0) == 0 and (bt is None or bt <= temp): break
        time.sleep(15)
    return round(time.time() - t0)


class KeepAwake(threading.Thread):
    def __init__(self, serials):
        super().__init__(daemon=True); self.serials = serials; self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            for s in self.serials:
                try: sh(s, 'input keyevent KEYCODE_WAKEUP', timeout=15)
                except subprocess.TimeoutExpired: pass
            self.stop.wait(45)


def routes(gid):
    f = REPO / 'dm/games' / gid / 'bench_android.tsv'
    out = []
    if f.is_file():
        for line in f.read_text(encoding='utf-8').splitlines():
            if not line.strip() or line.startswith('#'): continue
            c = line.split('\t') + ['-'] * 7
            out.append({'name': c[0], 'keys': '' if c[1] == '-' else c[1], 'save': '' if c[2] == '-' else c[2], 'start': float(c[3]), 'length': float(c[4]),
                        'ready': '' if c[5] == '-' else c[5], 'about': '' if c[6] == '-' else c[6]})
    return out or [{'name': 'boot', 'keys': '', 'save': '', 'start': 20.0, 'length': 30.0, 'ready': '', 'about': 'no input, no save'}]


def game_of(folder):   # → (title ID, game record)
    builds = sorted(Path(folder).glob('*_build/android_game.json'))
    if not builds: sys.exit(f'{folder}: no <title ID>_build/android_game.json (pack the game with build_android_from_nsp.py first)')
    g = json.loads(builds[0].read_text(encoding='utf-8'))
    return g['title_id'].upper(), g


def pct(xs, p):   # nearest rank
    if not xs: return None
    s = sorted(xs); return round(s[min(len(s) - 1, max(0, math.ceil(p / 100 * len(s)) - 1))], 2)


def frames(tsv):   # → {frame: {name: value}}
    rows = {}
    for line in tsv.splitlines():
        c = line.split('\t')
        if len(c) == 3 and c[1] in TIMING:
            try: rows.setdefault(int(c[0]), {})[c[1]] = float(c[2])
            except ValueError: pass
    return rows


def window_stats(rows, start, length):
    w = [r for r in rows.values() if '@t_s' in r and start <= r['@t_s'] < start + length]
    ft = [r['@frame_ms'] for r in w if '@frame_ms' in r]
    gpu = [r['@gpu_ms'] for r in w if '@gpu_ms' in r]
    return {'frames': len(w), 'fps': round(len(w) / length, 1) if length else None, 'frame_p50': pct(ft, 50), 'frame_p95': pct(ft, 95), 'frame_p99': pct(ft, 99),
            'frame_max': round(max(ft), 1) if ft else None, 'over_17ms_pct': round(100 * sum(x > 17.5 for x in ft) / len(ft), 1) if ft else None,
            'over_34ms_pct': round(100 * sum(x > 34 for x in ft) / len(ft), 1) if ft else None, 'gpu_p50': pct(gpu, 50), 'gpu_p95': pct(gpu, 95),
            'draws_p50': pct([r['@draws'] for r in w if '@draws' in r], 50)}


def log_facts(logcat, ready):
    def epoch(line): m = re.match(r'\s*(\d+\.\d+)', line); return float(m.group(1)) if m else None
    # shift: add to the host's times (@t_s, the log's [N s]) to make them seconds from the launch. The host counts from its process's start, and Android 16 starts
    # app processes ahead of use (the OnePlus Pad 3's ran 83 s early), so a line holding both clocks (an fs open, DM_FS=1) gives the offset to ActivityManager's start
    lines = logcat.splitlines(); start = None; out: dict[str, Any] = {'ready_s': None, 'exit': None, 'vulkan': None, 'resident_mb': None, 'shift': 0.0}; anchored = False
    for line in lines:
        if start is None and 'Start proc' in line and GAME_PROC in line: start = epoch(line)
        m = re.search(r'\[dm\] vulkan: (.+)$', line)
        if m: out['vulkan'] = m.group(1).strip()
        m = re.search(r'\[vk\] frame \d+: resident (\d+) MB', line)
        if m: out['resident_mb'] = int(m.group(1))
        t = epoch(line)
        m = re.search(r'fs open \[([0-9.]+)s\]', line)
        if m and not anchored and start is not None and t is not None: out['shift'] = round(t - float(m.group(1)) - start, 3); anchored = True
        if ready and out['ready_s'] is None and start is not None and t is not None and re.search(ready, line): out['ready_s'] = round(t - start, 2)
        if 'Fatal signal' in line and out['exit'] is None: out['exit'] = 'crash: ' + line.split('Fatal signal', 1)[1].strip()[:120]
        m = re.search(r'Process \d+ exited cleanly \((\d+)\)', line)
        if m and out['exit'] is None: out['exit'] = 'exit ' + m.group(1) + (' (svcBreak: the game aborted)' if m.group(1) == '42' else '')
        if re.search(r'lowmemorykiller|lmkd.*Kill.*' + re.escape(GAME_PROC), line) and out['exit'] is None: out['exit'] = 'killed for memory'
    return out


def run_one(serial, folder, gid, route, n, out, args):
    d = out / f'{gid}_{route["name"]}_r{n}'; d.mkdir(parents=True, exist_ok=True)
    sh(serial, f'am force-stop {PKG}')
    waited = cool_down(serial, args.cool_temp, args.cool_max)
    st0, bt0 = thermal(serial)
    env_before = sh(serial, f'cat {EXT}/env.txt 2>/dev/null')
    env = ['# written by scripts/bench_android.py for a benchmark run; put back as it was when the run ends', f'DM_SAVE={EXT}/bench/save/{gid}',
           f'DM_NVN_TSV={TSV}', 'DM_NVN_TSV_CALLS=0', 'DM_FS=1'] + ([f'DM_KEYS={route["keys"]}'] if route['keys'] else []) + args.env   # DM_FS: file opens in the log, for ready patterns
    sh(serial, f'rm -rf {EXT}/bench && mkdir -p {EXT}/bench/save')
    if route['save']:
        src = next((p for p in (Path(folder) / route['save'], Path(folder).parent / route['save']) if p.is_dir()), None)
        if not src: sys.exit(f'route {route["name"]}: no save folder {route["save"]} beside {folder}')
        adb(serial, 'push', str(src), f'{EXT}/bench/save/', timeout=300); sh(serial, f'mv {EXT}/bench/save/{src.name} {EXT}/bench/save/{gid}')
    # The save copy is made by adb's shell user, which the game cannot write to on an enforcing device (Android 16 on the OnePlus Pad 3): opened to all, as
    # build_android_from_nsp.py opens games/. The timing file goes in files/ itself: what the game makes in a folder of the shell's has the app's own group, which
    # the shell cannot read, and in files/ it has ext_data_rw (setgid there; a chmod does not set it on this storage)
    sh(serial, f'chmod -R 777 {EXT}/bench; rm -f {TSV}')
    adb(serial, 'push', str(write_tmp(d / 'env.txt', '\n'.join(env) + '\n')), f'{EXT}/env.txt')
    adb(serial, 'logcat', '-c')
    with open(d / 'logcat.txt', 'wb') as lf:
        lc = subprocess.Popen([ADB, '-s', serial, 'logcat', '-v', 'epoch', 'nxnative:V', 'ActivityManager:I', 'Zygote:I', 'DEBUG:V', 'libc:F', 'lmkd:I', '*:S'], stdout=lf)
        sh(serial, 'input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard')
        t0 = time.time()
        sh(serial, f'am start -n {PKG}/.Launcher --es game {gid} --ez play true')
        shots = {route['start']: 'start', route['start'] + route['length']: 'end'}; died = None; pss = None
        end = route['start'] + route['length'] + 3
        while time.time() - t0 < end:
            time.sleep(1); el = time.time() - t0
            for at, name in list(shots.items()):
                if el >= at: (d / f'shot_{name}.png').write_bytes(adb_bytes(serial, 'exec-out', 'screencap', '-p')); del shots[at]
            if pss is None and el >= route['start'] + route['length'] - 2:
                m = re.search(r'TOTAL PSS:\s+(\d+)|TOTAL\s+(\d+)', sh(serial, f'dumpsys meminfo {GAME_PROC}')); pss = int(m.group(1) or m.group(2)) // 1024 if m else None
            if el > 15 and not sh(serial, f'pidof {GAME_PROC}').strip(): died = round(el, 1); break
        st1, bt1 = thermal(serial)
        sh(serial, f'am force-stop {PKG}'); time.sleep(1); lc.terminate()
    (d / 'frames.tsv').write_bytes(adb_bytes(serial, 'exec-out', f'cat {TSV}'))
    (d / 'log.txt').write_bytes(adb_bytes(serial, 'exec-out', f'cat {EXT}/log.txt'))
    if env_before.strip(): adb(serial, 'push', str(write_tmp(d / 'env_before.txt', env_before)), f'{EXT}/env.txt')
    else: sh(serial, f'rm -f {EXT}/env.txt')
    facts = log_facts((d / 'logcat.txt').read_text(errors='replace'), route['ready'])
    rows = frames((d / 'frames.tsv').read_text(errors='replace'))
    for r in rows.values():
        if '@t_s' in r: r['@t_s'] += facts['shift']
    first = min((r['@t_s'] for r in rows.values() if '@t_s' in r), default=None)
    res = {'serial': serial, 'game': gid, 'route': route['name'], 'run': n, 'first_frame_s': round(first, 2) if first is not None else None, **facts,
           **window_stats(rows, route['start'], route['length']), 'pss_mb': pss, 'died_at_s': died, 'cooled_s': waited,
           'thermal': [st0, st1], 'battery_c': [bt0, bt1]}
    if died and not res['exit']: res['exit'] = f'stopped at {died} s'
    (d / 'result.json').write_text(json.dumps(res, indent=1), encoding='utf-8')
    return res


def write_tmp(p, text):
    p.write_text(text, encoding='utf-8'); return p


def report(out, devices, results):
    (out / 'results.json').write_text(json.dumps({'devices': devices, 'runs': results}, indent=1), encoding='utf-8')
    names = {d['serial']: f"{d['maker']} {d['model']}" for d in devices}
    def f(v): return '–' if v is None else str(v)
    lines = ['| Device | Game | Route | Run | First frame s | Ready s | FPS | Frame p50 / p95 / p99 ms | > 17.5 ms % | > 34 ms % | GPU p50 ms | PSS MB | Battery °C | Exit |',
             '|---|---|---|---|---|---|---|---|---|---|---|---|---|---|']
    for r in results:
        lines.append(f"| {names.get(r['serial'], r['serial'])} | {r['game']} | {r['route']} | {r['run'] or 'warm-up'} | {f(r['first_frame_s'])} | {f(r['ready_s'])} | {f(r['fps'])} | "
                     f"{f(r['frame_p50'])} / {f(r['frame_p95'])} / {f(r['frame_p99'])} | {f(r['over_17ms_pct'])} | {f(r['over_34ms_pct'])} | {f(r['gpu_p50'])} | "
                     f"{f(r['pss_mb'])} | {f(r['battery_c'][0])} → {f(r['battery_c'][1])} | {r['exit'] or 'ran'} |")
    dev = ['', '| Device | SoC | Android | RAM GB | Vulkan (from the host) |', '|---|---|---|---|---|']
    for d in devices:
        vk = next((r['vulkan'] for r in results if r['serial'] == d['serial'] and r.get('vulkan')), None) or d['gles']
        dev.append(f"| {names[d['serial']]} | {d['soc']} | {d['android']} | {f(d['ram_gb'])} | {vk} |")
    (out / 'results.md').write_text('\n'.join(lines + dev) + '\n', encoding='utf-8')


def main():
    ap = argparse.ArgumentParser(description='Baseline runs of games on Android devices over adb (see the comment at the top)')
    ap.add_argument('folders', nargs='+', help='NSP folders packed by build_android_from_nsp.py')
    ap.add_argument('-s', '--serial', action='append', help='an adb device (repeatable; default: every ready one)')
    ap.add_argument('--route', help="a route name of the game's bench_android.tsv (default: its first)")
    ap.add_argument('--runs', type=int, default=2); ap.add_argument('--install', action='store_true', help='build_android_from_nsp.py --push-only to each device first')
    ap.add_argument('-k', '--keys', default=str(Path.home() / '.switch/prod.keys'), help='prod.keys for --install (default ~/.switch/prod.keys)')
    ap.add_argument('--warmup', action='store_true', help='a warm-up run (run 0) before the measured ones, reported apart: the first launch after an install builds pipelines')
    ap.add_argument('--out'); ap.add_argument('--env', action='append', default=[], help='KEY=VALUE for every run (repeatable)')
    ap.add_argument('--cool-temp', type=float, default=38.0, help='start a run once the battery is at or under this many °C (default 38)')
    ap.add_argument('--cool-max', type=int, default=300, help='wait at most this many seconds to cool down (default 300)')
    args = ap.parse_args()
    serials = args.serial or ready_devices()
    if not serials: sys.exit('no adb device ready')
    out = Path(args.out or data_dir() / 'bench' / datetime.datetime.now().strftime('%Y%m%d-%H%M%S')); out.mkdir(parents=True, exist_ok=True)
    devices = [device_info(s) for s in serials]
    for d in devices: print(f"device {d['serial']}: {d['maker']} {d['model']}, {d['soc']}, Android {d['android']}, {d['ram_gb']} GB", flush=True)
    awake = KeepAwake(serials); awake.start(); results = []
    try:
        for folder in args.folders:
            gid, g = game_of(folder)
            rs = routes(gid); route = next((r for r in rs if r['name'] == args.route), None) if args.route else rs[0]
            if not route: sys.exit(f'{gid}: no route {args.route} in dm/games/{gid}/bench_android.tsv')
            for d in devices:
                if args.install:
                    print(f"{gid} → {d['model']}: installing", flush=True)
                    subprocess.run([sys.executable, str(REPO / 'scripts/build_android_from_nsp.py'), folder, '-k', args.keys, '--push-only', '--serial', d['serial'], '--progress', 'lines'], check=True)
                for n in range(0 if args.warmup else 1, args.runs + 1):   # run 0: the warm-up, the first launch after an install (pipelines built, files cached)
                    print(f"{g.get('name', gid)} ({route['name']}) on {d['model']}, {'warm-up' if n == 0 else f'run {n}'}", flush=True)
                    r = run_one(d['serial'], folder, gid, route, n, out / f"{d['model'].replace(' ', '_')}_{d['serial']}", args); results.append(r)
                    print(f"  first frame {r['first_frame_s']} s, ready {r['ready_s']} s, {r['fps']} fps, frame p50 {r['frame_p50']} / p95 {r['frame_p95']} ms, "
                          f"GPU p50 {r['gpu_p50']} ms, {r['exit'] or 'ran'}", flush=True)
                    report(out, devices, results)
    finally:
        awake.stop.set()
    print(f'results: {out / "results.md"}')


if __name__ == '__main__':
    main()
