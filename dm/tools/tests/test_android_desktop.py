"""DroidPlay for Windows' first run, as the desktop app (scripts/nxnative_android.py) shows it, from its Qt-free helpers in dm/android/desktop: the "Get started"
checklist's four steps worked out from what the computer has (first_run.py), Install tools' one bar across --setup's stages, and plain words for what went wrong
with the report for #help (explain.py), matched against the packing script's, nx_extract's and adb's own messages. No PySide6, phone or network needed."""
import hashlib
import http.server
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/desktop'))
import first_run as fr   # noqa: E402  # pyright: ignore[reportMissingImports]  (dm/android/desktop, put on the path above)
import explain as ex   # noqa: E402  # pyright: ignore[reportMissingImports]
import phone_guide as pg   # noqa: E402  # pyright: ignore[reportMissingImports]
import phone_gpu as gpu   # noqa: E402  # pyright: ignore[reportMissingImports]
import vk_drivers as vkd   # noqa: E402  # pyright: ignore[reportMissingImports]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import vk_catalog   # noqa: E402  # pyright: ignore[reportMissingImports]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_android_cli import elf, make_pkg   # noqa: E402  (a minimal Android driver ELF and an AdrenoTools package around it)

ROWS_OK = [{'name': n, 'ok': True, 'detail': '', 'fix': ''} for n in ('Python module lz4', '.NET SDK 10', 'Android SDK', 'NDK', 'CMake', 'build-tools 36.0.0',
                                                                       'platform android-35', 'adb', 'JDK keytool', 'JDK javac', 'signing key', 'game hosts')]


def rows(*missing): return [dict(r, ok=r['name'] not in missing) for r in ROWS_OK]


class Keys(unittest.TestCase):
    def setUp(self): self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)

    def test_none_picked_asks_for_them(self):
        s = fr.keys_step('')
        self.assertEqual((s.state, s.button), (fr.TODO, 'Choose prod.keys…'))

    def test_prod_keys_are_done(self):
        f = self.tmp / 'prod.keys'; f.write_text('header_key = 00\nmaster_key_00 = 11\n')
        s = fr.keys_step(str(f))
        self.assertTrue(s.done); self.assertIn('prod.keys', s.text)

    def test_title_keys_are_a_problem(self):   # Lockpick_RCM writes both: title.keys holds rights IDs and their keys, which can't open a game alone
        f = self.tmp / 'title.keys'; f.write_text('01006f8002326000000000000000000a = 0123456789abcdef0123456789abcdef\n')
        s = fr.keys_step(str(f))
        self.assertEqual(s.state, fr.PROBLEM); self.assertIn('not title.keys', s.text)

    def test_a_file_since_moved_is_a_problem(self):
        s = fr.keys_step(str(self.tmp / 'gone.keys'))
        self.assertEqual(s.state, fr.PROBLEM); self.assertIn("isn't there any more", s.text)


class Tools(unittest.TestCase):
    def test_looking_while_check_runs(self):
        self.assertEqual(fr.tools_step(None, True).state, fr.WORKING)

    def test_all_there_is_done(self):
        self.assertTrue(fr.tools_step(rows(), True).done)

    def test_a_new_pc_installs_all_three(self):
        s = fr.tools_step(rows('.NET SDK 10', 'Android SDK', 'adb', 'JDK keytool', 'JDK javac'), True)
        self.assertEqual((s.state, s.button), (fr.TODO, 'Install tools…')); self.assertIn('1.5 GB', s.text)

    def test_only_what_is_missing_is_named(self):
        s = fr.tools_step(rows('NDK'), True)
        self.assertIn('Still to install: the Android SDK.', s.text); self.assertNotIn('Java', s.text.split('Still')[1])

    def test_elsewhere_settings_says_how(self):   # --setup installs on Windows alone
        s = fr.tools_step(rows('.NET SDK 10'), False)
        self.assertEqual(s.button, 'Open Settings'); self.assertIn('Settings says how', s.text)

    def test_one_bar_while_setup_runs(self):
        s = fr.tools_step(rows('NDK'), True, ('running', 0.4, 'Installing the Android SDK · the NDK (4 of 5)'))
        self.assertEqual((s.state, s.fraction), (fr.WORKING, 0.4))

    def test_a_stopped_setup_says_why_and_tries_again(self):
        s = fr.tools_step(rows('NDK'), True, ('failed', 'the download does not match its sha1'))
        self.assertEqual((s.state, s.button), (fr.PROBLEM, 'Try again')); self.assertIn('does not match', s.text)

    def test_a_check_that_failed_looks_again(self):
        s = fr.tools_step([{'name': 'check', 'ok': False, 'detail': 'boom', 'fix': ''}], True)
        self.assertEqual((s.state, s.button), (fr.PROBLEM, 'Look again'))


class Phone(unittest.TestCase):
    S25 = {'serial': 'R5C0', 'state': 'device', 'name': 'Galaxy S25 Edge', 'model': 'Galaxy S25 Edge', 'android': '16'}

    def test_no_adb_points_at_the_tools(self):
        s = fr.phone_step([], False)
        self.assertEqual(s.state, fr.TODO); self.assertIn('step 2', s.text)

    def test_connected_is_done_with_its_name(self):
        s = fr.phone_step([self.S25], True)
        self.assertTrue(s.done); self.assertIn('Galaxy S25 Edge', s.text); self.assertIn('Android 16', s.text)

    def test_one_waiting_for_allow_says_what_to_tap(self):   # adb lists it with no model until it allows this PC
        s = fr.phone_step([{'serial': 'R5C0', 'state': 'unauthorized', 'model': ''}], True)
        self.assertEqual(s.state, fr.WAITING); self.assertIn('Your phone', s.text); self.assertIn('Allow', s.text)

    def test_offline_says_to_plug_it_again(self):
        s = fr.phone_step([dict(self.S25, state='offline')], True)
        self.assertEqual(s.state, fr.PROBLEM); self.assertIn('plug it back in', s.text)

    def test_one_set_up_before_stays_done_unplugged(self):   # the step can't come undone each time a phone is unplugged, or the checklist would return at every launch
        self.assertTrue(fr.phone_step([], True, seen=True).done)
        self.assertEqual(fr.phone_step([], True).state, fr.TODO)

    def test_battery_and_free_space_on_its_line(self):
        s = fr.phone_step([dict(self.S25, battery=64, charging=False, free=212 * 10**9)], True)
        self.assertIn('212 GB free · battery 64%', s.text); self.assertNotIn('⚠', s.text)

    def test_a_nearly_flat_phone_is_warned(self):   # the S25 Edge sat at 3-4% on the test PC's USB port
        s = fr.phone_step([dict(self.S25, battery=4, charging=True)], True)
        self.assertTrue(s.done); self.assertIn('⚠ Battery 4%', s.text); self.assertIn('wall charger', s.text)

    def test_the_picked_phone_first(self):
        pad = dict(self.S25, serial='PAD', name='OnePlus Pad 3')
        self.assertIn('OnePlus Pad 3', fr.phone_step([self.S25, pad], True, picked='PAD').text)


class Game(unittest.TestCase):
    BD = {'folder': 'D:/Games/BD', 'name': 'Pokémon Brilliant Diamond', 'state': 'build', 'tested': True, 'error': None}

    def test_none_yet_asks_for_a_folder(self):
        s = fr.game_step([], [], False)
        self.assertEqual((s.state, s.button), (fr.TODO, 'Add a game…'))

    def test_reading_names_the_folder(self):
        s = fr.game_step(['D:/Games/BD'], [], True)
        self.assertEqual((s.state, s.fraction), (fr.WORKING, -1)); self.assertIn('BD', s.text)

    def test_read_is_done_and_builds_next(self):
        s = fr.game_step(['D:/Games/BD'], [self.BD], False)
        self.assertTrue(s.done); self.assertEqual((s.button, s.ref), ('Build and install', 'D:/Games/BD')); self.assertIn('played on Android', s.text)

    def test_waiting_for_tools_isnt_called_unreadable(self):   # a supported game read before the tools came read as "Not supported" (droidplay-core #55)
        s = fr.game_step(['D:/Games/BD'], [dict(self.BD, state='tools')], False)
        self.assertEqual(s.state, fr.TODO); self.assertIn('once the tools are installed', s.text)

    def test_unreadable_says_why(self):
        s = fr.game_step(['D:/x'], [dict(self.BD, name='x', state='none', error='no NSP or XCI in it')], False)
        self.assertEqual(s.state, fr.PROBLEM); self.assertIn('no NSP or XCI', s.text)

    def test_names_are_escaped(self):
        self.assertIn('&lt;b&gt;', fr.game_step(['D:/x'], [dict(self.BD, name='<b>')], False).text)


class SetupBar(unittest.TestCase):   # Install tools: one bar across the parts --setup installs, rather than one per stage that starts again from nothing
    def run_events(self, *evs, t0=0.0):
        p = fr.SetupProgress(t0)
        for e in evs: p.feed(e)
        return p

    def test_a_new_pc_runs_all_four_weighted_by_size(self):
        p = self.run_events({'ev': 'stage', 'k': 1, 'n': 4, 'name': 'JDK 21'}, {'ev': 'progress', 'k': 1, 'step': 'downloading the JDK', 'done': 95 << 20, 'total': 190 << 20, 'unit': 'B'})
        self.assertEqual(p.planned(), [s[0] for s in fr.SETUP_STAGES])
        self.assertAlmostEqual(p.fraction(), 95 / 1580, places=3)
        self.assertTrue(p.text(5).startswith('Downloading Java · 95 MB of 190 MB'))

    def test_later_stages_count_what_came_before(self):
        p = self.run_events({'ev': 'stage', 'k': 1, 'n': 2, 'name': '.NET SDK 10'}, {'ev': 'stage_end', 'k': 1},
                            {'ev': 'stage', 'k': 2, 'n': 2, 'name': 'Android SDK packages'}, {'ev': 'progress', 'k': 2, 'step': 'installing ndk;28.2.13676358', 'done': 3, 'total': 5, 'unit': ''})
        self.assertEqual(p.planned(), ['.NET SDK 10', 'Android SDK packages'])
        self.assertAlmostEqual(p.fraction(), (290 + 950 * 130 / 850) / 1240, places=3)   # the NDK, most of the stage, still to come
        self.assertIn('Installing the Android SDK · the NDK (4 of 5)', p.text(5))

    def test_unplanned_stages_are_the_last_ones(self):   # a PC with the command-line tools already: n=2 after the JDK means the packages alone are left
        p = self.run_events({'ev': 'stage', 'k': 1, 'n': 2, 'name': 'JDK 21'})
        self.assertEqual(p.planned(), ['JDK 21', 'Android SDK packages'])

    def test_time_left_once_there_is_a_rate(self):
        p = self.run_events({'ev': 'stage', 'k': 1, 'n': 1, 'name': 'JDK 21'}, {'ev': 'progress', 'k': 1, 'step': 'downloading the JDK', 'done': 50, 'total': 100, 'unit': 'B'})
        self.assertNotIn('left', p.text(5))   # too soon to say
        self.assertIn('about 4 minutes left', p.text(240))
        self.assertIn('less than a minute left', p.text(40))


class Count(unittest.TestCase):
    def test_counts_the_done_steps(self):
        steps = [fr.keys_step(''), fr.tools_step(rows(), True), fr.phone_step([], True, seen=True), fr.game_step([], [], False)]
        self.assertEqual(fr.ready_count(steps), 2)



class Explain(unittest.TestCase):   # the messages as the script, nx_extract and adb print them; each gets a title, what to do and its button
    def test_phone_full_names_the_sizes(self):
        h = ex.explain('the phone has 2.1 GB free: the RomFS image needs 4.7 GB, plus 268 MB left free for Android and the app. Free up 2.9 GB on the phone, then install again',
                       phone='Galaxy S25 Edge', game='Pokémon Brilliant Diamond')
        self.assertEqual((h.title, h.action), ('Not enough space on Galaxy S25 Edge', 'retry'))
        self.assertIn('needs 4.7 GB and Galaxy S25 Edge has 2.1 GB free. Free up 2.9 GB', h.body)

    def test_a_step_that_failed_on_a_nearly_full_phone(self):   # says_when_phone_full's line under a step that printed nothing
        h = ex.explain('adb -s X shell sh /data/local/tmp/nxnative_mkdirs.sh failed (exit status 1): no output\nThe phone has only 310 MB free, which is likely why: free up space')
        self.assertTrue(h.title.startswith('Not enough space on')); self.assertIn('310 MB', h.body)

    def test_adb_no_space_is_the_phones_and_oserror_the_pcs(self):
        self.assertIn('your phone', ex.explain('adb -s X push a b failed (exit status 1): adb: error: failed to copy: No space left on device').title)
        self.assertEqual(ex.explain("[Errno 28] No space left on device: 'D:\\BD\\x'", folder='D:\\Games\\BD').title, 'Not enough space on this PC')

    def test_pc_full_names_the_drive(self):
        h = ex.explain('less than 12 GB free on the volume of D:\\Games\\BD\\0100000011D90000_build', game='Pokémon Brilliant Diamond')
        self.assertEqual((h.title, h.action), ('Not enough space on this PC', 'folder')); self.assertIn('about 12 GB free on drive D:', h.body)

    def test_unauthorized_asks_for_allow(self):
        for t in ('0 adb devices ready (R5C0 (unauthorized)): connect one, or pick it with --serial', 'adb: device unauthorized.'):
            h = ex.explain(t, phone='Galaxy S25 Edge'); self.assertEqual((h.title, h.action), ("Galaxy S25 Edge hasn't allowed this PC yet", 'phone'))

    def test_a_web_servers_401_isnt_the_phone(self):
        self.assertEqual(ex.explain('<urlopen error HTTP Error 401: Unauthorized>', setup=True).title, 'The download stopped')

    def test_offline_and_unplugged_mid_copy(self):
        for t in ("adb: device offline", "adb: error: device 'R5C0' not found", 'adb -s R5C0 push x y failed (exit status 255): no output', 'error: no devices/emulators found'):
            self.assertEqual(ex.explain(t).title, 'Your phone stopped answering', t)

    def test_no_phone(self):
        h = ex.explain('0 adb devices ready (none): connect one, or pick it with --serial')
        self.assertEqual((h.title, h.label), ('No phone connected', 'Set up my phone…'))

    def test_keys(self):
        self.assertEqual(ex.explain('give -k <prod.keys>: the game is in NSP / XCI files, which are encrypted').action, 'keys')
        h = ex.explain('[RED] BD.nsp: prod.keys has no titlekek_13 (master key 13, which came with firmware 17.0.0): the keys are older than the game; dump prod.keys again')
        self.assertEqual(h.title, 'Your keys are older than this game'); self.assertIn('firmware 17.0.0 or later', h.body)

    def test_no_ticket(self):
        h = ex.explain('BD.nsp: no title key for rights ID 0100000011d90000000000000000000d: the package has no common ticket for it')
        self.assertEqual((h.title, h.action), ("This game file can't be opened with your keys", ''))

    def test_tools_missing_isnt_called_unsupported(self):
        h = ex.explain("reading the packages' titles and versions needs dotnet (.NET SDK 10), which the extraction needs too")
        self.assertEqual((h.title, h.action), ('Install the tools first', 'tools'))

    def test_install_blocks(self):
        self.assertEqual(ex.explain('adb: failed to install x.apk: Failure [INSTALL_FAILED_USER_RESTRICTED: Install canceled by user]').title, 'Your Xiaomi phone blocked the install')
        self.assertEqual(ex.explain('the DroidPlay app (org.nxnative.android) on the phone was signed with another key than ~/.android/nxnative-debug.jks').action, 'backup')

    def test_setup_downloads(self):
        self.assertEqual(ex.explain('<urlopen error [Errno 11001] getaddrinfo failed>', setup=True).body, 'Check your internet connection, then Install tools again.')
        self.assertEqual(ex.explain('the JDK: the download does not match its sha256 (https://aka.ms/x)', setup=True).title, 'The download came through damaged')

    def test_anything_else_is_a_bug_with_the_plain_stage(self):
        h = ex.explain('patch_nso.py exit code 1 on subsdk0 (full output: x)', stage='rewrite')
        self.assertTrue(h.bug); self.assertEqual(h.title, 'The build stopped at "Adapting the game\'s code for Android"'); self.assertIn('#help', h.body)
        self.assertEqual(ex.explain('boom', stage='extract v393216').title, 'The build stopped at "Reading the game files"')
        self.assertEqual(ex.explain('boom', setup=True, stage='Android SDK packages').title, 'Installing the tools stopped at "Installing the Android SDK"')


class Report(unittest.TestCase):   # Copy report: one Discord message, home folder as ~, never key material
    INFO = {'version': '0.5.0', 'title': 'Build Pokémon Brilliant Diamond', 'stage': 'rewrite', 'k': 3, 'n': 8, 'game': 'Pokémon Brilliant Diamond',
            'game_id': '0100000011D90000', 'game_version': '393216', 'phone': 'Galaxy S25 Edge', 'android': '16', 'gpu': 'Adreno (TM) 830'}

    def test_fits_one_discord_message_however_long_the_log(self):
        log = [f'C:\\Users\\andre\\games\\step {i} ' + 'x' * 150 for i in range(400)]
        text = ex.markdown_report(self.INFO, ['[RED] patch_nso.py exit code 1 on subsdk0'] * 3 + ['[RED] ' + 'y' * 900], log, 'C:\\Users\\andre')
        self.assertLess(len(text), ex.DISCORD_LIMIT)
        self.assertIn('stopped at Adapting the game\'s code for Android (`rewrite`, stage 3 of 8)', text); self.assertIn('Adreno (TM) 830', text)
        self.assertIn('step 399', text); self.assertNotIn('andre', text)

    def test_key_lines_are_dropped(self):
        text = ex.markdown_report(self.INFO, [], ['header_key = 0123456789abcdef0123456789abcdef0123456789abcdef', 'fine'], '/home/p')
        self.assertNotIn('0123456789abcdef', text); self.assertIn('fine', text)

    def test_the_phones_serial_stays_out(self):
        text = ex.markdown_report(self.INFO, ['[RED] adb -s R5CY00000XX push a b failed (exit status 255): no output'], ['$ python b.py D:/BD -k k --serial R5CY00000XX'], '/home/p')
        self.assertNotIn('R5CY00000XX', text); self.assertIn('adb -s <serial> push', text); self.assertIn('--serial <serial>', text)

    def test_forward_slashed_home_is_redacted_too(self):
        self.assertNotIn('andre', ex.full_report(self.INFO, 'C:/Users/andre/x.log failed', 'C:\\Users\\andre\\j.jsonl', 'C:\\Users\\andre'))



class Guide(unittest.TestCase):   # PhoneGuide: the brand picked from what adb says, and the battery and space read in the same shell call
    def test_brand_from_the_manufacturer(self):
        for maker, model, want in (('samsung', 'SM-S937U1', 'samsung'), ('Google', 'Pixel 9', 'pixel'), ('Xiaomi', 'Redmi Note 10 Pro', 'xiaomi'),
                                   ('OnePlus', 'OPD2415', 'oneplus'), ('AYN', 'Odin2', 'handheld'), ('Moorechip', 'Retroid Pocket 5', 'handheld'), ('motorola', 'edge', 'other')):
            self.assertEqual(pg.brand_for(maker, model), want, maker)

    def test_a_phone_waiting_for_allow_has_only_its_model(self):   # devices -l's: a Galaxy's model code still says Samsung
        self.assertEqual(pg.brand_for('', 'SM_S937U1'), 'samsung'); self.assertEqual(pg.brand_for('', ''), 'other')

    def test_every_brand_ends_with_plugging_in(self):
        self.assertEqual({k for k, *_ in pg.BRANDS}, {'samsung', 'pixel', 'xiaomi', 'oneplus', 'handheld', 'other'})
        self.assertTrue(all(steps[-1] == pg.PLUG for _, _, steps, _ in pg.BRANDS))

    def test_battery_and_space_from_one_shell_call(self):   # a OnePlus Pad 3 on a Mac's USB port, as it printed them
        text = ('  AC powered: false\n  USB powered: true\n  Wireless powered: false\n  Dock powered: false\n  status: 4\n  level: 80\n'
                '/dev/fuse      233949316 153851140  79967104  66% /storage/emulated\n')
        self.assertEqual(pg.parse_status(text), {'battery': 80, 'charging': False, 'free': 79967104 * 1024})
        self.assertEqual(pg.parse_status(''), {})

    def test_warning_below_20_percent(self):
        self.assertEqual(pg.battery_warning({'battery': 20}), '')
        self.assertIn('wall charger', pg.battery_warning({'battery': 12, 'charging': False}))
        self.assertIn("it's charging", pg.battery_warning({'battery': 15, 'charging': True}))


if __name__ == '__main__':
    unittest.main()


class PhoneGpu(unittest.TestCase):   # the Phones page's GPU column (phone_gpu.py): which drivers can run on a phone is a matter of its GPU
    def test_the_gles_line_names_the_renderer(self):
        self.assertEqual(gpu.gles_renderer('GLES: Qualcomm, Adreno (TM) 830, OpenGL ES 3.2 V@0800.0 (GIT@1a2b, I0123) (Date:01/01/26)\n'), 'Adreno (TM) 830')
        self.assertEqual(gpu.gles_renderer('GLES: ARM, Mali-G715, OpenGL ES 3.2 v1.r47p0-01eac0'), 'Mali-G715')
        self.assertEqual(gpu.gles_renderer(''), '')

    def test_adreno_by_number_mali_xclipse_by_name(self):
        self.assertEqual(gpu.classify('Adreno (TM) 650'), {'kind': 'adreno', 'adreno': 650, 'label': 'Adreno 650'})
        self.assertEqual(gpu.classify('Adreno (TM) 840', 'adreno', 'SM8850')['adreno'], 840)
        self.assertEqual(gpu.classify('Mali-G715')['label'], 'Mali-G715')
        self.assertEqual(gpu.classify('Samsung Xclipse 950')['kind'], 'xclipse')
        self.assertEqual(gpu.classify('PowerVR Rogue GE8320')['kind'], 'powervr')

    def test_without_a_renderer_the_properties_decide(self):
        self.assertEqual(gpu.classify('', 'adreno', ''), {'kind': 'adreno', 'adreno': None, 'label': 'Adreno'})
        self.assertEqual(gpu.classify('', '', 'SM8475')['kind'], 'adreno')
        self.assertEqual(gpu.classify('', '', 'SC9863A')['kind'], 'unknown')   # Unisoc's, not Qualcomm's
        self.assertEqual(gpu.classify('', 'mali', 'Tensor G4')['kind'], 'mali')
        self.assertEqual(gpu.classify('', 'samsung', 's5e9955'), {'kind': 'xclipse', 'adreno': None, 'label': 'Xclipse'})   # a Galaxy Z Flip 7: no GLES line at all
        self.assertEqual(gpu.classify('Some GPU')['kind'], 'other')


class VkCatalog(unittest.TestCase):   # the Vulkan driver catalog (dm/android/vk_drivers.json) and the desktop app's side of it (vk_drivers.py)
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.cat = {e['id']: e for e in vkd.load()}

    def test_the_catalog_reads_and_pins_both_hashes(self):
        t30 = self.cat['turnip-mrpurple-t30']
        self.assertEqual(t30['zip_sha256'][:8], 'f65b2d33'); self.assertEqual(t30['library_sha256'][:8], '1d80dfa0')   # the package DroidPlay tested
        for e in self.cat.values():
            for r in e['tested']: self.assertTrue(vkd.in_ranges(r['gpu'], e['gpus']), f'{e["id"]} tested on the {r["gpu"]}, which its gpus leave out')

    def test_marks_against_a_phone(self):
        t30, faux = self.cat['turnip-mrpurple-t30'], self.cat['turnip-faux123-1.2.10']
        m = vkd.mark(t30, gpu.classify('Adreno (TM) 650'), '33', '0100000011D90000')
        self.assertEqual(m['kind'], vkd.TESTED); self.assertIn('Brilliant Diamond', m['rows'][0][1])   # this game's run first
        self.assertEqual(vkd.mark(t30, gpu.classify('Adreno (TM) 722'))['kind'], vkd.OTHER_GPU)   # T30 dropped the 710/720 family
        self.assertEqual(vkd.mark(faux, gpu.classify('Adreno (TM) 722'))['kind'], vkd.SUPPORTED)
        self.assertEqual(vkd.mark(t30, gpu.classify('Mali-G715'))['kind'], vkd.NOT_ADRENO)
        self.assertEqual(vkd.mark(t30, gpu.classify('', 'adreno'))['kind'], vkd.UNKNOWN)
        self.assertIn('API 30', vkd.mark(t30, gpu.classify('Adreno (TM) 650'), '29')['warn'])
        self.assertIn("doesn't have", vkd.mesh_note(t30)); self.assertIn("isn't known", vkd.mesh_note(self.cat['turnip-stevenmxz-gen8-v39']))

    def test_a_bad_catalog_is_refused(self):
        bad = json.loads(vkd.CATALOG.read_text()); bad['drivers'][0]['env'] = ['DM_VK_RAW_GMEM=1']
        f = self.tmp / 'c.json'; f.write_text(json.dumps(bad))
        with self.assertRaises(ValueError): vkd.load(f)

    def serve(self, files):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = files.get(self.path)
                self.send_response(200 if body is not None else 404); self.send_header('Content-Length', str(len(body or b''))); self.end_headers(); self.wfile.write(body or b'')
            def log_message(self, *a): pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start(); self.addCleanup(server.server_close); self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_address[1]}'

    def entry(self, base, data, lib=None):
        lib = elf() if lib is None else lib
        return {'id': 'test-driver', 'name': 'Test driver', 'url': base + '/turnip.adpkg.zip', 'zip_sha256': hashlib.sha256(data).hexdigest(), 'size': len(data),
                'library': 'vulkan.purple.so', 'library_sha256': hashlib.sha256(lib).hexdigest(), 'library_size': len(lib)}

    def test_download_checked_by_both_hashes(self):
        data = make_pkg(self.tmp).read_bytes(); base = self.serve({'/turnip.adpkg.zip': data}); e = self.entry(base, data)
        f = vkd.download(e, self.tmp / 'dl')
        self.assertEqual(f.read_bytes(), data); self.assertEqual(vkd.cached(e, self.tmp / 'dl'), f)
        other = make_pkg(self.tmp, 'other.zip', data=elf(pad=64)).read_bytes()   # same name, another driver: the zip's hash refuses it
        base2 = self.serve({'/turnip.adpkg.zip': other})
        with self.assertRaises(ValueError): vkd.download(self.entry(base2, data), self.tmp / 'dl2')
        self.assertFalse(any((self.tmp / 'dl2').rglob('*.zip*')))
        e3 = self.entry(base2, other, lib=elf())   # the zip as pinned, but the driver inside isn't the one the catalog names
        with self.assertRaises(ValueError): vkd.download(e3, self.tmp / 'dl3')
        with self.assertRaises(vkd.Cancelled): vkd.download(self.entry(base, data), self.tmp / 'dl4', cancelled=lambda: True)

    def test_a_players_own_driver_is_checked_and_kept(self):
        r = vkd.import_custom(make_pkg(self.tmp), self.tmp / 'drivers')
        self.assertEqual(r['id'], 'custom-' + hashlib.sha256(elf()).hexdigest()[:8]); self.assertFalse(r['proprietary'])
        self.assertTrue(Path(r['file']).is_file())
        meta = {'schemaVersion': 1, 'name': 'Q', 'description': '', 'author': 'Q', 'packageVersion': '1', 'vendor': 'Qualcomm', 'driverVersion': '891', 'minApi': 33,
                'libraryName': 'vulkan.adreno.so'}
        self.assertTrue(vkd.import_custom(make_pkg(self.tmp, 'q.zip', 'vulkan.adreno.so', meta=meta), self.tmp / 'drivers')['proprietary'])
        so = self.tmp / 'not.so'; so.write_bytes(elf(needed=('libc.so.6',)))
        with self.assertRaises(vkd.vkpkg.PackageError): vkd.import_custom(so, self.tmp / 'drivers')

    def test_the_weekly_check_names_a_changed_or_gone_asset(self):
        e = self.cat['turnip-faux123-1.2.10']; name = e['url'].rsplit('/', 1)[1]
        rel = lambda digest, n=name: {'assets': [{'name': n, 'size': e['size'], 'digest': digest}]}   # noqa: E731
        self.assertEqual(vk_catalog.check([e], lambda url: rel(f'sha256:{e["zip_sha256"]}')), [])
        self.assertIn('has changed', vk_catalog.check([e], lambda url: rel('sha256:' + '0' * 64))[0])
        self.assertIn('no longer', vk_catalog.check([e], lambda url: rel('x', 'other.zip'))[0])

    def test_a_report_names_the_driver_and_its_last_start(self):   # every "it doesn't work on Turnip" report needs the driver named
        h = ex.header({'version': '0.8.0', 'phone': 'Odin2', 'android': '13', 'gpu': 'Adreno (TM) 740', 'vk_driver': 'Mr. Purple Turnip T30', 'vk_result': 'fell back no Vulkan device'})
        self.assertIn('Vulkan driver: Mr. Purple Turnip T30 (last start: fell back no Vulkan device)', h)
        self.assertFalse(any('Vulkan driver' in x for x in ex.header({'phone': 'Odin2'})))
