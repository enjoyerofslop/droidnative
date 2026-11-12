# Assassin's Creed: The Rebel Collection (`010044700DEB0000`)

The cartridge's base game, 1.0.0, SDK **8.2.0** (`NintendoSDK_NVN-8_2_0`, `NintendoSDK_gfx-8_2_0`). It holds **Assassin's Creed IV: Black Flag** and **Assassin's Creed Rogue** on Ubisoft's **AnvilNext**, with Havok and Wwise. It renders with **NVN**. The RomFS is 120 files, 10.95 GB in all: 28 `.forge` archives, 15 Wwise `.pck` banks, 75 Bink movies (`.bik`, `.bk2`), a `.txt` and a `.lang` file.

- **On the Mac:** In-game. Black Flag boots straight to its title, menus and opening storm at sea, with the player in control at 30 fps. The ship, Edward and the crew are drawn, and no shader the run asks for is missing from the map. The shaders come from the `.forge` archives; see [Shaders](#shaders).
- **On Android:** In-game on a OnePlus Pad 3, a Moto Razr Plus 2023, an Ayn Odin 2 and a Galaxy Z Flip 7 (Xclipse 950), at 30 fps, with the same picture as the Mac. Edward walks the deck to the ship's wheel, the save loads, and sound plays. Sailing wasn't reached. Rogue can't run from this cartridge: its game data isn't on it. See [Android](#android).

## What it needs

| Setting | Where | Why |
|---|---|---|
| `launch_param hex:…` | [`game.tsv`](game.tsv) | the launcher's parameter for Black Flag, handed over at the start, so the game skips its launcher. See [Two programs](#two-programs) |
| `shader_separate on` | [`game.tsv`](game.tsv) | every BNSH file holds one stage, and the game combines a vertex shader of one with a pixel shader of another per draw, so every vertex shader is padded for any pixel shader. See [Shaders](#shaders) |
| `modules main sdk` | [`game.tsv`](game.tsv) | every module `main` imports from |
| `sys_resource 0x0`, `mem_reserve 0x100000000`, `mem_alias 0x10000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000` | [`game.tsv`](game.tsv) | the NPDM declares no system resource; `main` sets a heap of at most the pool less 64 MB |
| `zip_store .bik:.bk2:.forge:.pck:.metallib` | [`game.tsv`](game.tsv) | movies, archives and sound banks that are already compressed |

The profile is the provisional one `scripts/build_ipa_from_nsp.py` made (the survey's keys and the heap check), with `launch_param`, `shader_separate` and the comments added by hand. Its tables were split again with the `.forge` reader.

## Two programs

- **Program 0** (`010044700DEB0000`, this profile) is the program HOME starts. It shows a launcher with two choices.
- **Black Flag:** the launcher restarts program 0 with `oe::ExecuteProgram(0, "/launcher:off /gamesoundlanguage:en /gamemenulanguage:en /gamerewardsPurchased:0")`, 81 bytes with the terminating zero. Started with that parameter, program 0 runs Black Flag.
- **Why the parameter is in the profile:** the host runs one program, and a restart through `DM_PROGRAMS` needs a table of programs. With `launch_param`, `oe::TryPopLaunchParameter` hands program 0 that parameter once at the start (`hle_oe.c`; the log says `81 bytes from the profile`), so Black Flag starts with no launcher and no table.
- **Rogue** is program 1 (`010044700DEB0001`). It has no profile and wasn't tried.

## Shaders

- **Where they are:** 33,147 shaders in all (22,334 vertex, 10,813 pixel). 326 are BNSH inside `main`. The other 32,821 are BNSH in the entries of the `.forge` archives, including the two DLC folders, which [`anvil_forge.py`](../../gfx/tools/anvil_forge.py) reads ([AnvilNext .forge archives](../../../docs/reference/shaders.md#anvilnext-forge-archives)).
  - **The format:** version 27 tables, and each entry's blocks are LZO1X chunks of up to 32 KB. The decoded blocks of the material entries hold whole BNSH files.
  - **Where most come from:** `DataNX.forge` gives the most shaders first seen (7,314), then the Caribbean Sea DLC file (6,264), `DataNX_Abstergo.forge` (4,329) and `DataNX_CaribbeanSea.forge` (4,249).
- **Before the reader:** the split found only `main`'s 326. By the main menu 24 shaders were missing from the map, and 210 once the opening at sea was under way, each logged as `[RED] shader … is not in the shader map`. The ship and Edward weren't drawn. All 210 are in the map now.
- **One stage per BNSH:** every BNSH file holds one stage, and the game draws with a vertex shader of one file and a pixel shader of another. So the profile sets `shader_separate on`, and every vertex shader is paired with the pixel shaders' cover: here one pixel shader that reads every location any of them reads. That is 22,334 pairs.
  - **Before the key:** Metal refused two pipelines of `main`'s shaders, vertex `fa4f282f3b5ed0bd` with fragment `124def699891b06c` or `421ae232a7b7df44`: ``Fragment input(s) `user(locn3)` mismatching vertex shader output type(s) or not written by vertex shader``.
- **Five false BNSH headers:** a loose scan of the `.forge` files found the BNSH magic once in each of five, by chance in compressed bytes, with offsets outside the file. The five are `DataNX.forge`, `DataNX_Cozumel.forge`, `DataNX_Delirium.forge`, `DataNX_NorthCarolina.forge` and `dlc_10/DataNX_DLC_CN_CaribbeanSea_10_dlc.forge`. They counted as unreadable and stopped the registered profile's build at the split. The `.forge` files no longer go through the loose scan.

## Mac

- **Checked on an M5 Max**, 2026-11-10, headless, with the host's control file (`DM_CTL`): scripted presses and screenshots, no hand play.
- **Route:** within 15 s to the title ("press +"). Then Plus, A on Story Mode, and A on "start new game".
  - **The software keyboard:** the game then asks for a name (its default text is `Abstergo`). Headless, the keyboard returns cancel and the game asks again, so the run sets `DM_KBD=Abstergo`.
  - A on "start new game" again, a save, and the opening storm at sea, where the "reach the ship's wheel" objective is shown and the camera follows the input.
- **What draws:** the title's logo, Edward on the Story Mode menu, the opening cutscene's sailor, and in play the ship (deck, masts, rigging, cannons), Edward, the crew, the sea, the storm and the HUD.
  - Before the `.forge` reader, the opening drew the sea, the sky, the fires and the HUD, with no ship and no characters. 210 shaders were missing then.
  - The run logged no red line: no shader missing from the map, and no pipeline refused.
- **Frame rate:** 30.0 fps, the game's target on the Switch, from the title through 235 s of the opening. Frame time p50 33.3 ms, p95 33.7 to 34.0 ms. The CPU used 34% of one core.
- **The pipeline prebuild** (22,334 pairs) crashed once, inside Metal (`MultiLevelAirntBinaryCache::getElementAtDestination`, called by `MTL4Compiler` from `arch_capture` on one of 18 workers), after 13,000 pairs. The next build went on from the archive and finished with none failed.
- **Not checked:** sound, saving and loading, Rogue, and play by hand.

## Android

### Moto Razr Plus 2023

- **Tested 2026-11-10 on a Moto Razr Plus 2023** (Adreno 730, Qualcomm's driver V@0615.98, Vulkan 1.1, Android 16), from this branch as a game app (`--game-apk`). The RomFS went over as the app's OBB file, and the phone's DroidPlay was left alone.
  - **The run:** scripted over adb, with `DM_CTL` presses and `DM_KBD=Abstergo` in the app's `env.txt`. No hand play.
  - **The control file:** create it with mode 666. A file `adb shell` makes in the app's folder is 660 and owned by `shell`, the app can't open it, and the presses are lost without a red line.
- **First start:** unpacking the 72,000 translated shader files took about 30 s, then the title came up.
- **Route:** the title's attract trailer (Bink) and the title, then the menus and the name prompt as on the Mac, then a new game into the opening storm at sea.
  - **What draws:** the ship, Edward, the crew, the rain, the explosions, the cannon fire and the HUD, as on the Mac.
  - **Some frames are much brighter:** lighting that looks like the storm's lightning, with the sky and the ship beside lit and the HUD unchanged. It wasn't compared with the Switch.
- **Control:** the left stick took Edward from the opening's spot along the deck, up to the raised deck and to the ship's wheel. The right stick turned the camera.
  - **The wheel:** its "take wheel" prompt showed, but no A press landed while it was up: the deck sways and moved him off the spot between screenshots. So taking the wheel and sailing weren't reached; a person with a controller should check them.
- **Frame rate:** 29.7 fps over 3 minutes of the opening, and 28.9 fps over 5 minutes of the second session (menus, loading, walking). Frame time p50 33.5 ms, p95 43 to 48 ms.
  - **The slow frames:** 2 to 7% of frames take 50 to 73 ms. Each is a single frame with about twice the usual draws and passes (2,276 draws and 118 passes, against 1,135 and 59), not a new pipeline.
  - **The GPU:** busy 20 to 23 ms a frame.
- **Saves:** the opening saves on its own. After a restart, Story Mode lists the save ("Abstergo", 0%) and loads it back into the storm.
- **Sound:** the game opens AudioOut (6 channels, from `main`) and the audio renderer. Neither underran.
  - **The dump:** 140 s of `DM_AUDIO_DUMP` holds signal throughout: RMS 170 to 2,500 in 5 s windows, with peaks to 27,500, louder once the game loaded. Nobody listened to it.
- **Red lines:** none from the game in either session.

### OnePlus Pad 3

- **Tested 2026-11-11** (Adreno 830), from main 7a17f7af with this branch merged in (`ANDROID_CHAIN` 6). It ran as a game app with the RomFS as its OBB, the same way as on the Razr, and the tablet's DroidPlay (0.7.5-26-ga91a6a64) was left alone. Scripted over adb, no hand play.
- **Route:** as on the Razr. The title's attract trailer, the menus and the name prompt, then a new game into the opening storm, and Edward walked along the deck and up to the wheel. The take-wheel prompt wasn't caught this time either.
- **Frame rate:** 30.0 fps over 5 minutes of the opening, frame time p50 33.1 ms and p95 40.9 ms, with 0.2% of frames over 50 ms. That's steadier than the Razr. The GPU was busy 12.3 ms a frame.
  - **During the attract trailer** (Bink), frames ran 45 to 68 ms with the GPU at 1.6 ms, and 3% were over 50 ms. Time on the CPU, not looked into.
- **Memory:** 1.44 GB PSS (1.56 GB RSS) in the opening, of the tablet's 11.7 GB, with 179 MB of Vulkan images.
- **Saves:** after a restart, Story Mode lists the opening's save and loads it back into the storm.
- **Sound:** the AudioOut dump holds signal in 55 of 58 ten-second windows (the silent ones at the start), with peaks to 27,500. Nobody listened.
- **Red lines:** none, and no crash.

### Ayn Odin 2

- **Tested 2026-11-12** (SM8550, Adreno 740 with Qualcomm's driver 0x802a4000), from this branch with main 011e97f9 merged in, as a game app: a 421 MB APK with the 11.8 GB RomFS as its OBB. The split found 33,147 shaders, and all translated (1 min 8 s on the Mac). No Mac decoder is involved: `anvil_forge.py` reads the archives in Python.
- **Route:** the title, Story Mode, start new game, the name (`DM_KBD=Abstergo`), the save, "Ubisoft Presents" and the opening storm, with Edward walking the deck toward the "reach the ship's wheel" marker.
  - Near the raised deck he stopped advancing under scripted input, so the wheel wasn't reached here either.
- **Frame rate:** 30.0 fps in every 30 s window over 4 minutes of the storm, frame p50 33.4 ms, p95 about 37 ms, GPU 9.3 ms a frame.
- **Memory:** 1.41 GB PSS.
- **Saves:** after a cold start, Story Mode lists "Abstergo, 0%" with its date and time, and loads it back into the storm.
- **Sound:** the 6-channel `AudioOut` and the audio renderer underran only in two reports, during start-up and the opening's load; none in play.
- **Red lines:** none.

### Galaxy Z Flip 7

- **Tested 2026-11-12** (Xclipse 950 with Samsung's driver 24.0.533, 0x6000215), with the Odin's game app: this branch with main 011e97f9 merged in. The Xclipse has no BC textures, so those are decoded on the CPU; ASTC is native.
- **Route:** the Odin's, through the opening storm.
  - After a cold start, from the save, Edward climbed the side stairs to the raised deck and stood by the ship's wheel with its "reach" marker showing.
  - The swaying deck turned him away before the prompt to take it, so sailing wasn't reached.
- **Frame rate:** 30.0 fps in every 30 s window once the storm had loaded, over 11 minutes in two runs. Frame p50 33.3 ms, p95 about 37 ms, GPU 12.7–13.7 ms a frame (9.3 on the Odin's Adreno 740).
- **Memory:** 1.87–1.96 GB PSS, 0.74–0.78 GB of it graphics. That's more than the Odin's 1.41 GB; BC textures kept decoded may be the difference, but that wasn't measured.
- **Saves:** after a cold start, Story Mode lists "Abstergo, 0%" and loads it back into the storm.
- **Picture:** the same as the Odin's at the same points of the opening, with the same texture detail on Edward, the cannons and the deck.
- **Sound:** no underrun in either output in any report of either run.
- **Red lines:** none, and no crash or kill.

## Rogue (program 1)

- **Not on the cartridge:** program 1 (`010044700DEB0001`) has a full `main` (44.7 MB of code), but its RomFS is 0.8 GB of ten Bink movies and a language file, with no `.forge` archive. Program 0's RomFS holds only Black Flag's (the Caribbean, Kingston, Havana, Nassau…), and the cartridge carries no other content. So Rogue's game data is a download, not part of this dump.
- **On Android, 2026-11-12, Ayn Odin 2:** packed with a test wrapper that does what `build_ipa_from_nsp.py --program 1` does: program 1 as a title of its own, from a provisional profile, 427 shaders from `main`. It crashes on its main thread before its first frame: a read of address 0x50 at `main+0xd6f19c`, right after mounting its RomFS, with an `.ini` path on the stack. A game missing its data would do that.
- **Unblock:** dump Rogue's download. `build_android_from_nsp.py` also has no `--program` yet, which the iOS script has.
- **The lightning-like bright frames** show here too, now and then.

## Open

- **Android:** taking the wheel and sailing, by hand; the frames with twice the draws; the bright frames, against the Switch.
- **Rogue** (program 1): not profiled. Its own RomFS may use the same `.forge` format.
- **`pso_manifest.tsv`** is empty. It can be recorded on the Mac now that the shaders are complete (`DM_PSO_MANIFEST=off DM_PSO_RECORD`).
- **The prebuild crash** inside Metal, seen once: not reproduced.
