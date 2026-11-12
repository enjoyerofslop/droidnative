# Blasphemous 2 (`010040801A4C8000`)

Update 1.0.8 (v524288) over the base game, SDK 15.3.2, Unity 2021.3.20f1 IL2CPP with FMOD on NVN. Modules `main`, `subsdk0` (NintendoSDK_movie) and `sdk`. Plays on the Mac: title, Pilgrimage menu, a new game, opening H.264 cinematic with subtitles, awakening, movement into the weapon room, healing, Veredicto pickup, jumping and a weapon swing. Control testing deliberately stops there. The unsigned IPA is about 1.5 GB; iPhone/iPad validation remains open. On Android, the cartridge's 1.0.1 runs at 60 fps into the weapon room ([Android](#android)).

## What it needs

| Setting | Where | Why |
|---|---|---|
| `sys_resource 0x1000000` | [`game.tsv`](game.tsv) | The NPDM declares 16 MB of system resource, enabling virtual address memory |
| 5 GB guest block, 4.375 GB alias region, 1 GB application pool | `game.tsv` | The initial Mac heap check sets no heap and reaches +4.26 GB of the alias region with the hardware pool. A 1 GB pool leaves room beside StandardAllocator for Unity's own address regions |
| SDK-wide node-area and size-class alignment patches | `dm/tools/sdk_patches.py` | Applied to this SDK by the shared function matcher; no game-specific cut or host change |
| `shader_groups /Data/=data` | `game.tsv` | The serialized files and Addressables bundles all live under `Data/` |
| `depth_mode zero` | `game.tsv` | the game selects near-zero NVN depth (the NSP script's heap check on the registered build); offline pipeline bases must use the matching vertex entry |

## Files and shaders

- The merged RomFS has 1,428 files, 1.69 GB, including 1,408 UnityFS bundles under `Data/StreamingAssets`. IL2CPP metadata version 29 contains 114 assembly images and 140,569 methods.
- The DLC NSP is a licence-only package, index 1 (`010040801A4C9001`); its content is already in the update. Packing recognizes the licence. Access to the DLC campaign has not been tested.
- 4,354 shaders: 2,174 vertex, 2,178 pixel, one compute and one geometry. Eleven are Unity's GLSLC outputs in `main`, the others come from serialized Shader objects. All 4,354 compile on the Mac, with zero unresolved bindings or unfillable driver-bank reads.
- 2,177 vertex/pixel pairs; the Mac prebuild makes 2,163 bases, leaves 14 for their draws, and reports zero failures.
- All 4,354 libraries compile for iOS too. `pso_manifest.tsv` records the Mac startup and opening rooms, including Veredicto pickup; it contains shader and pipeline keys only.

## Performance and validation

- Tested on the Mac on 2026-10-28. No runtime `[RED]` message, abort or crash in the checked route. The shader split's omitted ComputeShader kernels are recorded below.
- Gameplay runs at the game's 60 fps target: late 300-frame windows report frame-time p50 16.57 ms, p95 19.34 ms, GPU p50 1.62 ms. These are diagnostic windowless measurements, not a device performance claim.
- Resident memory stays around 2.3–2.4 GB in the opening rooms, with about 1.58 GB allocated by Metal. The alias-region high-water mark is +3.51 GB of 4.375 GB; no sustained growth while standing in the weapon room.
- FMOD uses one AudioOut; the callback log reports no underruns in the settled run. NintendoSDK_movie decodes the H.264 pictures, which are visible in the windowless run.
- The Python tool suite passes (379 tests across 37 files, including Mac packaging; 16 skipped). Host and shader-chain sources are unchanged, so other-game runtime regressions were not run.

## Mac route

Build with `scripts/build_ipa_from_nsp.py <NSP folder> -k <prod.keys> --platform mac`. Use the printed command and a `DM_CTL` file to drive the game: A at the title, A on Pilgrimage, A on the first slot, then A on New Game.

The title route can start with `DM_KEYS="f1400:A,f1500:A,f1600:A"`, then the final New Game confirmation through `DM_CTL` once the slot screen is ready. Let the opening play, or hold B to skip when it permits. In play: left stick / D-pad to move, B to jump, Y to attack, X to heal, Up to interact. Move right from the awakening room to the three statues and interact beside the left statue for Veredicto. The default 2D touch-pad layout is sufficient.

Keep the game focused during its opening cinematic. Unity pauses the sequence after a Mac focus-loss notification, while menus and frame submissions can still run. A windowless diagnostic run (omit `DM_WINDOW`, `DM_PRESENT_LINK=0`) plays the cinematic and supports `DM_CTL` screenshots without focus changes. `DM_PRESENT_LINK=0` also allows screenshots when macOS stops the display link of an unfocused window; it is a diagnostic option, not a profile setting.

## Android

First run on Android, 2026-11-11, on a Galaxy S25 Edge (SM8750, Adreno 830 with Qualcomm's driver 0x80320001, Android 16), in handheld mode, driven over adb with `DM_CTL`. The cartridge's 1.0.1 (v65536), packed as a game app (`build_android_from_nsp.py --game-apk`) from DroidPlay Core `main` at `1c06a5c4`: one 1.5 GB APK with the RomFS inside.

- **The build:** a profile derived from 1.0.8's (the same Unity 2021.3.20f1). The split found 2,655 shaders (1.0.8 has 4,354), all translated to SPIR-V, none failed.
- **What was played:** the title, Pilgrimage → New Game, the opening quote and the H.264 cinematic with its subtitles (MediaCodec), the awakening with the Bile Flask tutorial (L), walking right into the room of the three statues, the sword taken from the middle one (X), and a few swings and jumps beyond it.
- **Frame rate:** 60 fps (the profile's target): every 30 s window 58.8–60.0 over 9 minutes, frame p50 16.7 ms, p95 about 19 ms, GPU 4.5–6.5 ms.
- **Sound:** FMOD through a stereo `AudioOut`, no underrun. The `DM_AUDIO_DUMP` has the cinematic and the music (RMS about 360–2,700). Not listened to by a person.
- **Picture:** nothing wrong seen in the cinematic, the cave, the statues' room or the HUD. One `[RED]` line: `advanced blend mode 25: drawn with plain blending`, nothing visibly wrong where it was seen; not compared with the Mac.
- **Memory:** 1.99 GB PSS (0.73 GB graphics). Not killed.
- **Save:** the game saves only at a Prie Dieu, which wasn't reached. After a cold start the pilgrimage's slot 1 is still New Game, so saving and Continue are untested.
- **Not Playable yet:** it's a real-time platformer, so the stretch (through the Faceless One, with a Prie Dieu save loaded after a cold start) needs a person with a controller.
- **On an Ayn Odin 2 (SM8550, Adreno 740 with Qualcomm's driver 0x802a4000), with its built-in controller:** the same route from a new game into the statues' room and the sword, 60 fps in every 30 s window but one (58.6), GPU about 1 ms, no underrun, 1.32 GB PSS, the same single blend-mode red line. The game app stays installed there (no `env.txt`) for a person to play.
- **Not tried:** the other devices.

## Found on this game

- **Offline depth metadata:** [Offline pipeline archive and profile depth disagree](../../../docs/reference/shaders.md#offline-pipeline-archive-and-profile-depth-disagree). The key was missing until the check boots began reading it; the archive at this mode has not been rebuilt or measured here.
Existing mechanisms used by this profile:

- [The SDK's address-region node area](../../../docs/reference/memory.md#the-sdks-address-region-node-area).
- [Size-class alignment doubles Unity's regions](../../../docs/reference/memory.md#size-class-alignment-doubles-unitys-regions).
- [Unity's video planes and checking the movie path](../../../docs/reference/movies.md#unitys-video-planes-and-checking-the-movie-path).

## Open

- iPhone/iPad validation, save reload, combat encounters, later areas and the DLC campaign. Only the opening control check above was run; the base version was surveyed but not played or registered.
- The shader split reports ComputeShader objects in `Data/Resources/unity default resources` whose stripped type hash `abd9135b8ce83d043fef4e9ec7f53366` has no available tree. Their kernels are omitted; no missing-shader runtime diagnostic has appeared in the startup route.
