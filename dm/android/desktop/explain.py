"""Plain words for what went wrong in DroidPlay for Windows (scripts/nxnative_android.py): explain() turns the packing script's and adb's own messages into a
title, what to do, and the one button that does it, for the Builds page's failure banner, the Library's statuses and the toasts. The raw message stays on screen
beside it. And the report a player copies for the Discord's #help (Markdown under its 2,000-character limit) or saves in full, with the home folder written as ~
and anything that looks like key material dropped, as scripts/bug_report.py does. Qt-free, so dm/tools/tests/test_android_desktop.py tests the rules against the
real messages without PySide6."""
import platform
import re
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'scripts'))
import bug_report   # noqa: E402  # pyright: ignore[reportMissingImports]  (scripts/, put on the path above: its redaction)

DISCORD = 'https://discord.gg/3r92f8wmh7'
DISCORD_LIMIT = 2000   # characters in one message


@dataclass
class Help:
    title: str
    body: str          # rich text: names in it are escaped
    action: str = ''   # what its button does: phone, retry, keys, tools, folder, backup; '' for none
    label: str = ''    # the button's text
    bug: bool = False  # nothing the player did or can fix: the report for #help is what to do


def esc(s): return str(s).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


# The script's stage names as a player reads them (its own name stays beside, in the report and the Builds page): a stage named with a version or a file
# ("extract v393216") is matched by its first word
STAGES = {'build nx_extract': 'Preparing the game reader', 'extract': 'Reading the game files', 'unpack': 'Reading the game files', 'check': 'Reading the game files',
          'decompress NSZ': 'Unpacking compressed game files', 'rewrite': "Adapting the game's code for Android", 'shader split': "Finding the game's shaders",
          'shaders for Vulkan': "Translating shaders for your phone's GPU", 'Android host': "Building the game's engine", 'APK': 'Packing the DroidPlay app',
          'install and copy to the phone': 'Copying the game to the phone', 'install': 'Installing DroidPlay on the phone',
          'copy the shaders to the phone': 'Copying the shaders to the phone', 'game app': "Packing the game's own app", 'move the one-game install': 'Moving the old install',
          'JDK 21': 'Downloading Java', '.NET SDK 10': 'Downloading .NET', 'Android command-line tools': 'Downloading the Android tools',
          'Android SDK packages': 'Installing the Android SDK'}


def stage_name(tech):
    if not tech: return ''
    if tech.startswith('survey'): return 'Studying the game (experimental build)'
    return STAGES.get(tech) or STAGES.get(tech.split()[0]) or tech


NETWORK = ('urlopen error', 'timed out', 'getaddrinfo failed', 'name or service not known', 'temporary failure in name resolution', 'connection reset',
           'connectionreseterror', 'remotedisconnected', 'connection aborted', 'incompleteread', 'errno 11001', 'winerror 10054', 'winerror 10060', 'http error 5')
PC_FULL = ('not enough space on the disk', 'errno 28', 'winerror 112', 'no space left on device')


def explain(text, phone='', game='', stage='', setup=False, folder='', wifi=False):
    """text: what failed said (its [RED] lines, the last line); phone, game: their names; stage: the script's name of the stage it stopped in; setup: it was
    --setup (Install tools); folder: the game's folder; wifi: the phone was connected over Wi-Fi (wireless debugging). → Help"""
    t = text or ''; low = t.lower(); wifi = wifi or 'wireless debugging is still on' in low   # the script's own words for a Wi-Fi phone that didn't come back
    ph, the_phone, g = esc(phone) if phone else 'Your phone', esc(phone) if phone else 'your phone', esc(game) if game else 'The game'
    adb_said = re.search(r'\badb\b', low) is not None   # an adb command's failure: "No space left on device" is then the phone's, not this PC's
    if 'INSTALL_FAILED_USER_RESTRICTED' in t:
        return Help('Your Xiaomi phone blocked the install', 'In Developer options, turn on <b>Install via USB</b> (it may ask you to sign in to your Xiaomi account), '
                    'then Install again.', 'retry', 'Install again')
    if 'INSTALL_FAILED_UPDATE_INCOMPATIBLE' in t or 'signed with another key' in t:
        return Help('DroidPlay on this phone came from another computer', 'To update it from this PC, copy the signing key (<b>.android\\nxnative-debug.jks</b> in '
                    'your user folder) from that computer to this one. Uninstalling DroidPlay from the phone instead deletes its saves.', 'backup', 'Back up saves')
    m = re.search(r'the phone has ([\d.]+ [KMG]?B) free: .+? needs ([\d.]+ [KMG]?B).*?Free up ([\d.]+ [KMG]?B)', t, re.S)
    if m: return Help(f'Not enough space on {the_phone}', f'{g} needs {m[2]} and {the_phone} has {m[1]} free. Free up {m[3]} (videos, other games), then Install again.',
                      'retry', 'Install again')
    m = re.search(r'The phone has only ([\d.]+ [KMG]?B) free', t)
    if m or 'INSTALL_FAILED_INSUFFICIENT_STORAGE' in t or (adb_said and 'no space left on device' in low):
        return Help(f'Not enough space on {the_phone}', (f'{ph} has only {m[1]} free. ' if m else '') + 'Free up a few GB (videos, other games), then Install again: '
                    'a copy cut short carries on from where it stopped.', 'retry', 'Install again')
    if ('unauthorized' in low or 'authorizing' in low) and 'http error' not in low:   # adb's state, not a web server's 401
        if wifi: return Help(f"{ph} doesn't know this PC over Wi-Fi", 'Pair it again: on the phone, Wireless debugging › Pair device with pairing code, then '
                             '<b>Pair over Wi-Fi…</b> on the Phones page.', 'phone', 'Set up my phone…')
        return Help(f"{ph} hasn't allowed this PC yet", 'Unlock it and tap <b>Allow</b> on "Allow USB debugging?" (tick "Always allow from this computer"). '
                    'No prompt? Unplug it and plug it back in.', 'phone', 'Set up my phone…')
    m = re.search(r'lost the phone (\d+) times', low)   # the script gave up on a connection that kept dropping (survives_drops)
    if m:
        return Help(f'The connection to {the_phone} keeps dropping', f'It dropped {m[1]} times in one install. ' +
                    ('Move the phone closer to the router (5 GHz is faster), keep it awake and charging, or use a USB cable for this install, then Install again: '
                     'the copy carries on from where it stopped.' if wifi or 'router' in low else
                     'Try another cable or USB port (one on the computer itself, not a hub), then Install again: the copy carries on from where it stopped.'), 'retry', 'Install again')
    if ('device offline' in low or '(offline)' in low or 'no devices/emulators found' in low or re.search(r"device '?\S*'? not found", low)
            or 'exit status 255' in low or 'error: closed' in low or 'did not come back within' in low):
        if wifi: return Help(f'{ph} dropped off Wi-Fi', 'Wake it, and check that it is on the same network as this PC and that Wireless debugging is still on '
                             '(its address changes when Wireless debugging restarts: DroidPlay finds it again). Then Install again: the copy carries on from where '
                             'it stopped.', 'retry', 'Install again')
        return Help(f'{ph} stopped answering', 'Unplug it and plug it back in, then Install again: the copy carries on from where it stopped. A different cable or USB '
                    'port helps if it keeps happening.', 'retry', 'Install again')
    if re.search(r'\b0 adb devices ready', low):
        return Help('No phone connected', 'Plug in your phone with a USB cable that carries data, with USB debugging on, or connect it over Wi-Fi on the Phones page '
                    '(Android 11 and later).', 'phone', 'Set up my phone…')
    m = re.search(r'less than ([\d.]+) GB free on the volume of (.+)', t)
    if m or any(x in low for x in PC_FULL):
        where = m[2].strip() if m else folder or ''
        d = re.match(r'[A-Za-z]:', where); drive = f' on drive {d[0].upper()}' if d else ''   # a Windows path's, read on any system
        more = f'about {m[1]} GB free' if m else 'more room'
        return Help('Not enough space on this PC', f'Building {g.lower() if not game else g} needs {more}{drive}' + (f' (in {esc(where)})' if where else '') +
                    ". Free some up, or move the game's folder to a drive with more room.", 'folder' if where else '', 'Open the folder' if where else '')
    m = re.search(r'prod\.keys has no \S+ \(master key \w+, which came with ((?:firmware|a firmware after) [\w.]+)\)', t)
    if m: return Help('Your keys are older than this game', f'It needs keys from a Switch on {esc(m[1])}{"" if "after" in m[1] else " or later"}. Update your Switch, '
                      'dump prod.keys again, and pick the new file.', 'keys', 'Choose prod.keys…')
    if 'no title key for rights id' in low or 'has no common ticket' in low:
        return Help("This game file can't be opened with your keys", 'The file has no ticket for it. Dump the game again from your Switch, with its ticket.')
    if 'give -k' in low or ('prod.keys' in low and 'needs' in low and 'keys' in low and 'master key' not in low):
        return Help('DroidPlay needs your keys', 'NSP and XCI games are encrypted: pick your prod.keys first.', 'keys', 'Choose prod.keys…')
    if 'needs dotnet' in low or 'install the .net 10 sdk' in low:
        return Help('Install the tools first', "DroidPlay reads and builds games with tools it hasn't installed yet.", 'tools', 'Install tools…')
    if 'does not match its' in low:
        return Help('The download came through damaged', "It didn't match what its publisher lists, so DroidPlay deleted it. Try again; if it keeps happening, something "
                    'on your network is changing downloads.', 'retry', 'Try again')
    if any(x in low for x in NETWORK):
        return Help('The download stopped', f'Check your internet connection, then {"Install tools" if setup else "try"} again.', 'retry', 'Try again')
    what, at = 'Installing the tools' if setup else 'The build', stage_name(stage)
    return Help(f'{what} stopped at "{at}"' if at else f'{what} stopped', 'This is probably a bug in DroidPlay, not something you did. Copy the report and post it in '
                '<b>#help</b> on the Discord.', bug=True)


# ---- the report ----
def system_name():
    if sys.platform == 'win32':
        b = sys.getwindowsversion().build   # pyright: ignore[reportAttributeAccessIssue]  (Windows only)
        return f'Windows {11 if b >= 22000 else 10} (build {b})'
    return f'{platform.system()} {platform.release()}'


def redact(text, home):   # bug_report's rules; Windows spells the home folder with \ and, in some tools' messages, with /. And the phone's serial, which a post
    # in a public channel has no need of: the script's --serial and adb's -s name it
    if home: text = text.replace(home.replace('\\', '/'), home)
    text = re.sub(r'(--serial[ =]|--phone-id[ =]|\badb(?:\.exe)? -s )\S+', r'\1<serial>', text)
    text = re.sub(r'\badb-[A-Za-z0-9]+-[^\s.]+\._adb-tls-(?:connect|pairing)\._tcp\.?', '<serial>', text)   # a Wi-Fi phone's mDNS name carries its serial number
    return bug_report.redact(text, home)[0]


def header(info):   # info: version, title, stage, k, n, game, game_id, game_version, phone, android, gpu
    st = info.get('stage') or ''
    lines = [f'**DroidPlay {info.get("version") or "?"}** on {system_name()}',
             f'**{info.get("title") or "A build"}** stopped' + (f' at {stage_name(st)} (`{st}`' + (f', stage {info["k"]} of {info["n"]}' if info.get('k') else '') + ')' if st else '')]
    if info.get('game_id'): lines.append(f'Game: {info.get("game") or "?"} `{info["game_id"]}`' + (f' v{info["game_version"]}' if info.get('game_version') else ''))
    if info.get('phone'):
        lines.append('Phone: ' + ' · '.join(x for x in (info['phone'], f'Android {info["android"]}' if info.get('android') else '', info.get('gpu') or '') if x))
    return lines


def markdown_report(info, reds, log_lines, home, limit=DISCORD_LIMIT - 10):
    """The report to paste in #help: who, what, where it stopped, its [RED] lines and the last lines of its log, cut to fit one Discord message"""
    reds = list(dict.fromkeys(r.strip() for r in reds if r.strip()))[-6:]; tail = [x for x in log_lines if x.strip()][-15:]
    def make(reds, tail):
        out = header(info)
        if reds: out += ['**Error**', '```text', *reds, '```']
        if tail: out += ['**Last lines**', '```text', *tail, '```']
        return redact('\n'.join(out), home)
    text = make(reds, tail)
    while len(text) > limit and tail: tail = tail[1:]; text = make(reds, tail)
    while len(text) > limit and len(reds) > 1: reds = reds[1:]; text = make(reds, tail)
    if len(text) > limit: text = make([r[-300:] for r in reds], tail)
    return text[:limit]


def full_report(info, log_text, journal, home):   # Save full report: the same header, where the journal is, and the whole log
    head = [x.replace('**', '').replace('`', '') for x in header(info)]
    return redact('\n'.join(head + ['', f'Journal: {journal}' if journal else 'Journal: none', '', '---- log ----', log_text]), home)
