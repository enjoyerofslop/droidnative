# The Elder Scrolls V: Skyrim (`01000A10041EA000`)

Update 1.1.404 (v393216, the Anniversary Edition build) over the base game, SDK **14.3.0** (`nnSdk-14_3_0`, `NintendoSDK_NVN-14_3_0`). Bethesda's **Creation Engine** with Havok, drawing with **NVN**. Modules `main` and `sdk`. Every game file is in 89 BSA archives (version 105) and the plugin files (`.esm`, `.esl`) under `Data/`, 12.4 GB. Started from the provisional profile the NSP script wrote from its survey (`dm/games/profile_guess.py`); answers droidplay-core#414 (music, no picture).

- **On the Mac:** draws from boot at the game's 30 fps: the title, the main menu, a new game's opening cart ride, the arrival in Helgen and character creation.
- **On Android:** not run yet.

## What it needs

| Setting | Where | Why |
|---|---|---|
| `modules main sdk` | [`game.tsv`](game.tsv) | `main` imports from these two only |
| `mem_reserve 0x1028000000`, `mem_alias 0x1000000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000`, `sys_resource 0x800000` | [`game.tsv`](game.tsv) | see [Memory](#memory) |
| `render_cond on` | [`game.tsv`](game.tsv) | the render thread waits for a timestamp report's counter field to read 0; see [Boot](#boot) |
| `depth_mode zero` | [`game.tsv`](game.tsv) | the game calls `nvnDeviceSetDepthMode` with near = 0 in its first seconds |
| `shader_groups /Data/=data /BatchFiles/=batchfiles` | [`game.tsv`](game.tsv) | the shaders are in `Data/Skyrim - Shaders.bsa` and in `main`; see [Shaders](#shaders) |
| `zip_store .bik:.bsa:.esm:.metallib` | [`game.tsv`](game.tsv) | the archives are stored uncompressed already |

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

## Mac test controls

`DM_CTL` presses of A held 0.5 s pass the title ("Press any button"), pick New and answer Yes. Character creation opens about six minutes later; Y finishes it and A confirms, then the game asks for a name: run with `DM_KBD=Prisoner`, or with no window the keyboard returns cancel.

## Found on this game

- [FXP shader records in Bethesda BSA archives and in main](../../../docs/reference/shaders.md#fxp-shader-records-in-bethesda-bsa-archives-and-in-main).
- [A linear texture whose stride is shorter than its rows](../../../docs/reference/nvn-objects.md#a-linear-texture-whose-stride-is-shorter-than-its-rows).

## Open

- **`[RED] stage 1 cb11 has no uniform buffer bound`**, once, when the opening loads (PR #444's 1.0.12 note has it too). Nothing missing was seen.
- **The main menu's "Start a new game?" box** draws as two vertical lines the height of the screen beside its text; not compared with the Switch.
- **Not checked from PR #444's 1.0.12 findings:** the lost wake of a plain-store mutex unlock before `SignalLightEvent` (stalls in loading on 1.0.12, 517 inlined unlocks cut there by build), and Helgen Keep's interior lighting (stencil written as a raw buffer by a compute pass). Neither was met in the opening; this build has no cuts for either.
- **The iPhone:** the regions need more than its alias region holds (see [Memory](#memory)).
