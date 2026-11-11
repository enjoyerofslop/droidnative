# Pokémon: Let's Go, Pikachu! (`010003F003A34000`)

The base game 1.0.0 (v0, no update), SDK **5.4.150** (`nnSdk-5_4_150`, `NintendoSDK_NVN-5_4_150`). Game Freak's engine before Sword and Shield's, on NVN, with Wwise sound and NEX networking. Modules `main`, `subsdk0` (GLSLC), `subsdk1` (`NintendoSDK_movie`) and `sdk`. The RomFS holds 27,818 files in 4.1 GB.

- **On Android:** plays at 30 fps (as on the Switch) on a Galaxy Z Fold 8, from a new game through Pallet Town and Professor Oak's lab to Route 1, with Pikachu and the first catches made with buttons. Saves and Continue work. No trainer battle reached yet. See [Android](#android).
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

First run on Android, 2026-11-10: a Galaxy Z Fold 8 (SM-F971U1: Snapdragon 8 Elite Gen 5, Adreno 840 with Qualcomm's driver 0x8034a013, Android 17), folded, on its cover screen, with the on-screen controls. DroidPlay Core `main` at `61eb7c31` (0.7.2), packed and installed with `build_android_from_nsp.py`. Seven launches, about 40 minutes in all, the longest 24 minutes.

- **Plays from a new game into Pallet Town**, with nothing wrong seen in the picture, no crash and no hang:
  - the controller screen, the opening movie, Professor Oak's introduction and choosing the player's look;
  - the names (`DM_KBD` answers both the player's and the rival's);
  - the bedroom, where the rival comes up the stairs;
  - downstairs past Mom, and out of the front door into Pallet Town.
- **On to Route 1, Pikachu and the first catches** (a 24-minute launch from a save outside the house):
  - Professor Oak's scene in Route 1's grass and the catch tutorial on Pikachu;
  - Oak's lab: the middle Poké Ball, Pikachu as the partner, the rival's choice and the Pokédex;
  - Mom's Town Map outside the lab;
  - two wild catches on Route 1, a Pidgey and a Rattata, each with its first throw.
- **Catching in handheld mode works with the buttons:** A readies a Poké Ball with the aim circle on the Pokémon, and A throws.
  - The game says to move the system to look around (motion aiming), but the circle starts on the Pokémon, so a throw at one in front needs no motion.
  - The host logs nothing about motion input. Whether DroidPlay hands the phone's gyroscope to the game wasn't checked.
- **No trainer battle on this stretch:** wild Pokémon in Let's Go are caught, not fought, and no trainer battled on the way to Route 1's first catches.
- **A save:** the X menu's Save, then "Save your progress", commits (`save commit #1`) and shows "You saved your progress!". After a restart the title offers "Continue your adventure" with the trainer card's name and play time, and the game goes on where it was saved: in the bedroom, outside the house, and at Route 1's edge after the catches (Pokédex 3 Pokémon, play time 0:34).
- **30 fps throughout, as on the Switch:**
  - the bedroom: frame p50 33.3 ms, p95 35.7 ms, GPU 5.7 ms;
  - the opening's 3D scenes: GPU up to 12.6 ms (15 s means);
  - walking in Pallet Town: frame p50 33.4 ms, p95 39.3 ms, p99 41.4 ms, max 43.1 ms, GPU 15.2–15.5 ms;
  - the two catches (the encounter and the throw): frame p50 33.3 ms, p95 35.4–35.6 ms, GPU p50 9.1–9.2 ms, p95 15.0–15.3 ms;
  - the whole 24-minute launch: frame p95 36.4 ms, 54 frames over 50 ms (the longest 131 ms) at scene changes and loads, GPU p50 10.7 ms, p95 17.5 ms.
- **Starting:** the first frame comes about 0.4 s after the host starts, and the controller screen is up within 10 s. With a save, the Game Freak and Pokémon logos and the title screen come next; without one, the game goes straight into the opening.
- **Sound:** Wwise opens its 10 banks (`Init.bnk`, `System_Common.bnk` and the others in `bin/sound/NX64/wwise/bank`) and streams its `.wem` music, on AAudio at 48 kHz stereo with no underrun.
  - It asks for an `English(US)` copy of each bank first, which the RomFS doesn't have: Wwise's localized lookup, not an error.
  - Confirmed by an audio dump (`DM_AUDIO_DUMP`, 156 s from the Route 1 save: walking and a catch). The front channels carry the mix at about −22 dBFS RMS, peaks to −6.4 dBFS; the centre and LFE channels are silent, the rear pair nearly so.
  - The music runs from the title on, steady at −24 dBFS on Route 1. The menu's confirm sound is the only signal before it, at each A press on the controller screen. The level changes at the wild encounter, and louder peaks come with the catch fanfare and Pikachu's level-up.
- **Two `[RED]` lines,** each kind at boot only:
  - `more than 16 font engines with a small work buffer: this one keeps the game's`, 5 times. The game makes 21 `nn::fontll` engines with small work buffers, and `hle_sdk16.c` gives host memory to 16. Every text seen drew.
  - `a second NVN queue submits: the Vulkan replay shares one state between queues`, as in Pokémon Shield. Nothing in the picture showed it.
- **Driving it over adb:** the on-screen buttons need a held touch (`input swipe x y x y 150`), since a plain `input tap` is shorter than one 30 fps frame and is sometimes missed. In the X menu, the ▶ cursor is moved onto SAVE with the stick; SAVE's highlight alone doesn't select it. A wild Pokémon that walks into the player starts an encounter, which B and then Yes leave.
- **Not tried:** a trainer battle (the first one comes later in the story), aiming with motion, docked mode, the other devices and the Mac.

**On a Google Pixel 9 Pro XL**, 2026-11-10: Tensor G4, Mali-G715 with Arm's driver 0xd803000 and Vulkan 1.4.343, Android 17. The hosts from `main` at `898ac92f`, the game files from the same build folder; handheld, the on-screen controls, played by hand with adb input:

- **From a new game:** the controller screen, the opening, the language, Oak, the player and the rival (`DM_KBD`), the bedroom, the rival's visit, Mom downstairs, then Pallet Town. Nothing wrong was seen in the picture, and there was no crash and no hang.
- **A catch, from the Z Fold 8's Route 1 save:** a wild Pidgey (Lv 3) caught with the buttons on its first throw, then the Pokédex entry.
- **30 fps, as on the Switch:** 29.7–30.0 fps per 30 s over the new game; the bedroom GPU p50 11–12 ms; walking in Pallet Town 30.0 fps, frame p50 33.2 / p95 43.5 ms, GPU p50 16.6 / p95 23.5 ms; the catch 29.9–30.0 fps, GPU p50 15–18 ms.
- **Saves:** the X menu's Save committed (`save commit #1`), and after a restart "Continue your adventure" loaded it in Pallet Town.
- **Sound:** an audio dump from the Continue start (47 s): silent on the controller screen, as on the Z Fold 8, then the confirm sound and the music from about 20 s at −21 to −24 dBFS RMS on the front pair.
- **`[RED]`:** the same two kinds.
- **Not tried:** Route 1 from a save made on this phone, trainer battles, aiming with motion.

**On a Samsung Galaxy Z Flip 7**, 2026-11-10: Exynos 2500, Xclipse 950 with Samsung's driver 0x6000215 and Vulkan 1.3.279, Android 16, open, on its inner screen. The hosts from `main` at `898ac92f`, the game files from the same build folder; the on-screen controls, played by hand with adb input from a new game:

- **The stretch:** the controller screen, the opening movie, Oak's introduction, the default look, both names (`DM_KBD`), then walking in the bedroom.
- **30 fps, as on the Switch:** 29.8 fps over the 6.6-minute first launch, 29.9 walking; frame p50 33.4 ms, p95 37–40 ms; GPU p50 5.0–7.2 ms.
- **Saves:** the X menu's SAVE committed (`save commit #1`), and the title's "Continue your adventure" loaded it in the bedroom.
- **Sound:** an audio dump: the title music at −20 to −27 dBFS and the bedroom's at −23 to −26 dBFS on the front pair; no underrun in 256,000 callbacks.
- **`[RED]`:** the same two kinds.
- **Not tried:** downstairs and Pallet Town, catches, aiming with motion.
