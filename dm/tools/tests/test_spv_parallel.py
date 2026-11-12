"""dm/android/tools/spv_android.py's post-pass in several processes (-j, a spawn pool, as Windows has): each shader's files and the lines printed are those of one process,
in key order, over more shaders than one pool job takes; a shader that stops the post-pass stops the run, while one whose translator output is empty or cut short is a
[RED] line. The modules are test_spv_cbsize's and test_spv_posrows', a vertex
shader with transform feedback, one without a position output (a [RED] line) and a fragment shader, assembled with spirv-as. Skipped without spirv-as."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / 'dm/android/tools/spv_android.py'
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import spv_android as sa   # noqa: E402  # pyright: ignore[reportMissingImports]  # dm/android/tools, put on the path above
import test_spv_cbsize, test_spv_posrows   # noqa: E401, E402
from test_spv_cbsize import SPV_AS   # noqa: E402

NO_POSITION = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %out
OpDecorate %out Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%pout = OpTypePointer Output %v4
%out = OpVariable %pout Output
%f0 = OpConstant %f32 0
%o = OpConstantComposite %v4 %f0 %f0 %f0 %f0
%main = OpFunction %void None %fn
%entry = OpLabel
OpStore %out %o
OpReturn
OpFunctionEnd
'''
FRAGMENT = NO_POSITION.replace('OpEntryPoint Vertex %main "main" %out', 'OpEntryPoint Fragment %main "main" %out\nOpExecutionMode %main OriginUpperLeft')


@unittest.skipIf(SPV_AS is None, 'no spirv-as')
class Parallel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        def asm(text, subst):
            for k, v in subst.items(): text = text.replace(k, v)
            p = cls.tmp / 'm.spvasm'; p.write_text(text)
            subprocess.run([str(SPV_AS), '--target-env', 'vulkan1.1', str(p), '-o', str(cls.tmp / 'm.spv')], check=True)
            return (cls.tmp / 'm.spv').read_bytes()
        cbsize = asm(test_spv_cbsize.MODULE, {'%USE%': ''})
        posrows = asm(test_spv_posrows.MODULE, {'%IFACE%': '', '%IDEC%': '', '%IVAR%': ''})
        cls.kinds = [   # (module, res.json without its key)
            (cbsize, {'stage': 'vs', 'cbufs': [{'binding': 1, 'slot': 4}, {'binding': 2, 'slot': 25}]}),
            (posrows, {'stage': 'vs', 'cbufs': [{'binding': 14, 'slot': 3}, {'binding': 10, 'slot': 5}]}),
            (cbsize, {'stage': 'vs', 'cbufs': [{'binding': 1, 'slot': 4}], 'tf': [[[[0, 4]], 16], [], [], []]}),   # output 0, xyzw, in feedback buffer 0
            (asm(NO_POSITION, {}), {'stage': 'vs'}),
            (asm(FRAGMENT, {}), {'stage': 'ps'}),
        ]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def folder(self, name, n, broken=None, cut=()):   # n shaders, the kinds in turn, so [RED] lines come from keys throughout the list; broken: a res.json the post-pass trips on;
        d = self.tmp / name; d.mkdir()                 # cut: shaders whose .spv is empty or cut short
        for i in range(n):
            k = f'{i * 0x9e3779b97f4a7c15 % (1 << 64):016x}'   # keys out of order of i: main sorts them
            data, res = self.kinds[i % len(self.kinds)]
            (d / f'{k}.spv').write_bytes((data[:len(data) // 8 * 4] if cut.index(i) else b'') if i in cut else data)   # the first cut empty, the next ones half their words
            (d / f'{k}.res.json').write_text(json.dumps({'key': k, **res, **({'cbufs': 7} if i == broken else {})}))
        return d

    def run_post(self, src, name, j):
        dst = self.tmp / name
        r = subprocess.run([sys.executable, str(SCRIPT), '-j', str(j), str(src), str(dst)], capture_output=True, text=True)
        return r, dst

    def test_several_processes_make_what_one_makes(self):
        n = 3 * sa.CHUNK + 7   # four pool jobs, the last one short
        src = self.folder('src', n)
        one, d1 = self.run_post(src, 'one', 1)
        many, d3 = self.run_post(src, 'many', 3)
        self.assertEqual(one.returncode, 0, one.stderr); self.assertEqual(many.returncode, 0, many.stderr)
        files = sorted(p.name for p in d1.iterdir())
        self.assertEqual(files, sorted(p.name for p in d3.iterdir()))
        for f in files: self.assertEqual((d1 / f).read_bytes(), (d3 / f).read_bytes(), f)
        self.assertEqual(one.stdout, many.stdout)   # the [RED] lines in key order, and the same summary
        red = [ln.split(':')[0][6:] for ln in many.stdout.splitlines() if ln.startswith('[RED]')]
        self.assertEqual(len(red), len(range(3, n, len(self.kinds))))   # the shaders without a position output
        self.assertEqual(red, sorted(red))
        vs = sum(1 for i in range(n) if i % len(self.kinds) < 4)
        self.assertIn(f'spv_android: {n} shaders, {vs - len(red)} depth variants, {len(red)} without one;', many.stdout)
        self.assertEqual(sum(1 for f in files if f.endswith('.tf.spv')), len(range(2, n, len(self.kinds))))

    def test_a_shader_that_stops_the_post_pass_stops_the_run(self):
        src = self.folder('bad', 3 * sa.CHUNK, broken=sa.CHUNK + 1)
        r, _ = self.run_post(src, 'bad_out', 3)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn('TypeError', r.stderr)
        self.assertIn(f'shader {(sa.CHUNK + 1) * 0x9e3779b97f4a7c15 % (1 << 64):016x}', r.stderr)   # which one, though the processes take them out of order

    def test_empty_or_cut_short_outputs_are_lines_not_a_stop(self):   # what the translator leaves when a write fails, as on a full disk (droidplay-core#307's IndexError)
        n, cut = 3 * sa.CHUNK, (2, sa.CHUNK + 4)
        src = self.folder('cut', n, cut=cut)
        r, dst = self.run_post(src, 'cut_out', 3)
        self.assertEqual(r.returncode, 0, r.stderr)
        keys = [f'{i * 0x9e3779b97f4a7c15 % (1 << 64):016x}' for i in cut]
        for k, why in zip(keys, ('.spv empty (0 bytes)', '.spv cut short')):
            self.assertIn(f"[RED] {k}: the translator's output can't be read: {why}", r.stdout)
            self.assertFalse((dst / f'{k}.res.json').exists())
        self.assertEqual(len(list(dst.glob('*.res.json'))), n - len(cut))
        self.assertIn(f'spv_android: {n} shaders,', r.stdout)

    def test_few_shaders_take_no_pool(self):   # one job's worth or less: no processes started for it
        with mock.patch.object(sa.cf, 'ProcessPoolExecutor', side_effect=AssertionError('a pool for one job')):
            src = self.folder('few', sa.CHUNK)
            with mock.patch.object(sys, 'argv', ['spv_android.py', '-j', '4', str(src), str(self.tmp / 'few_out')]), mock.patch('builtins.print'):
                sa.main()
        self.assertEqual(len(list((self.tmp / 'few_out').glob('*.res.json'))), sa.CHUNK)


class Jobs(unittest.TestCase):
    def test_windows_stays_within_the_pools_limit(self):   # spv_build.py passes -j os.cpu_count(), which can pass 61 on a big PC
        with mock.patch.object(sa.sys, 'platform', 'win32'): self.assertEqual(sa.pool_size(128, 100_000), 61)
        with mock.patch.object(sa.sys, 'platform', 'darwin'): self.assertEqual(sa.pool_size(128, 100_000), 128)

    def test_no_more_processes_than_jobs(self):
        self.assertEqual(sa.pool_size(18, 2 * sa.CHUNK + 1), 3)
        self.assertEqual(sa.pool_size(18, sa.CHUNK), 1)
        self.assertEqual(sa.pool_size(1, 100_000), 1)
        self.assertEqual(sa.pool_size(0, 100_000), 1)

    def test_an_unknown_cpu_count_still_runs(self):
        with mock.patch.object(sa.os, 'process_cpu_count', lambda: None, create=True), mock.patch.object(sa.os, 'cpu_count', lambda: None):
            self.assertEqual(sa.jobs_default(), 4)


if __name__ == '__main__':
    unittest.main()
