# Packs the Android app (no Gradle): the manifest linked by aapt2, lib/arm64-v8a/ (the loader libnxloader.so and a host per game, libdmhost_<title ID>.so), classes.dex
# from dm/android/java (javac, then d8), the self test in assets/selftest (the synthetic module of dm/android/tests/selftest_nso.py, rewritten with DM_TARGET=android),
# page-aligned by zipalign, signed by apksigner.
# Usage: build_apk.py --sdk <Android SDK> --loader <libnxloader.so> --so <libdmhost_<id>.so> [--so ...] --selftest <folder of main.patched.bin, main.fixups.tsv, ...>
#   [--lib <lib*.so> ...] [--demo <folder>] --keystore <.jks> -o <out.apk> [--label <app name>] [--icon <icon.jpg or .png>] [--build-tools 36.0.0] [--platform android-35]
# --lib: another library for lib/arm64-v8a/, in either kind of app: libadrenotools.so and its hooks libhook_impl.so and libmain_hook.so, which DM_VK_DRIVER opens a Vulkan
#   driver of the player's through (dm/android/vk_driver.c)
# The app is "DroidPlay" (package org.nxnative.android) with DroidPlay's adaptive icon in apk/res: its launcher shows the games' own icons and names. --label and
# --icon name it otherwise.
# A game app instead: build_apk.py --sdk <SDK> --game-app <title ID> --so libdmhost_<title ID>.so --game-dir <folder> [--romfs <RomFS.img>] --keystore <.jks> -o <out.apk>
#   --label <name> --icon <icon.jpg>: one game in an app of its own (apk/AndroidManifest.game.xml, package game_package(<title ID>)), entered through GameStart with no
#   launcher or loader. --game-dir is the game's folder as the launcher's games/<title ID>/ holds it, packed into assets/game/; --romfs packs the RomFS image there as a
#   stored entry, which GameStart hands to the host where it lies in the APK. The APK stays a plain ZIP (no ZIP64, which apksigner can't read): Python's zipfile
#   keeps it under 2 GiB, so a bigger game ships its RomFS, and its DLC if need be, beside the APK (build_android_from_nsp.py --game-apk, make_game_app).
# The keystore is made on first use (keytool, a debug key: alias nxnative, password "android"); keep it outside the repository.
import argparse, os, shutil, subprocess, sys, tempfile, zipfile
from xml.sax.saxutils import quoteattr

HERE = os.path.dirname(os.path.abspath(__file__))


def game_package(title_id):   # a game app's package: a name segment may not start with a digit, as a title ID does
    return 'org.nxnative.game.t' + title_id.lower()

# Why a game app's ZIP stopped: zipfile raises the same LargeZipFile for each limit of a ZIP without ZIP64 ("Files count", or the bytes: "Filesize", "Zipfile size",
# "Central directory offset" / "size" … would require ZIP64 extensions), and the message once said 2 GiB for all of them, so a game with too many files was told its RomFS was too big (droidplay-core
# issue #169). writing: the entry being added, its size, how many entries the ZIP had and its bytes written
def zip64_message(out, why, writing):
    arc, size, entries, written = writing
    if str(why).startswith('Files count'):
        limit = f'reached {entries:,} entries, and an APK without ZIP64, which apksigner needs, holds at most 65,535'
    else:
        limit = f'passed 2 GiB ({written:,} bytes written), more than an APK without ZIP64, which apksigner needs, holds'
    return (f'{out}: the game app {limit}, while {arc} ({size:,} bytes) was being added ({why}). build_android_from_nsp.py --game-apk weighs the parts and counts '
            'their files before packing, packs the shaders into one file and puts the RomFS and the DLC beside the APK when they don\'t fit (make_game_app)')

def run(*a):
    r = subprocess.run(a, capture_output=True, text=True, errors='replace')
    if r.returncode: sys.exit(f'{a[0]} failed ({r.returncode}):\n{r.stdout}{r.stderr}')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sdk', required=True); ap.add_argument('--selftest', help='the self test module (the launcher app; not a game app)')
    ap.add_argument('--so', action='append', required=True, help='a game host, libdmhost_<title ID>.so (once per game)'); ap.add_argument('--loader', help='libnxloader.so (the launcher app; not a game app)')
    ap.add_argument('--lib', action='append', default=[], help='another native library for lib/arm64-v8a/ (libadrenotools.so and its hooks)')
    ap.add_argument('--game-app', metavar='TITLE_ID', help='a game app: that game alone, entered through GameStart (its host is the one --so)')
    ap.add_argument('--game-dir', help="a game app's files, the launcher's games/<title ID>/ layout, for assets/game/"); ap.add_argument('--romfs', help="a game app's RomFS image, stored in assets/game/")
    ap.add_argument('--demo', help='folder for assets/demo: the synthetic shaders and their SPIR-V (tests/synth_shaders.py, tools/spv_android.py)')
    ap.add_argument('--keystore', required=True); ap.add_argument('-o', '--out', required=True)
    ap.add_argument('--label', help="the app's name in the launcher (default DroidPlay)"); ap.add_argument('--icon', help="the app's launcher icon: a JPEG or PNG (the game's icon.jpg)")
    ap.add_argument('--build-tools', default='36.0.0'); ap.add_argument('--platform', default='android-35')
    ap.add_argument('--version-name', help="the app's version, as Android's settings and DroidPlay's Phones page show it (the manifest's 0.1 otherwise)")
    a = ap.parse_args()
    for so in a.so:
        n = os.path.basename(so)
        if not (n.startswith('libdmhost_') and n.endswith('.so')): sys.exit(f'--so must be a game host named libdmhost_<title ID>.so: {so}')
    for lib in a.lib:
        n = os.path.basename(lib)
        if not (n.startswith('lib') and n.endswith('.so')) or n.startswith('libdmhost_') or n == 'libnxloader.so': sys.exit(f'--lib takes another lib<name>.so than a host or the loader: {lib}')
    if a.game_app:
        if len(set(a.so)) != 1 or os.path.basename(a.so[0]) != f'libdmhost_{a.game_app.upper()}.so': sys.exit(f'--game-app {a.game_app} takes one --so, libdmhost_{a.game_app.upper()}.so')
        if not a.game_dir or not os.path.isfile(os.path.join(a.game_dir, 'game.json')): sys.exit('--game-app needs --game-dir with the game\'s files (game.json among them)')
    elif not (a.loader and a.selftest): sys.exit('the launcher app needs --loader and --selftest')
    bt = os.path.join(a.sdk, 'build-tools', a.build_tools); exe = '.exe' if os.name == 'nt' else ''; bat = '.bat' if os.name == 'nt' else ''
    jar = os.path.join(a.sdk, 'platforms', a.platform, 'android.jar')
    if not os.path.exists(a.keystore):
        run('keytool', '-genkeypair', '-keystore', a.keystore, '-storepass', 'android', '-keypass', 'android', '-alias', 'nxnative',
            '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000', '-dname', 'CN=nxnative debug')
    with tempfile.TemporaryDirectory() as d:
        base = os.path.join(d, 'base.apk'); aapt2 = os.path.join(bt, 'aapt2' + exe)
        # the manifest with the app's label and icon: the application element's label replaced, an icon attribute added beside it (a drawable compiled by aapt2)
        with open(os.path.join(HERE, '..', 'apk', 'AndroidManifest.game.xml' if a.game_app else 'AndroidManifest.xml'), encoding='utf-8') as f: manifest = f.read()
        if a.game_app: manifest = manifest.replace('@PACKAGE@', game_package(a.game_app)).replace('@LIB@', f'dmhost_{a.game_app.upper()}')
        # the label always: the application element's is replaced whole, and an app with none shows its package name (org.nxnative.android)
        attrs, res = f' android:label={quoteattr(a.label or "DroidPlay")}', []
        if a.icon:
            ext = os.path.splitext(a.icon)[1].lower()
            if ext not in ('.jpg', '.jpeg', '.png'): sys.exit(f'--icon must be a JPEG or PNG: {a.icon}')
            rd = os.path.join(d, 'res', 'drawable'); os.makedirs(rd); shutil.copyfile(a.icon, os.path.join(rd, 'icon' + ('.jpg' if ext == '.jpeg' else ext)))
            run(aapt2, 'compile', '--dir', os.path.join(d, 'res'), '-o', os.path.join(d, 'res.zip')); res = ['-R', os.path.join(d, 'res.zip'), '--auto-add-overlay']
            attrs += ' android:icon="@drawable/icon" android:roundIcon="@drawable/icon"'
        else:   # the app's own adaptive icon (apk/res: DroidPlay's controller on its light green, vector drawables, with a monochrome layer for themed icons)
            run(aapt2, 'compile', '--dir', os.path.join(HERE, '..', 'apk', 'res'), '-o', os.path.join(d, 'res.zip')); res = ['-R', os.path.join(d, 'res.zip'), '--auto-add-overlay']
            attrs += ' android:icon="@mipmap/ic_launcher" android:roundIcon="@mipmap/ic_launcher"'
        if attrs:
            if '<application android:label="DroidPlay"' not in manifest: sys.exit('AndroidManifest.xml: no <application android:label="DroidPlay"> to name the app in')
            manifest = manifest.replace('<application android:label="DroidPlay"', '<application' + attrs, 1)
        mf = os.path.join(d, 'AndroidManifest.xml')
        with open(mf, 'w', encoding='utf-8') as f: f.write(manifest)
        # the version name only: the version code stays 1, as a lower code than the installed app's would make adb refuse the update
        ver = ['--version-name', a.version_name, '--replace-version'] if a.version_name else []
        run(aapt2, 'link', '-o', base, '--manifest', mf, '-I', jar, *res, '--min-sdk-version', '29', '--target-sdk-version', '34', *ver)
        # the Java side (the touch controls, the text box): javac for Java 8 against the platform's android.jar, then d8 to classes.dex
        src = os.path.join(HERE, '..', 'java'); cls = os.path.join(d, 'classes'); os.makedirs(cls)
        javas = [os.path.join(r, f) for r, _, fs in os.walk(src) for f in fs if f.endswith('.java')]
        run('javac', '-source', '8', '-target', '8', '-Xlint:-options', '-encoding', 'UTF-8', '-bootclasspath', jar, '-d', cls, *javas)
        # d8 gets the classes as one jar: on Windows d8.bat runs through cmd.exe, whose 8,191-character line the class files' paths passed in 0.8.7 (89 classes under
        # a temporary folder), so every APK build there failed (droidplay-core issue #462)
        cjar = os.path.join(d, 'classes.jar')
        with zipfile.ZipFile(cjar, 'w') as z:
            for r, _, fs in os.walk(cls):
                for f in sorted(fs):
                    if f.endswith('.class'): z.write(os.path.join(r, f), os.path.relpath(os.path.join(r, f), cls).replace(os.sep, '/'))
        run(os.path.join(bt, 'd8' + bat), '--lib', jar, '--min-api', '29', '--output', d, cjar)
        # a game app's ZIP without ZIP64 (allowZip64=False: past 2 GiB zipfile raises instead of writing records apksigner can't read). What was being written when it
        # did is named: the message used to advise packing the RomFS beside the APK, which a game whose other files passed 2 GiB already did (droidplay-core issue #169)
        writing = ['', 0, 0, 0]
        def put(z, path, arc, **kw): writing[:] = [arc, os.path.getsize(path), len(z.filelist), z.fp.tell() if z.fp else 0]; z.write(path, arc, **kw)
        try:
            with zipfile.ZipFile(base, 'a', zipfile.ZIP_DEFLATED, allowZip64=not a.game_app) as z:
                put(z, os.path.join(d, 'classes.dex'), 'classes.dex')
                if a.loader: put(z, a.loader, 'lib/arm64-v8a/libnxloader.so')
                for so in sorted(set(a.so)): put(z, so, f'lib/arm64-v8a/{os.path.basename(so)}')
                for lib in sorted(set(a.lib), key=os.path.basename): put(z, lib, f'lib/arm64-v8a/{os.path.basename(lib)}')
                if a.selftest:
                    n = 0
                    for f in sorted(os.listdir(a.selftest)):
                        if f.startswith('main.'): put(z, os.path.join(a.selftest, f), f'assets/selftest/{f}'); n += 1
                    if not n: sys.exit(f'no self test module (main.*) in {a.selftest}')
                for f in sorted(os.listdir(a.demo)) if a.demo else []: put(z, os.path.join(a.demo, f), f'assets/demo/{f}')
                if a.game_app:
                    # the game's files as games/<title ID>/ holds them (folders given as links are followed), then the RomFS image stored: GameStart opens it with
                    # AssetManager.openFd, which takes only an uncompressed entry, and the host reads it at its offset in the APK
                    for root, _, fs in sorted(os.walk(a.game_dir, followlinks=True)):
                        for f in sorted(fs):
                            path = os.path.join(root, f); rel = os.path.relpath(path, a.game_dir).replace(os.sep, '/')
                            if rel != 'RomFS.img': put(z, path, f'assets/game/{rel}')
                    if a.romfs: put(z, a.romfs, 'assets/game/RomFS.img', compress_type=zipfile.ZIP_STORED)
        except zipfile.LargeZipFile as why:   # (only a game app's ZIP is written without ZIP64)
            sys.exit(zip64_message(a.out, why, writing))
        aligned = os.path.join(d, 'aligned.apk')
        run(os.path.join(bt, 'zipalign' + exe), '-f', '-P', '16', '4', base, aligned)   # stored entries (a game app's RomFS) on 4 bytes, the libraries on 16 KiB pages
        run(os.path.join(bt, 'apksigner' + bat), 'sign', '--ks', a.keystore, '--ks-pass', 'pass:android', '--key-pass', 'pass:android', '--out', a.out, aligned)
    print(f'{a.out}: {os.path.getsize(a.out):,} bytes')

if __name__ == '__main__':
    main()
