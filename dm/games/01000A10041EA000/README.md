# The Elder Scrolls V: Skyrim (`01000A10041EA000`)

Update 1.1.404 (v393216, the Anniversary Edition build) over the base game, SDK **14.3.0** (`nnSdk-14_3_0`, `NintendoSDK_NVN-14_3_0`). Bethesda's **Creation Engine** with Havok, drawing with **NVN**. Modules `main` and `sdk`. Every game file is in 89 BSA archives (version 105) and the plugin files (`.esm`, `.esl`) under `Data/`, 12.4 GB. Started from the provisional profile the NSP script wrote from its survey (`dm/games/profile_guess.py`); answers droidplay-core#414 (music, no picture).

- **On the Mac:** In-game at the game's 30 fps, by `DM_CTL` presses from a new game: the title, the main menu, the opening cart ride, the arrival in Helgen, character creation and the dragon attack, to the first steps under the player's control.
- **On Android:** In-game on a Galaxy S25 Edge (Adreno 830), the same stretch over adb at 30 fps. See [Android](#android).

## What it needs

| Setting | Where | Why |
|---|---|---|
| `modules main sdk` | [`game.tsv`](game.tsv) | `main` imports from these two only |
| `mem_reserve 0x1028000000`, `mem_alias 0x1000000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000`, `sys_resource 0x800000` | [`game.tsv`](game.tsv) | see [Memory](#memory) |
| `render_cond on` | [`game.tsv`](game.tsv) | the render thread waits for a timestamp report's counter field to read 0; see [Boot](#boot) |
| `depth_mode zero` | [`game.tsv`](game.tsv) | the game calls `nvnDeviceSetDepthMode` with near = 0 in its first seconds |
| `shader_groups /Data/=data /BatchFiles/=batchfiles` | [`game.tsv`](game.tsv) | the shaders are in `Data/Skyrim - Shaders.bsa` and in `main`; see [Shaders](#shaders) |
| `zip_store .bik:.bsa:.esm:.metallib` | [`game.tsv`](game.tsv) | the archives are stored uncompressed already |
| the scene initializer's stencil clear (`main+0xbf7d5c`) | [`patches.py`](patches.py) | see [Helgen Keep's lighting](#helgen-keeps-lighting) |

`pso_manifest.tsv` is still the empty provisional list.

## Memory

The NPDM declares 8 MB of system resource and `main` never sets a heap: the game's heaps are address regions it reserves itself (`nn::os::AllocateAddressRegion`, from `main+0xacf43c`): 2 GB at alias +0.07 GB, 2 GB at +2.07 GB, 0.59 GB at +4.23 GB and 1 GB at +4.82 GB, and more after them, so its regions reach alias +6.92 GB in its first 15 s, with 1.27–1.94 GB mapped. That is past the 4.375 GB alias region of an iPhone's 5 GB block. The Mac and Android give every game a Switch's 64 GB alias region whatever the profile says (`hle_svc.c` `mem_init_once`), so the profile names that much, as Unreal's bring-up profiles do, and the regions fit as on a Switch. An iPhone would need the heaps' ceilings cut: [seedds/nxnative PR #444](https://github.com/seedds/nxnative/pull/444) does that for 1.0.12 (Default and GPU heaps 2 → 1.5 GB, the small-block pool 1 GB → 256 MB, build-gated cuts); no such cuts exist for 1.1.404.

## Shaders

- **Where:** 23,133 shaders: 23,080 in `shadersfx/shaders011.fxp`, the one file of `Data/Skyrim - Shaders.bsa` (BSA version 105, stored, 116 MB), and 53 in `main`. 19,645 pixel, 3,468 vertex and 20 compute; every program binds one stage, so the vertex shaders get the pixel input cover. Read by `bsa.py` and `fxp_shaders` ([FXP shader records in Bethesda BSA archives and in main](../../../docs/reference/shaders.md#fxp-shader-records-in-bethesda-bsa-archives-and-in-main)); the whole RomFS splits in 2 s.
- **The records:** `{u32 16, u32 control length, u32 code offset, u32 code length}`, the control section, then the code area. In the `.fxp` each record has a 0x30-byte header before it (magic 0x11223344 at +8, the record's length at +12) and a 0x880-byte control section. Main's controls are 0x7d1 (3), 0x838 (49) and 0x848 (1) bytes, each with its code area right after it, unaligned after the 0x7d1-byte ones. The first two shaders the game asks for, `c654c9273c80debb` (vertex) and `8f865c34471ac9d7` (pixel), are main's 0x7d1-byte ones at `main@0x20e0cf0` and `@0x20e16d1`.
- **Mac:** all 23,133 translate.

## Boot

- **One black frame, then none (resolved):** with the shaders found, the game presented one black frame and no more, its music playing. After its first frame the render thread waits for a timestamp report's counter field to read 0, as the GPU writes it; the host writes the time there unless the profile has `render_cond on`, which this one now has. seedds/nxnative PR #444 found the same wait on 1.0.12 (`main+0xb5e808`).
- **Abort at "Start a new game?" → Yes (resolved):** the game makes a 1280x720 RGBA8 `LINEAR` texture with 3840-byte rows, which Metal's validation refused as a view and the host aborted on the replay thread ([A linear texture whose stride is shorter than its rows](../../../docs/reference/nvn-objects.md#a-linear-texture-whose-stride-is-shorter-than-its-rows)).
- **Loading:** the title shows about 20 s after launch on the Mac; a new game reaches its opening cart ride about 30 s after Yes.

## Helgen Keep's lighting

- **The report (droidplay-core#444):** inside Helgen Keep the lights flicker, the room switching between bright and dark, on an AYN Thor Pro (Adreno 740) with Qualcomm's driver and with PurpleVK; occlusion queries off (`DM_VK_OCCLUSION=0`) change nothing. seedds/nxnative PR #444 found the cause on 1.0.12: [Raw depth/stencil storage written as a buffer](../../../docs/reference/rendering.md#raw-depthstencil-storage-written-as-a-buffer).
- **The same code in 1.1.404:** the scene initializer (`main+0xbf7690`) switches on its mode at `+0xbf7cd8` with 1.0.12's table (1.0.12: `+0xb551c0`): modes 0 and 6 clear depth and stencil, 2 the stencil, 1 the depth, and 7 the depth and then dispatches `a76fe13a8630d619` (main's FXP record at `main@0x20d0a60`) with storage buffer 0 laid over the 1600x900 D24S8 target (6,553,600 bytes). The interior's shadow mask (`f83614ab6954bec4`) takes its shadow class from the stencil's upper three bits, which the dispatch writes as 0 into the buffer only; the image's stencil keeps what the interface left there (255 on 1.0.12, class 7: secondary-shadow data the scene does not have).
- **Cut (current):** `main+0xbf7d5c` `mov w3, wzr` → `neg w3, w21`: w21 is 1 in mode 7 and 0 in mode 1, so mode 7's depth clear also clears the stencil to 0 (mask 0xffffffff) and mode 1 stays depth-only. On the Mac the pass dump shows it: mode 7's clear was `stencil_mask=0` with the stencil plane left unwritten before the dispatch, and is `stencil_mask=0xffffffff` with the plane cleared and stored with the cut. Mode 7 runs every frame outdoors too (the execution yard, the tower); the shadow mask is not drawn there, and screenshots of the same outdoor stretch show the same lighting and shadows with and without the cut.
- **Not confirmed:** the keep's flicker itself. Reaching it means following Hadvar through Helgen under the dragon, which was not driven here, so the flicker was not seen before or after the cut on any device. PR #444's user confirmed the same cut on 1.0.12 on an iPhone.

## Unlocks before SignalLightEvent (open)

- **What:** 552 inlined unlocks in 1.1.404's main are a plain `str wzr`, then `bl nn::os::SignalLightEvent`, then `dmb ish` (1.0.12 has 517; PR #444 cut them to release stores there).
- **No lost wake here:** 1.0.12 loses wakes after them because SDK 3.4's `SignalLightEvent` reads the event with `ldarb` and skips its write when the event is signalled already. SDK 14.3's reads it after a `dmb ish` (`sdk+0x123868`), so this build cannot lose a wake that way.
- **Ordering gap:** nothing orders the critical section's stores before the plain unlock. A native litmus test sees another core read the old data with the plain store (on an Odin 2's Snapdragon 8 Gen 2 cores and on an M5 Max), never with `stlr`; no failure of the game is tied to it. Release-store cuts for all 552 (Armv8.0 forms) are held on branch `android/skyrim-1-1-404-cuts` (c234dce8), not in this build.
- **The report's BSTaskManager crashes:** both are unchecked pops of the audio pools' `std::deque<void *>` (`main+0xabd428`, whose garbage pointer `nn::audio::ParseAdpcmHeader` faults on at `pc=sdk+0x1ca880 lr=main+0xac0d24`, and `main+0xabd548`, `pc=main+0xabd5c8 lr=main+0xac11bc`). The second reproduced on the Mac without any cuts (M5 Max, thread `LibAudioUpdate`, 620 s after launch, just after walking into the tower), so it is neither Android's nor PurpleVK's. The cause is not known.

## Mac

On an M5 Max, a new game from the title through the cart ride, Helgen, character creation (named with `DM_KBD=Prisoner`) and the dragon attack to "Use L to move", where a held stick walks the player: 30 fps, 33.3 ms median frame time in every 300-frame window but one (41 ms), a resident footprint of 4.1 GB and 2.7 GB of GPU memory. One `[RED]` line in the whole run, `stage 1 cb11 has no uniform buffer bound` ([Open](#open)).

## Android

- **Galaxy S25 Edge (Adreno 830, Qualcomm's driver):** over adb from a new game, in a private save folder: the title, the main menu, the cart ride into Helgen, character creation (named in DroidPlay's text box), the dragon attack and the first steps with the left stick. 30 fps: the frame time's median is 33.0–33.5 ms in 64 of the 69 300-frame windows, the others 33.8–39.6 ms (the first at boot, and loads). 3.2 GB PSS. Both audio renderers produce output (renderer 0: 142,944 of 144,000 frames not silent); not listened to. The game wrote its character-creation save and an autosave; neither was loaded back.
- **All 23,133 shaders translate** for Vulkan. One `[RED]` line, 8 times when the opening loads: `[vk] shader e8910903259b956c reads uniform slot 11, which has no buffer bound: it reads 0`, the Mac's cb11 line.
- **Not tried:** the other devices; a stretch played by hand (real-time action: its Playable evidence needs a person); loading a save.

## Mac test controls

`DM_CTL` presses of A held 0.5 s pass the title ("Press any button"), pick New and answer Yes. Character creation opens about six minutes later; Y finishes it and A confirms, then the game asks for a name: run with `DM_KBD=Prisoner`, or with no window the keyboard returns cancel.

## Found on this game

- [FXP shader records in Bethesda BSA archives and in main](../../../docs/reference/shaders.md#fxp-shader-records-in-bethesda-bsa-archives-and-in-main).
- [A linear texture whose stride is shorter than its rows](../../../docs/reference/nvn-objects.md#a-linear-texture-whose-stride-is-shorter-than-its-rows).
- [Raw depth/stencil storage written as a buffer](../../../docs/reference/rendering.md#raw-depthstencil-storage-written-as-a-buffer).

## Open

- **`[RED] stage 1 cb11 has no uniform buffer bound`** on the Mac, once, when the opening loads, and Android's `shader e8910903259b956c reads uniform slot 11` (PR #444's 1.0.12 note has it too). Nothing missing was seen.
- **The main menu's "Start a new game?" box** draws as two vertical lines the height of the screen beside its text, on the Mac and on the S25 alike; not compared with the Switch.
- **The 1280x720 texture of 3840-byte rows** (made at "Start a new game?" → Yes) is uploaded as the GPU would read it; what it holds and where it shows is not known.
- **Helgen Keep's flicker after the cut:** not seen in the keep on any device yet ([Helgen Keep's lighting](#helgen-keeps-lighting)).
- **The unlocks before `SignalLightEvent` and the audio pool crashes** (droidplay-core#444, and once on the Mac): see [Unlocks before SignalLightEvent](#unlocks-before-signallightevent-open).
- **The iPhone:** the regions need more than its alias region holds (see [Memory](#memory)).
