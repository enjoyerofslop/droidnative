# Mario Kart 8 Deluxe (`0100152000022000`)

Updates 4.0.0 (v1441792) and 4.0.1 (v1507328) over the base game, SDK 4.4.0, the oldest SDK until [Bayonetta 2](../01007960049A0000/README.md)'s 3.6.0. Nintendo's sead / agl / gsys engine with NintendoWare (G3d, Ui2d, Vfx, Atk) and Pia networking, on NVN. Modules `main`, `subsdk0` (the SDK's movie library: the menus' H.264 previews) and `sdk`. RomFS is mostly Yaz0-compressed SARC (`.szs`), BFRES models and BNTX textures, which the game reads itself. Plays on the iPhone (A20 Pro): 60 fps docked with about 6 ms of GPU time a frame, a 2.4 GB footprint with 3.7 GB of headroom, no audio underruns. Mii heads draw nothing (no firmware); see [Miis](#miis).

The 4.0.1 build has the same `subsdk0` and `sdk` build IDs as 4.0.0 and a different `main` build ID. This profile has no build-specific function patches. [A 4.0.1 iPhone report](https://github.com/seedds/nxnative/issues/281) covers the title, menus and a complete three-lap Grand Prix race after the shared notification-wait fix. A second 4.0.1 build from current upstream, with Booster Course DLC and a derived profile, completed a full race on an iPhone 15 Pro Max (iOS 27.0.1) and on a Mac. The registered profile's combined shader tables and Mac build passed shader and pipeline prebuild checks; gameplay on a build made from this registered profile has not yet been tested. A build from the registered profile needs both update NSPs in the input folder.

On Android it plays two 50cc races at 60 fps on a Pixel 9 Pro XL, steered by the game's Smart Steering; on a Moto Razr Plus 2023 (Adreno 730) at about 45 fps, since a crash at every course load was fixed ([Android](#android)).

Brought up on the Mac from 4.0.0: boot, the title with its demo race, the Mii pick, the menus (their movie previews play), a 50cc Grand Prix race at Mario Kart Stadium to its results, and a second boot that loads the save. 60 fps (p50 16.7 ms), sound; about 2.4 GB resident and 1.26 GB of Metal allocations in the race, flat over minutes.

## What it needs

| Setting | Where | Why |
|---|---|---|
| `render_cond on` | [`game.tsv`](game.tsv) | the race records `SetRenderEnableConditional` as a course loads: evaluated at replay, as on the GPU (drawn anyway, the same race route at the same frames looked the same; evaluated is NVN's behaviour) |
| 4 GB layout: `mem_reserve 0x100000000`, `mem_alias 0x10000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000` | `game.tsv` | no virtual address memory: the game sets a 3.03 GB heap (pool − 64 MB) in the 3.25 GB heap region |
| `sys_resource 0x0` | `game.tsv` | the NPDM declares 0 MB of system resource: `IsVirtualAddressMemoryEnabled` is false, as on Horizon |
| `modules main subsdk0 sdk` | `game.tsv` | every module `main` imports from |
| `shader_groups` (`/MapObj/`, `/Course/`, `/UI/`, `/Kart/`, `/Driver/`, …) | `game.tsv` | the shader split's groups; see [Files and shaders](#files-and-shaders) |

## Miis

The game builds Mii heads from the console's MiiModel system data, starting at boot for the title's demo race, and lists the six default Miis for its "Select a Mii". Firmware content is not the host's to ship, so Mii heads draw nothing while bodies and favourite colours show.

- **Current: the Mii database** (`hle_mii.c`). The first boot logged `[RED] sf: the game connects to service mii:e … mii:u itself`, then aborted: `nn::mii::Database` keeps an `IDatabaseService` of the mii service at +0 (`Database::Initialize`, `sdk+0x1c5664`), and `AppendMii` / `ShowMiiEdit` start the MiiEdit applet. The host takes over the public methods: a console with no Mii of its own (an empty database: no index, nothing to update) that still has the six default Miis every console has. The game asks for those with `Get(…, 6, SourceFlag 2)` and never reads the count (`main+0x81e954`): its boot-time list of Mii icons (`main+0x419dc8`) builds a head model for each of the six, and zeroed entries failed the model's `CharInfoAccessor::IsValid` (`CharModel::Initialize` returned 0xd67e, `main+0x8f15b0`) and crashed at `main+0x8f152c`. A CharInfo the host builds is the default Mii's parameters with Switch common colours, a create ID with version 4 and variant bits (fixed per default Mii, so a saved choice finds the same Mii; fresh for `BuildRandom`, which the title's demo race calls for 12 racers) and the nickname "no name"; every field is within `CharInfoRaw::Verify`'s ranges (`sdk+0x1b68c8`). The Mii editor is cancelled (0xE7E, which `ShowMiiEdit` itself treats as success).
- **Current: the MiiModel stand-in** (`dm_mii_standin` in `hle_mii.c`, mounted by `hle_fs.c` `MountSystemData`; any other system data answers "target not found"). The game aborted in `fs::detail::GetFileSystemProxyServiceObject` under `fs::QueryMountSystemDataCacheSize` (`main+0x8f23bc`): it mounts system data 0100000000000802, MiiModel, as `MiiResource:` and reads `NXTexture{Low,Mid}{Linear,SRGB}.dat` and `Shape{Mid,High}.dat` whole; the SDK's Mii rendering is linked into `main` (`main+0x8f1400`–`+0x8fc000`). The host writes a stand-in of the same layout with every part empty. The layout as the code reads it:
  - texture file: +0xc the largest decompressed size of each of 11 part kinds, +0x38 their alignments, from +0x64 one 0x1c-byte entry per part (offset, size, stored size, 4 zlib parameters, then width, height, format, mips);
  - shape file: +0xc / +0x3c the same for 12 kinds, from +0x6c one 0x58-byte entry per part (offset, size, stored size, parameters, five vertex attribute offsets and sizes, index offset and byte size, bounding box), then hair (132 × 0x48, +0x12704) and faceline (12 × 0x24, +0x14c24) transforms.
  - A texture of size 0 is skipped (`main+0x8faaf4`). Shapes cannot all be absent, because the faceline is drawn without a check (a null buffer read at `main+0xa690d0` under `main+0x8286c4`), so every shape entry points at one shared mesh of one vertex and the triangle (0, 0, 0), 32 bytes of zeros in a stored zlib block. The largest sizes must not be 0: they size the model's memory pool (`main+0x8f2e6c`), whose alignment is the first one.

## Files and saves

- **Resolved: SIGSEGV in `crypto::detail::CbcModeAes128Helper::DecryptBlocks` with a null destination** (`main+0x8737e8`, right after `aoc:` is mounted). The add-on content (0100152000023001: `contents.dat` and `version.txt`; the courses are in the update) is decrypted in `AocHeap`, a 0x3130-byte heap that also holds the mount cache. The host answered `QueryMountAddOnContentCacheSize` with 4 KB, and the 0x1400-byte decryption buffer then did not fit. On Horizon the cache is the RomFS's file table as `RomFsFileSystem::GetRequiredWorkingMemorySize` sizes it: both hash tables (4 bytes a bucket, the builder's bucket count) and all directory and file entries (0x18 / 0x20 bytes plus the name, padded to 4), 0x88 bytes for these two files. The host computes that from the folder it mounts (`romfs_work_size` in `hle_fs.c`); `rom` keeps its minimum answer, which is too small rather than too large.
- **Resolved: every boot asked to pick a Mii again** (`DM_FS=1`: `UserSave:/userdata.dat` not found although the host save had it). The game mounts `CommonSave` with `MountDeviceSaveData` and `UserSave` with `MountSaveData(uid)` (`main+0x8b0c84`), two saves on Horizon; the host made device save data the account save (for Animal Crossing: New Horizons, which mounts only device save data), so both names shared one directory. At boot the save manager deletes `CommonSave:/userdata.dat` (`main+0x8b1910`, through its file device's `DeleteFile`, `main+0x633afc`; a probe there with `@*x1+8` shows the name) and commits, and in the shared directory that was the account save's own file. A game whose `main` imports `MountSaveData` too now gets its device save as `<DM_SAVE>_device`, a transaction of its own (`hle_fs.c`); of the games on hand only this one imports both.
- `romfs_marker` is `UI/cmn/movie/StaffCredits.mp4`.

## Audio

- **Resolved: an incomplete first command list permanently selected the wrong header layout.** The reproducing test from [PR #331](https://github.com/seedds/nxnative/pull/331) fails on the old host and produces stereo PCM with the fix; the PR author reports sound on the Mac with 4.0.1. Local validation uses synthetic command lists because this machine has no Mario Kart Mac build. See [Incomplete startup lists must not select the command layout](../../../docs/reference/audio.md#incomplete-startup-lists-must-not-select-the-command-layout).
- **Resolved: no sound; `[RED] audren: no DeviceSink (ID 0x10) in the command list, 0 commands of 0x148 bytes`.** SDK 4's command list has SDK 6's header, but its DeviceSink (`CommandBuffer::GenerateDeviceSinkCommand`, `sdk+0x19e690`) is ID 0xf and 0x130 bytes: device name +0x14, upsample buffer +0x118, input count +0x120, input indices as bytes from +0x124. `capture` takes the one 0x130-byte command with 1 to 6 inputs when there is no 0x148-byte one (`g_sink4` in `hle_audren.c`).
- **Resolved: the update lock.** Its `AudioRenderSystem::Update` (`sdk+0x19b77c`) locks an `nn::os::MutexType` at +0x1d0, not SDK 16's `SdkMutexType` at +0x1f0. The host took SDK 16's for every SDK before 20, which wrote a lock word into another field and excluded nothing; this was the first game it was plainly wrong for. `update_lock` in `hle_audren.c` now reads it off each SDK's own `Update`.

## Rendering

- **Resolved: a 2D array in a cube slot.** As a race loads, the game binds a one-layer 2D array (format 0x44) at slot 10 of two pixel shaders that declare a cube there, and it was bound as is (`texture type mismatch … declares slot 10 as Metal type 5, texture … is type 3`). The zero cube is now bound for a 2D array of fewer than six layers in a cube slot (`tex_fit`).
- The race records conditional rendering as a course loads; `render_cond on` evaluates it at replay.

## Files and shaders

- 29,785 shaders across 4.0.0 and 4.0.1 (12,579 vertex, 17,177 pixel, 28 compute, 1 geometry): BNSH in the courses' and objects' `.bfsha` / `.bfres` archives inside the `.szs` SARCs (courses, objects, karts, drivers), the effects' `.ptcl`, the layouts, agl's two BAHS sharcb and `main`; 19,012 variation pairs.
- The NSP script's Mac-only build (`--platform mac`) saves about 30,000 iOS shader compiles and the 12 GB IPA for this game ([development.md, A Mac-only build for development](../../../docs/development.md#a-mac-only-build-for-development)). The player README gives the IPA as about 11.9 GB.

## Rewriter

- The spin-wait search with the lock, test and store rules finds `main` 25 → 26 loops (a state setter like Breath of the Wild's, `main+0x715df8`) and one loop wider in `subsdk0` (the movie library's thread loop, `0x24118`) ([development.md, Power](../../../docs/development.md#power)).

## Mac routes

- The work folder's `run/ctl.sh` drives a run started with `DM_CTL`.
- `run/race.sh` boots from a copy of a save past the Mii pick into a 50cc Grand Prix (Mario, Mushroom Cup) with frame-timed keys and holds accelerate: `DM_KEYS=f960:L+R~0.3,f1260:A,f1500:A,f1740:A,f2000:A,f2240:A,f2400:A,f2560:A,f2800:A,f3040:A,f4300:A~70`.
- From a fresh save, L+R at the title opens "Select a Mii" (Right, A takes the first default Mii).
- 2P: from a save past the Mii pick, L+R at the title, Down, A (2P), A (Grand Prix), A (50cc) opens the controller applet; 1.5–4 s between presses, or the menu fades drop them. Headless runs report one player; two players need a second controller.

## Android

Played on a Google Pixel 9 Pro XL (Mali-G715, Android 16) on 2026-11-10, from `main` at `0d83f7df`, as a game app (`build_android_from_nsp.py --game-apk`), with adb button input:

- **The build:** the folder held the base game and 4.0.1 (v1507328), not 4.0.0, so the packing script used a profile derived from 4.0.1, with 4.0.1's own shaders: 29,651, all translated for Vulkan, none failed. The RomFS (12.1 GB) went beside the APK, as the app's OBB file.
- **Played:** from a new save: boot, the title and its demo race, L+R, Select a Mii (the six default Miis, their heads blank as on the Mac; see [Miis](#miis)), the menus with their movie previews, then Grand Prix, 50cc, Mario in the Standard Kart and the Mushroom Cup. Mario Kart Stadium's three laps, won (1st).
- **The steering:** the game's Smart Steering, on by default (the kart's antenna), with accelerate held over adb; no Auto-Accelerate switch was found on the kart screen. No race has been steered by hand, so how steering feels on a phone is not checked, and the game stays In-game until someone steers a race by hand with a controller.
- **Save:** six save commits by the end of the race. After the app was stopped and started again, L+R at the title went straight to the main menu with no Mii pick, so the save loaded. A second race from there was won too (15 points).
- **Frame rate:** 60 fps. Over each race the median frame time was 16.6 ms, with a p95 of about 20 ms. The worst 30 s was 56.6 fps on the first start (pipelines building, and the results menu after the race) and 59.1 on the second. GPU 9–11 ms a frame, 600–740 draws (1,262 at most), about 10 ms of replay CPU; on the title, GPU about 11 ms.
- **Memory:** 4.3–4.4 GB resident, against 2.4 GB on the Mac: the Mali-G715 has no BC textures, so they are decoded on the CPU.
- **Sound:** 390 s of the audio renderer's stereo output from the cold start through the second race (`DM_AUDIO_DUMP`), as long as the run took: −26 to −37 dBFS, spectra like music, no clipping. 3 underruns on the first start, in the menus; none on the second.
- **Red lines:** two, from the title on. Nothing wrong showed on screen; the picture was not compared with the Mac.
  - `[vk] a GPU block encoder draws into a BC texture decoded on the CPU (format 137): only BC4 and BC5 are decoded on the GPU, the pass draws into the decoded image`: a GPU without BC textures only (Mali, Xclipse).
  - `[vk] texture view in format 107 over an image of format 37, which lists only its own and its sRGB twin …: read in the image's format`.
- **Pipelines:** 2,290 draws on the first start and 481 on the second were left out while their pipelines built in the background.
- **Not tried:** steering or items by hand, other cups and courses, 100cc and up, other Mali devices.

On a Moto Razr Plus 2023 (Adreno 730, Qualcomm driver V@0615.98, Vulkan 1.1, Android 16) on 2026-11-10, the same game app:

- **The title and menus:** 60 fps (p50 16.6 ms, p95 18.9 ms), GPU about 8 ms a frame, 1.8–1.9 GB resident with the BC textures native (the Pixel was at 2.1 GB on the title). The Mii pick and the menus through the cup select worked.
- **Resolved: every course load crashed**, until [#243](https://github.com/enjoyerofslop/droidplay-core/pull/243): `CRASH sig=11 addr=0x4 pc=…(vulkan.adreno.so+0x16ff5c)` on the replay thread, in `vkCmdEndRenderPass` (`rp_end`). The title's demo race crashed at about frame 2,100 in every boot, and a 50cc race as Mario Kart Stadium loaded. The pass: one full-screen draw, colour slots 0–2 empty and an A2B10G10R10 target alone in slot 3, 480×270 to 640×360 with the dynamic resolution. A scratch target in slot 0 stops it: [A render pass with colour slot 0 empty hangs or crashes Qualcomm's Adreno driver](../../../docs/reference/rendering.md#a-render-pass-with-colour-slot-0-empty-hangs-or-crashes-qualcomms-adreno-driver-android).
- **With the fix** (a game app from `main` 0d83f7df with #243's change, no switches; 2026-11-11):
  - the demo race played through to the title again;
  - a 50cc Grand Prix race at Mario Kart Stadium ran to its results (5th, Smart Steering with accelerate held over adb);
  - the save loaded after a cold start, with no Mii pick.
- **Frame rate in the race:** about 45 fps (median frame 22.1 ms, p95 30.6 ms, worst 30 s 42.7 fps), against 60 on the title and menus. The GPU takes 10.9 ms a frame and the replay's CPU 19 ms (the Pixel's: 10 ms), with about 760 draws, so the race is CPU-bound on this phone. Thermal status 0.
- **Memory:** 1.6 GB resident in the race with the BC textures native, against the Pixel's 4.3 GB.
- **Sound:** 613 s from boot through the race (`DM_AUDIO_DUMP`), stereo, −26 to −40 dBFS, no clipping, 0 underruns.
- **Red lines:** none. The Pixel's two came in its first 5 s, so both are Mali's only.

## Found on this game

- **Display sleep during controller play on the Mac (resolved, player-confirmed):** [Mac display sleep during controller play](../../../docs/reference/services.md#mac-display-sleep-during-controller-play).
- **Resolved in the sanitizer audit:** [Unaligned command headers during layout probing](../../../docs/reference/audio.md#unaligned-command-headers-during-layout-probing), reproduced with the SDK 4 command-list fixture.

- **Audio layout detection after incomplete startup lists (resolved):** [Incomplete startup lists must not select the command layout](../../../docs/reference/audio.md#incomplete-startup-lists-must-not-select-the-command-layout).
- **Rumble on a DualShock 4-style controller (resolved, Mac):** a GameSir Cyclone takes the [DualShock 4 effects report](../../../docs/reference/services.md#dualshock-4-rumble-through-its-effects-report). The game holds its low band at 0.1–0.4 all race long, which rotating motors play as constant rumble; `DM_RUMBLE_MIN=0.45` leaves crashes and drifts ([low levels on rotating motors](../../../docs/reference/services.md#controller-haptic-engines-without-advanced-players), open).
- **Fullscreen slowdown to 15 frames a second on an M4's ProMotion screen (#348, closed into #347):** the display link skipped refreshes at frame latency 1; latency 2 in fullscreen is the workaround: [Frame latency 2 for the display link in fullscreen](../../../docs/reference/frame-rate.md#frame-latency-2-for-the-display-link-in-fullscreen). Measured on TotK; not yet checked on this game.
- **2P hung on its 2P screen until the window lost and regained focus (resolved, GitHub issue #550):** the game applies the controller applet's answer only after the InFocus notification that follows a library applet, and with one controller it reopened the applet on an answer a Switch never gives: [Library applets take the application's focus](../../../docs/reference/services.md#library-applets-take-the-applications-focus). Checked on the Mac with 4.0.0, headless: two players (player 2 reported by a test build) reach the 2P character select, which takes input; one player goes back to the engine class menu. Leaving 2P and entering it again in one session did not hang before the fix either (reported, not traced).
- **Race and result layout archives left out of the shader split (resolved, GitHub issue #640):** since the split's archive budget came in, it counted the one Yaz0 layout archive in `UI/<lang>/race.sarc`, `tv.sarc` and `UI/cmn/tv_result.sarc` twice and stopped a registered build at `[RED] 14 file(s) could not be read` (28 with 4.0.1): [A Yaz0 member that expands is not overlap](../../../docs/reference/shaders.md#a-yaz0-member-that-expands-is-not-overlap). With the fix all 14 files of 4.0.0 read (4 shaders in `tv_result.sarc`, all also found in other files), and the split of 4.0.0 with the DLC finishes with no `[RED]` line and the same 29,650 shaders, package and tables as before.
- **Save-write failure isolation (resolved; host regression):** the separate device and account saves make this game a relevant two-save case. Failure state, recovery and commit synchronization now belong to each backing transaction: [Save-write failures stay with their backing transaction](../../../docs/reference/services.md#save-write-failures-stay-with-their-backing-transaction).

General host changes first needed here; each applies to every game:

- **The Mii database and the MiiModel stand-in** (`hle_mii.c`, `dm_mii_standin`, `MountSystemData`), **the add-on content cache sized as Horizon's RomFS working memory** (`romfs_work_size`), **device save data as a save of its own** for a game that mounts account save data too (`<DM_SAVE>_device`) and **SDK 4's DeviceSink** (`g_sink4`): [Mii database answered by the host](../../../docs/reference/services.md#mii-database-answered-by-the-host), [System data stand-in for the MiiModel archive](../../../docs/reference/services.md#system-data-stand-in-for-the-miimodel-archive), [Add-on content mount cache sized as RomFS working memory](../../../docs/reference/services.md#add-on-content-mount-cache-sized-as-romfs-working-memory), [Device and account save data as two saves](../../../docs/reference/services.md#device-and-account-save-data-as-two-saves), [SDK 4: DeviceSink is command 0xf of 0x130 bytes](../../../docs/reference/audio.md#sdk-4-devicesink-is-command-0xf-of-0x130-bytes).
- **The audio renderer's update lock read off each SDK's `Update`** (`update_lock`): [The renderer's update lock (`update_lock`)](../../../docs/reference/audio.md#the-renderers-update-lock-update_lock).
- **The zero cube for a 2D array of fewer than six layers in a cube slot** (`tex_fit`): [A 2D texture in a cube slot binds the zero cube](../../../docs/reference/rendering.md#a-2d-texture-in-a-cube-slot-binds-the-zero-cube).
- **Cold Mac Metal shader builds:** [Cold Mac shader builds compile each pixel shader more than once](../../../docs/reference/shaders.md#cold-mac-shader-builds-compile-each-pixel-shader-more-than-once). Apple M2, `J=8`, no keys, `own_compilers`: 22:46 (1366 s) to 14:47 (886.86 s), 1.54×.

## Open

- On the Moto Razr Plus 2023 (Adreno 730) a race runs at about 45 fps: the replay takes 19 ms of CPU a frame, against 10 ms on the Pixel 9 Pro XL ([Android](#android)).
- Mii heads draw nothing: the host ships no MiiModel firmware data (the player README notes "no Mii heads").
