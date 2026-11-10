# Frostpunk (`0100B1C0249B4000`)

Update 1.0.1 (v65536) over the base game, SDK **20.5.19** (`nnSdk-20_5_19`, `NintendoSDK_NVN-20_5_19`), with the "all expansions pack" add-on, which is a licence only (no content of its own; the main menu then shows "Downloadable content: new content available"). It's 11 bit studios' own **Liquid engine** (namespace `N6Liquid`), drawing with **NVN**. The survey's "Unreal 4" marker is a stray `UE4` in `main`: there are no paks. Every game file is in a dozen archives of three files each at the RomFS root (`<name>.idx`, `.str`, `.dat`; 3.53 GB): zstd entries, with sound and movies as Ogg streams that the game decodes itself.

- **On the Mac:** plays at 30 fps from boot through the 11 bit studios logo, the title, the main menu and A New Home's intro movie into the city, with the Generator and the wreckage drawn.
- **On Android:** the same route at 30 fps on a Galaxy S25 Edge, with sound, but every building, the Generator and the props are invisible. See [Android](#android).

## What it needs

| Setting | Where | Why |
|---|---|---|
| `modules main sdk` | [`game.tsv`](game.tsv) | `main` imports from these two only. It imports `nn::ro`, but the RomFS holds no NRO and the runs loaded none |
| `sys_resource 0x0`, `mem_reserve 0x100000000`, `mem_alias 0x10000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000` | [`game.tsv`](game.tsv) | no system resource, so no virtual address memory. `main` sets a heap of at most the pool − 64 MB, which the 3.25 GB heap region holds (`heap 3.12 GB (heap region 3.25 GB)` in the log, on the Mac and on Android) |
| `shader_groups /=romfs` | [`game.tsv`](game.tsv) | every shader is in `common.dat` at the RomFS root. See [Shaders](#shaders) |
| `zip_store .dat:.metallib` | [`game.tsv`](game.tsv) | the archives' entries are zstd frames and Ogg streams already |

The profile is the provisional one `scripts/build_ipa_from_nsp.py` made from the survey, unchanged but for its comments. Its shader tables come from the Liquid archive reader. `pso_manifest.tsv` is still the empty provisional list.

## Shaders

- **Where:** 2,550 shaders in `common.dat`, found through `common.idx` and `common.str` by `shader_split.py`'s Liquid archive reader ([Shader files in Liquid Engine archives](../../../docs/reference/shaders.md#shader-files-in-liquid-engine-archives)). They are HLSL compiled for NVN, one stage per file (`shaders/compiled/<technique>/<hash>.<stage>_5_0`): 1,577 pixel, 833 vertex, 75 compute, 32 hull, 32 domain and 1 geometry.
- **Raw global memory:** all 1,108 shaders of the techniques `meshsolid` and `meshtranslucent` (539 vertex, 569 pixel; exactly those with a 0x88c-byte control section) read through raw global memory: `Global memory operation "Load" traced to no storage buffer: it goes through the memory pool table`. The Mac's `gmem_map` serves them. Android has no such table yet. See [Android](#android).
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

  The city's numbers are without the meshes, which aren't drawn (below).
- **First start:** 1,045 draws were left out while their pipelines built in the background, then none. On the next start the pipeline cache (2 MB) leaves out 13. One 3.75 s frame while the scenario loads.
- **Broken: the meshes are invisible.** The Generator, the buildings and the wreckage don't draw. The terrain, snow, lights, UI, movies and the Generator's shadow do.
  - `DM_VK_DUMP` of a city frame: the G-buffer passes 10 and 11 hold the `meshsolid` draws (about 120, depth test greater, 5 targets), and they leave colour and depth empty. Pass 12's terrain then covers the crater.
  - **Cause:** these shaders read their per-object data through raw global memory (see [Shaders](#shaders)). The Vulkan replay binds 16 zero bytes for the raw pool table, so every such load reads 0: `[RED] [vk] storage buffer of shader 7069f9743717cd32 (c255 +0) is not a bound buffer: it reads 0`. It's the same gap as [Ocarina of Time](../0400486024DEC000/README.md)'s black forest on the Switch 2. The shadow pass uses other shaders, which is why the shadow is there.
- **`[RED]` lines:** that one, and `shader 1e7e00b64456ac66 reads uniform slot 1, which has no buffer bound: it reads 0` (the sky's pixel shader, `environment/sky/physicalsky`).

## Found on this game

- [Separate sampler bindings per stage](../../../docs/reference/nvn-objects.md#separate-sampler-bindings-per-stage): the boot crash, item 0x5F of `nvnDeviceGetInteger`.
- [Shader files in Liquid Engine archives](../../../docs/reference/shaders.md#shader-files-in-liquid-engine-archives).
- `cb_extents` stopped the Android shader build on a Private register's initializer (12 pixel shaders): enjoyerofslop/droidplay-core#139.

## Open

- **Android: raw global memory on Vulkan**, which every solid and translucent mesh needs.
- **Android: hull and domain shaders** (terrain, terrain shadow map, water and 8 `meshsolid` variants). None were seen in the first city view; a tessellated scene was not looked for.
- **Mac: the two domain shaders' attribute clash and the 40 shaders without a texture slot**, above.
- **Not played past day 1's first minutes:** no building placed, no night, no storm, no other scenario. The DLC scenarios were not opened. Hand play on the Mac, the iPhone, a physical controller, docked mode and the other Android devices were not tried.
- **`pso_manifest.tsv`** is still empty: no prewarm list was recorded.
