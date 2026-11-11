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

**On a Google Pixel 9 Pro XL**, 2026-11-10: Tensor G4, Mali-G715 with Arm's driver 0xd803000 and Vulkan 1.4.343, Android 17. The hosts from `main` at `898ac92f`, the game files from the same build folder; handheld (720p), the on-screen controls, played by hand with adb input from a new game:

- **The stretch:** the language, the photo and the name (`DM_KBD`), Rose's broadcast and Leon's match, the living room and Hop with Wooloo, the Bag in the bedroom and its scene, a save from the X menu, then out of the front door to Hop on the path in Postwick. Nothing wrong was seen in the picture (the spots compared with the S25 Edge's shots of them), and there was no crash and no hang.
- **30 fps, as on the Switch:** 29.5–30.1 fps per 30 s in the house, GPU p50 16–18 ms; walking in Postwick 29.8 fps, frame p50 33.2 / p95 39.9 ms, GPU p50 22.2 / p95 27.5 ms.
- **First start:** 934 pipelines were built in 18.7 s, with 4,089 draws left out meanwhile; the first step outside took one 4.6 s frame. The Mali-G715 has no BC textures, so they are decoded on the CPU.
- **Saves:** the X menu's save committed (`save commit #1`), and after a restart the title's Continue loaded it in the bedroom.
- **Sound:** `DM_AUDIO_DUMP` over the title and the bedroom (59 s): the front pair at −22.5 / −23.2 dBFS RMS, peaks −3 / −2 dBFS; the other four channels silent, as on the S25 Edge.
- **`[RED]`:** the same single line.
- **Not tried:** a battle, the Wild Area.

**On a Samsung Galaxy Z Flip 7**, 2026-11-10: Exynos 2500, Xclipse 950 with Samsung's driver 0x6000215 and Vulkan 1.3.279, Android 16, open, on its inner screen. The hosts from `main` at `898ac92f`, the game files from the same build folder; the on-screen controls, played by hand with adb input from a new game:

- **The stretch:** the language, the look and the name (`DM_KBD`), the stadium opening with Chairman Rose, Postwick's Wooloo scene and Hop's talk, then walking in the house.
- **30 fps, as on the Switch:** 29.7 fps over the 7.7-minute first launch, 30.0 walking; frame p50 33.4 ms, p95 37.9–39.9 ms; GPU p50 10.5–11.8 ms.
- **Saves:** the X menu's save committed (`save commit #1`), and after a restart Continue loaded it where it was made.
- **Sound:** an audio dump of the title and the house: the front pair at −22 / −23 dBFS RMS, peaks to −2 dBFS; no underrun in 266,000 callbacks.
- **`[RED]`:** the same single line.
- **Not tried:** outside the house, the Bag, a battle.

**Past the first battle on the Z Flip 7**, the same day (job q78): main's Shield host at `5736949c` (the files were unchanged from the run above), the same phone and controls. Played by hand with adb input, 43 minutes from a new game, along the Retroid Pocket 5's route:

- **The stretch:**
  - Postwick, Route 1, Wedgehurst station and Leon's starters (Scorbunny);
  - **Hop's battle**: Wooloo, then Grookey, finished with Ember. Won; Scorbunny went up to Lv 7;
  - the next part of the story: Hop hears the Wooloo break through the gate, and the two follow it into the **Slumbering Weald**, where a wild Skwovet (Lv 2) is beaten in the fog.

  The Weald's paths through the fog kept the walk to its first stretch: blind stick moves kept meeting trees and rocks, so the Weald's event and Route 2 were not reached.
- **Saves and Continue:** four commits (manual saves and an autosave), the last in the Weald (play time 0:38). A cold start's title and Continue loaded it there.
- **30 fps throughout:** 257 windows of 300 frames, frame p50 33.0–33.9 ms (median 33.4), p95 median 37.3 ms. GPU p50 median 14.2 ms, the most 22.1.
- **First start:** the longest frame was 6.4 s at the first step outside. 245 pipelines and 298 libraries were made in that frame (5.7 s), on Samsung's slow first-time shader creation. 1.2–1.3 s frames came at two later loads. With the pipeline cache (6.5 MB), the Continue start's longest frame was 118 ms.
- **Sound:** `DM_AUDIO_DUMP` over the Continue start (95 s): the title music, then the Weald's, in the front pair. No underrun in 647 reports during play and 22 after the restart.
- **`[RED]`:** the same single line; no crash, no hang, nothing wrong seen in the picture (the battle scenes, the Weald's fog).

**Through the Slumbering Weald on the Retroid Pocket 5**, the same day (job q105). The phone's own APK (main `5736949c`, 0.7.3-16-g5736949c), started from the Z Flip 7's Weald save (`saves/slumbering_weald`, a save made on an Android phone). Played by hand with adb input, 29 minutes.

- **The stretch:**
  - The Weald in the fog: a wild Rookidee and a wild Skwovet beaten on the way. The fog thickens until Hop can't see his own hand.
  - **The Weald's event:** Zamazenta's silhouette in the fog, then the battle against "???". Its turns end in the fog, as the story has it. Leon and Charizard find the two, with the Wooloo.
  - Back in Postwick: Hop sends the player home, and Mum's scene plays in the kitchen. The next objective is Wedgehurst.
- **Through the fog with adb:** a short run (B held) in each direction, kept when the next screenshot changed. The depths are west: runs west, then north up a sunken path, reached the event. Hop following can make a blocked run look like a move.
- **Saves and Continue:** six commits:
  - the X menu's save after the Weald (its "Current time" is the real date and time);
  - the game's autosave after Mum;
  - a save in Hop's garden (play time 1:06).

  A cold start's Continue loaded the last one there. Kept as `saves/after_weald_rp5`.
- **30 fps throughout:** 172 windows of 300 frames, frame p50 33.0–34.5 ms (median 33.3), p95 median 36.3 ms. GPU p50 median 19.1 ms, at most 27.2, on the Adreno 650.
- **Sound:** `DM_AUDIO_DUMP` over the Continue start (105 s, one 6-channel output): the title and Postwick's music in the front pair, at −22 to −31 dBFS RMS. Peaks on notes (440 / 880 Hz, 659 Hz), no clipping. No underrun during play; one 12 ms gap during the Continue start.
- **`[RED]`:** the same single line; no crash, no hang.
- **Not played:** Route 2, Professor Magnolia's house, the Wild Area.
