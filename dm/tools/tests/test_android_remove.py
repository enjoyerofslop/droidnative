"""The Android launcher's Remove game (dm/android/java/org/nxnative/android/Removal.java), run on a JVM over the SDK's android.jar stubs: what a launcher install put on
the phone goes (the game's folder, its pipeline cache, a RomFS image an install with --romfs-dir put in a folder of its own), what isn't the install's stays (the saves,
the backups, other games, anything else defaults.txt's DM_ROMFS names), symbolic links are deleted without being followed, the sizes the prompt shows, and the folder
a removal cut short leaves behind. Synthetic folders only: no phone and no game files."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from test_android_saves import ANDROID_JAR, JDK, files_of, tree

REPO = Path(__file__).resolve().parents[3]
TID, OTHER = '0100000011D90000', '01006F8002326000'

# A driver of Removal's package-private methods: one command per run, its results on one line
DRIVER = r'''package org.nxnative.android;
import java.io.File;
public class RemoveCheck {
    public static void main(String[] a) throws Exception {
        switch (a[0]) {
        case "plan": {   // game internal id → game cache romfs bytes, the image elsewhere or -, whether it is there
            Removal r = new Removal(new File(a[1]), new File(a[2]), a[3]);
            System.out.println(r.gameBytes + " " + r.cacheBytes + " " + r.romfsBytes + " " + (r.romfs != null ? r.romfs.getPath() : "-") + " " + r.romfsThere);
            break;
        }
        case "remove": {   // game internal id → bytes freed, files or folders left, the first of them
            Removal.Tally t = new Removal(new File(a[1]), new File(a[2]), a[3]).remove();
            System.out.println(t.freed + " " + t.left + " " + (t.leftAt != null ? t.leftAt : "-"));
            break;
        }
        case "sweep": System.out.println(Removal.sweep(new File(a[1]))); break;
        case "size": System.out.println(Removal.size(Long.parseLong(a[1]))); break;
        case "where": System.out.println(Removal.where(new File(a[1]))); break;
        case "bad":
            try { new Removal(new File(a[1]), new File(a[2]), a[3]); System.out.println("taken"); } catch (IllegalArgumentException e) { System.out.println("refused"); }
            break;
        }
    }
}
'''


@unittest.skipUnless(JDK and ANDROID_JAR, 'needs a JDK (JAVA_HOME, or javac on PATH) and the Android SDK (ANDROID_HOME, or the Mac\'s default)')
class Remove(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert JDK is not None and ANDROID_JAR is not None
        cls.build = Path(tempfile.mkdtemp())
        src = cls.build / 'src'; out = cls.build / 'out'; src.mkdir(); out.mkdir()
        (src / 'RemoveCheck.java').write_text(DRIVER)
        javas = [str(p) for p in (REPO / 'dm/android/java').rglob('*.java')] + [str(src / 'RemoveCheck.java')]
        subprocess.run([JDK[0], '-source', '8', '-target', '8', '-Xlint:none', '-nowarn', '-encoding', 'UTF-8', '-bootclasspath', str(ANDROID_JAR), '-cp', str(ANDROID_JAR),
                        '-d', str(out), *javas], check=True, capture_output=True)
        cls.classes = out

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.build)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.ext = self.tmp / 'ext'; self.internal = self.tmp / 'internal'

    def run_java(self, *args) -> 'list[str]':
        assert JDK is not None
        r = subprocess.run([JDK[1], '-cp', f'{ANDROID_JAR}{os.pathsep}{self.classes}', 'org.nxnative.android.RemoveCheck', *map(str, args)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split()

    def phone(self, defaults='DM_LANG=en-US\n', name=TID) -> Path:   # a launcher install of TID beside another game, saves, backups and caches
        tree(self.ext, {f'games/{name}/code/main.fixups.tsv': 'f' * 100, f'games/{name}/code/main.patched.bin': 'c' * 1000, f'games/{name}/spv/a.spv': 's' * 300,
                        f'games/{name}/RomFS.img': 'r' * 5000, f'games/{name}/defaults.txt': defaults, f'games/{name}/launcher.txt': 'DM_OPMODE=0\n',
                        f'games/{name}/glslc_capture/': '', f'games/{OTHER}/code/main.fixups.tsv': 'o', 'env.txt': 'DM_SHOW_FPS=1\n',
                        f'backups/20261112-120000-{TID}/saves/{TID}/s.bin': 'old save', f'import/{TID}/s.bin': 'sent'})
        tree(self.internal, {f'saves/{TID}/s.bin': 'save', f'saves/{TID}_device/d.bin': 'device save', f'cache/{TID}/pipeline.cache': 'p' * 700,
                             f'cache/{TID}/pipeline.cache.keys4': 'k' * 70, f'saves/{OTHER}/s.bin': 'other', f'cache/{OTHER}/pipeline.cache': 'q'})
        return self.ext / 'games' / name

    def kept(self) -> None:   # everything that isn't the game's own is as it was
        self.assertEqual(files_of(self.internal / 'saves'), {f'{TID}/s.bin': b'save', f'{TID}_device/d.bin': b'device save', f'{OTHER}/s.bin': b'other'})
        self.assertEqual(files_of(self.internal / 'cache'), {f'{OTHER}/pipeline.cache': b'q'})
        self.assertTrue((self.ext / f'backups/20261112-120000-{TID}/saves/{TID}/s.bin').is_file())
        self.assertTrue((self.ext / f'import/{TID}/s.bin').is_file())
        self.assertTrue((self.ext / 'env.txt').is_file())
        self.assertEqual(sorted(p.name for p in (self.ext / 'games').iterdir()), [OTHER])   # no .removing- folder left either

    def test_game_and_cache_go_saves_stay(self):
        game = self.phone()
        game_bytes = sum(p.stat().st_size for p in game.rglob('*') if p.is_file())
        self.assertEqual(self.run_java('plan', game, self.internal, TID), [str(game_bytes), '770', '0', '-', 'false'])
        self.assertEqual(self.run_java('remove', game, self.internal, TID), [str(game_bytes + 770), '0', '-'])
        self.kept()

    def test_lowercase_folder(self):   # the launcher lists a folder named in any case; the host names the cache in capitals
        game = self.phone(name=TID.lower())
        self.assertEqual(self.run_java('remove', game, self.internal, TID.lower())[1:], ['0', '-'])
        self.kept()

    def test_romfs_dir_image_goes(self):   # --romfs-dir sd: the image and a copy's pieces in the card's romfs/<title ID>/, its folder too; the folder above and another game's stay
        card = self.tmp / 'card/Android/data/org.nxnative.android/files/romfs'
        tree(card, {f'{TID}/RomFS.img': 'R' * 4000, f'{TID}/RomFS.img.partial': 'P' * 10, f'{OTHER}/RomFS.img': 'O'})
        game = self.phone(f'DM_LANG=en-US\nDM_ROMFS={card}/{TID}/RomFS.img\nDM_VK_OCCLUSION=0\n')
        (game / 'RomFS.img').unlink()   # an install with --romfs-dir deletes the game folder's copy
        plan = self.run_java('plan', game, self.internal, TID)
        self.assertEqual(plan[2:], ['4010', str((card / TID / 'RomFS.img').resolve()), 'true'])
        freed = self.run_java('remove', game, self.internal, TID)
        self.assertEqual(freed, [str(int(plan[0]) + 770 + 4010), '0', '-'])
        self.assertFalse((card / TID).exists())
        self.assertEqual(files_of(card), {f'{OTHER}/RomFS.img': b'O'})
        self.kept()

    def test_romfs_dir_card_out(self):   # the image can't be seen (the card taken out): named, counted as nothing, and the removal goes on
        game = self.phone(f'DM_ROMFS={self.tmp}/gone/romfs/{TID}/RomFS.img\n')
        self.assertEqual(self.run_java('plan', game, self.internal, TID)[2:], ['0', str((self.tmp / f'gone/romfs/{TID}/RomFS.img').resolve()), 'false'])
        self.assertEqual(self.run_java('remove', game, self.internal, TID)[1:], ['0', '-'])
        self.kept()

    def test_dm_romfs_not_the_installs(self):   # what defaults.txt's DM_ROMFS names that isn't <folder>/<title ID>/RomFS.img outside the game's folder stays
        other = tree(self.tmp / 'mine', {f'{OTHER}/RomFS.img': 'x', f'{TID}/game.img': 'y', 'RomFS.img': 'z'})
        for value in ['fd:12:0:4096', f'{other}/{OTHER}/RomFS.img', f'{other}/{TID}/game.img', f'{other}/RomFS.img', 'romfs/RomFS.img']:
            with self.subTest(value=value):
                game = self.phone(f'DM_ROMFS={value}\n')
                self.assertEqual(self.run_java('plan', game, self.internal, TID)[2:4], ['0', '-'])
                shutil.rmtree(game)
        game = self.phone(f'DM_ROMFS={self.ext}/games/{TID}/sub/{TID}/RomFS.img\n')   # inside the game's folder: goes with it, counted once
        tree(game, {f'sub/{TID}/RomFS.img': 'i' * 50})
        self.assertEqual(self.run_java('plan', game, self.internal, TID)[2:4], ['0', '-'])
        card = tree(self.tmp / 'card', {f'{TID}/RomFS.img': 'c'})   # the first DM_ROMFS is the one the host takes (front_android.c env_file)
        game = self.phone(f'DM_ROMFS={other}/{TID}/game.img\nDM_ROMFS={card}/{TID}/RomFS.img\n')
        self.assertEqual(self.run_java('plan', game, self.internal, TID)[3], '-')
        self.assertEqual(files_of(other), {f'{OTHER}/RomFS.img': b'x', f'{TID}/game.img': b'y', 'RomFS.img': b'z'})

    def test_links_not_followed(self):   # a link in the game's folder goes, what it points at stays and isn't counted
        outside = tree(self.tmp / 'outside', {'keep/a.bin': 'a' * 999, 'b.bin': 'b' * 999})
        game = self.phone()
        try:
            os.symlink(outside / 'keep', game / 'linked', target_is_directory=True); os.symlink(outside / 'b.bin', game / 'code/b.bin')
        except (OSError, NotImplementedError) as e: self.skipTest(f'no symbolic links here: {e}')
        before = self.run_java('plan', game, self.internal, TID)
        self.assertEqual(self.run_java('remove', game, self.internal, TID), [str(int(before[0]) + 770), '0', '-'])
        self.assertEqual(files_of(outside), {'keep/a.bin': b'a' * 999, 'b.bin': b'b' * 999})
        self.kept()

    @unittest.skipIf(os.name == 'nt' or (hasattr(os, 'geteuid') and os.geteuid() == 0), 'needs a folder its owner may not change (not Windows, not root)')
    def test_files_that_stay_are_named(self):   # a folder the app may not change (adb made it and its chmod was cut short): what stays is said, the rest goes
        game = self.phone()
        def unlock():   # for the clean-up, wherever the test stopped
            for p in (game / 'spv', self.ext / f'games/.removing-{TID}/spv'):
                if p.exists(): os.chmod(p, 0o755)
        os.chmod(game / 'spv', 0o555); self.addCleanup(unlock)
        out = self.run_java('remove', game, self.internal, TID)
        self.assertGreater(int(out[1]), 0)
        self.assertEqual(out[2], str(self.ext / f'games/.removing-{TID}/spv/a.spv'))
        self.assertEqual(files_of(self.ext / f'games/.removing-{TID}'), {'spv/a.spv': b's' * 300})   # renamed out of the games list; only what was locked stays
        self.assertFalse((self.internal / f'cache/{TID}').exists())
        os.chmod(self.ext / f'games/.removing-{TID}/spv', 0o755)
        self.assertEqual(self.run_java('sweep', self.ext / 'games'), ['1'])   # the next start finishes it
        self.kept()

    def test_sweep(self):   # games/.removing-<title ID> folders go; a game, and anything else, stay
        tree(self.ext / 'games', {f'.removing-{TID}/code/x': 'x', f'.removing-{OTHER.lower()}/y': 'y', '.removing-notes/z': 'z', f'{TID}/code/main.fixups.tsv': 'f'})
        self.assertEqual(self.run_java('sweep', self.ext / 'games'), ['2'])
        self.assertEqual(sorted(p.name for p in (self.ext / 'games').iterdir()), ['.removing-notes', TID])
        self.assertEqual(self.run_java('sweep', self.tmp / 'nothing'), ['0'])

    def test_title_id_checked(self):   # the ID names a folder, so only 16 hex digits
        for bad in ['../../saves', '0100000011D9000', '0100000011D90000/..', '']:
            with self.subTest(bad=bad): self.assertEqual(self.run_java('bad', self.tmp, self.internal, bad), ['refused'])

    def test_words(self):
        self.assertEqual([self.run_java('size', n) for n in (0, 600_000, 52_428_800, 1 << 30, 13_207_024_435)], [['0', 'MB'], ['1', 'MB'], ['50', 'MB'], ['1.0', 'GB'], ['12.3', 'GB']])
        self.assertEqual(self.run_java('where', '/storage/1A2B-3C4D/Android/data/org.nxnative.android/files/romfs/0100000011D90000/RomFS.img'), ['on', 'the', 'SD', 'card'])
        self.assertEqual(' '.join(self.run_java('where', '/storage/emulated/0/romfs/0100000011D90000/RomFS.img')), 'in /storage/emulated/0/romfs/0100000011D90000')


if __name__ == '__main__':
    unittest.main()
