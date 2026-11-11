# Pokémon Shield (`01008DB008C2C000`)

Update 1.3.2 (`v458752`) over the base game, SDK 7.3.2. Pokémon Sword's twin ([0100ABF008968000](../0100ABF008968000/README.md)): the same engine, and the same `sdk`, `subsdk0` (movie) and `subsdk1` (GLSLC) builds; only `main` is a build of its own (`a1680262…`, Sword's is `a3b75bcd…`). Everything in Sword's note about the engine, its services, files, shaders and rendering holds here; this note gives only what differs or was checked again. The profile is Sword's with Shield's title, name, IPA name, build row and shader tables. Plays on the iPhone (IPA 12.4 GB, user, 2026-10-26) and on the Mac at 30 fps, as on the Switch, and on Android at 30 fps too ([Android](#android)).

## What it needs

The same keys as Sword's profile, for the same reasons ([Sword, What it needs](../0100ABF008968000/README.md#what-it-needs)): the 4 GB layout with a 3.13 GB heap (`main.npdm` declares no system resource either), `mem_used 0x4c00000`, `pad_layout full`. The node area cut and the alignment of large regions come with the `sdk` build (`fcf93a41…`, `dm/tools/sdk_patches.py`). No host code is keyed to either game's `main`.

No `patches.py`.

## Files and shaders

- The RomFS has the same layout as Sword's (GFPAK archives under `bin/archive`, Wwise banks, loose BNSH files); `bin/sound/NX64/wwise/bank/Stream.pck` is the `romfs_marker` again.
- Shaders: 41,516, the same as Sword's. The split's three tables have the same data rows byte for byte (the game's own shaders, the GFPAK and loose BNSH files, and YEBIS's `.tfxo` stream in `main`, at the same offset); only the map's header note differs. The prewarm list is Sword's (it names shaders by content key).
- Each shader's cache key covers the profile's `shader_*` keys, so Shield's build does not hit Sword's cache entries; with `DMSH_PREFILL` naming Sword's library roots, the Metal compile cache takes Sword's libraries and only the translation runs again (the Mac build: 21,974 filled from Sword's, 45,728 reused, 176 compiled; 15 minutes for the 41,516; the iOS build: 21,684 filled, 175 compiled). IPA 12.4 GB.

## Performance

- On the Mac: 30 fps as on the Switch (frame time p50 33.3 ms, p95 34–35 ms in the house and outside in Postwick), no red line in 10 minutes from a fresh save.

## Mac routes

- The work folder's `run/boot.sh`, `run/ctl.sh` and `run/step.sh` are Sword's, run headless as there; `run/mash.sh <prefix> <rounds>` presses A ten times a round and takes a screenshot after each.
- From a fresh save (`DM_KBD` answers the name; without it the keyboard counts as cancelled and the game goes back to the photo), A at the language (about frame 600), the photo and the name reach the opening; A presses lead through it to the living room in Postwick, and the stairs to the bedroom with the Bag.
- `run/save_ref` is a save in the bedroom with the Bag taken, the same place as Sword's: Sword's route out of the front door (`LDown~0.8 LLeft~2.5 LRight~0.5 LDown~2.5 LLeft~0.3 LDown~2`, `run/route_out.sh`) works unchanged.
- The route checked on the Mac: the first boot's language, photo and name choices, the opening (the Champion's broadcast, the stadium), Postwick (the house, Hop's visit, the bedroom and the Bag), a save, and out of the front door to Hop.

## Android

First run on Android, 2026-11-10: a Samsung Galaxy S25 Edge (SM-S937U1: Snapdragon 8 Elite for Galaxy, Adreno 830 with Samsung's driver 0x80320001 and Vulkan 1.3.284, Android 16), DroidPlay Core `main` at `4743c9da`, handheld (720p), the on-screen controls. Packed with `build_android_from_nsp.py` from a cartridge dump: the XCI carries the base game and update 1.3.2 (v458752), so the build is this profile's own, not a derived one. All 41,516 shaders translated, none failed (9 min 53 s on the Mac).

- **Plays from a new game into Postwick**, with nothing wrong seen in the picture, no crash and no hang: the language, the photo and the name (`DM_KBD` answers it; without it the app's text box opens), the opening (the video site, Chairman Rose's broadcast in the stadium), the living room, the Bag in the bedroom, the X menu and a save, out of the front door, Hop and his Wooloo, and the town (the bridge, the river, the windmill). On the next start, the title screen and Continue, which loaded the autosave the game had made after the manual save.
- **30 fps throughout, as on the Switch:** frame p50 33.3 ms, p95 35–38 ms. GPU p50: the menus 5.3 ms (route `boot`, the language menu: 30.0 fps, frame p95 34.7 ms), the stadium 15–16 ms, the house 13–16 ms, walking in Postwick 23–25 ms, so about 8 ms to spare outdoors. `bench_android.tsv` route `postwick` (Continue from `saves/bedroom` beside the NSP folder, a save made on the phone where the Mac's `run/save_ref` is, then Sword's walk out of the front door; Postwick loads at 37.4 s, then 30 s standing outside the house), two runs on the warm pipeline cache: 30.0 fps, frame p50 33.2–33.3 / p95 36.9–37.1 / max 40.8 ms, GPU p50 20.7 / p95 21.8 ms, about 1,140 draws a frame, PSS 2.3 GB.
- **First start:** pipelines are built in the background. 2,570 draws were left out while theirs were built, over the first 17 minutes; the longest frame was 2.3 s, the first step outside. The driver's pipeline cache (7.8 MB after that run) leaves out 2 on the next start.
- **Sound:** AudioOut #0 (6 channels, `main+0x3a60d0`) on AAudio at 48 kHz stereo. `DM_AUDIO_DUMP` has the title and town music in the first two channels, the other four silent; no underrun in 34 reports.
- **Saves:** the manual save and the autosave committed (`save commit #1`, `#2`) and loaded again.
- **One `[RED]` line**, once at boot: `a second NVN queue submits: the Vulkan replay shares one state between queues` (the replay keeps one state for every NVN queue, `gfx_vk.c` `mtl_queue_activate`). Nothing in the picture showed it.

**Through the first battle on a Retroid Pocket 5**, 2026-11-10: SM8250, Adreno 650 with Qualcomm's driver 0x802ea000 and Vulkan 1.1.128, Android 13. DroidPlay Core `main` at `898ac92f`, handheld (720p), the built-in controls. The same build folder (no shader translated again). Played by hand with adb input, about 36 minutes from a new game:

- **The stretch:**
  - the opening and the Bag;
  - Hop and the race to his house, where his mum sends them to meet Leon;
  - Route 1, and Wedgehurst station, where Leon and Charizard arrive among the fans;
  - back in Hop's garden, Leon's three starters (Scorbunny taken; its nickname box answered by `DM_KBD` as well), and dinner;
  - the next day, **Hop's battle**: his Wooloo (Lv 3) and Grookey (Lv 5) against Scorbunny (Lv 5) with Tackle. Won; Scorbunny went up to Lv 6 and learned Ember.

  Then a save, and a cold start: the title and Continue loaded it in Hop's garden. Nothing wrong was seen in the picture (battle scenes, HP bars, menus, the level-up panel), and there was no crash and no hang.
- **30 fps throughout:** 218 windows of 300 frames, frame p50 33.0–34.5 ms (median 33.3), p95 median 36.5 / max 40.4 ms. GPU p50 median 19.5 ms, the most 27.2 ms (outdoors, Wedgehurst). Battles: GPU 14–17 ms.
- **First start:** the longest frames are pipelines and shader libraries made in the frame, as on the S25 Edge but longer on this GPU:
  - 5.0 s at the first step outside (245 pipelines and 481 libraries, 4.3 s of it);
  - 1.7 s in the opening;
  - 1.2 s as the battle starts.

  25 of the 218 windows had a frame over 100 ms. With the pipeline cache (10.8 MB after the run), the Continue start's longest frame was 178 ms.
- **Sound:** `DM_AUDIO_DUMP` over the Continue start (82 s): the title and town music in the first two channels; no underrun in 291 reports.
- **Saves:** three commits (two manual saves and the game's autosave), and the last was loaded again.
- **`[RED]`:** the same single line as on the S25 Edge.
- **Installing:** the Retroid Pocket 5 unpacks the 101,375 shader files at about 13–32 a second (per-file kernel time), so the first install took 1 h 32 min. Shield takes about 15 GB there.
- **Not tried:** the Wild Area, docked mode, the Ayn Odin 2 and the OnePlus Pad 3 (it was installed on both on 2026-11-09, with no result written down).
