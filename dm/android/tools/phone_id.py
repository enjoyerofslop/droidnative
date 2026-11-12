#!/usr/bin/env python3
# What a phone is called in a file or folder name on this computer: its adb serial made safe for every file system. A phone on USB has a plain serial
# (R5CY51ZLGKH), but one over Wi-Fi (wireless debugging) has its address, 192.168.1.20:37123, after `adb connect`, or the name adb found it by on the network,
# adb-R5CY51ZLGKH-AbCdEf._adb-tls-connect._tcp. Windows refuses a ':' in a file or folder name (and <>"/\|?*), and a name that ends in a dot or a space, so a
# folder named after such a serial failed there before anything was copied. Imported by scripts/build_android_from_nsp.py, scripts/bench_android.py and
# device_lock.py, which name a device's logs, runs and lock after it.
import re


def safe(serial):   # every character outside A-Z, a-z, 0-9 and ._- as _, and no dot at the end: the name means the same phone on every computer
    return re.sub(r'[^A-Za-z0-9._-]', '_', serial).rstrip('.') or '_'
