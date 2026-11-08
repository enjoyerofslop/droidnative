# Android baselines

The first baselines of droidnative on more than one device: four Switch 1 games on three Snapdragon devices, run the same way on each with
`scripts/bench_android.py` (the same save, scripted input and measuring window). Measured 2026-11-08 on droidnative `main` at `f4f7abb3` with PR #1 (the
present's vsync sleep outside the submission lock) and PR #3 (the game window keeps the screen on), each game packed by `build_android_from_nsp.py`.
They are a starting point for fixes, not a verdict: every known problem below is open.

## Devices

| Device | SoC | GPU, driver, Vulkan | Android | RAM |
|---|---|---|---|---|
| Ayn Odin 2 | QCS8550 (Snapdragon 8 Gen 2) | Adreno 740, V@0676.32, 1.3.128 | 13 | 12 GB |
| OnePlus Pad 3 | SM8750P (Snapdragon 8 Elite) | Adreno 830, V@0800.74, 1.3.284 | 16 | 12 GB |
| Retroid Pocket 5 | SM8250 (Snapdragon 865) | Adreno 650, V@0746.0, 1.1.128 | 13 | 8 GB |

All three use 4 KB pages. The Odin 2 and the Retroid Pocket 5 have built-in controls; the Pad 3 shows the on-screen controls over the game.

## Results

Frames per second over a 30 s window, then frame time p50 / p95 in ms, from two measured runs after a warm-up run (ranges where they differ). GPU is the
median GPU time per frame. Animal Crossing runs at 30 fps on the Switch too.

| Game, scene | Odin 2 | Pad 3 | Retroid Pocket 5 |
|---|---|---|---|
| **Super Mario Odyssey 1.4.1**, Start menu (a fresh save) | 60 · 16.7 / 17.6–18.7 | 60 · 16.6 / 18.0 | 60 · 16.6 / 17.5–17.9 |
| Super Mario Odyssey, the opening cutscene (Start pressed on a fresh save) | 59.9 · 16.7 / 18.4 · GPU 5.5 (one run crashed at boot) | 59.9 · 16.7 / 18.9 · GPU 9.3 | **38** · 25.9 / 30.6–31.5 · GPU 12.9 |
| Super Mario Odyssey, play (Cascade Kingdom) | **Crashes** at the first hint video | not run (same code path) | not run |
| **Pokémon Brilliant Diamond 1.3.0**, language menu (a fresh save) | 60 · 16.7 / 19.2–19.4 | 60 · 16.6–16.7 / 18.5–18.8 | **Crashes** at 2.6 s |
| Pokémon Brilliant Diamond, Eterna City (a save) | 60 · 16.6 / 18.1–18.2 · GPU 8.1 | 58.9–59.7 · 16.6–16.8 / 18.8–19.7 · GPU 10.7 | **Crashes** at 2.6 s |
| **Animal Crossing: New Horizons 3.0.3**, the new game's airport (a fresh save) | 30 · 33.3 / 34.7–35.4 · GPU 5.3 | 30 · 33.3 / 35.7–35.8 · GPU 7.1 | 30 · 33.4 / 36.5–36.7 · GPU 15.8 |
| Animal Crossing, outside the player's house (a save) | 30 · 33.3–33.4 / 35.7–35.8 · GPU 9.4–9.7 | 29.9 · 33.3–33.4 / 38.0–38.1 · GPU 15.5–15.9 | 30 · 33.3–33.4 / 36.5–36.6 · GPU 10.4–10.5 |
| **Super Smash Bros. Ultimate 13.0.5**, boot | **Crashes** at about 2.5 s with the stock shared font | **Crashes** | **Crashes** |
| Smash, the opening movie (with a fuller shared font) | 60 · 12.0 / 33.9 | 59.9 · 13.1–13.4 / 34.7–35.1 | 59.7 · 13.5–13.9 / 35.5–36.0 |
| Smash, a battle (a fuller shared font; stage and CPU fighter vary) | 39.7–59.3 fps | 16.8–29.7 fps, frames up to 215 ms | 13.4–19.3 fps, frames up to 368 ms |

Time from launch to the first frame, warm: about 1.3 s (Odyssey), 3.2–4.3 s (Brilliant Diamond, a Unity game), 1.5 s (Animal Crossing), 2.0–3.0 s (Smash). The
first launch after an install is slower while the driver builds its pipelines: Brilliant Diamond's first frame took 33 s on the Pad 3's first launch.

## Known problems

In the order they block play:

1. **Super Mario Odyssey crashes when a hint video plays.** The host's AVC decoder (`media_android.c` `on_image`) copies a picture's colour planes without
   checking `AImage_getPlaneData`, and reads a null plane (`CRASH sig=11 addr=0` in `libdmhost`), right after `MovieData/PlayGuideMovieRStick.mp4` opens, as
   play starts in the Cascade Kingdom. Games whose movies are VP9 (Smash) take the software decoder and are not affected.
2. **Brilliant Diamond crashes on the Retroid Pocket 5** in the Adreno 650 driver's shader compiler (`libllvm-qgl.so`, `addr=0x48`), while it builds its first
   pipelines. The newer drivers of the other two take the same SPIR-V. Which shader it is is not known yet: nothing logs each pipeline as it is built.
3. **Smash crashes at boot with Android's stock shared font.** On Android the standard shared font is the system's Roboto (`front_android.c`); Smash crashes
   right after loading it (`main+0x7caa0`, `addr=0x38`). With the Mac's Arial Unicode as `DM_SHARED_FONT` it runs, and the iPhone build ships that font
   (`dm/ios/tools/build_ipa.sh`); the Android packer should give each game a fuller `standard.ttf` the same way.
4. **Smash and Super Mario Odyssey crash now and then at boot.** Smash at `main+0x385201c` (`addr=0x50`), even with the font, on all three devices (about one
   launch in six). Odyssey only on the Odin 2, three times in about 20 launches, all in its first seconds of loading: twice in its loader thread as the mode-select
   layout loads (`main+0x95d414` with `addr=0`, once `svcBreak`), once at `main+0x954fb8`; never in 18 launches on the other two.
5. **The pipeline cache is saved only when the app pauses** (`vkb_pipeline_cache_save` on `APP_CMD_PAUSE`). An app stopped by force (the benchmark, or a player
   swiping it away) loses it, so every run builds its pipelines from scratch. The Pad 3's driver builds them about six times slower than the Odin 2's: a Smash
   battle made 682 to 943 pipelines in 11 to 12 s on it (1,147 in 3.1 s on the Odin 2, 368 in 12.5 s on the Retroid Pocket 5), which is where its battle
   frames of 100 to 370 ms come from.
6. **The Retroid Pocket 5 cannot hold 60 fps in Odyssey's opening cutscene** (38 fps, GPU 12.9 ms a frame).

## Reading the numbers

- **Cold pipelines.** Because of problem 5, every run here built its pipelines from scratch. A run whose cache survives should stutter less, most of all on the
  Pad 3.
- **GPU time is at the clock the driver chose.** The Pad 3 shows longer GPU times than the Odin 2 in light scenes although its GPU is faster: it keeps its
  clocks low when the work is light. Compare the GPU column within one device, not across devices.
- **Smash's battles are a range, not a baseline.** The route picks Random stage and a random CPU fighter (D-pad moves on the stage grid did not land on the
  same stage from run to run), so the load differs per run.
- **Animal Crossing's island has a pinned clock.** `DM_FIXED_TIME` fixes the island at 3 PM on the day after the save, so the light and Isabelle's announcement
  repeat.
- **The Odin 2's runs after the first may have started from the last run's save** in the boot routes and Odyssey's cutscene (a script bug since fixed). Those
  routes never reach a save point, so the scene is the same.

## Saves

Brilliant Diamond and Animal Crossing start from downloaded saves, which this repository does not contain (they are other people's files):

- Brilliant Diamond: MegaMarble's 1.3.0 "100% Save File" (GameBanana mod 634809, `pkmnbrilliantdiamond_100.7z`, `SaveData.bin` only), in the NSP folder's
  parent as `saves/eterna`.
- Animal Crossing: Anrei's 3.0.1 + DLC save (GBAtemp download 39784), linked once to the host's user (the unlinked-resident prompt: Existing data, then the
  resident, then Link) and kept as `saves/island_linked`. The host's user ID is fixed, so the linked save works on every device and on the Mac.

Smash's battle and Odyssey's routes start from a fresh save.

## Running them again

```
python3 scripts/bench_android.py <NSP folder> [<NSP folder> ...] -s <serial> [-s <serial> ...] --route <name> --warmup --runs 2
```

The routes are in each game's `dm/games/<id>/bench_android.tsv` ([dm/android/README.md, Benchmarks](README.md#benchmarks)). Smash's routes need
`DM_SHARED_FONT` at a fuller TTF on the device until the packer ships one.
