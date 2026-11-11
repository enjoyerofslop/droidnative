# The Vulkan drivers DroidPlay for Windows offers per game (droidplay's plans/turnip-driver-windows-app.md, phase 3): the catalog pinned in the repository
# (dm/android/vk_drivers.json), each entry checked against a phone's GPU (phone_gpu.py), downloaded on demand from its builder's release and checked by the zip's
# and the driver's SHA-256, and drivers a player adds ("Add your own…"), checked by vk_driver_pkg as the packing script checks them. Nothing from a driver is run
# on the computer. Without Qt, so dm/tools/tests/test_android_desktop.py runs it where PySide6 isn't installed.
#   The files: <data>/vk_drivers/<id>/<the release's zip name> for catalog entries, <data>/vk_drivers/custom-<sha8>/<the file's name> for a player's own (<data>:
#   build_android_from_nsp.py's data folder). The app passes that file to the packing script (--vk-driver, --set-vk-driver), which checks it again.
import hashlib, io, json, re, shutil, sys, urllib.request, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CATALOG = REPO / 'dm/android/vk_drivers.json'
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import vk_driver_pkg as vkpkg   # noqa: E402  # pyright: ignore[reportMissingImports]  (dm/android/tools, put on the path above)

FIELDS = ('id', 'name', 'builder', 'page', 'url', 'zip_sha256', 'size', 'library', 'library_sha256', 'library_size', 'min_api', 'gpus', 'tested', 'mesh_shaders',
          'env', 'licence')
TESTED, SUPPORTED, OTHER_GPU, NOT_ADRENO, UNKNOWN = 'tested', 'supported', 'other gpu', 'not adreno', 'unknown'


class Cancelled(Exception): pass


def load(path=CATALOG):
    """The catalog's entries, each checked for its fields (ValueError names what is wrong: a catalog change is a pull request, and its tests read this)"""
    d = json.loads(Path(path).read_text(encoding='utf-8'))
    if d.get('schema') != 1: raise ValueError(f'{path}: schema {d.get("schema")!r}, not 1')
    out, ids = [], set()
    for e in d.get('drivers') or []:
        missing = [k for k in FIELDS if k not in e]
        if missing: raise ValueError(f'{path}: {e.get("id", "an entry")} lacks {", ".join(missing)}')
        for k in ('zip_sha256', 'library_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', e[k]): raise ValueError(f'{path}: {e["id"]}\'s {k} is not a SHA-256')
        if not re.fullmatch(r'[a-z0-9][a-z0-9.-]*', e['id']) or e['id'].startswith('custom-') or e['id'] in ids: raise ValueError(f'{path}: bad or repeated id {e["id"]!r}')
        if not e['url'].startswith('https://github.com/'): raise ValueError(f'{path}: {e["id"]} is not a GitHub release asset')
        bad_env = [x for x in e['env'] if x.split('=', 1)[0] not in vkpkg.ENV_ALLOWED]
        if bad_env: raise ValueError(f'{path}: {e["id"]} sets {", ".join(bad_env)}: only {", ".join(vkpkg.ENV_ALLOWED)} may go beside a driver')
        ids.add(e['id']); out.append(e)
    return out


def in_ranges(n, gpus): return any(lo <= n <= hi for lo, hi in gpus)


def mark(e, gpu, sdk=None, game=''):
    """How entry e fits a phone (gpu: phone_gpu.classify's; sdk: its API level) → {kind, text, rows, warn}: TESTED with DroidPlay's runs on that Adreno (this game's
    first), SUPPORTED where the builder lists it, OTHER_GPU, NOT_ADRENO, or UNKNOWN when no phone or no number is known. warn: an Android too old for the driver"""
    kind_g, n = (gpu or {}).get('kind'), (gpu or {}).get('adreno')
    warn = f'needs Android API {e["min_api"]} (the phone has {sdk})' if sdk and str(sdk).isdigit() and int(sdk) < e['min_api'] else ''
    if kind_g in ('mali', 'xclipse', 'powervr', 'other'): return {'kind': NOT_ADRENO, 'text': 'not for this GPU: Turnip is for Adreno GPUs', 'rows': [], 'warn': warn}
    if not n: return {'kind': UNKNOWN, 'text': 'the phone\'s Adreno model is not known', 'rows': rows_of(e, None, game), 'warn': warn}
    rows = rows_of(e, n, game)
    if rows: return {'kind': TESTED, 'text': f'tested on the Adreno {n}', 'rows': rows, 'warn': warn}
    if in_ranges(n, e['gpus']): return {'kind': SUPPORTED, 'text': f'the builder lists the Adreno {n}; not tested by DroidPlay', 'rows': [], 'warn': warn}
    return {'kind': OTHER_GPU, 'text': f'not for the Adreno {n}', 'rows': [], 'warn': warn}


def rows_of(e, n, game=''):   # its tested rows on Adreno n (all of them for None), as (row, game's line): this game's first
    out = [(r, r['games'].get(game, '')) for r in e['tested'] if n is None or r['gpu'] == n]
    return sorted(out, key=lambda x: not x[1])


def mesh_note(e):   # for a Switch 2 game (NVN2): its mesh draws need VK_EXT_mesh_shader
    if e.get('mesh_shaders') is True: return ''
    return ("This Switch 2 game may draw with mesh shaders, which this driver doesn't have: those draws are skipped" if e.get('mesh_shaders') is False
            else "This Switch 2 game may draw with mesh shaders, and whether this driver has them isn't known")


def file_of(e, folder):   # where a catalog entry's zip goes (and is found)
    return Path(folder) / e['id'] / e['url'].rsplit('/', 1)[1]


def check_zip(e, data):   # the zip's bytes against the entry: its hash, then the driver inside it → None, or why not
    if hashlib.sha256(data).hexdigest() != e['zip_sha256']: return f'{e["name"]}\'s download doesn\'t match the catalog\'s checksum'
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if z.getinfo(e['library']).file_size != e['library_size']: return f'{e["library"]} in {e["name"]} is not the size the catalog says'
            lib = z.read(e['library'])
    except (KeyError, zipfile.BadZipFile) as x: return f'{e["name"]}\'s download is not the package the catalog names ({x})'
    if hashlib.sha256(lib).hexdigest() != e['library_sha256']: return f'{e["library"]} in {e["name"]} doesn\'t match the catalog\'s checksum'
    return None


def cached(e, folder):   # the entry's zip, downloaded before and still matching, or None
    f = file_of(e, folder)
    try: return f if f.is_file() and f.stat().st_size == e['size'] and check_zip(e, f.read_bytes()) is None else None
    except OSError: return None


def download(e, folder, progress=None, cancelled=lambda: False):
    """The entry's zip from its builder's release into folder, checked by the zip's and the driver's SHA-256 → its path. Raises Cancelled, or ValueError (the file
    deleted) when it doesn't match. progress(done, total) as it comes"""
    out = file_of(e, folder); out.parent.mkdir(parents=True, exist_ok=True)
    if cached(e, folder): return out
    part = out.with_name(out.name + '.part'); buf, done = io.BytesIO(), 0
    req = urllib.request.Request(e['url'], headers={'User-Agent': 'DroidPlay'})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            while chunk := r.read(1 << 16):
                if cancelled(): raise Cancelled()
                buf.write(chunk); done += len(chunk)
                if done > max(e['size'], 1) * 2: raise ValueError(f'{e["name"]}\'s download is larger than the catalog says')
                if progress: progress(done, e['size'])
    except BaseException:
        part.unlink(missing_ok=True); raise
    why = check_zip(e, buf.getvalue())
    if why: raise ValueError(why + ', so it was deleted and nothing was installed')
    part.write_bytes(buf.getvalue()); part.replace(out)
    return out


def import_custom(path, folder):
    """A player's own driver (an AdrenoTools zip or a .so) checked by vk_driver_pkg and copied into folder → its record: id custom-<sha8>, name, sha256, meta,
    file, proprietary (meta.json names a vendor other than Mesa: Qualcomm's driver from another phone, allowed with a warning). Raises vk_driver_pkg.PackageError"""
    d = vkpkg.read(path)
    rid = f'custom-{d.sha256[:8]}'; dst = Path(folder) / rid / Path(path).name
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.is_file() or dst.read_bytes() != Path(path).read_bytes(): shutil.copyfile(path, dst)
    vendor = str((d.meta or {}).get('vendor') or '')
    return {'id': rid, 'name': (d.meta or {}).get('name') or Path(path).name, 'library': d.library, 'sha256': d.sha256, 'meta': d.meta, 'file': str(dst),
            'min_api': d.min_api, 'proprietary': bool(vendor) and vendor.lower() != 'mesa'}


ADD_WARNING = ('Drivers you add run inside the game on your phone. A Vulkan driver is native code. DroidPlay checked that this file is an Android arm64 driver '
               "package; it can't check what the code does. It runs with the game's access to its own files and saves (the app has no internet permission). "
               "Add drivers only from builders you trust. If the game can't start with it, DroidPlay goes back to the phone's own driver and says so; you can "
               'switch back here at any time.')
PROPRIETARY_WARNING = ("This package says it is a {vendor} driver, not Mesa's: a proprietary driver taken from another device. It may not suit this phone, "
                       'and DroidPlay has no licence to pass it on, so it stays your own file.')
