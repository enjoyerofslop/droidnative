"""The Android packing script's shader stage (scripts/build_android_from_nsp.py build_shaders) around the shader split (build_ipa_from_nsp.py split_shaders, stubbed here):
a registered profile's split error stops the build instead of packing the game without shaders, a provisional profile's still packs without them, and compute kernels a newer
reader decodes, or DLC-only shaders, take the shader-only derived profile the iPhone build takes, whose shader facts the translation then reads (droidplay-core#218)."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

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

    def build(self, g, split, derive=None):
        with mock.patch.object(ba.bi, 'split_shaders', side_effect=split) as sp:
            r = ba.build_shaders(['v65536'], {'v65536': self.tmp / 'v65536'}, self.work, self.logs, {}, g, (), derive)
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


if __name__ == '__main__':
    unittest.main()
