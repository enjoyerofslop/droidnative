# Pokémon: Let's Go, Pikachu! (`010003F003A34000`)

The base game 1.0.0 (v0, no update), SDK **5.4.150** (`nnSdk-5_4_150`, `NintendoSDK_NVN-5_4_150`). Game Freak's engine before Sword and Shield's, on NVN, with Wwise sound and NEX networking. Modules `main`, `subsdk0` (GLSLC), `subsdk1` (`NintendoSDK_movie`) and `sdk`. The RomFS holds 27,818 files in 4.1 GB.

- **On Android:** plays at 30 fps (as on the Switch) from a new game through the opening into Pallet Town on a Galaxy Z Fold 8, with saves and Continue working. See [Android](#android).
- **On the Mac:** not run yet.

## What it needs

| Setting | Where | Why |
|---|---|---|
| `modules main subsdk0 subsdk1 sdk` | [`game.tsv`](game.tsv) | every module `main` imports from |
| `sys_resource 0x0`, `mem_reserve 0x100000000`, `mem_alias 0x10000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000` | [`game.tsv`](game.tsv) | the NPDM declares no system resource, so no virtual address memory. `main` sets a heap of at most the pool − 64 MB |
| `shader_groups /bin/=bin /system_resource/=systemresource` | [`game.tsv`](game.tsv) | the shaders are under `bin/` and `system_resource/shader`. See [Shaders](#shaders) |
| `zip_store .arc:.bfotf:.gfpak:.ptcl:.webm:.metallib` | [`game.tsv`](game.tsv) | already-compressed archives, fonts, effects and movies |

The profile is the provisional one `build_android_from_nsp.py` made from the survey (`dm/games/profile_guess.py`), unchanged but for its comments. `pso_manifest.tsv` is still the empty provisional list.

## Shaders

- **Where:** 11,160 shaders (4,710 vertex, 6,411 pixel, 39 compute), found by `shader_split.py`:
  - 5,864 in the effect files (`.ptcl`);
  - 2,770 in BNSH data inside `main`;
  - 2,117 in GFPAK archives (`gfpak_members`);
  - 395 in loose `.bnsh_vsh`, `.bnsh_fsh` and `.bnsh` files;
  - 14 in SARC (`.arc`) archives.
- **Android, current:** all 11,160 translate for Vulkan, none fail (`main` at `61eb7c31`).
- **Mac:** not built yet.

## Android

First run on Android, 2026-11-10: a Galaxy Z Fold 8 (SM-F971U1: Snapdragon 8 Elite Gen 5, Adreno 840 with Qualcomm's driver 0x8034a013, Android 17), folded, on its cover screen, with the on-screen controls. DroidPlay Core `main` at `61eb7c31` (0.7.2), packed and installed with `build_android_from_nsp.py`. Five launches, about 14 minutes in all.

- **Plays from a new game into Pallet Town**, with nothing wrong seen in the picture, no crash and no hang:
  - the controller screen, the opening movie, Professor Oak's introduction and choosing the player's look;
  - the names (`DM_KBD` answers both the player's and the rival's);
  - the bedroom, where the rival comes up the stairs;
  - downstairs past Mom, and out of the front door into Pallet Town.
- **A save:** the X menu's Save, then "Save your progress", commits (`save commit #1`) and shows "You saved your progress!". After a restart the title offers "Continue your adventure" with the trainer card's name and play time, and the game goes on where it was saved: in the bedroom, and outside the house from a save made there.
- **30 fps throughout, as on the Switch:**
  - the bedroom: frame p50 33.3 ms, p95 35.7 ms, GPU 5.7 ms;
  - the opening's 3D scenes: GPU up to 12.6 ms (15 s means);
  - walking in Pallet Town: frame p50 33.4 ms, p95 39.3 ms, p99 41.4 ms, max 43.1 ms, GPU 15.2–15.5 ms.
- **Starting:** the first frame comes about 0.4 s after the host starts, and the controller screen is up within 10 s. With a save, the Game Freak and Pokémon logos and the title screen come next; without one, the game goes straight into the opening.
- **Sound:** Wwise opens its 10 banks (`Init.bnk`, `System_Common.bnk` and the others in `bin/sound/NX64/wwise/bank`) and streams its `.wem` music, on AAudio at 48 kHz stereo with no underrun.
  - It asks for an `English(US)` copy of each bank first, which the RomFS doesn't have: Wwise's localized lookup, not an error.
  - Not checked by ear or with `DM_AUDIO_DUMP`.
- **Two `[RED]` lines,** each kind at boot only:
  - `more than 16 font engines with a small work buffer: this one keeps the game's`, 5 times. The game makes 21 `nn::fontll` engines with small work buffers, and `hle_sdk16.c` gives host memory to 16. Every text seen drew.
  - `a second NVN queue submits: the Vulkan replay shares one state between queues`, as in Pokémon Shield. Nothing in the picture showed it.
- **Driving it over adb:** the on-screen buttons need a held touch (`input swipe x y x y 150`), since a plain `input tap` is shorter than one 30 fps frame and is sometimes missed. In the X menu, the ▶ cursor is moved onto SAVE with the stick; SAVE's highlight alone doesn't select it.
- **Not tried:** Route 1 (Professor Oak and the Pikachu event), a battle or a catch (the throw uses motion), docked mode, the other devices and the Mac.
