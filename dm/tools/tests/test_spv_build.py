"""dm/android/tools/spv_build.py's run around the translator, over a package of synthetic pixel shader records, with a stand-in for dmsh_xlate (it writes each job's
.spv and .res.json, or what a test asks for); spv_android.py's post-pass runs as it does in a build, on a minimal fragment shader. Checked: the temporary folder (the code
areas, the job lists and the translator's output) is made under WORK, the build's <id>_build/tmp, and removed however the run ends, a full disk included
(droidplay-core#307: three failed Pokémon Pokopia runs each left tens of GB in the system's temp folder); a full disk, in the translator's lines or in this script's own
writes, stops the run with a plain line before the post-pass, which stopped at the first empty .spv. No game files, no translator, no spirv-as."""
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
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
        self.touts, self.lines = [], ''
        self.post_fails = False
        real = subprocess.run
        def run(cmd, **k):
            if cmd[0] == sys.executable:   # the post-pass, run as spv_build runs it, its output kept for the test
                if self.post_fails: raise subprocess.CalledProcessError(1, cmd)
                r = real(cmd, capture_output=True, text=True); self.lines += r.stdout + r.stderr
                if k.get('check') and r.returncode: raise subprocess.CalledProcessError(r.returncode, cmd, r.stdout, r.stderr)
                return r
            jp, tout = Path(cmd[-2]), Path(cmd[-1]); self.touts.append(tout)
            err = ''.join(self.translate(j, tout) for j in json.loads(jp.read_text(encoding='utf-8')))
            return subprocess.CompletedProcess(cmd, 0, f'translated: {self.N}\n', err)
        for p in (mock.patch.object(sb.subprocess, 'run', side_effect=run), mock.patch.object(tempfile, 'tempdir', str(self.sysdir))):   # the system's temp folder, watched too
            p.start(); self.addCleanup(p.stop)

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
                if 'WORK' not in env: os.environ.pop('WORK', None)
                sb.main()
        finally: self.text = buf.getvalue()
        return self.text

    def left(self):   # temporary folders under WORK or in the system's temp folder after the run
        return sorted(str(p) for d in (self.work, self.sysdir) if d.exists() for p in d.glob('spv_*'))


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


if __name__ == '__main__':
    unittest.main()
