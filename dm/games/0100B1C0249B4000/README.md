# Frostpunk (`0100B1C0249B4000`)

Update 1.0.1 (v65536) over the base game, SDK **20.5.19** (`nnSdk-20_5_19`, `NintendoSDK_NVN-20_5_19`), with the "all expansions pack" add-on, which is a licence only (no content of its own; the main menu then shows "Downloadable content: new content available"). It's 11 bit studios' own **Liquid engine** (namespace `N6Liquid`), drawing with **NVN**. The survey's "Unreal 4" marker is a stray `UE4` in `main`: there are no paks. Every game file is in a dozen archives of three files each at the RomFS root (`<name>.idx`, `.str`, `.dat`; 3.53 GB): zstd entries, with sound and movies as Ogg streams that the game decodes itself.

- **On the Mac:** plays at 30 fps from boot through the 11 bit studios logo, the title, the main menu and A New Home's intro movie into the city, with the Generator and the wreckage drawn.
- **On Android:** the same route at 30 fps on a Galaxy S25 Edge, with sound. The Generator, the buildings and the props need raw global memory on the Vulkan replay (enjoyerofslop/droidplay-core#150), which this profile turns on; without it they are invisible. See [Android](#android).

## What it needs

| Setting | Where | Why |
|---|---|---|
| `modules main sdk` | [`game.tsv`](game.tsv) | `main` imports from these two only. It imports `nn::ro`, but the RomFS holds no NRO and the runs loaded none |
| `sys_resource 0x0`, `mem_reserve 0x100000000`, `mem_alias 0x10000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000` | [`game.tsv`](game.tsv) | no system resource, so no virtual address memory. `main` sets a heap of at most the pool − 64 MB, which the 3.25 GB heap region holds (`heap 3.12 GB (heap region 3.25 GB)` in the log, on the Mac and on Android) |
| `shader_groups /=romfs` | [`game.tsv`](game.tsv) | every shader is in `common.dat` at the RomFS root. See [Shaders](#shaders) |
| `zip_store .dat:.metallib` | [`game.tsv`](game.tsv) | the archives' entries are zstd frames and Ogg streams already |
| `DM_VK_RAW_GMEM=1` | [`android_defaults.txt`](android_defaults.txt) | Android: raw global memory, which every solid and translucent mesh reads (see [Shaders](#shaders)). It's on by default only for Switch 2 games, and Frostpunk is a Switch 1 one. It takes effect on a Qualcomm Adreno or a Samsung Xclipse ([Android](#android)) |

The profile is the provisional one `scripts/build_ipa_from_nsp.py` made from the survey, unchanged but for its comments. Its shader tables come from the Liquid archive reader. `pso_manifest.tsv` is still the empty provisional list.

## Shaders

- **Where:** 2,550 shaders in `common.dat`, found through `common.idx` and `common.str` by `shader_split.py`'s Liquid archive reader ([Shader files in Liquid Engine archives](../../../docs/reference/shaders.md#shader-files-in-liquid-engine-archives)). They are HLSL compiled for NVN, one stage per file (`shaders/compiled/<technique>/<hash>.<stage>_5_0`): 1,577 pixel, 833 vertex, 75 compute, 32 hull, 32 domain and 1 geometry.
- **Raw global memory:** all 1,108 shaders of the techniques `meshsolid` and `meshtranslucent` (539 vertex, 569 pixel; exactly those with a 0x88c-byte control section) read through raw global memory: `Global memory operation "Load" traced to no storage buffer: it goes through the memory pool table`. The Mac's `gmem_map` serves them. On Android, raw global memory (enjoyerofslop/droidplay-core#150) does, turned on by [`android_defaults.txt`](android_defaults.txt). See [Android](#android).
- **Mac, current:** 2,548 of 2,550 translate. The two `meshsolid` domain shaders `1ff1e13a5d5f963b` and `529b32dc47755a08` fail Metal's compile: `'attribute' index '30' is used more than once`. At run time, 40 pixel shaders (the SMAA passes among them) log `reflection conversion failed: B binding fp_t_tcb_15A has no resolved slot number` (also `15C`, `15E`): texture handles read from c1 at 0x5A-0x68 that the translator's queries had no answer for. Nothing wrong was seen in the picture.
- **Android, current:** 2,486 translate, none fail. The 64 hull and domain shaders are not on the Vulkan path yet (draws with them would count as `shader missing`; the city view counted none).

## Boot

- **Resolved:** the game crashed on its `Renderer` thread about 7 s into loading, before its first frame, on the Mac and on Android: `CRASH sig=11 pc=main+0x1aa90ac lr=main+0x1aa8a70`. Its renderer sizes a 32-slot per-stage binding table to min(device items 0x5E, 0x5F) (`main+0x1aa68d4`) and clears that many slots every frame (`main+0x762f50`). The host answered 0x5F with 4096, so it cleared 128 slots. Fixed by answering 32 ([Separate sampler bindings per stage](../../../docs/reference/nvn-objects.md#separate-sampler-bindings-per-stage)).
- **Loading:** about 30 s from launch to the title screen on the S25 Edge. After "A New Home", the loading screen shows the controls, then the intro movie plays (B skips it), then the scenario's story screen.

## Audio

- One stereo `AudioOut` at boot (`main+0x1a7ab64`), fed by the game's own OpenAL Soft mixer (thread `alsoft-mixer`). An Android `DM_AUDIO_DUMP` of 225 s (title, menu, intro movie, city) holds sound throughout, with 10 s RMS of 750 to 4,850 and peaks up to 32,767. It is silent only during the 50-60 s load. AAudio counted 0 underruns. The sound was judged from the dump; nobody listened to it.

## Mac

- **Checked on an M5 Max**, headless, with scripted presses (`DM_KEYS=28:A,34:A,40:A,70:B,74:B,80:A,90:A,100:A`: the title, A New Home, skip the intro, the story screen, the first message) and `DM_NVN_SHOT` every 600 frames.
- **Frame rate:** 30 fps in the city (frame p50 32.7 ms), GPU p50 6.6 ms.

## Android

- **Tested 2026-11-10 on a Samsung Galaxy S25 Edge** (Adreno 830, Samsung's driver 0x80320001, Android 16), from DroidPlay Core main `648a3758` with the fixes of enjoyerofslop/droidplay-core#137, #138 and #139 applied, on the touch controls with live adb input.
- **Route:** the title, A New Home, the intro movie, the story screen, the first two messages, then about two minutes in the city: the camera moved with the stick, the zoom on the 3D layout's right side, the Command Hub and the build radial opened.
- **Frame rate:** 30 fps throughout:

  | Where | Frame p50 / p95 | GPU p50 | Replay submit + present p50 |
  |---|---|---|---|
  | Title and menu | 33.2-33.5 / 33.8-34.5 ms | 14.4-19.6 ms | 4.5-5.9 ms |
  | Intro movie | 33.0 / 33.5 ms | 2.3 ms | 2.0 ms |
  | City | 33.8 / 34.6 ms | 23.4 ms | 17.4 ms |

  The city's numbers are without the meshes, which weren't drawn then (below).
- **First start:** 1,045 draws were left out while their pipelines built in the background, then none. On the next start the pipeline cache (2 MB) leaves out 13. One 3.75 s frame while the scenario loads.
- **The meshes need raw global memory.** On main without enjoyerofslop/droidplay-core#150, the Generator, the buildings and the wreckage don't draw. The terrain, snow, lights, UI, movies and the Generator's shadow do.
  - `DM_VK_DUMP` of a city frame: the G-buffer passes 10 and 11 hold the `meshsolid` draws (about 120, depth test greater, 5 targets), and they leave colour and depth empty. Pass 12's terrain then covers the crater.
  - **Cause:** these shaders read their per-object data through raw global memory (see [Shaders](#shaders)). Without it, the Vulkan replay binds 16 zero bytes for the raw pool table, so every such load reads 0: `[RED] [vk] storage buffer of shader 7069f9743717cd32 (c255 +0) is not a bound buffer: it reads 0`. It's the same gap as [Ocarina of Time](../0400486024DEC000/README.md)'s black forest on the Switch 2. The shadow pass uses other shaders, which is why the shadow is there.
  - **Fix:** #150's raw global memory, on by default only for Switch 2 games, is turned on for Frostpunk by [`android_defaults.txt`](android_defaults.txt). On the S25 Edge it takes the AHardwareBuffer route (no `VK_EXT_map_memory_placed` on Samsung's driver).
- **With raw global memory, 2026-11-10 on the S25 Edge:** a Frostpunk-only APK of #150's head merged with main `5736949c`, with the game's `defaults.txt` as the profile writes it. Three scripted runs from the title into the city (5, 5 and 7 minutes); the off run set `DM_VK_RAW_GMEM=0` in `env.txt`:

  | City | Generator and wreckage | Frame p50 / p95 | GPU p50 | Replay submit + present p50 | PSS |
  |---|---|---|---|---|---|
  | On | drawn, as on the Mac | 33.6-33.9 / 34.3-34.6 ms | 24.2-25.3 ms | 18.6-20.4 ms | 2.86-2.88 GB |
  | Off | invisible | 33.6-33.9 / 34.4-34.6 ms | 22.7-22.9 ms | 19.6-20.3 ms | 2.69 GB |

  - Ranges are of 10 s windows in the city, without the stretch where the 7-minute run's input opened a menu.
  - **Memory:** 345-370 MiB placed at the end of a run (peak 346-372 MiB), 0 pools over the cap (2.71 GiB, a quarter of the phone's memory). The game finalizes pools as it loads, and 675 were given back each run. PSS stays flat in the city over the 7-minute run (2.84-2.90 GB from 150 s to 390 s).
  - The `c255` red line is gone. 13 draws were left out while pipelines built, as with the earlier host's warm pipeline cache.
- **`[RED]` lines:** with raw global memory, only `shader 1e7e00b64456ac66 reads uniform slot 1, which has no buffer bound: it reads 0` (the sky's pixel shader, `environment/sky/physicalsky`).
- **Picture:** the S25's screen grabs of the opening view are darker than the Mac's capture of the same view (the snow greyer, the Generator's metal near black), with or without raw global memory. Not looked into: the two are taken differently (`screencap` against `DM_NVN_SHOT`), and an earlier grab zoomed out at 09:59 is as bright as the Mac's.

- **On a Moto Razr Plus 2023, 2026-11-10: blocked by the driver's compiler.** Adreno 730 with Qualcomm's driver V@0615.98 (Vulkan 1.1.128), Android 16, open. Frostpunk's host from `main` at `0cad2e47`, the game files from the build folder with `defaults.txt` holding `DM_VK_RAW_GMEM=1`.
  - **What runs:** the title, the menu, the intro movie, the story screen and the city, with sound. Raw global memory is on (the AHardwareBuffer route, 618 pieces, 349 MiB placed), and the terrain, snow, lights and UI draw. City: 29.0 fps, frame p50 34.1 / p95 37.7 ms, GPU p50 17.8 ms (without the meshes). The sound dump runs at −17 to −32 dBFS; 1 underrun in 68,000 callbacks.
  - **What doesn't:** the Generator, the buildings and the props, which leave only their shadows and lights. Every pipeline with one of the 1,108 shaders that read raw global memory fails (`pipeline creation failed: VkResult -13`: 32 pipelines, about 242,000 draws left out in four minutes). Logcat says why: `AdrenoVK-0: Shader compilation failed for shaderType: 0 ... INTERNAL ERROR: Instruction OpConvertUToPtr not supported`. The translator turns raw global memory into `PhysicalStorageBuffer` pointers made with `OpConvertUToPtr` from 64-bit addresses (539 vertex and 569 fragment modules).
  - **Two rewrites tried on the device** (the modules swapped in `games/<id>/spv`, then put back): an `OpBitcast` from the 64-bit address fails `src expected to have two components`, and an `OpBitcast` through a `uvec2` (GL_EXT_buffer_reference_uvec2's form, valid by spirv-val) gets past that but crashes the compiler (`SIGSEGV in libllvm-qgl.so+0x2cc258`, building `7069f9743717cd32`). So this driver takes no physical pointer form tried; Turnip does (below), and a translation of raw global memory without pointers would.
- **On the Moto Razr Plus 2023 with a Turnip driver, 2026-11-11: the meshes draw.** Mr. Purple's Turnip T30 (`turnip_mrpurple_T30-toasted.adpkg.zip`, a third-party Mesa build; not part of DroidPlay) put on the phone and named with `DM_VK_DRIVER=vulkan.purple.so` ([Another Vulkan driver](../../../docs/android.md#another-vulkan-driver-turnip)). The installed app from `main` at `ec8f451f`, the game files as above (`DM_VK_RAW_GMEM=1`), and `DM_KEYS=45:A,52:A,60:A,100:B,105:B,112:A,122:A,132:A` into the city; the two drivers run back to back with the same build and route:

  | | Qualcomm's driver V@0615.98 | Turnip T30 |
  |---|---|---|
  | Device | `Adreno (TM) 730`, Vulkan 1.1.128 | `PurpleVK-public Adreno (TM) 725`, Vulkan 1.4.359 (T30 names the GPU a 725) |
  | Raw global memory | AHardwareBuffers (no `VK_EXT_map_memory_placed`) | placed Vulkan memory: 635 pieces, 358.9 MiB |
  | Pipelines that fail | 31 (`pipeline creation failed`) | none |
  | Generator, buildings, props | invisible | drawn |
  | City: frame time | p50 33.8 / p95 34.3 ms (about 29.6 fps) | p50 34.0 / p95 34.9 ms (about 29.4 fps) |
  | City: GPU | p50 17.0 / p95 19.4 ms, without the meshes | p50 13.7 / p95 14.3 ms, with them |
  | The game's PSS | 1.59 GB (+171 MB swap) | 1.95 GB (+151 MB swap), about the placed memory more |
  | Crashes, `[RED]` lines | none; the sky's uniform slot line | none; the sky's uniform slot line |

  - T30's first start compiled every pipeline from an empty cache and still reached the city by 220 s.
  - **Not done:** played past the tutorial's first pop-up, a building placed, a night, a save and Continue. Other Adreno 7xx phones on old drivers weren't tried.

- **On a Galaxy Z Flip 7, 2026-11-11: the meshes draw.** Xclipse 950 with Samsung's driver 24.0.533 (0x6000215, Vulkan 1.3.279), Android 16, open. By hand from the title through A New Home's intro into the city, the game files sent with `push_game` (`defaults.txt` holding `DM_VK_RAW_GMEM=1`).
  - **Raw global memory:** the driver compiles every pipeline of the shaders that read it, with no `pipeline creation failed`. It takes the AHardwareBuffer route (no `VK_EXT_map_memory_placed`). The pages read at 11–18 GB/s, so they're cached. About 614–618 pieces, 345–359 MiB placed.
  - **Red lines:** only the sky's uniform slot, and no `c255` line.
  - **From `main` 25cdf3e1, with `DM_VK_RAW_GMEM_ANYGPU=1`** (then needed on a GPU not from Qualcomm). The off run is the same launch without it. City, in 30 s windows:

  | Run | fps | Frame p50 / p95 | GPU p50 | PSS | Generator, wreckage |
  |---|---|---|---|---|---|
  | On | 29.4–29.5 | 33.9–34.0 / 34.5 ms | 11.9–12.4 ms | 3.13 GB | drawn |
  | Off | 29.4–29.5 | 33.9–34.0 / 34.5 ms | 13.0–13.3 ms | 2.93 GB | missing: only the Generator's base and lights |

  - **With raw global memory allowed on Samsung's Xclipse** (no env switch), the same: 29.4–29.5 fps in the city, GPU p50 12.2–13.3 ms, PSS 3.04 GB, the meshes drawn.
  - **A camera panned low to the crater's edge** showed large flat bright faces on the cliffs. Not compared with the Mac; it may be the terrain's hull and domain shaders (Open, below).

## Found on this game

- [Separate sampler bindings per stage](../../../docs/reference/nvn-objects.md#separate-sampler-bindings-per-stage): the boot crash, item 0x5F of `nvnDeviceGetInteger`.
- [Shader files in Liquid Engine archives](../../../docs/reference/shaders.md#shader-files-in-liquid-engine-archives).
- `cb_extents` stopped the Android shader build on a Private register's initializer (12 pixel shaders): enjoyerofslop/droidplay-core#139.

## Open

- **Android: the Adreno 730's driver (V@0615.98) compiles no raw global memory shader** (the Moto Razr Plus 2023, above): the meshes are invisible there on the phone's own driver. With a Turnip driver they draw (above); a translation of raw global memory without pointers would fix it on Qualcomm's driver too.
- **Android: the opening view's darker picture** and the sky shader's unbound uniform slot, above.
- **Android: hull and domain shaders** (terrain, terrain shadow map, water and 8 `meshsolid` variants). None were seen in the first city view; a tessellated scene was not looked for.
- **Mac: the two domain shaders' attribute clash and the 40 shaders without a texture slot**, above.
- **Not played past day 1's first minutes:** no building placed, no night, no storm, no other scenario. The DLC scenarios were not opened. Hand play on the Mac, the iPhone, a physical controller, docked mode and the other Android devices were not tried.
- **`pso_manifest.tsv`** is still empty: no prewarm list was recorded.
