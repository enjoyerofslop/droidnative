"""One user of a phone at a time (dm/android/tools/device_lock.py), as scripts/bench_android.py and scripts/build_android_from_nsp.py take it: a second process is
refused with who holds the device, a holder that dies gives it up, a waiter gets it when it is free, and a holder's children (bench_android.py --install's build) go on.
Runs on Linux, the Mac and Windows (flock, or msvcrt.locking): android.yml runs it on Linux and Windows."""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import device_lock as dl   # noqa: E402  # pyright: ignore[reportMissingImports]   (dm/android/tools, put on the path above)

HOLD = ("import sys, time; sys.path.insert(0, {tools!r}); import device_lock as dl\n"
        "dl.acquire(sys.argv[1], 'a test hold'); print('held', flush=True)\n"
        "time.sleep(float(sys.argv[2]))\n")


class Lock(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp, True)
        env = mock.patch.dict(os.environ, {'NXNATIVE_LOCK_DIR': str(self.tmp)}); env.start(); self.addCleanup(env.stop)
        os.environ.pop(dl.LOCKED_ENV, None); os.environ.pop('NXNATIVE_DEVICE_HOLDER', None)
        self.addCleanup(lambda: [dl.release(s) for s in list(dl._held)])
        self.procs = []
        self.addCleanup(self.end_holders)

    def end_holders(self):
        for p in self.procs:
            if p.poll() is None: p.kill()
            p.wait(); p.stdout.close()   # pyright: ignore[reportOptionalMemberAccess]

    def hold(self, serial, seconds: float = 30, holder='session one'):   # another process holding serial; returns once it holds it
        env = dict(os.environ, NXNATIVE_DEVICE_HOLDER=holder); env.pop(dl.LOCKED_ENV, None)
        p = subprocess.Popen([sys.executable, '-c', HOLD.format(tools=str(REPO / 'dm/android/tools')), serial, str(seconds)], env=env, stdout=subprocess.PIPE, text=True)
        self.procs.append(p)
        self.assertEqual(p.stdout.readline().strip(), 'held')   # pyright: ignore[reportOptionalMemberAccess]
        return p

    def test_a_second_process_is_refused_and_told_who_holds_it(self):
        self.hold('R5CY51ZLGKH')
        with self.assertRaises(dl.DeviceBusy) as e: dl.acquire('R5CY51ZLGKH', 'a bench')
        self.assertIn('R5CY51ZLGKH', str(e.exception)); self.assertIn('session one: a test hold', str(e.exception))
        self.assertEqual(dict(dl.status())['R5CY51ZLGKH'][:21], 'session one: a test h')

    def test_a_holder_that_dies_gives_the_device_up(self):
        p = self.hold('e7879cce'); p.kill(); p.wait()
        dl.acquire('e7879cce', 'after a crash')
        self.assertIn('e7879cce', dl._held)
        self.assertIn('after a crash', dict(dl.status())['e7879cce'])

    def test_a_waiter_gets_the_device_once_it_is_free(self):
        self.hold('4839ed0d', seconds=1.5); said = []
        t = time.monotonic(); dl.acquire('4839ed0d', 'a waiting bench', wait=30, say=said.append)
        self.assertLess(time.monotonic() - t, 25)
        self.assertEqual(len(said), 1); self.assertIn('session one', said[0])

    def test_other_devices_stay_free(self):
        self.hold('be4ec45a')
        dl.acquire('RFGL70T5WNF', 'the Fold'); self.assertIn('RFGL70T5WNF', dl._held)

    def test_children_of_a_holder_go_on(self):   # bench_android.py --install runs build_android_from_nsp.py --push-only on a device it holds
        dl.acquire('4839ed0d', 'a bench with --install')
        self.assertIn('4839ed0d', os.environ[dl.LOCKED_ENV].split(','))
        code = ("import sys; sys.path.insert(0, %r); import device_lock as dl\n"
                "dl.acquire('4839ed0d', 'its install'); print('went on' if '4839ed0d' not in dl._held else 'locked again')") % str(REPO / 'dm/android/tools')
        self.assertEqual(subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=True).stdout.strip(), 'went on')

    def test_release_frees_and_held_keeps_an_earlier_hold(self):
        with dl.held('e7879cce', 'a block'): self.assertIn('e7879cce', dl._held)
        self.assertNotIn('e7879cce', dl._held)
        self.assertIsNone(dict(dl.status())['e7879cce'])
        dl.acquire('e7879cce', 'the whole run')
        with dl.held('e7879cce', 'an install inside it'): pass
        self.assertIn('e7879cce', dl._held)

    def test_a_wifi_serial_gets_a_file_of_its_own(self):
        dl.acquire('192.168.50.20:5555', 'over Wi-Fi')
        self.assertTrue((self.tmp / '192.168.50.20_5555.lock').exists())
        dl.acquire('adb-R5CY51ZLGKH-AbCdEf._adb-tls-connect._tcp.', 'found by adb on the network')   # no dot at the end: Windows drops it
        self.assertTrue((self.tmp / 'adb-R5CY51ZLGKH-AbCdEf._adb-tls-connect._tcp.lock').exists())

    def build_script(self, props):   # build_android_from_nsp.py with adb answering phone_id.ID_CMD from props (serial → its output), and nothing else
        spec = importlib.util.spec_from_file_location('build_android_from_nsp', REPO / 'scripts/build_android_from_nsp.py')
        assert spec and spec.loader
        ba = importlib.util.module_from_spec(spec); spec.loader.exec_module(ba)
        def adb(serial, *a, log=None, check=True, timeout=None):
            self.assertEqual(a, ('shell', ba.phone_id.ID_CMD)); return props.get(serial, '')
        cm = mock.patch.object(ba, 'adb', adb); cm.start(); self.addCleanup(cm.stop)
        return ba

    def test_the_build_script_stops_with_a_build_error(self):
        ba = self.build_script({})   # phones that give no ID are locked by their serial
        self.hold('R5CY51ZLGKH', holder='a bench')
        with self.assertRaises(ba.BuildError) as e:
            with ba.phone('R5CY51ZLGKH', 'installing a game'): pass
        self.assertIn('in use by a bench', str(e.exception))
        with ba.phone('e7879cce', 'installing a game'): self.assertIn('e7879cce', dl._held)
        self.assertNotIn('e7879cce', dl._held)

    def test_a_phone_on_usb_and_wifi_is_one_device(self):   # two serials, one phone: two locks let two installs run on it at once
        ba = self.build_script({'R5CY51ZLGKH': 'R5CY51ZLGKH\n9774d56d682e549c\n', '192.168.1.20:37123': 'R5CY51ZLGKH\r\n9774d56d682e549c\r\n',
                                'adb-R5CY51ZLGKH-AbCdEf._adb-tls-connect._tcp': 'R5CY51ZLGKH\n9774d56d682e549c\n'})
        self.hold('R5CY51ZLGKH', holder='an install over the cable')
        for wifi in ('192.168.1.20:37123', 'adb-R5CY51ZLGKH-AbCdEf._adb-tls-connect._tcp'):
            with self.assertRaisesRegex(ba.BuildError, 'in use by an install over the cable'):
                with ba.phone(wifi, 'installing a game over Wi-Fi'): pass

    def test_a_phone_with_a_placeholder_serial_is_locked_by_its_android_id(self):   # cheap phones share 0123456789ABCDEF: two of them are two devices
        ba = self.build_script({'0123456789ABCDEF': '0123456789ABCDEF\n9774d56d682e549c\n', '10.0.0.5:5555': '0123456789ABCDEF\nf00dfeed12345678\n'})
        with ba.phone('0123456789ABCDEF', 'installing'):
            with ba.phone('10.0.0.5:5555', 'installing on the other one'): self.assertEqual(set(dl._held), {'aid-9774d56d682e549c', 'aid-f00dfeed12345678'})


if __name__ == '__main__':
    unittest.main()
