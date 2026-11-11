"""The Android packing script's machine-readable side and its phone copy (scripts/build_android_from_nsp.py), as the desktop app (scripts/nxnative_android.py) uses them:
--check prints its requirement rows as JSON alone on stdout; the games table is read from dm/games/README.md; the host library keeps one host per game and the APK is made
from all of them; a game is copied to files/games/<title ID>/ and its folders opened to the app (Android 15 kept it out of adb's drwxrws--- folders); a one-game install
(files/game) of the same game is moved there with its legacy_save marker, one of another game is left alone. No phone, SDK or game files needed (adb is a recording stand-in)."""
import hashlib
import http.server
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from typing import Any
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / 'scripts/build_android_from_nsp.py'
spec = importlib.util.spec_from_file_location('build_android_from_nsp', SCRIPT)
assert spec and spec.loader
ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)
spec = importlib.util.spec_from_file_location('update', REPO / 'dm/android/desktop/update.py')
assert spec and spec.loader
upd = importlib.util.module_from_spec(spec); spec.loader.exec_module(upd)
GID = '010015100B514000'


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.said = []
        for cm in (mock.patch.object(ba.bi, 'PROG', mock.Mock()), mock.patch.object(ba, 'say', self.said.append), mock.patch.object(ba, 'data_dir', lambda: self.tmp / 'data')):
            cm.__enter__(); self.addCleanup(cm.__exit__, None, None, None)


class Json(unittest.TestCase):
    def test_check_prints_only_json_rows(self):
        r = subprocess.run([sys.executable, SCRIPT, '--check'], capture_output=True, text=True, encoding='utf-8', timeout=300)
        self.assertEqual(r.returncode, 0, r.stderr)
        rows = json.loads(r.stdout)
        self.assertTrue(rows and all(set(x) == {'name', 'ok', 'detail', 'fix'} for x in rows))
        names = {x['name'] for x in rows}
        for want in ('Android SDK', 'adb', 'JDK keytool', '.NET SDK 10', 'Python module lz4'): self.assertIn(want, names)
        self.assertTrue(all(x['fix'] == '' for x in rows if x['ok']))

    def test_games_table(self):
        t = ba.games_table()
        self.assertIn(GID, t)
        self.assertEqual(t[GID]['graphics'], 'NVN')
        self.assertTrue(all(len(k) == 16 for k in t))

    def test_only_nvn_games_build(self):   # issue #112: Hades (Vulkan) was built, then stopped at launch on its first vk* import
        self.assertIsNone(ba.unsupported_graphics(('nvn', 'main imports nvnBootstrapLoader'), 'Odyssey'))
        why = ba.unsupported_graphics(('vulkan', 'main imports 40 Vulkan functions and not nvnBootstrapLoader'), 'Hades')
        self.assertIn('Hades draws with Vulkan, not NVN', why); self.assertIn('NVN games only', why)
        self.assertIn('with OpenGL', ba.unsupported_graphics(('gl', 'main imports eglCreateWindowSurface'), 'Digimon'))
        t = ba.games_table()   # no game played on Android is one the table lists as drawing without NVN
        self.assertEqual([g for g in ba.ANDROID_TESTED if g in t and 'NVN' not in t[g]['graphics']], [])

    def test_games_played_on_android_have_profiles(self):   # a mistyped title ID would leave its game shown as not played on Android
        t = ba.games_table()
        self.assertTrue(ba.ANDROID_TESTED)
        self.assertEqual(sorted(g for g in ba.ANDROID_TESTED if g not in t), [])

    def test_game_status_rows_start_with_a_tier(self):   # the README's tiers spelled as its tier table spells them: a hyphen typed for the en dash, or a bare "Playable", fails
        tiers = ('Playable – minor issues through ', 'Playable – major issues through ', 'In-game', 'Menus', 'Boots', "Doesn't run")
        table = (REPO / 'README.md').read_text(encoding='utf-8').split('| Game | Device | State |\n|---|---|---|\n', 1)[1].split('\n\n', 1)[0]
        rows = [[c.strip() for c in line[1:-1].split('|')] for line in table.splitlines()]
        self.assertGreater(len(rows), 10)
        self.assertEqual([r[0] for r in rows if len(r) != 3], [])
        self.assertEqual([r[0] for r in rows if not r[2].lstrip('*').startswith(tiers)], [])

    def test_playable_now_names_the_playable_rows(self):   # the README's "Playable now" lines above Game Status repeat the table for players, so a row that moves tier moves there too
        readme = (REPO / 'README.md').read_text(encoding='utf-8')
        table = readme.split('| Game | Device | State |\n|---|---|---|\n', 1)[1].split('\n\n', 1)[0]
        rows = [[c.strip() for c in line[1:-1].split('|')] for line in table.splitlines()]
        name = lambda game: re.sub(r' \(Switch 2\)$', '', game.strip('*')).rsplit(' ', 1)[0]   # the game without its version: "Persona 3 Portable 1.0.2"
        for tier in ('Playable – minor issues', 'Playable – major issues'):
            line = re.search(rf'^- \*\*{tier}:\*\* (.+)$', readme, re.M)
            assert line, f'README.md: no "- **{tier}:**" line under Playable now'
            want = sorted(name(r[0]) for r in rows if r[2].lstrip('*').startswith(tier))
            self.assertEqual(sorted(name(r[0]) for r in rows if name(r[0]) in line.group(1)), want, f'README.md: the "{tier}" line under Playable now')


class Windows(unittest.TestCase):
    def test_loads_where_python_has_no_fcntl(self):   # Windows: build_ipa_from_nsp.py loads tree_tar.py, which imports fcntl; dm/android/tools/compat's stand-in is found
        code = '\n'.join([
            'import importlib.machinery, importlib.util, sys',
            'class NoFcntl:   # the platform has no fcntl, as on Windows: only a stand-in on the path is found',
            '    def find_spec(self, name, path=None, target=None):',
            "        if name != 'fcntl': return None",
            "        spec = importlib.machinery.PathFinder.find_spec(name, [p for p in sys.path if p.endswith('compat')])",
            "        if spec is None: raise ModuleNotFoundError(\"No module named 'fcntl'\")",
            '        return spec',
            "sys.modules.pop('fcntl', None); sys.meta_path.insert(0, NoFcntl())",
            f"spec = importlib.util.spec_from_file_location('build_android_from_nsp', {str(SCRIPT)!r})",
            'ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)',
            'import fcntl, tree_tar',
            'print(fcntl.__file__)',
            'try: fcntl.flock(0, fcntl.LOCK_EX | fcntl.LOCK_NB)',
            "except OSError: print('no lock')",
        ])
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, encoding='utf-8', timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        where, lock = r.stdout.splitlines()
        self.assertEqual(Path(where), REPO / 'dm/android/tools/compat/fcntl.py')
        self.assertEqual(lock, 'no lock')

    def test_packages_are_read_with_this_scripts_nx_extract(self):   # build_ipa_from_nsp.py's package_reader builds its own, which looked for nx_extract, not Windows' nx_extract.exe
        with mock.patch.object(ba, 'build_nx_extract', return_value='nx') as built:
            self.assertEqual(ba.bi.build_nx_extract(REPO, Path('work'), Path('logs'), {}), 'nx')
        built.assert_called_once_with(Path('work'), Path('logs'), {})

    def test_nx_extract_is_built_once_and_reused(self):   # the desktop app reads every game with --info, each read used to run a dotnet build
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp); builds = []
        name = 'nx_extract.exe' if os.name == 'nt' else 'nx_extract'
        def dotnet(cmd, log, env=None, **k): builds.append(cmd); (Path(cmd[cmd.index('-o') + 1]) / name).write_bytes(b'nx')
        with mock.patch.object(ba, 'data_dir', lambda: tmp / 'data'), mock.patch.object(ba.bi, 'run', dotnet):
            first = ba.build_nx_extract(tmp / 'a', tmp / 'logs', {}); again = ba.bi.build_nx_extract(REPO, tmp / 'b', tmp / 'logs', {})
        self.assertEqual(len(builds), 1); self.assertEqual(first, again); self.assertTrue(first.is_file())
        self.assertTrue(first.parent.name.startswith('nx_extract-') and first.parent.parent == tmp / 'data' / 'tools')

    def test_game_app_stage_without_symbolic_links(self):   # Windows makes them only with Developer Mode on (or as administrator): the stage takes the files instead
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp)
        spv = tmp / 'spv'; (spv / 'vs').mkdir(parents=True); (spv / 'vs' / '0001.spv').write_bytes(b'spv'); (tmp / 'icon.jpg').write_bytes(b'jpg')
        stage = tmp / 'stage'; stage.mkdir()
        def refused(*a, **k): raise OSError(1314, 'A required privilege is not held by the client')
        with mock.patch.object(Path, 'symlink_to', refused):
            ba.stage_link(stage / 'spv', spv); ba.stage_link(stage / 'icon.jpg', tmp / 'icon.jpg')
        self.assertFalse((stage / 'spv').is_symlink())
        self.assertEqual((stage / 'spv/vs/0001.spv').read_bytes(), b'spv')
        self.assertEqual((stage / 'icon.jpg').read_bytes(), b'jpg')


MB = 1 << 20


def jdk() -> 'tuple[str, str] | None':   # (javac, java) of JAVA_HOME, else of PATH, when javac runs (a Mac's /usr/bin/javac is there with no JDK behind it); else None
    home = os.environ.get('JAVA_HOME')
    javac, java = (str(Path(home, 'bin', 'javac')), str(Path(home, 'bin', 'java'))) if home else (shutil.which('javac'), shutil.which('java'))
    if not javac or not java: return None
    try: return (javac, java) if subprocess.run([javac, '-version'], capture_output=True, timeout=60).returncode == 0 else None
    except (OSError, subprocess.SubprocessError): return None


JDK = jdk()
ANDROID_JAR = next(iter(sorted(Path(os.environ.get('ANDROID_HOME') or Path.home() / 'Library/Android/sdk').glob('platforms/android-*/android.jar'), reverse=True)), None)


class GameApp(Base):   # droidplay-core issue #169: a game app whose DLC doesn't fit in the APK carries it after the RomFS, in the .romfs beside it or the XAPK's OBB
    def test_plan_puts_the_romfs_out_first_then_the_dlc(self):
        L = ba.GAME_APP_LIMIT
        small = {'code': 40 * MB, 'shaders': 300 * MB, 'font': 22 * MB, 'the rest': MB}
        self.assertEqual(ba.game_app_plan(small, 10 * MB, 500 * MB, False, L), (True, True))
        self.assertEqual(ba.game_app_plan(small, 10 * MB, 8 << 30, False, L), (False, True))
        self.assertEqual(ba.game_app_plan(small, 10 * MB, 500 * MB, True, L), (False, True))   # an XAPK's RomFS is always its OBB
        # Mario Kart 8 Deluxe with the Booster Course Pass (sizes only): its shaders and DLC pass 2 GiB with no RomFS; the DLC goes beside, in either kind
        mk8 = {'code': 90 * MB, 'shaders': 700 * MB, 'font': 22 * MB, 'the rest': 2 * MB}
        self.assertEqual(ba.game_app_plan(mk8, 1600 * MB, 11 << 30, False, L), (False, False))
        self.assertEqual(ba.game_app_plan(mk8, 1600 * MB, 11 << 30, True, L), (False, False))

    def test_what_cant_go_beside_is_named(self):
        with self.assertRaises(ba.BuildError) as e:
            ba.game_app_plan({'code': 90 * MB, 'shaders': 2100 * MB, 'font': 22 * MB, 'the rest': MB}, 1600 * MB, 11 << 30, False)
        m = str(e.exception)
        for want in ('shaders 2.05 GiB', 'code 0.09 GiB', 'font 0.02 GiB', 'the DLC (1.56 GiB)', 'without --game-apk'): self.assertIn(want, m)

    def stage(self, dlc=(1 << 20, 10)):   # a synthetic game: a small RomFS image, code, shaders, font, and DLC images of the sizes given (no game files)
        g = self.tmp / 'g'; game = g / 'game'; game.mkdir(parents=True); (game / 'RomFS.img').write_bytes(b'DMROMFS1' + bytes(range(256)) * 9)
        (game / 'icon.jpg').write_bytes(b'jpg'); (game / 'control.nacp').write_bytes(b'\0' * 64)
        for d, f in (('code', 'main.fixups.tsv'), ('spv', 'vs/0001.spv'), ('font', 'standard.ttf')): (g / d / f).parent.mkdir(parents=True, exist_ok=True); (g / d / f).write_bytes(b'x' * 100)
        aoc = g / 'aoc'; aoc.mkdir()
        for i, n in zip((1, 3), dlc): (aoc / f'{i}.img').write_bytes(os.urandom(n))
        return g, game, aoc

    def make(self, xapk, limit):
        g, game, aoc = self.stage(); out = self.tmp / 'out'; work = self.tmp / 'work'; (work / 'logs').mkdir(parents=True)
        def fake_apk(cmd, *a, **k): Path(cmd[cmd.index('-o') + 1]).write_bytes(b'apk')
        meta = {'title_id': GID, 'name': 'Test Game', 'romfs_bytes': (game / 'RomFS.img').stat().st_size}
        with mock.patch.object(ba.bi, 'run', fake_apk), mock.patch.dict(os.environ, {'NXNATIVE_GAME_APP_LIMIT': str(limit)}):
            made, inside = ba.make_game_app('sdk', mock.Mock(id=GID), game, g / 'code', g / 'spv', g / 'font', aoc, 'DM_LANG=en-US\n', g / 'host.so', meta, work,
                                            work / 'logs', {}, out, xapk)
        return made, inside, json.loads((work / 'game_app/game.json').read_text()), work / 'game_app', game, aoc

    def check_data(self, data, game, aoc, info):   # the RomFS from byte 0, then the pack at dlc_at with each image at its record
        rom = (game / 'RomFS.img').read_bytes(); at = info['dlc_at']
        self.assertEqual(data[:len(rom)], rom); self.assertEqual(at % ba.DLC_ALIGN, 0); self.assertEqual(len(data), info['data_bytes'])
        self.assertEqual(data[at:at + 8], ba.DLC_MAGIC)
        n, zero = struct.unpack_from('<II', data, at + 8); self.assertEqual((n, zero), (2, 0))
        for k, i in enumerate((1, 3)):
            idx, _, off, size = struct.unpack_from('<IIQQ', data, at + 16 + 24 * k)
            img = (aoc / f'{i}.img').read_bytes()
            self.assertEqual((idx, off % ba.DLC_ALIGN, size), (i, 0, len(img))); self.assertEqual(data[at + off:at + off + size], img)

    def test_dlc_too_big_for_the_apk_follows_the_romfs_beside_it(self):
        made, inside, info, stage, game, aoc = self.make(False, 512 << 10)   # the code and such fit in 512 KB, the 1 MB of DLC doesn't
        self.assertFalse(inside); self.assertEqual([p.name for p in made], ['Test Game.apk', 'Test Game.romfs'])
        self.assertFalse((stage / 'aoc').exists()); self.assertNotIn('aoc/1.img', (stage / 'files.txt').read_text())
        self.check_data(made[1].read_bytes(), game, aoc, info)
        self.assertFalse(os.path.samefile(made[1], game / 'RomFS.img'))   # a copy (or clone) the DLC was appended to, never a link to the extraction's image
        self.assertTrue(any('the DLC' in m for m in self.said))

    def test_dlc_too_big_for_the_apk_follows_the_romfs_in_the_xapks_obb(self):
        import zipfile
        made, inside, info, stage, game, aoc = self.make(True, 512 << 10)
        with zipfile.ZipFile(made[0]) as z:
            m = json.loads(z.read('manifest.json')); obb = m['expansions'][0]['file']
            self.check_data(z.read(obb), game, aoc, info)
        self.assertEqual(m['total_size'], 3 + info['data_bytes'])

    def test_dlc_that_fits_stays_in_the_apk(self):
        made, inside, info, stage, game, aoc = self.make(False, 64 << 20)
        self.assertTrue(inside); self.assertEqual(len(made), 1); self.assertNotIn('dlc_at', info)
        self.assertEqual((stage / 'aoc/1.img').read_bytes(), (aoc / '1.img').read_bytes())

    def test_a_dlc_folder_cant_go_beside(self):   # an older extraction's aoc/<index>/: a game app carries DLC beside the APK as images only
        aoc = self.tmp / 'aoc'; (aoc / '2').mkdir(parents=True)
        with self.assertRaises(ba.BuildError): ba.dlc_images(aoc)

    def jvm(self, cls, code, *args):   # a class of GameStart's package compiled with the app's Java and run on a JVM over the SDK's android.jar stubs → its output
        assert JDK is not None and ANDROID_JAR is not None   # (the callers' skip)
        javac, java = JDK; jar = ANDROID_JAR
        src = self.tmp / f'jsrc_{cls}'; out = self.tmp / f'jout_{cls}'; src.mkdir(); out.mkdir()
        (src / f'{cls}.java').write_text('package org.nxnative.android;   // GameStart\'s helpers are package-private\n' + code)
        javas = [str(p) for p in (REPO / 'dm/android/java').rglob('*.java')] + [str(src / f'{cls}.java')]
        subprocess.run([javac, '-source', '8', '-target', '8', '-Xlint:none', '-nowarn', '-bootclasspath', str(jar), '-cp', str(jar), '-d', str(out), *javas], check=True, capture_output=True)
        return subprocess.run([java, '-cp', f'{jar}{os.pathsep}{out}', f'org.nxnative.android.{cls}', *map(str, args)], check=True, capture_output=True, text=True).stdout

    @unittest.skipUnless(JDK and ANDROID_JAR, 'needs a JDK (JAVA_HOME, or javac on PATH) and the Android SDK (ANDROID_HOME, or the Mac\'s default)')
    def test_gamestart_reads_the_packers_pack(self):   # GameStart's own parser, run on a JVM, against a pack this script wrote
        made, inside, info, stage, game, aoc = self.make(False, 512 << 10)
        out = self.jvm('PackCheck', '''import java.io.RandomAccessFile;
public class PackCheck { public static void main(String[] a) throws Exception {
    RandomAccessFile f = new RandomAccessFile(a[0], "r"); long at = Long.parseLong(a[1]), size = Long.parseLong(a[2]);
    byte[] h = new byte[16]; f.seek(at); f.readFully(h); int n = GameStart.dlcCount(h);
    byte[] head = new byte[16 + 24 * n]; f.seek(at); f.readFully(head);
    for (long[] r : GameStart.dlcRecords(head, size - at)) System.out.println(r[0] + " " + r[1] + " " + r[2]);
    head[16] = 0; head[17] = 0; System.out.println(GameStart.dlcRecords(head, size - at) == null ? "bad index refused" : "bad index taken");
} }
''', made[1], info['dlc_at'], info['data_bytes'])
        _, recs, _ = ba.dlc_pack(ba.dlc_images(aoc))
        self.assertEqual(out.split('\n'), [f'{i} {o} {n}' for i, o, n in recs] + ['bad index refused', ''])

    # droidplay-core issue #169 again: a ZIP without ZIP64 holds 65,535 entries, and Mario Kart 8 Deluxe's shaders with its DLC passed that at 492 MB
    def spv_folder(self, n):   # a synthetic spv folder of n tiny files, as the translator names them (no game files)
        spv = self.tmp / f'spv{n}'; spv.mkdir()
        for i in range(n): (spv / f'{i:016x}{".z" if i % 3 == 0 else ""}.spv').write_bytes(i.to_bytes(4, 'little'))
        return spv

    def test_shaders_past_the_entry_limit_go_in_one_entry(self):
        import zipfile
        g, game, aoc = self.stage(); spv = self.spv_folder(65_600); out = self.tmp / 'out'; work = self.tmp / 'work'; (work / 'logs').mkdir(parents=True)
        meta = {'title_id': GID, 'name': 'Test Game', 'romfs_bytes': (game / 'RomFS.img').stat().st_size}
        with mock.patch.object(ba.bi, 'run', lambda cmd, *a, **k: Path(cmd[cmd.index('-o') + 1]).write_bytes(b'apk')):
            ba.make_game_app('sdk', mock.Mock(id=GID), game, g / 'code', spv, g / 'font', aoc, 'DM_LANG=en-US\n', g / 'host.so', meta, work, work / 'logs', {}, out, False)
        stage = work / 'game_app'; listed = (stage / 'files.txt').read_text().split()
        self.assertFalse((stage / 'spv').exists()); self.assertIn(ba.SPV_ZIP, listed); self.assertLess(len(listed), 100)   # the APK's entries: a handful, not 65,600
        with zipfile.ZipFile(stage / ba.SPV_ZIP) as z:
            infos = z.infolist()
            self.assertEqual(len(infos), 65_600); self.assertTrue(all(i.compress_type == zipfile.ZIP_STORED for i in infos))
            self.assertEqual(z.read('0000000000000003.z.spv'), (3).to_bytes(4, 'little'))

    def test_too_many_files_is_named(self):   # the files the APK must carry, past the entry limit even with the shaders packed
        parts = {'code': 90 * MB, 'shaders': 500 * MB, 'font': 22 * MB, 'the rest': MB}
        with self.assertRaises(ba.BuildError) as e:
            ba.game_app_plan(parts, 0, 1 << 30, False, files={'code': 70_000, 'shaders': 1, 'font': 3, 'the rest': 6})
        for want in ('70,010 files', 'code 70,000', 'shaders 1', '65,535 entries', 'without --game-apk'): self.assertIn(want, str(e.exception))
        self.assertEqual(ba.game_app_plan(parts, MB, 1 << 30, False, files={'code': 100}, dlc_files=ba.GAME_APP_ENTRIES), (False, False))   # DLC whose files don't fit goes beside

    def test_build_apk_names_the_limit_it_hit(self):   # zipfile raises one LargeZipFile for every limit; the message says which
        import zipfile
        spec = importlib.util.spec_from_file_location('build_apk', REPO / 'dm/android/tools/build_apk.py'); assert spec and spec.loader
        bapk = importlib.util.module_from_spec(spec); spec.loader.exec_module(bapk)
        writing = ['assets/game/spv/e94e9c942d2987fd.z.spv', 18_856, 65_535, 492_500_937]
        m = bapk.zip64_message('x.apk', zipfile.LargeZipFile('Files count would require ZIP64 extensions'), writing)
        self.assertIn('reached 65,535 entries', m); self.assertNotIn('2 GiB', m)
        m = bapk.zip64_message('x.apk', zipfile.LargeZipFile('Zipfile size would require ZIP64 extensions'), writing)
        self.assertIn('passed 2 GiB (492,500,937 bytes written)', m); self.assertNotIn('65,535', m)

    @unittest.skipUnless(JDK and ANDROID_JAR, 'needs a JDK (JAVA_HOME, or javac on PATH) and the Android SDK (ANDROID_HOME, or the Mac\'s default)')
    def test_gamestart_unpacks_the_packers_shaders(self):   # GameStart.unzip, run on a JVM, over the script's spv.zip, and a name that leaves the folder refused
        import zipfile
        spv = self.spv_folder(300); z = self.tmp / 'spv.zip'; ba.pack_spv(spv, z)
        bad = self.tmp / 'bad.zip'
        with zipfile.ZipFile(bad, 'w') as b: b.writestr('../outside.spv', b'x')
        dst = self.tmp / 'unpacked'
        out = self.jvm('UnzipCheck', '''import java.io.*;
public class UnzipCheck { public static void main(String[] a) throws Exception {
    System.out.println(GameStart.unzip(new FileInputStream(a[0]), new File(a[1]), new byte[1 << 16], null));
    try { GameStart.unzip(new FileInputStream(a[2]), new File(a[3]), new byte[1 << 16], null); System.out.println("taken"); }
    catch (IOException e) { System.out.println("refused"); }
} }
''', z, dst, bad, self.tmp / 'bad_dst')
        self.assertEqual(out.split(), ['300', 'refused'])
        self.assertEqual(sorted(p.name for p in dst.iterdir()), sorted(p.name for p in spv.iterdir()))
        self.assertTrue(all((dst / p.name).read_bytes() == p.read_bytes() for p in spv.iterdir()))
        self.assertFalse((self.tmp / 'outside.spv').exists())


class Setup(unittest.TestCase):   # --setup (dm/android/tools/host_setup.py): what --check finds missing, installed where the script looks; nothing is downloaded here
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.hs = ba.host_setup; self.sdk = self.tmp / 'sdk'; self.tools = self.tmp / 'tools'
        cm = mock.patch.object(self.hs, 'WINDOWS', True); cm.__enter__(); self.addCleanup(cm.__exit__, None, None, None)

    def test_installed_tools_go_first_on_path_and_the_sdks_adb_last(self):   # they are there because the computer had none; its own adb keeps its server
        for d in ('tools/jdk/bin', 'tools/dotnet', 'sdk/platform-tools'): (self.tmp / d).mkdir(parents=True)
        with mock.patch.dict(os.environ, {'PATH': '/usr/bin', 'JAVA_HOME': str(self.tmp / 'jdk-8-uninstalled')}):   # a JAVA_HOME left behind by an old JDK
            self.hs.add_tool_paths(self.tools, self.sdk)
            self.assertEqual(os.environ['PATH'].split(os.pathsep), [str(self.tools / 'jdk/bin'), str(self.tools / 'dotnet'), '/usr/bin', str(self.sdk / 'platform-tools')])
            self.assertEqual(os.environ['JAVA_HOME'], str(self.tools / 'jdk')); self.assertEqual(os.environ['DOTNET_ROOT'], str(self.tools / 'dotnet'))

    def test_platform_tools_already_on_path_keep_their_place(self):   # nxplay puts ANDROID_HOME's first, ahead of any other adb: that order stays
        (self.sdk / 'platform-tools').mkdir(parents=True)
        with mock.patch.dict(os.environ, {'PATH': os.pathsep.join([str(self.sdk / 'platform-tools'), '/opt/homebrew/bin', '/usr/bin'])}):
            self.hs.add_tool_paths(self.tools, self.sdk)
            self.assertEqual(os.environ['PATH'].split(os.pathsep), [str(self.sdk / 'platform-tools'), '/opt/homebrew/bin', '/usr/bin'])

    def test_the_macs_default_sdk_is_found(self):   # Android Studio's folder on a Mac, where no ANDROID_HOME is set
        (self.tmp / 'Library/Android/sdk/platform-tools').mkdir(parents=True)
        with mock.patch.dict(os.environ, {'HOME': str(self.tmp), 'USERPROFILE': str(self.tmp), 'LOCALAPPDATA': str(self.tmp / 'none')}):
            for k in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'): os.environ.pop(k, None)
            self.assertEqual(ba.sdk_dir(None), self.tmp / 'Library/Android/sdk')

    def test_the_sdk_option_puts_its_adb_on_path(self):   # adb is run by name: --sdk's platform-tools, which the import-time lookup did not know
        (self.sdk / 'platform-tools').mkdir(parents=True)
        with mock.patch.dict(os.environ, {'PATH': '/usr/bin'}), mock.patch.object(ba, 'data_dir', lambda: self.tmp / 'data'):
            ba.tool_paths(str(self.sdk))
            self.assertEqual(os.environ['PATH'].split(os.pathsep), ['/usr/bin', str(self.sdk / 'platform-tools')])

    def test_each_step_runs_with_what_the_steps_before_it_installed(self):   # sdkmanager needs the JDK unpacked a moment earlier, in the same run
        seen = {}
        def jdk(tools, work, prog): (tools / 'jdk/bin').mkdir(parents=True); return tools / 'jdk'
        def packages(sdk, pkgs, prog): seen.update(path=os.environ['PATH'].split(os.pathsep), java=os.environ.get('JAVA_HOME'))
        (self.sdk / 'cmdline-tools/latest/bin').mkdir(parents=True)
        with mock.patch.dict(os.environ, {'PATH': '/usr/bin'}), mock.patch.object(self.hs, 'install_jdk', jdk), mock.patch.object(self.hs, 'install_packages', packages):
            os.environ.pop('JAVA_HOME', None)
            self.hs.setup({'JDK javac', 'NDK'}, self.sdk, self.tools, ba.sdk_packages(self.sdk), True, mock.Mock(), lambda m: None)
        self.assertEqual(seen['path'][0], str(self.tools / 'jdk/bin')); self.assertEqual(seen['java'], str(self.tools / 'jdk'))

    def test_only_what_is_missing_is_installed(self):
        calls = []
        with mock.patch.object(self.hs, 'install_jdk', lambda *a: calls.append('jdk') or self.tools / 'jdk'), \
             mock.patch.object(self.hs, 'install_dotnet', lambda *a: calls.append('dotnet')), \
             mock.patch.object(self.hs, 'install_cmdline_tools', lambda *a: calls.append('cmdline-tools')), \
             mock.patch.object(self.hs, 'install_packages', lambda sdk, pkgs, prog: calls.append([p for p, _ in pkgs])):
            done = self.hs.setup({'JDK javac', 'NDK', 'Python module PySide6'}, self.sdk, self.tools, ba.sdk_packages(self.sdk), True, mock.Mock(), lambda m: None)
        self.assertEqual(calls, ['jdk', 'cmdline-tools', [f'ndk;{ba.NDK}']])
        self.assertEqual(done, ['JDK 21', 'Android command-line tools', 'Android SDK packages'])

    def test_no_sdk_found_installs_every_package(self):
        got = []
        with mock.patch.object(self.hs, 'install_cmdline_tools', lambda *a: None), mock.patch.object(self.hs, 'install_packages', lambda sdk, pkgs, prog: got.extend(pkgs)):
            self.hs.setup({'Android SDK'}, self.sdk, self.tools, ba.sdk_packages(self.sdk), True, mock.Mock(), lambda m: None)
        self.assertEqual({p for p, _ in got}, {'platform-tools', f'platforms;{ba.PLATFORM}', f'build-tools;{ba.BUILD_TOOLS}', f'ndk;{ba.NDK}', f'cmake;{ba.CMAKE}'})

    def test_the_sdk_waits_for_its_licence(self):
        with self.assertRaisesRegex(self.hs.SetupError, 'accept-android-licenses'):
            self.hs.setup({'NDK'}, self.sdk, self.tools, ba.sdk_packages(self.sdk), False, mock.Mock(), lambda m: None)

    def test_off_windows_it_says_where_to_go(self):
        with mock.patch.object(self.hs, 'WINDOWS', False), self.assertRaisesRegex(self.hs.SetupError, 'DroidPlay'):
            self.hs.setup({'NDK'}, self.sdk, self.tools, ba.sdk_packages(self.sdk), True, mock.Mock(), lambda m: None)

    def run_install(self, cli):   # install_packages with subprocess stubbed: the command for the NDK, and what it was fed
        b = self.sdk / 'cmdline-tools/latest/bin'; b.mkdir(parents=True); (b / ('android.exe' if cli else 'sdkmanager.bat')).touch()
        seen = []
        def run(cmd, input=None, **k): seen.append((cmd, input)); (self.sdk / 'ndk' / ba.NDK).mkdir(parents=True); return mock.Mock(returncode=0, stdout='', stderr='')
        with mock.patch.object(self.hs.subprocess, 'run', run): self.hs.install_packages(self.sdk, [ba.sdk_packages(self.sdk)['NDK']], mock.Mock())
        return seen[0]

    def test_packages_go_through_the_android_cli_without_metrics(self):   # command-line tools 23: one package a call, / for ;
        cmd, fed = self.run_install(cli=True)
        self.assertEqual(cmd[1:], ['--no-metrics', f'--sdk={self.sdk}', 'sdk', 'install', f'ndk/{ba.NDK}']); self.assertIsNone(fed)

    def test_older_command_line_tools_use_sdkmanager(self):
        cmd, fed = self.run_install(cli=False)
        self.assertEqual(cmd[1:], [f'--sdk_root={self.sdk}', '--install', f'ndk;{ba.NDK}']); self.assertTrue(fed.startswith('y\n'))


class Library(Base):
    def test_hosts_kept_per_game_and_all_in_the_apk(self):
        for gid in (GID, '0100A6301214E000'):
            so = self.tmp / f'libdmhost_{gid}.so'; so.write_bytes(b'host'); loader = self.tmp / 'libnxloader.so'; loader.write_bytes(b'loader')
            st = self.tmp / 'st'; st.mkdir(exist_ok=True); (st / 'main.patched.bin').write_bytes(b'x')
            ba.library_add(gid, so, loader, st, {'name': gid})
        self.assertEqual(sorted(ba.library()), sorted([GID, '0100A6301214E000']))
        ran = []
        with mock.patch.object(ba.bi, 'run', lambda cmd, log, env=None: ran.append([str(c) for c in cmd])):
            apk = ba.make_apk(Path('sdk'), self.tmp, {})
        self.assertEqual(apk, self.tmp / 'data' / f'nxnative.{os.getpid()}.apk')   # this run's own copy: another build packing at the same time can't swap it under the install
        cmd = ran[0]
        self.assertEqual(cmd[cmd.index('-o') + 1], str(apk))
        self.assertEqual([cmd[i + 1] for i, c in enumerate(cmd) if c == '--so'], [str(self.tmp / 'data/hosts' / g / f'libdmhost_{g}.so') for g in sorted([GID, '0100A6301214E000'])])
        self.assertIn('--loader', cmd)

    def test_vk_driver_libs_in_both_kinds_of_app(self):   # DM_VK_DRIVER's libadrenotools and hooks, built beside the loader, go into the app and into a game app
        b = self.tmp / 'build'; b.mkdir()
        so = b / f'libdmhost_{GID}.so'; so.write_bytes(b'host'); loader = b / 'libnxloader.so'; loader.write_bytes(b'loader')
        for n in ba.VK_DRIVER_LIBS: (b / n).write_bytes(n.encode())
        st = self.tmp / 'st'; st.mkdir(); (st / 'main.patched.bin').write_bytes(b'x')
        ba.library_add(GID, so, loader, st, {'name': GID})
        ran = []
        with mock.patch.object(ba.bi, 'run', lambda cmd, log, env=None: ran.append([str(c) for c in cmd])):
            ba.make_apk(Path('sdk'), self.tmp, {})
        libs = lambda cmd: [Path(cmd[i + 1]).name for i, c in enumerate(cmd) if c == '--lib']
        self.assertEqual(libs(ran[0]), list(ba.VK_DRIVER_LIBS))
        self.assertTrue(all((self.tmp / 'data/loader' / n).is_file() for n in ba.VK_DRIVER_LIBS))
        self.assertEqual(ba.driver_libs(b), [b / n for n in ba.VK_DRIVER_LIBS])   # make_game_app's: beside the host it packs
        (self.tmp / 'data/loader/libhook_impl.so').unlink()   # a library from before: its APK goes without the missing one
        ran.clear()
        with mock.patch.object(ba.bi, 'run', lambda cmd, log, env=None: ran.append([str(c) for c in cmd])):
            ba.make_apk(Path('sdk'), self.tmp, {})
        self.assertEqual(libs(ran[0]), ['libadrenotools.so', 'libmain_hook.so'])

    def test_no_host_no_apk(self):
        with self.assertRaises(ba.BuildError): ba.make_apk(Path('sdk'), self.tmp, {})

    def test_app_version_from_the_release_or_the_checkout(self):   # the launcher app's versionName: a release archive's VERSION file, else git describe, else the manifest's
        rel = self.tmp / 'release'; rel.mkdir(); (rel / 'VERSION').write_text('0.3.1\n', encoding='utf-8')
        with mock.patch.object(ba, 'REPO', rel): self.assertEqual(ba.core_version(), '0.3.1')
        with mock.patch.object(ba, 'REPO', self.tmp / 'neither'): self.assertIsNone(ba.core_version())   # not a release, not a checkout
        so = self.tmp / f'libdmhost_{GID}.so'; so.write_bytes(b'host'); loader = self.tmp / 'libnxloader.so'; loader.write_bytes(b'loader')
        st = self.tmp / 'st'; st.mkdir(); (st / 'main.patched.bin').write_bytes(b'x'); ba.library_add(GID, so, loader, st, {'name': GID})
        ran = []
        with mock.patch.object(ba.bi, 'run', lambda cmd, log, env=None: ran.append([str(c) for c in cmd])), mock.patch.object(ba, 'core_version', lambda: '0.3.1'):
            ba.make_apk(Path('sdk'), self.tmp, {})
        self.assertEqual(ran[0][ran[0].index('--version-name') + 1], '0.3.1')


class Journal(Base):
    def test_events_in_the_journal_whatever_the_console_mode(self):
        p = ba.Journaled('off', ['x', '--no-push'])
        p.plan(2); p.stage('one', step='a', total=10, done=3); p.set(done=7); p.end('fine'); p.say('hello'); p.stage('two'); p.exit(0)
        (f,) = (self.tmp / 'data/builds').glob('*.jsonl')
        evs = [json.loads(line) for line in f.read_text(encoding='utf-8').splitlines()]
        self.assertEqual(evs[0]['ev'], 'start'); self.assertEqual(evs[0]['argv'], ['x', '--no-push'])
        self.assertEqual(evs[-1], {'ev': 'exit', 'code': 0, 't': evs[-1]['t']})
        kinds = [e['ev'] for e in evs]
        self.assertEqual(kinds.count('stage'), 2); self.assertEqual(kinds.count('stage_end'), 2)   # the second ended by exit()
        self.assertIn('say', kinds)
        self.assertEqual([e['done'] for e in evs if e['ev'] == 'progress' and e['name'] == 'one'][-1], 7)


class AdbErrors(unittest.TestCase):
    def test_a_failure_names_its_exit_status_even_with_no_output(self):
        r = subprocess.CompletedProcess([], 1, stdout='', stderr='')
        with mock.patch.object(ba.subprocess, 'run', return_value=r):
            with self.assertRaisesRegex(ba.BuildError, r'adb -s S shell true failed \(exit status 1\): no output'): ba.adb('S', 'shell', 'true')
        r = subprocess.CompletedProcess([], 255, stdout='', stderr="adb: device 'S' not found\n")
        with mock.patch.object(ba.subprocess, 'run', return_value=r):
            with self.assertRaisesRegex(ba.BuildError, r"failed \(exit status 255\): adb: device 'S' not found$"): ba.adb('S', 'shell', 'true')


class Phone(Base):
    def setUp(self):
        super().setUp()
        self.cmds = []; self.remote: dict[str, Any] = {}   # remote path → exists ('free': the phone's free KiB for df, 'mkdirs': what the folder script prints)
        def adb(serial, *a, log=None, check=True):
            c = [str(x) for x in a]; self.cmds.append(c)
            if c[:2] == ['shell', 'sh'] and c[2].endswith('nxnative_mkdirs.sh'):
                out = self.remote.get('mkdirs', ba.MKDIRS_DONE + '\n')
                if isinstance(out, Exception): raise out
                return out
            if c[:1] == ['shell'] and len(c) == 2 and c[1].startswith('df -k '):
                return f"/dev/fuse 233000000 120000000 {self.remote['free']} 51% /storage/emulated\n" if 'free' in self.remote else ''
            if c[:1] == ['shell'] and len(c) == 2 and c[1].startswith('[ -e '):
                path = c[1].split("'")[1]; return 'yes\n' if self.remote.get(path) else ''
            if c[:1] == ['shell'] and len(c) == 2 and c[1].startswith('sha256sum '): return self.remote.get('sha', '') + '  x\n'
            if c[:1] == ['shell'] and len(c) == 2 and c[1].startswith('cat ') and ba.MANIFEST in c[1]: return self.remote.get('manifest', '')
            return ''
        cm = mock.patch.object(ba, 'adb', adb); cm.__enter__(); self.addCleanup(cm.__exit__, None, None, None)
        self.game = self.tmp / 'v1'; (self.game / 'RomFS').mkdir(parents=True); (self.game / 'RomFS/a.bin').write_bytes(b'a')
        (self.game / 'control.nacp').write_bytes(b'nacp'); (self.game / 'icon.jpg').write_bytes(b'jpg')
        self.patched = self.tmp / 'patched_android_v1'; self.patched.mkdir(); (self.patched / 'main.fixups.tsv').write_text('x')
        self.font = self.tmp / 'font'; self.font.mkdir(); (self.font / 'f.ttf').write_bytes(b'f')
        (self.tmp / 'logs').mkdir()

    def push(self):
        ba.push_game('S', GID, self.game, self.patched, None, self.font, self.tmp / 'aoc', 'en-US', self.tmp, self.tmp / 'logs', {'title_id': GID})
        return [' '.join(c) for c in self.cmds]

    def test_copies_to_games_folder_and_opens_it(self):
        flat = self.push(); dst = f'{ba.REMOTE}/games/{GID}'
        self.assertTrue(any(c.startswith('push') and c.endswith(f'{dst}/') for c in flat))
        self.assertTrue(any(c.startswith('push') and c.endswith(f'{dst}/game.json') for c in flat))
        self.assertTrue(any(f"chmod -R a+rwX '{dst}' 2>&1; chmod a+rwx '{ba.REMOTE}/games' 2>&1" in c for c in flat), flat)
        writes = [c for c in flat if not c.startswith('shell [ -e ')]   # the one-game layout is only looked for
        self.assertFalse(any(f'{ba.REMOTE}/game/' in c or c.endswith(f'{ba.REMOTE}/game') for c in writes), writes)

    def test_launcher_files_end_lines_with_newline_alone(self):   # on Windows too: the desktop app reads game.json by lines, and the \r of \r\n split its JSON
        ba.push_game('S', GID, self.game, self.patched, None, self.font, self.tmp / 'aoc', 'DM_LANG=en-US\n', self.tmp, self.tmp / 'logs', {'title_id': GID, 'name': 'x'})
        for f in ('android_game.json', 'android_defaults.txt'): self.assertNotIn(b'\r', (self.tmp / f).read_bytes(), f)

    def test_one_game_install_of_the_same_game_is_moved(self):
        self.remote = {f'{ba.REMOTE}/game/code/main.fixups.tsv': True, 'sha': hashlib.sha256(b'nacp').hexdigest()}
        flat = self.push()
        mv = [c for c in flat if ' mv ' in c and 'legacy_save' in c]
        self.assertEqual(len(mv), 1, flat)
        self.assertIn(f"mv '{ba.REMOTE}/game' '{ba.REMOTE}/games/{GID}'", mv[0])

    def test_one_game_install_of_another_game_is_left(self):
        self.remote = {f'{ba.REMOTE}/game/code/main.fixups.tsv': True, 'sha': hashlib.sha256(b'other').hexdigest()}
        flat = self.push()
        self.assertFalse(any(' mv ' in c and 'legacy_save' in c for c in flat))
        self.assertTrue(any('another game' in s for s in self.said))

    def test_many_files_go_as_one_archive_and_only_changed_ones_again(self):
        big = self.tmp / 'spv'; big.mkdir()
        for i in range(ba.TAR_FILES + 5): (big / f'{i:04}.spv').write_bytes(b'x' * (i % 7 + 1))
        ba.push_dir('S', big, f'{ba.REMOTE}/games/{GID}', 'spv', self.tmp / 'logs' / 'p.log', sync=True)
        flat = [' '.join(c) for c in self.cmds]
        self.assertEqual(sum(c.startswith('push ') and c.endswith('/.spv.tar') for c in flat), 1, flat)
        self.assertTrue(any(f"tar -xf '{ba.REMOTE}/games/{GID}/.spv.tar' -C '{ba.REMOTE}/games/{GID}/spv'" in c for c in flat), flat)
        self.assertFalse(any(c.startswith('push ') and c.endswith('/spv') or c.endswith(f'{GID}/') for c in flat if 'manifest' not in c and '.tar' not in c), flat)
        man = (self.tmp / 'logs' / 'p.manifest').read_text(encoding='utf-8')
        self.assertEqual(len(man.splitlines()), ba.TAR_FILES + 5)
        self.cmds.clear(); self.remote['manifest'] = man   # the phone has them: nothing is sent again
        ba.push_dir('S', big, f'{ba.REMOTE}/games/{GID}', 'spv', self.tmp / 'logs' / 'p.log', sync=True)
        self.assertFalse(any(' '.join(c).endswith('.tar') for c in self.cmds if c[0] == 'push'), self.cmds)
        self.assertTrue(any('0 of' in s for s in self.said), self.said)

    def test_large_file_goes_on_from_what_the_phone_holds(self):
        import re
        files = {}; sent = []
        def q(s): return s.strip().strip("'")
        def adb(serial, *a, log=None, check=True):
            c = [str(x) for x in a]
            if c[0] == 'push':
                if len(sent) == 1 and not getattr(adb, 'cut', False): adb.cut = True; raise ba.BuildError('no response: Broken pipe')
                sent.append(c[2]); files[c[2]] = Path(c[1]).read_bytes(); return ''
            cmd = c[1]
            if m := re.fullmatch(r"stat -c %s (.+) 2>/dev/null", cmd): p = q(m[1]); return f'{len(files[p])}\n' if p in files else ''
            if m := re.fullmatch(r": > (.+)", cmd): files[q(m[1])] = b''; return ''
            if m := re.fullmatch(r"dd if=(.+) bs=4096 skip=(\d+) count=(\d+) 2>/dev/null \| head -c (\d+) \| sha256sum", cmd):
                b = files[q(m[1])][int(m[2]) * 4096:][:int(m[3]) * 4096][:int(m[4])]; return hashlib.sha256(b).hexdigest() + '  -\n'
            if m := re.fullmatch(r"cat (.+) >> (.+) && rm (.+)", cmd): files[q(m[2])] += files.pop(q(m[1])); return ''
            if m := re.fullmatch(r"mv -f (.+) (.+)", cmd): files[q(m[2])] = files.pop(q(m[1])); return ''
            if cmd.startswith('df -k '): return ''   # free space not known: no check
            raise AssertionError(c)
        big = self.tmp / 'RomFS.img'; big.write_bytes(bytes(range(256)) * 9000)   # 2.2 MB, in 1 MB pieces
        with mock.patch.object(ba, 'adb', adb), mock.patch.object(ba, 'CHUNK', 1 << 20):
            with self.assertRaises(ba.BuildError): ba.push_resumable('S', big, '/r/RomFS.img', self.tmp / 'logs' / 'p.log')   # cut after the first piece
            self.assertEqual(len(files['/r/RomFS.img.partial']), 1 << 20)
            ba.push_resumable('S', big, '/r/RomFS.img', self.tmp / 'logs' / 'p.log')
        self.assertEqual(files['/r/RomFS.img'], big.read_bytes())
        self.assertEqual(len(sent), 3)   # the first piece once, then the two left
        self.assertTrue(any('going on from there' in s for s in self.said), self.said)

    def test_folder_script_stops_at_the_first_failure_and_must_finish(self):   # droidplay-core issue #37: "nxnative_mkdirs.sh failed:" and nothing after it
        self.push()
        script = (self.tmp / 'logs' / 'push_S/adb_push_font.mkdirs.sh').read_text(encoding='utf-8').splitlines()
        self.assertEqual(script[0], 'set -e'); self.assertEqual(script[-1], f'echo {ba.MKDIRS_DONE}')
        self.cmds.clear(); self.remote['mkdirs'] = ''   # the script printed nothing and adb reported success
        with self.assertRaisesRegex(ba.BuildError, 'folders for font were not made on the phone.*printing nothing'): self.push()
        self.assertFalse(any(c[0] == 'push' and c[-1].endswith(f'{GID}/') for c in self.cmds), self.cmds)   # the folder is not sent into nothing

    def test_a_failed_step_on_a_full_phone_says_so(self):
        self.remote = {'mkdirs': ba.BuildError('adb -s S shell sh /data/local/tmp/nxnative_mkdirs.sh failed (exit status 1): no output'), 'free': 100 * 1024}
        with mock.patch.object(ba, 'ROOM_SPARE', 0):   # the font fits: the step after it fails
            with self.assertRaisesRegex(ba.BuildError, r'(?s)exit status 1.*only 105 MB free.*RomFS\.img\.partial'): self.push()
            self.remote['free'] = 20 << 20   # 20 GB free: the error stays as it was
            with self.assertRaises(ba.BuildError) as e: self.push()
        self.assertNotIn('free', str(e.exception))
        self.remote['free'] = 100 * 1024   # with the usual spare, 105 MB stops the install before anything is copied
        with self.assertRaisesRegex(ba.BuildError, r'the phone has 105 MB free: font needs 0 MB, plus 268 MB left free for Android and the app\. Free up 164 MB'): self.push()

    def test_a_copy_that_does_not_fit_stops_before_it_starts(self):
        big = self.tmp / 'RomFS.img'; big.write_bytes(b'r' * 3_000_000)
        self.remote = {'free': 1}
        with mock.patch.object(ba, 'ROOM_SPARE', 1 << 20):
            with self.assertRaisesRegex(ba.BuildError, r'the phone has 0 MB free: RomFS\.img \(3 MB left to send\) needs 6 MB, plus 1 MB left free for Android and the app\. Free up 7 MB'):
                ba.push_resumable('S', big, f'{ba.REMOTE}/games/{GID}/RomFS.img', self.tmp / 'logs' / 'p.log')
        self.assertFalse(any(c[0] == 'push' for c in self.cmds), self.cmds)
        spv = self.tmp / 'spv'; spv.mkdir()
        for i in range(ba.TAR_FILES + 1): (spv / f'{i:04}.spv').write_bytes(b'x' * 100)
        with self.assertRaisesRegex(ba.BuildError, r'spv \(201 files in one archive, unpacked beside itself\) needs'):
            ba.push_dir('S', spv, f'{ba.REMOTE}/games/{GID}', 'spv', self.tmp / 'logs' / 'p.log', sync=True)
        self.assertFalse(any(c[0] == 'push' for c in self.cmds), self.cmds)
        self.assertFalse((self.tmp / 'logs' / 'p.tar').exists())   # the archive made on this computer is removed too

    def test_leftovers_of_a_copy_cut_short_are_removed(self):
        flat = self.push(); dst = f'{ba.REMOTE}/games/{GID}'
        self.assertIn(f"shell rm -f '{dst}'/.*.tar '{dst}/RomFS.img.piece'", flat)
        self.assertFalse(any('rm' in c and 'RomFS.img.partial' in c for c in flat), flat)   # the next copy goes on from it

    def test_install_is_an_update(self):
        apk = self.tmp / 'a.apk'; apk.write_bytes(b'apk')
        with mock.patch.object(ba, 'KEYSTORE', self.tmp / 'k.jks'):
            (self.tmp / 'k.jks').write_bytes(b'k'); ba.install('S', apk, self.tmp / 'logs')
        self.assertEqual(self.cmds[-1][:2], ['install', '-r'])
        self.assertFalse(any('uninstall' in ' '.join(c) for c in self.cmds))



class Update(unittest.TestCase):   # dm/android/desktop/update.py, the desktop app's updates: the newest release read, its Setup downloaded and checked; a local server is GitHub
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.setup = b'MZ' + os.urandom(300_000); files = self.files = {'/setup.exe': self.setup}
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = files.get(self.path)
                self.send_response(200 if body is not None else 404); self.send_header('Content-Length', str(len(body or b''))); self.end_headers(); self.wfile.write(body or b'')
            def log_message(self, *a): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start(); self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        self.base = f'http://127.0.0.1:{server.server_address[1]}'

    def release(self, digest=None, name='DroidPlay-Setup-0.5.1.exe'):
        digest = f'sha256:{hashlib.sha256(self.setup).hexdigest()}' if digest is None else digest
        self.files['/api'] = json.dumps({'tag_name': 'v0.5.1', 'html_url': 'https://example.invalid/v0.5.1', 'assets': [
            {'name': 'droidplay-core-0.5.1.zip', 'size': 1, 'browser_download_url': self.base + '/x', 'digest': 'sha256:' + '0' * 64},
            {'name': name, 'size': len(self.setup), 'browser_download_url': self.base + '/setup.exe', 'digest': digest}]}).encode()
        return upd.latest_release(self.base + '/api')

    def test_release_numbers(self):   # a checkout's git describe is no release: nothing is newer than it
        self.assertEqual(upd.release_number('v0.5.1'), (0, 5, 1)); self.assertEqual(upd.release_number('0.10.0'), (0, 10, 0))
        self.assertGreater(upd.release_number('0.10.0'), upd.release_number('0.9.9'))
        for v in ('0.5.0-3-gabc1234', '', None, 'v0.5'): self.assertIsNone(upd.release_number(v))

    def test_setup_only_with_the_digest_github_lists(self):
        r = self.release(); self.assertEqual((r['tag'], r['setup']['name'], r['setup']['sha256']), ('v0.5.1', 'DroidPlay-Setup-0.5.1.exe', hashlib.sha256(self.setup).hexdigest()))
        self.assertIsNone(self.release(digest='')['setup'])   # nothing to check the download against: the release's page instead
        self.assertIsNone(self.release(name='Install.DroidPlay.cmd')['setup'])

    def test_setup_downloaded_and_checked(self):
        folder = self.tmp / 'updates'; folder.mkdir(); (folder / 'DroidPlay-Setup-0.5.0.exe').write_bytes(b'old')
        seen = []; path = upd.download_setup(self.release()['setup'], folder, lambda d, t: seen.append((d, t)))
        self.assertEqual(path.read_bytes(), self.setup); self.assertEqual(seen[-1], (len(self.setup), len(self.setup)))
        self.assertEqual(sorted(f.name for f in folder.iterdir()), ['DroidPlay-Setup-0.5.1.exe'])   # the older download gone, no .part left

    def test_a_setup_that_does_not_match_is_deleted(self):
        folder = self.tmp / 'updates'
        with self.assertRaisesRegex(ValueError, "doesn't match the release's checksum"): upd.download_setup(self.release(digest='sha256:' + 'a' * 64)['setup'], folder)
        self.assertEqual(list(folder.iterdir()), [])

    def test_cancelled_leaves_nothing(self):
        folder = self.tmp / 'updates'
        with self.assertRaises(upd.Cancelled): upd.download_setup(self.release()['setup'], folder, cancelled=lambda: True)
        self.assertEqual(list(folder.iterdir()), [])

    def test_a_copy_setup_installed(self):   # <app>\core with the runtime and Inno's uninstaller beside it: Update; any other copy gets the release's page
        app = self.tmp / 'DroidPlay'; (app / 'core').mkdir(parents=True); (app / 'runtime').mkdir()
        self.assertFalse(upd.setup_install(app / 'core'))
        (app / 'unins000.exe').write_bytes(b''); (app / 'runtime' / 'pythonw.exe').write_bytes(b'')
        self.assertTrue(upd.setup_install(app / 'core'))


if __name__ == '__main__':
    unittest.main()
