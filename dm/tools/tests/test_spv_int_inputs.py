"""dm/android/tools/spv_build.py int_input_jobs, the second pass for vertex shaders, in several processes (a spawn pool, as Windows has): the shaders to translate again
and the inputs added to their jobs are those of one process, in key order, over more shaders than one pool job takes. Translated output stands in as test_spv_cbsize's
module (its input read only through a bit cast to an integer: int_inputs gives it uint) and test_spv_posrows' (read as a float: nothing to add), assembled with spirv-as.
An empty or cut-short output (a write that failed) adds nothing and doesn't stop the pass. Skipped without spirv-as."""
import copy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import spv_build as sb   # noqa: E402  # pyright: ignore[reportMissingImports]  # dm/android/tools, put on the path above
import test_spv_cbsize, test_spv_posrows   # noqa: E401, E402
from test_spv_cbsize import SPV_AS   # noqa: E402


@unittest.skipIf(SPV_AS is None, 'no spirv-as')
class IntInputJobs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        def asm(text, subst):
            for k, v in subst.items(): text = text.replace(k, v)
            p = cls.tmp / 'm.spvasm'; p.write_text(text)
            subprocess.run([str(SPV_AS), '--target-env', 'vulkan1.1', str(p), '-o', str(cls.tmp / 'm.spv')], check=True)
            return (cls.tmp / 'm.spv').read_bytes()
        integer = asm(test_spv_cbsize.MODULE, {'%USE%': ''})
        floats = asm(test_spv_posrows.MODULE, {'%IFACE%': '', '%IDEC%': '', '%IVAR%': ''})
        cls.tout = cls.tmp / 'out'; cls.tout.mkdir(); cls.jobs = {}
        for i in range(3 * sb.CHUNK + 5):   # four pool jobs, the last one short
            k = f'{i * 0x9e3779b97f4a7c15 % (1 << 64):016x}'
            kind = i % 5   # 0, 1: integer input; 2: float input; 3: integer input its facts already declare; 4: a pixel shader
            if kind != 4 or i % 2: (cls.tout / f'{k}.spv').write_bytes(floats if kind == 2 else integer)   # some pixel shaders have no output at all
            cls.jobs[k] = {'key': k, 'stage': 'ps' if kind == 4 else 'vs', 'attr': {'0': 'sint'} if kind == 3 else {}}
        cls.keys = sorted(cls.jobs)
        (cls.tout / f'{cls.keys[0]}.spv').unlink()   # a vertex shader the translator failed on: no output, nothing to read

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def run_pass(self, j):
        jobs = copy.deepcopy(self.jobs)
        return sb.int_input_jobs(self.keys, jobs, self.tout, j), jobs

    def test_several_processes_choose_what_one_chooses(self):
        one, jobs1 = self.run_pass(1)
        many, jobs3 = self.run_pass(3)
        self.assertEqual(one, many)
        self.assertEqual(jobs1, jobs3)
        want = [k for k in self.keys if self.jobs[k]['stage'] == 'vs' and not self.jobs[k]['attr'] and (self.tout / f'{k}.spv').exists()
                and sb.int_inputs_of(self.tout / f'{k}.spv')]
        self.assertEqual(many, want)   # the integer-input shaders, in key order: not the float one, not the one whose facts say so, not the one without output
        self.assertTrue(many and all(jobs3[k]['attr'] == {'0': 'uint'} for k in many))
        self.assertTrue(all(jobs3[k]['attr'] == {'0': 'sint'} for k in self.keys if self.jobs[k]['attr']))   # facts are kept

    def test_one_jobs_worth_takes_no_pool(self):
        with mock.patch.object(sb.cf, 'ProcessPoolExecutor', side_effect=AssertionError('a pool for one job')):
            jobs = copy.deepcopy(self.jobs)
            sb.int_input_jobs(self.keys[:sb.CHUNK], jobs, self.tout, 8)

    def test_a_shader_that_cannot_be_read_stops_the_pass(self):
        bad = self.tmp / 'bad'; shutil.copytree(self.tout, bad)
        k = next(k for k in self.keys[sb.CHUNK:] if self.jobs[k]['stage'] == 'vs' and (bad / f'{k}.spv').exists())
        (bad / f'{k}.spv').unlink(); (bad / f'{k}.spv').mkdir()   # a folder in its place: reading it fails
        with self.assertRaises(OSError):
            sb.int_input_jobs(self.keys, copy.deepcopy(self.jobs), bad, 3)

    def test_an_empty_or_cut_short_output_is_left_to_the_post_pass(self):   # what a write that failed leaves (a full disk): no inputs found, and the post-pass's [RED] line
        cut = self.tmp / 'cut'; shutil.copytree(self.tout, cut)
        ks = [k for k in self.keys[sb.CHUNK:] if self.jobs[k]['stage'] == 'vs' and (cut / f'{k}.spv').exists()][:2]
        (cut / f'{ks[0]}.spv').write_bytes(b''); (cut / f'{ks[1]}.spv').write_bytes((cut / f'{ks[1]}.spv').read_bytes()[:40])
        again = sb.int_input_jobs(self.keys, copy.deepcopy(self.jobs), cut, 3)
        self.assertFalse(set(ks) & set(again))
        self.assertEqual(again, [k for k in self.run_pass(3)[0] if k not in ks])


if __name__ == '__main__':
    unittest.main()
