# Android baselines

The first baselines of DroidPlay Core (then droidnative) on more than one device: six Switch 1 games on three Snapdragon devices, run the same way on each with
`scripts/bench_android.py` (the same save, scripted input and measuring window). The first four were measured 2026-11-08 on its `main` at `f4f7abb3`
with PR #1 (the present's vsync sleep outside the submission lock) and PR #3 (the game window keeps the screen on); The Legend of Zelda: Link's Awakening
and Skyward Sword HD the same evening on `main` at `ee18169a`. Each game was packed by `build_android_from_nsp.py`. They are a starting point for fixes,
not a verdict: every known problem below that is not marked fixed is open. The Samsung Galaxy S25 Edge's column and Final Fantasy Resonance's rows were
added 2026-11-10, measured the same way on `main` at `cf42941d`; Brilliant Diamond's Eterna City on it the same day, in the eight runs that checked [a fix for the
Adreno 830](../../docs/reference/rendering.md#uniform-bound-tests-in-a-vertex-shader-lose-the-device-on-the-adreno-830). The Retroid Pocket 5's rows for Odyssey,
Brilliant Diamond, Animal Crossing and Link's Awakening were measured again 2026-11-10 on `main` at `54e21235`, which turns on a cached copy of storage-buffer
write-backs on that device's driver for every game (problem 13); with the copy off (`DM_VK_WB_READBACK=0`) only Brilliant Diamond's Eterna City changes. Super Smash
Bros. Ultimate's Retroid Pocket 5 rows were measured again the same day on `main` at `3b07c5cf` (problem 16).

## Devices

| Device | SoC | GPU, driver, Vulkan | Android | RAM |
|---|---|---|---|---|
| Ayn Odin 2 | QCS8550 (Snapdragon 8 Gen 2) | Adreno 740, V@0676.32, 1.3.128 | 13 | 12 GB |
| OnePlus Pad 3 | SM8750P (Snapdragon 8 Elite) | Adreno 830, V@0800.74, 1.3.284 | 16 | 12 GB |
| Retroid Pocket 5 | SM8250 (Snapdragon 865) | Adreno 650, V@0746.0, 1.1.128 | 13 | 8 GB |
| Samsung Galaxy S25 Edge | SM8750 (Snapdragon 8 Elite for Galaxy) | Adreno 830, V@0800.40.1, 1.3.284 | 16 | 12 GB |
| Google Pixel 9 Pro XL ([Mali](#mali-super-mario-odyssey-on-a-pixel-9-pro-xl)) | Tensor G4 | Mali-G715, Arm's driver 0xd803000, 1.4.343 | 17 | 16 GB |
| Samsung Galaxy Z Flip 7 ([Xclipse](#xclipse-brilliant-diamond-on-a-galaxy-z-flip-7)) | Exynos 2500 | Xclipse 950, Samsung's driver 24.0.533 (0x6000215), 1.3.279 | 16 | 12 GB |
| Moto Razr Plus 2023 ([Adreno 730](#adreno-730-a-moto-razr-plus-2023)) | SM8475 (Snapdragon 8+ Gen 1) | Adreno 730, V@0615.98 (0x80267062), 1.1.128 | 16 | 8 GB |

All seven use 4 KB pages. The Odin 2 and the Retroid Pocket 5 have built-in controls; the Pad 3, the S25 Edge, the Pixel 9 Pro XL, the Z Flip 7 and the Razr Plus 2023 show the on-screen controls over the game.
The Pixel 9 Pro XL, the first GPU outside Adreno, is not in the Results table: it has [a section of its own](#mali-super-mario-odyssey-on-a-pixel-9-pro-xl).

The RAM column is the device's installed capacity, not a measurement of how much memory a game uses. These baselines report frame rates and frame
times, not per-game peak memory use or a matched memory-use comparison with an emulator. A result on the 8 GB Retroid Pocket 5 does not establish
how the same game runs on a different 8 GB device.

## Results

Frames per second over a 30 s window, then frame time p50 / p95 in ms, from two measured runs after a warm-up run (ranges where they differ). GPU is the
median GPU time per frame. Animal Crossing runs at 30 fps on the Switch too.

| Game, scene | Odin 2 | Pad 3 | Retroid Pocket 5 | Galaxy S25 Edge |
|---|---|---|---|---|
| **Super Mario Odyssey 1.4.1**, Start menu (a fresh save) | 60 · 16.7 / 17.6–18.7 | 60 · 16.6 / 18.0 | 60 · 16.7 / 17.6–17.8 · GPU 1.4–1.5 (2026-11-10, `main` 54e21235) | 60 · 16.7 / 17.6–17.7 · GPU 2.2 |
| Super Mario Odyssey, the opening cutscene (Start pressed on a fresh save) | 59.9 · 16.7 / 18.4 · GPU 5.5 (one run crashed at boot) | 59.9 · 16.7 / 18.9 · GPU 9.3 | 59.3–59.4 · 16.6 / 18.7–18.9 · GPU 12.3–12.4 (2026-11-10, `main` 54e21235; 38 on 2026-11-08, problem 6, fixed) | 60 · 16.6 / 19.3–19.4 · GPU 9.9 |
| Super Mario Odyssey, play (the Cap Kingdom, at the Look Around hint) | 60 · 16.7 / 18.5 · GPU 4.5 (one run, 15 s; it crashed at the hint video before the fix in problem 1) | not run | not run | not run |
| **Pokémon Brilliant Diamond 1.3.0**, language menu (a fresh save) | 60 · 16.7 / 19.2–19.4 | 60 · 16.6–16.7 / 18.5–18.8 | 60 · 16.7 / 17.4–19.1 · GPU 1.0 (2026-11-10, `main` 54e21235) | not run |
| Pokémon Brilliant Diamond, Eterna City (a save) | 60 · 16.6 / 18.1–18.2 · GPU 8.1 | 58.9–59.7 · 16.6–16.8 / 18.8–19.7 · GPU 10.7 | 59.0–59.6 · 16.6 / 26.6–26.9 · GPU 13.0 (2026-11-10, `main` 54e21235, after problem 13's fix; 21.0 with `DM_VK_WB_READBACK=0`, 24.0–24.6 before the fix) | 60 · p95 19.5 · GPU 10.6–10.7 (eight runs, 2026-11-10) |
| **Animal Crossing: New Horizons 3.0.3**, the new game's airport (a fresh save) | 30 · 33.3 / 34.7–35.4 · GPU 5.3 | 30 · 33.3 / 35.7–35.8 · GPU 7.1 | 30 · 33.2–33.3 / 35.7–36.0 · GPU 12.3–12.4 (2026-11-10, `main` 54e21235) | 30 · 33.4 / 35.8–35.9 · GPU 15.8 |
| Animal Crossing, outside the player's house (a save) | 30 · 33.3–33.4 / 35.7–35.8 · GPU 9.4–9.7 | 29.9 · 33.3–33.4 / 38.0–38.1 · GPU 15.5–15.9 | 30.0 · 33.3 / 36.3–36.5 · GPU 21.8–22.3 (2026-11-10, after the save fix below; 30.0 again on `main` 32302b99, and with `DM_VK_WB_READBACK=0`) | 30 · 33.2–33.4 / 35.6–36.3 · GPU 22.7–23.1 |
| **Super Smash Bros. Ultimate 13.0.5**, boot with Android's Roboto as the shared font (fixed: problem 3) | **Crashes** 2–4 s in | **Crashes** | **Crashes** | not run (fixed before) |
| Smash, the opening movie (with a hinted shared font, now packed with the game) | 60 · 12.0 / 33.9 | 59.9 · 13.1–13.4 / 34.7–35.1 | 59.8–59.9 · 11.9–13.9 / 35.8–36.2 · GPU 2.0 (2026-11-10, `main` 3b07c5cf; 59.7 on 2026-11-08) | 60 · 9.8–12.4 / 33.5–33.7 · GPU 1.9–2.1 |
| Smash, a battle (a fuller shared font; stage and CPU fighter vary) | 39.7–59.3 fps | 52.3–59.9 · 16.6–18.9 / 20.5–25.0 · GPU 8.2–8.9 (2026-11-09, `main` 8edd2b38 with #72 and #73, both since merged, as droidplay-core#72 reports; 38.2–50.3 on `main` 54711866 that morning; 16.8–29.7 and frames up to 215 ms on 2026-11-08) | 57.0–58.8 · 16.8–17.1 / 22.0–24.4 · GPU 8.5–9.5, frames up to 112–119 ms (2026-11-10, `main` 3b07c5cf: both runs on Fountain of Dreams, the warm-up 56.9 on another stage; from an empty pipeline cache 59.4 on Mushroom Kingdom; 13.4–19.3 fps and frames up to 368 ms on 2026-11-08; problem 16) | 59.9 fps, frames up to 52 ms · GPU 6.3–6.6 |
| **The Legend of Zelda: Link's Awakening 1.1.0**, the opening movie (a fresh save) | 59.8–59.9 · 16.7 / 17.6–17.7 · GPU 2.3–2.4 | 59.7 · 16.7 / 16.8 · GPU 4.5 (the other run crashed at boot) | 58.8–59.1 · 16.7 / 17.0–17.4 · GPU 5.3–5.7 (2026-11-10, `main` 54e21235) | 60 · 16.7 / 16.8 · GPU 4.9 |
| Link's Awakening, the overworld at the Ancient Ruins (a save) | 59.9–60.0 · 16.7 / 17.0 · GPU 5.8–5.9 (2026-11-09, `main` 54711866; GPU 4.1 on 2026-11-08 with the world black, problem 8) | 33.3 · 33.2 / 34.1–34.4 · GPU 10.8 (2026-11-09, `main` 54711866, one run crashed at boot; 31.3 · GPU 12.0 on 2026-11-08 with the world black, problem 8) | 32.3–32.4 · 33.1–33.2 / 34.6–34.8 · GPU 12.9 (2026-11-10, `main` 54e21235; 34.7–36.0 on an earlier `main`; the game falls to its 30 fps interval, problem 12) | 38.1–44.6 · 16.8–32.5 / 33.8–34.1 · GPU 13.0–13.7 |
| **The Legend of Zelda: Skyward Sword HD 1.0.1**, the opening movie (a fresh save) | 55.2–55.9 · 18.1–18.3 / 36.6–37.7 · GPU 2.3–2.4 | 59.9–60 · 16.7 / 24.5–25.1 · GPU 2.8 | 41.1–41.4 · 24.4–24.6 / 49.1–49.8 · GPU 3.7 | 60 · 16.6 / 18.0–18.1 · GPU 2.5 |
| Skyward Sword HD, Skyloft's plaza (a save) | 60.0 · 16.7 / 17.9 · GPU 3.7–3.8 (2026-11-09, `main` 54711866; 30.0–30.5 on 2026-11-08, problem 11, fixed) | 60.0 · 16.7 / 19.7–19.9 · GPU 6.8 (2026-11-09, `main` 54711866; 30.0–34.0 on 2026-11-08, problem 11, fixed) | 43.2–43.3 · 17.7 / 34.9–35.2 · GPU 8.5 (2026-11-10, after the save fix below; terrain and sky in colour). An average of two rates: the game switches between 60 and 30 within a run (problem 11's interval drop), 58.8, 53.5 and 30.0 fps in three runs on `main` 648a3758 | 60 · 16.6–16.7 / 20.6–20.7 · GPU 9.8–9.9 |
| **Final Fantasy Resonance 1.0.1**, the Lancarse logo and the Brightness screen (a fresh save) | 59.6–59.7 · 16.8 / 18.7 · GPU 1.8 | not measured here | not run | 59.6 · 16.8 / 21.3–21.5 · GPU 5.8 |
| Final Fantasy Resonance, the first field (a save made by its `tofield` route) | 42.2–42.6 · 23.3–23.6 / 27.1–27.4 · GPU 12.5–12.7 | not measured here | not run | 30.1–33.3 · 29.7–33.0 / 40.9–42.8 · GPU 20.2–22.7 |
| **The Legend of Zelda: Breath of the Wild 1.9.0**, the Shrine of Resurrection (the `outdoors` save, a 40 s window) | no GPU hang: 30.0–30.5 · 33.0–33.3 / 37.5–38.2 · GPU 13.2–15.3 on main (the frame step tries 60 and fails), **29.9 · 33.2 / 36.2–36.6 · GPU 14.3** with droidplay-core#108 | **30.0 · 33.2–33.3 / 37.9–38.4 · GPU 16.5–16.7** on main with BotW's defaults and the empty slot 0 filled (problem 14, fixed; the picture is still dark, problem 15). Before that fix the GPU was lost at the first frame in the field; with the hanging draw skipped: 20.0 · 48.6–49.2 / 68–71 · GPU 22.3 on main | not run | **29.9 · 33.2 / 38.8–39.0 · GPU 20.5** on main 54e21235 with BotW's defaults and the duplicate colour slots attached once (problem 15, fixed); 29.9 · 33.2–33.3 / 38.7–39.6 · GPU 21.4 and the Shrine dark without that fix. No GPU hang (problem 14's fix is on for its Adreno 830) |

Link's Awakening's opening movie on the Odin 2 and the Pad 3 was measured on 2026-11-08, before problem 8's fix, with its colours wrong; its other cells
are from after the fix, with the picture right. Skyward Sword HD's Skyloft had grey terrain on the Odin 2 and the Pad 3 until problem 10's fix; it is in
colour on all four. The cells dated 2026-11-09 on `main` 54711866 are that day's regression pass of `main`, reported in droidplay-core#72 beside the
PR's own runs.

Time from launch to the first frame, warm: about 1.3 s (Odyssey), 3.2–4.3 s (Brilliant Diamond, a Unity game), 1.5 s (Animal Crossing), 2.0–3.0 s (Smash),
0.4–0.6 s (Link's Awakening), 1.3–2.1 s (Skyward Sword HD). The first launch after an install is slower while the driver builds its pipelines: Brilliant
Diamond's first frame took 33 s on the Pad 3's first launch. On the Galaxy S25 Edge: 1.0–1.2 s (Odyssey), 1.2–1.4 s (Animal Crossing), 1.6–1.9 s
(Smash), 0.4–0.5 s (Link's Awakening), 1.0–1.1 s (Skyward Sword HD), 0.5–0.6 s (Final Fantasy Resonance).

## Switch 2: The Legend of Zelda: Ocarina of Time on a Galaxy Z Fold 8

The first Switch 2 game measured on Android (2026-11-10, #76's branch with #82-#87 and #94, chain 5 shaders), on a fourth device: a Galaxy Z Fold 8 (SM-F971U1, SM8850 / Snapdragon 8 Elite
Gen 5, Adreno 840, Qualcomm's driver 0x8034a013, Vulkan 1.4.295, Android 17, 11.3 GB of RAM), folded, on its cover display. `scripts/bench_android.py`, route `title`,
two runs without a warm-up (the pipeline cache warm from earlier runs; Kokiri Forest on main with the texture pool set, route `kokiri`):

| Game, scene | Galaxy Z Fold 8 |
|---|---|
| **Ocarina of Time v131072**, the title and its menu (a fresh save) | 29.6-31.1 · 33.2-33.3 / 35.1-48.2 · GPU 26.7 |
| Ocarina of Time, Kokiri Forest (a Mac save, route `kokiri`) | 1.7 fps · frame p50 593-611 / p95 683-691 · GPU 119.4-128.2, PSS 8.5 GB; the forest black: the replay has no raw global memory (the pool table in slot 0xFF that 2,247 of the game's shaders read through); 1.6 fps and GPU 138.7 with `DM_VK_POOL=0` |

The title's GPU frame is nn::ndve's last convolution (36.8 ms in a `prof_now` frame). Kokiri Forest's memory (`DM_VK_MEMREPORT`, #95), its black picture (no raw global memory on Vulkan) and what is open: the game's note,
[Android](../games/0400486024DEC000/README.md#android).

## Mali: Super Mario Odyssey on a Pixel 9 Pro XL

The first GPU outside Adreno (2026-11-10): a Google Pixel 9 Pro XL (Tensor G4, Mali-G715, Arm's driver 0xd803000, Vulkan 1.4.343, Android 17, 16 GB of RAM). Odyssey was
packed from `main` at 648a3758 by `build_android_from_nsp.py`, then run from Odyssey-only APKs with #133 (`build_apk.py`). `scripts/bench_android.py`, two runs each, the
pipeline cache warm from earlier runs:

| Game, scene | Pixel 9 Pro XL |
|---|---|
| **Super Mario Odyssey 1.4.1**, Start menu (a fresh save) | 59.6–60.0 · 16.6–16.7 / 18.1–18.3 · GPU 0.9 |
| Super Mario Odyssey, the opening cutscene (Start pressed on a fresh save) | 59.8 · 16.6–16.7 / 19.0–19.6 · GPU 9.4–9.5 |

The picture is as on the Adreno (the Start menu, Bowser's airship). The first frame comes at 1.4–1.5 s, the Start menu at 11.4–11.5 s. The cutscene's first run, with none of its
pipelines cached, made 398 graphics pipelines in 9.5 s and measured 57.1 fps, with one 5.1 s frame as its scene loaded. Where this GPU differs from every Adreno above:

- **No BC textures** (`textureCompressionBC` false; the device line says `BC decoded on the CPU`). The replay has decoded BC on the CPU since the port began (`bcdec`, as for the
  original port's Adreno 619), and Odyssey draws right with it. #133 fixes its one red line, a BC view of a decoded texture (its entry in `docs/reference/rendering.md`: "BC textures decoded on the CPU, viewed in their BC formats").
  - **Time:** the cutscene's scene load decoded 265 textures (233 MB of texels) in 211 ms.
  - **Memory:** 2.2 GB resident in the cutscene, against 1.64 GB on the Odin 2 and the S25 Edge, where BC stays compressed. Re-encoding into formats of the same size that the
    GPU has (BC1, BC4 and BC5 to ETC2 and EAC; BC3 and BC7 to ASTC 4×4) would win that back. Open.
  - **Fixed:** a GPU block encoder writing into a decoded BC texture (Breath of the Wild's BC4 encoder) draws into a block shadow, and the shadow is decoded into the image
    on the GPU after the pass ([A GPU block encoder's blocks decoded on the GPU into a texture the CPU decoded](../../docs/reference/rendering.md#a-gpu-block-encoders-blocks-decoded-on-the-gpu-into-a-texture-the-cpu-decoded-android)).
    BC4 and BC5 only; an encoder of another BC format keeps the old path, with a red line.
- **16-lane subgroups** in fragment and compute shaders (`minSubgroupSize` = `maxSubgroupSize` = 16, so `VK_EXT_subgroup_size_control` cannot ask for a 32-lane warp).
  - **Odyssey** uses no subgroup operations.
  - **Quad shuffles** (Maxwell's fwidth, `c = 0x1c03`) read the right lanes: `t_quad_shuffle` passes on the Pixel as translated and as `spv_wide` and `spv_limits` rewrite them (#134). Those are all the
    shuffles in Brilliant Diamond (23 fragment shaders), Link's Awakening (5) and Animal Crossing (1).
  - **Warp-aggregated atomics** stay right in 16-lane groups: a ballot, a leader lane, one atomic, then a shuffle from the leader (most of Final Fantasy Resonance's compute
    shaders). The lane ID, the masks, the ballot and the shuffle's source all stay within one subgroup.
  - **Fixed: a shuffle from 16 or more lanes away has no lane to read.** Final Fantasy Resonance reduces over the whole warp with shuffles of 1, 2, 4, 8 and 16 lanes (clamp
    31) in 309 compute shaders. On this GPU the last step gave the lane's own value, which counted each subgroup's sum twice (`t_warp_reduce`). Each subgroup is now a warp of
    its own (`spv_narrow`: [rendering.md](../../docs/reference/rendering.md#maxwells-32-lane-warps-in-a-narrower-subgroup)). Mario Kart World has 3 such shaders, and 1,333
    of its shuffles take their source lane at run time (one past the subgroup reads the lane's own value). Final Fantasy Resonance's opening runs at 30 fps on the Pixel, GPU 23 ms.
  - **Not examined:** Animal Crossing's 499 fragment shaders with a ballot.
- **No `VK_EXT_vertex_attribute_divisor`, but `VK_KHR_vertex_attribute_divisor`** (core in Vulkan 1.4, `supportsNonZeroFirstInstance` false). The replay looks only for the EXT, so
  a vertex stream that stepped once every N > 1 instances stepped every instance, with red line 87. Fixed: the KHR one is enabled, and a draw with such a stream at a
  non-zero base instance starts at instance 0 with the base instance in its stream offsets, since this driver reads element `instance / N` there, base instance and all
  (`dm/android/tests/t_divisor.c`: 101 102 102 102 … at base instance 5, against NVN's 105 105 105 106 …). Neither Odyssey nor Final Fantasy Resonance has such a stream.
- **No `VK_EXT_shader_stencil_export`:** depth-stencil copies that a blit cannot make are drawn a stencil bit at a time, as on the Adreno 650. Odyssey made none on these routes.
- **"draws not made: pipeline N"** in the stats line counts the draws left out while pipelines met for the first time are built in the background (`DM_VK_ASYNC_PIPE`:
  [rendering.md](../../docs/reference/rendering.md#pipelines-met-for-the-first-time-built-in-the-background)), not pipelines that failed (`0 failed`, no red line). It was 718 in
  the cutscene's first run, and 9 and 0 in the warm ones.

## Xclipse: Brilliant Diamond on a Galaxy Z Flip 7

The first Samsung Xclipse GPU (2026-11-10): a Galaxy Z Flip 7 (SM-F766U1, Exynos 2500, Xclipse 950, an AMD RDNA design; Samsung's driver 24.0.533, 0x6000215; Vulkan 1.3.279,
Android 16, 12 GB of RAM), open, on its inner screen. Brilliant Diamond was packed from `main` at 648a3758 by `build_android_from_nsp.py`, the first DroidPlay install on this
phone, and boots with no change: the picture is right (the language menu, Eterna City's buildings, paving, cloud shadows and people), and the log has no red line.
`scripts/bench_android.py`, two runs each, the pipeline cache warm from earlier runs:

| Game, scene | Galaxy Z Flip 7 |
|---|---|
| **Pokémon Brilliant Diamond 1.3.0**, language menu (a fresh save) | 53.3–59.6 · 16.7 / 18.1–18.2 · GPU 0.5–0.6 (the first run's window caught the game's load, its first frame at 17.9 s); 60.0 · 16.7 / 17.9–18.0 with #144 |
| Pokémon Brilliant Diamond, Eterna City (a save) | 60.0 · 16.6 / 18.7–19.5 · GPU 10.8, the route's presses 7 s later (below); 59.6–60.0 · 16.5–16.6 / 19.2–20.6 · GPU 10.5–10.6 with #144 on the route as it is |

Where this GPU differs from the Adreno above:

- **Start-up:** the first frame comes at 9.7–17.9 s with a warm cache (3.2–4.3 s on the Pad 3), and at 99.4 s on the first launch after the install (33 s on the Pad 3).
  - **Warm:** Samsung's driver does a compile's work in `vkCreateShaderModule` (0.8–0.9 ms a module, about 0.1 on the Adreno 830), which its pipeline cache does not keep. The game's
    8,844 modules took 6.1–9.6 s of every start, its 2,982 pipelines 0.2–0.4 s. #144 makes a module only for a pipeline the cache lacks (`VK_EXT_shader_module_identifier`):
    the first frame at 3.2–3.3 s.
  - **First launch:** the pipelines' compile is 74.5–74.8 s (25 ms a pipeline) either way; with #144, 79.7 s, since only 5,672 of the modules are ever made.
  - **The `eterna` route:** its A presses at 16–25 s come during the game's 10–11 s load after the first frame (a 9.6 s frame on the Pad 3 too), so on `main` the game stays
    at the title. The table's runs used a local copy of the route with the presses at 23 s and the window at 42–72 s. With #144 the route as it is reaches Eterna City at 27.7 s.
- **Memory:** PSS 2.6 GB at the language menu and 3.4 GB in Eterna City, measured near each window's end. The driver keeps what it made of every module: with #144,
  1.4 and 2.1 GB.
- **No BC textures** (`BC decoded on the CPU`), as on the Pixel: Brilliant Diamond draws right, without either of the symptoms #133 fixes.
- **64-lane subgroups in every stage** (stages 0x3d3f, sizes 32 to 64, a required size in compute only): `spv_wide` rewrote Brilliant Diamond's 23 `fwidth` fragment shaders.
  No vertex shader of the nine games packed for Android on the Mac uses subgroup operations. Compute shaders in Final Fantasy Resonance (1,199) and Mario Kart World (184) do, and stay as
  translated, with `spv_wide`'s red line; neither game has run on this phone.
- **16-bit normalized formats it cannot filter:** R16_UNORM, R16G16_UNORM, R16G16B16A16_UNORM and their SNORM forms are sampled without linear filtering on this GPU. Brilliant Diamond's water simulation needs it, and drew Twinleaf's pond as a grid of white dashes until such textures were made in the 16-bit float formats ([16-bit normalized textures a GPU cannot filter](../../docs/reference/rendering.md#16-bit-normalized-textures-a-gpu-cannot-filter)).
- **The cover screen:** folding the phone while the game plays puts it in the background (focus states 2 and 3, audio suspended) and shows Samsung's own cover home on the cover
  screen. The game process keeps running, and nothing crashes. Opening the phone brings back its lock screen first. Not seen:
  - the game's return after unlocking (the next install stopped it);
  - the game on the cover screen, Samsung's per-app setting, with the window size change it would bring (`sc_follow_window`).

  The fold was simulated with `cmd device_state`, which locks a phone that has a secure screen lock.
- **The benchmark's screenshots:** `screencap` needs a display on a phone with two screens; without one, every shot was unreadable before #132.

## Adreno 730: a Moto Razr Plus 2023

The first Adreno 730, 2026-11-10: a Moto Razr Plus 2023.
- **Hardware:** SM8475, Snapdragon 8+ Gen 1; Adreno 730 with Qualcomm's driver V@0615.98 (0x80267062, built 2025-05-02); Vulkan 1.1.128; Android 16; 8 GB of RAM.
- **Setup:** open, on its inner screen (1080 × 2640, modes from 24 to 165 Hz, 90 Hz when the runs began), with the on-screen controls.
- **Build:** an APK of Brilliant Diamond's, Odyssey's and Final Fantasy Resonance's hosts built from `main` at 30215723, the first DroidPlay install on this phone, with each game's chain-5 shaders from `main`.
- **Runs:** `scripts/bench_android.py`, a warm-up plus two runs.

| Game, scene | Moto Razr Plus 2023 |
|---|---|
| **Super Mario Odyssey 1.4.1**, the opening cutscene (Start pressed on a fresh save) | 57.4–58.1 · 16.8–17.0 / 20.2 · GPU 12.5–12.6 (the warm-up 52.5) |
| **Pokémon Brilliant Diamond 1.3.0**, language menu and Eterna City | **Crashes** at boot, before its first frame, in every launch (6 of 6): the driver's shader compiler |
| **Final Fantasy Resonance 1.0.1**, the first field (the `battlefield` save) | **The GPU hung** as the field appeared, about 56 s in, in every run (3 of 3), with no frame after it. With `spv_xor` (`main` 5c21a252, two runs, no warm-up): 19.9–20.0 · 50.4–50.7 / 59.8–60.3 · GPU 30.5, no hang |

Where this GPU differs from the Adreno above:

- **Brilliant Diamond's crash** is in the driver's shader compiler: `CRASH sig=11 addr=0x48 pc=libllvm-qgl.so+0xd8a064`, on the replay thread, about 4 s into the boot.
  - It happens building the pipeline of vertex shader `472d0b6794a8a777` and fragment shader `5ec702f7caaf2ff6`, at the same address in all six launches.
  - It isn't problem 2's: that fragment shader has no subgroup operation and no derivative, and this GPU runs subgroup operations in fragment shaders.
  - The game boots on the Adreno 650 (driver V@0746), the 740 (V@0676) and the 830 (V@0800), all newer drivers than this one. Not narrowed down yet.
- **Final Fantasy Resonance's hang:** 55–60 fps through the load and the field's first frames. Then one submission ran 10.2–10.6 s on the GPU until the driver's hang recovery cut it short, its end timestamp never written; its last commands were compute dispatches.
  - The game kept running (sound, vsync) and drew no further frame.
  - Its red line `a compute shader with Maxwell's 32-lane warp instructions on the GPU's 64-lane subgroups` (`e918336692525691`) shows on the other 64-lane GPUs too, where the field plays. It isn't the hang's cause.
  - **Found and fixed:** the particle simulation's warp reduction through the translator's butterfly shuffle comes back as garbage on this driver, so a sprite draw asked for billions of instances. `spv_xor` makes that shuffle ShuffleXor: [Maxwell's butterfly shuffle on the Adreno 730](../../docs/reference/rendering.md#maxwells-butterfly-shuffle-on-the-adreno-730).
- **The flames:** the field's last frame before the hang has black pixel-art shapes along the road where its flames burn. That's the Ayn Odin 2's Adreno 740 picture before droidplay-core#135, whose run-time rows it turns on for Qualcomm's Adreno 7xx. So it points the same way for the 730, from one frozen frame: the hang came before the route's walk, and #135 wasn't run here.
- **Odyssey** plays the opening at 57–58 fps, with GPU 12.5 ms against the Odin 2's 5.5 ms; the picture is right.
- **Vulkan:**
  - 64-lane subgroups in fragment and compute shaders only (stages 0x30), so `spv_wide` applies.
  - No `VK_EXT_shader_module_identifier`, so #144's lazy modules stay off.
  - `VK_EXT_vertex_attribute_divisor` but not the KHR one; `VK_GOOGLE_display_timing`.
  - BC, ETC2 and ASTC textures; `maxStorageBufferRange` 128 MB.
- **The cover screen** (1056 × 1066, 48 to 144 Hz) was off: the phone stayed open. The screenshots came from the inner screen with droidplay-core#154's `bench_android.py`.

## Known problems

Numbered in the order they were found, so links to a number stay right:

1. **Fixed: Super Mario Odyssey crashed when a hint video played.** The Snapdragon 8 Gen 2's H.264 decoder gave the host's image reader UBWC-compressed
   NV12, whose colour planes the CPU cannot map, and `media_android.c` read through the null plane (`CRASH sig=11 addr=0`) as play started in the Cap
   Kingdom. The decoder now asks for flexible YUV, which gets linear NV12, and a picture without readable planes is dropped rather than read: [Android:
   H.264 pictures in a buffer the CPU cannot read](../../docs/reference/movies.md#android-h264-pictures-in-a-buffer-the-cpu-cannot-read). Games whose movies are
   VP9 (Smash) take the software decoder and were not affected.
2. **Fixed: Brilliant Diamond crashed on the Retroid Pocket 5** in the Adreno 650 driver's shader compiler (`libllvm-qgl.so+0x2dcef0`, `addr=0x48`) on every
   launch, as it built its first pipelines. The pipeline being built (vertex shader `f8d70797a143b99f`, fragment shader `b2f8ca02b9c1a06c`) is one of the 23 whose
   fragment shader shuffles: Maxwell's `fwidth`, translated to `OpGroupNonUniformShuffle`, in a stage where this GPU runs no subgroup operations
   (`subgroupSupportedStages` is compute alone; the Adreno 740 and 830 run them in fragment shaders too). With that shuffle made a copy of its own value, the
   pipeline built and the crash moved to the next of the 23 (`74f249b01166d890`); with all 23 shuffles out, the game booted. Such modules are now rewritten as
   they are made, the quad's lanes read through fine derivatives: [Subgroup operations rewritten for stages the GPU runs none in](../../docs/reference/rendering.md#subgroup-operations-rewritten-for-stages-the-gpu-runs-none-in).
   The game boots and plays on the phone's own driver (2026-11-10): the language menu at 60 fps, Eterna City at 14.9 fps (problem 13). Mesa's Turnip compiled
   the modules as they were (`DM_VK_DRIVER`, [Another Vulkan driver](README.md#another-vulkan-driver-dm_vk_driver)): Eterna City at 57.7–58.2 fps (GPU 8.8–9.2 ms) on the same build.
3. **Fixed: Smash crashed at boot with Android's stock shared font.** The standard shared font was the device's Roboto, which has no TrueType hinting,
   and Smash's font engine needs a hinted font (`main+0x7caa0`, `addr=0x38`). The packer now copies a hinted TrueType font into each game's
   `font/standard.ttf` (Arial Unicode on a Mac, as the iPhone build does), and Smash boots on all three devices: [Android: the standard shared font must
   be hinted](../../docs/reference/services.md#android-the-standard-shared-font-must-be-hinted).
4. **Fixed: Smash and Odyssey crashed now and then at boot.** Smash crashed at `main+0x385201c` (`addr=0x50`) in a `render dispatch` thread, even with the font, on
   all three devices (about one launch in five; on the Retroid Pocket 5 3 of 12, 2 of 12 with `DM_PREEMPT=1`, 1 of 6 with a test host keeping that sum). Its two
   render dispatch threads sort their pool of command buffers by `nvnCommandBufferGetCommandMemorySize` while the other one records into them, and the host summed
   that size at each call from the bytes used and the write pointer, which a record written in between tore. The test host compared each sum with the size kept for
   the buffer: 7 to 29 torn sums per boot, and in the boot that crashed, the last one was the sort's pivot, read 0x190 bytes short just before the crash; the sort
   then read it right and walked past the vector's start. Fixed with nxnative's 843081d0, the size kept from `AddCommandMemory`: [`GetCommandMemorySize` read while
   another thread records](../../docs/reference/nvn-objects.md#getcommandmemorysize-read-while-another-thread-records); with it, 0 of 18 boots crashed on the
   Retroid Pocket 5, at the same frame times. Odyssey crashed on the Odin 2 three times in about 20 launches, all in its first seconds of loading: twice in its
   loader thread as the mode-select layout loads (`main+0x95d414` with `addr=0`, once `svcBreak`), once at `main+0x954fb8`; never in 18 launches on the other two
   then, but later in about one launch in four on the Retroid Pocket 5. Fixed by the host for every game (first by `core_preempt on` in its profile): [A thread woken by a higher-priority thread of
   its core runs before that one blocks](../../docs/reference/threads.md#a-thread-woken-by-a-higher-priority-thread-of-its-core-runs-before-that-one-blocks).
5. **Fixed: the pipeline cache was saved only when the app paused** (`vkb_pipeline_cache_save` on `APP_CMD_PAUSE`). The list of pipelines to make again at start
   (`pipeline.cache.keys4`) is written as each one is made, but the driver's compiled binaries are in the cache, so after a stop by force (the benchmark, or a player
   swiping the app away) the next start made the whole list again without them, in the background while the game played. The Pad 3's driver builds them about six
   times slower than the Odin 2's: a Smash battle made 682 to 943 pipelines in 11 to 12 s on it (1,147 in 3.1 s on the Odin 2, 368 in 12.5 s on the Retroid Pocket
   5), which is where its battle frames of 100 to 370 ms came from. The cache is now also written during play, after every 64 new pipelines and at most every
   15 s, on a thread of its own: [The pipeline cache written during play](../../docs/reference/rendering.md#the-pipeline-cache-written-during-play). Two Smash
   battles on the Pad 3 afterwards: 32.3 and 34.0 fps, frame p95 37.7 and 38.6 ms (16.8 to 29.7 fps and 73 to 81 ms before; the stage differs from run to run). Pipelines met for the first time are now built in the background, their draws left out for a few frames: from an empty
   cache, two battles at 40.0 and 40.2 fps against 27.9 and 26.5, frame p95 33 and 35 ms against 96 and 85: [Pipelines met for the first time built in the
   background](../../docs/reference/rendering.md#pipelines-met-for-the-first-time-built-in-the-background).
6. **Fixed: the Retroid Pocket 5 could not hold 60 fps in Odyssey's opening cutscene** (38 fps, GPU 12.9 ms a frame, on 2026-11-08). The regression pass of
   `main` at `54711866` (2026-11-09) measured 59.4–59.5 fps there, and `main` at `54e21235` runs it at 59.3–59.4 (frame p95 18.7–18.9 ms, GPU 12.3–12.4 ms),
   the same with `DM_VK_WB_READBACK=0`, so problem 13's fix plays no part. Most likely fixed by droidplay-core#28 (queued NVN commands grow by doubling),
   which `54711866` holds; not measured on its own.
7. **Not seen in a game: the Pad 3's H.264 decoder took no input** in `dm/android/tests/t_media` (`[RED] movie: the AVC decoder took no input for 2 s`), before
   and after the fix in problem 1.
   - **In a game it decodes (2026-11-10, no build):** Super Mario Odyssey's first hint video (`MovieData/PlayGuideMovieRStick.mp4`, H.264 High, 480×272) played in
     the Look Around hint box on the Pad 3, with DroidPlay 0.7.0-1-g4743c9da and the SMO it held (`make_save` route). The log has `[movie] AVC: MediaCodec decoding,
     profile 100` and 19 pictures of 195,840 bytes (NV12) before the route answers the hint, with no red line and no crash.
   - `t_media` was not run again, so why it saw no input there is still unknown.
8. **Fixed: Link's Awakening drew wrongly on all three devices.** Its movies and two of its HUD icons came out in ring-banded colours, and in play the 3D
   world was black behind the HUD, without ambient occlusion. Pass dumps (`dump_now`) of the overworld on the Odin 2 showed where:
   - **Fixed: the colours, a raw copy between two formats.** The frame's last target (`s4`, R11G11B10F) holds the right colours; the game then copies it
     into its RGBA8 window texture, and `copy_t2t` in `gfx_vk.c` copied the bits, since its test for a raw copy held for any two formats the replay does
     not convert on the CPU. A format change between float, normalized and sRGB formats is now a blit: [Texture copies that change format convert on
     Vulkan](../../docs/reference/rendering.md#texture-copies-that-change-format-convert-on-vulkan). The movies, the file select and the HUD have their
     colours on the Odin 2.
   - **Fixed: the black world, culled full-screen passes.** The scene was drawn (pass 22), but every pass after it kept its cleared value: the occlusion,
     its blurs and the composite. A dump with each draw's depth and stencil tests showed the blurs and the composite had none, so they were culled: the
     replay inverted the front face by the device's origin and the queue's raster flip together, which cancel for a game that keeps the lower-left origin
     for both. It now inverts by the queue's flip alone, as Metal's draws do: [The front face follows the queue's raster flip alone on
     Vulkan](../../docs/reference/rendering.md#the-front-face-follows-the-queues-raster-flip-alone-on-vulkan). The Ancient Ruins draw at 59.9 fps on the
     Odin 2.
   - **Fixed: no ambient occlusion.** The replay skipped the game's half-size depth-stencil copies (`[RED] [vk] texture copy with a format change or
     scaling between formats 130 and 130: not blittable on this GPU`): no Adreno blits `D32_SFLOAT_S8_UINT`. The occlusion pass tests its stencil (bit 1)
     against the copy, so it wrote nothing and its target kept its cleared 1.0. The copies are now drawn: [Depth-stencil copies a blit cannot make, drawn on
     Vulkan](../../docs/reference/rendering.md#depth-stencil-copies-a-blit-cannot-make-drawn-on-vulkan).
9. **Fixed: Link's Awakening crashed at boot** on every launch on the Retroid Pocket 5 (7 of 7), now and then on the Pad 3 (3 of 8), never on the Odin 2
   (0 of 10): `CRASH sig=11 pc=main+0x1c180` about 0.4 s in, in the constructor of the camera `MainCamera_1P`. It reads an entry of a 0x58-byte table at
   `main+0x1bcc898` by a 16-bit index that is always 0xFFFF there (its caller sets it at `main+0xbdb68` and nothing changes it), so every boot reads 5.5 MB
   past the table, past main's end. Not a race in the game: on a Switch the modules are mapped back to back and that address is subsdk0's code, while the
   host mapped each module where `mmap` put it, and on Android what lay past main depended on what other mappings had filled the gap by then. The modules
   are now mapped back to back: [Modules back to back, as Horizon maps them](../../docs/reference/memory.md#modules-back-to-back-as-horizon-maps-them-android).
   On the Retroid Pocket 5 0 of 11 boots crashed after it, and 6 of 6 on the same build with `DM_MODULE_PACK=0` (the old placement), each at `main+0x214c889`.
10. **Fixed, cause not bisected: Skyward Sword HD drew Skyloft's terrain and sky flat grey** on the Odin 2 and the Pad 3, with no red line. A pass dump on the
    Pad 3 showed the terrain grey in the first pass that draws it, while Link and the bird statue, drawn next with the same ASTC 6×6 textures, had their colours.
    The terrain's draws also sample 64×64 textures the game renders earlier in the frame, which came out black. The opening movie was right.
    - **Check (2026-11-10, no build):** Skyloft is in colour on both. Each ran the `skyloft` route with the SSHD it held. On the Odin 2 that was SSHD's code and
      shaders from `cf42941d` (chain 4) and a host from the RP5 save-fix branch of that morning (#123, since merged): three runs, 56–60 fps. On the Pad 3 it was
      DroidPlay 0.7.0-1-g4743c9da with SSHD's files from 2026-11-09 22:08 (chain 4): two runs, 60 fps, GPU 6.8 ms.
    - Grey was last recorded on `main` at `ee18169a` (2026-11-08). The wide-subgroup rewrite (`DM_SPV_WIDE=0`) and layered targets (SSHD makes no layered pass) are not
      what fixed it. Candidates, not tested: the replay's copy fixes of 2026-11-08, texture copies between formats converting (`97fce01c`) and depth-stencil copies a
      blit cannot make drawn (`b86d5505`).
11. **Fixed for Skyward Sword HD: it played at 30 fps** on the Odin 2 and the Pad 3 (the Mac runs Skyloft at 60): the game drops its present interval
    to 2 when frames come late. Its long frames showed the replay writing a 1920×1080 RGBA8 render target back to guest memory after its pass (`[vk]
    linear render target s19 1920x1080 (format 0x25) written back to guest memory`) and uploading it again (`texture uploads 0 first + 2 re-uploads,
    15.8 MB`), with submit and present taking up to 36 ms while the GPU takes 5 ms on the Odin 2. Its profile now turns on `DM_VK_WB_ABSORB` (59.7 fps
    on the Pad 3, 59.3 on the Odin 2): [A linear render target uploaded again after its own write-back, every
    frame](../../docs/reference/rendering.md#a-linear-render-target-uploaded-again-after-its-own-write-back-every-frame). That Odin 2 figure was one run:
    later runs spread from 33 to 57 fps, the write-back's 8.3 MB staging buffer being made and freed every frame. It is pooled now (60 fps in three runs of
    three on the Odin 2, 60.0 on the Pad 3): [A 1080p linear render target's write-back staged in a buffer of its own every
    frame](../../docs/reference/rendering.md#a-1080p-linear-render-targets-write-back-staged-in-a-buffer-of-its-own-every-frame). Link's Awakening's overworld
    likewise falls to 31 fps on the Pad 3: the game switched interval 175 times in one run there, against 4 on the Odin 2. On the Galaxy S25 Edge, the
    other Adreno 830 here, it plays at 38.1–44.6 fps over the Ancient Ruins window (frame p50 16.8–32.5 ms, GPU 13.0–13.7 ms).
12. **Link's Awakening's overworld plays at 30 fps on the Retroid Pocket 5** (34.7–36.0 fps over the Ancient Ruins window, frame p50 33 ms, p95 34.5 ms, the
    picture right; 32.3–32.4 on `main` at `54e21235`, and 32.3–32.7 there with `DM_VK_WB_READBACK=0`: its two write-backs a frame, 34 KB, take under 0.1 ms
    through problem 13's copy and 0.4 ms without it). The game sets its present interval from the vsyncs its last frame took (`main+0xca44`–`0xcb24`, applied at `main+0x1144c18`), and frames
    there take two even at interval 1, so it switches between 1 and 2 about 350 times a run. Per frame in that window: the game's own CPU 5.3 ms, the
    replay's recording of about 616 draws 9.7 ms on the game's thread (`@nvn_ms`), a 9.0 ms `nvnSyncWait` on the GPU (`@sync_ms`), GPU 12.9 ms at 490
    MHz, the floor this device keeps (`min_pwrlevel` 3; 670 MHz at most), 44% busy. The wait and the work after it are in series, so a frame's work takes about
    24 ms, two vsyncs; 60 fps needs the recording cost or the GPU's time to come down by about a third, or the two to overlap. Not worked on yet.
13. **Fixed: Brilliant Diamond's Eterna City ran at 15–25 fps on the Retroid Pocket 5's own driver** (14.9 fps after problem 2's fix, 24.0–24.6 on `main` at `4743c9da`,
    frame p50 40–41 ms, GPU 16.8–17.0 ms), against 57.7–58.2 fps with Turnip on the same build. The completion thread (`vk-done`) took 26 ms a frame landing six
    storage-buffer write-backs of about 494 KB: the driver lists the arena's memory type 4 as cached and coherent (`0xf`), but the CPU maps it uncached (1.3–1.6 GB/s
    with wide loads, about 50 ns a byte in `wb_apply`'s byte loop, against 11–13 GB/s from malloc'd memory). The GPU now copies such write-backs into a cached
    transfer-destination buffer (type 2, `0xb`) at each submission's end and the completion thread reads them from there, 1.7 ms a frame: Eterna City at 54.6–60.0 fps
    (60.0 in three runs of four; frame p50 16.6–18.2 ms, GPU 13.5–15.0 ms) in runs alternating with `main`'s, the picture the same. [Storage buffer write-backs read from
    memory the CPU maps uncached](../../docs/reference/rendering.md#storage-buffer-write-backs-read-from-memory-the-cpu-maps-uncached).
    - **On `main`** at `54e21235` (2026-11-10): Eterna City at 59.0–59.6 fps, 21.0 with `DM_VK_WB_READBACK=0`. At that hour the scene had 1,100 draws and seven write-backs
      of 637 KB a frame (1,068 and six of 494 KB in the runs above), frame p95 26.6–26.9 ms; landing them took 2.3–3.0 ms a frame through the copy, 34 ms from the arena.
    - **Other games.** The timing check turns the copy on for every game on this driver. Odyssey's opening, Link's Awakening's Ancient Ruins and Animal Crossing's
      airport and island run at the same rates with it off: they land 0–12 write-backs a frame, at most 34 KB in all.

14. **Fixed: Breath of the Wild lost the GPU on the Pad 3** at its first frame in the field. Then `vkQueueSubmit` gave -4 (`VK_ERROR_DEVICE_LOST`), the loading screen stayed up for good, and the GPU time read 0.
    - **What hangs.** One draw a frame hangs the GPU: vertex `2decd3e894b3736a`, fragment `26ae1640f3448ba4`, a fullscreen triangle sampling one 640×360 RGBA8 texture into another, the vertical pass of a blur whose horizontal pass runs fine just before it. The driver recovers each hang about 250 ms in (the chunk's fence signals, its end timestamp never written) until one runs past 3 s. `VK_EXT_device_fault` gives no address and no vendor record.
    - **How it was found.** droidplay-core#90 logs such chunks with their draws, and a `vk_mid` file holding 1 cuts the chunks after every draw.
    - **Still hangs with:**
      - `DM_VK_UBWC=0`, `DM_VK_LAYERED=0`, `DM_VK_TBUF_RANGE=0`, `DM_VK_SAFE=1`, `DM_VK_GEOCACHE=0`, `DM_VK_BIND_FILTER=0`;
      - robustBufferAccess;
      - a full colour write mask (the draw's is 0xe);
      - the zero stand-in texture in place of its source;
      - the horizontal pass's fragment or vertex module in place of its own;
      - `VK_EXT_depth_clip_control` instead of the `.z` vertex variant;
      - its target cleared before the pass;
      - draws that sample an attachment of their own pass skipped;
      - duplicate colour attachments left unused;
      - the earlier pass that binds the target alone (below) with its draws skipped: its clear still begins it.
    - **What differs.** Its pipeline key is the horizontal pass's byte for byte but for the write mask, with the same D16 depth image. Only the target image differs: it is also the sixth colour target of the G-buffer passes.
    - **Not on the Odin 2.** Its Adreno 740 (driver 0x802a4000) runs the same draw without a hang: seven launches of the same save on main 1e4dd802 with droidplay-core#108, nothing skipped, no slow submission reported.
    - **Cause.** An earlier pass of the frame binds that target alone in colour slot 5, with slots 0–4 empty (`VK_ATTACHMENT_UNUSED`). That pass runs; the later one drawing into the target as slot 0 hangs. A scratch target in every empty slot below a used one stops it, and so does one in slot 0 alone. Filling only a G-buffer pass's empty slot 6 below slot 7, or zeroing the write masks of empty slots, doesn't.
    - **Fix.** On every Adreno on Qualcomm's driver (Adreno 8xx at first; the 730 crashed on such a pass in Mario Kart 8 Deluxe) a render pass with colour slot 0 empty below a used slot gets a scratch RGBA8 target there (`DM_VK_SLOT0_FILL`, [rendering.md](../../docs/reference/rendering.md#a-render-pass-with-colour-slot-0-empty-hangs-or-crashes-qualcomms-adreno-driver-android)). About one pass a frame gets it in BotW.
    - **Check** (main 4743c9da with the fix, BotW's defaults from droidplay-core#108): 30.0 fps in three runs, no hang report. With `DM_VK_SLOT0_FILL=0` the GPU is lost as before. The picture is still wrong there (problem 15).

15. **Fixed: Breath of the Wild's Shrine of Resurrection was drawn dark and blurred on the Adreno 830**: Link unlit, the walls a blur, on the Pad 3 and the Galaxy S25 Edge (Samsung's driver 0x80320001), where the Odin 2 draws them right.
    - **Cause.** The 1280×720 G-buffer passes bind one image in two colour slots (1 and 2, 3 and 4) and write only the first of each pair (mask 0xf0f0ff). Each slot was its own attachment of the same view, loaded and stored. Vulkan leaves attachments that alias in one subpass undefined, and the 830 apparently stores the unwritten copy over the written one.
    - **Fix.** A render pass attaches each image once, on every GPU, and leaves its other slots unused (`DM_VK_DUP_SLOTS`, [rendering.md](../../docs/reference/rendering.md#one-image-in-two-colour-slots-of-a-pass-is-drawn-wrong-on-the-adreno-830-android)). About 18 passes a frame in the Shrine.
    - **Check** (S25 Edge, main 54e21235 with the fix and BotW's defaults, a warm-up and 2 runs each way): the Shrine is drawn as on the Odin 2, with no write lost. 29.9 fps, GPU 20.5 ms, against 21.4 ms without the fix. With `DM_VK_DUP_SLOTS=0` it is dark as before. On the Pad 3 only a local test of the same idea has run so far, and it drew the room right.
    - **Not on the Adreno 840.** A Galaxy Z Fold 8 (Qualcomm's driver 0x8034a013, folded) draws the Shrine right either way: 23.7–23.9 fps, frame p95 47.8–48.1 ms, GPU 29.6 ms with the fix, against 23.1–23.3 fps, p95 48.2–48.3 ms, GPU 30.3 ms without it, no write lost.
16. **Smash's battles on the Retroid Pocket 5 stay just under 60 fps on the heavier stages** (57.0–58.8 fps on `main` at `3b07c5cf`, 2026-11-10; 13.4–19.3 in the
    first baselines, when its pipelines were built during play: problem 5). Pipelines no longer hold it: from an empty pipeline cache a battle ran at 59.4 fps while
    560 pipelines were built in the background (about 52 ms each on this driver, 11,656 draws left out meanwhile), and warm runs build almost none. Nor does the GPU,
    at 5–10 ms a frame. The replay's CPU time does, because it runs in series with the game's own frame: the game's thread waits in `SyncWait` for the frame the
    replay is still turning into Vulkan, so a frame takes about the replay's wall time plus 5.5 ms. The frames over 20 ms are those with 500–600 draws (330–390 in the
    60 fps ones), where the replay took 13–18 ms of CPU.
    - **The replay's cost.** About 27 µs a draw on the phone's Cortex-A77, on the three 2.42 GHz cores and never the 2.84 GHz one (`DM_VK_PLACE_LOG=1`); the power
      HAL has no performance hint sessions, so nothing raises its clock (`[hint] no performance hint session`). In a profile half of the replay thread was `memcmp`
      and `memcpy` and about an eighth the driver itself. Most of the copying was read-only storage buffers copied into every chunk and compared at every draw,
      2.1–2.2 MB a frame of the same bytes: kept on the GPU, the replay takes 22 µs a draw instead of 29 (droidplay-core#162). The completion thread took 1.1–4.0 ms
      a frame landing 1.1–1.8 MB of storage-buffer write-backs a byte at a time, before the chunk's NVN fence; a word at a time it is about twice as fast
      (droidplay-core#161).
    - **Rare long frames** of 90–120 ms remain in warm battles: a few pipelines the background builder leaves to the replay thread (a target drawn for the first
      time), about 48 ms each, and an 84 ms submission with none, not explained yet.

17. **Fixed: Final Fantasy Resonance's first field had no flames on the Odin 2**: the pixel-art flames along the road were black holes, where the Pad 3 and the S25 Edge
    drew them.
    - Its 35 flame cards a frame (vertex shader `19274e72bf8f5d0d`) were binned nowhere. Qualcomm's Adreno 740 driver bins a pass with a position-only copy of
      the vertex shader, and that copy read Unreal's clip matrix (c3 rows 0-3, constant indices) as garbage. Turnip (`DM_VK_DRIVER`) drew them.
    - **Fix.** `spv_android.py` `pos_rows` (`ANDROID_CHAIN` 6) lets a vertex shader's position read its constant buffer rows at run time, behind a specialization constant the
      replay sets only on Qualcomm's Adreno 7xx driver and only for the vertex shaders a game's profile names (FF's `vk_pos_rows`: the flames' vertex shader)
      ([rendering.md](../../docs/reference/rendering.md#a-vertex-shaders-position-lost-in-the-adreno-740s-binning-copy)).
    - **Check** (the Odin 2, main `b75f9719` against the fix, a warm-up and 2 runs each): FF's field at 42.1 fps on both, GPU 12.4 ms on main without the flames and
      13.0 ms with them; Animal Crossing's island 8.6–8.8 ms on both, Skyward Sword HD's Skyloft 3.7–3.8 ms on both, as their profiles name no shader.

## Reading the numbers

- **Cold pipelines.** Because of problem 5 (since fixed), every run here began without the driver binaries of the pipelines earlier runs made, most of all on
  the Pad 3.
- **GPU time is at the clock the driver chose.** The Pad 3 shows longer GPU times than the Odin 2 in light scenes although its GPU is faster: it keeps its
  clocks low when the work is light. Compare the GPU column within one device, not across devices.
- **Fixed: the Retroid Pocket 5 couldn't run a route whose game saves early.** The benchmark keeps each run's save in the app's external files. On the
  Retroid Pocket 5 (kernel 4.19) that folder is sdcardfs, which cannot swap two folders atomically (`renameat2` with `RENAME_EXCHANGE` fails with `EINVAL`)
  and has no extended attributes, so every save commit failed: `[RED] save commit: atomic swap failed errno=22`. Animal Crossing saves as soon as the island
  loads, so it stopped with its "an error occurred" screen, which it drew at 30 fps, and the first published version of this page counted that as the island.
  Skyward Sword HD saves while its file list loads, and crashed (`main+0xf2b210`, `addr=0x20`) when it read the save back after the failed commit. A player's
  saves are in the app's internal storage (f2fs), which can swap, so play was never affected. The host now swaps with plain renames where `RENAME_EXCHANGE`
  is refused, and the save's mount puts back a swap that a kill cut short ([services reference](../../docs/reference/services.md#android-a-save-folder-on-sdcardfs)).
  Both routes now run there with every commit made (18 a run in Skyward Sword HD, one in Animal Crossing), and a restart on the committed save loads it.
- **The Pad 3's logcat drops lines from a game that logs fast.** Android 16 rate-limits an app's log, and Link's Awakening logs every file open, so the
  line that marks it ready never reached logcat. The benchmark now takes it from the host's own `log.txt` when logcat lacks it.
- **Smash's battles are a range, not a baseline.** The route picks Random stage and a random CPU fighter (D-pad moves on the stage grid did not land on the
  same stage from run to run), so the load differs per run.
- **Animal Crossing's island has a pinned clock.** `DM_FIXED_TIME` fixes the island at 3 PM on the day after the save, so the light and Isabelle's announcement
  repeat.
- **The Galaxy S25 Edge's runs alternate with another build's.** Its column and the Odin 2's Final Fantasy Resonance rows were measured during PR #76's
  regression check: `main`'s warm-up and first run came after the PR's warm-up and first run, and its second run after the PR's second, each build
  reinstalled from its own APK with its own code and shaders, so a second run starts with the driver's pipeline cache holding both builds' pipelines. On the
  S25 Edge, Link's Awakening's overworld (problem 11) and Final Fantasy Resonance's field vary by a few fps from run to run, and Smash's battle with its stage.
- **The Odin 2's runs after the first may have started from the last run's save** in the boot routes and Odyssey's cutscene (a script bug since fixed). Those
  routes never reach a save point, so the scene is the same.

## Saves

Brilliant Diamond, Animal Crossing and the two Zelda games start from downloaded saves, which this repository does not contain (they are other people's
files):

- Brilliant Diamond: MegaMarble's 1.3.0 "100% Save File" (GameBanana mod 634809, `pkmnbrilliantdiamond_100.7z`, `SaveData.bin` only), in the NSP folder's
  parent as `saves/eterna`.
- Animal Crossing: Anrei's 3.0.1 + DLC save (GBAtemp download 39784), linked once to the host's user (the unlinked-resident prompt: Existing data, then the
  resident, then Link) and kept as `saves/island_linked`. The host's user ID is fixed, so the linked save works on every device and on the Mac.
- Link's Awakening: techhit's save from the Ancient Ruins, after the fifth dungeon (a Tinfoil backup attached to GBAtemp thread 549404,
  `1D6B3FEC0200001087A5E3E5734E0501.zip`; `savedata0.bin` and `savedata3.bin` only), as `saves/ruins`. Made on 1.0.x in 2019; 1.1.0 loads it.
- Skyward Sword HD: soaresden's Checkpoint dump attached to GBAtemp thread 591874 (`20210726-014323 Soaresden.zip`; `wiiking2.sav` and `skip.dat` only), as
  `saves/skyloft`. Its file list has the autosave and three files; the route takes the third, a Hero Mode file at 31 hours that starts at Skyloft's bird
  statue. Made on 1.0.0; 1.0.1 loads it.

- Breath of the Wild: `saves/outdoors`, the save the Mac's smoke route uses (`dm/games/01007EF00011E000/smoke.tsv`). It loads in the Shrine of Resurrection.

Smash's battle and Odyssey's routes start from a fresh save.

## Running them again

```
python3 scripts/bench_android.py <NSP folder> [<NSP folder> ...] -s <serial> [-s <serial> ...] --route <name> --warmup --runs 2
```

The routes are in each game's `dm/games/<id>/bench_android.tsv` ([dm/android/README.md, Benchmarks](README.md#benchmarks)). Smash needs its packed
`font/standard.ttf` (problem 3); a game packed before that change needs packing again.

One run or install at a time on a device: `bench_android.py` locks every device it uses for the whole run, and `build_android_from_nsp.py` locks the phone
while it installs or decodes shaders there, so a second one is refused with who holds the device and since when (`--wait-device <s>` waits instead). Two
benches on one device used to force-stop each other's game and overwrite each other's `env.txt`, voiding both. `python3 dm/android/tools/device_lock.py`
lists who holds which device, and `NXNATIVE_DEVICE_HOLDER=<name>` names a run in that list. A crashed run gives its lock up.
