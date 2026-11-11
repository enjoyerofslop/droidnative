# Assassin's Creed: The Rebel Collection (`010044700DEB0000`)

The cartridge's base game, 1.0.0, SDK **8.2.0** (`NintendoSDK_NVN-8_2_0`, `NintendoSDK_gfx-8_2_0`). It holds **Assassin's Creed IV: Black Flag** and **Assassin's Creed Rogue** on Ubisoft's **AnvilNext**, with Havok and Wwise. It renders with **NVN**. The RomFS is 120 files, 10.95 GB in all: 28 `.forge` archives, 15 Wwise `.pck` banks, 75 Bink movies (`.bik`, `.bk2`), a `.txt` and a `.lang` file.

- **On the Mac:** In-game, blocked. Black Flag boots straight to its title, menus and opening at sea, at 30 fps, with the player in control. The ship and Edward are not drawn, because 210 of the shaders the opening asks for are missing from the shader map. See [Shaders](#shaders).
- **On Android:** not run yet.

## What it needs

| Setting | Where | Why |
|---|---|---|
| `launch_param hex:…` | [`game.tsv`](game.tsv) | the launcher's parameter for Black Flag, handed over at the start, so the game skips its launcher. See [Two programs](#two-programs) |
| `modules main sdk` | [`game.tsv`](game.tsv) | every module `main` imports from |
| `sys_resource 0x0`, `mem_reserve 0x100000000`, `mem_alias 0x10000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000` | [`game.tsv`](game.tsv) | the NPDM declares no system resource; `main` sets a heap of at most the pool less 64 MB |
| `zip_store .bik:.bk2:.forge:.pck:.metallib` | [`game.tsv`](game.tsv) | movies, archives and sound banks that are already compressed |

The profile is the provisional one `scripts/build_ipa_from_nsp.py` made (the survey's keys and the heap check), with `launch_param` and the comments added by hand.

## Two programs

- **Program 0** (`010044700DEB0000`, this profile) is the program HOME starts. It shows a launcher with two choices.
- **Black Flag:** the launcher restarts program 0 with `oe::ExecuteProgram(0, "/launcher:off /gamesoundlanguage:en /gamemenulanguage:en /gamerewardsPurchased:0")`, 81 bytes with the terminating zero. Started with that parameter, program 0 runs Black Flag.
- **Why the parameter is in the profile:** the host runs one program, and a restart through `DM_PROGRAMS` needs a table of programs. With `launch_param`, `oe::TryPopLaunchParameter` hands program 0 that parameter once at the start (`hle_oe.c`; the log says `81 bytes from the profile`), so Black Flag starts with no launcher and no table.
- **Rogue** is program 1 (`010044700DEB0001`). It has no profile and wasn't tried.

## Shaders

- **What the split finds:** 326 shaders, all of them BNSH inside `main`. The RomFS gives none.
- **What is missing:** 24 shaders by the main menu, and 210 once the opening at sea is under way. Each is logged as `[RED] shader … is not in the shader map`. The ship and Edward are among what isn't drawn; the sea, the sky, the rain, the fires and the HUD are drawn.
- **Where they presumably are:** the `.forge` archives. These are mostly compressed chunks the split doesn't read, and no shader turned up in their raw bytes. A reader for the `.forge` format is the open work; see [Open](#open).
- **Five false BNSH headers:** the split's raw scan finds the BNSH magic once in each of five `.forge` files: `DataNX.forge`, `DataNX_Cozumel.forge`, `DataNX_Delirium.forge`, `DataNX_NorthCarolina.forge` and `dlc_10/DataNX_DLC_CN_CaribbeanSea_10_dlc.forge`. Each lies in compressed data, with offsets that lie outside the file or fail their checks. Each is left out alone with a red line, and the file's other shaders are kept ([A BNSH header in compressed data](../../../docs/reference/shaders.md#a-bnsh-header-in-compressed-data)). Before that fix the five files counted as unreadable, and the registered profile's build stopped at the split.
- **Pipelines Metal refuses:** two render pipelines, vertex `fa4f282f3b5ed0bd` with fragment `124def699891b06c` or `421ae232a7b7df44`, fail with ``Fragment input(s) `user(locn3)` mismatching vertex shader output type(s) or not written by vertex shader``. What they draw wasn't found.

## Mac

- **Checked on an M5 Max**, 2026-11-10, headless, with the host's control file (`DM_CTL`): scripted presses and screenshots, no hand play.
- **Route:** within 15 s to the title ("press +"). Then Plus, A on Story Mode, and A on "start new game".
  - **The software keyboard:** the game then asks for a name (its default text is `Abstergo`). Headless, the keyboard returns cancel and the game asks again, so the run sets `DM_KBD=Abstergo`.
  - A on "start new game" again, a save, and the opening storm at sea, where the "reach the ship's wheel" objective is shown and the camera follows the input.
- **Frame rate:** 30.0 fps (frame time p50 33.3 ms, p95 34.2 ms) from the title through 190 s of the opening, the game's target on the Switch. The CPU used 38% of one core.
- **Not checked:** sound, saving and loading, Rogue, and play by hand.

## Open

- **A `.forge` reader in `shader_split.py`**, for the 210 missing shaders. Until then the opening draws without the ship and the characters.
- **Android:** not run. It would draw the same way, since the same shaders are missing.
- **The two refused pipelines** above.
- **Rogue** (program 1): not profiled.
- **`pso_manifest.tsv`** is empty. It is recorded on the Mac (`DM_PSO_MANIFEST=off DM_PSO_RECORD`) once the shaders are complete.
