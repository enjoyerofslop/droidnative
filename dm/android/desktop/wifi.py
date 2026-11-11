"""DroidPlay for Windows' Wi-Fi setup (scripts/nxnative_android.py's PairDialog and the Phones page's Connect…): what adb pair, adb connect, adb devices and
adb mdns services say, read into what the dialog needs and into plain words. adb's own text ("Failed: Unable to start pairing client.") was shown raw in a toast.
Qt-free, so dm/tools/tests/test_android_desktop.py tests it against adb's real messages without PySide6."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import phone_id   # noqa: E402  # pyright: ignore[reportMissingImports]  (dm/android/tools, put on the path above: mDNS names and services)

SAME_NETWORK = 'the phone and this PC are on the same Wi-Fi network (a guest network keeps devices apart)'
STEPS = ('On the phone: <b>Settings › Developer options › Wireless debugging</b>, turned on (Android 11 and later).',
         'Tap <b>Pair device with pairing code</b> and keep that screen open.',
         'Pick the phone below and type the six-digit code it shows.')


def pairing(out):   # adb mdns services → [(label, 'ip:port')]: the phones showing a pairing code now
    return [(f'{phone_id.serialno_of(name) or name} · {addr}', addr) for name, kind, addr in phone_id.services(out) if kind == 'pairing']


def last_line(out): return next((x.strip() for x in reversed((out or '').splitlines()) if x.strip()), '') or 'no answer'


def pair_result(ok, out):   # adb pair's exit and output → (paired, the phone's serial number from adb's guid or None, what to tell the player)
    t = out or ''; low = t.lower()
    m = re.search(r'successfully paired to \S+ \[guid=([^\]\s]+)\]', t, re.I)
    if m or (ok and 'successfully paired' in low): return True, phone_id.serialno_of(m[1]) if m else None, 'Paired'
    if 'wrong password' in low:
        return False, None, "The code didn't match. Type the six digits the phone shows now: it makes a new code each time that screen opens."
    if any(x in low for x in ('timed out', 'timeout')):
        return False, None, f"The phone didn't answer in time. Keep its pairing screen open, and check that {SAME_NETWORK}."
    if any(x in low for x in ('unable to start pairing client', 'failed to connect', 'connection refused', 'no route to host', 'unreachable', 'cannot connect')):
        return False, None, f"DroidPlay couldn't reach the phone. Keep its <b>Pair device with pairing code</b> screen open, and check that {SAME_NETWORK}."
    if 'unknown host' in low or 'cannot resolve' in low or 'bad address' in low:
        return False, None, 'That address is not one adb can use: type it as the phone shows it, e.g. 192.168.1.20:37123.'
    return False, None, f'Pairing failed: {last_line(t)}'


def connect_result(ok, out):   # adb connect's exit and output → (connected, what to tell the player). adb connect exits 0 when it fails, too
    t = out or ''; low = t.lower()
    if re.search(r'\b(already )?connected to ', low) and 'failed' not in low and 'cannot' not in low: return True, 'Connected'
    if 'failed to authenticate' in low or 'unauthorized' in low:
        return False, "The phone didn't accept this PC: pair it first (<b>Pair over Wi-Fi…</b>)."
    if 'cannot resolve' in low or 'unknown host' in low or 'bad address' in low:
        return False, 'That address is not one adb can use: type it as the phone shows it, e.g. 192.168.1.20:37123.'
    if any(x in low for x in ('failed to connect', 'connection refused', 'no route to host', 'unreachable', 'timed out', 'cannot connect')):
        return False, ("No phone answered there. Check the address and port on the phone's <b>Wireless debugging</b> screen (the port changes each time it restarts), "
                       f'and that {SAME_NETWORK}.')
    return False, f'Connecting failed: {last_line(t)}'


def listed(devices_out, serialno, ip):   # adb devices' output → the serial adb already lists for that phone, ready: adb connects a paired phone by itself (mDNS)
    for line in (devices_out or '').splitlines()[1:]:
        p = line.split()
        if len(p) > 1 and p[1] == 'device' and ((serialno and phone_id.serialno_of(p[0]) == serialno) or (ip and p[0].startswith(ip + ':'))): return p[0]
    return None


def connect_target(mdns_out, serialno, ip):   # after pairing: the phone's wireless debugging service ('ip:port'), by its serial number or its address, or None
    for name, kind, addr in phone_id.services(mdns_out):
        if kind == 'connect' and ((serialno and phone_id.serialno_of(name) == serialno) or (ip and addr.rsplit(':', 1)[0] == ip)): return addr
    return None
