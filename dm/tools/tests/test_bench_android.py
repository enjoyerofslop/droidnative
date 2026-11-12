#!/usr/bin/env python3
# scripts/bench_android.py: which screen a run's screenshots are taken of on a phone with more than one (a Galaxy Z Fold 8 or Z Flip 7), from adb's dumpsys output;
# that what is saved is a PNG even when screencap writes a warning ahead of it; that a run removes its own save folder under bench_runs and no other; and that an
# empty pidof alone is never a death; and that a run an adb stall stopped part-way puts the device back and is recorded, not fatal
import contextlib, importlib.util, io, struct, subprocess, unittest, zlib
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


START = '  1794414500.100  2745  2803 I ActivityManager: Start proc 8294:org.nxnative.android:game/u0a160 for next-top-activity {org.nxnative.android/android.app.NativeActivity}\n'


class MemoryKills(unittest.TestCase):   # only the low-memory killer's lines about the game make a run's exit "killed for memory"; lines from real runs (the Galaxy
    # S25 Edge, the Odin 2, the Pixel 9 Pro XL)
    def exit(self, *lines): return ba.log_facts(START + ''.join(lines), None)['exit']

    def test_other_apps_lines_are_not_the_games(self):
        for line in ('  1794414610.042   596   670 E lowmemorykiller: process_mrelease 16341 failed: No such process\n',   # the S25: another app's, mid-run
                     "  1794414618.069   596   596 I lmkd    : Reclaim 'org.nxnative.android' (30238), uid 10392, oom_score_adj 900, state 16 to free 59848kB rss, "
                     "40884kB swap; reason: low watermark is breached or filecache is low (339288kB).\n",   # the launcher's own process, not the game's
                     "  1794421085.000   467   467 I lowmemorykiller: Kill 'com.android.chrome' (23627), uid 10209, oom_score_adj 999 to free 66732kB rss; reason: "
                     "low watermark is breached\n",   # the Pixel: AOSP's tag, another app
                     '  1794421085.100   596   596 W lmkd    : Failed to open /proc/8294/oom_score_adj; errno=3: process 8294 might have been killed\n',   # a maybe
                     '  1794421085.200   596   596 I lmkd    : cached 12, sandbox(not0) 3\n'):
            with self.subTest(line=line[30:90]): self.assertIsNone(self.exit(line))

    def test_the_games_own_kill(self):
        for line in ("  1794414700.000   596   596 I lmkd    : Reclaim 'org.nxnative.android:game' (8294), uid 10392, oom_score_adj 0, state 2 to free 5000000kB rss, "
                     "0kB swap; reason: low watermark is breached and swap is low (11350956kB < 5033160kB)\n",   # the S25's wording
                     "  1794414700.000   467   467 I lowmemorykiller: Kill 'org.nxnative.android:game' (8294), uid 10160, oom_score_adj 0 to free 4000000kB rss; reason: "
                     "min watermark is breached\n",   # AOSP's
                     '  1794414700.000   596   670 E lowmemorykiller: process_mrelease 8294 failed: No such process\n'):   # by the game's pid
            with self.subTest(line=line[30:90]): self.assertEqual(self.exit(line), 'killed for memory')

    def test_a_pid_without_the_games_start_line_names_nothing(self):   # Android 16 can start the process before the run's logcat begins
        line = '  1794414700.000   596   670 E lowmemorykiller: process_mrelease 8294 failed: No such process\n'
        self.assertIsNone(ba.log_facts(line, None)['exit']); self.assertIsNone(self.exit(line.replace('8294', '82941')))


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

    def test_a_wifi_devices_folder_is_one_windows_takes(self):   # its serial is ip:port, and Windows refuses a ':' in a folder name
        self.assertEqual(ba.device_folder({'model': 'Pixel 9 Pro XL', 'serial': '192.168.1.20:37123'}), 'Pixel_9_Pro_XL_192.168.1.20_37123')
        self.assertEqual(ba.device_folder({'model': 'SM-S937B', 'serial': 'R5CY51ZLGKH'}), 'SM-S937B_R5CY51ZLGKH')   # a USB serial is kept as it was

    def test_never_bench_runs_itself_or_a_pattern(self):   # other sessions' run folders live beside this run's
        for bad in (ba.RUNS, ba.RUNS + '/', ba.RUNS + '/*', ba.RUNS + '/..', ba.RUNS + '/a/b', ba.EXT, '/sdcard/Download/x'):
            with self.subTest(bad), mock.patch.object(ba, 'sh') as sh:
                with self.assertRaises(ValueError): ba.remove_run('s1', bad)
                sh.assert_not_called()


class StalledRuns(unittest.TestCase):   # q213's RP5 sweep: `adb exec-out cat bench_frames.tsv` timed out after 120 s, which ended the sweep and left the run's folder and env.txt
    def setUp(self):
        self.run = ba.RUNS + '/0100000000010000_1794445200'; self.lc = mock.Mock(); self.d = Path('/tmp/out/dev/r1')
        ba.PENDING['s1'] = {'run': self.run, 'env': '', 'dir': self.d, 'logcat': self.lc}

    def tearDown(self): ba.PENDING.clear()

    def test_tidy_puts_the_device_back(self):
        with mock.patch.object(ba, 'sh') as sh: ba.tidy('s1')
        self.assertEqual([c.args[1] for c in sh.call_args_list], [f'am force-stop {ba.PKG}', f'rm -rf {self.run} 2>/dev/null', f'rm -f {ba.EXT}/env.txt'])
        self.lc.terminate.assert_called_once(); self.assertNotIn('s1', ba.PENDING)
        with mock.patch.object(ba, 'sh') as sh: ba.tidy('s1')   # nothing left to do
        sh.assert_not_called()

    def test_an_env_txt_that_was_there_goes_back(self):
        ba.PENDING['s1']['env'] = 'DM_VK_DRIVER=turnip\n'
        with mock.patch.object(ba, 'sh'), mock.patch.object(ba, 'adb') as adb, mock.patch.object(ba, 'write_tmp', side_effect=lambda p, t: p): ba.tidy('s1')
        self.assertEqual(adb.call_args.args, ('s1', 'push', str(self.d / 'env_before.txt'), f'{ba.EXT}/env.txt'))

    def test_adb_still_down(self):   # said, not raised: the sweep goes on to the next route
        out = io.StringIO()
        with mock.patch.object(ba, 'sh', side_effect=subprocess.TimeoutExpired('adb', 60)), contextlib.redirect_stdout(out): ba.tidy('s1')
        self.assertIn(self.run, out.getvalue())

    def test_the_run_is_recorded_as_a_bench_error(self):
        r = ba.failed_run('s1', '0100000000010000', {'name': 'dl_sand'}, 1, subprocess.TimeoutExpired('adb', 120))
        self.assertEqual((r['route'], r['fps'], r['exit']), ('dl_sand', None, 'bench error: adb timed out after 120 s'))
        devices = [{'serial': 's1', 'maker': 'Moorechip', 'model': 'Retroid Pocket 5', 'soc': 'SM8250', 'android': '13', 'ram_gb': 7.5, 'gles': ''}]
        with mock.patch.object(Path, 'write_text'): ba.report(Path('/tmp/out'), devices, [r])   # every field report() reads is there
        self.assertIn('| dl_sand | – | – |', ba.bench_sweep.table(ba.bench_sweep.summarize([r]), {}))


def stat(pid, start, state='S'):   # /proc/<pid>/stat, cut down: field 22 is the start time
    return f'{pid} (ive.android:game) {state} 1279 1279 0 0 -1 4194624 100 0 0 0 50 20 0 0 20 0 80 0 {start} 123456 789\n'


class Device:   # answers to the liveness check's two shell calls, in turn: a string, or an exception raised
    def __init__(self, pidof, stat=()):
        self.pidof, self.stat, self.cmds = list(pidof), list(stat), []

    def sh(self, serial, cmd, timeout=60):
        self.cmds.append(cmd); q = self.pidof if cmd.startswith('pidof ') else self.stat if cmd.startswith('cat /proc/') else None
        assert q is not None, cmd; a = q.pop(0)
        if isinstance(a, Exception): raise a
        return a


SEEN = '8294\npidof-done\n'; EMPTY = 'pidof-done\n'; NONE = ''   # pidof found the game; ran and found none; adb gave nothing back (no marker)
GONE = 'stat-done\n'
DIED_AM = '  1794421090.100  2294  2763 I ActivityManager: Process org.nxnative.android:game (pid 8294) has died: fg  TOP\n'
LAUNCHER_DIED = '  1794421085.634  2294  2763 I ActivityManager: Process org.nxnative.android (pid 8258) has died: cch CAC\n'
ZYGOTE = '  1794421090.300  1279  1279 I Zygote  : Process 8294 exited due to signal 9 (Killed)\n'


class GameLiveness(unittest.TestCase):
    def watch(self, dev, logcat=''):
        return ba.GameWatch('odin', lambda: logcat), mock.patch.object(ba, 'sh', dev.sh)

    def check(self, w, el=90.0):
        out = io.StringIO()
        with contextlib.redirect_stdout(out): state = w.check(el)
        return state, out.getvalue()

    def test_an_empty_pidof_while_the_game_lives_is_not_a_death(self):   # the Odin 2's OoT runs: pidof empty at 89 s, the game logging until the bench stopped it
        dev = Device([SEEN, EMPTY], [stat(8294, 5000) + GONE, stat(8294, 5000) + GONE])
        w, p = self.watch(dev)
        with p:
            self.assertEqual(self.check(w, 20.0)[0], 'alive')
            state, said = self.check(w, 89.4)
        self.assertEqual(state, 'alive'); self.assertIn('but the game (pid 8294) is alive', said)
        self.assertEqual(w.misses, [{'t_s': 89.4, 'pidof': 'empty', 'game': 'alive', 'pid': '8294'}])
        self.assertEqual(dev.cmds[0], 'pidof org.nxnative.android:game; echo pidof-done')

    def test_no_answer_from_the_shell_is_unknown(self):
        dev = Device([SEEN, NONE, subprocess.TimeoutExpired('adb', 20)], [stat(8294, 5000) + GONE, NONE, subprocess.TimeoutExpired('adb', 20)])
        w, p = self.watch(dev, LAUNCHER_DIED)   # the launcher's own process dying is not the game's
        with p:
            self.check(w, 20.0)
            self.assertEqual(self.check(w)[0], 'unknown'); self.assertEqual(self.check(w, 91.0)[0], 'unknown')
        self.assertEqual([m['pidof'] for m in w.misses], ['no answer', 'no answer'])

    def test_a_run_of_misses_is_said_once(self):   # a game never seen running would otherwise print a line a second
        w, p = self.watch(Device([EMPTY, EMPTY, EMPTY]))
        with p: said = [self.check(w, t)[1] for t in (16.0, 17.0, 18.0)]
        self.assertEqual([bool(x) for x in said], [True, False, False]); self.assertEqual(len(w.misses), 3)

    def test_a_death_the_kernel_confirms(self):
        for after in (GONE, stat(8294, 7777) + GONE, stat(8294, 5000, 'Z') + GONE):   # no such process; the pid another process's now; a zombie
            with self.subTest(after=after):
                w, p = self.watch(Device([SEEN, EMPTY], [stat(8294, 5000) + GONE, after]))
                with p:
                    self.check(w, 20.0); self.assertEqual(self.check(w)[0], 'dead')
                self.assertEqual(w.misses, [])

    def test_logcat_confirms_a_death_when_the_shell_does_not_answer(self):
        w, p = self.watch(Device([SEEN, NONE], [stat(8294, 5000) + GONE, NONE]), LAUNCHER_DIED + DIED_AM)
        with p:
            self.check(w, 20.0); self.assertEqual(self.check(w)[0], 'dead')

    def test_a_game_never_seen_running(self):
        lmkd = "  1794421090.200   596   596 I lmkd    : Kill 'org.nxnative.android:game' (8294), uid 10160, oom_score_adj 0 to free 1000kB rss\n"
        for logcat, want in (('', 'unknown'), (ZYGOTE, 'unknown'), (lmkd, 'dead'), (DIED_AM, 'dead')):   # Zygote's line names no process: by the pid alone
            with self.subTest(want=want, logcat=logcat[:60]):
                w, p = self.watch(Device([EMPTY]), logcat)
                with p: self.assertEqual(self.check(w, 16.0)[0], want)
                self.assertIsNone(w.pid)

    def test_death_lines_by_pid(self):
        self.assertTrue(ba.died_in_logcat(ZYGOTE, '8294')); self.assertFalse(ba.died_in_logcat(ZYGOTE, '8295'))
        self.assertFalse(ba.died_in_logcat(DIED_AM, '9000'))   # an earlier game process's death, not this one's

    def test_the_pixels_lmkd_tag(self):   # the Pixel 9 Pro XL's lmkd logs under AOSP's tag, lowmemorykiller
        pixel = "  1794421090.200   467   467 I lowmemorykiller: Kill 'org.nxnative.android:game' (8294), uid 10160, oom_score_adj 0 to free 4000000kB rss, 0kB anon rss, " \
                "0kB swap, 0kB dmabuf_pss, 0kB dmabuf_rss; reason: min watermark is breached\n"
        self.assertTrue(ba.died_in_logcat(pixel, '8294')); self.assertTrue(ba.died_in_logcat(pixel, None)); self.assertFalse(ba.died_in_logcat(pixel, '8295'))
        other = pixel.replace('org.nxnative.android:game', 'com.android.chrome')
        self.assertFalse(ba.died_in_logcat(other, None))


if __name__ == '__main__':
    unittest.main()
