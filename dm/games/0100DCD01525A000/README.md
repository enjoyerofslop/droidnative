# Persona 3 Portable (`0100DCD01525A000`)

Update 1.0.2 (`v131072`), SDK **14.3.0** (`NintendoSdk_nnSdk-14_3_0`, `NintendoSDK_NVN-14_3_0`). Atlus's in-house engine with CRI middleware (CRIWARE), on NVN: the same engine as [Persona 4 Golden](../010062B01525C000/README.md), whose `subsdk0` and `sdk` it shares byte for byte. Modules `main`, `subsdk0` (`NintendoSDK_movie`) and `sdk`. The RomFS holds 11 CPK files in 7.09 GB.

- **On Android:** plays at 60 fps (as on the Switch) from a new game through the opening and the first two school days, to April 8's Dark Hour, on a Galaxy S25 Edge, with saves and Continue working, in Console mode. See [Android](#android).
- **On the Mac:** not run yet.

## What it needs

| Setting | Where | Why |
|---|---|---|
| `modules main subsdk0 sdk` | [`game.tsv`](game.tsv) | every module `main` imports from |
| `sys_resource 0x0`, `mem_reserve 0x100000000`, `mem_alias 0x10000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000` | [`game.tsv`](game.tsv) | the NPDM declares no system resource, so no virtual address memory. `main` sets a heap of at most the pool − 64 MB − its 148 MB of bss |
| `romfs_marker data/umd0.cpk`, `zip_store .cpk:.metallib` | [`game.tsv`](game.tsv) | the RomFS is CPK archives: `data/` (6.26 GB), one `data_XX/` per language and the small `sysdat.cpk` at the root |
| Console mode (`DM_OPMODE=1`) | the game's settings on the phone | see [Android](#android): in Android's default handheld mode the game's menus don't take the buttons |

## Shaders

- **Where:** 30 shaders (12 vertex, 17 pixel, 1 geometry), all BNSH entries under `sysdat.cpk/shaders` (`P4G/`, `system/` and `system/posteffect/hdr/`), found by `shader_split.py`. The survey's `shader_groups` names the `data*` folders, so the split puts them all in its `other` packages; [Persona 4 Golden](../010062B01525C000/README.md)'s `shader_groups /sysdat.cpk/=sysdat` would name them better, untested here.
- **Android, current:** all 30 translate for Vulkan, none fail (`main` at `30215723`).
- **Mac:** not built yet.

## Android

First run on Android, 2026-11-10: a Galaxy S25 Edge (SM-S937U1: Snapdragon 8 Elite, Adreno 830 with Qualcomm's driver, Vulkan 1.3.284, Android 16), with the on-screen controls. DroidPlay Core `main` at `30215723` (0.7.2), packed and installed with `build_android_from_nsp.py`. Four launches, about 70 minutes in all.

- **Plays from a new game to April 8's Dark Hour**, with nothing wrong seen in the picture, no crash and no hang:
  - the opening movie, the title, a new game (male protagonist, Beginner);
  - the prologue's arrival at the dorm and the name entry (the game's own keyboard, driven with the buttons; `DM_KBD` answers only the system keyboard);
  - the protagonist's room, the first point-and-click exploration (its cursor and hotspots), and bed;
  - April 7 at Gekkoukan High: the train, the main lobby and the Faculty Office hallway (the Y button's "Where do you want to go?" list), the Faculty Office, the opening ceremony and the classroom after school;
  - back at the dorm in the evening, and the lounge;
  - after Continue: bed, the calendar, April 8 (the class's question, after school, the Chairman's visit to the dorm and his questions), and that night's Dark Hour cutscenes.
- **A save:** the lounge's Sign-In Sheet → Save, into slot 1, commits (`save commit #3`) and shows "Save complete." with 4/7 (Tu) Evening, Dorm, 0h 40m. After a restart the title loads it, and the game goes on in the dorm lounge, the cursor still on the Sign-In Sheet.
- **60 fps throughout, as on the Switch:** in all 638 of the logs' 300-frame windows over the two long launches (191,400 frames, 53 minutes), the frame time's median is 16.64–16.77 ms. p95 median 17.7 ms (worst window 22.2 ms); GPU p50 about 6 ms, 9.7 ms at most. The game process holds about 0.94 GB resident (RSS) on April 8.
- **Sound:** CRI's sound plays on AAudio at 48 kHz stereo with no underrun. A `DM_AUDIO_DUMP` of the boot holds the opening movie's song.
- **One `[RED]` line,** in the first long launch only, about four minutes in (frame 15,600, during the new game's opening): `[vk] storage buffer of shader 1f8fd67ad5e3e355 (c0 +0x120) is not a bound buffer: it reads 0`. The shader is `system/custom_Prim3D_Flat_vert.bnsh`. Nothing in the picture showed it.
- **Console mode is needed.** Android starts every game in handheld mode (`front_android.c`), where player 1 is the Handheld controller. In that mode the game's menus didn't respond to the on-screen buttons; with Console mode (`DM_OPMODE=1`, player 1 the full-key controller No1) everything did. Why the game doesn't read the Handheld controller isn't known yet.
- **Driving it over adb:** the on-screen buttons need a held touch (`input swipe x y x y 150`). In the point-and-click areas, the D-pad moves the cursor (holding it moves it fast), a hotspot names itself at the bottom right when the cursor is on it, and Y lists the area's exits.
- **Not tried:** the first battle (the night of April 9), Tartarus, the female protagonist, handheld mode's cause, the other devices and the Mac.
