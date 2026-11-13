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
| the audio pool's four deque functions under a mutex (`main+0xabd428`, `+0xabd4b8`, `+0xabd548`, `+0xabd5f0`) | [`patches.py`](patches.py) | see [The audio pool crashes](#the-audio-pool-crashes-resolved) |

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
- **Confirmed:** the tester saw no flicker in the keep with the cut (droidplay-core#444, AYN Thor Pro). PR #444's user confirmed the same cut on 1.0.12 on an iPhone. The keep's first room, reached on the Mac by following Hadvar, runs mode 7 too and draws no shadow mask; the lit rooms further in were not reached here.
- **The lower bits:** the dispatch writes a 4x4 ordered-dither matrix into the stencil's lower five bits ([Raw depth/stencil storage written as a buffer](../../../docs/reference/rendering.md#raw-depthstencil-storage-written-as-a-buffer)), which the cut leaves 0; no draw of the frames dumped tests or reads them.

## First-person draws left out while their pipeline builds

- **What:** the first-person model's colour draw tests depth `EQUAL` against a copy of its own depth-only draw, and the world's colour passes test `EQUAL` against that depth too, so where the model stands nothing else draws. On Android a draw whose new pipeline is still building in the background is left out until it exists; for this draw that shows the scene target's clear colour, (59, 77, 74) through the tone mapping, for those frames, not a frame-late model. Leaving out its colour draw on the Mac (`DM_NVN_SKIP_FS=af549618df61ad30`) gives the same colour.
- **Seen:** on an Ayn Odin 2 with an empty pipeline cache and slow background builds forced (`DM_VK_ASYNC_DELAY_MS=1500`), the old rule left the first-person view in the clear colour for seconds after a load. Such draws now build their pipeline at once ([Draws left out while their pipeline builds, over a depth pre-pass](../../../docs/reference/rendering.md#draws-left-out-while-their-pipeline-builds-over-a-depth-pre-pass-android)): the first two frames after that load took 447 and 92 ms, against 144 and 112.
- **Not the report's flat model:** droidplay-core#444's flat hands and weapons stayed with background builds off (`DM_VK_ASYNC_PIPE=0`) on the tester's phone. That was Qualcomm's stale low-resolution depth after the copy ([below](#the-first-person-model-drawn-in-one-flat-colour-resolved)).

## The first-person model drawn in one flat colour (resolved)

- **The report (droidplay-core#444):** first-person hands and weapons drawn as flat grey-teal shapes, (63, 77, 74), on an AYN Thor Pro (Adreno 740, Qualcomm's driver 0x802a4035), with `DM_VK_ASYNC_PIPE=0` and with `DM_VK_POS_ROWS=1` too.
- **Repro:** on an Ayn Odin 2 (Adreno 740, driver 0x802a4000), the tester's quicksave with the axe drawn, loaded and looking down at the first room's gate: flat every time. The axe equipped in the session draws, and so do the Mac and Turnip (PurpleVK T30) on the same phone.
- **The draws:** a depth-only draw (vertex `6326d1201b3be710`) into the scene depth s26 (`D32_SFLOAT_S8_UINT` 1600×900), a copy of its 1280×720 region into s35, and the colour draw (`f7057c92d3b43ddb` / `4cc831b81dfc0b2a`) depth-`EQUAL` against s35, without depth writes. s35 gets its depth from that copy alone, every frame.
- **Cause and fix:** Qualcomm's driver kept a stale low-resolution depth for s35 that the copy didn't reset; the first pass on s35 after the copy now begins with a depth-writing draw of no pixels ([A depth image a copy wrote keeps a stale low-resolution depth on Qualcomm's Adreno driver](../../../docs/reference/rendering.md#a-depth-image-a-copy-wrote-keeps-a-stale-low-resolution-depth-on-qualcomms-adreno-driver-android), `DM_VK_COPIED_DEPTH`).
- **Not checked:** the Thor Pro's driver itself.

## Unlocks before SignalLightEvent (open)

- **What:** 552 inlined unlocks in 1.1.404's main are a plain `str wzr`, then `bl nn::os::SignalLightEvent`, then `dmb ish` (1.0.12 has 517; PR #444 cut them to release stores there).
- **No lost wake here:** 1.0.12 loses wakes after them because SDK 3.4's `SignalLightEvent` reads the event with `ldarb` and skips its write when the event is signalled already. SDK 14.3's reads it after a `dmb ish` (`sdk+0x123868`), so this build cannot lose a wake that way.
- **Ordering gap:** nothing orders the critical section's stores before the plain unlock. A native litmus test sees another core read the old data with the plain store (on an Odin 2's Snapdragon 8 Gen 2 cores and on an M5 Max), never with `stlr`; no failure of the game is tied to it. Release-store cuts for all 552 (Armv8.0 forms) are held on branch `android/skyrim-1-1-404-cuts` (c234dce8), not in this build.
- **The report's BSTaskManager crashes** are not these unlocks: see [The audio pool crashes](#the-audio-pool-crashes-resolved).

## The audio pool crashes (resolved)

- **The report (droidplay-core#444):** two SIGSEGVs on thread `BSTaskManager` at load-like moments (a door, getting up after a knockdown) on an AYN Thor Pro: `pc=sdk+0x1ca880 lr=main+0xac0d24` with a garbage x0, and `pc=main+0xabd5c8 lr=main+0xac11bc` at address 0. The second came once on the Mac too (M5 Max, thread `LibAudioUpdate`, 620 s after launch, garbage address), in none of six later 12-minute runs.
- **The pool:** the object at `*main+0x219afe8` holds the game's streamed-sound buffers: a memory pool (`nn::audio::MemoryPoolType` at +0x170) and two libc++ `std::deque<void *>` free lists, wave buffers at +0x1c0 (each an `nn::audio::WaveBuffer` over a 4 KB block of the pool) and ADPCM header records at +0x1f0. Four functions are their only users: `main+0xabd548` takes a wave buffer (checks the deque is not empty, pops it, `nn::audio::CopyMemoryPoolData` into it), `+0xabd5f0` gives one back, `+0xabd428` / `+0xabd4b8` take and give back a header record. They have 8 call sites, and the pool pointer is loaded in 4 places.
- **Who calls them:** BSTaskManager when a sound loads (`main+0xac0cd8`: a header record for `nn::audio::ParseAdpcmHeader`, then the first fill, `main+0xac0f48`), LibAudioUpdate when it refills a stream (`main+0xac134c`) and whoever drops a stream's last reference (its destructor `main+0xabfaf8` gives everything back). Probes every 25th hit over 200 s: about 10,000 takes on LibAudioUpdate, 6,000 on BSTaskManager, 12,000 give-backs, in the same seconds.
- **Cause:** nothing locks the deques (the voice functions beside them hold a lock of their own, `main+0x219afa8`; the pool functions do not). A pop and a push at once lose an update of the deque's start or size, or one moves the map the other reads, and a later pop hands out a slot nothing filled: the garbage header pointer and the null or garbage wave buffer above. Both faulting pops check for an empty deque; the deque was inconsistent, not empty. The released-buffer path plays no part: a stream re-appends its own buffers as `nn::audio::GetReleasedWaveBuffer` returns them (`main+0xac35bc`) and gives them back to the pool only when it is destroyed or a fill fails, and the SDK's own renderer code, which the host runs, decides what is released.
- **The Switch** runs the same unlocked code: no lock, priority or core mask keeps the two threads apart (LibAudioUpdate is pinned to core 2 at priority 29, BSTaskManager may run on cores 0–2 at 44). The window is a few instructions wide, so how often it shows depends on how often the two threads meet in it; that rate was not measured on a Switch.
- **Fast repro:** probes that sleep 300 µs inside the take and the give-back (`DM_PROBE=main:abd594~300,main:abd660~300`, [05-debugging.md](../../../docs/agents/05-debugging.md#probes-without-a-debugger-dm_probe)) widen the window: all four runs from the Helgen save crashed 62–103 s after launch, once in the pool itself (`pc=main+0xabd664`, a give-back writing through a garbage slot, on LibAudioUpdate) and three times in the job system (`main+0x5e3418` on JobThread1, twice; a call to a heap address from `main+0xaeab68` on the main thread). The probes are the same with the cut and none of these comes back, so those three come from the pool as well, most likely its writes through stale slots into other heap objects. A third report from the Thor (a cave entrance, on 7c263999) has that last form: a JobThread calls through an `IAnimationSetCallbackFunctor` whose vtable pointer points into the heap (`pc=` the fault address, `lr=main+0xa7d21c`, under `main+0xaeab6c`). That it comes from the pool is likely, not proven.
- **Cut (current):** each of the four entries branches to a wrapper in the zero padding after the text (`main+0x1265a00`–`+0x1265b3c`, inside the text's executable page) that holds an `nn::os::MutexType` around the original function: `LockMutex`, the function with x0–x3 as they came (its first instruction runs from the wrapper, which branches on to the second), `UnlockMutex`, its x0. The mutex is the first 32 bytes after the bss the module uses (`main+0x3a85800`; MOD0's bss ends at `+0x3a857d0`, the NSO's at `+0x3a86000`, and no code or relocation names an address past `+0x3a857cc`); zeros are an unlocked non-recursive mutex to SDK 14.3's `LockMutex` / `UnlockMutex` (`InitializeMutex` writes nothing else they read). `dm/tools/tests/test_skyrim_audio_pool.py` runs the wrappers in unicorn. With the cut, the same probes: four runs of 360 s, no crash, sound playing (renderer 0: 23,541 of 24,000 frames not silent); unprobed, two runs of 720 s past the Mac's 620 s crash, no crash (renderer 0: 142,541 of 144,000 frames not silent).
- **1.0.12** (seedds/nxnative PR #444's build) has the same pool with `std::vector` free lists and the same lack of a lock: `main+0xa26f0c`, `+0xa26f34`, `+0xa26f7c` (with `CopyMemoryPoolData`), `+0xa26fd4`, 8 call sites. Not cut here (the profile registers 1.1.404 only).

## Mac

On an M5 Max, a new game from the title through the cart ride, Helgen, character creation (named with `DM_KBD=Prisoner`) and the dragon attack to "Use L to move", where a held stick walks the player: 30 fps, 33.3 ms median frame time in every 300-frame window but one (41 ms), a resident footprint of 4.1 GB and 2.7 GB of GPU memory. One `[RED]` line in the whole run, `stage 1 cb11 has no uniform buffer bound` ([Open](#open)).

## Android

- **Galaxy S25 Edge (Adreno 830, Qualcomm's driver):** over adb from a new game, in a private save folder: the title, the main menu, the cart ride into Helgen, character creation (named in DroidPlay's text box), the dragon attack and the first steps with the left stick. 30 fps: the frame time's median is 33.0–33.5 ms in 64 of the 69 300-frame windows, the others 33.8–39.6 ms (the first at boot, and loads). 3.2 GB PSS. Both audio renderers produce output (renderer 0: 142,944 of 144,000 frames not silent); not listened to. The game wrote its character-creation save and an autosave; neither was loaded back.
- **All 23,133 shaders translate** for Vulkan. One `[RED]` line, 8 times when the opening loads: `[vk] shader e8910903259b956c reads uniform slot 11, which has no buffer bound: it reads 0`, the Mac's cb11 line.
- **Ayn Odin 2 (Adreno 740, Qualcomm's driver):** the tester's saves in Helgen Keep, loaded in a private save folder: the first room with the axe drawn ([The first-person model drawn in one flat colour](#the-first-person-model-drawn-in-one-flat-colour-resolved)).
- **Not tried:** the other devices; a stretch played by hand (real-time action: its Playable evidence needs a person).

## Mac test controls

`DM_CTL` presses of A held 0.5 s pass the title ("Press any button"), pick New and answer Yes. Character creation opens about six minutes later; Y finishes it and A confirms, then the game asks for a name: run with `DM_KBD=Prisoner`, or with no window the keyboard returns cancel.

## Found on this game

- [FXP shader records in Bethesda BSA archives and in main](../../../docs/reference/shaders.md#fxp-shader-records-in-bethesda-bsa-archives-and-in-main).
- [A linear texture whose stride is shorter than its rows](../../../docs/reference/nvn-objects.md#a-linear-texture-whose-stride-is-shorter-than-its-rows).
- [Raw depth/stencil storage written as a buffer](../../../docs/reference/rendering.md#raw-depthstencil-storage-written-as-a-buffer).
- [A depth image a copy wrote keeps a stale low-resolution depth on Qualcomm's Adreno driver](../../../docs/reference/rendering.md#a-depth-image-a-copy-wrote-keeps-a-stale-low-resolution-depth-on-qualcomms-adreno-driver-android).
- [Draws left out while their pipeline builds, over a depth pre-pass](../../../docs/reference/rendering.md#draws-left-out-while-their-pipeline-builds-over-a-depth-pre-pass-android).

## Open

- **`[RED] stage 1 cb11 has no uniform buffer bound`** on the Mac, once, when the opening loads, and Android's `shader e8910903259b956c reads uniform slot 11` (PR #444's 1.0.12 note has it too). Nothing missing was seen.
- **The main menu's "Start a new game?" box** draws as two vertical lines the height of the screen beside its text, on the Mac and on the S25 alike; not compared with the Switch.
- **The 1280x720 texture of 3840-byte rows** (made at "Start a new game?" → Yes) is uploaded as the GPU would read it; what it holds and where it shows is not known.
- **Helgen Keep's flicker after the cut:** fixed on the tester's AYN Thor Pro (droidplay-core#444); not seen in the keep's lit rooms on our devices ([Helgen Keep's lighting](#helgen-keeps-lighting)).
- **The unlocks before `SignalLightEvent`:** see [Unlocks before SignalLightEvent](#unlocks-before-signallightevent-open).
- **The audio pool cut on a device:** not yet run on Android or played by hand at the report's doors and knockdowns ([The audio pool crashes](#the-audio-pool-crashes-resolved)).
- **The iPhone:** the regions need more than its alias region holds (see [Memory](#memory)).
