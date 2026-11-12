"""dm/android/tools/build_stamp.py, the commit and version the Android host logs on its `build:` line at start (main.c, build_stamp.c), which said
"commit not recorded" on every Android run (droidplay-core#389): a release's archive or DroidPlay for Windows' staged tree gives VERSION and the commit git archive
filled in, a checkout gives git's short hash, +dirty and git describe."""
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import build_stamp as bs   # noqa: E402  # pyright: ignore[reportMissingImports]

SHA = 'c6920f36abcd0123456789abcdef0123456789ab'
FORM = re.compile(r'[0-9a-f]{12}(\+dirty)?( \(v[0-9A-Za-z.+_/-]+\))?|not recorded( \(v[0-9A-Za-z.+_/-]+\))?')   # what main.c's build: line carries after "commit"
GIT = shutil.which('git')
QUIET = ['-c', 'user.name=t', '-c', 'user.email=t@example.com', '-c', 'commit.gpgsign=false', '-c', 'tag.gpgsign=false', '-c', 'core.hooksPath=' + os.devnull]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve(); self.addCleanup(shutil.rmtree, self.tmp, True)

    def tree(self, version=None, commit=None):   # a tree laid out as a release's archive: VERSION, dm/android/tools/build_commit
        t = self.tmp / 'tree'; (t / bs.ARCHIVED).parent.mkdir(parents=True, exist_ok=True)
        if version is not None: (t / 'VERSION').write_text(version, encoding='utf-8')
        if commit is not None: (t / bs.ARCHIVED).write_text(commit, encoding='utf-8')
        return t

    def stamp(self, repo):
        s = bs.stamp(repo); self.assertRegex(s, FORM); return s


class Archive(Base):
    def test_a_release_gives_its_version_and_commit(self):
        self.assertEqual(self.stamp(self.tree('0.8.4\n', SHA + '\n')), 'c6920f36abcd (v0.8.4)')
        self.assertEqual(self.stamp(self.tree('0.8.4-12-gc6920f3\r\n', SHA + '\r\n')), 'c6920f36abcd (v0.8.4-12-gc6920f3)')   # stage.ps1's describe from a checkout; CRLF from git on Windows

    def test_an_archive_without_version_gives_its_commit(self):   # GitHub's own archive of a tag or a branch
        self.assertEqual(self.stamp(self.tree(None, SHA)), 'c6920f36abcd')

    def test_no_git_and_no_archive_commit(self):
        self.assertEqual(self.stamp(self.tree(None, '$Format:%H$\n')), 'not recorded')   # a checkout's copy without its .git
        self.assertEqual(self.stamp(self.tree('0.8.4', '$Format:%H$\n')), 'not recorded (v0.8.4)')

    def test_nothing_that_breaks_the_c_string(self):
        self.assertEqual(self.stamp(self.tree('0.8"4\\x', SHA)), 'c6920f36abcd (v0.8?4?x)')

    def test_the_header_is_rewritten_only_when_it_changes(self):
        out = self.tmp / 'gen' / 'build_stamp.h'
        self.assertEqual(bs.main(['build_stamp.py', str(out)]), 0)
        self.assertRegex(out.read_text(encoding='utf-8'), r'(?m)^#define DM_BUILD_COMMIT "[^"\\]*"$')
        os.utime(out, (1_000_000_000, 1_000_000_000))
        self.assertEqual(bs.main(['build_stamp.py', str(out)]), 0)
        self.assertEqual(out.stat().st_mtime, 1_000_000_000)   # left alone: build_stamp.c does not recompile
        out.write_text('stale', encoding='utf-8')
        bs.main(['build_stamp.py', str(out)])
        self.assertIn('DM_BUILD_COMMIT', out.read_text(encoding='utf-8'))


@unittest.skipIf(GIT is None, 'no git')
class Checkout(Base):
    def git(self, repo, *args):
        return subprocess.run(['git', *QUIET, '-C', str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()

    def test_a_checkout_gives_its_hash_describe_and_dirty(self):
        t = self.tree(None, '$Format:%H$\n'); self.git(t, 'init', '-q'); self.git(t, 'add', '-A'); self.git(t, 'commit', '-qm', 'one')
        head = self.git(t, 'rev-parse', '--short=12', 'HEAD')
        self.assertEqual(self.stamp(t), head)   # no tag to describe from
        self.git(t, 'tag', 'v1.2.3')
        self.assertEqual(self.stamp(t), f'{head} (v1.2.3)')
        (t / 'a.txt').write_text('a', encoding='utf-8'); self.git(t, 'add', 'a.txt'); self.git(t, 'commit', '-qm', 'two')
        head = self.git(t, 'rev-parse', '--short=12', 'HEAD'); desc = self.git(t, 'describe', '--tags')
        self.assertTrue(desc.startswith('v1.2.3-1-g'))
        self.assertEqual(self.stamp(t), f'{head} ({desc})')
        (t / 'a.txt').write_text('b', encoding='utf-8')
        self.assertEqual(self.stamp(t), f'{head}+dirty ({desc})')
        (t / 'a.txt').write_text('a', encoding='utf-8'); (t / 'untracked.txt').write_text('u', encoding='utf-8')
        self.assertEqual(self.stamp(t), f'{head} ({desc})')   # untracked files are not changes to the build

    def test_a_tree_unpacked_inside_another_checkout_is_not_that_checkout(self):
        self.git(self.tmp, 'init', '-q'); (self.tmp / 'x').write_text('x', encoding='utf-8'); self.git(self.tmp, 'add', 'x'); self.git(self.tmp, 'commit', '-qm', 'outer')
        self.assertEqual(self.stamp(self.tree('0.8.4', '$Format:%H$\n')), 'not recorded (v0.8.4)')

    def test_git_archive_fills_in_the_commit(self):   # the .gitattributes beside build_stamp.py, on this repository's HEAD
        head = bs.git(REPO, 'rev-parse', 'HEAD')
        if not head: self.skipTest('not a checkout')
        tar = subprocess.run(['git', '-C', str(REPO), 'archive', '--format=tar', 'HEAD', bs.ARCHIVED.as_posix()], capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            f = t.extractfile(bs.ARCHIVED.as_posix()); assert f is not None
            self.assertEqual(f.read().decode().strip(), head)
        self.assertEqual((REPO / bs.ARCHIVED).read_text(encoding='utf-8').strip(), '$Format:%H$')   # and the checkout's own copy stays the placeholder


if __name__ == '__main__':
    unittest.main()
