# Pack a Switch game you own for Android: your NSP / XCI files and your prod.keys in, the nxnative app and the game files on the phone out.
#   python scripts/build_android_from_nsp.py <NSP folder> -k <prod.keys> [-p <version>] [-l <language>] [--serial <adb device>] [--no-push]
#   The folder may instead hold the game as one NUP container (a .nup file: base game, updates and DLC), or as a dump folder (scripts/pack_dump.py), or the .nup file may
#   be given in its place: neither needs prod.keys (build_ipa_from_nsp.py reads them, as for iOS)
#   python scripts/build_android_from_nsp.py <NSP folder> -k <prod.keys> --push-only [--serial ...]   install the app and copy a game built before, without building
#   python scripts/build_android_from_nsp.py --apk-only [--serial ...]                                  the app with every game host built on this computer, installed
#   python scripts/build_android_from_nsp.py --migrate --title <title ID> [--serial ...]               a one-game install's folder (files/game) into files/games/<title ID>
#   python scripts/build_android_from_nsp.py --check | --info <NSP folder>                              requirements / the game's details, as JSON (the desktop app)
#   python scripts/build_android_from_nsp.py --setup [--accept-android-licenses]                         install what --check finds missing (Windows: dm/android/tools/host_setup.py)
#   python scripts/build_android_from_nsp.py <NSP folder> -k <prod.keys> --game-apk [--xapk] [--out <folder>]   the game in an app of its own, to install anywhere (make_game_app)
#   --progress json: newline-delimited JSON events on stdout (build_ipa_from_nsp.py Progress), for the desktop app (scripts/nxnative_android.py)
#   Every build also writes those events to a journal, <data>/builds/<time>-<pid>.jsonl (start and exit events around them), whatever its --progress: the desktop app
#   shows a build started from a console too
# One app carries every game: its launcher (dm/android/java Launcher.java) lists the games on the phone, Android/data/org.nxnative.android/files/games/<title ID>/,
# and the app holds a host per game, lib/arm64-v8a/libdmhost_<title ID>.so, started by its loader (dm/android/loader.c). The hosts built on this computer are kept in a
# library (<data>/hosts/<title ID>/: %LOCALAPPDATA%\nxnative\android on Windows, ~/.local/share/nxnative/android elsewhere), and every APK is packed from all of them,
# so building a second game keeps the first in the app.
# Steps (the extraction and the rewrite are build_ipa_from_nsp.py's own, reused):
#   1. find the game profile from the title ID (dm/games/<id>); a game without one is surveyed and packed from a provisional profile (<NSP folder>/<id>_build/profile),
#      first with --no-push, then built and installed like the others (an experimental build: it may not boot)
#   2. extract the version to pack (the newest in the folder, or -p) with nx_extract (built with dotnet)
#   3. rewrite the code modules for Android (dm/tools/patch_nso.py with DM_TARGET=android) into <id>_build/patched_android_<version>/
#   (the shaders: split as for iOS, translated to SPIR-V for the Vulkan replay by dm/android/tools/spv_build.py)
#   4. build the game's host (dm/android, CMake + the NDK), the loader and the self test into the library, and pack the APK (dm/android/tools/build_apk.py) into <data>,
#      signed with ~/.android/nxnative-debug.jks (made on first use; every later build must use it to update the app); the button-icon font (make_ext_font.py)
#   5. unless --no-push: install the APK with adb (an update: the app's data, saves included, stay) and copy the rewritten modules, the RomFS (the extraction's
#      RomFS.img), any DLC and the translated shaders to files/games/<title ID>/, with its icon, control data, default game language (defaults.txt) and game.json.
#      A one-game install of the same game (files/game, the layout before the launcher) is moved there instead of copied again, and its save is copied by the app
# The picture comes from the Vulkan replay of NVN (dm/android/gfx_vk.c).
# Needs: Python with lz4, capstone, fonttools and backports.zstd (not on Python 3.14), the .NET SDK 10, the Android SDK with an NDK, CMake 3.22 and build-tools (ANDROID_HOME or --sdk), adb, keytool (a JDK).
import argparse, atexit, contextlib, datetime, functools, hashlib, json, os, re, shutil, struct, subprocess, sys, tarfile, tempfile, time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
try: import fcntl  # noqa: F401
except ImportError: sys.path.append(str(REPO / 'dm/android/tools/compat'))   # Windows: build_ipa_from_nsp.py loads tree_tar.py, which imports fcntl (compat/fcntl.py)
if os.name == 'nt': os.environ.setdefault('DM_REWRITE_J', '1')   # patch_nso.py's parallel scans fork their workers with SIGTERM blocked, which Windows cannot: one there
import build_ipa_from_nsp as bi   # noqa: E402
from build_ipa_from_nsp import BuildError, say   # noqa: E402

PKG = 'org.nxnative.android'
# One signing key for every build on this computer: an update must be signed like the installed app, and uninstalling it would delete the saves and the game files on the phone
KEYSTORE = Path.home() / '.android' / 'nxnative-debug.jks'
# The letters of the button-icon font (make_ext_font.py): macOS's Arial Rounded Bold is its default; elsewhere a bold sans-serif of the system
LETTER_FONTS = ['/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf', r'C:\Windows\Fonts\arialbd.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
                '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf', '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf']
# The standard shared font (hle_sdk16.c: every font type but the Nintendo extension), copied into <id>_build/font/standard.ttf: STD_FONT names one, else the first of these.
# It must be a hinted TrueType font. Android's own Roboto has no TrueType hinting, and Super Smash Bros. Ultimate crashed at boot on it (main+0x7caa0); Roboto with empty
# cvt / fpgm / prep tables crashed too, while Arial stripped of everything but its hinting booted. The iPhone build copies Arial Unicode the same way (build_ipa.sh)
STANDARD_FONTS = ['/System/Library/Fonts/Supplemental/Arial Unicode.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf', r'C:\Windows\Fonts\arialuni.ttf',
                  r'C:\Windows\Fonts\arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', '/usr/share/fonts/TTF/DejaVuSans.ttf',
                  '/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf', '/usr/share/fonts/liberation-sans/LiberationSans-Regular.ttf']
REMOTE = f'/sdcard/Android/data/{PKG}/files'
BUILD_TOOLS, PLATFORM = '36.0.0', 'android-35'   # build_apk.py's defaults
# libadrenotools and its hooks (dm/android/CMakeLists.txt), in every APK: DM_VK_DRIVER opens a Vulkan driver of the player's through them (dm/android/vk_driver.c), so trying
# one needs no other build. Built beside the loader, and kept with it in the library
VK_DRIVER_LIBS = ('libadrenotools.so', 'libhook_impl.so', 'libmain_hook.so')
# Games played on an Android device: the rows of the README's Game Status whose tier is Playable – minor issues, Playable – major issues or In-game from a run
# on current code, with a profile, kept in step with that table. The desktop app shows the others as not played there yet. Left out: In-game, blocked (Frostpunk,
# Ocarina of Time) and Menus (Mario Kart World), and the rows from before the nxnative merge (†: Super Mario Bros. Wonder, Super Mario 3D World + Bowser's Fury),
# which current code hasn't run
ANDROID_TESTED = {
    '01008DB008C2C000',   # Pokémon Shield (Playable – minor issues through the first battle, into the Slumbering Weald)
    '010027400CDC6000',   # Divinity: Original Sin 2 - Definitive Edition (Playable – major issues through the first combat)
    '010003F003A34000',   # Pokémon: Let's Go, Pikachu! (Playable – minor issues through the rival's first battle)
    '0100000011D90000',   # Pokémon Brilliant Diamond (Playable – minor issues through Lake Verity's first battle)
    '0100DCD01525A000',   # Persona 3 Portable (Playable – minor issues through the first battle)
    '01006F8002326000',   # Animal Crossing: New Horizons
    '0100000000010000',   # Super Mario Odyssey
    '01006A800016E000',   # Super Smash Bros. Ultimate
    '01006BB00C6F0000',   # The Legend of Zelda: Link's Awakening
    '01002DA013484000',   # The Legend of Zelda: Skyward Sword HD
    '01007EF00011E000',   # The Legend of Zelda: Breath of the Wild (Playable – major issues through the Shrine of Resurrection onto the Great Plateau)
    '0100606026F12000',   # Final Fantasy Resonance
    '010069C01AB82000',   # SHIN MEGAMI TENSEI V: Vengeance (a contributor's report)
}


def data_dir():   # the library of game hosts, the loader, the self test and the APK
    base = Path(os.environ['LOCALAPPDATA']) if os.name == 'nt' and os.environ.get('LOCALAPPDATA') else Path.home() / '.local/share'
    return base / 'nxnative' / 'android'


class Journaled(bi.Progress):   # the console's progress, and the same build's events as JSON lines in a journal file (a second Progress in json mode, written there)
    KEEP = 20   # journals kept

    def __init__(self, mode, argv):
        super().__init__(mode); self.inner = False
        d = data_dir() / 'builds'; d.mkdir(parents=True, exist_ok=True)
        for old in sorted(d.glob('*.jsonl'))[:-self.KEEP]: old.unlink(missing_ok=True)
        self.f = open(d / f'{datetime.datetime.now():%Y%m%d-%H%M%S}-{os.getpid()}.jsonl', 'a', encoding='utf-8')
        self.j = bi.Progress('json'); self.j._json = self.write
        self.write({'ev': 'start', 'pid': os.getpid(), 'id': os.environ.get('NXNATIVE_BUILD_ID'), 'argv': argv, 'cwd': os.getcwd()})

    def write(self, obj):
        obj.setdefault('t', round(datetime.datetime.now().timestamp(), 3))
        try: self.f.write(json.dumps(obj, ensure_ascii=False, default=str) + '\n'); self.f.flush()
        except (OSError, ValueError): pass   # the journal never stops the build

    def plan(self, n): super().plan(n); self.j.plan(n)
    def add(self, n): super().add(n); self.j.add(n)
    def stage(self, name, poll=None, step='', **kw):
        self.inner = True   # stage() ends the current stage and sets the counts through end() and set(): the journal's own stage() does both itself
        try: super().stage(name, None, step, **kw)
        finally: self.inner = False
        self.j.stage(name, step=step, **kw)
        if poll: self.watch(poll)
    def set(self, **kw):
        super().set(**kw)
        if not self.inner: self.j.set(**kw)
    def end(self, summary='', ok=True):
        super().end(summary, ok)
        if not self.inner: self.j.end(summary, ok)
    def say(self, msg): super().say(msg); self.j.say(msg)
    def close(self, ok=True): super().close(ok); self.j.close(ok)
    def exit(self, code): self.close(ok=code == 0); self.write({'ev': 'exit', 'code': code}); self.f.close()


def sdk_dir(arg):   # --sdk, the environment, then where Android Studio puts it: Windows, Linux, macOS
    for c in (arg, os.environ.get('ANDROID_HOME'), os.environ.get('ANDROID_SDK_ROOT'), os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Android', 'Sdk'), os.path.expanduser('~/Android/Sdk'),
              os.path.expanduser('~/Library/Android/sdk')):
        if c and (Path(c) / 'platform-tools').is_dir(): return Path(c)
    raise BuildError('Android SDK not found: give --sdk or set ANDROID_HOME')


sys.path.append(str(REPO / 'dm/android/tools')); import host_setup   # noqa: E402  # pyright: ignore[reportMissingImports]  (--setup; dm/android/tools, put on the path here)
NDK, CMAKE = '28.2.13676358', '3.22.1'   # what --setup installs, and the CI builds with; a build takes the newest NDK and CMake the SDK has


def sdk_packages(sdk):   # check()'s rows for the SDK's parts → (sdkmanager's name, a file it puts there), for --setup
    exe = '.exe' if os.name == 'nt' else ''
    return {'adb': ('platform-tools', sdk / 'platform-tools' / f'adb{exe}'), f'platform {PLATFORM}': (f'platforms;{PLATFORM}', sdk / 'platforms' / PLATFORM / 'android.jar'),
            f'build-tools {BUILD_TOOLS}': (f'build-tools;{BUILD_TOOLS}', sdk / 'build-tools' / BUILD_TOOLS), 'NDK': (f'ndk;{NDK}', sdk / 'ndk' / NDK),
            'CMake': (f'cmake;{CMAKE}', sdk / 'cmake' / CMAKE)}


def tool_paths(sdk_arg=None):   # the JDK and .NET SDK --setup installed, and the SDK's adb, on PATH for this run and what it starts (the desktop app imports this script for it too)
    try: sdk = sdk_dir(sdk_arg)
    except BuildError: sdk = None
    host_setup.add_tool_paths(data_dir() / 'tools', sdk)


tool_paths()


def newest(d, what):
    vs = sorted((p for p in d.iterdir() if p.is_dir()), key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split('.')]) if d.is_dir() else []
    if not vs: raise BuildError(f'no {what} in {d}')
    return vs[-1]


def build_nx_extract(work, logs, env):
    """build_ipa_from_nsp.py's, with Windows' .exe, and built once per version of its source into <data>/tools/nx_extract-<digest>, which every run then takes:
    the desktop app reads each game with --info, so a build per folder per read was a dotnet build each time, several at once writing the project's obj/.
    work is unused (that script's builder put it there)"""
    src = REPO / 'dm/tools/nx_extract'; name = 'nx_extract.exe' if os.name == 'nt' else 'nx_extract'
    h = hashlib.sha256()
    for p in sorted(src.rglob('*')):
        rel = p.relative_to(src)
        if p.is_file() and not {'bin', 'obj'} & set(rel.parts): h.update(rel.as_posix().encode() + b'\0' + p.read_bytes() + b'\0')
    out = data_dir() / 'tools' / f'nx_extract-{h.hexdigest()[:16]}'
    if (out / name).is_file(): return out / name
    with tempfile.TemporaryDirectory(prefix='nx_extract_') as t:   # built outside and copied in, as that script does: MSBuild breaks on an apostrophe in the path
        bi.run(['dotnet', 'build', src, '-c', 'Release', '-o', t, '-v', 'quiet', '-nologo'], logs / 'nx_extract_build.log', env=env)
        if not (Path(t) / name).exists(): raise BuildError(f'nx_extract built without an executable (see {logs / "nx_extract_build.log"})')
        part = out.with_name(f'{out.name}.{os.getpid()}'); bi.rmtree(part); shutil.copytree(t, part)
        try: os.replace(part, out)
        except OSError: bi.rmtree(part)   # another run put the same build there meanwhile
    return out / name


# build_ipa_from_nsp.py builds nx_extract itself wherever it reads packages (package_reader, which scan() uses) and in the survey, and looks for an executable named
# nx_extract, which on Windows is nx_extract.exe: every NSP folder stopped there. This script's builder takes its place for the whole run.
bi.build_nx_extract = lambda repo, work, logs, env: build_nx_extract(work, logs, env)


def build_host(sdk, game_id, work, logs, env):   # → (the game's host, the loader, the NDK); VK_DRIVER_LIBS beside them
    ndk = newest(sdk / 'ndk', 'NDK'); cm = newest(sdk / 'cmake', 'CMake') / 'bin'
    exe = '.exe' if os.name == 'nt' else ''
    bdir = work / 'android_host'
    # a build folder set up from another checkout (a worktree, a clone that moved, another checkout picked in a desktop app): cmake refuses a cache made for another
    # source folder, so that one starts afresh
    cache = bdir / 'CMakeCache.txt'
    if cache.is_file():
        m = re.search(r'^CMAKE_HOME_DIRECTORY:INTERNAL=(.*)$', cache.read_text(encoding='utf-8', errors='replace'), re.M)
        if m and Path(m.group(1).strip()).resolve() != (REPO / 'dm/android').resolve(): shutil.rmtree(bdir)
    bi.run([cm / f'cmake{exe}', '-G', 'Ninja', '-S', REPO / 'dm/android', '-B', bdir, f'-DCMAKE_MAKE_PROGRAM={cm / ("ninja" + exe)}',
            f'-DCMAKE_TOOLCHAIN_FILE={ndk / "build/cmake/android.toolchain.cmake"}', '-DANDROID_ABI=arm64-v8a', '-DANDROID_PLATFORM=android-29',
            f'-DGAME={game_id}', f'-DPython3_EXECUTABLE={sys.executable}'], logs / 'android_cmake.log', env=env)
    bi.run([cm / f'ninja{exe}', '-C', bdir, 'dmhost_app', 'nxloader', *[n[3:-3] for n in VK_DRIVER_LIBS]], logs / 'android_host.log', env=env)
    return bdir / f'libdmhost_{game_id}.so', bdir / 'libnxloader.so', ndk


def build_selftest(ndk, work, logs, env):
    bin_ = next((ndk / 'toolchains/llvm/prebuilt').iterdir()) / 'bin'; exe = '.exe' if os.name == 'nt' else ''
    d = work / 'android_selftest'; d.mkdir(parents=True, exist_ok=True)
    bi.run([sys.executable, REPO / 'dm/android/tests/selftest_nso.py', bin_ / f'clang{exe}', bin_ / f'llvm-objcopy{exe}', d / 'main.nso'], logs / 'android_selftest.log', env=env)
    bi.run([sys.executable, REPO / 'dm/tools/patch_nso.py', d / 'main.nso', d / 'patched', 'main'], logs / 'android_selftest_rewrite.log', env=env)
    return d / 'patched'


def button_font(work, logs, env):   # the Nintendo extension shared font's stand-in (hle_sdk16.c: button icons at their private-use code points), into <id>_build/font
    font = work / 'font'; ttf = font / 'nintendo_ext.ttf'
    letters = next((f for f in LETTER_FONTS if Path(f).is_file()), None)
    if not letters: raise BuildError('no letter font for the button icons: ' + ', '.join(LETTER_FONTS))
    if not bi._importable('fontTools'): raise BuildError(f'the current Python ({sys.executable}) is missing fontTools (pip install fonttools)')
    font.mkdir(parents=True, exist_ok=True)
    bi.run([sys.executable, REPO / 'dm/tools/make_ext_font.py', ttf, letters], logs / 'make_ext_font.log', env=env)
    standard_font(font)
    return font


def hinted(path):   # a TrueType font with hinting programs (STANDARD_FONTS)
    try:
        from fontTools.ttLib import TTFont
        f = TTFont(path, lazy=True); return 'glyf' in f and 'fpgm' in f and 'prep' in f
    except Exception: return False


def standard_font(font):   # <font>/standard.ttf: a hinted TrueType font; without one the device falls back to its own Roboto, on which some games crash
    dst = font / 'standard.ttf'
    named = os.environ.get('STD_FONT')
    cands = [named] if named else [f for f in STANDARD_FONTS if Path(f).is_file()]
    src = next((f for f in cands if hinted(f)), None)
    if not src:
        dst.unlink(missing_ok=True)
        say(f'[RED] no hinted TrueType font for the standard shared font ({"STD_FONT=" + named + " is not one" if named else "none of " + ", ".join(STANDARD_FONTS)}): '
            "the game uses the device's Roboto, on which Super Smash Bros. Ultimate crashes at boot. Set STD_FONT to a hinted .ttf")
        return
    if not dst.is_file() or dst.stat().st_size != Path(src).stat().st_size: shutil.copyfile(src, dst)


def build_shaders(sv, dirs, work, logs, env, g, dlc_roms=()):
    """The game's NVN shaders for the Vulkan replay: the split (build_ipa_from_nsp.py split_shaders, checked against the profile's tables), then
    dm/android/tools/spv_build.py (the in-repository translator, dmsh_xlate_bin's dll run by dotnet) into <work>/spv. None when there are none"""
    if not sv: return None
    sh = work / 'shader'
    own = not g.dir.resolve().is_relative_to((REPO / 'dm/games').resolve())   # a provisional profile (outside dm/games) takes the split's tables, as build_ipa_from_nsp.py does; the repository's are checked
    try: bi.split_shaders(sys.executable, REPO, [bi.rfs.source(dirs[v]) for v in sv], [dirs[v] / 'ExeFS/main' for v in sv], sh / 'pkg', env, logs, g, own, dlc_roms=dlc_roms)   # its own stage (a DLC's shaders too)
    except BuildError as e: bi.PROG.end(str(e), ok=False); say('[RED] the game is packed without shaders (its draws are skipped)'); return None
    bi.PROG.stage('shaders for Vulkan', step='translating')
    out = work / 'spv'
    try: bi.run([sys.executable, REPO / 'dm/android/tools/spv_build.py', sh / 'pkg', out, '--xlate', REPO / 'dm/gfx/tools/dmsh_xlate_bin/dmsh_xlate.dll',
                 '--facts', g.table('shader_facts.tsv')], logs / 'spv_build.log', env=env)
    except BuildError as e: bi.PROG.end(str(e), ok=False); say(f'[RED] shader translation failed (see {logs / "spv_build.log"}): the game is packed with the shaders translated so far'); return out if out.is_dir() else None
    last = [l for l in (logs / 'spv_build.log').read_text(errors='replace').splitlines() if l.startswith('spv_build:')]
    bi.PROG.end(last[-1][11:] if last else str(out))
    return out


def ue_decode(dirs, pkg_ver, nsp_dir, patched, work, logs, env, g, serial, sdk, game):
    """Unreal's shaders, decoded into each version's <extraction>/ue_shaders before the split reads them (build_ipa_from_nsp.py decode_ue_shaders, the NSP scripts' step): they are
    Oodle-compressed, and only the game's own decoder undoes it. The Mac build runs it in the Mac host; this computer may not run the game's arm64 code (Windows, Linux), so the
    phone does (scripts/android_oodle.py): the game's host goes into the app, and its rewritten code to the phone, before the shaders exist (the host does not depend on them).
    A folder whose stamp matches its paks and containers is kept, and one a Mac build made beside this NSP folder (<game>/<title ID>_build, from the same files) is taken"""
    sys.path.insert(0, str(REPO / 'dm/gfx/tools')); import uepak, android_oodle   # noqa: E401  # pyright: ignore[reportMissingImports]
    fresh = lambda d: (d / 'ue_shaders/stamp').is_file() and (d / 'ue_shaders/stamp').read_text() == bi.ue_stamp(d)
    todo = {v: d for v, d in dirs.items() if not fresh(d)}
    bi.PROG.add(1); bi.PROG.stage('UE shader decode')
    for v, d in list(todo.items()):   # DroidPlay's Mac build of the same game (the folder above the NSP folder), its decoded archives made from the same paks
        if os.environ.get('DM_UE_DECODE') == 'phone': break   # the phone's decode wanted even so (a test of it on a Mac with the game's Mac build)
        mac = nsp_dir.parent / f'{g.id}_build' / 'extract' / v / 'ue_shaders'
        if (mac / 'stamp').is_file() and (mac / 'stamp').read_text() == bi.ue_stamp(d):
            part = d / 'ue_shaders.partial'; bi.rmtree(part); shutil.copytree(mac, part); bi.swap_in(part, d / 'ue_shaders'); del todo[v]
            say(f'{v}: the decoded shader archives of the Mac build in {mac.parent.parent.parent}')
    if not todo: bi.PROG.end('reused'); return
    if not serial:
        raise BuildError('the game\'s Unreal shaders are Oodle-compressed, and only the game\'s own decoder undoes them: it runs on the phone here, so connect one (or build once without '
                         '--no-push, or build the game in DroidPlay for Mac first)')
    bi.PROG.set(step='the game\'s host and code to the phone, where its own Oodle decodes the shaders')
    so, loader, ndk = build_host(sdk, g.id, work, logs, env); st = build_selftest(ndk, work, logs, env)
    library_add(g.id, so, loader, st, {'title_id': g.id, 'name': bi.nacp.name(game / 'control.nacp') or g.get('name', ''), 'version': pkg_ver,
                                       'display': bi.nacp.version(game / 'control.nacp'), 'nsp_dir': str(nsp_dir)})
    install(serial, make_apk(sdk, logs, env), logs)
    dst = f'{REMOTE}/games/{g.id}'; adb(serial, 'shell', 'mkdir', '-p', dst); adb(serial, 'shell', 'rm', '-rf', f'{dst}/code')
    push_dir(serial, patched, dst, 'code', logs / 'adb_push_code_oodle.log'); open_tree(serial, dst)
    phone = android_oodle.Phone(adb, serial, g.id, REMOTE, PKG, work, logs, say)
    t0, total = time.time(), 0
    for v, d in todo.items():
        bi.PROG.set(step=f'{v}: decoding the shaders with the game\'s Oodle on the phone')
        jd, out = work / f'tmp/ue_job_{v}', d / 'ue_shaders.partial'; bi.rmtree(out)
        try: listing, n = android_oodle.decode(uepak, bi.rfs.source(d), d / 'ExeFS/main', jd, out, phone)
        except ValueError as e: raise BuildError(str(e)) from e   # a damaged pak or container, or the phone's job (its log named)
        if not listing: raise BuildError(f'the RomFS has Unreal paks, but none under {bi.rfs.source(d)} holds a shader code archive: where the shaders are has to be found first')
        say(f'{v}: ' + '; '.join(f'{x["name"]} {x["shaders"]:,} shaders' + (f' ({x["compression"]})' if x.get('compression') else '') for x in listing))
        (out / 'stamp').write_text(bi.ue_stamp(d)); bi.swap_in(out, d / 'ue_shaders'); bi.rmtree(jd)
        total += n + sum(x['shaders'] for x in listing if x['compression'] == 'IoStore, decoded')
    bi.PROG.end(f'{total:,} shaders in {bi.hms(time.time() - t0)}, {phone.jobs} job(s) on the phone')


# ---------------- The library of game hosts ----------------
def library_add(gid, so, loader, selftest, meta):   # the game's host, and the loader, VK_DRIVER_LIBS and self test of the latest build (they do not depend on the game)
    lib = data_dir(); d = lib / 'hosts' / gid; d.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(so, d / so.name)
    (d / 'meta.json').write_text(json.dumps(dict(meta, built=datetime.datetime.now().isoformat(timespec='seconds')), indent=1), encoding='utf-8')
    (lib / 'loader').mkdir(exist_ok=True); shutil.copyfile(loader, lib / 'loader' / loader.name)
    for f in driver_libs(loader.parent): shutil.copyfile(f, lib / 'loader' / f.name)
    st = lib / 'selftest'; shutil.rmtree(st, ignore_errors=True); shutil.copytree(selftest, st)


def driver_libs(d):   # VK_DRIVER_LIBS in a folder: a library made before they were built has none, and its APK goes without (DM_VK_DRIVER then logs that they are missing)
    return [d / n for n in VK_DRIVER_LIBS if (d / n).is_file()]


def library():   # {title ID: (host, meta)} of the hosts built on this computer
    out = {}
    for d in sorted((data_dir() / 'hosts').glob('*')):
        so = d / f'libdmhost_{d.name}.so'
        if so.is_file():
            try: meta = json.loads((d / 'meta.json').read_text(encoding='utf-8'))
            except (OSError, ValueError): meta = {}
            out[d.name] = (so, meta)
    return out


def safe_name(name):   # a file name every file system takes, a phone's and Windows' too
    return re.sub(r'\s+', ' ', re.sub(r'[/\\:*?"<>|]', '', name)).strip()


def clone(src, dst):   # an APFS clone where the volume can make one, else a hard link, else a copy: the RomFS beside a game app costs no space where it can
    Path(dst).unlink(missing_ok=True)
    if sys.platform == 'darwin' and subprocess.run(['cp', '-c', str(src), str(dst)], capture_output=True).returncode == 0: return
    try: os.link(src, dst)
    except OSError: shutil.copyfile(src, dst)


def stage_link(dst, src):   # a symbolic link, else the files cloned (clone): Windows lets a process make symbolic links only with Developer Mode on, or as administrator
    try: Path(dst).symlink_to(src, target_is_directory=Path(src).is_dir())
    except OSError:
        if Path(src).is_dir(): shutil.copytree(src, dst, copy_function=clone)
        else: clone(src, dst)


# A game app (--game-apk): the game in an app of its own, org.nxnative.game.t<title ID> with its name and icon, entered through dm/android/java GameStart with no launcher
# (apk/AndroidManifest.game.xml). The APK carries the game's host and its files as push_game lays them out on the phone (assets/game/, unpacked by GameStart at the first
# start), and the RomFS image as a stored entry when the APK stays under 2 GiB (build_apk.py: a ZIP without ZIP64). A bigger game's RomFS goes beside it, <name>.romfs,
# which the player puts anywhere on the device and picks once in the app. --xapk packs one .xapk instead (an XAPK installer's format: the APK, the RomFS as the app's OBB
# file Android/obb/<package>/main.1.<package>.obb, icon.jpg and manifest.json), for any size; the two kinds sit side by side, each replacing only its own files. Nothing
# goes into the library of hosts: the nxnative app stays as it was.
# The DLC images (aoc/<index>.img) go into the APK while it can hold them; when it can't (Mario Kart 8 Deluxe's Booster Course Pass and its shaders pass 2 GiB with no
# RomFS at all: droidplay-core issue #169), they follow the RomFS in the same data file, the .romfs beside the APK or the XAPK's OBB, so a player still picks one file and
# an XAPK still has one expansion. GameStart copies them out of it into games/<title ID>/aoc/ once, where front_android.c points DM_AOC_DIR, so the host reads them as a
# launcher install's (it mounts DLC by path; only the RomFS goes to it as a descriptor). The RomFS leaves the APK first: the DLC goes beside only with it.
# The data file: the RomFS image from byte 0 (the host reads it as DM_ROMFS=fd:<descriptor>:0:<romfs_bytes>), then, at dlc_at (the RomFS's end rounded up to DLC_ALIGN),
# the DLC pack: DLC_MAGIC, the image count and a zero (little-endian 32-bit), a record per image (32-bit index, 32-bit zero, 64-bit offset from dlc_at, 64-bit size), and
# the images, each at a DLC_ALIGN offset. game.json gives romfs_bytes, data_bytes (the file's whole size) and dlc_at (none: no DLC in it), which GameStart checks.
# → the files made, the APK (or XAPK) first
GAME_APP_LIMIT = (2 << 30) - (64 << 20)   # an APK's size, kept clear of 2 GiB for the ZIP's own records
# A ZIP without ZIP64 also holds at most 65,535 entries, and a game's translated shaders are files of their own (Mario Kart 8 Deluxe's with its DLC passed that at 492 MB:
# droidplay-core issue #169). So a game app carries them as one entry, SPV_ZIP: a stored ZIP of the spv folder (ZIP64 allowed inside it: apksigner never reads it), which
# GameStart unpacks into games/<title ID>/spv/ at the first start with the rest, where the host reads them by path as from a launcher install. The other files are counted
# against GAME_APP_ENTRIES, which leaves room for the APK's own entries (classes.dex, the libraries, resources, the signature)
GAME_APP_ENTRIES = 65535 - 1024
SPV_ZIP = 'spv.zip'
DLC_MAGIC, DLC_ALIGN = b'DMAOCPK1', 4096


def game_app_limit():   # NXNATIVE_GAME_APP_LIMIT=<bytes>: a smaller limit, so that a smaller game takes a big one's layout (a device check of the DLC beside the APK)
    v = os.environ.get('NXNATIVE_GAME_APP_LIMIT', '').strip()
    return int(v) if v.isdigit() else GAME_APP_LIMIT


def gib(n): return f'{n / (1 << 30):.2f} GiB'


# Where a game app's RomFS and DLC go: → (RomFS in the APK, DLC in the APK). parts: the files the APK must carry, by name (code, shaders, font, the rest), with their
# sizes; files: how many entries each makes, dlc_files the DLC's. The RomFS leaves the APK first, then the DLC with it; what the APK must carry and can't, in bytes or in
# entries, is a BuildError naming each part
def game_app_plan(parts, dlc, rom, xapk, limit=GAME_APP_LIMIT, files=None, dlc_files=0, entries=GAME_APP_ENTRIES):
    core = sum(parts.values()); n = sum((files or {}).values())
    if n >= entries:
        raise BuildError(f'a game app can\'t hold this game: the APK would carry {n:,} files ({", ".join(f"{k} {v:,}" for k, v in (files or {}).items())}), and an APK '
                         f'without ZIP64, which apksigner needs, holds at most 65,535 entries ({entries:,} of them for the game). '
                         'Install it through DroidPlay\'s library instead (without --game-apk), which has no such limit')
    if core >= limit:
        raise BuildError(f'a game app can\'t hold this game: the files the APK must carry are {gib(core)} ({", ".join(f"{k} {gib(v)}" for k, v in parts.items())}), and an APK '
                         f'holds {gib(limit)} (2 GiB less room for its records); the RomFS ({gib(rom)}) and the DLC ({gib(dlc)}) could go beside it, these can\'t. '
                         'Install it through DroidPlay\'s library instead (without --game-apk), which has no such limit')
    dlc_fits = core + dlc < limit and n + dlc_files < entries
    if not xapk and dlc_fits and core + dlc + rom < limit: return True, True
    return False, dlc_fits


def pack_spv(spv, dst):   # the spv folder → one stored ZIP (SPV_ZIP), its files named as in the folder; → how many
    import zipfile
    n = 0
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:   # stored: the APK deflates its entries itself
        for r, ds, fs in os.walk(spv, followlinks=True):
            ds.sort()
            for f in sorted(fs): p = Path(r, f); z.write(p, p.relative_to(spv).as_posix()); n += 1
    return n


def dlc_images(aoc):   # → [(index, path)] of aoc/<index>.img, by index; a DLC kept as a folder (an older extraction) can't go into the pack
    out = []
    for p in sorted(Path(aoc).iterdir()) if aoc and Path(aoc).is_dir() else []:
        m = re.fullmatch(r'([1-9][0-9]*)(\.img)?', p.name)
        if not m: continue
        if not m.group(2) or not p.is_file(): raise BuildError(f'the DLC {p} is a folder, and a game app carries its DLC beside the APK as images: extract the game again')
        out.append((int(m.group(1)), p))
    return sorted(out)


def dlc_pack(images):   # → the pack's header and its records [(index, offset from the pack's start, size)], and its length
    head = len(DLC_MAGIC) + 8 + 24 * len(images); off = -(-head // DLC_ALIGN) * DLC_ALIGN; recs = []
    for i, p in images:
        size = Path(p).stat().st_size; recs.append((i, off, size)); off = -(-(off + size) // DLC_ALIGN) * DLC_ALIGN
    end = recs[-1][1] + recs[-1][2] if recs else head
    return DLC_MAGIC + struct.pack('<II', len(recs), 0) + b''.join(struct.pack('<IIQQ', i, 0, o, n) for i, o, n in recs), recs, end


def write_data(dst, rom, images):   # the data file beside a game app: the RomFS (an APFS clone where the volume makes one, never a hard link: the DLC is appended), then the DLC pack
    rom_bytes = Path(rom).stat().st_size; at = -(-rom_bytes // DLC_ALIGN) * DLC_ALIGN
    head, recs, _ = dlc_pack(images); Path(dst).unlink(missing_ok=True)
    if not (sys.platform == 'darwin' and subprocess.run(['cp', '-c', str(rom), str(dst)], capture_output=True).returncode == 0): shutil.copyfile(rom, dst)
    with open(dst, 'r+b') as f:
        f.truncate(at); f.seek(at); f.write(head)
        for (i, p), (_, off, size) in zip(images, recs):
            f.seek(at + off)
            with open(p, 'rb') as src: shutil.copyfileobj(src, f, 16 << 20)
    return at


# The game's defaults.txt: the language, then the profile's Android switches (dm/games/<id>/android_defaults.txt: KEY=VALUE per line, # comments), for a game that needs
# a switch only some games want. The host takes them as it takes env.txt's, without overriding a key env.txt or the settings screen sets (front_android.c); a game app
# sets them the same way (GameStart.java)
def defaults_text(g, lang):
    lines = [f'DM_LANG={lang}']
    own = g.dir / 'android_defaults.txt'
    if own.is_file(): lines += [ln.strip() for ln in own.read_text(encoding='utf-8').splitlines() if '=' in ln and not ln.lstrip().startswith('#')]
    return ''.join(ln + '\n' for ln in lines)


def make_game_app(sdk, g, game, patched, spv, font, aoc, defaults, so, meta, work, logs, env, out_dir, xapk):
    sys.path.insert(0, str(REPO / 'dm/android/tools')); import build_apk   # pyright: ignore[reportMissingImports]  # dm/android/tools, put on the path here
    pkg = build_apk.game_package(g.id)
    rom = bi.rfs.source(game)
    if not bi.rfs.is_image(rom): raise BuildError(f'a game app reads the RomFS as one image ({game}/RomFS.img), and this extraction has a RomFS folder: extract the game again')
    stage = work / 'game_app'; shutil.rmtree(stage, ignore_errors=True); stage.mkdir(parents=True)
    def walk(p): return [(Path(r, f), Path(r, f).stat().st_size) for r, _, fs in os.walk(p, followlinks=True) for f in fs] if p and Path(p).is_dir() else []
    for name, src in (('code', patched), ('font', font)):
        if src and Path(src).is_dir(): stage_link(stage / name, Path(src).resolve())
    if spv and Path(spv).is_dir(): bi.PROG.set(step='packing the shaders into one file'); pack_spv(spv, stage / SPV_ZIP)
    for f in ('icon.jpg', 'control.nacp'):
        if (game / f).is_file(): stage_link(stage / f, (game / f).resolve())
    (stage / 'defaults.txt').write_text(defaults, encoding='utf-8', newline='\n')   # \n on Windows too, as the phone's files are
    staged = [(f.relative_to(stage).as_posix(), n) for f, n in walk(stage)]
    parts = {'code': 0, 'shaders': 0, 'font': 0, 'the rest': 4096 + sum(len(f) + 1 for f, _ in staged)}   # the rest: icon, control data, defaults; game.json and files.txt
    files = {'code': 0, 'shaders': 0, 'font': 0, 'the rest': 2}
    for f, n in staged:
        k = {'code': 'code', SPV_ZIP: 'shaders', 'font': 'font'}.get(f.split('/')[0], 'the rest'); parts[k] += n; files[k] += 1
    rom_bytes = Path(str(rom)).stat().st_size; dlc_walk = walk(aoc); dlc = sum(n for _, n in dlc_walk)
    inside, dlc_inside = game_app_plan(parts, dlc, rom_bytes, xapk, game_app_limit(), files, len(dlc_walk))
    if dlc_inside and dlc: stage_link(stage / 'aoc', Path(aoc).resolve())
    out_images = dlc_images(aoc) if dlc and not dlc_inside else []
    dlc_at = -(-rom_bytes // DLC_ALIGN) * DLC_ALIGN if out_images else 0
    data_bytes = (dlc_at + dlc_pack(out_images)[2]) if out_images else rom_bytes
    info = {**meta, 'package': pkg, 'data_bytes': data_bytes, **({'dlc_at': dlc_at} if dlc_at else {})}
    (stage / 'game.json').write_text(json.dumps(info, indent=1), encoding='utf-8', newline='\n')
    files = sorted(Path(r, f).relative_to(stage).as_posix() for r, _, fs in os.walk(stage, followlinks=True) for f in fs)
    (stage / 'files.txt').write_text(''.join(f + '\n' for f in files + ['files.txt']), encoding='utf-8', newline='\n')
    out_dir.mkdir(parents=True, exist_ok=True)
    base = safe_name(meta.get('name') or g.id) or g.id
    apk = (work / f'{pkg}.apk') if xapk else out_dir / f'{base}.apk'
    icon = game / 'icon.jpg'
    bi.PROG.set(step='packing the APK' + (' with the RomFS inside' if inside else ''))
    bi.run([sys.executable, REPO / 'dm/android/tools/build_apk.py', '--sdk', sdk, '--game-app', g.id, '--so', so, '--game-dir', stage,
            *[x for f in driver_libs(Path(so).parent) for x in ('--lib', f)], *(['--romfs', str(rom)] if inside else []), '--keystore', KEYSTORE, '-o', apk, '--label', meta.get('name') or g.id,
            *(['--icon', icon] if icon.is_file() else [])], logs / 'android_game_apk.log', env=env)
    Path(f'{apk}.idsig').unlink(missing_ok=True)   # apksigner's v4 signature, for adb's incremental installs only: clutter beside an app to share
    if xapk:
        out = out_dir / f'{base}.xapk'; obb = f'Android/obb/{pkg}/main.1.{pkg}.obb'
        manifest = {'xapk_version': 2, 'package_name': pkg, 'name': meta.get('name') or g.id, 'locales_name': {}, 'version_code': '1', 'version_name': '0.1',
                    'min_sdk_version': '29', 'target_sdk_version': '34', 'permissions': ['android.permission.VIBRATE'],
                    'total_size': apk.stat().st_size + data_bytes, 'expansions': [{'file': obb, 'install_location': 'EXTERNAL_STORAGE', 'install_path': obb}]}
        if icon.is_file(): manifest['icon'] = 'icon.jpg'
        tmp = out.with_suffix('.xapk.part')
        import zipfile
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_STORED) as z:   # stored: the APK is compressed already, and the RomFS is read where it lies
            z.writestr('manifest.json', json.dumps(manifest, indent=1, ensure_ascii=False))
            if icon.is_file(): z.write(icon, 'icon.jpg')
            z.write(apk, f'{pkg}.apk')
            with z.open(zipfile.ZipInfo(obb, datetime.datetime.now().timetuple()[:6]), 'w', force_zip64=True) as dst:   # the OBB: the RomFS, then the DLC pack when the APK can't hold it
                done = 0
                def put(path):
                    nonlocal done
                    with open(str(path), 'rb') as src:
                        while chunk := src.read(16 << 20):
                            dst.write(chunk); done += len(chunk); bi.PROG.set(step='packing the XAPK', done=done, total=data_bytes, unit='B')
                put(rom)
                if out_images:
                    head, recs, _ = dlc_pack(out_images)
                    dst.write(b'\0' * (dlc_at - rom_bytes)); dst.write(head); pos = len(head)
                    for (_, p), (_, off, n) in zip(out_images, recs): dst.write(b'\0' * (off - pos)); put(p); pos = off + n
        tmp.replace(out); apk.unlink(missing_ok=True); made = [out]
    else:   # an APK and the data file beside it, or an APK with the RomFS inside, whichever the game's size gave: a .romfs left from the other way goes
        made = [apk]; romfs = out_dir / f'{base}.romfs'
        if inside: romfs.unlink(missing_ok=True)
        else:
            if out_images: write_data(romfs, rom, out_images)
            else: clone(str(rom), romfs)
            made.append(romfs)
    if out_images: say(f'the DLC ({len(out_images)} image{"s" * (len(out_images) != 1)}, {gib(dlc)}) is in {made[-1].name} after the RomFS: the APK can\'t hold it; the app copies it out at its first start')
    return made, inside


def core_version():   # DroidPlay Core's version, for the launcher app's: the VERSION file a release's archives carry (release-assets.yml), else git describe in a checkout
    if (REPO / 'VERSION').is_file(): return (REPO / 'VERSION').read_text(encoding='utf-8').strip() or None
    try: r = subprocess.run(['git', '-C', str(REPO), 'describe', '--tags', '--always'], capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))   # the desktop app asks too, from pythonw.exe: no console window for git
    except (OSError, subprocess.TimeoutExpired): return None
    return (r.stdout.strip().removeprefix('v') or None) if r.returncode == 0 else None


def make_apk(sdk, logs, env):   # the app with every host in the library → this run's own copy, which it installs; the library's nxnative.apk becomes the same app
    lib = data_dir(); hosts = library()
    loader, st = lib / 'loader' / 'libnxloader.so', lib / 'selftest'
    if not hosts or not loader.is_file() or not st.is_dir(): raise BuildError(f'no game host built on this computer yet ({lib}): build a game first')
    KEYSTORE.parent.mkdir(parents=True, exist_ok=True)
    # Packed under a name of this process's own: two builds in parallel (other sessions, other phones) packed and installed the one nxnative.apk, so a build's install
    # could get the other's half-written file (apksigner failed with "offset (16777216) > source size (0)")
    apk, own = lib / 'nxnative.apk', lib / f'nxnative.{os.getpid()}.apk'
    atexit.register(own.unlink, missing_ok=True)
    bi.run([sys.executable, REPO / 'dm/android/tools/build_apk.py', '--sdk', sdk, '--loader', loader, *[x for so, _ in hosts.values() for x in ('--so', so)],
            *[x for f in driver_libs(loader.parent) for x in ('--lib', f)], '--selftest', st, '--keystore', KEYSTORE, '-o', own,
            *(['--version-name', v] if (v := core_version()) else [])], logs / 'android_apk.log', env=env)
    if own.is_file(): tmp = lib / f'.nxnative.{os.getpid()}.apk'; shutil.copyfile(own, tmp); os.replace(tmp, apk)   # whole or not at all, for anyone who takes it from there
    names = [m.get('name') or gid for gid, (_, m) in hosts.items()]
    say(f'app: {", ".join(names)} ({apk})')
    return own


# ---------------- The phone ----------------
WAIT_DEVICE = 0.0   # --wait-device


@contextlib.contextmanager
def phone(serial, what):   # the device to this build while it installs or runs something there (dm/android/tools/device_lock.py): a bench's runs on it, or another build's
    # install, would be force-stopped by this one, and this one's by them. Not held while it builds on the computer
    sys.path.insert(0, str(REPO / 'dm/android/tools')); import device_lock   # pyright: ignore[reportMissingImports]
    try: lock = device_lock.held(serial, what, WAIT_DEVICE, say); lock.__enter__()
    except device_lock.DeviceBusy as e: raise BuildError(str(e)) from None
    try: yield
    finally: lock.__exit__(None, None, None)


def pick_device():
    """The one device adb lists as ready ('device'): an offline Wi-Fi entry left from an earlier connection does not count"""
    out = subprocess.run(['adb', 'devices'], capture_output=True, text=True, errors='replace').stdout.splitlines()[1:]
    rows = [l.split() for l in out if l.strip()]
    ready = [r[0] for r in rows if len(r) > 1 and r[1] == 'device']
    if len(ready) == 1: return ready[0]
    listed = ', '.join(f'{r[0]} ({r[1]})' for r in rows) or 'none'
    raise BuildError(f'{len(ready)} adb devices ready ({listed}): connect one, or pick it with --serial')


def adb(serial, *a, log=None, check=True):
    cmd = ['adb'] + (['-s', serial] if serial else []) + [str(x) for x in a]
    r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', env=dict(os.environ, MSYS_NO_PATHCONV='1'))
    if log: log.write_text(r.stdout + r.stderr)
    # the exit status too: a step that printed nothing left only "failed:" (droidplay-core issue #37), with no way to tell a missing program (127), adb losing the phone (255)
    # and a command that failed (1)
    if r.returncode and check:
        out = (r.stdout + r.stderr).strip()
        raise BuildError(f'{" ".join(cmd)} failed (exit status {r.returncode}): {out[-400:] if out else "no output"}')
    return r.stdout


def sh_quote(s): return "'" + s.replace("'", "'\\''") + "'"


# adb push prints no progress when its output is not a terminal: a copy's count is read from the phone while it runs (the files under the destination folder, or the
# size of the file being written), so the desktop app sees it move
def remote_files(serial, d):
    n = adb(serial, 'shell', f'find {sh_quote(d)} -type f 2>/dev/null | wc -l', check=False).strip()
    return int(n) if n.isdigit() else None


def remote_size(serial, f):
    n = adb(serial, 'shell', f'stat -c %s {sh_quote(f)} 2>/dev/null', check=False).strip()
    return int(n) if n.isdigit() else None


# A phone that fills up in the middle of an install fails at whatever step comes next, often with nothing printed (droidplay-core issue #37: the folder script, after an install
# that ran out of room). The large copies check the room first, and a failed install on a nearly full phone says how full it is
ROOM_SPARE = 256 << 20   # left free besides a copy's own bytes: Android, the app's saves and its log need room too
LOW_ROOM = 1 << 30       # a failed install on a phone with less than this free names the free space as the likely cause


def size_text(n): return f'{n / 1e9:.1f} GB' if n >= 1e9 else f'{max(n, 0) / 1e6:.0f} MB'


def remote_free(serial, d):   # bytes free on the phone's storage where folder d is, or None
    row = adb(serial, 'shell', f'df -k {sh_quote(d)} 2>/dev/null | tail -n 1', check=False).split()
    return int(row[3]) * 1024 if len(row) >= 4 and row[3].isdigit() else None


def need_room(serial, d, need, what):
    free = remote_free(serial, d)
    if free is None or free >= need + ROOM_SPARE: return
    raise BuildError(f'the phone has {size_text(free)} free: {what} needs {size_text(need)}, plus {size_text(ROOM_SPARE)} left free for Android and the app. '
                     f'Free up {size_text(need + ROOM_SPARE - free)} on the phone, then install again')


def says_when_phone_full(f):   # a failed step's error, plus the phone's free space when that is low (a full phone fails steps that print nothing)
    @functools.wraps(f)
    def run(serial, *a, **k):
        try: return f(serial, *a, **k)
        except BuildError as e:
            free = remote_free(serial, REMOTE)
            if free is None or free >= LOW_ROOM or 'free up' in str(e).lower(): raise
            raise BuildError(f'{e}\nThe phone has only {size_text(free)} free, which is likely why: free up space on the phone '
                             f'(a game\'s RomFS.img.partial is a copy cut short, kept so the next install goes on from it), then install again') from e
    return run


@contextlib.contextmanager
def counting(note, total, unit, read):   # while the block runs: done = read() (None: not known yet) of total, in unit ('B': bytes)
    bi.PROG.set(done=0, total=total, unit=unit, note=note)
    def poll():
        v = read()
        return None if v is None else {'done': min(v, total)}
    bi.PROG.watch(poll)
    try: yield
    finally: bi.PROG.watch(None)


TAR_FILES = 200   # a folder with more files than this goes over as one tar archive (push_tar)
MANIFEST = '.nxnative_manifest'   # in a folder copied as a tar: each file's size and modification time, for the next copy to send only what changed


def push_tar(serial, local, parent, name, files, log, sync):
    # adb push sends a folder file by file: Super Mario Bros. Wonder's 37,393 shader files took over 20 minutes to a phone that had none (about 30 files a second).
    # One tar archive, unpacked by the phone's tar, takes a minute or two. With sync, the manifest a copy left in the folder keeps it incremental, as push --sync was
    dst = f'{parent}/{name}'
    rows = {f.relative_to(local).as_posix(): f'{f.stat().st_size} {f.stat().st_mtime_ns}' for f in files}
    old = {}
    if sync:
        for line in adb(serial, 'shell', f'cat {sh_quote(dst + "/" + MANIFEST)} 2>/dev/null', check=False).splitlines():
            meta, _, rel = line.rstrip('\r').partition('\t')
            if rel: old[rel] = meta
    send = [r for r in rows if old.get(r) != rows[r]]
    adb(serial, 'shell', 'mkdir', '-p', dst)
    if send:
        tar = log.with_suffix('.tar')
        bi.PROG.set(done=0, total=len(send), unit='files', note='packing')
        with tarfile.open(tar, 'w', format=tarfile.USTAR_FORMAT) as t:
            for i, r in enumerate(send, 1):
                ti = t.gettarinfo(local / r, arcname=r); ti.mode = 0o666; ti.uid = ti.gid = 0; ti.uname = ti.gname = ''
                with open(local / r, 'rb') as fh: t.addfile(ti, fh)
                bi.PROG.set(done=i)
        remote = f'{parent}/.{name}.tar'
        try:
            need_room(serial, dst, 2 * tar.stat().st_size, f'{name} ({len(send):,} files in one archive, unpacked beside itself)')
            with counting('sending', tar.stat().st_size, 'B', lambda: remote_size(serial, remote)):
                adb(serial, 'push', tar, remote, log=log)
            have = len(rows) - len(send)   # the files kept from an earlier copy are counted by the phone too
            with counting('unpacking on the phone', len(send), 'files', lambda: (lambda n: None if n is None else max(n - have, 0))(remote_files(serial, dst))):
                adb(serial, 'shell', f'tar -xf {sh_quote(remote)} -C {sh_quote(dst)}')
        finally:
            adb(serial, 'shell', 'rm', '-f', remote, check=False); tar.unlink(missing_ok=True)
    man = log.with_suffix('.manifest'); man.write_text(''.join(f'{v}\t{k}\n' for k, v in sorted(rows.items())), encoding='utf-8', newline='\n')
    adb(serial, 'push', man, f'{dst}/{MANIFEST}')
    say(f'{name}: {len(send):,} of {len(rows):,} files sent in one archive' + ('' if len(send) == len(rows) else ' (the others were on the phone already)'))


CHUNK = 256 << 20   # push_resumable's piece


def remote_hash(serial, remote, a, n):   # SHA-256 of n bytes at offset a (a multiple of 4 KiB) of a file on the phone, or None
    out = adb(serial, 'shell', f'dd if={sh_quote(remote)} bs=4096 skip={a // 4096} count={(n + 4095) // 4096} 2>/dev/null | head -c {n} | sha256sum', check=False).split()[:1]
    return out[0] if out else None


def same_ends(serial, local, remote):   # the first and last MiB of a local file and of the same-size file on the phone hash the same
    size = local.stat().st_size
    with open(local, 'rb') as f:
        for a in sorted({0, max(0, size - (1 << 20)) // 4096 * 4096}):
            f.seek(a); n = min(1 << 20, size - a)
            if remote_hash(serial, remote, a, n) != hashlib.sha256(f.read(n)).hexdigest(): return False
    return True


def push_resumable(serial, local, remote, log):
    # A large file (a game's RomFS.img, gigabytes) in pieces appended to <remote>.partial, renamed when whole: adb push cannot resume a file, and wireless adb dropped
    # twice in the middle of Bowser's Fury's 2.8 GB image, each time from zero. A copy cut short goes on from what the phone holds, once the last MiB of it matches
    size, part = local.stat().st_size, remote + '.partial'
    have = remote_size(serial, part) or 0
    if have > size: have = 0
    if have:
        a = max(0, have - (1 << 20)) // 4096 * 4096   # the phone's last MiB (from a 4 KiB boundary), hashed on both sides
        theirs = adb(serial, 'shell', f'dd if={sh_quote(part)} bs=4096 skip={a // 4096} count={(have - a + 4095) // 4096} 2>/dev/null | head -c {have - a} | sha256sum', check=False).split()[:1]
        with open(local, 'rb') as f: f.seek(a); ours = hashlib.sha256(f.read(have - a)).hexdigest()
        if theirs != [ours]: say(f'{remote}: the part on the phone ({have:,} bytes) differs from this file: sent again from the start'); have = 0
        else: say(f'{remote}: {have:,} of {size:,} bytes on the phone already: going on from there')
    if not have: adb(serial, 'shell', f': > {sh_quote(part)}')
    if have < size:   # the part grows to the whole file, and each piece is on the phone twice for a moment (as itself, then appended)
        folder, file = remote.rsplit('/', 1)
        need_room(serial, folder, size - have + min(CHUNK, size - have), f'{file} ({size_text(size - have)} left to send)')
    piece, tmp = log.with_suffix('.piece'), remote + '.piece'
    with counting('sending', size, 'B', lambda: (lambda a, b: None if a is None else a + (b or 0))(remote_size(serial, part), remote_size(serial, tmp))):
        with open(local, 'rb') as f:
            f.seek(have)
            while have < size:
                data = f.read(min(CHUNK, size - have)); piece.write_bytes(data)
                adb(serial, 'push', piece, tmp, log=log)
                adb(serial, 'shell', f'cat {sh_quote(tmp)} >> {sh_quote(part)} && rm {sh_quote(tmp)}')
                have += len(data)
    piece.unlink(missing_ok=True)
    if remote_size(serial, part) != size: raise BuildError(f'{part} is not {size:,} bytes after the copy: run the install again')
    adb(serial, 'shell', f'mv -f {sh_quote(part)} {sh_quote(remote)}')


MKDIRS_DONE = 'nxnative_mkdirs_done'   # the last line push_dir's folder script prints


def push_dir(serial, local, parent, name, log, sync=False):
    files = [f for f in local.rglob('*') if f.is_file()]
    if len(files) > TAR_FILES: return push_tar(serial, local, parent, name, files, log, sync)
    # <local folder> → <parent>/<name>: adb push copies a folder by its own name into the remote parent ("<folder>/." makes "/./" paths that adb cannot create
    # subfolders under on Windows); a folder named otherwise is pushed under its own name and renamed. adbd may not create folders under Android/data (its FUSE
    # mount refuses them: "secure_mkdirs() failed"), while the shell may: the whole tree is made first by a mkdir script run in the shell
    need_room(serial, parent, sum(f.stat().st_size for f in files), name)
    dirs = [f'{parent}/{local.name}'] + [f'{parent}/{local.name}/{d.relative_to(local).as_posix()}' for d in sorted(local.rglob('*')) if d.is_dir()]
    # set -e: the script's status was its last mkdir's, so one that failed in the middle went unnoticed until adb push stopped on the missing folder. The closing
    # line is checked too: an adb without the shell protocol reports 0 whatever the command did, and an empty script succeeds
    script = log.with_suffix('.mkdirs.sh')
    script.write_text('set -e\n' + ''.join(f'mkdir -p {sh_quote(d)}\n' for d in dirs) + f'echo {MKDIRS_DONE}\n', newline='\n')
    adb(serial, 'push', script, '/data/local/tmp/nxnative_mkdirs.sh')
    out = adb(serial, 'shell', 'sh', '/data/local/tmp/nxnative_mkdirs.sh')
    if MKDIRS_DONE not in out:
        raise BuildError(f'the folders for {name} were not made on the phone: the folder script stopped early, ' + (f'printing {out.strip()[-300:]}' if out.strip() else 'printing nothing'))
    with counting('sending', len(files), 'files', lambda: remote_files(serial, dirs[0])):
        adb(serial, 'push', *(['--sync'] if sync else []), local, f'{parent}/', log=log)
    if local.name != name:
        adb(serial, 'shell', 'rm', '-rf', f'{parent}/{name}'); adb(serial, 'shell', 'mv', f'{parent}/{local.name}', f'{parent}/{name}')


# Shaders a game compiles at run time with its own GLSLC: the app saves each new one on the phone (front_android.c DM_GLSLC_CAPTURE: games/<title ID>/glslc_capture, or
# glslc_capture/<title ID> where env.txt pointed it before), and every build or install of a game with a provisional profile pulls the ones this computer lacks into
# <version dir>/glslc_capture, where the shader split reads them. A registered profile's tables name the captures they were made from, so its games are left as they are
CAPTURE_DIRS = ('games/{id}/glslc_capture', 'glslc_capture/{id}')


def pull_captures(serial, gid, dest, logs):   # → how many new captures were copied to dest
    have = {f.name for f in dest.glob('*.glslc')} if dest.is_dir() else set()
    new = 0
    for rel in CAPTURE_DIRS:
        d = f'{REMOTE}/{rel.format(id=gid)}'
        names = [n.strip() for n in adb(serial, 'shell', f'ls {sh_quote(d)} 2>/dev/null', check=False).split() if re.fullmatch(r'[0-9a-f]{16}\.glslc', n.strip())]
        for n in names:
            if n in have: continue
            dest.mkdir(parents=True, exist_ok=True)
            adb(serial, 'pull', f'{d}/{n}', dest / n, log=logs / 'adb_pull_captures.log')
            have.add(n); new += 1
    if new: say(f'{new} new run-time shader(s) captured on the phone: copied to {dest}')
    return new


def open_tree(serial, d):
    # adb makes the folders as the shell user, drwxrws--- (group ext_data_rw): on Android 15 (a Galaxy S21 Ultra) the app could not enter them, found no game and ran its self test.
    # Opened to everyone; Android/data/<package> is reachable only by the app and the shell, so this gives no other app access
    # One chmod -R (rw for files, rwx for folders: X): find -exec chmod {} + overflowed the argument list on 37,000 shader files. The games folder too, which adb made the same way
    # A file the app made there itself (launcher.txt, its settings) is the app's: the shell may not chmod it ("Operation not permitted"), and the app needs no help to read it
    out = adb(serial, 'shell', f"chmod -R a+rwX {sh_quote(d)} 2>&1; chmod a+rwx {sh_quote(d.rsplit('/', 1)[0])} 2>&1", check=False)
    bad = [ln for ln in out.splitlines() if ln.strip() and 'Operation not permitted' not in ln]
    if bad: raise BuildError(f'opening {d} to the app failed: {"; ".join(bad)[:400]}')


def install(serial, apk, logs):   # an update (-r): the app's data, saves included, stay. Never uninstalled here: that would delete the saves
    if not KEYSTORE.is_file(): raise BuildError(f'no signing key {KEYSTORE}: the app on the phone could not be updated')
    try: adb(serial, 'install', '-r', apk, log=logs / 'adb_install.log')
    except BuildError as e:
        if 'INSTALL_FAILED_UPDATE_INCOMPATIBLE' in str(e):
            raise BuildError(f'the DroidPlay app ({PKG}) on the phone was signed with another key than {KEYSTORE}. Uninstalling it deletes its saves and game files: '
                             f'back up {REMOTE} and the saves first (the launcher\'s Back up saves), then uninstall it by hand and run this again') from e
        raise


def remote_exists(serial, path): return adb(serial, 'shell', f'[ -e {sh_quote(path)} ] && echo yes', check=False).strip() == 'yes'


def migrate_legacy(serial, gid, nacp_local=None):
    """The one-game layout (files/game, before the launcher) → files/games/<gid>, with a legacy_save marker: the app then copies its internal files/save to saves/<gid>
    (Launcher.java migrate, after a backup; files/save itself is left as it was). With nacp_local, only when the phone's game is that one (same control.nacp)
    → whether it moved"""
    old, new = f'{REMOTE}/game', f'{REMOTE}/games/{gid}'
    if not remote_exists(serial, f'{old}/code/main.fixups.tsv'): return False
    if nacp_local is not None:
        theirs = adb(serial, 'shell', f'sha256sum {sh_quote(old + "/control.nacp")}', check=False).split()[:1]
        if theirs != [hashlib.sha256(Path(nacp_local).read_bytes()).hexdigest()]:
            say(f'[RED] the phone has another game in {old} (the layout before the launcher): left as it is; move it with --migrate --title <its title ID>'); return False
    if remote_exists(serial, new): raise BuildError(f'{new} exists already: the old {old} is left as it is (remove one of them by hand)')
    adb(serial, 'shell', f'mkdir -p {sh_quote(REMOTE + "/games")} && mv {sh_quote(old)} {sh_quote(new)} && touch {sh_quote(new + "/legacy_save")}')
    open_tree(serial, new)
    say(f'moved the one-game install {old} to {new}: the app copies its save to that game when it next opens (after a backup in files/backups/)')
    return True


@says_when_phone_full
def push_game(serial, gid, game, patched, spv, font, aoc, defaults, work, logs, meta):
    """The game's files → files/games/<gid>/ (the RomFS with --sync: a repeat copies only what changed)"""
    dst = f'{REMOTE}/games/{gid}'
    # each device's copy logs, and the tar archives and RomFS pieces named after them, in a folder of its own: two installs at once (one per device) shared
    # adb_push_spv.tar, and one's cleanup removed the archive the other was sending
    logs = logs / f'push_{serial}'; logs.mkdir(parents=True, exist_ok=True)
    parts = ['the one-game install', 'font', 'code'] + ['shaders'] * bool(spv) + ['RomFS'] + ['DLC'] * aoc.is_dir() + ['launcher files', 'permissions']
    def part(name, step=None):   # the part in the step's name; the count is the part's files or bytes (counting), or the parts when it has none
        bi.PROG.set(step=f'{step or name} · part {parts.index(name) + 1} of {len(parts)}'); bi.PROG.set(done=parts.index(name), total=len(parts), unit='parts')
    part('the one-game install', 'looking for the one-game install'); migrate_legacy(serial, gid, game / 'control.nacp')
    adb(serial, 'shell', 'rm', '-rf', f'{dst}/code', f'{dst}/font', f'{dst}/{patched.name}'); adb(serial, 'shell', 'mkdir', '-p', dst)
    # an install cut short (the phone full, the cable out) can leave a folder's archive (push_tar) or a RomFS piece (push_resumable) behind: gigabytes that kept the
    # phone full, and that no install reuses. RomFS.img.partial stays, as the next copy goes on from it
    adb(serial, 'shell', f'rm -f {sh_quote(dst)}/.*.tar {sh_quote(dst + "/RomFS.img.piece")}', check=False)
    part('font'); push_dir(serial, font, dst, 'font', logs / 'adb_push_font.log')
    part('code'); push_dir(serial, patched, dst, 'code', logs / 'adb_push_code.log')
    if spv: part('shaders', 'shaders (only the changed files)'); push_dir(serial, spv, dst, 'spv', logs / 'adb_push_spv.log', sync=True)
    part('RomFS', 'RomFS (a large game takes a while; only a changed image is copied again)')
    rom = bi.rfs.source(game)   # the extraction's RomFS image (RomFS.img: the host reads it as it is, hle_fs.c), or a RomFS folder from an older extraction
    if bi.rfs.is_image(rom):   # not rom.is_file(): romfs.Path takes an image as its root folder
        # a RomFS.img folder left by an earlier push would make adb fail ("Is a directory"); a RomFS.img file stays, for --sync
        adb(serial, 'shell', f"rm -rf {sh_quote(dst + '/RomFS')}; if [ -d {sh_quote(dst + '/RomFS.img')} ]; then rm -rf {sh_quote(dst + '/RomFS.img')}; fi")
        # there whole, the same size and the same first and last MiB: kept. Not adb push --sync, which also compares modification times: push_resumable's image is
        # assembled on the phone (cat >>), so its time is the copy's, and --sync sent the whole image again on every install (Danganronpa V3's 6.7 GB)
        if remote_size(serial, f'{dst}/RomFS.img') == os.path.getsize(str(rom)) and same_ends(serial, Path(str(rom)), f'{dst}/RomFS.img'):
            say('RomFS.img: on the phone already (same size, first and last MiB)')
        else: push_resumable(serial, Path(str(rom)), f'{dst}/RomFS.img', logs / 'adb_push_romfs.log')
    else:
        adb(serial, 'shell', 'rm', '-f', f'{dst}/RomFS.img')
        push_dir(serial, rom, dst, 'RomFS', logs / 'adb_push_romfs.log', sync=True)
    if aoc.is_dir(): part('DLC'); push_dir(serial, aoc, dst, 'aoc', logs / 'adb_push_aoc.log', sync=True)
    part('launcher files')
    # the launcher (dm/android/java Launcher.java): the game's icon and control data (name, version, languages), its defaults (defaults_text) and
    # game.json; env.txt is the player's and stays as it is (a key it sets wins over the settings screen)
    for f in ('icon.jpg', 'control.nacp'):
        if (game / f).is_file(): adb(serial, 'push', game / f, f'{dst}/{f}')
    dflt = work / 'android_defaults.txt'; dflt.write_text(defaults, encoding='utf-8', newline='\n')   # \n on Windows too: the desktop app reads game.json by lines
    adb(serial, 'push', dflt, f'{dst}/defaults.txt')
    gj = work / 'android_game.json'; gj.write_text(json.dumps(meta, indent=1), encoding='utf-8', newline='\n')
    adb(serial, 'push', gj, f'{dst}/game.json')
    part('permissions'); open_tree(serial, dst)


# ---------------- --check and --info (JSON for the desktop app) ----------------
def tool_version(cmd):
    try: r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=30)
    except (OSError, subprocess.TimeoutExpired): return None
    return (r.stdout + r.stderr).strip() if r.returncode == 0 else None


def check(sdk_arg):
    rows = []
    def row(name, ok, detail, fix=''):
        if os.name == 'nt' and fix and not name.startswith('Python'): fix = "Install what's missing (the desktop app's Settings), or build_android_from_nsp.py --setup"
        rows.append({'name': name, 'ok': bool(ok), 'detail': detail, 'fix': '' if ok else fix})
    for m, pip in (('lz4.block', 'lz4'), ('capstone', 'capstone'), ('fontTools', 'fonttools'), ('PySide6', 'PySide6')):
        row(f'Python module {pip}', bi._importable(m), sys.executable, f'{sys.executable} -m pip install {pip}')
    z = bi._importable('compression.zstd') or bi._importable('backports.zstd')
    row('Python zstd', z, sys.executable, f'{sys.executable} -m pip install backports.zstd (or Python 3.14+)')
    env = dict(os.environ)
    try: bi.configure_dotnet(env); dn = tool_version(['dotnet', '--version'])
    except BuildError as e: dn = None; row('.NET SDK 10', False, str(e), 'install the .NET 10 SDK: https://dotnet.microsoft.com/download')
    else: row('.NET SDK 10', dn and dn.split('.')[0] == '10', dn or 'not found', 'install the .NET 10 SDK: https://dotnet.microsoft.com/download')
    try: sdk = sdk_dir(sdk_arg)
    except BuildError: sdk = None; row('Android SDK', False, 'not found', 'install Android Studio or the command-line tools, then set ANDROID_HOME (or give --sdk)')
    else: row('Android SDK', True, str(sdk))
    if sdk:
        for what, d in (('NDK', sdk / 'ndk'), ('CMake', sdk / 'cmake')):
            try: row(what, True, str(newest(d, what)))
            except BuildError as e: row(what, False, str(e), f'sdkmanager "{f"ndk;{NDK}" if what == "NDK" else f"cmake;{CMAKE}"}"')
        row(f'build-tools {BUILD_TOOLS}', (sdk / 'build-tools' / BUILD_TOOLS).is_dir(), str(sdk / 'build-tools' / BUILD_TOOLS), f'sdkmanager "build-tools;{BUILD_TOOLS}"')
        row(f'platform {PLATFORM}', (sdk / 'platforms' / PLATFORM / 'android.jar').is_file(), str(sdk / 'platforms' / PLATFORM), f'sdkmanager "platforms;{PLATFORM}"')
    a = tool_version(['adb', 'version'])
    row('adb', a, a.splitlines()[0] if a else 'not found', 'install the Android SDK platform-tools and put them on PATH')
    for t in ('keytool', 'javac'):
        v = shutil.which(t)
        if v and os.name == 'nt': v = str(Path(v).with_suffix(Path(v).suffix.lower()))   # which() spells the extension as PATHEXT does (javac.EXE), not as the file is named
        row(f'JDK {t}', v, v or 'not found', 'install a JDK (17 or newer) and put its bin folder on PATH')
    row('signing key', True, f'{KEYSTORE}' + ('' if KEYSTORE.is_file() else ' (made at the first build)'))
    hosts = library(); row('game hosts', True, f'{len(hosts)} in {data_dir() / "hosts"}' + (': ' + ', '.join(hosts) if hosts else ''))
    return rows


def setup(sdk_arg, accept):   # --setup: what check() finds missing, installed (host_setup.py), then checked again; the Python modules stay pip's (or uv run's)
    missing = {r['name'] for r in check(sdk_arg) if not r['ok']}
    try: sdk = sdk_dir(sdk_arg)
    except BuildError: sdk = Path(sdk_arg or os.path.join(os.environ.get('LOCALAPPDATA') or Path.home(), 'Android', 'Sdk')).expanduser()   # Android Studio's place
    try: done = host_setup.setup(missing, sdk, data_dir() / 'tools', sdk_packages(sdk), accept, bi.PROG, say)
    except host_setup.SetupError as e: raise BuildError(str(e)) from e
    host_setup.add_tool_paths(data_dir() / 'tools', sdk)
    still = [r for r in check(sdk_arg) if not r['ok']]
    if done: say(f'installed: {", ".join(done)}')
    if [r for r in still if not r['name'].startswith('Python')]: raise BuildError('still missing: ' + ', '.join(r['name'] for r in still))
    for r in still: say(f'{r["name"]} is missing: {r["fix"]}')


GRAPHICS_NAMES = {'nvn': 'NVN', 'vulkan': 'Vulkan', 'gl': 'OpenGL'}


def unsupported_graphics(gfx, name):   # why a game cannot be built for Android, from profile_guess.build_sources' (graphics API, reason); None for an NVN game
    # The Android host replays NVN on Vulkan (dm/android/gfx_vk.c) and has nothing for a game that calls Vulkan or OpenGL itself: the host's layers for those are
    # Metal (dm/gfx/vk/hle_vk.m, the GL layer). Built anyway, such a game stopped at launch on its first unimplemented vk* import (Hades, issue #112)
    api, why = gfx
    if api == 'nvn': return None
    return (f'{name} draws with {GRAPHICS_NAMES.get(api, api)}, not NVN ({why}). DroidPlay Core on Android runs NVN games only so far, '
            f'so this game cannot be built for Android yet')


def games_table():   # {title ID: {engine, graphics, build, sdk}} from dm/games/README.md's Games table
    out = {}
    for line in (REPO / 'dm/games/README.md').read_text(encoding='utf-8').splitlines():
        c = [x.strip() for x in line.strip().strip('|').split('|')]
        if len(c) == 6 and re.fullmatch(r'`[0-9A-F]{16}`', c[1]):
            out[c[1].strip('`')] = {'build': c[2], 'sdk': c[3], 'engine': c[4], 'graphics': c[5]}
    return out


def provisional_profile(gamemod, nsp_dir, app):   # the provisional profile an experimental build wrote (<NSP folder>/<id>_build/profile/<id>), joined to game.py's search path; None before the survey
    pdir = nsp_dir / f'{app:016X}_build' / 'profile'
    if not (pdir / f'{app:016X}' / 'game.tsv').is_file(): return None
    os.environ['DM_GAMES_DIR'] = os.pathsep.join([str(pdir)] + [d for d in os.environ.get('DM_GAMES_DIR', '').split(os.pathsep) if d and d != str(pdir)])
    return gamemod.load(f'{app:016X}')


def scan(src, keys, env, nsz=True):
    """The game in src as build_ipa_from_nsp.py's main finds it: (folder, title ID, fam, kind). src is a folder of NSPs / XCIs (kind None), a dump folder ('folder')
    or a NUP container ('nup': a .nup file, or the one .nup in the folder); the folder is where <title ID>_build goes. A NUP and a dump are not encrypted: no keys"""
    nup = bi.nup_file(src)
    folder = src.parent if src.is_file() else src
    if nup:
        app, fam = bi.scan_nup(nup)
        say(f'a NUP: {nup.name}, {app:016X}, {len(fam["updates"])} update(s), {len(fam["dlc"])} DLC')
        if fam['base'] is None: say(bi.pack_nup.NO_BASE)
        return folder, app, fam, 'nup'
    if bi.dump_folder(folder):
        app, fam = bi.scan_dump(folder)
        say(f'a dump folder: {app:016X}, {len(fam["updates"])} update(s), {len(fam["dlc"])} DLC')
        return folder, app, fam, 'folder'
    if not keys: raise BuildError('give -k <prod.keys>: the game is in NSP / XCI files, which are encrypted')
    with bi.package_reader(REPO, keys, env) as packages:
        app, fam = bi.scan_nsps(folder, packages.contents)
        packages.check_keys(fam)
    if nsz: fam = bi.decompress_nsz(folder, app, fam, keys, env)
    return folder, app, fam, None


def game_files(fam, kind):   # what the game was read from, for the desktop app: the NSPs, the NUP, or a dump's version folders
    if kind == 'nup': p = Path(fam['nup'].path); return [{'name': p.name, 'bytes': p.stat().st_size}]
    if kind == 'folder': return [{'name': p.name, 'bytes': bi.tree_size(p)[1]} for p in [fam['base'], *[p for _, p in fam['updates']]] if p]
    return [{'name': p.name, 'bytes': p.stat().st_size} for p in [fam['base'], *[p for _, p in fam['updates']], *[p for _, _, p in fam['dlc']]] if p]


def info(src, keys=None):
    sys.path.insert(0, str(REPO / 'dm/games')); import game as gamemod
    sys.path.insert(0, str(REPO / 'dm/tools')); import nacp
    env = dict(os.environ); bi.configure_dotnet(env)
    nsp_dir, app, fam, kind = scan(src, keys, env, nsz=False)
    tid = f'{app:016X}'; g = gamemod.by_title(app); prov = False
    if g is None: g = provisional_profile(gamemod, nsp_dir, app); prov = g is not None   # an experimental build's: its art, versions and host show like a profiled game's
    out = {'title_id': tid, 'folder': str(nsp_dir), 'profile': bool(g), 'provisional': prov, 'name': g.get('name', '') if g else '', 'table': games_table().get(tid),
           'android_tested': tid in ANDROID_TESTED, 'dlc': len(fam['dlc']), 'container': kind or 'nsp', 'files': game_files(fam, kind)}
    if g:
        have = bi.nsp_versions(fam)
        out['versions'] = sorted(have, key=bi.vnum); out['newest'] = max(have, key=bi.vnum)
        work = nsp_dir / f'{g.id}_build'; ex = work / 'extract'
        out['extracted'] = {}
        for v in out['versions']:
            d = ex / v
            if (d / 'control.nacp').is_file():
                rom = bi.rfs.source(d)
                out['extracted'][v] = {'icon': str(d / 'icon.jpg') if (d / 'icon.jpg').is_file() else None, 'name': nacp.name(d / 'control.nacp'),
                                       'display': nacp.version(d / 'control.nacp'), 'languages': nacp.languages(d / 'control.nacp'),
                                       'romfs_bytes': Path(rom).stat().st_size if bi.rfs.is_image(rom) else None,
                                       'built': (work / f'patched_android_{v}' / 'main.fixups.tsv').is_file(),
                                       'captures': len(list((d / 'glslc_capture').glob('*.glslc')))}   # run-time shaders on this computer (pull_captures)
        h = library().get(g.id); out['host'] = h[1] if h else None
    return out


# ---------------- main ----------------
def main(argv):
    ap = argparse.ArgumentParser(description='Pack a Switch game you own for Android (the DroidPlay app + the game files on the phone)')
    ap.add_argument('nsp_dir', nargs='?'); ap.add_argument('-k', '--keys', help='your prod.keys')
    ap.add_argument('-p', '--package', help='the version to pack (v0 = the base game; default: the newest in the folder)')
    ap.add_argument('-l', '--language', default='en-US', help='the game language (a code or a name; English by default)')
    ap.add_argument('--sdk', help='the Android SDK (default ANDROID_HOME)'); ap.add_argument('--serial', help='the adb device (default: the only one)')
    ap.add_argument('--no-push', action='store_true', help='build the APK only; do not install it or copy the game files to the phone')
    ap.add_argument('--push-only', action='store_true', help='install the app and copy a game built before to the phone, without building')
    ap.add_argument('--wait-device', type=float, default=0, help='wait up to this many seconds for a phone a bench or another build holds (default: stop at once)')
    ap.add_argument('--update-shaders', action='store_true', help='pull the shaders a game compiled at run time on the phone, translate the new ones and copy them (no app build)')
    ap.add_argument('--apk-only', action='store_true', help='pack the app with every game host built on this computer and install it')
    ap.add_argument('--migrate', action='store_true', help="move a one-game install's files/game to files/games/<--title> on the phone")
    ap.add_argument('--title', help='the title ID for --migrate')
    ap.add_argument('--check', action='store_true', help='print the requirements as JSON and stop')
    ap.add_argument('--info', action='store_true', help="print the NSP folder's game details as JSON and stop")
    ap.add_argument('--progress', choices=('auto', 'bar', 'lines', 'json', 'off'), default='auto', help='stage lines on the console; json = newline-delimited JSON events')
    ap.add_argument('--allow-damaged', action='store_true', help='pack files that fail the NCA hash check as read')
    ap.add_argument('--game-apk', action='store_true', help='the game in an app of its own, to install on any device (no phone needed; the DroidPlay app is left as it is)')
    ap.add_argument('--xapk', action='store_true', help='with --game-apk: one .xapk (the APK with the RomFS as its OBB file) for an XAPK installer')
    ap.add_argument('--out', help='with --game-apk: the folder for the app (default: the NSP folder)')
    ap.add_argument('--setup', action='store_true', help='install what --check finds missing (Windows: the JDK, the .NET SDK and the Android SDK)')
    ap.add_argument('--accept-android-licenses', action='store_true', help="with --setup: you accept the Android SDK License (https://developer.android.com/studio/terms)")
    a = ap.parse_args(argv)
    # adb is run by name: --sdk's platform-tools go on PATH too. The import-time tool_paths() only knew the SDK found without the options, so on a Mac with no
    # ANDROID_HOME and no adb on PATH, --sdk built the app and then stopped at its install with "No such file or directory: 'adb'"
    if a.sdk: tool_paths(a.sdk)
    global WAIT_DEVICE; WAIT_DEVICE = a.wait_device
    if a.xapk: a.game_apk = True
    if a.game_apk:
        if a.push_only or a.update_shaders or a.apk_only or a.migrate: raise BuildError('--game-apk builds the game; it goes with none of --push-only, --update-shaders, --apk-only, --migrate')
        a.no_push = True   # a game app goes to no phone from here
    bi.PROG.mode = bi.progress_mode('off' if a.check or a.info else a.progress); bi.ALLOW_DAMAGED = a.allow_damaged
    if not (a.check or a.info) and os.environ.get('NXNATIVE_JOURNAL', '1') != '0': bi.PROG = Journaled(bi.PROG.mode, argv)
    if a.check or a.info:   # stdout carries the JSON alone: messages on the way (say) go to stderr
        if a.info and not a.nsp_dir: raise BuildError('--info needs the NSP folder')
        with contextlib.redirect_stdout(sys.stderr): out = check(a.sdk) if a.check else info(Path(a.nsp_dir).expanduser().resolve(), Path(a.keys).expanduser().resolve() if a.keys else None)
        print(json.dumps(out, indent=1)); return
    if a.setup: setup(a.sdk, a.accept_android_licenses); return
    if a.apk_only or a.migrate:
        logs = data_dir() / 'logs'; logs.mkdir(parents=True, exist_ok=True)
        serial = a.serial or os.environ.get('ANDROID_SERIAL') or pick_device()
        if a.migrate:
            if not a.title or not re.fullmatch(r'[0-9A-Fa-f]{16}', a.title): raise BuildError('--migrate needs --title <the game\'s 16-digit title ID>')
            bi.PROG.plan(1); bi.PROG.stage('move the one-game install')
            with phone(serial, f'build_android_from_nsp.py: moving {a.title.upper()} to the launcher'):
                if not migrate_legacy(serial, a.title.upper()): say(f'nothing to move: no game in {REMOTE}/game')
            bi.PROG.end(); return
        bi.PROG.plan(2); env = dict(os.environ)
        bi.PROG.stage('APK'); apk = make_apk(sdk_dir(a.sdk), logs, env); bi.PROG.end(str(apk))
        bi.PROG.stage('install')
        with phone(serial, 'build_android_from_nsp.py: installing the app'): install(serial, apk, logs)
        bi.PROG.end(serial)
        return
    if not a.nsp_dir: raise BuildError('give the NSP folder (or the .nup file) and -k <prod.keys> (or --check / --apk-only / --migrate)')
    src, keys = Path(a.nsp_dir).expanduser().resolve(), Path(a.keys).expanduser().resolve() if a.keys else None
    if not src.exists(): raise BuildError(f'not a folder: {src}')
    if keys and not keys.is_file(): raise BuildError(f'no such file: {keys}')
    missing = [m for m in ('lz4.block', 'capstone') if not bi._importable(m)]
    if missing: raise BuildError(f'the current Python ({sys.executable}) is missing modules: {", ".join(missing)} (pip install lz4 capstone)')
    if not (bi._importable('compression.zstd') or bi._importable('backports.zstd')):   # the shader split decompresses zstd files (Python 3.14's compression.zstd, or its backport)
        raise BuildError(f'the current Python ({sys.executable}) has no zstd module: pip install backports.zstd (or use Python 3.14 or newer)')
    sys.path.insert(0, str(REPO / 'dm/games')); import game as gamemod
    import profile_guess; bi.pg = profile_guess
    sys.path.insert(0, str(REPO / 'dm/tools')); import nacp; bi.nacp = nacp
    sdk = sdk_dir(a.sdk)
    env = dict(os.environ); bi.configure_dotnet(env)
    nsp_dir, app, fam, kind = scan(src, keys, env)
    g = gamemod.by_title(app)
    if g is None:   # no game profile: surveyed and packed from a provisional profile outside the repository, as build_ipa_from_nsp.py does (the game may not boot)
        pdir = nsp_dir / f'{app:016X}_build' / 'profile'
        if (pdir / f'{app:016X}' / 'game.tsv').exists(): say(f'no game profile for {app:016X}: reusing the provisional profile from the last run (delete it to survey again)')
        else:   # the first experimental build only packs; once its provisional profile exists, it is built and installed like a profiled game's (to try it on a phone)
            if not a.no_push: raise BuildError(f'no game profile for {app:016X}: a game without one is first packed with --no-push (a survey, a provisional profile and an APK that may not boot)')
            facts = bi.survey(nsp_dir, app, fam, keys, REPO, sys.executable, env)
            facts['survey'] = str(nsp_dir / f'{app:016X}_survey' / 'survey.md')
            bi.write_profile(pdir / f'{app:016X}', app, facts)
        g = provisional_profile(gamemod, nsp_dir, app); env['DM_GAMES_DIR'] = os.environ['DM_GAMES_DIR']
        if g is None: raise BuildError(f'no provisional profile in {pdir}: the survey wrote none')
        say('[RED] provisional game profile: values guessed from the survey, the game may not boot; bring it up per docs/agents after packing')
    say(f'game profile: {g.id} ({g.get("name", "")})')
    builds = g.builds(); have = bi.nsp_versions(fam)
    pkg_ver = a.package or max(have, key=bi.vnum)
    if pkg_ver not in have: raise BuildError(f'version {pkg_ver} is not in the folder, which holds {", ".join(sorted(have, key=bi.vnum))}')
    # A version the profile does not register, or one whose shader tables' versions are not all in the folder, is packed from a profile derived from it (derive_profile below),
    # with its own shaders, as build_ipa_from_nsp.py's main does: Mario Kart World's NUP holds update 1.8.0 alone, and its profile registers the base game
    prov = not g.dir.resolve().is_relative_to((REPO / 'dm/games').resolve())   # its captures are pulled (pull_captures)
    derived = ''
    if not prov:
        need = g.words('shader_versions')
        registered = ', '.join(f'{v} {b["display"]}' for v, b in builds.items())
        if pkg_ver not in builds: derived = f'{pkg_ver} is not a version game profile {g.id} registers ({registered})'
        elif not all(v in have for v in need): derived = f'the folder has no {", ".join(v for v in need if v not in have)}, whose files game profile {g.id}\'s shader tables were made from'
        if derived: say(f'{derived}: packing {pkg_ver} from a profile derived from it')
    work = nsp_dir / f'{g.id}_build'; logs = work / 'logs'; ex = work / 'extract'
    ex.mkdir(parents=True, exist_ok=True); (work / 'tmp').mkdir(exist_ok=True)
    env.update(DM_GAME=g.id, DM_ROOT=str(work), WORK=str(work / 'tmp'), DM_TARGET='android', PYTHONUTF8='1')   # the tools' text files in UTF-8 on Windows too (its default is the ANSI code page)
    patched = work / f'patched_android_{pkg_ver}'
    serial = None if a.no_push else a.serial or os.environ.get('ANDROID_SERIAL')
    if not a.no_push and not serial:   # the phone now (its captures are pulled before the shader stages); none connected fails at the install, as before, unless only the phone is wanted
        try: serial = pick_device()
        except BuildError:
            if a.push_only or a.update_shaders: raise
    capture_dir = ex / pkg_ver / 'glslc_capture'
    if a.push_only or a.update_shaders:   # what an earlier build left: the extraction, the rewrite, the shaders, the font and the host in the library
        game, spv, font = ex / pkg_ver, work / 'spv', work / 'font'
        need = [p for p in (game / 'control.nacp', patched / 'main.fixups.tsv', font) if not p.exists()]
        if need or g.id not in library(): raise BuildError(f'{g.id} {pkg_ver} was not built on this computer yet ({", ".join(map(str, need)) or "no host in the library"}): build it first')
        if not spv.is_dir(): spv = None
        new = pull_captures(serial, g.id, capture_dir, logs) if prov else 0
        if a.update_shaders and not prov: say('a registered profile: its shader tables name the captures they were made from, nothing is pulled')
        bi.PROG.plan((0 if a.update_shaders else 3) + 2 * bool(new) + bool(a.update_shaders))
        if new:   # the split again with the new captures, and the new ones translated (the others are kept)
            aoc = work / 'aoc'; dlc_roms = sorted(p for p in aoc.iterdir() if p.is_dir() or p.suffix == '.img') if aoc.is_dir() else []
            spv = build_shaders(g.words('shader_versions') or [pkg_ver], {pkg_ver: game}, work, logs, env, g, dlc_roms) or spv
        if a.update_shaders:
            if not new: say('no new run-time shaders on the phone'); bi.PROG.end(); return
            bi.PROG.stage('copy the shaders to the phone'); dst = f'{REMOTE}/games/{g.id}'
            adb(serial, 'shell', 'am', 'force-stop', PKG)   # the game reads its shaders when it starts
            if spv: push_dir(serial, spv, dst, 'spv', logs / 'adb_push_spv.log', sync=True); open_tree(serial, f'{dst}/spv')
            bi.PROG.end(f'{dst}/spv'); say('done: open the game again on the phone'); return
    else:
        # the shaders are split from every version the profile's shader tables were made from (shader_versions), as the iOS build does
        sv = [pkg_ver] if derived else g.words('shader_versions') or [pkg_ver]
        if not all(v in have for v in sv): say(f'[RED] the folder has no {", ".join(v for v in sv if v not in have)}, whose files the profile shader tables were made from: no shaders are translated'); sv = []
        picks = bi.pick_nsps(fam, have, sorted(set(sv) | {pkg_ver}, key=bi.vnum))
        bi.PROG.plan(4 + (not kind) + 2 * bool(sv) + len(set(sv) - {pkg_ver}) + bool(fam['dlc']) + (not a.no_push))   # an extraction per other shader version, and the DLC's
        nx = None
        if not kind: bi.PROG.stage('build nx_extract'); nx = build_nx_extract(work, logs, env); bi.PROG.end()   # a NUP or a dump folder is read without it
        def extract(v):   # one version into extract/<v>, as build_ipa_from_nsp.py's main does: a NUP's packages, a dump's folders, or the NSPs through nx_extract
            b, u = picks[v]
            if kind == 'nup': return bi.extract_nup(ex, v, u or b, b, app, fam['nup'])
            if kind == 'folder': return bi.extract_dump(ex, v, u or b, app)
            return bi.extract(nx, keys, ex, v, b, u, None, logs, g, app)
        game = extract(pkg_ver)
        why = unsupported_graphics(bi.pg.build_sources(game / 'ExeFS', bi.rfs.source(game), g.words('modules') or ['main'])['graphics'],
                                   nacp.name(game / 'control.nacp') or g.get('name', '') or g.id)
        if why: raise BuildError(why)   # before the rewrite and the shaders, which take minutes and make an app that cannot start
        bad = [] if derived or prov else bi.build_mismatch(game, pkg_ver, g)
        if bad:   # files of another build under a registered version's tag: packed like any other version
            derived = f'not the builds game profile {g.id} registers: {"; ".join(bad)}'; sv = [pkg_ver]
            say(f'{derived}: packing {pkg_ver} from a profile derived from it')
        reg = g   # the profile as registered (refine_after_rewrite checks a derived build's keys against it)
        if derived:   # where a provisional profile goes (<id>_build/profile), and game.py (the host's CMake, the shader tools) takes it first (DM_GAMES_FIRST)
            pdir = work / 'profile'
            disp = bi.derive_profile(g, pdir / g.id, pkg_ver, game, g.words('modules'), app)
            os.environ['DM_GAMES_DIR'] = env['DM_GAMES_DIR'] = os.pathsep.join([str(pdir)] + [d for d in os.environ.get('DM_GAMES_DIR', '').split(os.pathsep) if d and d != str(pdir)])
            os.environ['DM_GAMES_FIRST'] = env['DM_GAMES_FIRST'] = '1'
            g = gamemod.load(g.id)
            say(f'derived game profile for {pkg_ver} ({disp}): {g.dir}')
        g = bi.rewrite(sys.executable, REPO, game / 'ExeFS', patched, env, logs, g, bool(prov))
        if prov or derived: bi.provisional_prep(sys.executable, REPO, env, logs, g); g = bi.refine_after_rewrite(g, game, patched, reg if derived else None)
        # the DLC in the folder, as for iOS: <id>_build/aoc/<index>.img, which push_game copies to the game's aoc/ and the host mounts and reports as owned (DM_AOC_DIR).
        # It was not extracted for Android: The Binding of Isaac's Repentance (DLC 010021C000B6B001) started as Afterbirth+
        aoc = bi.extract_aoc(nx, keys, REPO, work, app, fam, logs)
        if prov and serial: pull_captures(serial, g.id, capture_dir, logs)
        dlc_roms = sorted(p for p in aoc.iterdir() if p.is_dir() or p.suffix == '.img') if aoc else []
        sdirs = {v: (game if v == pkg_ver else extract(v)) for v in sv}
        if sv and bi.pg.build_sources(game / 'ExeFS', bi.rfs.source(game), g.words('modules') or ['main'])['ue_decode'][0]:   # Unreal's Oodle-compressed shaders (ue_decode)
            with phone(serial, f'build_android_from_nsp.py: decoding {g.id}\'s Unreal shaders') if serial else contextlib.nullcontext():
                ue_decode(sdirs, pkg_ver, nsp_dir, patched, work, logs, env, g, serial, sdk, game)
        spv = build_shaders(sv, sdirs, work, logs, env, g, dlc_roms)
        bi.PROG.stage('Android host'); so, loader, ndk = build_host(sdk, g.id, work, logs, env); st = build_selftest(ndk, work, logs, env)
        if not a.game_apk: library_add(g.id, so, loader, st, {'title_id': g.id, 'name': nacp.name(game / 'control.nacp') or g.get('name', ''), 'version': pkg_ver,
                                            'display': nacp.version(game / 'control.nacp'), 'nsp_dir': str(nsp_dir)})
        bi.PROG.end(str(so))
        font = button_font(work, logs, env)
    have_l = nacp.languages(game / 'control.nacp')
    lang = bi.game_language(bi.language_code(a.language) or 'en-US', a.language != 'en-US', have_l)
    defaults = defaults_text(g, lang)
    label = nacp.name(game / 'control.nacp') or g.get('name', '') or g.id
    if a.game_apk:
        rom = bi.rfs.source(game)
        meta = {'title_id': g.id, 'name': label, 'version': pkg_ver, 'display': nacp.version(game / 'control.nacp'),
                'romfs_bytes': Path(rom).stat().st_size if bi.rfs.is_image(rom) else None}
        bi.PROG.stage('game app')
        made, inside = make_game_app(sdk, g, game, patched, spv, font, work / 'aoc', defaults, so, meta, work, logs, env,
                                     Path(a.out).expanduser().resolve() if a.out else nsp_dir, a.xapk)
        bi.PROG.end(str(made[0]))
        if a.xapk: say(f'done: {made[0]}. Install it with an XAPK installer on the device; it puts the game data in Android/obb. Or unzip it, install the APK and copy Android/obb/ to the device')
        elif inside: say(f'done: {made[0]}, the game with its data inside. Install it on any Android device (arm64, Vulkan)')
        else: say(f'done: {made[0]} and {made[1].name}. Install the APK, put {made[1].name} anywhere on the device or its SD card, and pick it when the app first opens')
        return
    bi.PROG.stage('APK'); apk = make_apk(sdk, logs, env); bi.PROG.end(str(apk))
    if a.no_push:
        say(f'done: {data_dir() / "nxnative.apk"}. On the phone: install it, then copy {patched} to {REMOTE}/games/{g.id}/code and {bi.rfs.source(game)} to {REMOTE}/games/{g.id}/'); return
    bi.PROG.stage('install and copy to the phone')
    serial = serial or pick_device()
    with phone(serial, f'build_android_from_nsp.py: installing {label} ({g.id})'):
        bi.PROG.set(step='installing the app (an update keeps its data)'); install(serial, apk, logs)   # words that hold for a first install too, with no adb call to tell them apart
        adb(serial, 'shell', 'am', 'force-stop', PKG)
        rom = bi.rfs.source(game)
        push_game(serial, g.id, game, patched, spv, font, work / 'aoc', defaults, work, logs,
                  {'title_id': g.id, 'name': label, 'version': pkg_ver, 'display': nacp.version(game / 'control.nacp'),
                   'romfs_bytes': Path(rom).stat().st_size if bi.rfs.is_image(rom) else None})
    bi.PROG.end(f'{REMOTE}/games/{g.id}')
    say(f'done: open DroidPlay on the phone and pick "{label}". Log: {REMOTE}/log.txt (adb logcat -s DroidPlay)')


if __name__ == '__main__':
    code = 1
    try: main(sys.argv[1:]); code = 0
    except BuildError as e:
        bi.PROG.close(ok=False); bi.PROG.say(f'[RED] {e}'); sys.exit(1)
    except SystemExit as e: code = e.code if isinstance(e.code, int) else (0 if e.code is None else 1); raise
    except KeyboardInterrupt: code = 130; raise
    finally:
        bi.PROG.close(ok=False)
        if isinstance(bi.PROG, Journaled): bi.PROG.exit(code)
