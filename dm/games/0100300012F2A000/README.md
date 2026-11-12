# Advance Wars 1+2: Re-Boot Camp (`0100300012F2A000`)

Base game 1.0.0 (v0), the only version, SDK 10.4.1 (The Great Ace Attorney Chronicles' `sdk` and movie module builds, [010036E00FB20000](../010036E00FB20000/README.md)). Unity 2020.2.1f3 IL2CPP on NVN; FMOD sound through `AudioOut`; Bink 2 movies (`.bk2`) decoded by Bink's Unity plugin in `main`; Pia / NEX for online play. Modules `main`, `subsdk0` (`NintendoSDK_movie`, which `main` imports from; the movies seen so far, the opening among them, are Bink's) and `sdk`. Plays on the iPhone (IPA 7.1 GB), and on Android through Field Training's first lesson ([Android](#android)).

On the Mac: the boot, the Bink opening movie, the title, Nell's introduction, a new casual campaign and the first training battle (Field Training, Troop Orders); sound, about 2.5 GB resident and 1.6–1.9 GB of Metal allocations, level over 15 minutes with no red line.

## What it needs

| Setting | Where | Why |
|---|---|---|
| Node area cut 1 GB → 62 MB, and 2 MB alignment for regions of 4 MB and more (SDK 20's) | `dm/tools/sdk_patches.py` SDK-wide rules, `sdk` build `d9add76f…` | StandardAllocator's region (more than 1 GB) aborted in `nninitStartup`; see [Memory](#memory) |
| `sys_resource 0x1000000` | [`game.tsv`](game.tsv) | the NPDM declares 16 MB of system resource (virtual address memory) |
| 5 GB block with a 2 GB pool: `mem_reserve 0x140000000`, `mem_alias 0x118000000`, `mem_stack 0x10000000`, `app_pool 0x80000000` | `game.tsv` | Engage's 5 GB block (4.375 GB alias region). The heap check's 1 GB pool ran the game's malloc dry at the first loading screen |
| `pad_layout full` | `game.tsv` | the 3D gamepad layout: the map cursor moves with the D-pad |

## Frame rate

- 60 fps in the menus, 30 fps in battle by the game's own limit (present interval 1, the frame's work 33 ms with the CPU and GPU mostly idle).

## Memory

- The NPDM declares virtual address memory: `nninitStartup` (`main+0x365310`) hands pool − used to StandardAllocator as one address region and `main` sets no heap; Unity reserves its own regions beside it.
- **Resolved: `StandardAllocator::Initialize` aborted in `nninitStartup`** (`sdk+0x2edf90`, its `CentralHeap::Init` at `sdk+0x2ee060`; the heap check reported "the host stopped before nnMain"). The `sdk` build is The Great Ace Attorney Chronicles', which has no virtual address memory. Its AddressRegionManager constructor (`sdk+0x340e90`) loads the node area with `orr w8 / w9, wzr, #0x3fe00000` (`e8230b32` at `+0x340ea0`, `e9230b32` at `+0x340f3c`), the SDK 7 / 8 form, so the search for the `mov` form finds nothing there. `AllocateAddressRegion` (`sdk+0x341030`) aligns a region by its size (64 KB under 2 MB, 2 MB under 4 MB, 4 MB under 32 MB, 32 MB under 1 GB, else 1 GB, at `+0x34109c`), as DRAGON QUEST XI S's SDK 7.3.2 build, and the region is more than 1 GB. The cuts: both `orr` → `mov w8 / w9,#0x3e00000` (62 MB) and `orr w10,wzr,#0x40000000` → `mov w10,#0x2000000` at `+0x34109c` (32 MB, as from 32 MB up). Pikmin 4's SDK 10.4.8 build ([0100B7C00933A000](../0100B7C00933A000/README.md)) has the same cuts at the same offsets.
- **Resolved: then the frames stopped at the first loading screen, a graphics worker at 100% CPU** (17 s in, `UnityGfxDeviceWorker` running, the main thread waiting on a condition variable, no red line). The heap check had set a 1 GB pool (the hardware pool had used the alias region up to +4.25 GB within seconds), as for the other Unity games with virtual address memory, and that left the game's malloc too little: Unity's GPU memory pool block allocation (`main+0x96f430`) calls `aligned_alloc` through `main+0x866810`, halves the request after each failure, and once the request rounds to 0 calls on for ever with a size of 0. `sample <pid>` on the Mac host showed the spin (the guest frames are `???` in the host's image list; subtract the module base from the log's `base` lines); it worked here where lldb does not.
- **Current:** a 2 GB pool. Through 15 minutes of the title, the opening movie, the menus and the first training battle: 2.26 GB of the alias region mapped, its high-water mark +3.27 GB; the process holds about 2.5 GB on the Mac, 1.6–1.9 GB of it Metal allocations. The 1 GB of the heap check is a starting point, not a measurement ([dm/games/README.md, Adding a game](../README.md#adding-a-game)).

## Movies

- The opening and the other movies seen so far are Bink 2 (`.bk2`), decoded by Bink's Unity plugin in `main`. Their 32 shaders are loose in `main` ([Files and shaders](#files-and-shaders)); without them every movie drew white.

## Files and shaders

- Everything is in Addressables bundles under `Data/StreamingAssets/aa/Switch`, read as Engage's (`unityfs.py`). `romfs_marker` is `Data/StreamingAssets/music.bank`.
- 20,424 shaders, all of which build: 20,392 from the bundles and Unity's 11 GLSLC outputs in `main`, and Bink's 32 (2 vertex, 22 pixel, 8 compute).
- **Resolved: every movie drew white.** Bink's movie player builds its programs from 32 control sections and code areas in `main`'s read-only segment that are in no GLSLC output and no BNSH file. 26 are 0x20-byte records in two tables in `.data` (`{code area pointer, control section pointer, u32 code length, u32 control length}`, both pointers relative relocations). The code takes the other 6 by address (`adrp` + `add` to the control section and, a few instructions away, to the code area it copies with `memcpy`); the code area lies right after the control section's own length (+0x20, 16-byte aligned) or right before it, and two control sections share one code area. Both neighbours can pass the header and length checks, so the reader (`shader_split.py` `raw_shaders`) takes only a code area the code builds the address of, the nearest one to the control section's. The 8 compute shaders' code areas have no header (SDK 10). Without them the shaders were not in the map (two `[RED] shader … is not in the shader map` lines and `program has no vertex shader` as the opening movie starts). Of 25 `main`s on hand no other has such control sections.

## Input

- The 3D pad layout: the map cursor moves with the D-pad (the tutorial battle was played with it on the Mac).

## Packing

- A regional release of the same build (`0100300012FFF000`, issue #114) packs from a profile derived from this one, with the folder's title ID and `main.npdm`'s program ID (`same_build`, `game.py` `by_build`; [development.md, The packing script in detail](../../../docs/development.md#the-packing-script-in-detail)).

## Mac routes

- The work folder's `run/step.sh <shot> <wait> <presses…>` drives a run started with `DM_CTL`. About 22 s into a boot the opening movie plays: A skips it, `L+R~0.5` opens the main menu (the first time Nell's introduction, A about 25 times, then the file select); A (Campaign), A, A (Advance Wars, the file), A, A, A, A (the mission, Field Training, Troop Orders) start the first battle.

## Android

First run on Android, 2026-11-11: a Moto Razr Plus 2023 (SM8475, Adreno 730 with Qualcomm's own driver 0x80267062, Android 16), unfolded, in handheld mode with the 3D on-screen layout. DroidPlay Core `main` at `9811908b`, packed as a game app (`build_android_from_nsp.py --game-apk`, 359 MB APK with the 7.1 GB RomFS as its OBB). Three launches, about 55 minutes.

- **The build:** the registered profile, with no derived one; the split found all 20,424 shaders in 16 s, and all 20,424 translated to SPIR-V (5 min 10 s on the Mac, none failed).
- **Plays from a new game through Field Training's first lesson:** the Bink opening movie, the title, Nell's introduction, Campaign → Advance Wars → New Game → Casual → Field Training → Troop Orders, then the lesson's battle: two infantry moved, one ordered to Wait, an attack with Fire, End Turn, the enemy's turn, then Quick Fire to finish the enemy on day 2 ("Lesson complete!"). Then the second lesson, Cities & Terrain: the four units' captures, Fire and the mountain's cover through day 2, then Exit Map (Field Training doesn't save a lesson left part way).
- **Save and Continue:** the game saves by itself at the lesson's end (`save commit #6` with "Lesson complete!"). After a cold start the main menu opens without Nell's introduction, and the file shows "Next Lesson: Cities & Terrain", with Troop Orders ticked.
- **Frame rate, the game's own:** 60 fps in the menus and 30 in battle by its own limit (present interval 1 throughout; frame work 33 ms with the replay at 7–8 ms and the GPU at 13–16 ms). In battle, every 30 s window is 29.7–30.0 fps (one at 36, with a stretch at 60 between scenes), over 14 minutes of the first lesson and 17 of the second; frame p50 33.2–33.4 ms, p95 36.5–40 ms; 150–230 draws a frame. Menus 59–60 fps.
- **Hitches:** 32 frames over 60 ms in the first lesson's 27,500, 45 in the second's 33,100:
  - the switch into each 3D battle animation (0.1–0.35 s, the replay idle: Unity's own scene load);
  - the first sight of each animation, whose pipelines are built then (0.3–0.8 s; 138 pipelines in the first launch, kept for later launches);
  - frames of 65–90 ms in the animations' busiest moments (400–500 draws a frame). The animations are short: about 2–4 s of such frames in each lesson.
  - While a pipeline is built in the background its draws are left out (792 in the first launch, 311 in the next, as on other games); nothing missing showed in the screenshots.
- **The menus after a battle can stay at 30 fps:** back on Field Training's menu after either lesson, the menu ran at 30 fps with the GPU busy 24 ms a frame, against 60 fps and 13 ms on the same menu after a cold start. The NVN calls, draws (68), passes (22) and the replay's own copies per frame were the same; the submission's CPU time doubled too (3.9 → 8 ms). A few taps on an empty part of the screen brought it back to 60 fps and 13 ms at once, and it stayed there: the battle's light frames at 30 fps leave the 730's GPU (and CPU) clocks low, and a menu that then takes 24 ms a frame keeps them there. The taps' input boost raises them. The runs above were driven by `DM_CTL`, which sends no touches; with the on-screen controls each press is a touch. Not tried with a controller.
- **Sound:** FMOD plays through `AudioOut` (AAudio, 48 kHz stereo) with no underrun in any launch. A `DM_AUDIO_DUMP` has sound in the opening movie, the menus and both battles; the game's `AudioRenderer` output stays silent. Not listened to by a person.
- **Picture:** nothing wrong seen: the movie, the title art, Nell, the 3D board with its forests, mountains and cities, the troops and their HP, the movement and attack ranges, the menus, the blur behind "Lesson complete!", and the plains and mountain battle animations with their sky and effects. No `[RED]` line in any launch. Not compared with the Mac, as nothing needed it.
- **Memory:** the alias region mapped to 2.26 GB (as on the Mac); 2.35 GB PSS 20 minutes into both long launches (1.4–1.6 GB resident, the rest in zram), high-water mark 2.18 GB. On this 8 GB phone (7.46 GB usable) lmkd killed 13 background apps over the session ("PSI critical event"), never the game.
- **Driving it over adb:** `env.txt` with `DM_CTL` in the game app's external files (`chmod 666`). The movie starts about 22 s in; A skips it and `L+R~0.5` opens the main menu. Nell's introduction takes about 20 A presses. On the board each D-pad press moves the cursor one tile. Nell's lines and the troops' tips (Quick Fire, holding ZR) appear without warning and take the next presses, so look after every move. A selects a unit, a tile, then the command; A on an empty tile opens the Map menu (End Turn is its third item). To leave a lesson: + → Options → Exit Map, then Left to Yes (No is preselected).
- **On Xclipse too:** a Galaxy Z Flip 7 (SM-F766U1: Exynos 2500, Xclipse 950 with Samsung's driver 24.0.533 / 0x6000215, Vulkan 1.3.279, Android 16), unfolded, 2026-11-11, the same game app. Two launches, about 20 minutes.
  - **What was played:** a new Casual campaign through Field Training's first lesson (won on day 2), the save (`save commit #6` at "Lesson complete!"), then a cold start (the file shows "Next Lesson: Cities & Terrain"), and the second lesson through its first day and the enemy's turn.
  - **The picture:** troops, the map, its cities and the battle scenes (plains and mountain) all draw, as on the Adreno. Another Android port of this game draws no troops or map on Xclipse; this build doesn't share that fault. The textures are BC, which Xclipse lacks, so they are decoded on the CPU. No `[RED]` line.
  - **Frame rate:**
    - Battles: 29.7–30.0 fps in every 30 s window (frame p50 33.3 ms, p95 about 36 ms, GPU about 12 ms). Frames over 60 ms were 12 of 11,300 in the first lesson: animation scene switches and one first-time pipeline build of 0.42 s.
    - Menus: 60 fps, including back on Field Training's menu after the battle (GPU 5 ms). The Razr's post-battle 30 fps menu didn't happen here.
  - **Sound:** no underrun; the dump has signal in the movie, the menus and the battle.
  - **Memory:** 2.94 GB PSS after the first lesson and 3.23 GB in the second, of which 0.59–0.86 GB is graphics. VmHWM 2.49 GB, no swap used, 11.2 GB on the phone. No lmkd kill.
- **Not tried:** past Field Training's second lesson, the other devices and Mali (the Pixel 9 Pro XL).

## Found on this game

- **Shader control sections loose in `main`** (`shader_split.py` `raw_shaders`): [Loose control sections and code areas in `main` (Bink 2)](../../../docs/reference/shaders.md#loose-control-sections-and-code-areas-in-main-bink-2).
- **`sdk` node-area and 1 GB alignment cuts in the `orr` form** of the SDK 7 / 8 constructor: [The SDK's address-region node area](../../../docs/reference/memory.md#the-sdks-address-region-node-area), [1 GB alignment of regions of 1 GB and more](../../../docs/reference/memory.md#1-gb-alignment-of-regions-of-1-gb-and-more).
- **The heap check's 1 GB pool is too small here**: [dm/games/README.md, Adding a game](../README.md#adding-a-game).
- The spin-wait search's store rule takes one wider loop in its `main`: [development.md, Power](../../../docs/development.md#power).
