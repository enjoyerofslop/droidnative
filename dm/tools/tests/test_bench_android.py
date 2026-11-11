#!/usr/bin/env python3
# scripts/bench_android.py: which screen a run's screenshots are taken of on a phone with more than one (a Galaxy Z Fold 8 or Z Flip 7), from adb's dumpsys output;
# that what is saved is a PNG even when screencap writes a warning ahead of it; and that a run removes its own save folder under bench_runs and no other
import importlib.util, struct, unittest, zlib
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('bench_android', REPO / 'scripts/bench_android.py'); assert spec and spec.loader
ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)

INNER, COVER = '4630000000000000001', '4630000000000000002'
SF_TWO = f'Display {INNER} (HWC display 0): port=147 pnpId=QCM displayName=""\nDisplay {COVER} (HWC display 3): port=148 pnpId=QCM displayName=""\n'
SF_ONE = 'Display 4619827259835644672 (HWC display 0): port=0 pnpId=QCM displayName=""\n'
# What a Galaxy Z Fold 8 (Android 17) writes ahead of the PNG to `screencap -p` without -d, byte for byte from a bench's shot_start.png of 2026-11-10
FOLD_WARNING = (b'[Warning] Multiple displays were found, but no display id was specified! Defaulting to the first display found, however this default is not '
                b'guaranteed to be consistent across captures. A display id should be specified.\nA display ID can be specified with the [-d display-id] option.\n'
                b'See "dumpsys SurfaceFlinger --display-id" for valid display IDs.\n')


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))


PNG = ba.PNG_SIGNATURE + chunk(b'IHDR', struct.pack('>IIBBBBB', 1, 1, 8, 0, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(b'\0\x80')) + chunk(b'IEND', b'')   # 1x1 grey


def is_png(b: bytes) -> bool:   # the signature, then chunks with good CRCs from IHDR to IEND, and nothing after: what `file` and PIL need
    if not b.startswith(ba.PNG_SIGNATURE): return False
    at, kinds = len(ba.PNG_SIGNATURE), []
    while at < len(b):
        n, kind = struct.unpack('>I4s', b[at:at + 8]); data = b[at + 8:at + 8 + n]
        if struct.unpack('>I', b[at + 8 + n:at + 12 + n])[0] != zlib.crc32(kind + data): return False
        kinds.append(kind); at += 12 + n
    return bool(kinds) and kinds[0] == b'IHDR' and kinds[-1] == b'IEND'


def display_dump(inner, cover):   # the shape of a Galaxy Z Fold 8's `dumpsys display` (Android 17), cut down to what is read and what must not be
    return f'''DISPLAY MANAGER (dumpsys display)
  mViewports=[DisplayViewport{{type=INTERNAL, valid=true, isActive=true, displayId=0, uniqueId='local:{COVER}', physicalPort=148}}]

Display Devices: size=2
-----------------------
  DisplayDeviceInfo{{"Built-in Screen": uniqueId="local:{INNER}", 2448 x 1848, modeId 1}}
    mAdapter=LocalDisplayAdapter
    mUniqueId=local:{INNER}
    mHasArrSupport=true
    mState={inner}
    mCommittedState={inner}
  DisplayDeviceInfo{{"Built-in Screen": uniqueId="local:{COVER}", 1248 x 1972, modeId 3}}
    mAdapter=LocalDisplayAdapter
    mUniqueId=local:{COVER}
    mState={cover}
    mCommittedState={cover}

LogicalDisplayMapper:
  Logical Displays: size=2
    mDisplayId=0
    mPrimaryDisplayDevice=Built-in Screen(local:{COVER})

Automatic Brightness Controller Configuration:
    mUniqueId=local:{INNER}
  mState=AUTO_BRIGHTNESS_ENABLED
'''


def ids(sf): return ba.re.findall(r'^Display (\d+) \(HWC display (\d+)\)', sf, ba.re.M)


class ShotDisplay(unittest.TestCase):
    def test_states_from_the_display_devices_section_only(self):
        self.assertEqual(ba.display_states(display_dump('OFF', 'ON')), {INNER: 'OFF', COVER: 'ON'})   # not the brightness section's mState after it
        self.assertEqual(ba.display_states('nothing here\n'), {})

    def test_the_screen_that_is_on(self):
        self.assertEqual(ba.shot_display(ids(SF_TWO), ba.display_states(display_dump('OFF', 'ON'))), COVER)       # folded: the cover screen (HWC display 3)
        self.assertEqual(ba.shot_display(ids(SF_TWO), ba.display_states(display_dump('ON', 'OFF'))), INNER)       # unfolded: the inner screen
        self.assertEqual(ba.shot_display(ids(SF_TWO), ba.display_states(display_dump('OFF', 'ON_SUSPEND'))), COVER)

    def test_none_or_both_on_keep_hwc_display_0(self):   # #132's choice when the state doesn't settle it
        self.assertEqual(ba.shot_display(ids(SF_TWO), ba.display_states(display_dump('OFF', 'OFF'))), INNER)
        self.assertEqual(ba.shot_display(ids(SF_TWO), ba.display_states(display_dump('ON', 'ON'))), INNER)
        self.assertEqual(ba.shot_display(ids(SF_TWO), {}), INNER)

    def test_one_screen_no_display_argument(self):
        self.assertIsNone(ba.shot_display(ids(SF_ONE), {}))
        self.assertIsNone(ba.shot_display([], {}))

    def test_screenshot_asks_which_screen_is_on_at_each_shot(self):
        dumps = iter([display_dump('OFF', 'ON'), display_dump('ON', 'OFF')])   # folded at the first shot, unfolded at the second
        calls = []
        def sh(serial, cmd, timeout=60):
            calls.append(cmd); return SF_TWO if 'SurfaceFlinger' in cmd else next(dumps)
        with mock.patch.dict(ba._displays, clear=True), mock.patch.object(ba, 'sh', sh), mock.patch.object(ba, 'adb_bytes', return_value=b'png') as shot:
            ba.screenshot('s1'); ba.screenshot('s1')
        self.assertEqual([c.args for c in shot.call_args_list], [('s1', 'exec-out', 'screencap', '-p', '-d', COVER), ('s1', 'exec-out', 'screencap', '-p', '-d', INNER)])
        self.assertEqual(calls.count('dumpsys SurfaceFlinger --display-id'), 1)   # the displays once per device, their state each time

    def test_screenshot_on_a_phone_with_one_screen(self):
        with mock.patch.dict(ba._displays, clear=True), mock.patch.object(ba, 'sh', return_value=SF_ONE) as sh, mock.patch.object(ba, 'adb_bytes', return_value=b'png') as shot:
            ba.screenshot('s2'); ba.screenshot('s2')
        self.assertEqual(shot.call_args.args, ('s2', 'exec-out', 'screencap', '-p'))
        self.assertEqual(sh.call_count, 1)   # no dumpsys display: nothing to choose between

    def test_an_empty_display_list_is_asked_for_again(self):   # adb or dumpsys failing at the first shot leaves the later ones their -d
        sf = iter(['', SF_TWO])
        def sh(serial, cmd, timeout=60): return next(sf) if 'SurfaceFlinger' in cmd else display_dump('OFF', 'ON')
        with mock.patch.dict(ba._displays, clear=True), mock.patch.object(ba, 'sh', sh), mock.patch.object(ba, 'adb_bytes', return_value=PNG) as shot:
            ba.screenshot('s3'); ba.screenshot('s3'); ba.screenshot('s3')
        self.assertEqual([c.args for c in shot.call_args_list], [('s3', 'exec-out', 'screencap', '-p')] + [('s3', 'exec-out', 'screencap', '-p', '-d', COVER)] * 2)


class ShotBytes(unittest.TestCase):
    def test_the_fold_warning_ahead_of_the_png_goes(self):
        self.assertFalse(is_png(FOLD_WARNING + PNG))   # the file a bench saved before: `file` calls it data
        self.assertEqual(ba.png_only(FOLD_WARNING + PNG), PNG)
        self.assertTrue(is_png(ba.png_only(FOLD_WARNING + PNG)))

    def test_a_png_alone_or_no_png_is_kept_as_it_is(self):
        self.assertEqual(ba.png_only(PNG), PNG)
        self.assertEqual(ba.png_only(b'Error: display 7 not found\n'), b'Error: display 7 not found\n')   # screencap's own words, left to read
        self.assertEqual(ba.png_only(b''), b'')

    def test_screenshot_saves_the_png_without_the_warning(self):   # a two-screen phone whose display list didn't come: no -d, so the warning, but a PNG saved
        with mock.patch.dict(ba._displays, clear=True), mock.patch.object(ba, 'sh', return_value=''), \
                mock.patch.object(ba, 'adb_bytes', return_value=FOLD_WARNING + PNG):
            self.assertEqual(ba.screenshot('s4'), PNG)


class RunFolders(unittest.TestCase):
    def test_a_run_removes_its_own_folder(self):
        run = ba.run_folder('0400486024DEC000')
        self.assertRegex(run, r'^' + ba.RUNS + r'/0400486024DEC000_\d+$')
        with mock.patch.object(ba, 'sh') as sh: ba.remove_run('s1', run)
        self.assertEqual(sh.call_args.args, ('s1', f'rm -rf {run} 2>/dev/null'))

    def test_never_bench_runs_itself_or_a_pattern(self):   # other sessions' run folders live beside this run's
        for bad in (ba.RUNS, ba.RUNS + '/', ba.RUNS + '/*', ba.RUNS + '/..', ba.RUNS + '/a/b', ba.EXT, '/sdcard/Download/x'):
            with self.subTest(bad), mock.patch.object(ba, 'sh') as sh:
                with self.assertRaises(ValueError): ba.remove_run('s1', bad)
                sh.assert_not_called()


if __name__ == '__main__':
    unittest.main()
