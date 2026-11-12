#!/usr/bin/env python3
# dm/android/tools/bench_sweep.py: the save sweeps of scripts/bench_android.py (--sweep, --routes, --compare), with mocked runs: which routes a sweep picks, a downloaded
# save read from its archive without writing beside it, red-line kinds, one row per phone and route, and the regressions against an earlier sweep
import shutil, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import bench_sweep as bs   # noqa: E402  # pyright: ignore[reportMissingImports]


def run(route, serial='pad3', run=1, fps=60.0, exit=None, reds=None, game='0100000000010000'):   # a run's result as bench_android.py's run_one returns it, cut down
    return {'serial': serial, 'game': game, 'route': route, 'run': run, 'ready_s': 20.5, 'first_frame_s': 1.4, 'fps': fps, 'frame_p50': 16.7, 'frame_p95': 19.0,
            'gpu_p50': 8.0, 'pss_mb': 1550, 'exit': exit, 'died_at_s': None, 'red_kinds': reds or {}, 'shot': f'/out/{route}/shot_end.png', 'dir': f'/out/{route}'}


class PickRoutes(unittest.TestCase):
    ROUTES = [{'name': n} for n in ('boot', 'opening', 'dl_metro', 'dl_sand', 'make_save', 'dl_bowsers')]

    def test_a_sweep_takes_every_dl_route_in_the_files_order(self):
        self.assertEqual([r['name'] for r in bs.pick_routes(self.ROUTES, 'dl_*')], ['dl_metro', 'dl_sand', 'dl_bowsers'])

    def test_several_patterns(self):
        self.assertEqual([r['name'] for r in bs.pick_routes(self.ROUTES, 'boot, dl_s*')], ['boot', 'dl_sand'])
        self.assertEqual(bs.pick_routes(self.ROUTES, 'nothing_*'), [])


class SaveDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.game = self.tmp / 'Game'; self.nsp = self.game / 'android'; self.nsp.mkdir(parents=True)
        self.saves = self.game / 'saves'; self.cache = self.tmp / 'out' / 'saves'

    def tearDown(self): shutil.rmtree(self.tmp, ignore_errors=True)

    def zip(self, name, members):
        d = self.saves / name; d.mkdir(parents=True, exist_ok=True); z = d / f'{name}.zip'
        with zipfile.ZipFile(z, 'w') as f:
            for m, data in members.items(): f.writestr(m, data)
        return z

    def test_a_save_folder_is_used_as_it_is(self):
        (self.saves / 'eterna').mkdir(parents=True); (self.saves / 'eterna' / 'main').write_bytes(b'x')
        self.assertEqual(bs.save_dir('saves/eterna', self.nsp, self.cache), self.saves / 'eterna')   # found in the NSP folder's parent, the game's folder
        self.assertFalse(self.cache.exists())
        with self.assertRaises(ValueError): bs.save_dir('saves/eterna//inside', self.nsp, self.cache)

    def test_the_folder_inside_an_archive(self):   # a JKSV-style archive: the save's files three folders down
        z = self.zip('dl-final-day', {'JKSV/Game/Vip - 2023.01.22/data0006.bin': b'save', 'JKSV/Game/Vip - 2023.01.22/P4G.ini': b'ini'})
        d = bs.save_dir('saves/dl-final-day/dl-final-day.zip//JKSV/Game/Vip - 2023.01.22', self.nsp, self.cache)
        self.assertEqual(sorted(p.name for p in d.iterdir()), ['P4G.ini', 'data0006.bin'])
        self.assertTrue(d.is_relative_to(self.cache)); self.assertEqual(sorted(p.name for p in z.parent.iterdir()), ['dl-final-day.zip'])   # nothing written beside it

    def test_an_archive_whose_root_is_the_save(self):
        self.zip('dl-postgame', {'main': b'pk'})
        self.assertEqual([p.name for p in bs.save_dir('saves/dl-postgame/dl-postgame.zip', self.nsp, self.cache).iterdir() if p.name != '.unpacked'], ['main'])

    def test_unpacked_once(self):
        self.zip('dl-a', {'0/game_data.sav': b'1'})
        d = bs.save_dir('saves/dl-a/dl-a.zip//0', self.nsp, self.cache); (d / 'game_data.sav').write_bytes(b'kept')
        self.assertEqual((bs.save_dir('saves/dl-a/dl-a.zip//0', self.nsp, self.cache) / 'game_data.sav').read_bytes(), b'kept')

    def test_other_archives_through_tar(self):   # rar and 7z go through bsdtar; a plain tar takes the same path
        if not (shutil.which('bsdtar') or shutil.which('tar')): self.skipTest('no tar')
        src = self.tmp / 'src' / 'slot_00'; src.mkdir(parents=True); (src / 'progress.sav').write_bytes(b'p')
        (self.saves / 'dl-t').mkdir(parents=True)
        with tarfile.open(self.saves / 'dl-t' / 'dl-t.tar', 'w') as t: t.add(src, arcname='slot_00')
        self.assertEqual([p.name for p in bs.save_dir('saves/dl-t/dl-t.tar//slot_00', self.nsp, self.cache).iterdir()], ['progress.sav'])

    def test_refusals(self):
        self.zip('dl-bad', {'../escape': b'x'})
        with self.assertRaises(ValueError): bs.save_dir('saves/dl-bad/dl-bad.zip', self.nsp, self.cache)
        self.zip('dl-ok', {'a/b': b'x'})
        with self.assertRaises(FileNotFoundError): bs.save_dir('saves/dl-ok/dl-ok.zip//nowhere', self.nsp, self.cache)
        with self.assertRaises(FileNotFoundError): bs.save_dir('saves/missing', self.nsp, self.cache)
        (self.saves / 'dl-txt').mkdir(parents=True); (self.saves / 'dl-txt' / 'notes.txt').write_text('x')
        with self.assertRaises(ValueError): bs.save_dir('saves/dl-txt/notes.txt', self.nsp, self.cache)


class RedKinds(unittest.TestCase):
    def test_numbers_and_addresses_made_alike(self):
        log = ('[dm] [RED] [vk] texture ser=6870 2560x1440 format 43, made without storage use\n[dm] [RED] [vk] texture ser=7001 1920x1080 format 43, made without storage use\n'
               '[dm] fs open [1.2s] content:/x\n[dm] [RED] [vk] storage buffer of shader 3a26262eee1427c9 (c255 +0) is not a bound buffer\n')
        k = bs.red_kinds(log)
        self.assertEqual(sorted(k.values()), [1, 2]); self.assertEqual(len(k), 2)
        self.assertTrue(any('shader N' in x for x in k))
        self.assertEqual(bs.red_kinds('[dm] no reds here\n'), {})


class SummaryAndCompare(unittest.TestCase):
    def test_one_row_per_phone_and_route_from_its_last_run(self):
        rows = bs.summarize([run('dl_metro', run=0, fps=40.0), run('dl_metro', run=1, fps=59.0), run('dl_sand'), run('dl_metro', serial='pixel', run=0, fps=55.0)])
        got = {(r['serial'], r['route']): r['fps'] for r in rows}
        self.assertEqual(got, {('pad3', 'dl_metro'): 59.0, ('pad3', 'dl_sand'): 60.0, ('pixel', 'dl_metro'): 55.0})   # a warm-up only when it's all there is

    def test_regressions(self):
        old = bs.summarize([run('dl_metro', fps=60.0), run('dl_sand', fps=60.0, reds={'a': 1}), run('dl_bowsers', fps=30.0), run('dl_gone')])
        new = bs.summarize([run('dl_metro', fps=56.9), run('dl_sand', fps=57.1, reds={'a': 3, 'b': 1}), run('dl_bowsers', fps=30.0, exit='crash: SIGSEGV'),
                            run('dl_new')])
        flags = bs.compare(new, old)
        self.assertEqual(flags[('pad3', '0100000000010000', 'dl_metro')], ['fps 60.0 → 56.9'])   # 5 % or more under
        self.assertEqual(flags[('pad3', '0100000000010000', 'dl_sand')], ['1 new red kind'])   # 57.1 is within 5 %; more of a known kind is no flag
        self.assertEqual(flags[('pad3', '0100000000010000', 'dl_bowsers')], ['ended: crash: SIGSEGV'])
        self.assertEqual(flags[('pad3', '0100000000010000', 'dl_new')], ['new route'])
        self.assertEqual(sorted(k[2] for k in bs.regressions(flags)), ['dl_bowsers', 'dl_metro', 'dl_sand'])
        self.assertEqual(bs.compare(new, new)[('pad3', '0100000000010000', 'dl_bowsers')], [])   # a crash the earlier sweep had too isn't new

    def test_written_and_read_back(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            old = bs.summarize([run('dl_metro', fps=60.0), run('dl_metro', serial='pixel', fps=60.0)])
            bs.write(tmp, old, {'pad3': 'OnePlus Pad 3'})
            self.assertEqual(bs.load(tmp), old); self.assertEqual(bs.load(tmp / 'sweep.json'), old)
            md = (tmp / 'sweep.md').read_text()
            self.assertIn('### OnePlus Pad 3', md); self.assertIn('### pixel', md); self.assertIn('No earlier sweep', md)
            reg = bs.write(tmp, bs.summarize([run('dl_metro', fps=50.0), run('dl_metro', serial='pixel', fps=60.0)]), {}, old)
            self.assertEqual(list(reg), [('pad3', '0100000000010000', 'dl_metro')]); self.assertIn('1 route(s) flagged', (tmp / 'sweep.md').read_text())
        finally: shutil.rmtree(tmp, ignore_errors=True)

    def test_table_cells(self):   # no ready pattern shows –, not the first frame; a screenshot inside the sweep's folder is given relative to it
        r = run('dl_final_day') | {'ready_s': None, 'shot': '/sweeps/flip/phone/dl_final_day_r1/shot_end.png'}
        md = bs.table([r, run('dl_metro')], {}, None, Path('/sweeps/flip'))
        self.assertIn('| dl_final_day | – | 60.0 |', md); self.assertIn('| phone/dl_final_day_r1/shot_end.png |', md)
        self.assertIn('| /out/dl_metro/shot_end.png |', md)   # outside it: as it is


if __name__ == '__main__':
    unittest.main()
