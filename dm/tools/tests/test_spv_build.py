"""dm/android/tools/spv_build.py's run around the translator, over a package of synthetic pixel shader records, with a stand-in for dmsh_xlate (it writes each job's
.spv and .res.json, or what a test asks for); spv_android.py's post-pass runs as it does in a build, on a minimal fragment shader. Checked: the temporary folder (the code
areas, the job lists and the translator's output) is made under WORK, the build's <id>_build/tmp, and removed however the run ends, a full disk included
(droidplay-core#307: three failed Pokémon Pokopia runs each left tens of GB in the system's temp folder); a full disk, in the translator's lines or in this script's own
writes, stops the run with a plain line before the post-pass, which stopped at the first empty .spv; a run the drives can't hold stops before it translates anything; and
an empty or cut-short output is a [RED] line, not a stop, the translator's failures come before the post-pass, and a shader's res.json is written last and whole, so one
cut short is translated again; a run that had shaders to translate and translated none of them stops, unless the translator said why for each and earlier runs translated
the game's others. No game files, no translator, no spirv-as."""
import contextlib
import errno
import io
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
import time
from types import SimpleNamespace
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import spv_android as sa   # noqa: E402  # pyright: ignore[reportMissingImports]  # dm/android/tools, put on the path above
import spv_build as sb   # noqa: E402  # pyright: ignore[reportMissingImports]


def words(s):   # a SPIR-V literal string
    b = s.encode() + b'\0'; b += bytes(-len(b) % 4)
    return list(struct.unpack(f'<{len(b) // 4}I', b))


# void main() {} as a fragment shader: OpCapability Shader, OpMemoryModel Logical GLSL450, OpEntryPoint Fragment %3 "main", OpExecutionMode %3 OriginUpperLeft,
# %1 void, %2 function type, the function %3 with its label %4, OpReturn, OpFunctionEnd
FRAGMENT = sa.emit([0x07230203, 0x00010000, 0, 5, 0], [[17, 1], [14, 0, 1], [15, 4, 3] + words('main'), [16, 3, 7], [19, 1], [33, 2, 1], [54, 1, 3, 0, 2], [248, 4], [253], [56]])


def record(i):   # a pixel shader record as shader_split.py packs it: the header (+0x28 control length, +0x2c code length), the code area with its 0x30 header, the control section
    code = bytes(0x30) + struct.pack('<I', i) * 8
    ctl = bytearray(0x880); ctl[:4] = sb.CTL_MAGIC   # c1 at +0x700..+0x704: none
    return b'BTCDBTCD' + bytes(0x20) + struct.pack('<2I', len(ctl), len(code)) + bytes(8) + code + bytes(ctl)


class Harness(unittest.TestCase):
    N = 5   # shaders in the package

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pkg, self.out, self.work, self.sysdir = self.tmp / 'pkg', self.tmp / 'spv', self.tmp / 'work', self.tmp / 'system_temp'
        self.pkg.mkdir(); self.sysdir.mkdir(); (self.pkg / 'ps_0.bin').write_bytes(b''.join(record(i) for i in range(self.N)))
        self.touts, self.lines, self.before_post = [], '', ''
        self.post_fails = False
        real = subprocess.run
        def run(cmd, **k):
            if cmd[0] == sys.executable:   # the post-pass, run as spv_build runs it, its output kept for the test
                self.before_post = sys.stdout.getvalue() if isinstance(sys.stdout, io.StringIO) else ''   # what spv_build had printed by then
                if self.post_fails: raise subprocess.CalledProcessError(1, cmd)
                r = real(cmd, capture_output=True, text=True); self.lines += r.stdout + r.stderr
                if k.get('check') and r.returncode: raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
                return r
            jp, tout = Path(cmd[-2]), Path(cmd[-1]); self.touts.append(tout)
            return self.process(cmd, json.loads(jp.read_text(encoding='utf-8')), tout)
        for p in (mock.patch.object(sb.subprocess, 'run', side_effect=run), mock.patch.object(tempfile, 'tempdir', str(self.sysdir))):   # the system's temp folder, watched too
            p.start(); self.addCleanup(p.stop)

    def process(self, cmd, jobs, tout):   # one dmsh_xlate process over its job list: → what it printed, and its exit code
        err = ''.join(self.translate(j, tout) for j in jobs)
        return subprocess.CompletedProcess(cmd, 0, f'translated: {self.N}\n', err)

    def translate(self, job, tout):   # dmsh_xlate's output for one job: its .spv, then its .res.json; → its stderr lines
        k = job['key']
        (tout / f'{k}.spv').write_bytes(FRAGMENT)
        (tout / f'{k}.res.json').write_text(json.dumps({'key': k, 'stage': job['stage'], 'cbufs': []}, indent=2), encoding='utf-8')
        return ''

    def build(self, env=None):   # spv_build.py <package> <out> with WORK as env gives it (the build's), → its output
        env = {'WORK': str(self.work)} if env is None else env
        argv = ['spv_build.py', str(self.pkg), str(self.out), '--xlate', 'dmsh_xlate', '-j', '2']
        buf = io.StringIO()
        try:
            with mock.patch.object(sys, 'argv', argv), mock.patch.dict(os.environ, env), contextlib.redirect_stdout(buf):
                for name in ('WORK', 'DM_SPV_SPACE_CHECK'):
                    if name not in env: os.environ.pop(name, None)
                sb.main()
        finally: self.text = buf.getvalue()
        return self.text

    def left(self):   # temporary folders under WORK or in the system's temp folder after the run
        return sorted(str(p) for d in (self.work, self.sysdir) if d.exists() for p in d.glob('spv_*'))

    def keys(self): return sorted(sb.key_of(*reversed(sb.split(record(i)))) for i in range(self.N))

    def old_output(self, k, chain, size=100):   # a shader an earlier run translated
        self.out.mkdir(exist_ok=True); (self.out / f'{k}.spv').write_bytes(bytes(size)); (self.out / f'{k}.res.json').write_text(json.dumps({'key': k, 'android': chain}))


class TemporaryFolder(Harness):
    def test_a_run_works_under_work_and_leaves_nothing_there(self):
        text = self.build()
        self.assertIn(f'spv_build: {self.N} translated', text)
        self.assertIn(f'spv_android: {self.N} shaders', self.lines); self.assertEqual(len(list(self.out.glob('*.res.json'))), self.N)
        self.assertTrue(self.touts and all(t.parent.parent == self.work for t in self.touts), self.touts)   # WORK/spv_*/out, on the game's drive
        self.assertEqual(self.left(), [])

    def test_a_failed_post_pass_leaves_nothing(self):   # the post-pass subprocess stops (check=True): spv_build stops before its old rmtree
        self.post_fails = True
        with self.assertRaises(subprocess.CalledProcessError): self.build()
        self.assertTrue(self.touts)
        self.assertEqual(self.left(), [])

    def test_a_full_disk_while_the_code_areas_are_written_leaves_nothing(self):
        real, n = Path.write_bytes, [0]
        def write(p, data):   # the third code area finds the disk full
            if p.parent.name.startswith('spv_') and p.suffix == '.bin':
                n[0] += 1
                if n[0] == 3: raise OSError(errno.ENOSPC, 'No space left on device', str(p))
            return real(p, data)
        with mock.patch.object(Path, 'write_bytes', write), self.assertRaises(SystemExit) as e: self.build()
        self.assertEqual(e.exception.code, 1)
        self.assertRegex(self.text, r'\[RED\] spv_build: the disk is full: .*\.bin could not be written\. The drive with .* has [\d.]+ GB free')
        self.assertEqual(self.touts, [])   # nothing was translated
        self.assertEqual(self.left(), [])

    def test_a_folder_a_killed_run_left_goes_at_the_next_run(self):   # a closed window or a killed process runs no finally
        old = self.work / 'spv_k1ll3d'; (old / 'out').mkdir(parents=True); (old / 'a.bin').write_bytes(b'x' * 100)
        keep = self.work / 'ue_job_v0'; keep.mkdir()   # the build's other temporary folders stay
        self.build()
        self.assertEqual(self.left(), []); self.assertTrue(keep.is_dir())

    def test_without_work_the_system_temp_folder(self):   # spv_build.py run by hand
        self.build(env={})
        self.assertTrue(self.touts and all(t.parent.parent == self.sysdir for t in self.touts), self.touts)
        self.assertEqual(list(self.sysdir.iterdir()), [])
        self.assertFalse(self.work.exists())


class DiskFull(Harness):
    """The translator writes each output with File.WriteAllBytes and catches each shader's exception: on a full disk it leaves an empty or cut-short .spv and prints
    `[RED] <key>: IOException: …`, then goes on to the next shader"""
    def setUp(self):
        super().setUp(); self.good, self.message = 2, "IOException: No space left on device : '{path}'"

    def translate(self, job, tout):
        if self.good: self.good -= 1; return super().translate(job, tout)
        p = tout / f"{job['key']}.spv"
        if 'IOException' in self.message: p.write_bytes(b'')   # created, then the write failed; a shader it can't translate gets no file
        return f"[RED] {job['key']}: {self.message.format(path=p)}\n"

    def test_the_translator_finding_the_disk_full_stops_the_run_before_the_post_pass(self):
        for name, message in (('POSIX', "IOException: No space left on device : '{path}'"), ('Windows', "IOException: There is not enough space on the disk. : '{path}'")):
            with self.subTest(message=name):
                self.good, self.message, self.lines = 2, message, ''
                with self.assertRaises(SystemExit) as e: self.build()
                self.assertEqual(e.exception.code, 1)
                self.assertRegex(self.text, r"\[RED\] spv_build: the disk is full: the translator could not write 3 shaders' output in its first pass \(\w{16}: IOException: ")
                self.assertIn('Nothing more is translated', self.text)
                self.assertEqual(self.lines, ''); self.assertFalse(self.out.exists() and any(self.out.iterdir()))   # no post-pass: it stopped at the first empty .spv
                self.assertEqual(self.left(), [])

    def test_a_shader_the_translator_cannot_handle_is_no_stop(self):
        self.good, self.message = 2, 'NotImplementedException: LDC with a bindless bank or an address mode'
        text = self.build()
        self.assertEqual(len(list(self.out.glob('*.res.json'))), 2)
        self.assertEqual(text.count('LDC with a bindless bank'), 3); self.assertNotIn('disk is full', text)

    def test_the_line_says_what_build_android_from_nsp_looks_for(self):   # its DISK_FULL, the same pattern: the player's message adds what to free
        self.assertTrue(sb.DISK_FULL.search('[RED] spv_build: the disk is full: a file could not be written'))
        self.assertTrue(sb.DISK_FULL.search('OSError: [Errno 28] No space left on device'))
        self.assertFalse(sb.DISK_FULL.search('[RED] 0123456789abcdef: IndexOutOfRangeException: Index was outside the bounds of the array.'))


class FreeSpace(Harness):   # spv_build.py room: 20 bytes free for each byte of the records it translates (sb.OUT_PER_BYTE + sb.TEMP_PER_BYTE), plus ROOM_SPARE
    REC = len(record(0))

    def free(self, n, *where):   # disk_usage reporting n bytes free (on every drive, or only on those under the folders given; 1 TB elsewhere)
        def usage(p): return SimpleNamespace(total=1 << 40, used=0, free=n if not where or any(Path(p) == w or w in Path(p).parents for w in where) else 1 << 40)
        return mock.patch.object(sb.shutil, 'disk_usage', side_effect=usage)

    def need(self, n): return n * self.REC * (sb.OUT_PER_BYTE + sb.TEMP_PER_BYTE) + sb.ROOM_SPARE

    def test_a_run_that_cannot_fit_stops_before_it_translates(self):
        with self.free(self.need(self.N) - 1), self.assertRaises(SystemExit) as e: self.build()
        self.assertEqual(e.exception.code, 1)
        self.assertRegex(self.text, rf'\[RED\] spv_build: not enough free space to translate {self.N} shaders \(0 MB in the package\): the drive with .+ has 2\.1 GB free, and they '
                         r"need about 2\.1 GB there: 0\.0 GB for the translated shaders and 0\.0 GB for the translator's temporary copy of them until the end, and 2\.1 GB to spare\. "
                         r'Free 0\.0 GB more there')
        self.assertIn('Nothing was translated (DM_SPV_SPACE_CHECK=0 translates anyway)', self.text)
        self.assertEqual(self.touts, []); self.assertFalse(any(self.out.iterdir())); self.assertEqual(self.left(), [])

    def test_a_run_that_fits_goes_on(self):
        with self.free(self.need(self.N)): self.build()
        self.assertEqual(len(list(self.out.glob('*.res.json'))), self.N)

    def test_the_switch_skips_it(self):
        with self.free(0): self.build({'WORK': str(self.work), 'DM_SPV_SPACE_CHECK': '0'})
        self.assertEqual(len(list(self.out.glob('*.res.json'))), self.N)

    def test_only_the_shaders_left_to_translate_count(self):   # a run after one that stopped: the shaders done are skipped, and need no room
        for k in self.keys()[:2]: self.old_output(k, sa.ANDROID_CHAIN)
        with self.free(self.need(3)): self.build()
        self.assertIn('spv_build: 3 translated, 2 already there', self.text)
        shutil.rmtree(self.out)
        for k in self.keys()[:2]: self.old_output(k, sa.ANDROID_CHAIN)
        with self.free(self.need(3) - 1), self.assertRaises(SystemExit): self.build()   # the same run with a byte less: it counts the 3, not the 5
        self.assertIn('not enough free space to translate 3 shaders', self.text)

    def test_an_older_chains_files_are_room_it_reuses(self):   # after an ANDROID_CHAIN bump every shader is translated again, over its old files
        for k in self.keys(): self.old_output(k, sa.ANDROID_CHAIN - 1, size=self.REC * sb.OUT_PER_BYTE)
        with self.free(self.N * self.REC * sb.TEMP_PER_BYTE + sb.ROOM_SPARE): self.build()   # room for the temporary copy alone
        self.assertIn(f'spv_build: {self.N} translated, 0 already there', self.text)

    def test_each_drive_is_checked_for_its_own_part(self):   # WORK on another drive than the out folder: the temporary copy there, the translated files beside out
        with mock.patch.object(sb, 'same_drive', return_value=False):
            with self.free(self.N * self.REC * sb.TEMP_PER_BYTE + sb.ROOM_SPARE - 1, self.work), self.assertRaises(SystemExit): self.build()
            self.assertRegex(self.text, rf"the drive with {re.escape(str(self.work))}.spv_\w+ has .*: 0\.0 GB for the translator's temporary copy of them until the end, and")
            with self.free(self.N * self.REC * sb.TEMP_PER_BYTE + sb.ROOM_SPARE, self.work): self.build()   # the out folder's drive has 1 TB
        self.assertEqual(len(list(self.out.glob('*.res.json'))), self.N)


class Unreadable(Harness):   # what a write that failed leaves: the translator's File.WriteAllBytes creates the file first
    def setUp(self):
        super().setUp(); self.bad = {}   # key → (.spv bytes or None for no file, res.json text or None, [RED] line or '')

    def translate(self, job, tout):
        k = job['key']
        if k not in self.bad: return super().translate(job, tout)
        spv, res, red = self.bad[k]
        if spv is not None: (tout / f'{k}.spv').write_bytes(spv)
        if res is not None: (tout / f'{k}.res.json').write_text(res, encoding='utf-8')
        return red

    def test_empty_or_cut_short_outputs_are_red_lines_and_the_rest_is_translated(self):
        k = self.keys(); good = json.dumps({'key': 'x', 'stage': 'ps', 'cbufs': []})
        self.bad = {k[0]: (b'', good, ''), k[1]: (FRAGMENT[:-4], good, ''), k[2]: (FRAGMENT, '', ''),   # empty; cut at an instruction's end; reflection empty
                    k[3]: (None, None, f'[RED] {k[3]}: NotImplementedException: LDC with a bindless bank or an address mode\n')}   # a shader it can't translate
        text = self.build()
        self.assertEqual(sorted(p.name[:16] for p in self.out.glob('*.res.json')), [k[4]])
        for key, why in ((k[0], '.spv empty (0 bytes)'), (k[1], f'.spv cut short ({len(FRAGMENT) - 4} bytes: it does not end in OpFunctionEnd)'), (k[2], '.res.json empty or cut short')):
            self.assertIn(f"[RED] {key}: the translator's output can't be read: {why}", self.lines)
        self.assertIn('spv_build: 1 translated, 0 already there (0 given their constant buffer extents), 4 failed', text)
        self.assertIn(f'[RED] {k[3]}: NotImplementedException', self.before_post)   # printed before the post-pass, which a stop would lose
        self.assertEqual(self.left(), [])

    def test_a_res_json_cut_short_in_the_out_folder_is_translated_again(self):   # a post-pass that stopped on a full disk before main wrote res.json whole
        k = self.keys()
        self.out.mkdir(); (self.out / f'{k[0]}.spv').write_bytes(FRAGMENT); (self.out / f'{k[0]}.res.json').write_bytes(b'{"key": "')
        text = self.build()
        self.assertIn(f'spv_build: {self.N} translated, 0 already there', text)
        self.assertEqual(json.loads((self.out / f'{k[0]}.res.json').read_text())['android'], sa.ANDROID_CHAIN)


class NoneTranslated(Harness):
    """A run that had shaders to translate and translated none (spv_build.py none_made). runner-a moved the translator's dll aside: dotnet printed why, wrote nothing,
    and every shader got 'no output from the translator'; the run ended '0 translated, …, 30 failed' with exit code 0, and the build packed the game without shaders
    (droidplay-core#307's follow-up). A shader the translator says it can't handle stays no stop, even when it is all a later run has left to translate"""
    GONE = 'Could not execute because the specified command or file was not found.'   # dotnet's first line for a dll that isn't there
    RED = 'NotSupportedException: Ampere instruction 481 at 0x0 (000000000000000000000000020c0481) is not implemented'   # Mario Kart World's 078997bf631992c5

    def setUp(self):
        super().setUp(); self.gone, self.red, self.mute = False, set(), set()   # the dll gone; keys failed with a [RED] line; keys left with nothing and no word

    def process(self, cmd, jobs, tout):
        if self.gone: return subprocess.CompletedProcess(cmd, 1, '', f'{self.GONE}\nPossible reasons for this include:\n')
        r = super().process(cmd, jobs, tout)
        return subprocess.CompletedProcess(cmd, 1 if any(j['key'] in self.red for j in jobs) else 0, r.stdout, r.stderr)   # dmsh_xlate exits 1 when one failed

    def translate(self, job, tout):
        k = job['key']
        if k in self.red: return f'[RED] {k}: {self.RED}\n'
        return '' if k in self.mute else super().translate(job, tout)

    def stops(self, line):   # the run stops with exit code 1, its last line this [RED] spv_build line, before any post-pass, and leaves no temporary folder
        with self.assertRaises(SystemExit) as e: self.build()
        self.assertEqual(e.exception.code, 1)
        self.assertRegex(self.text.rstrip().splitlines()[-1], r'^\[RED\] spv_build: no shader was translated: ' + line)
        self.assertEqual(self.lines, ''); self.assertEqual(self.left(), [])

    def test_a_translator_that_makes_nothing_stops_the_run(self):
        self.gone = True
        self.stops(rf'the translator made none of the {self.N} shaders it was given, and gave a reason for none of them \(exit code 1: {re.escape(self.GONE)}\)\. '
                   r'Check that dmsh_xlate is there and runs, then build again')
        self.assertIn(f'spv_build: 0 translated, 0 already there (0 given their constant buffer extents), {self.N} failed', self.text)
        self.assertEqual(self.text.count('no output from the translator'), self.N); self.assertFalse(self.out.exists() and any(self.out.iterdir()))

    def test_one_that_prints_nothing_either(self):   # a stand-in, or a runtime that starts and exits without a word
        self.mute = set(self.keys())
        self.stops(rf'the translator made none of the {self.N} shaders it was given, and gave a reason for none of them \(it printed nothing\)')

    def test_it_stops_a_later_run_too(self):   # the shaders an earlier run translated are a part of the game's: packed alone, some scenes would draw nothing
        for k in self.keys()[:2]: self.old_output(k, sa.ANDROID_CHAIN)
        self.gone = True
        self.stops(r'the translator made none of the 3 shaders it was given')
        self.assertIn('spv_build: 0 translated, 2 already there', self.text)

    def test_a_translator_that_fails_every_shader_of_a_new_build_stops_it(self):   # with its reasons, but the game would have no shader at all
        self.red = set(self.keys())
        self.stops(rf"the translator failed every one of the game's {self.N} shaders \(their \[RED\] lines above\), and none is there from an earlier run, so the game would have none")
        self.assertEqual(self.text.count('Ampere instruction 481'), self.N)

    def test_a_later_run_with_only_shaders_the_translator_cannot_handle_goes_on(self):   # Mario Kart World's builds after its first: '0 translated, 11576 already there, 1 failed'
        k = self.keys()
        for key in k[:3]: self.old_output(key, sa.ANDROID_CHAIN)
        self.red = set(k[3:])
        text = self.build()
        self.assertIn('spv_build: 0 translated, 3 already there (0 given their constant buffer extents), 2 failed', text)
        self.assertNotIn('no shader was translated', text); self.assertEqual(text.count('Ampere instruction 481'), 2)

    def test_a_run_that_translated_some_goes_on_however_many_failed(self):   # 4 of 5, with reasons and without: how many a game can lose and still play isn't known
        k = self.keys(); self.red, self.mute = {k[0], k[1]}, {k[2], k[3]}
        text = self.build()
        self.assertIn('spv_build: 1 translated, 0 already there (0 given their constant buffer extents), 4 failed', text)
        self.assertEqual(text.count('no output from the translator'), 2); self.assertNotIn('no shader was translated', text)
        self.assertEqual(sorted(p.name[:16] for p in self.out.glob('*.res.json')), [k[4]])

    def test_a_run_with_nothing_to_translate_goes_on(self):   # every shader there already: the translator doesn't run
        for key in self.keys(): self.old_output(key, sa.ANDROID_CHAIN)
        self.gone = True
        text = self.build()
        self.assertIn(f'spv_build: 0 translated, {self.N} already there', text); self.assertEqual(self.touts, [])


class PostPass(unittest.TestCase):   # spv_android.py post_one in this process
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        self.src, self.dst = self.tmp / 'out', self.tmp / 'spv'; self.src.mkdir(); self.dst.mkdir()
        (self.src / 'k.spv').write_bytes(FRAGMENT); (self.src / 'k.res.json').write_text(json.dumps({'key': 'k', 'stage': 'ps', 'cbufs': []}))

    def test_a_full_disk_while_the_files_are_written_leaves_no_res_json(self):   # res.json comes last: without it the shader is not translated, and the next run makes it
        real = Path.write_bytes
        def write(p, data):
            if p.name.startswith('k.res.json'): raise OSError(errno.ENOSPC, 'No space left on device', str(p))
            return real(p, data)
        with mock.patch.object(Path, 'write_bytes', write), self.assertRaises(OSError): sa.post_one(self.src, self.dst, 'k')
        self.assertTrue((self.dst / 'k.spv').exists()); self.assertFalse((self.dst / 'k.res.json').exists())

    def test_files_are_written_whole_under_their_names(self):
        sa.post_one(self.src, self.dst, 'k')
        self.assertEqual(sorted(p.name for p in self.dst.iterdir()), ['k.res.json', 'k.spv'])   # no temporary names left
        self.assertEqual(json.loads((self.dst / 'k.res.json').read_text())['android'], sa.ANDROID_CHAIN)

    def test_an_unreadable_output_removes_an_older_runs_res_json(self):   # else an older chain's reflection would stand for a shader this run lost
        (self.dst / 'k.res.json').write_text('{"android": 5}'); (self.src / 'k.spv').write_bytes(b'')
        counts, lines = sa.post_one(self.src, self.dst, 'k')
        self.assertEqual(counts, (0,) * 7); self.assertIn("[RED] k: the translator's output can't be read: .spv empty (0 bytes)", lines[0])
        self.assertFalse((self.dst / 'k.res.json').exists())

    def test_what_counts_as_unreadable(self):
        self.assertIsNone(sa.unreadable(FRAGMENT))
        n = len(FRAGMENT)
        for data, why in ((b'', 'empty (0 bytes)'), (FRAGMENT[:-3], f'cut short ({n - 3} bytes)'), (FRAGMENT[:20], 'cut short (20 bytes)'), (bytes(64), 'not SPIR-V (64 bytes)'),
                          (FRAGMENT[:-4], f'cut short ({n - 4} bytes: it does not end in OpFunctionEnd)'),
                          (FRAGMENT[:32], 'cut short (32 bytes: an instruction runs past the end)')):   # the header, OpCapability, then OpMemoryModel's first word
            with self.subTest(why=why): self.assertEqual(sa.unreadable(data), why)


class Progress(Harness):   # 'progress: <done>/<total>', which build_android_from_nsp.py shows as a count (droidplay-core#307: hours of translation with nothing to show)
    def counts(self, text): return [ln for ln in text.splitlines() if ln.startswith('progress: ')]

    def test_a_run_says_it_starts_and_ends_with_the_shaders_it_translates(self):
        c = self.counts(self.build())
        self.assertEqual(c[0], f'progress: 0/{self.N}'); self.assertEqual(c[-1], f'progress: {self.N}/{self.N}')

    def test_only_the_shaders_left_to_translate_count(self):   # a build after a stopped one counts from 0 of what is left
        for k in self.keys()[:2]: self.old_output(k, sa.ANDROID_CHAIN)
        c = self.counts(self.build())
        self.assertEqual(c[0], f'progress: 0/{self.N - 2}'); self.assertEqual(c[-1], f'progress: {self.N - 2}/{self.N - 2}')

    def test_nothing_left_says_no_count(self):
        for k in self.keys(): self.old_output(k, sa.ANDROID_CHAIN)
        self.assertEqual(self.counts(self.build()), [])

    def test_the_count_is_the_translators_finished_shaders(self):   # each one's .spv, its reader variant aside, as spv_build's `done` counts them
        d = self.tmp / 'tout'; d.mkdir()
        for n in ('a.spv', 'b.spv', 'b.reader.spv', 'a.res.json'): (d / n).write_bytes(b'')
        self.assertEqual(sb.translated(d), 2); self.assertEqual(sb.translated(self.tmp / 'missing'), 0)

    def test_the_final_pass_is_a_step_with_its_own_count(self):   # #437: after 100 % the post-pass ran with nothing said
        lines = [ln for ln in self.build().splitlines() if ln.startswith(('progress: ', 'step: '))]
        at = lines.index('step: final pass')
        self.assertEqual(lines[at - 1], f'progress: {self.N}/{self.N}')   # the first pass ended
        self.assertEqual(lines[at + 1:], [f'progress: 0/{self.N}', f'progress: {self.N}/{self.N}'])   # the post-pass's res.json files, counted

    def test_written_counts_the_res_json_files_made_since_the_start(self):   # an older run's res.json is older; one the post-pass hasn't reached yet is missing
        d = self.tmp / 'out'; d.mkdir()
        for k in ('old', 'new'): (d / f'{k}.res.json').write_text('{}')
        os.utime(d / 'old.res.json', (1_000_000, 1_000_000))
        self.assertEqual(sb.written(d, ['old', 'new', 'missing'], time.time() - 60), 1)

    def test_counting_says_the_start_and_the_end(self):
        n, buf = [0], io.StringIO()
        with mock.patch.object(sb, 'PROGRESS_SECS', 0.01), contextlib.redirect_stdout(buf):
            with sb.counting(3, lambda: n[0]): n[0] = 3; time.sleep(0.1)
        c = self.counts(buf.getvalue())
        self.assertEqual((c[0], c[-1]), ('progress: 0/3', 'progress: 3/3'))

    def test_the_watch_says_a_count_that_moved_once(self):
        d = self.tmp / 'tout'; d.mkdir(); (d / 'a.spv').write_bytes(b'')
        stop, buf = threading.Event(), io.StringIO()
        with mock.patch.object(sb, 'PROGRESS_SECS', 0.01), contextlib.redirect_stdout(buf):
            t = threading.Thread(target=sb.progress, args=(d, 4, stop)); t.start(); time.sleep(0.2); stop.set(); t.join()
        self.assertEqual(self.counts(buf.getvalue()), ['progress: 1/4'])


if __name__ == '__main__':
    unittest.main()
