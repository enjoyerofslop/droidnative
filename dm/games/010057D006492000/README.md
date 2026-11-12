# OCTOPATH TRAVELER (`010057D006492000`)

Update 1.0.5 (v327680) over the base game, SDK 3.5.1 (its own `sdk` build; NVN API 53). Square Enix / Acquire, Unreal Engine 4.18 (`++UE4+Release-4.18`; its project is called Kingship): two legacy version 4 paks with the shaders inline in the cooked packages, NVN, PhysX 3.4, CRIWARE (ADX2 sound banks, one USM movie). Modules `main`, `subsdk0` (the movie module) and `sdk`. 60 fps (30 on the Switch).

Status: brought up on the Mac: the boot, the language notice, the title, a new game, the traveler selection (the world map, the travelers' cards), Ophilia's opening (her room, the cathedral hall and nave, the tutorials) and H'aanit's (the flashback, free play in S'warkii), at 60 fps since 2026-11-09 (frame time p50 16.7 ms; 30 before, p50 33.4 ms) with no red line but the two untranslated compute shaders below; about 2.4 GB resident with 1.2 GB of Metal allocations. Not yet seen on the Mac: a battle, the sound (runs were headless, `DM_AUDIO` off), the iPhone. On Android, Playable – major issues through H'aanit's first battles on a Pixel 9 Pro XL, with battles, sound, a save and Continue ([Android](#android)).

## What it needs

| Setting | Where | Why |
|---|---|---|
| 4 GB layout: `mem_reserve 0x100000000`, `mem_alias 0x10000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000`; `sys_resource 0x0` | [`game.tsv`](game.tsv) | no virtual address memory: `nninitStartup` sets a heap of pool − used (3.08 GB); see [Memory](#memory) |
| `mem_used 0x8000000` | `game.tsv` | the rewritten modules are larger than the default 64 MB of used memory |
| `tex_flush_upload on`, `tex_dirty_upload on` | `game.tsv` | the CPU loads textures straight into CPU-uncached pools after creating them and never flushes; see [Rendering](#rendering) |
| `pad_layout full` | `game.tsv` | menus and the battle commands take the D-pad |
| `shader_groups GlobalShaderCache=global #Engine/=engine #Kingship/=game` | `game.tsv` | the global shader cache, the engine's materials and the game's |
| `fps_target 60` | `game.tsv` | 60 fps: the host writes the frame limit the game sets to 30; see [Frame rate](#frame-rate) |

## Frame rate

- **Current:** 60 fps (30 on the Switch), since 2026-11-09. The game's config sets Unreal's frame limit `t.MaxFPS` to 30; its present interval, `nvn.SyncInterval` in UE 4.18's Switch RHI, is already 1 (the log's "present interval set by the game 1"). The rewriter finds both console variables by name (`dm/tools/ue_cvar.py`: `t.MaxFPS` at `main+0x50b5688`, `nvn.SyncInterval` at `main+0x5adc4a8`), and `hle_fpslock.c` writes 60 into `t.MaxFPS` (profile key `fps_target 60`); `DM_FPS_TARGET=30` keeps the game's 30. This build registers its variables in inlined static constructors, which take one page base in `x22` (`main+0x1bfd0a4`, about 700 instructions before the `t.MaxFPS` name at `main+0x1bfdb90`) and store each object's vtable and value pointer at offsets from it (`[x22, #0x5d8]`, `[x22, #0x5e8]`); the search follows that form since 2026-11-09 ([Unreal's frame limit and present interval, found by name](../../../docs/reference/frame-rate.md#unreals-frame-limit-and-present-interval-found-by-name)).
- **Measured** (M4 Pro, headless, the S'warkii route below, 300 s each): frame time p50 16.7 ms at 60 against 33.5 ms with `DM_FPS_TARGET=30`, GPU p50 about 7 ms. Long frames (CPU-side: no new pipelines, the GPU under 12 ms) are more frequent at 60: 284 over 50 ms and 101 over 100 ms, against 127 and 39 at 30 in the same 300 s (open, below). Unreal steps the game by the time that really passed, as in [OCTOPATH TRAVELER II](../0100A3501946E000/README.md); the game's speed at 60 has not been compared on a walk yet.

## Memory

- **Current:** the NPDM declares no system resource, so there is no virtual address memory and no engine address region: `nninitStartup` (`main+0x2c67cc` calls into the SDK's heap setup) sets a 3.08 GB heap, and Unreal's own allocator ("Using Standard Allocator", Binned Small Heap 3154 MB) and the NVN pools live in it. The game prints its memory setup through `nn::diag::LogImpl`, which reaches the host log with `DM_DBG=1` (`svcOutputDebugString`), as does an Unreal assertion.
- **Resolved: `SetHeapSize OOM: req 0xc5400000 > cap 0` and a `Break` in `nninitStartup`** with the provisional profile, which gave every Unreal game a 64 GB alias region and no heap region: [Unreal's engine address region](../../../docs/reference/memory.md#unreals-engine-address-region-and-its-options) (note).
- **Resolved: `Failed to allocate 1879113728 bytes from Standard Allocator`** at boot: [The sparse tile layout of a texture](../../../docs/reference/nvn-objects.md#the-sparse-tile-layout-of-a-texture).
- On the Mac the process holds about 2.4 GB (1.2 GB of Metal allocations) in the cathedral and in S'warkii; 221 memory pools.

## Rendering

- **Resolved: the language notice's pictures, the title logo and the whole traveler selection missing** (only the backdrop and the footer text drew). Unreal writes these textures from the CPU into CPU-uncached pools (flags 0xe2) after `nvnTextureInitialize`, with no flush, so the host kept them as GPU textures with no content; Slate then drew nothing for them. The profile turns on `tex_flush_upload` and `tex_dirty_upload` ([dm/games/README.md](../README.md)), which upload them from guest memory and again when their pages change.
- **Resolved: the world map on the traveler selection a patchwork of rectangles:** [Sparse textures take the block height of their 64 KB tile](../../../docs/reference/rendering.md#sparse-textures-take-the-block-height-of-their-64-kb-tile).
- **Resolved: streamed textures black or missing** (S'warkii's ground, plants and props) and `[RED] MapVirtual: non-contiguous mapping (true sparse) not implemented`: [Virtual pools of one texture each](../../../docs/reference/nvn-objects.md#virtual-pools-of-one-texture-each-mapped-before-and-after-the-texture).
- **Current (checked, not confirmed on hardware): a dark red cast at the screen edges in S'warkii.** The tonemapper is right (checked by snapshots of its inputs, `DM_NVN_TEXSNAP`): its scene input is neutral there and its LUT turns dark greys red. The LUT is computed every frame from the area's grading parameters (pass with `172ec899e321a2a5`, no textures), which in S'warkii hold a red-weighted gain (1.5, 1.08, 1.0), an offset (1, 0, 0) with −0.116 and a white balance of 8000 K (6500 K on the title), so the strong vignette (intensity 1.17) darkens the edges into the red shadows. The grid there is the out-of-focus foreground foliage's pixel-art blocks.
- Two compute shaders of the global shader cache did not translate (`327fce53f1fce4c1`, `6d87d48e86bd7f3c`: image atomics whose result is used, refused on MSL 2.3), and their dispatch was skipped with a red line. Both build on chain `0ce4b5e8aefb` (a build of those two keys, 2026-10-27; [Image atomics](../../../docs/reference/shaders.md#image-atomics)); not run since.
- 5,434 shaders (4,517 pixel, 672 vertex, 232 compute, 13 geometry), all but those two built for the Mac; all 5,434 built for iOS.

## Files and shaders

- `Kingship/Content/Paks/Kingship-Switch.pak` (1.97 GB, 103,018 files; the profile's `romfs_marker`) and the update's `Kingship-Switch_0_P.pak` (601 MB, 1,294 files), legacy version 4, Zlib blocks, index not encrypted; beside them 383 CRIWARE `.awb` banks, `CRIWARE/movie01_op.usm` and the vibration data. `UE4CommandLine.txt` holds the project path.
- The shaders are inline in the cooked packages and the global shader cache, as for [DRAGON QUEST XI S](../01006C300E9F0000/README.md) ([Unreal Engine 4.18 shaders inline in cooked packages](../../../docs/reference/shaders.md#unreal-engine-418-shaders-inline-in-cooked-packages)); here the paks are Zlib, so no game decoder is needed.

## Rewriter

- **Resolved: `jump table 1676f58`:** [64-bit bounds check of the index](../../../docs/reference/rewriter.md#64-bit-bounds-check-of-the-index).

## Sound

- **Resolved: `FATAL audren: missing SDK symbol _ZN2nn2os12SdkMutexType4LockEv`:** [No `SdkMutexType` in SDK 3](../../../docs/reference/audio.md#no-sdkmutextype-in-sdk-3). The renderer then runs at 32 kHz with the SDK 4 command layout (`DeviceSink` as command 0xf); not listened to yet.

## Mac routes

The work folder `<NSP folder>/010057D006492000-work/run` has `host.sh` (builds the octo1 worktree's host and copies it to `build/o1host`; since 2026-11-09 the NSP script's build holds only the current chain's libraries, so run its `tools/dmhost` with `DM_GAMES_DIR` set to this repository's `dm/games` and `DM_ROMFS=<build>/extract/v327680/RomFS.img`), `boot.sh <log> [secs] VAR=…`, `ctlrun.sh` / `ctl.sh` / `step.sh` / `see.sh` / `mash.sh` for driving a run through `DM_CTL`, `stop.sh`, `to_story.sh` (Ophilia's opening) and `ab.sh` (several variants at once on copies of the save, the same scripted route, shots at given frames).

- With system data in the save (the language notice is shown only on a fresh save): the title at about 28 s; A, A (New Game) opens the traveler selection; L picks a traveler (L once Ophilia, twice H'aanit); A opens the confirmation, whose cursor appears only after a direction press (Down, Up), then A starts the story.
- Into S'warkii: `DM_KEYS=28:A,36:A,70:L,72:L,75:A,78:Down,79:Up,80:A,95:A*480/0.6,390:B` (the village at about frame 12,000).
- In S'warkii: from the start, `LUp~1.5`, `LRight~0.1`, `A` talks to the villager on the path ("This is S'warkii, …"); the headman (green bubble, by the big house) starts the Linde scene and the Path Actions tutorial, after which the objective is to Provoke the two fledgling hunters in the plaza (Y facing one; with nobody in front Y offers only Examine, the monster roster). Characters do not block H'aanit: walking into a villager walks through it, and talking needs her to stop beside one, facing it.
- **Checked, not a bug: walking through villagers.** Probes on PhysX's query callback (`MultiQueryCallback::invoke`, the scene's pre-filter at `main+0x154d750`) show the player's movement sweep (Pawn channel, block bits `fffffef3`, touch bits `4`) only touches Pawn shapes, by the game's own collision data, while villagers' own sweeps block each other and the WorldDynamic queries that touch Pawns find the villagers' capsules.
- The game saves no story progress before its first save point; no save of the openings is kept yet.

## Android

First run on Android, 2026-11-11: a Google Pixel 9 Pro XL (Tensor G4, Mali-G715 with Arm's driver 0xd803000 (v1.r54p3) and Vulkan 1.4.343, Android 17, 16 GB), in handheld mode with the on-screen controls. DroidPlay Core `main` at `95df9a63`, packed as a game app (`build_android_from_nsp.py --game-apk`: a 108 MB APK with the 3.7 GB RomFS as its OBB). Three launches, about 47 minutes, all driven over adb with `DM_CTL`.

- **The build:** the cartridge holds 1.0.3 (v196608), which the profile doesn't register, so it was packed from a profile derived from 1.0.5's. The rewriter finds Unreal's console variables by name in 1.0.3 too (`t.MaxFPS` at `main+0x50b6688`, `nvn.SyncInterval` at `main+0x5add4a8`), so the 60 fps target holds. The split found all 5,434 shaders in 11 s, as in 1.0.5, and all translated to SPIR-V in 46 s, none failed.
- **Plays from a new game through H'aanit's first battles:** the language notice, the title, H'aanit picked on the traveler selection, her flashback ("One year ago…") and the return to S'warkii, the radar tutorial, the headman (the Linde scene and the Path Actions tutorial), then Provoke on both fledgling hunters in the plaza: two battles fought with Linde, both won. After the scene that follows, the objective is to leave west for the Whisperwood. Continued from the save below: the Path to the Whisperwood, its first chest, and the first monster battle (Battle Basics I and II, a Marmot broken with the bow and beaten: "Victory!").
- **Save and Continue:** the save tutorial comes after the hunters' scene, and the save monument stands by the headman's door. Saved in slot 1 (S'warkii, H'aanit level 2, 0:23); after a cold start the title offers Continue, which loads slot 1: H'aanit at the monument, level 2, 261 HP, 2,542 leaves, the Whisperwood objective.
- **Frame rate** (the target is 60; 300-frame windows' median frame times):
  - New game to the save, 26 minutes: median 52.1 fps, 38–60.
  - Continue to the Marmot, 10 minutes: median 58.7 fps.
  - The title, the battles and the Whisperwood hold 57–60.
  - S'warkii is GPU-bound on the Mali (GPU 17–19 ms a frame, against about 7 ms on an M4 Pro): 44–57 fps in the village, 38 on the save screen over it. No window under 30.
- **Sound:** CRIWARE's mix plays through the renderer's 6-channel output. Underruns were few and short: 41 ms of padding in the first launch's first seconds, and 17 ms once in the third, near the Marmot battle. A `DM_AUDIO_DUMP` has signal on the front pair from the logos to the end of each launch, battles included, with no gap over 2 s and as long as the launch (no lost blocks). The second, 2-channel output stays silent (the movie wasn't played). Not listened to by a person.
- **Picture:** the language notice's pictures, the title, the traveler selection's map and H'aanit's card all draw; her signature was drawn whole (the Mac stopped at "Haa…", [Open](#open)). The battle scenes and menus draw too. S'warkii's red-tinted edges are the area's own grading, as found on the Mac ([Rendering](#rendering)). The flashback and the night scene after the hunters are dark, as the scenes are lit.
  - Not compared with the Mac: on the Path to the Whisperwood, pale, sharp-edged areas at the top and bottom of the screen where the blurred foreground meets the background. Higher up the path they look like mist behind the trees; the Mac hasn't been played this far.
- **Red lines:** `virtual pool remap … failed: 5`, 26–55 a launch. Android can't alias the private memory a virtual pool maps; the page table keeps the mapping, so textures still read it, and S'warkii's streamed textures drew. Also `[vk] buffer textures are not on Vulkan yet` once a launch, with no effect seen. While pipelines build in the background their draws are left out (141 and 96 in the two longer launches), as on other games.
- **Memory:** the process's memory cgroup peaked at 3.39 GB from the new game to the save, and 3.53 GB over all launches. That is well under the cap Android 17 puts on each app on the Pixel (8 GiB in memory, then 4 GiB of swap before `MemoryLimiter` kills it), with no swap and no limiter event. PSS was 2.84 GB, of which 0.81 GB graphics and 0.10 GB native heap. Never killed.
- **Driving it over adb:**
  - `env.txt` with `DM_CTL` goes in the game app's external files. That folder must be made by the app's first start, not by adb, or the app can't use it.
  - `DM_PAD_SCALE=0.6` keeps the on-screen buttons off the radar.
  - From the title: A, A (New Game), L, L (H'aanit), A, then Down, Up (the cursor), A.
  - The opening takes about 400 A presses at 0.6 s; the radar tutorial closes with B.
  - Talking and Path Actions need H'aanit level with the person (the same depth on screen), facing them. Y offering only Examine means nobody is in front. The headman stands by his door, so stop at the door ("Open"), then turn right to him. The save monument opens from in front of it, facing up.
- **Not tried:** a person playing with the on-screen controls or a controller; `DM_FPS_TARGET=30`; past the Whisperwood's first battle; the other devices but the Retroid Pocket 5 (below).

Second device, 2026-11-12: a Retroid Pocket 5 (Snapdragon 865, Adreno 650 with Qualcomm's driver 0x802ea000 and Vulkan 1.1.128), as a game app from `main` a50dfcb0.

- **The boot crash:** every start crashed about 3 s in, before the first frame was presented (`CRASH sig=11 addr=0x2f100000058 pc=…(vulkan.adreno.so+0x170020)`, thread `NVN queue repla`). The driver crashes in `vkCreateFramebuffer` for the game's 32×32×32 colour-grading LUT, drawn as 32 layers into one A2B10G10R10 target: a layered framebuffer small enough for the GPU's tile memory. Such passes now get scratch colour slots on Adreno 6xx: [A small layered render pass crashes the Adreno 650's driver](../../../docs/reference/rendering.md#a-small-layered-render-pass-crashes-the-adreno-650s-driver-android).
- **With that:** from a new game through the title, H'aanit's flashback, S'warkii, the radar tutorial and the walk toward the headman, at about 49 fps (frame p50 20.4 ms), 2.16 GB PSS. The grading looks as on the Pixel: S'warkii's red-tinted edges and its bluish mist. The same two red lines as on the Pixel. Not played further: no battle, save or Continue here yet.

## Found on this game

General changes first needed here; each applies to every game:

- **Rewriter:** a 64-bit bounds check of a jump table's index: [64-bit bounds check of the index](../../../docs/reference/rewriter.md#64-bit-bounds-check-of-the-index).
- **Provisional profiles:** Unreal's 64 GB alias layout only with virtual address memory (`profile_guess.py`): [Unreal's engine address region](../../../docs/reference/memory.md#unreals-engine-address-region-and-its-options).
- **NVN:** `nvnTextureBuilderGetSparseTileLayout` / `nvnTextureGetSparseTileLayout`: [The sparse tile layout of a texture](../../../docs/reference/nvn-objects.md#the-sparse-tile-layout-of-a-texture); every virtual pool with a range of its own until its first mapping decides: [Virtual pools of one texture each](../../../docs/reference/nvn-objects.md#virtual-pools-of-one-texture-each-mapped-before-and-after-the-texture); sparse textures' block height: [Sparse textures take the block height of their 64 KB tile](../../../docs/reference/rendering.md#sparse-textures-take-the-block-height-of-their-64-kb-tile).
- **Audio:** the update lock without `SdkMutexType`: [No `SdkMutexType` in SDK 3](../../../docs/reference/audio.md#no-sdkmutextype-in-sdk-3).
- **Android, Adreno 6xx:** small layered render passes padded past the tile memory: [A small layered render pass crashes the Adreno 650's driver](../../../docs/reference/rendering.md#a-small-layered-render-pass-crashes-the-adreno-650s-driver-android).
- **Frame rate:** Unreal console variables registered by inlined static constructors, from a page base made far before the name: [Unreal's frame limit and present interval, found by name](../../../docs/reference/frame-rate.md#unreals-frame-limit-and-present-interval-found-by-name).

## Open

- On the Mac, a battle and the sound are not tested (both are on Android: [Android](#android)), nor the iPhone; the IPA (3.6 GB) is built but not run on a device.
- The travelers' signatures on their cards stop part-drawn ("Opli…", "Haa…"): not looked into. On the Pixel, H'aanit's was drawn whole.
- On Android: S'warkii's GPU time on the Mali (17–19 ms a frame, 44–57 fps), and the pale areas on the Path to the Whisperwood, not compared with the Mac ([Android](#android)).
- The two untranslated compute shaders (above).
- At 60 fps: CPU-side long frames are 2 to 2.5 times as frequent as at 30 over the same route ([Frame rate](#frame-rate)), not looked into; and the game's speed at 60 is not compared on a walk yet.
