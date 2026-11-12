"""The Android launcher's save import and export (dm/android/java/org/nxnative/android/Saves.java), run on a JVM over the SDK's android.jar stubs: finding the save in
the layouts other tools write (a DroidPlay export or backup, yuzu and its successors, Ryujinx, JKSV, EdiZon, Checkpoint, UltraTears, a bare folder), matching it to
the game, keeping the current save first and swapping the new one in, the export ZIP, the ZIP reader's limits and the saves kept for Restore. Synthetic saves only:
no phone and no game files."""
import os
from pathlib import Path
from typing import Mapping, Union
import shutil
import struct
import subprocess
import tempfile
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[3]
TID, OTHER = '0100000011D90000', '01006F8002326000'
UID1, UID2 = '36A250565B2EA2C6F4603C0A7FA0AACD', '00000000000000010000000000000002'


def jdk() -> 'tuple[str, str] | None':   # as test_android_cli.py's: JAVA_HOME's javac and java, else PATH's, when javac runs
    home = os.environ.get('JAVA_HOME')
    javac, java = (str(Path(home, 'bin', 'javac')), str(Path(home, 'bin', 'java'))) if home else (shutil.which('javac'), shutil.which('java'))
    if not javac or not java: return None
    try: return (javac, java) if subprocess.run([javac, '-version'], capture_output=True, timeout=60).returncode == 0 else None
    except (OSError, subprocess.SubprocessError): return None


JDK = jdk()
ANDROID_JAR = next(iter(sorted(Path(os.environ.get('ANDROID_HOME') or Path.home() / 'Library/Android/sdk').glob('platforms/android-*/android.jar'), reverse=True)), None)

# A driver of Saves' package-private methods: one command per run, its results one per line
DRIVER = r'''package org.nxnative.android;
import java.io.*;
import java.util.*;
public class SaveCheck {
    static Set<String> names(String p) { return p.equals("-") ? new HashSet<String>() : Saves.names(new File(p)); }
    static String rel(File root, File f) {
        if (f == null) return "-";
        String r = root.getAbsoluteFile().toURI().relativize(f.getAbsoluteFile().toURI()).getPath();
        return r.endsWith("/") ? r.substring(0, r.length() - 1) : r;
    }
    // stands in for android.system.Os: every file has user.x = its name's length; apply prints what it was asked
    static final Saves.Xattrs XA = new Saves.Xattrs() {
        public void read(File f, String rel, StringBuilder tsv) { if (f.isFile()) tsv.append(rel).append("\tuser.x\t").append(String.format("%02x", f.getName().length())).append('\n'); }
        public void apply(File root, String top, File tsv) { System.out.println("apply " + root.getName() + " " + top + " " + tsv.getName()); }
    };
    public static void main(String[] a) throws Exception {
        switch (a[0]) {
        case "find": {
            File root = new File(a[1]);
            for (Saves.Found f : Saves.find(root, a[2], names(a[3]), names(a[4])))
                System.out.println(f.format + "|" + f.titleId + "|" + rel(root, f.account) + "|" + rel(root, f.device) + "|" + f.label + "|" + f.files + "|"
                    + (f.matched ? "matched" : f.unmatched ? "unmatched" : "-"));
            break;
        }
        case "import": {   // internal tid source index keep [xattrs]
            File in = new File(a[1]); String tid = a[2]; Saves.Xattrs xa = a.length > 6 ? XA : null;
            List<Saves.Found> fs = Saves.find(new File(a[3]), tid, Saves.names(new File(in, "saves/" + tid)), Saves.names(new File(in, "saves/" + tid + "_device")));
            System.out.println(Saves.keep(in, tid, new File(a[5]), "kept\n", xa) ? "kept" : "nothing to keep");
            Saves.install(in, tid, fs.get(Integer.parseInt(a[4])), xa);
            System.out.println("installed");
            break;
        }
        case "export":
            try (OutputStream o = new FileOutputStream(a[3])) { System.out.println(Saves.export(new File(a[1]), a[2], o, "readme\n", a.length > 4 ? XA : null)); }
            break;
        case "unzip":
            try { System.out.println(Saves.unzip(new File(a[1]), new File(a[2]), Long.parseLong(a[3]))); } catch (IOException e) { System.out.println("error: " + e.getMessage()); }
            break;
        case "kept":
            for (Saves.Found f : Saves.kept(new File(a[1]), a[2])) System.out.println(f.label + "|" + (f.account != null) + "|" + (f.device != null) + "|" + f.files);
            break;
        case "restore": {   // internal tid backups index: a kept save back, after keeping the current one
            File in = new File(a[1]); Saves.Found f = Saves.kept(new File(a[3]), a[2]).get(Integer.parseInt(a[4]));
            Saves.keep(in, a[2], new File(a[3], "now"), "kept\n", null); Saves.install(in, a[2], f, null);
            System.out.println("restored " + f.label);
            break;
        }
        case "kind": System.out.println(Saves.kind(Saves.head(new File(a[1]), 8))); break;
        case "top": System.out.println(Saves.top(new File(a[1]), Integer.parseInt(a[2]))); break;
        }
    }
}
'''


def tree(root: Path, files: 'Mapping[str, bytes | str]') -> Path:   # files by path under root; a path ending in / is an empty folder
    for p, data in files.items():
        f = root / p
        if p.endswith('/'): f.mkdir(parents=True, exist_ok=True); continue
        f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(data.encode() if isinstance(data, str) else data)
    return root


def files_of(root: Path) -> 'dict[str, bytes]':
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}


def extra_data(tid: str, kind: int) -> bytes:   # Ryujinx's ExtraData0: LibHac's SaveDataExtraData, its SaveDataAttribute first
    return struct.pack('<Q16sQB', int(tid, 16), bytes.fromhex(UID1), 0, kind).ljust(0x200, b'\0')


def jksv_meta(tid: str, kind: int) -> bytes:   # JKSV's fs::SaveMetaData, packed
    return struct.pack('<IBQ16sQBBHQQIqqQB', 0x56534B4A, 1, int(tid, 16), bytes.fromhex(UID1), 0, kind, 0, 0, 0, 0, 0, 0, 0, 0, 0)


@unittest.skipUnless(JDK and ANDROID_JAR, 'needs a JDK (JAVA_HOME, or javac on PATH) and the Android SDK (ANDROID_HOME, or the Mac\'s default)')
class Saves(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert JDK is not None and ANDROID_JAR is not None
        cls.build = Path(tempfile.mkdtemp())
        src = cls.build / 'src'; out = cls.build / 'out'; src.mkdir(); out.mkdir()
        (src / 'SaveCheck.java').write_text(DRIVER)
        javas = [str(p) for p in (REPO / 'dm/android/java').rglob('*.java')] + [str(src / 'SaveCheck.java')]
        subprocess.run([JDK[0], '-source', '8', '-target', '8', '-Xlint:none', '-nowarn', '-encoding', 'UTF-8', '-bootclasspath', str(ANDROID_JAR), '-cp', str(ANDROID_JAR),
                        '-d', str(out), *javas], check=True, capture_output=True)
        cls.classes = out

    @classmethod
    def tearDownClass(cls): shutil.rmtree(cls.build)

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)

    def run_java(self, *args) -> 'list[str]':
        assert JDK is not None
        r = subprocess.run([JDK[1], '-cp', f'{ANDROID_JAR}{os.pathsep}{self.classes}', 'org.nxnative.android.SaveCheck', *map(str, args)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.splitlines()

    def find(self, root, tid=TID, account: 'Union[str, Path]' = '-', device: 'Union[str, Path]' = '-') -> 'list[list[str]]':
        return [line.split('|') for line in self.run_java('find', root, tid, account, device)]

    # ---- the layouts ----
    def test_droidplay_export_round_trip(self):   # an export is a backup of one game: found as DroidPlay's, both parts, and swapped in whole
        phone = tree(self.tmp / 'phone', {f'saves/{TID}/SaveData.bin': 'mine', f'saves/{TID}/sub/b.bin': 'b', f'saves/{TID}_device/d.bin': 'dev', f'saves/{OTHER}/x': 'x'})
        z = self.tmp / 'export.zip'
        self.assertEqual(self.run_java('export', phone, TID, z, 'xattrs'), ['3'])
        with zipfile.ZipFile(z) as zf:
            names = zf.namelist()
            self.assertIn(f'saves/{TID}/SaveData.bin', names); self.assertIn(f'saves/{TID}_device/d.bin', names); self.assertIn('README.txt', names)
            self.assertFalse([n for n in names if OTHER in n])   # one game's save only
            self.assertIn(f'saves/{TID}/sub/b.bin\tuser.x\t05', zf.read('xattrs.tsv').decode())
        stage = self.tmp / 'stage'; stage.mkdir()
        self.assertEqual(self.run_java('unzip', z, stage, 1 << 30), ['5'])
        self.assertEqual(self.find(stage), [['DroidPlay', TID, f'saves/{TID}', f'saves/{TID}_device', TID, '3', '-']])
        other = tree(self.tmp / 'other', {f'saves/{TID}/SaveData.bin': 'theirs', f'saves/{TID}.work/SaveData.bin': 'half-written'})
        out = self.run_java('import', other, TID, stage, 0, self.tmp / 'kept', 'xattrs')
        self.assertEqual(out, ['kept', f'apply {TID}.importing saves/{TID} xattrs.tsv', f'apply {TID}_device.importing saves/{TID}_device xattrs.tsv', 'installed'])
        self.assertEqual(files_of(other / 'saves'), {f'{TID}/SaveData.bin': b'mine', f'{TID}/sub/b.bin': b'b', f'{TID}_device/d.bin': b'dev'})   # the host's .work went too
        self.assertEqual(files_of(self.tmp / 'kept'), {f'saves/{TID}/SaveData.bin': b'theirs', 'xattrs.tsv': f'saves/{TID}/SaveData.bin\tuser.x\t0c\n'.encode(), 'README.txt': b'kept\n'})

    def test_yuzu_users_and_device_save(self):   # nand/user/save/0000000000000000/<user>/<title ID>/: one per user, the all-zero user's is the device save
        root = tree(self.tmp / 'stage', {f'nand/user/save/0000000000000000/{UID1}/{TID}/a': 'a', f'nand/user/save/0000000000000000/{UID2}/{TID}/b': 'bb',
                                         f'nand/user/save/0000000000000000/{UID1}/{OTHER}/z': 'z', f'nand/user/save/0000000000000000/{"0" * 32}/{TID}/d': 'd'})
        got = sorted(self.find(root))
        base = 'nand/user/save/0000000000000000'
        self.assertEqual(got, sorted([['yuzu', TID, f'{base}/{UID1}/{TID}', '-', f'user {UID1}', '1', '-'], ['yuzu', TID, f'{base}/{UID2}/{TID}', '-', f'user {UID2}', '1', '-'],
                                      ['yuzu', TID, '-', f'{base}/{"0" * 32}/{TID}', 'device save', '1', '-']]))

    def test_another_games_save_only_when_nothing_else(self):
        root = tree(self.tmp / 'stage', {f'{UID1}/{OTHER}/z': 'z'})
        self.assertEqual(self.find(root), [['yuzu', OTHER, f'{UID1}/{OTHER}', '-', f'user {UID1}', '1', '-']])

    def test_ryujinx(self):   # bis/user/save/<save ID>/0/: ExtraData0 says whose, and its type says a device save
        root = tree(self.tmp / 'stage', {'save/0000000000000001/0/slot/a': 'a', 'save/0000000000000001/1/slot/a': 'working', 'save/0000000000000001/ExtraData0': extra_data(TID, 1),
                                         'save/0000000000000001/ExtraData1': extra_data(TID, 1), 'save/0000000000000001/.lock': '',
                                         'save/0000000000000002/0/b': 'b', 'save/0000000000000002/ExtraData0': extra_data(OTHER, 1),
                                         'save/0000000000000003/0/d': 'd', 'save/0000000000000003/ExtraData0': extra_data(TID, 3)})
        self.assertEqual(sorted(self.find(root)), [['Ryujinx', TID, '-', 'save/0000000000000003/0', '0000000000000003', '1', '-'],
                                                   ['Ryujinx', TID, 'save/0000000000000001/0', '-', '0000000000000001', '1', '-']])
        old = tree(self.tmp / 'old', {'0000000000000004/0/c': 'c', '0000000000000004/1/c': 'c'})   # before ExtraData: the save ID's folder name
        self.assertEqual(self.find(old), [['Ryujinx', 'null', '0000000000000004/0', '-', '0000000000000004', '1', '-']])

    def test_jksv(self):   # its meta file names the game and is left out of the save; an older JKSV's folder is known by its dated name
        root = tree(self.tmp / 'stage', {'JKSV/Game/Vip - 2023.01.22 @ 15.10.11/data0006.bin': 'save', 'JKSV/Game/Vip - 2023.01.22 @ 15.10.11/.nx_save_meta.bin': jksv_meta(TID, 1)})
        self.assertEqual(self.find(root), [['JKSV', TID, 'JKSV/Game/Vip - 2023.01.22 @ 15.10.11', '-', 'Vip - 2023.01.22 @ 15.10.11', '1', '-']])
        phone = self.tmp / 'phone'; phone.mkdir()
        self.assertEqual(self.run_java('import', phone, TID, root, 0, self.tmp / 'kept'), ['nothing to keep', 'installed'])
        self.assertEqual(files_of(phone / 'saves'), {f'{TID}/data0006.bin': b'save'})
        old = tree(self.tmp / 'old', {'JKSV/Persona 3 Portable/Vip - 2023.01.22 @ 15.10.11/data0006.bin': 'save'})
        self.assertEqual(self.find(old), [['JKSV', 'null', 'JKSV/Persona 3 Portable/Vip - 2023.01.22 @ 15.10.11', '-', 'Vip - 2023.01.22 @ 15.10.11', '1', '-']])

    def test_edizon_and_checkpoint(self):
        meta = f'{{"title_id": "{TID}", "title_name": "Game", "title_version": "1.0.1", "user_id": "{UID1}", "user_name": "Rick"}}'
        root = tree(self.tmp / 'ed', {f'saves/{TID}/20220320_225347/edizon_save_metadata.json': meta, f'saves/{TID}/20220320_225347/savedata0.bin': 's0'})
        self.assertEqual(self.find(root), [['EdiZon', TID, f'saves/{TID}/20220320_225347', '-', 'Rick, 20220320_225347', '1', '-']])
        phone = self.tmp / 'phone'; phone.mkdir()
        self.run_java('import', phone, TID, root, 0, self.tmp / 'kept')
        self.assertEqual(files_of(phone / 'saves'), {f'{TID}/savedata0.bin': b's0'})   # without EdiZon's own file
        cp = tree(self.tmp / 'cp', {f'Checkpoint/saves/0x{TID} Game/20200101-120000 Rick/a': 'a', f'Checkpoint/saves/0x{TID} Game/20200102-120000 Rick/a': 'a2'})
        self.assertEqual(sorted(r[:3] for r in self.find(cp)), [['Checkpoint', TID, f'Checkpoint/saves/0x{TID} Game/20200101-120000 Rick'],
                                                                ['Checkpoint', TID, f'Checkpoint/saves/0x{TID} Game/20200102-120000 Rick']])

    def test_bare_folders(self):   # UltraTears' save, a zip's one folder, a zip of the save's own files; where the game has a save, the folder that matches it
        ut = {f'userdata/save/{UID1.lower()}/{n}': 'x' for n in ('option.sav', 'slot_00/progress.sav', 'slot_01/progress.sav', 'picturebook/a', 'storage/b')}
        root = tree(self.tmp / 'ut', ut)
        self.assertEqual(self.find(root)[0][:3], ['folder', 'null', f'userdata/save/{UID1.lower()}'])   # no save to compare with: the end of the lone folders
        cur = tree(self.tmp / 'cur', {'option.sav': 'o', 'slot_00/progress.sav': 'p'})
        self.assertEqual(self.find(root, account=cur), [['folder', 'null', f'userdata/save/{UID1.lower()}', '-', UID1.lower(), '5', 'matched']])
        smash = tree(self.tmp / 'smash', {'save_data/system_data.bin': 's', 'save_data/mii/mii_64.bin': 'm'})   # a zip of the save's own top folder
        self.assertEqual(self.find(smash, account=tree(self.tmp / 'cur2', {'save_data/system_data.bin': 'old'}))[0][2], '')
        oot = tree(self.tmp / 'oot', {'OoT 100 % Savegame [0400486024dec000]/option.sav': 'o', 'OoT 100 % Savegame [0400486024dec000]/slot_00/progress.sav': 'p'})
        self.assertEqual(self.find(oot, tid='0400486024DEC000'), [['folder', 'null', 'OoT 100 % Savegame [0400486024dec000]', '-', 'OoT 100 % Savegame [0400486024dec000]', '2', '-']])
        self.assertEqual(self.find(oot, tid='0400486024DEC000', account=tree(self.tmp / 'cur3', {'main': 'x'}))[0][6], 'unmatched')   # shares no name with the save here
        empty = self.tmp / 'empty'; empty.mkdir()
        self.assertEqual(self.find(empty), [])

    def test_bare_device_save(self):   # a game with both kinds of save: the folder matching its device save goes there
        root = tree(self.tmp / 'stage', {'pick/common.dat': 'c'})
        phone = tree(self.tmp / 'phone', {f'saves/{TID}/userdata.dat': 'u', f'saves/{TID}_device/common.dat': 'old'})
        self.assertEqual(self.find(root, account=phone / f'saves/{TID}', device=phone / f'saves/{TID}_device')[0][2:4], ['-', 'pick'])
        self.run_java('import', phone, TID, root, 0, self.tmp / 'kept')
        self.assertEqual(files_of(phone / 'saves'), {f'{TID}/userdata.dat': b'u', f'{TID}_device/common.dat': b'c'})

    def test_a_device_save_where_the_game_keeps_one_save(self):   # Animal Crossing's island is device save data, and the host makes it the game's one save
        root = tree(self.tmp / 'stage', {'save/0000000000000001/0/main.dat': 'island', 'save/0000000000000001/ExtraData0': extra_data(TID, 3)})
        phone = tree(self.tmp / 'phone', {f'saves/{TID}/main.dat': 'old island'})
        self.run_java('import', phone, TID, root, 0, self.tmp / 'kept')
        self.assertEqual(files_of(phone / 'saves'), {f'{TID}/main.dat': b'island'})

    # ---- the swap, Restore ----
    def test_kept_saves_and_restore(self):
        phone = tree(self.tmp / 'phone', {f'saves/{TID}/a': 'now'})
        backups = tree(self.tmp / 'backups', {f'20261111-120000-{TID}/saves/{TID}/a': 'before import', f'20261110-090000/saves/{TID}/a': 'full backup',
                                              f'20261110-090000/saves/{OTHER}/x': 'x', f'20261109-090000/saves/{OTHER}/x': 'x', f'restore/saves/{TID}/a': 'pending'})
        self.assertEqual(self.run_java('kept', backups, TID), [f'20261111-120000-{TID}|true|false|1', '20261110-090000|true|false|1'])
        self.assertEqual(self.run_java('restore', phone, TID, backups, 1), ['restored 20261110-090000'])
        self.assertEqual(files_of(phone / 'saves'), {f'{TID}/a': b'full backup'})
        self.assertEqual((backups / f'now/saves/{TID}/a').read_bytes(), b'now')

    def test_swap_cut_short_leaves_the_host_its_side_folder(self):   # a leftover <save>.swap from an earlier cut-short swap is cleared before this one
        phone = tree(self.tmp / 'phone', {f'saves/{TID}/a': 'now', f'saves/{TID}.swap/a': 'stale', f'saves/{TID}.importing/junk': 'j'})
        root = tree(self.tmp / 'stage', {'pick/a': 'new'})
        self.run_java('import', phone, TID, root, 0, self.tmp / 'kept')
        self.assertEqual(files_of(phone / 'saves'), {f'{TID}/a': b'new'})

    # ---- the files picked ----
    def test_zip_limits(self):
        bad = self.tmp / 'slip.zip'
        with zipfile.ZipFile(bad, 'w') as z: z.writestr('../outside', 'x')
        self.assertTrue(self.run_java('unzip', bad, self.tmp / 'd1', 1 << 20)[0].startswith('error: a file outside the folder'))
        big = self.tmp / 'big.zip'
        with zipfile.ZipFile(big, 'w', zipfile.ZIP_DEFLATED) as z: z.writestr('a', b'\0' * 100_000)
        self.assertTrue(self.run_java('unzip', big, self.tmp / 'd2', 50_000)[0].startswith('error: too big'))
        d64 = self.tmp / 'd64.zip'   # Deflate64 (method 9), as Windows' own zip writes big files: named, not misread
        with zipfile.ZipFile(d64, 'w') as z: z.writestr('a.bin', b'data')
        raw = bytearray(d64.read_bytes())
        for sig, at in ((b'PK\x03\x04', 8), (b'PK\x01\x02', 10)): i = raw.index(sig); raw[i + at:i + at + 2] = struct.pack('<H', 9)
        d64.write_bytes(bytes(raw))
        self.assertTrue(self.run_java('unzip', d64, self.tmp / 'd3', 1 << 20)[0].startswith('error: method 9'))
        junk = self.tmp / 'mac.zip'
        with zipfile.ZipFile(junk, 'w') as z: z.writestr('save/a', 'a'); z.writestr('__MACOSX/save/._a', 'x'); z.writestr('save/.DS_Store', 'x')
        self.assertEqual(self.run_java('unzip', junk, self.tmp / 'd4', 1 << 20), ['1'])
        cp = self.tmp / 'cp437.zip'   # an old Windows zip's name: code page 437, no UTF-8 flag
        with zipfile.ZipFile(cp, 'w') as z: z.writestr('caf?.sav', 'x')
        raw = bytearray(cp.read_bytes()); raw = bytearray(bytes(raw).replace(b'caf?', b'caf\x82'))
        cp.write_bytes(bytes(raw))
        self.assertEqual(self.run_java('unzip', cp, self.tmp / 'd5', 1 << 20), ['1'])
        self.assertTrue((self.tmp / 'd5/café.sav').is_file())

    def test_kind_and_top(self):
        for data, want in ((b'PK\x03\x04rest', 'zip'), (b'Rar!\x1a\x07\x01\x00', 'RAR'), (b'7z\xbc\xaf\x27\x1c\x00\x04', '7z'), (b'\x1f\x8b\x08\x00', 'gzip'), (b'main', 'null')):
            f = self.tmp / 'f'; f.write_bytes(data)
            self.assertEqual(self.run_java('kind', f), [want])
        save = tree(self.tmp / 'save', {'option.sav': 'o', 'slot_00/a': 'a', 'slot_01/a': 'a', '.nx_save_meta.bin': 'm'})
        self.assertEqual(self.run_java('top', save, 2), ['option.sav, slot_00/ and 1 more'])


if __name__ == '__main__':
    unittest.main()
