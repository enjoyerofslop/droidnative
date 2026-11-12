#!/usr/bin/env python3
# Which phone an adb serial is, and what it is called in a file or folder name on this computer. A phone on USB has a plain serial (R5CY51ZLGKH), but one over
# Wi-Fi (wireless debugging) has its address, 192.168.1.20:37123, after `adb connect`, or the name adb found it by on the network,
# adb-R5CY51ZLGKH-AbCdEf._adb-tls-connect._tcp. The address changes whenever wireless debugging restarts or the phone reboots, and one phone on a cable and on
# Wi-Fi at once is listed twice, so anything kept per phone is kept under its stable ID: ro.serialno (what adb shows for it over USB), or, where a maker left that
# empty or a placeholder, the Android ID the shell reads (aid-<16 hex digits>, the same until a factory reset). Imported by scripts/build_android_from_nsp.py,
# scripts/bench_android.py, device_lock.py and the desktop app (scripts/nxnative_android.py); Qt-free, so its tests run without PySide6.
import re

ID_CMD = 'getprop ro.serialno; settings get secure android_id'   # one adb shell call; its two lines go to from_props
PLACEHOLDERS = {'', 'unknown', 'null', '0123456789abcdef', '0000000000000000', '1234567890abcdef'}   # serials cheap phones share, lower case: no use as an ID
MDNS = re.compile(r'^adb-(.+)-[^-.]+\._adb-tls-connect\._tcp\.?$')   # adbd's service name: adb-<ro.serialno>-<its own random suffix>
TRANSPORTS = ('usb', 'mdns', 'tcp')   # the order a phone listed more than once is picked in: a cable is faster than Wi-Fi, and an mDNS name survives a new port


def safe(serial):   # every character outside A-Z, a-z, 0-9 and ._- as _, and no dot at the end: Windows refuses ':' (and <>"/\|?*) in a name, and a trailing dot
    return re.sub(r'[^A-Za-z0-9._-]', '_', serial).rstrip('.') or '_'


def transport(serial):   # 'usb', 'tcp' (an address, after adb connect or adb tcpip) or 'mdns' (a name adb found on the network)
    if '._adb-tls-connect._tcp' in serial: return 'mdns'
    if re.fullmatch(r'(\[[0-9A-Fa-f:.%\w]+\]|[\w.-]+):\d+', serial): return 'tcp'
    return 'usb'


def wifi(serial): return transport(serial) != 'usb'


def mdns_serialno(name):   # the ro.serialno an mDNS service name carries, or None: a phone found on the network matched to one known, with no adb shell call
    m = MDNS.match(name)
    return m[1] if m and m[1].lower() not in PLACEHOLDERS else None


def stable_id(serialno, android_id=''):   # → the phone's ID, or None when it gives neither a real serial number nor an Android ID
    s, a = (serialno or '').strip(), (android_id or '').strip()
    if s.lower() not in PLACEHOLDERS and safe(s) == s: return s
    if re.fullmatch(r'[0-9A-Fa-f]{8,64}', a) and a.strip('0'): return f'aid-{a.lower()}'
    return None


def from_props(out):   # ID_CMD's output → the phone's ID, or None
    lines = [x.strip() for x in (out or '').splitlines()] + ['', '']
    return stable_id(lines[0], lines[1])


def one_per_phone(devs):   # devices as dicts with 'serial' and 'id' (None: not known) → one per phone, by TRANSPORTS' order, in the order each phone first came
    best, order = {}, []
    for d in devs:
        k = d.get('id') or d['serial']
        if k not in best: order.append(k); best[k] = d
        elif TRANSPORTS.index(transport(d['serial'])) < TRANSPORTS.index(transport(best[k]['serial'])): best[k] = d
    return [best[k] for k in order]


def find(serials, keys, ids):   # the index in serials (a picker's entries; None for one that is no phone) of the first of keys, an ID or a serial, naming one; or -1
    for k in keys:
        for i, s in enumerate(serials):
            if k and s and k in (s, ids.get(s)): return i
    return -1
