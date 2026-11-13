"""The Android packing script's shader stage (scripts/build_android_from_nsp.py build_shaders) around the shader split (build_ipa_from_nsp.py split_shaders, stubbed here):
a registered profile's split error stops the build instead of packing the game without shaders, as a profile derived from a registered one's does (droidplay-core#307), a
provisional profile's still packs without them, and compute kernels a newer reader decodes, or DLC-only shaders, take the shader-only derived profile the iPhone build takes,
whose shader facts the translation then reads (droidplay-core#218). A translation that stops (spv_build.py, stubbed too) stops the build for every profile, instead of packing
the shaders translated so far, and a full disk is said plainly there and at the command line's exit, naming the drive that filled and what to free (droidplay-core#307);
a translator that makes nothing stops it too, with spv_build.py run for real."""
import contextlib
import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zlib

REPO = Path(__file__).resolve().parents[3]
# The script as test_android_cli loaded it: loading it binds build_ipa_from_nsp.build_nx_extract to its own function, so a second copy would take that over from those tests
sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_android_cli  # noqa: E402
import test_spv_build  # noqa: E402  # its shader records, for a real spv_build.py run
ba = test_android_cli.ba
GID = '010089B00D09C000'   # AI: THE SOMNIUM FILES, whose registered tables the reader outgrew


class Profile:   # the parts of game.py's profile that build_shaders reads
    def __init__(self, d): self.dir = Path(d); self.id = GID
    def table(self, name): return self.dir / name


class BuildShaders(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.work = self.tmp / 'work'; self.logs = self.work / 'logs'; self.logs.mkdir(parents=True)
        self.registered = Profile(REPO / 'dm/games' / GID)
        self.provisional = Profile(self.tmp / 'profile' / GID)
        self.ran = []; self.translation_stops = False; self.log_text = 'IndexError: list index out of range\n'
        def run(cmd, log, env=None, on_line=None):   # spv_build.py: its output folder and its last line, or what bi.run raises for its exit code
            self.ran.append([str(c) for c in cmd]); (self.work / 'spv').mkdir(exist_ok=True)
            if self.translation_stops:   # the post-pass stopped at an empty .spv after a few shaders were done (Pokopia's log)
                (self.work / 'spv' / '0123456789abcdef.spv').write_bytes(b'\3\2\x23\7'); Path(log).write_text(self.log_text)
                raise ba.BuildError(f'spv_build.py exit code 1 (full output: {log})')
            Path(log).write_text('spv_build: 3 translated\n')
        for p in (mock.patch.object(ba.bi, 'run', side_effect=run), mock.patch.object(ba.bi, 'PROG', mock.MagicMock()),
                  mock.patch.object(ba.bi.rfs, 'source', side_effect=lambda p: p), mock.patch.object(ba, 'say')):
            p.start(); self.addCleanup(p.stop)

    def tearDown(self): import shutil; shutil.rmtree(self.tmp, ignore_errors=True)

    def build(self, g, split, derive=None, derived=''):
        with mock.patch.object(ba.bi, 'split_shaders', side_effect=split) as sp:
            r = ba.build_shaders(['v65536'], {'v65536': self.tmp / 'v65536'}, self.work, self.logs, {}, g, (), derive, derived)
        return r, sp

    def test_a_registered_profiles_table_mismatch_stops_the_build(self):
        def split(*a, **k): raise ba.BuildError(f"the split shader tables differ from game profile {GID}'s:\nshader_map.tsv: 13057 rows, the split 13072")
        with self.assertRaises(ba.BuildError) as cm: self.build(self.registered, split)
        msg = str(cm.exception)
        self.assertIn('the split shader tables differ', msg); self.assertIn('not packed', msg); self.assertIn('shader_split.log', msg)
        self.assertEqual(self.ran, [])   # no translation, and no shaderless pack
        self.assertFalse(any('packed without shaders' in str(c) for c in ba.say.call_args_list))

    def test_a_provisional_profiles_split_error_still_packs_without_shaders(self):   # a game that compiles its shaders while it runs (docs/android.md)
        def split(*a, **k): raise ba.BuildError('the shader split found no shaders in main or the RomFS')
        (out, g), _ = self.build(self.provisional, split)
        self.assertIsNone(out); self.assertIs(g, self.provisional)
        self.assertTrue(any('packed without shaders' in str(c) for c in ba.say.call_args_list))

    def test_a_derived_profiles_split_error_stops_the_build(self):   # its profile is outside dm/games like a provisional one, but its registered parent lists the shaders (#307)
        derived = Profile(self.work / 'profile' / GID)
        why = f'not the builds game profile {GID} registers: main build ID 1234 is not the registered 5678'
        def split(*a, **k): raise ba.BuildError('shader_split.py failed: [WinError 87] The parameter is incorrect')
        with self.assertRaises(ba.BuildError) as cm: self.build(derived, split, derived=why)
        msg = str(cm.exception)
        self.assertIn('WinError 87', msg); self.assertIn('not packed', msg); self.assertIn(why, msg); self.assertIn('--package', msg); self.assertIn('shader_split.log', msg)
        self.assertEqual(self.ran, [])   # no translation, and no shaderless pack
        self.assertFalse(any('packed without shaders' in str(c) for c in ba.say.call_args_list))

    def test_a_translation_that_stops_stops_the_build_for_every_profile(self):   # #307: Pokopia's derived build packed "the shaders translated so far" and went on to the install
        derived = Profile(self.work / 'profile' / GID)
        self.translation_stops = True
        for name, g, why in (('registered', self.registered, ''), ('derived', derived, f'v65536 is not a version game profile {GID} registers'), ('provisional', self.provisional, '')):
            with self.subTest(profile=name):
                ba.say.reset_mock()
                with self.assertRaises(ba.BuildError) as cm: self.build(g, lambda *a, **k: None, derived=why)
                msg = str(cm.exception)
                self.assertIn('spv_build.py exit code 1', msg); self.assertIn('Shader translation failed, so the game is not packed', msg)
                self.assertIn(str(self.logs / 'spv_build.log'), msg)
                self.assertFalse(any('translated so far' in str(c) and 'packed with' in str(c) for c in ba.say.call_args_list), ba.say.call_args_list)
                self.assertTrue((self.work / 'spv' / '0123456789abcdef.spv').exists())   # the shaders done are kept: the next build skips them

    def test_a_full_disk_in_the_translation_is_said_plainly(self):   # spv_build.py's own line, or a tool's text, in its log: the drive, its free space, what to free
        self.translation_stops = True
        own = "[RED] spv_build: the disk is full: the translator could not write 3 shaders' output in its first pass (0123456789abcdef: IOException: There is not enough space on the disk. : 'C:\\x.spv'). The drive with C:\\g\\tmp has 0.0 GB free"
        for name, text in (('spv_build line', f'spv_build: 2 vertex shaders\n{own}\n'), ('traceback', 'OSError: [Errno 28] No space left on device\n')):
            with self.subTest(log=name):
                self.log_text = text
                with self.assertRaises(ba.BuildError) as cm: self.build(self.registered, lambda *a, **k: None)
                msg = str(cm.exception)
                self.assertIn('This computer ran out of disk space: the drive ', msg); self.assertIn(' free (writing ', msg); self.assertIn('_build folder', msg)
                self.assertIn('Shader translation failed, so the game is not packed', msg)
                if name == 'spv_build line': self.assertIn(own[6:], msg)   # its own reason, first

    def test_a_full_disk_names_the_drive_that_filled(self):   # not <id>_build's: runner-a's check filled a small drive mounted at <id>_build/tmp, and the message named the other
        self.translation_stops = True
        tmp = self.work / 'tmp' / 'spv_u8kizb6u' / 'out'; err = tmp / '1f8fd67ad5e3e355.res.json'
        own = (f"[RED] spv_build: the disk is full: the translator could not write 7 shaders' output in its first pass (1f8fd67ad5e3e355: IOException: No space left on device : "
               f"'{err}'). The drive with {tmp} has 0.0 GB free, before this run's temporary files are removed. Nothing more is translated: free some space and build again")
        small = self.work / 'tmp'; small.mkdir()   # the mount point stays; the run's spv_* folder in it is gone
        def on_small(p): p = Path(os.path.abspath(p)); return p == small or small in p.parents
        for name, text, path in (('spv_build line', own, tmp), ('traceback', f"OSError: [Errno 28] No space left on device: '{err}'", err)):
            with self.subTest(log=name):
                self.log_text = f'spv_build: 2 vertex shaders\n{text}\n'
                with mock.patch.object(ba, 'drive_of', side_effect=lambda p: '/Volumes/small' if on_small(p) else '/Volumes/1TB'), \
                     mock.patch.object(ba.shutil, 'disk_usage', side_effect=lambda p: SimpleNamespace(total=1 << 40, used=0, free=1_000_000_000 if on_small(p) else 755 << 30)):
                    with self.assertRaises(ba.BuildError) as cm: self.build(self.registered, lambda *a, **k: None)
                self.assertIn(f'This computer ran out of disk space: the drive /Volumes/small has 1.0 GB free (writing {path})', str(cm.exception))

    def test_a_nearly_full_drive_is_taken_for_a_full_disk(self):   # the log says nothing of the disk, but the drive has 100 MB left
        self.translation_stops = True
        with mock.patch.object(ba.shutil, 'disk_usage', return_value=SimpleNamespace(total=1 << 40, used=1 << 40, free=100_000_000)):
            with self.assertRaises(ba.BuildError) as cm: self.build(self.registered, lambda *a, **k: None)
        self.assertIn('has 100 MB free', str(cm.exception))

    def test_another_stop_says_nothing_of_the_disk(self):
        self.translation_stops = True
        with mock.patch.object(ba.shutil, 'disk_usage', return_value=SimpleNamespace(total=1 << 40, used=0, free=500 << 30)):
            with self.assertRaises(ba.BuildError) as cm: self.build(self.registered, lambda *a, **k: None)
        self.assertNotIn('disk space', str(cm.exception)); self.assertIn('Shader translation failed', str(cm.exception))

    def test_too_little_room_says_the_shaders_were_not_translated(self):   # spv_build.py's free-space check stopped it before it started
        self.translation_stops = True
        line = ("[RED] spv_build: not enough free space to translate 131,426 shaders (4,400 MB in the package): the drive with C:\\g\\0400A3A01EE4C000_build\\spv has 61.0 GB free, "
                "and they need about 90.1 GB there")
        self.log_text = line + '\n'
        with mock.patch.object(ba.shutil, 'disk_usage', return_value=SimpleNamespace(total=1 << 40, used=0, free=61 << 30)):
            with self.assertRaises(ba.BuildError) as cm: self.build(self.registered, lambda *a, **k: None)
        msg = str(cm.exception)
        self.assertIn(line[6:], msg); self.assertIn('The game is not packed: its shaders were not translated.', msg)
        self.assertNotIn('Shader translation failed', msg); self.assertNotIn('ran out of disk space', msg)

    def test_a_translation_with_red_lines_still_packs(self):   # a shader the translator can't handle is a line in the log, and spv_build.py exits 0
        (out, g), _ = self.build(self.registered, lambda *a, **k: None)
        self.assertEqual(out, self.work / 'spv'); self.assertIs(g, self.registered)

    def test_compute_kernels_a_newer_reader_decodes_take_the_derived_profile(self):
        derived = Profile(self.work / 'profile' / GID); reasons = []
        def derive(reason): reasons.append(reason); return derived
        def split(*a, **k): k['derive_compute']()   # split_shaders, once compute_reader_additions passed
        (out, g), sp = self.build(self.registered, split, derive)
        self.assertEqual(out, self.work / 'spv'); self.assertIs(g, derived)
        self.assertIn('additional compute kernels', reasons[0])
        self.assertIn(str(derived.table('shader_facts.tsv')), self.ran[0])   # the translation reads the derived profile's facts, with the kernels' rows
        self.assertIsNotNone(sp.call_args.kwargs['derive_dlc'])

    def test_dlc_only_shaders_take_the_derived_profile(self):
        derived = Profile(self.work / 'profile' / GID); reasons = []
        def split(*a, **k): k['derive_dlc']()
        (out, g), _ = self.build(self.registered, split, lambda r: reasons.append(r) or derived)
        self.assertIs(g, derived); self.assertIn('DLC', reasons[0])

    def test_a_registered_profile_whose_tables_match_keeps_its_profile(self):
        (out, g), sp = self.build(self.registered, lambda *a, **k: None, lambda r: self.fail('derived without a difference'))
        self.assertIs(g, self.registered); self.assertIn(str(self.registered.table('shader_facts.tsv')), self.ran[0])

    def test_a_provisional_profile_gets_no_derive_hooks(self):   # its split takes the tables as they come
        _, sp = self.build(self.provisional, lambda *a, **k: None, lambda r: self.fail('derived a provisional profile'))
        self.assertIsNone(sp.call_args.kwargs['derive_compute']); self.assertIsNone(sp.call_args.kwargs['derive_dlc'])

    def test_only_a_profile_that_registers_the_version_splits_from_its_map(self):   # split_shaders' targeted split (docs/reference/packing.md)
        derived = Profile(self.work / 'profile' / GID)
        for g, why, want in ((self.registered, '', True), (self.provisional, '', False), (derived, f'v65536 is not a version game profile {GID} registers', False)):
            with self.subTest(g='derived' if g is derived else g.dir.parent.name):
                _, sp = self.build(g, lambda *a, **k: None, derived=why)
                self.assertIs(sp.call_args.kwargs['targeted'], want)

    def test_no_versions_no_split(self):
        with mock.patch.object(ba.bi, 'split_shaders') as sp:
            self.assertEqual(ba.build_shaders([], {}, self.work, self.logs, {}, self.registered), (None, self.registered))
        sp.assert_not_called()


class NoneTranslated(unittest.TestCase):
    """build_shaders with spv_build.py run as a build runs it, over three shaders, and a translator that runs and makes nothing: dotnet with the translator's dll moved
    aside, as runner-a's check had it. spv_build.py ended '0 translated, …, 30 failed' with exit code 0, and the build packed the game without shaders
    (droidplay-core#307's follow-up). A stand-in script takes the dll's place, printing dotnet's first line and exiting 1"""
    GONE = 'Could not execute because the specified command or file was not found.'

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.work = self.tmp / 'work'; self.logs = self.work / 'logs'; (self.work / 'tmp').mkdir(parents=True)
        pkg = self.work / 'shader/pkg'; pkg.mkdir(parents=True); (pkg / 'ps_0.bin').write_bytes(b''.join(test_spv_build.record(i) for i in range(3)))
        if os.name == 'nt': self.xlate = self.tmp / 'xlate.cmd'; self.xlate.write_text(f'@echo {self.GONE} 1>&2\n@exit /b 1\n')   # Windows runs a .cmd through cmd.exe
        else: self.xlate = self.tmp / 'xlate'; self.xlate.write_text(f'#!/bin/sh\necho "{self.GONE}" >&2\nexit 1\n'); self.xlate.chmod(0o755)
        real = ba.bi.run
        def run(cmd, log, env=None, on_line=None):   # the run as build_shaders asks for it, the stand-in in the dll's place
            cmd = [str(c) for c in cmd]; cmd[cmd.index('--xlate') + 1] = str(self.xlate)
            return real(cmd, log, env=env)
        for p in (mock.patch.object(ba.bi, 'run', side_effect=run), mock.patch.object(ba.bi, 'PROG', mock.MagicMock()), mock.patch.object(ba.bi, 'split_shaders'),
                  mock.patch.object(ba.bi.rfs, 'source', side_effect=lambda p: p), mock.patch.object(ba, 'say')):
            p.start(); self.addCleanup(p.stop)

    def test_the_build_stops_and_says_the_game_is_not_packed(self):
        env = dict(os.environ, WORK=str(self.work / 'tmp'), DM_SPV_SPACE_CHECK='0')   # as main sets WORK; the room check would want 2 GB free here
        with self.assertRaises(ba.BuildError) as cm:
            ba.build_shaders(['v65536'], {'v65536': self.tmp / 'v65536'}, self.work, self.logs, env, Profile(REPO / 'dm/games' / GID))
        msg = str(cm.exception)
        self.assertIn('spv_build.py exit code 1', msg)
        self.assertIn(f'spv_build: no shader was translated: the translator made none of the 3 shaders it was given, and gave a reason for none of them (exit code 1: {self.GONE})', msg)
        self.assertIn('Shader translation failed, so the game is not packed', msg); self.assertNotIn('disk space', msg)
        log = (self.logs / 'spv_build.log').read_text(encoding='utf-8')
        self.assertIn('spv_build: 0 translated, 0 already there (0 given their constant buffer extents), 3 failed', log); self.assertEqual(log.count('no output from the translator'), 3)
        self.assertEqual(list((self.work / 'spv').glob('*.res.json')), []); self.assertEqual(list((self.work / 'tmp').iterdir()), [])


class DiskFull(unittest.TestCase):   # the message a full disk gets anywhere in the build (build_android_from_nsp.py disk_full) and the command line's exit
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_it_names_the_drive_its_free_space_and_what_to_free(self):
        f = self.tmp / 'logs/push_S/adb_push_romfs.piece'
        msg = ba.disk_full(f)
        self.assertIn(f'the drive {ba.drive_of(self.tmp)} has ', msg); self.assertIn(f'(writing {f})', msg)   # a file not there yet: its folder's drive
        self.assertIn('move the game\'s folder to a drive with more room', msg)
        self.assertIn('This computer ran out of disk space: the drive is full.', ba.disk_full(None))

    def test_leftover_translation_folders_in_the_system_temp_folder_are_named(self):   # every failed translation before spv_build.py used WORK left one
        (self.tmp / 'spv_a1').mkdir(); (self.tmp / 'spv_b2').mkdir(); (self.tmp / 'spv_note.txt').write_text('')
        with mock.patch.object(ba.tempfile, 'gettempdir', return_value=str(self.tmp)):
            self.assertIn(f'2 spv_… folders in {self.tmp} were left by failed shader translations of earlier versions', ba.disk_full(self.tmp))
            shutil.rmtree(self.tmp / 'spv_a1'); shutil.rmtree(self.tmp / 'spv_b2')
            self.assertNotIn('spv_…', ba.disk_full(self.tmp))

    def test_the_command_line_says_a_full_disk_plainly(self):   # Pokopia's build ended in a traceback, OSError: [Errno 28], from push_resumable's piece.write_bytes
        f = self.tmp / 'adb_push_romfs.piece'
        code = '\n'.join([
            'import argparse, errno, runpy, sys',
            'def full(self, args=None, namespace=None):',
            f'    raise OSError(errno.ENOSPC, "No space left on device", {str(f)!r})',
            'argparse.ArgumentParser.parse_args = full',
            "sys.argv = ['build_android_from_nsp.py', 'game']",
            f'runpy.run_path({str(ba.__file__)!r}, run_name="__main__")',
        ])
        r = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, encoding='utf-8', timeout=120)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 1, out)
        self.assertIn('[RED] This computer ran out of disk space: the drive ', out); self.assertIn(f'(writing {f})', out)
        self.assertNotIn('Traceback', out)


class OodleDecode(unittest.TestCase):
    """issue #310: a game whose shaders are in archives compressed with its own Oodle (profile_guess.py oodle_packs) has the split's streams decoded on the phone first (oodle_decode,
    scripts/android_oodle.py fill), or by the Mac host of DroidPlay for Mac's build of the same main (mac_decoder). The record split and the phone are stand-ins here"""
    def setUp(self):
        import android_oodle as ao   # pyright: ignore[reportMissingImports]  (scripts/, which the script puts on the path)
        self.ao = ao
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.nsp, self.work = self.tmp / 'game/android', self.tmp / 'game/android' / f'{GID}_build'
        self.game, self.logs = self.work / 'extract/v0', self.work / 'logs'
        (self.game / 'ExeFS').mkdir(parents=True); (self.game / 'RomFS').mkdir(); (self.game / 'RomFS/a.gfpak').write_bytes(b'GFLXPACK'); self.logs.mkdir(); (self.work / 'tmp').mkdir()
        (self.game / 'ExeFS/main').write_bytes(bytes(0x40) + bytes(range(16)) + bytes(0x40))   # its build ID: 000102…0f
        self.streams = [(b'\x8c' + zlib.compress(b'%d' % i * 99), len(b'%d' % i * 99)) for i in range(3)]
        self.records, self.jobs = [], []
        def run(cmd, log, env=None, on_line=None, fatal=True):   # the record split: it lists every stream its cache lacks
            self.records.append(cmd); assert env is not None and not fatal
            have = {(h, int(n)) for f in Path(env['DM_OODLE_CACHE']).glob('*.idx') for h, n, _ in (ln.split('\t') for ln in f.read_text().splitlines())}
            with open(Path(env['DM_OODLE_RECORD']) / 'want.1', 'ab') as f:
                for c, n in self.streams:
                    if ao.stream_key(c, n) not in have: f.write(struct.pack('<II', len(c), n) + c)
            return 0
        def phone(recs): self.jobs.append(len(recs)); return [zlib.decompress(c[1:]) for c, _ in recs]
        for p in (mock.patch.object(ba.bi, 'run', side_effect=run), mock.patch.object(ba.bi, 'PROG', mock.MagicMock()), mock.patch.object(ba, 'say'),
                  mock.patch.object(ba, 'oodle_phone', return_value=phone), mock.patch.object(ba, 'phone', lambda *a: contextlib.nullcontext())):
            p.start(); self.addCleanup(p.stop)

    def decode(self, serial: str | None = 'SERIAL'):
        return ba.oodle_decode([self.game / 'RomFS'], [self.game / 'ExeFS/main'], [], self.game, 'v0', self.nsp, self.work / 'patched_android_v0', self.work, self.logs, {},
                               SimpleNamespace(id=GID), serial, None)

    def test_streams_decoded_on_the_phone_are_kept(self):
        self.assertEqual(self.decode(), self.game / 'oodle_cache')
        self.assertEqual((len(self.records), self.jobs, ba.oodle_phone.call_count), (2, [3], 1))   # a run with the phone, then one that lists nothing new
        self.assertEqual(len(self.ao.Cache(self.game / 'oodle_cache', hashlib.sha256((self.game / 'ExeFS/main').read_bytes()).hexdigest())), 3)
        self.decode(serial=None)   # the same files again, even with no phone (a game app): no record run, no job
        self.assertEqual((len(self.records), self.jobs, ba.oodle_phone.call_count), (2, [3], 1))

    def test_no_phone_says_to_connect_one(self):
        with self.assertRaises(ba.BuildError) as e: self.decode(serial=None)
        self.assertIn('connect one', str(e.exception)); self.assertEqual(ba.oodle_phone.call_count, 0)

    def test_ue_decode_still_hands_the_phone_to_uepak(self):   # its phone setup is oodle_phone now, which oodle_decode shares
        got = {}
        def decode(uepak, rom, main, jd, out, phone): got['phone'] = phone; Path(out).mkdir(parents=True); return [{'name': 'g', 'shaders': 2, 'compression': ''}], 0
        ba.oodle_phone.return_value = mock.Mock(jobs=1)
        with mock.patch.object(ba.bi, 'ue_stamp', return_value='stamp'), mock.patch.object(self.ao, 'decode', side_effect=decode), \
             mock.patch.object(ba.bi.rfs, 'source', side_effect=lambda p: p / 'RomFS'):
            ba.ue_decode({'v0': self.game}, 'v0', self.nsp, self.work / 'patched_android_v0', self.work, self.logs, {}, SimpleNamespace(id=GID), 'SERIAL', 'SDK', self.game)
        self.assertIs(got['phone'], ba.oodle_phone.return_value); self.assertEqual(ba.oodle_phone.call_args.args[:2], ('SERIAL', 'SDK'))
        self.assertEqual((self.game / 'ue_shaders/stamp').read_text(), 'stamp')

    def test_a_mac_build_of_the_same_main_decodes_on_the_mac(self):
        mac = self.tmp / 'game' / f'{GID}_build'; (mac / 'tools').mkdir(parents=True); (mac / 'tools/dmhost').write_bytes(b'host'); (mac / 'patched_v0').mkdir()
        fx = mac / 'patched_v0/main.fixups.tsv'; fx.write_text('# PATCH_OFF\t-0x2000000\n# BUILD_ID\t000102030405060708090a0b0c0d0e0f\n')
        def found(env=None, plat=('darwin', 'arm64')):
            with mock.patch.object(ba.sys, 'platform', plat[0]), mock.patch.object(ba.platform, 'machine', return_value=plat[1]):
                return ba.mac_decoder(self.nsp, self.work, SimpleNamespace(id=GID), 'v0', self.game, env or {})
        self.assertEqual(found(), {'DM_OODLE_HOST': str(mac / 'tools/dmhost'), 'DM_OODLE_MODULES': str(mac / 'patched_v0')})
        self.assertIsNone(found(plat=('win32', 'AMD64'))); self.assertIsNone(found(plat=('darwin', 'x86_64')))
        with mock.patch.dict(ba.os.environ, {'DM_UE_DECODE': 'phone'}): self.assertIsNone(found())
        self.assertEqual(found({'DM_OODLE_HOST': 'h', 'DM_OODLE_MODULES': 'm'}), {'DM_OODLE_HOST': 'h', 'DM_OODLE_MODULES': 'm'})   # set by hand: anywhere
        fx.write_text('# BUILD_ID\tffffffffffffffffffffffffffffffff\n'); self.assertIsNone(found())   # another build's modules


if __name__ == '__main__':
    unittest.main()
