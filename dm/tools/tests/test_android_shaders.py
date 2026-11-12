"""The Android packing script's shader stage (scripts/build_android_from_nsp.py build_shaders) around the shader split (build_ipa_from_nsp.py split_shaders, stubbed here):
a registered profile's split error stops the build instead of packing the game without shaders, as a profile derived from a registered one's does (droidplay-core#307), a
provisional profile's still packs without them, and compute kernels a newer reader decodes, or DLC-only shaders, take the shader-only derived profile the iPhone build takes,
whose shader facts the translation then reads (droidplay-core#218)."""
import contextlib
import hashlib
from pathlib import Path
import shutil
import struct
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
        self.ran = []
        def run(cmd, log, env=None):   # spv_build.py: its output folder and its last line
            self.ran.append([str(c) for c in cmd]); (self.work / 'spv').mkdir(exist_ok=True); Path(log).write_text('spv_build: 3 translated\n')
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

    def test_no_versions_no_split(self):
        with mock.patch.object(ba.bi, 'split_shaders') as sp:
            self.assertEqual(ba.build_shaders([], {}, self.work, self.logs, {}, self.registered), (None, self.registered))
        sp.assert_not_called()


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
