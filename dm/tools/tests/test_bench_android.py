#!/usr/bin/env python3
# scripts/bench_android.py: which screen a run's screenshots are taken of on a phone with more than one (a Galaxy Z Fold 8 or Z Flip 7), from adb's dumpsys output
import importlib.util, unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('bench_android', REPO / 'scripts/bench_android.py'); assert spec and spec.loader
ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)

INNER, COVER = '4630000000000000001', '4630000000000000002'
SF_TWO = f'Display {INNER} (HWC display 0): port=147 pnpId=QCM displayName=""\nDisplay {COVER} (HWC display 3): port=148 pnpId=QCM displayName=""\n'
SF_ONE = 'Display 4619827259835644672 (HWC display 0): port=0 pnpId=QCM displayName=""\n'


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


if __name__ == '__main__':
    unittest.main()
