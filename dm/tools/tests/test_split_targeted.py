"""The targeted shader split: shader_split.py's from_map (DM_SPLIT_FROM_MAP) reads only the RomFS files a shader map names, and build_ipa_from_nsp.py split_shaders tries it
first for a profile that registers the version (targeted, the Android build's), keeps it when its map, facts and pipeline pairs are the profile's, and splits every file when
they differ or the split fails. Real splits of GLSLC outputs in a made-up RomFS (as test_split_appledouble's), and split_shaders with its split run stood in for, as in
test_nsp_incremental. No game files."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/games')); sys.path.insert(0, str(REPO / 'dm/tools')); sys.path.insert(0, str(REPO / 'dm/gfx/tools'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import game, nacp, profile_guess   # noqa: E401, E402
with mock.patch.dict(os.environ, {'DM_GAME': '01007BB017812000'}): import shader_split   # noqa: E402  (it loads a profile when imported; any profile does for from_map)
from test_split_appledouble import shader_file   # noqa: E402
spec = importlib.util.spec_from_file_location('build_ipa_from_nsp', REPO / 'scripts/build_ipa_from_nsp.py')
assert spec is not None and spec.loader is not None
nsp = importlib.util.module_from_spec(spec); spec.loader.exec_module(nsp)
vars(nsp).update(pg=profile_guess, nacp=nacp)   # main sets them
TABLES = ('pkg', 'map.tsv', 'facts.tsv', 'pairs.tsv', 'pso.tsv')


class FromMap(unittest.TestCase):   # which of main's (path, source path) entries the filter keeps
    def keep(self, rows, files):
        with tempfile.TemporaryDirectory() as d:
            mp = Path(d) / 'map.tsv'
            mp.write_text('# header\npackage\tindex\tstage\tdm_ctl_sha16\tsource\n' + ''.join(f'vs_x.bin\t{i}\tvertex\t{i:016x}\t{r}\n' for i, r in enumerate(rows)))
            with mock.patch('builtins.print'): return [r for _, r in shader_split.from_map([('/x/' + r, r) for r in files], str(mp))]

    def test_named_files_their_archives_and_companions(self):
        rows = ['/Effect/a.vsetb.byml.zs#BNSH@0x15000#var0',   # a file
                '/EffectData/EffectPtcl.szs/EffectData.ptcl#BNSH@0x5a25000#var0',   # a member of an archive: the archive is read
                '/Data/Data0.bdt#BND3@0x40#a.shader',   # its index beside it, same name: read too
                '/v327680/Shader/b.bfsha#BNSH@0x0#var1',   # a later version's file, under its tag
                'main#BNSH@0x100#var0', 'main@v327680#GLSLC@0x0']   # main is read anyway
        files = ['Effect/a.vsetb.byml.zs', 'Effect/c.vsetb.byml.zs', 'EffectData/EffectPtcl.szs', 'Data/Data0.bdt', 'Data/Data0.bhd5', 'Data/Data1.bdt',
                 'Shader/b.bfsha', 'v327680/Shader/b.bfsha', 'aoc/1/RomFS/d.bin', 'Effect']
        self.assertEqual(self.keep(rows, files), ['Effect/a.vsetb.byml.zs', 'EffectData/EffectPtcl.szs', 'Data/Data0.bdt', 'Data/Data0.bhd5', 'v327680/Shader/b.bfsha',
                                                  'aoc/1/RomFS/d.bin', 'Effect'])   # DLC is all read; a folder's name in the list is harmless

    def test_a_dot_in_a_folder_is_not_an_extension(self):
        self.assertEqual(self.keep(['/pack.v2/data#X@0'], ['pack.v2/data', 'pack.v2/other', 'pack.idx']), ['pack.v2/data'])


class RealSplit(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.root, True)
        self.env = dict(os.environ, DM_GAME='01007BB017812000', J='2')
        for n in ('DM_GLSLC_CAPTURE', 'DM_UE_SHADERS', 'DM_GAMES_DIR', 'DM_SPLIT_FROM_MAP'): self.env.pop(n, None)

    def version(self, name, files):
        v = self.root / name; (v / 'RomFS').mkdir(parents=True); (v / 'main').write_bytes(b'NSO0' + bytes(0xfc))   # three empty NSO segments
        for rel, data in files.items(): p = v / 'RomFS' / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
        return v

    def split(self, versions, out, mp=None):
        out = self.root / out; out.mkdir()
        env = dict(self.env, **({'DM_SPLIT_FROM_MAP': str(mp)} if mp else {}))
        r = subprocess.run([sys.executable, REPO / 'dm/gfx/tools/shader_split.py', ','.join(str(v / 'RomFS') for v in versions), ','.join(str(v / 'main') for v in versions),
                            *(out / t for t in TABLES)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout, {str(p.relative_to(out)): p.read_bytes() for p in out.rglob('*') if p.is_file()}

    def test_the_named_files_make_the_same_package_and_tables(self):
        one, two, three = (shader_file('glslc', m) for m in (1, 2, 3))
        v0 = self.version('v0', {'a.bin': bytes(100) + one, 'sub/b.dat': two, 'sub/b.idx': b'index', 'c.txt': b'nothing', 'd.bin': one, 'e/f.bin': b'more nothing'})
        v1 = self.version('v1', {'x.bin': three, 'y.bin': b'nothing'})
        out, full = self.split([v0, v1], 'full')
        self.assertIn('shaders: 3 (', out)
        rows = full['map.tsv'].decode()
        self.assertIn('/a.bin#GLSLC@0x64', rows); self.assertIn('/v1/x.bin#GLSLC@0x0', rows); self.assertNotIn('d.bin', rows)   # d.bin's shader first appears in a.bin
        out, only = self.split([v0, v1], 'only', self.root / 'full/map.tsv')
        self.assertIn('files the shader map names: 4 of 8 RomFS files', out)   # a.bin, sub/b.dat and its sub/b.idx, v1/x.bin
        self.assertIn('progress: 4/4', out)
        self.assertEqual(only, full)


class SplitShaders(unittest.TestCase):
    """split_shaders with targeted: the split run is a stand-in writing the four tables, those of a split of the named files when DM_SPLIT_FROM_MAP is set"""
    TID = '0100AAAA00000000'
    PROFILE = {'shader_map.tsv': 'vs_x.bin\t0\tvertex\t00000000000000aa\t/a.bin#GLSLC@0x0\n', 'shader_facts.tsv': '# none\n',
               'shader_pairs.tsv': '00000000000000aa\t00000000000000bb\n', 'pso_pairs.tsv': '# none\n'}
    NAMES = ('shader_map.tsv', 'shader_facts.tsv', 'shader_pairs.tsv', 'pso_pairs.tsv')

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src = self.tmp / 'games' / self.TID; self.src.mkdir(parents=True)
        (self.src / 'game.tsv').write_text('\n'.join([f'title_id\t{self.TID}', f'program_id\t{self.TID}', 'name\tTest Game', 'modules\tmain', f'build\tv0\t1.0.0\tmain={"ab" * 16}',
                                                      'package\tv0', 'shader_versions\tv0']) + '\n')
        for n, t in self.PROFILE.items(): (self.src / n).write_text('# registered\n' + t)
        self.ex = self.tmp / 'extract/v0'; (self.ex / 'ExeFS').mkdir(parents=True); (self.ex / 'ExeFS/main').write_bytes(b'NSO0' + bytes(0x3c) + bytes.fromhex('ab' * 16) + bytes(0x50))
        (self.ex / 'RomFS').mkdir(); (self.ex / 'RomFS/a.bin').write_bytes(b'romfs')
        self.repo = self.tmp / 'repo'
        for f in ('dm/gfx/tools/shader_split.py', 'dm/gfx/tools/dmsh_chain.lock', 'dm/games/game.py', 'dm/ios/tools/ios_metal.py'):
            p = self.repo / f; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('v1')
        self.pkg = self.tmp / 'work/shader/pkg'; self.logs = self.tmp / 'logs'; self.logs.mkdir()
        self.calls, self.targeted_tables, self.full_tables, self.targeted_exit = [], dict(self.PROFILE), dict(self.PROFILE), 0
        self.said = []
        for cm in (mock.patch.dict(os.environ, {'DM_GAMES_DIR': str(self.tmp / 'games')}), mock.patch.object(nsp, 'PROG', mock.Mock()),
                   mock.patch.object(nsp, 'say', self.said.append), mock.patch.object(nsp, 'run', self.split)):
            cm.__enter__(); self.addCleanup(cm.__exit__, None, None, None)

    def split(self, cmd, log, env=None, cwd=None, on_line=None, ok=(), fatal=True):
        env = env or {}; only = 'DM_SPLIT_FROM_MAP' in env; self.calls.append(env.get('DM_SPLIT_FROM_MAP'))
        out = Path(cmd[4]); out.mkdir(parents=True); (out / 'vs_x.bin').write_bytes(b'record')
        for n, t in zip(self.NAMES, cmd[5:]): Path(t).write_text('# split\n' + (self.targeted_tables if only else self.full_tables)[n])
        Path(log).write_text('shaders: 1 (vertex 1)\n')
        if only and self.targeted_exit:
            assert not fatal, 'a failed split of the named files must not end the stage'
            return self.targeted_exit
        return 0

    def go(self, targeted=True, provisional=False, dlc_roms=(), env=None):
        return nsp.split_shaders(sys.executable, self.repo, [self.ex / 'RomFS'], [self.ex / 'ExeFS/main'], self.pkg, env or {}, self.logs, game.Game(self.src),
                                 provisional, None, dlc_roms, None, None, targeted)

    def test_a_matching_split_of_the_named_files_is_kept(self):
        self.targeted_tables['shader_pairs.tsv'] = '# fewer pairs: a file that only repeats shaders is named nowhere\n'
        self.go()
        self.assertEqual(self.calls, [str(self.src / 'shader_map.tsv')])
        self.assertEqual((self.pkg / 'vs_x.bin').read_bytes(), b'record')
        self.assertFalse((self.logs / 'shader_split.from_map.log').exists())

    def test_a_different_map_splits_every_file(self):
        self.targeted_tables['shader_map.tsv'] = '# a companion file the map does not name: a shader missing\n'
        self.go()
        self.assertEqual(self.calls, [str(self.src / 'shader_map.tsv'), None])
        self.assertTrue((self.logs / 'shader_split.from_map.log').is_file())
        self.assertTrue(any('shader_map.tsv that differs' in s and 'splitting every file' in s for s in self.said), self.said)

    def test_a_failed_split_of_the_named_files_splits_every_file(self):
        self.targeted_exit = 1
        self.go()
        self.assertEqual(self.calls, [str(self.src / 'shader_map.tsv'), None])
        self.assertTrue(any('stopped with an error' in s for s in self.said), self.said)

    def test_the_full_split_still_compares_the_pairs(self):   # the pairs are left out only for a split of the named files
        self.full_tables['shader_pairs.tsv'] = '# other pairs\n'
        with self.assertRaisesRegex(nsp.BuildError, 'shader_pairs.tsv'): self.go(targeted=False)
        self.assertEqual(self.calls, [None])

    def test_every_file_without_a_registered_version_or_with_dlc_or_when_switched_off(self):
        cases: list[dict[str, Any]] = [{'targeted': False}, {'dlc_roms': [self.tmp / 'aoc/1.img']}, {'env': {'DM_SPLIT_TARGETED': '0'}}, {'provisional': True}]
        for kw in cases:
            with self.subTest(**{k: str(v) for k, v in kw.items()}):
                self.calls.clear(); shutil.rmtree(self.pkg.parent, ignore_errors=True)
                try: self.go(**kw)
                except nsp.BuildError: pass   # a DLC run compares DLC tables the stand-in does not make: only the calls matter here
                self.assertEqual(self.calls, [None])


if __name__ == '__main__':
    unittest.main()
