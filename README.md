# droidnative

**Nintendo Switch and Switch 2 games running natively on Android: not an emulator.** The game's own ARM64 code runs directly on the device's CPU, and its NVN
graphics are replayed on the GPU through Vulkan. Pokémon Brilliant Diamond plays at 60 fps on an Ayn Odin 2, Animal Crossing: New Horizons at 30.

- **Native, not emulated.** A Switch and an Android device both run ARM64 code: the game's code is rewritten only where the host needs it (system calls,
  thread registers), and a host answers the Switch's system calls and SDK services. There is no CPU emulation.
- **A game is an app of its own**, with its name, icon and saves, installable on any arm64 device with Vulkan, or every game in one launcher app.
- **Packed on your computer** from your own dump: NSP / XCI files, or a Switch 2 game's `.nup` or dump folder. [DroidPlay](https://github.com/enjoyerofslop/droidplay),
  a Mac app, does it with a click; the command line works on any computer.

droidnative is [seedds/nxnative](https://github.com/seedds/nxnative) (Switch games natively on the iPhone, the iPad and the Mac) with an Android port. The port began
as [RogelioLB/nxnative-android](https://github.com/RogelioLB/nxnative-android) (the Vulkan replay of NVN, the Android front end, the packing script); droidnative
carries it on and follows nxnative's `main`, merged in regularly, so its games, fixes and Switch 2 work reach Android too. nxnative itself stays Apple-only by its
maintainer's choice: Android work belongs here, not there. Everything below the line further down is nxnative's own README (the iPhone and Mac side).

> [!IMPORTANT]
> **Bring your own game.** Nothing from any game is in this repository, and no packed game is distributed: you dump the game and the keys from **your own**
> Switch, and the app you build is for you only. Do not share APKs packed with a game (they carry its code and files), keys or firmware, and do not ask for them
> in issues. The project is not affiliated with Nintendo or any game publisher.

## Ways to play

- **DroidPlay on a Mac:** add your games folder, then **Install on Android** (one launcher app holding every game, over adb) or **Build Game App** (an APK, or an
  XAPK for an installer app). See [DroidPlay](https://github.com/enjoyerofslop/droidplay).
- **The command line, any computer:** [Packing from the command line](#packing-from-the-command-line). `--game-apk` makes a game app; without it the game goes into
  the launcher app on a connected device.
- **The desktop app** (`python scripts/nxnative_android.py`, Windows, macOS or Linux): the launcher-app flow with a window ([below](#the-desktop-app)).

## Status

| Game | Device | State |
|---|---|---|
| Pokémon Brilliant Diamond 1.3.0 | Ayn Odin 2, OnePlus Pad 3 | Playable: 60 fps in Eterna City's overworld. **Crashes at launch on a Retroid Pocket 5** (Adreno 650: its driver's shader compiler) |
| Animal Crossing: New Horizons 3.0.3 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5 | Runs at 30 fps (as on the Switch) in the new game's airport on all three, and outside the player's house on the Odin 2 and Pad 3; not played through |
| Super Mario Odyssey 1.4.1 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5 | The Start menu at 60 fps, the opening cutscene at 60 (38 on the Retroid Pocket 5). **Crashes when play starts**, at the first hint video (the host's AVC decoder) |
| Super Smash Bros. Ultimate 13.0.5 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5 | **Crashes at boot with Android's stock shared font**; with a fuller one, battles at 40–59 fps on the Odin 2, 13–30 fps on the other two (pipelines built during play) |
| The Legend of Zelda: Breath of the Wild 1.9.0 | Ayn Odin 2 | Runs with a correct picture at about 20 fps (CPU-bound in the Vulkan replay) † |
| Super Mario Bros. Wonder 1.2.1 | POCO X5 5G (Adreno 619) | Playable: about 30 fps at render scale 0.8 † |
| Super Mario 3D World + Bowser's Fury 1.2.2 | POCO X5 5G | Bowser's Fury runs with correct colours; one launch stopped at a black loading screen † |
| Danganronpa V3 Anniversary Edition 1.0.2, The Binding of Isaac: Afterbirth+ 1.7.9b | POCO X5 5G | Run from provisional profiles; not played through † |
| **Mario Kart World 1.8.0 (Switch 2)** | Ayn Odin 2 | **Boots and draws:** the world map at about 55 fps, the attract drive at about 3.4 fps. Open: sparse textures (the terrain is untextured), virtual memory pools, constant-buffer copies in the replay, no mesh shaders on the device |

† Tested before droidnative merged nxnative's `main` (2026-11-08); not run since.

The first four rows are from the [Android baselines](dm/android/baselines.md) of 2026-11-08: the same scripted runs on each device, with frame times, the devices'
drivers, and the known problems in the order they block play.

Every other game in the [games table](dm/games/README.md#games) has a profile and can be packed the same way, but has not been run on Android. A game without a
profile can still be packed as an *experimental build*: most likely it does not boot, but it is the starting point for porting it.

## Testing and reporting

Testers and contributors are welcome. Useful reports name the device and its GPU (Settings, or `adb shell getprop ro.product.model`), Android version, the game,
its title ID and version, how it was packed (DroidPlay, the command line, game app or launcher), and attach the log: `adb logcat -s nxnative`, or `log.txt` in the
app's folder (`Android/data/<package>/files/`). A screenshot and the first `[RED]` lines help most. Never attach game files or keys. How changes get in, and how
droidnative stays in step with nxnative: [CONTRIBUTING.md](CONTRIBUTING.md#droidnative).

## How it fits together

```
 Your computer (Windows, macOS or Linux)                         Your Android phone
 ───────────────────────────────────────                         ─────────────────────────────────────
 NSP / XCI files + prod.keys                                     nxnative app (org.nxnative.android)
          │                                                        ├─ Launcher: the games on the phone,
          ▼                                                        │    each game's settings, Play
 Desktop app: scripts/nxnative_android.py                          │
 (or the command line: scripts/build_android_from_nsp.py)          └─ Game screen, in its own process:
          │  1. extract the game (nx_extract)                           loads that game's host
          │  2. rewrite its code for Android (patch_nso.py)             (libdmhost_<title ID>.so), which runs
          │  3. split its shaders, translate them to SPIR-V             the game's code and replays its
          │  4. build the game's host with the Android NDK              graphics on Vulkan
          │  5. pack one APK carrying every game built so far
          └─ adb: install the APK, copy the game files ──────▶   Android/data/org.nxnative.android/files/games/<title ID>/
```

One app holds every game: each game you build adds its host to a library on your computer, and every APK is packed from the whole library, so building a second
game keeps the first one in the app. Game files (code, shaders, RomFS, icon) live in the app's folder on the phone; saves stay in the app's internal storage.

## What you need

- **Your game and keys**, dumped from your own Switch: the game as NSP / XCI files (the base game and, if you have it, its update; for example with nxdumptool) in one
  folder, and your `prod.keys` (Lockpick_RCM).
- **On the computer:** Python 3.12 or newer with `lz4`, `capstone`, `fonttools` and `backports.zstd` (not needed on Python 3.14), plus `PySide6` for the desktop app:
  `pip install lz4 capstone fonttools backports.zstd PySide6`. The .NET SDK 10, the Android SDK with an NDK, CMake 3.22 and build-tools (set `ANDROID_HOME` or pass
  `--sdk`), `adb`, and a JDK (for `keytool` and `javac`). The desktop app's **Settings** page checks all of this and says how to get what is missing.
- **On the phone:** USB debugging (or wireless debugging) turned on, so that `adb devices` lists the phone, and room for the game: its RomFS is copied as one image
  (Danganronpa V3's is 6.7 GB).

## The desktop app

`python scripts/nxnative_android.py` opens a window that drives the packing script and adb for you:

- **Library:** the games you added (**+ Build game** picks a folder with a game's NSP files), each with its box art, version and status on the phone picked at the top.
  The big button does what comes next: **Build and install**, **Install on phone** (a game built before, without building again) or **Play**. **Manage** has the rest:
  build only, update the app on the phone, remove the game. A game with no profile gets **Experimental build**: the script surveys the game, writes a guessed
  provisional profile into the game's folder and packs it; once built it is marked *Experimental* and can be installed like any other.
- **Builds:** the running build's stages, progress and messages (the bar at the bottom of every page follows it); a build started from a console shows here too.
- **Phones:** adb devices over USB and Wi-Fi (pair, connect, discover), the app version and the games on each phone, saves backed up to the computer.
- **Performance:** the game's log from `adb logcat`, with the frame time, GPU and CPU figures the host prints, and a frame's GPU time per pass.
- **Settings:** your `prod.keys`, and the requirements above with how to install what is missing.

A rebuild only does what changed: the extraction, the rewritten code and the translated shaders are reused when their inputs are the same, and the RomFS image is not
copied to the phone again when the phone already holds the same one.

## The Android app

- **Launcher.** Opening **nxnative** shows the games on the phone with their icon, name and version (a game whose host the installed app lacks is marked as needing an
  app update). Picking a game opens its **settings screen**, grouped into Game and Controls: console mode (handheld is lighter), game language, game timing, render
  scale where the game supports it, the frame-rate counter, rumble and its strength. **Play** starts the game. Lines like `DM_RENDER_SCALE=0.8` in
  `Android/data/org.nxnative.android/files/env.txt` win over the screen (they show greyed out).
- **In the game.** Touch controls are drawn over the picture in three layouts (2D, 3D and Tap, switched with the round button at the top); touches no control takes go
  to the game's touch screen. A physical controller works as player 1 and hides the touch controls; rumble goes to the controller or the phone, and shaking the phone
  shakes the controller. The **≡** button at the top (left of −) goes back to the launcher while the game keeps running behind it: **Play** on the same game resumes
  it, and picking another game asks before closing the running one.
- **Saves** stay in the app's internal storage (`saves/<title ID>`), so updating the app keeps them; the desktop app backs them up to the computer. The log is
  `Android/data/org.nxnative.android/files/log.txt` (also `adb logcat -s nxnative`).

## Packing from the command line

```
python scripts/build_android_from_nsp.py "<folder with your NSP / XCI files>" -k "<your prod.keys>"    build, install, copy the game
                         (a Switch 2 game: the folder with its .nup or dump, or the .nup itself; no keys needed)
    --game-apk [--xapk]  the game as an app of its own (<name>.apk, plus <name>.romfs for a game over 2 GB, or one .xapk); no device needed
    -p v0                pack the base game instead of the newest version in the folder (a version the profile does not register is packed from a derived profile)
    -l es-419            the default game language (a code or a name)
    --serial <device>    the adb device, when more than one is connected
    --no-push            build the APK only (a game without a profile is first built this way)
    --push-only          install the app and copy a game built before, without building
python scripts/build_android_from_nsp.py --apk-only    pack the app with every game built on this computer and install it
python scripts/build_android_from_nsp.py --check       what the build needs on this computer, as JSON
```

The first build of a game takes a while (the shader translation and, on a hard disk, the RomFS image); later builds reuse what did not change.

## Seeing what a game draws

When a game shows a black or wrong picture, these files in `Android/data/org.nxnative.android/files/` ask the running game for diagnostics (each is checked every
30 frames and removed when taken; `adb shell touch <path>` creates one):

- `shot_now`: the next presented frame as a PNG in `dump/` (`DM_NVN_SHOT=<frame>[,<frame>...]:<path>` in `env.txt` does the same for given frames).
- `dump_now`: every render target of one frame, after each pass, as `.raw` and `.png` in `dump/` (a 3D texture's slices stacked, up to 1,024 images), with each draw's shaders, bound textures, constant buffers (their first values) and blend state in the log.
- `threads_now`: every game thread's state, what it waits on and its backtrace, in the log (for a game that stops moving on).

## Games that compile their shaders while they run

Some games carry their shaders as GLSL source and compile them with Nintendo's GLSL compiler while they run (The Binding of Isaac does). Their files hold no shader to
translate, so the first build has none (`[RED] the game is packed without shaders`): the game runs but draws nothing. The app captures them on the phone by itself:

1. Play the game for a while: each shader is saved the first time the game compiles it (in the game's folder on the phone, `glslc_capture/`).
2. On the computer, the game's card in the desktop app says how many new shaders the phone has; **Manage → Update shaders from the phone** copies them, translates
   the new ones and puts them on the phone (no app build: about a minute). From the command line: `build_android_from_nsp.py "<NSP folder>" -k <prod.keys> --update-shaders`.
   Every build and **Install on phone** also picks up the new ones first.
3. Open the game again.

A scene reached later (or a DLC) can compile more shaders: repeat until the log shows no `no translated shader`. This is done for games packed from a provisional
profile; a registered profile's shader tables name the captures they were made from. DLC in the NSP folder is extracted and copied to the phone with the game.

## What the Android port changed

The iOS / Mac host runs on Android with stand-ins for the Darwin interfaces it calls (`dm/android/compat`); the guest's thread slots go through the x18 register (the
rewriter emits `mov xN, x18` for `DM_TARGET=android`). NVN is replayed on Vulkan (`dm/android/gfx_vk.c`, `gfx_vk_draw.inc`): textures (BC decoded on the CPU where the
GPU lacks it), copies, clears, draws, compute, indirect draws, transform feedback, queries and timestamps, submitted in chunks so the GPU works while the CPU records;
shaders are translated with the project's translator and adjusted for Android drivers (`dm/android/tools/spv_android.py`). Audio goes through AAudio, movies through
MediaCodec. Details of the port: [dm/android/README.md](dm/android/README.md).

Problems found on the way, each with its cause and fix in the reference ([rendering](docs/reference/rendering.md#android-vulkan-replay), [memory](docs/reference/memory.md),
[NVN objects](docs/reference/nvn-objects.md)):

- **Wrong pictures:** the Adreno driver misreading dynamic vector components in uniform buffers (vertical stripes); render targets attached in their sRGB view format
  (washed-out colours); `char` unsigned on Android (noise in clouds); separate textures read as "no texture" because the texture and sampler banks are packed into one
  field (Danganronpa V3's black screen); a second NVN device resetting the window origin (an upside-down picture); a 3D colour-grading LUT drawn a slice at a time into
  one slice (Bowser's Fury's blue scene).
- **Crashes:** the thread stack reported with bionic's guard page, which Unity's garbage collector scanned (Danganronpa V3 at boot); `pthread_exit` run on a game
  thread's small stack (Bowser's Fury after a few seconds).
- **Speed:** syncs limited to what a draw reads, passes kept open, early and mid-pass submissions, constant buffers copied only as far as the shader reads, pipeline keys
  built from the state fields, a capped pipeline prebuild; *Game time* holds the audio to the game's frames for levels timed to the music.

---

# nxnative

Play your own Nintendo Switch games natively on iPhone and iPad. Bring your game (its NSP files) and your `prod.keys`; one script turns them into an IPA that you sideload.

It is not an emulator: the game's own code runs directly on the Apple chip, with Switch graphics rebuilt on Metal. Nothing from any game is in this repository, and the project is not affiliated with Nintendo or any game publisher.

Switch 2 games have started too: [Donkey Kong Bananza](dm/games/040074A01BF12000/README.md), [Splatoon Raiders](dm/games/0400380020056000/README.md), [Fire Emblem Fortune's Weave](dm/games/04007EF01F8AE000/README.md), [Pokémon Pokopia](dm/games/0400A3A01EE4C000/README.md), [Hyrule Warriors: Age of Imprisonment](dm/games/04003F40232DE000/README.md), [Mario Kart World](dm/games/0400C3F00006E000/README.md) and [Mario Tennis Fever](dm/games/0400D4201C6EA000/README.md) play on the Mac, packed from one [`.nup` file](#switch-2-games) or a dump of the game; iPhone and iPad are untested.

## Discussions

Questions, how a game runs on your Mac or iPhone, and ideas go in [Discussions](https://github.com/seedds/nxnative/discussions); [Issues](https://github.com/seedds/nxnative/issues) are for bugs, with the log. Ocarina of Time's performance (frame rate, resolution, which Macs hold 60 fps) is followed in [Ocarina of Time: state on main](https://github.com/seedds/nxnative/discussions/1789).

## How to play

Switch 2 games are built from one `.nup` file or a folder of their files, not from NSPs, and are tested on the Mac only: see [Switch 2 games](#switch-2-games).

### With a Mac app

Community projects build on nxnative with Mac apps that turn your games into apps for your iPhone, iPad or Mac, with no command line, and keep them in a library. They are separate projects: questions and bugs about them go to their own pages.

- [NX2Apple](https://github.com/LNPANDY/NX2Apple)
- [NX Play](https://github.com/varyform/nx-native-wrapper)
- [NxNative Launcher](https://github.com/rennan101/nxnative_Launcher)
- [LumaNX](https://github.com/Xc1Ym/LumaNX)

### Build from the command line

You need a Mac with macOS 26.6 or later, [Xcode](https://developer.apple.com/download/all/?q=Xcode%2027.2) 27.2, [Homebrew](https://brew.sh) and Python 3.12 or newer (an arm64 one, not an Intel Homebrew's). An iPhone build also needs Xcode's iOS platform (Xcode → Settings → Components).

The shaders are built with Xcode 27.2's Metal compiler. Select it before step 1: `sudo xcode-select -s /Applications/Xcode.app`. With several Xcode versions installed, name this one `Xcode-27.2.app` and select it with `sudo xcode-select -s /Applications/Xcode-27.2.app`.

**1. Install the tools** (only once), in Terminal:

```
xcodebuild -downloadComponent MetalToolchain
git clone https://github.com/seedds/nxnative.git && cd nxnative
brew install xcodegen zstd glslang
brew install --cask dotnet-sdk
python3 -m pip install lz4 "capstone>=5,<6" fonttools nsz zbic "backports.zstd; python_version < '3.14'"
```

**2. Put your game in a folder**: the game, plus its update and DLC if you have them (`.nsp`, `.xci`, `.nsz` or `.xcz`):

```
~/Games/MarioWonder/
  Super Mario Bros. Wonder [010015100B514000][v0].nsp
  Super Mario Bros. Wonder [010015100B514800][v327680].nsp
```

**3. Build**, with your game folder and your `prod.keys`:

```
python3 scripts/build_ipa_from_nsp.py ~/Games/MarioWonder -k ~/keys/prod.keys
```

The IPA appears in the game's folder. The first build takes 30–60 minutes and needs free disk space of about twice the game's size plus 10 GB; building again is much faster.

To play on the Mac instead, add `--platform mac-app`: you get a Mac app of the game to open from Finder. All options: [The packing script in detail](docs/development.md#the-packing-script-in-detail).

**Android.** To play on an Android phone instead, see [the top of this page](#droidnative): a desktop app packs the game and installs it on the phone.

### Install

Install the IPA on your iPhone or iPad with a sideloading tool such as AltStore, Sideloadly or LiveContainer. If your tool offers **Increased Memory Limit**, turn it on: the bigger games need it.

Game too big to install? Build again with `--romfs separate`, and run the command the script prints once to copy the game files to your phone ([Quick reinstalls](docs/development.md#quick-reinstalls)). With AltServer, also add `--shader-files`: it cannot install a file of 2 GiB or more.

Controls, saves and settings: [Playing](docs/playing.md).

### Switch 2 games

A Switch 2 game is built from one [NUP](https://github.com/a55uka/nup) container (a `.nup` file) or a folder of its files, not from NSPs. Neither needs `prod.keys`. A game this project has no profile for is surveyed and gets a provisional profile, as NSPs do ([Port another game](docs/development.md#port-another-game)), which may not boot. You get a Mac app; iPhone and iPad are untested.

**From a `.nup` file**, which holds the base game, its updates and DLC in one file. Give the file, or a folder that holds it:

```
python3 scripts/build_ipa_from_nsp.py ~/Games/DonkeyKongBananza.nup --platform mac-app
```

[Hyrule Warriors: Age of Imprisonment](dm/games/04003F40232DE000/README.md) is played this way: its 47 GB NUP unpacks in under five minutes. A NUP that carries the game's control data (its NACP) and icon gives the app the game's name and icon; otherwise the name comes from the game's profile and the app has no icon.

A NUP without the base game also works, when its base package is empty or it has none and its updates are marked `standalone_update`: the update is taken as the whole game, and the script says so. If the game then stops on missing files, that update holds only what changed: pack a NUP with the base game. The newest update is selected by default; `--package v<N>` selects another version in the container. Such a container has no `v0` (base game) to select.

**From a folder of files**. The script expects this layout (`updates` and `dlc` are optional):

```
~/Games/DonkeyKongBananza/
  base/exefs/                     main, main.npdm, sdk, rtld
  base/romfs/
  updates/458752/exefs/           the update's version, as a decimal number
  updates/458752/romfs/           the patched RomFS, not a patch
  dlc/040074a01bf13001/0/romfs/   the DLC's title ID
```

```
python3 scripts/build_ipa_from_nsp.py ~/Games/DonkeyKongBananza --platform mac-app
```

An update's folder alone will do (no `base/`), and so will `exefs/` and `romfs/` directly in the folder, as `nup extract` writes them, which count as `base/`. The app has no icon, because the folder holds none. To turn such a folder into a NUP: `nup pack ~/Games/DonkeyKongBananza game.nup`.

## Games

Games tested on Mac or iPhone. See the [per-game notes](dm/games/README.md#games) for tested platforms, progress and known issues:

Needs iOS / iPadOS 26 or later on an iPhone 15 Pro or newer (A17 Pro chip or later) or an iPad with an M1 chip or later: the games' textures are BC-compressed, and older iPhones can't read that format. Other games aren't supported yet. For them the script writes a survey and still tries its best to pack an IPA, guessing the game's settings; such an IPA may not start.

Under a game, "60 fps with 1.2.0" means it runs at 60 fps (30 on the console) with that update. "Up to 120 fps" names no update because the host finds the frame rate in the game's code, whichever version it is; choose it under Frame rate, on a screen that shows 120 Hz.

<!-- gallery: written by dm/tools/docs_gallery.py from docs/images/gallery.tsv; change the table, then run it -->
<table>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/donkey-kong-bananza.jpg" width="256" alt="Donkey Kong Bananza"><br><small><b><a href="dm/games/040074A01BF12000/README.md">Donkey Kong Bananza</a></b><br>Switch 2, Mac only, from a dump</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/splatoon-raiders.jpg" width="256" alt="Splatoon Raiders"><br><small><b><a href="dm/games/0400380020056000/README.md">Splatoon Raiders</a></b><br>Switch 2, Mac only, from a dump</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/fire-emblem-fortunes-weave.jpg" width="256" alt="Fire Emblem Fortune's Weave"><br><small><b><a href="dm/games/04007EF01F8AE000/README.md">Fire Emblem Fortune's Weave</a></b><br>Switch 2, Mac only, from a dump, up to 120 fps</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-pokopia.jpg" width="256" alt="Pokémon Pokopia"><br><small><b><a href="dm/games/0400A3A01EE4C000/README.md">Pokémon Pokopia</a></b><br>Switch 2, Mac only, from a dump</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/hyrule-warriors-age-of-imprisonment.jpg" width="256" alt="Hyrule Warriors: Age of Imprisonment"><br><small><b><a href="dm/games/04003F40232DE000/README.md">Hyrule Warriors: Age of Imprisonment</a></b><br>Switch 2, Mac only, from a NUP</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-kart-world.jpg" width="256" alt="Mario Kart World"><br><small><b><a href="dm/games/0400C3F00006E000/README.md">Mario Kart World</a></b><br>Switch 2, Mac only, from a dump</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-tennis-fever.jpg" width="256" alt="Mario Tennis Fever"><br><small><b><a href="dm/games/0400D4201C6EA000/README.md">Mario Tennis Fever</a></b><br>Switch 2, Mac only, from a dump</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/yoshi-and-the-mysterious-book.jpg" width="256" alt="Yoshi and the Mysterious Book"><br><small><b><a href="dm/games/0400245021D2C000/README.md">Yoshi and the Mysterious Book</a></b><br>Switch 2, Mac only</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-ocarina-of-time.jpg" width="256" alt="The Legend of Zelda: Ocarina of Time"><br><small><b><a href="dm/games/0400486024DEC000/README.md">The Legend of Zelda: Ocarina of Time</a></b><br>Switch 2, Mac only, from a NUP</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-kart-8-deluxe.jpg" width="256" alt="Mario Kart 8 Deluxe"><br><small><b><a href="dm/games/0100152000022000/README.md">Mario Kart 8 Deluxe</a></b><br>no Mii heads</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-vs-donkey-kong.jpg" width="256" alt="Mario vs. Donkey Kong"><br><small><b><a href="dm/games/0100B99019412000/README.md">Mario vs. Donkey Kong</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/paper-mario-the-thousand-year-door.jpg" width="256" alt="Paper Mario: The Thousand-Year Door"><br><small><b><a href="dm/games/0100ECD018EBE000/README.md">Paper Mario: The Thousand-Year Door</a></b><br>60 fps with 1.0.1</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-3d-world.jpg" width="256" alt="Super Mario 3D World + Bowser's Fury"><br><small><b><a href="dm/games/010028600EBDA000/README.md">Super Mario 3D World + Bowser's Fury</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-bros-wonder.jpg" width="256" alt="Super Mario Bros. Wonder"><br><small><b><a href="dm/games/010015100B514000/README.md">Super Mario Bros. Wonder</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-3d-all-stars.jpg" width="256" alt="Super Mario 3D All-Stars"><br><small><b><a href="dm/games/010049900F546000/README.md">Super Mario 3D All-Stars</a></b><br>Super Mario 64 and Sunshine; Galaxy is 32-bit ARM, which Apple silicon cannot run</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-galaxy.jpg" width="256" alt="Super Mario Galaxy"><br><small><b><a href="dm/games/010099C022B96000/README.md">Super Mario Galaxy</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-galaxy-2.jpg" width="256" alt="Super Mario Galaxy 2"><br><small><b><a href="dm/games/0100FD8022DAA000/README.md">Super Mario Galaxy 2</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-odyssey.jpg" width="256" alt="Super Mario Odyssey"><br><small><b><a href="dm/games/0100000000010000/README.md">Super Mario Odyssey</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-breath-of-the-wild.jpg" width="256" alt="The Legend of Zelda: Breath of the Wild"><br><small><b><a href="dm/games/01007EF00011E000/README.md">The Legend of Zelda: Breath of the Wild</a></b><br>60 fps with 1.9.0</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-links-awakening.jpg" width="256" alt="The Legend of Zelda: Link's Awakening"><br><small><b><a href="dm/games/01006BB00C6F0000/README.md">The Legend of Zelda: Link's Awakening</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-tears-of-the-kingdom.jpg" width="256" alt="The Legend of Zelda: Tears of the Kingdom"><br><small><b><a href="dm/games/0100F2C0115B6000/README.md">The Legend of Zelda: Tears of the Kingdom</a></b><br>60 fps with 1.4.3</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/13-sentinels.jpg" width="256" alt="13 Sentinels: Aegis Rim"><br><small><b><a href="dm/games/01003FC01670C000/README.md">13 Sentinels: Aegis Rim</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/absolum.jpg" width="256" alt="Absolum"><br><small><b><a href="dm/games/0100A83022A22000/README.md">Absolum</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ace-attorney-investigations.jpg" width="256" alt="Ace Attorney Investigations Collection"><br><small><b><a href="dm/games/010005501E68C000/README.md">Ace Attorney Investigations Collection</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/advance-wars-1-2-re-boot-camp.jpg" width="256" alt="Advance Wars 1+2: Re-Boot Camp"><br><small><b><a href="dm/games/0100300012F2A000/README.md">Advance Wars 1+2: Re-Boot Camp</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ai-the-somnium-files.jpg" width="256" alt="AI: THE SOMNIUM FILES"><br><small><b><a href="dm/games/010089B00D09C000/README.md">AI: THE SOMNIUM FILES</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ai-the-somnium-files-nirvana-initiative.jpg" width="256" alt="AI: THE SOMNIUM FILES - nirvanA Initiative"><br><small><b><a href="dm/games/0100713016CCC000/README.md">AI: THE SOMNIUM FILES - nirvanA Initiative</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/animal-crossing-new-horizons.jpg" width="256" alt="Animal Crossing: New Horizons"><br><small><b><a href="dm/games/01006F8002326000/README.md">Animal Crossing: New Horizons</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/animal-well.png" width="256" alt="ANIMAL WELL"><br><small><b><a href="dm/games/010020D01AD24000/README.md">ANIMAL WELL</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/astral-chain.png" width="256" alt="ASTRAL CHAIN"><br><small><b><a href="dm/games/01007300020FA000/README.md">ASTRAL CHAIN</a></b><br>60 fps target with 1.0.1</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/balatro.jpg" width="256" alt="Balatro"><br><small><b><a href="dm/games/0100CD801CE5E000/README.md">Balatro</a></b><br>played by touch</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ball-x-pit.jpg" width="256" alt="BALL x PIT"><br><small><b><a href="dm/games/010086A022444000/README.md">BALL x PIT</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/bayonetta.jpg" width="256" alt="Bayonetta"><br><small><b><a href="dm/games/010076F0049A2000/README.md">Bayonetta</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/bayonetta-2.jpg" width="256" alt="Bayonetta 2"><br><small><b><a href="dm/games/01007960049A0000/README.md">Bayonetta 2</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/bayonetta-3.jpg" width="256" alt="Bayonetta 3"><br><small><b><a href="dm/games/01004A4010FEA000/README.md">Bayonetta 3</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/big-brain-academy-brain-vs-brain.jpg" width="256" alt="Big Brain Academy: Brain vs. Brain"><br><small><b><a href="dm/games/0100620012D6E000/README.md">Big Brain Academy: Brain vs. Brain</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/brain-memory-training-academy.jpg" width="256" alt="Brain Memory Training Academy"><br><small><b><a href="dm/games/0100F5D01DA3A000/README.md">Brain Memory Training Academy</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/captain-toad-treasure-tracker.jpg" width="256" alt="Captain Toad: Treasure Tracker"><br><small><b><a href="dm/games/01009BF0072D4000/README.md">Captain Toad: Treasure Tracker</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/catherine-full-body.jpg" width="256" alt="Catherine: Full Body"><br><small><b><a href="dm/games/0100BF00112C0000/README.md">Catherine: Full Body</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/celeste.jpg" width="256" alt="Celeste"><br><small><b><a href="dm/games/01002B30028F6000/README.md">Celeste</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/cuphead.jpg" width="256" alt="Cuphead"><br><small><b><a href="dm/games/0100A5C00D162000/README.md">Cuphead</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dark-souls-remastered-creation.jpg" width="256" alt="DARK SOULS: REMASTERED"><br><small><b><a href="dm/games/01004AB00A260000/README.md">DARK SOULS: REMASTERED</a></b><br>60 fps with 1.0.3</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/digimon-story-cyber-sleuth.jpg" width="256" alt="Digimon Story Cyber Sleuth: Complete Edition"><br><small><b><a href="dm/games/010014E00DB56000/README.md">Digimon Story Cyber Sleuth: Complete Edition</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/donkey-kong-country-tropical-freeze.jpg" width="256" alt="Donkey Kong Country: Tropical Freeze"><br><small><b><a href="dm/games/0100C1F0051B6000/README.md">Donkey Kong Country: Tropical Freeze</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dragon-quest-vii-reimagined.jpg" width="256" alt="DRAGON QUEST VII Reimagined"><br><small><b><a href="dm/games/0100A9D01C446000/README.md">DRAGON QUEST VII Reimagined</a></b><br>60 fps with 1.2.0</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/dragon-quest-xi-s.jpg" width="256" alt="DRAGON QUEST XI S: Echoes of an Elusive Age – Definitive Edition"><br><small><b><a href="dm/games/01006C300E9F0000/README.md">DRAGON QUEST XI S: Echoes of an Elusive Age – Definitive Edition</a></b><br>60 fps with 1.0.4</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/final-fantasy-resonance.jpg" width="256" alt="FINAL FANTASY RESONANCE"><br><small><b><a href="dm/games/0100606026F12000/README.md">FINAL FANTASY RESONANCE</a></b><br>60 fps with 1.0.1</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/final-fantasy-tactics.jpg" width="256" alt="FINAL FANTASY TACTICS - The Ivalice Chronicles"><br><small><b><a href="dm/games/010038B015560000/README.md">FINAL FANTASY TACTICS - The Ivalice Chronicles</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/fire-emblem-engage.jpg" width="256" alt="Fire Emblem Engage"><br><small><b><a href="dm/games/0100A6301214E000/README.md">Fire Emblem Engage</a></b><br>60 fps with 2.0.0</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/fire-emblem-three-houses.jpg" width="256" alt="Fire Emblem: Three Houses"><br><small><b><a href="dm/games/010055D009F78000/README.md">Fire Emblem: Three Houses</a></b><br>60 fps with 1.2.0</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ghost-trick-phantom-detective.jpg" width="256" alt="Ghost Trick: Phantom Detective"><br><small><b><a href="dm/games/010029B018432000/README.md">Ghost Trick: Phantom Detective</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/the-great-ace-attorney-chronicles.jpg" width="256" alt="The Great Ace Attorney Chronicles"><br><small><b><a href="dm/games/010036E00FB20000/README.md">The Great Ace Attorney Chronicles</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/hades.jpg" width="256" alt="Hades"><br><small><b><a href="dm/games/0100535012974000/README.md">Hades</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/hades-ii.jpg" width="256" alt="Hades II"><br><small><b><a href="dm/games/0100A00019DE0000/README.md">Hades II</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/hollow-knight-silksong.jpg" width="256" alt="Hollow Knight: Silksong"><br><small><b><a href="dm/games/010013C00E930000/README.md">Hollow Knight: Silksong</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/hyrule-warriors-age-of-calamity.jpg" width="256" alt="Hyrule Warriors: Age of Calamity"><br><small><b><a href="dm/games/01002B00111A2000/README.md">Hyrule Warriors: Age of Calamity</a></b><br>60 fps with 1.3.0</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/kirby-and-the-forgotten-land.jpg" width="256" alt="Kirby and the Forgotten Land"><br><small><b><a href="dm/games/01004D300C5AE000/README.md">Kirby and the Forgotten Land</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/luigis-mansion-3.jpg" width="256" alt="Luigi's Mansion 3"><br><small><b><a href="dm/games/0100DCA0064A6000/README.md">Luigi's Mansion 3</a></b><br>60 fps with 1.4.0</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/metroid-dread.jpg" width="256" alt="Metroid Dread"><br><small><b><a href="dm/games/010093801237C000/README.md">Metroid Dread</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/monster-hunter-rise.jpg" width="256" alt="Monster Hunter Rise"><br><small><b><a href="dm/games/0100B04011742000/README.md">Monster Hunter Rise</a></b><br>60 fps with 16.0.2</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/monster-train-2.jpg" width="256" alt="Monster Train 2"><br><small><b><a href="dm/games/010051701FB46000/README.md">Monster Train 2</a></b><br>60 fps with 1.1.1</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/octopath-traveler.jpg" width="256" alt="OCTOPATH TRAVELER"><br><small><b><a href="dm/games/010057D006492000/README.md">OCTOPATH TRAVELER</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/octopath-traveler-0.jpg" width="256" alt="Octopath Traveler 0"><br><small><b><a href="dm/games/01005270232F2000/README.md">Octopath Traveler 0</a></b><br>60 fps with 1.0.5</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/octopath-traveler-ii.jpg" width="256" alt="Octopath Traveler II"><br><small><b><a href="dm/games/0100A3501946E000/README.md">Octopath Traveler II</a></b><br>60 fps with 1.1.1</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/patricks-parabox.jpg" width="256" alt="Patrick's Parabox"><br><small><b><a href="dm/games/0100E44016C22000/README.md">Patrick's Parabox</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/persona-5-royal.jpg" width="256" alt="Persona 5 Royal"><br><small><b><a href="dm/games/01005CA01580E000/README.md">Persona 5 Royal</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/pikmin-4.jpg" width="256" alt="Pikmin 4"><br><small><b><a href="dm/games/0100B7C00933A000/README.md">Pikmin 4</a></b><br>60 fps, up to 120 on the Mac</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-brilliant-diamond.jpg" width="256" alt="Pokémon Brilliant Diamond"><br><small><b><a href="dm/games/0100000011D90000/README.md">Pokémon Brilliant Diamond</a></b><br>60 fps with 1.3.0</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-legends-z-a.jpg" width="256" alt="Pokémon Legends: Z-A"><br><small><b><a href="dm/games/0100F43008C44000/README.md">Pokémon Legends: Z-A</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-scarlet.png" width="256" alt="Pokémon Scarlet"><br><small><b><a href="dm/games/0100A3D008C5C000/README.md">Pokémon Scarlet</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-violet.jpg" width="256" alt="Pokémon Violet"><br><small><b><a href="dm/games/01008F6008C5E000/README.md">Pokémon Violet</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-sword.jpg" width="256" alt="Pokémon Sword"><br><small><b><a href="dm/games/0100ABF008968000/README.md">Pokémon Sword</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-shield.jpg" width="256" alt="Pokémon Shield"><br><small><b><a href="dm/games/01008DB008C2C000/README.md">Pokémon Shield</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/portal.jpg" width="256" alt="Portal"><br><small><b><a href="dm/games/01007BB017812000/README.md">Portal</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/raging-loop.jpg" width="256" alt="Raging Loop"><br><small><b><a href="dm/games/010020400E1C2000/README.md">Raging Loop</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/rhythm-heaven-groove.jpg" width="256" alt="Rhythm Heaven Groove"><br><small><b><a href="dm/games/0100D9F01D474000/README.md">Rhythm Heaven Groove</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/romance-of-the-three-kingdoms-8-remake.jpg" width="256" alt="ROMANCE OF THE THREE KINGDOMS 8 REMAKE"><br><small><b><a href="dm/games/0100C2A01A730000/README.md">ROMANCE OF THE THREE KINGDOMS 8 REMAKE</a></b><br>controller only</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/sea-of-stars.jpg" width="256" alt="Sea of Stars"><br><small><b><a href="dm/games/01008C0016544000/README.md">Sea of Stars</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/shin-megami-tensei-v-vengeance.jpg" width="256" alt="SHIN MEGAMI TENSEI V: Vengeance"><br><small><b><a href="dm/games/010069C01AB82000/README.md">SHIN MEGAMI TENSEI V: Vengeance</a></b><br>60 fps with 1.0.3</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/stardew-valley.jpg" width="256" alt="Stardew Valley"><br><small><b><a href="dm/games/0100E65002BB8000/README.md">Stardew Valley</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/steins-gate-reboot.jpg" width="256" alt="STEINS;GATE RE:BOOT"><br><small><b><a href="dm/games/01008BC024FDE000/README.md">STEINS;GATE RE:BOOT</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/super-smash-bros-ultimate.jpg" width="256" alt="Super Smash Bros. Ultimate"><br><small><b><a href="dm/games/01006A800016E000/README.md">Super Smash Bros. Ultimate</a></b><br>offline</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/taiko-risshiden-v-dx.jpg" width="256" alt="Taiko Risshiden V DX"><br><small><b><a href="dm/games/0100346017304000/README.md">Taiko Risshiden V DX</a></b><br>Japanese · played by touch</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/unicorn-overlord.jpg" width="256" alt="Unicorn Overlord"><br><small><b><a href="dm/games/010069401ADB8000/README.md">Unicorn Overlord</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/yoshis-crafted-world.jpg" width="256" alt="Yoshi's Crafted World"><br><small><b><a href="dm/games/01006000040C2000/README.md">Yoshi's Crafted World</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/nier-automata.png" width="256" alt="NieR:Automata The End of YoRHa Edition"><br><small><b><a href="dm/games/010056B015FE8000/README.md">NieR:Automata The End of YoRHa Edition</a></b><br>60 fps with 1.0.3</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-echoes-of-wisdom.jpg" width="256" alt="The Legend of Zelda: Echoes of Wisdom"><br><small><b><a href="dm/games/01008CF01BAAC000/README.md">The Legend of Zelda: Echoes of Wisdom</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/donkey-kong-country-returns-hd.png" width="256" alt="Donkey Kong Country Returns HD"><br><small><b><a href="dm/games/01009D901BC56000/README.md">Donkey Kong Country Returns HD</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-rabbids-sparks-of-hope.jpg" width="256" alt="Mario + Rabbids Sparks of Hope"><br><small><b><a href="dm/games/0100317013770000/README.md">Mario + Rabbids Sparks of Hope</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/xenoblade-chronicles-2.jpg" width="256" alt="Xenoblade Chronicles 2"><br><small><b><a href="dm/games/0100E95004038000/README.md">Xenoblade Chronicles 2</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/xenoblade-chronicles-3.jpg" width="256" alt="Xenoblade Chronicles 3"><br><small><b><a href="dm/games/010074F013262000/README.md">Xenoblade Chronicles 3</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/final-fantasy-crystal-chronicles.jpg" width="256" alt="FINAL FANTASY CRYSTAL CHRONICLES Remastered Edition"><br><small><b><a href="dm/games/0100CE4010AAC000/README.md">FINAL FANTASY CRYSTAL CHRONICLES Remastered Edition</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/return-of-the-obra-dinn.png" width="256" alt="Return of the Obra Dinn"><br><small><b><a href="dm/games/010032E00E6E2000/README.md">Return of the Obra Dinn</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/blasphemous-2.png" width="256" alt="Blasphemous 2"><br><small><b><a href="dm/games/010040801A4C8000/README.md">Blasphemous 2</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/silver-pines.jpg" width="256" alt="Silver Pines"><br><small><b><a href="dm/games/0100D5B026844000/README.md">Silver Pines</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/blasphemous.jpg" width="256" alt="Blasphemous"><br><small><b><a href="dm/games/0100698009C6E000/README.md">Blasphemous</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/final-fantasy-x-x2-hd-remaster.jpg" width="256" alt="FINAL FANTASY X/X-2 HD Remaster"><br><small><b><a href="dm/games/0100BC300CB48000/README.md">FINAL FANTASY X/X-2 HD Remaster</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-rabbids-kingdom-battle.jpg" width="256" alt="Mario + Rabbids Kingdom Battle"><br><small><b><a href="dm/games/010067300059A000/README.md">Mario + Rabbids Kingdom Battle</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/persona-4-golden.jpg" width="256" alt="Persona 4 Golden"><br><small><b><a href="dm/games/010062B01525C000/README.md">Persona 4 Golden</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/xenoblade-chronicles-definitive-edition.jpg" width="256" alt="Xenoblade Chronicles: Definitive Edition"><br><small><b><a href="dm/games/0100FF500E34A000/README.md">Xenoblade Chronicles: Definitive Edition</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/pokemon-legends-arceus.jpg" width="256" alt="Pokémon Legends: Arceus"><br><small><b><a href="dm/games/01001F5010DFA000/README.md">Pokémon Legends: Arceus</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-party-jamboree.jpg" width="256" alt="Super Mario Party Jamboree"><br><small><b><a href="dm/games/0100965017338000/README.md">Super Mario Party Jamboree</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/cult-of-the-lamb.jpg" width="256" alt="Cult of the Lamb"><br><small><b><a href="dm/games/01002E7016C46000/README.md">Cult of the Lamb</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/paper-mario-the-origami-king.jpg" width="256" alt="Paper Mario: The Origami King"><br><small><b><a href="dm/games/0100A3900C3E2000/README.md">Paper Mario: The Origami King</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/batman-arkham-knight.jpg" width="256" alt="Batman: Arkham Knight"><br><small><b><a href="dm/games/0100ACD0163D0000/README.md">Batman: Arkham Knight</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/bastion.jpg" width="256" alt="Bastion"><br><small><b><a href="dm/games/010038600B27E000/README.md">Bastion</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/baba-is-you.jpg" width="256" alt="Baba Is You"><br><small><b><a href="dm/games/01002CD00A51C000/README.md">Baba Is You</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/steamworld-heist-ii.jpg" width="256" alt="SteamWorld Heist II"><br><small><b><a href="dm/games/010089C01E9CA000/README.md">SteamWorld Heist II</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/steamworld-heist.jpg" width="256" alt="SteamWorld Heist: Ultimate Edition"><br><small><b><a href="dm/games/010016100A186000/README.md">SteamWorld Heist: Ultimate Edition</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/subnautica-below-zero.jpg" width="256" alt="Subnautica: Below Zero"><br><small><b><a href="dm/games/010014C011146000/README.md">Subnautica: Below Zero</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/steamworld-dig-2.jpg" width="256" alt="SteamWorld Dig 2"><br><small><b><a href="dm/games/0100CA9002322000/README.md">SteamWorld Dig 2</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/streets-of-rage-4.jpg" width="256" alt="Streets of Rage 4"><br><small><b><a href="dm/games/0100EC9010258000/README.md">Streets of Rage 4</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-party-superstars.jpg" width="256" alt="Mario Party Superstars"><br><small><b><a href="dm/games/01006FE013472000/README.md">Mario Party Superstars</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/subnautica.jpg" width="256" alt="Subnautica"><br><small><b><a href="dm/games/0100429011144000/README.md">Subnautica</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/steamworld-dig.jpg" width="256" alt="SteamWorld Dig"><br><small><b><a href="dm/games/01009320084A4000/README.md">SteamWorld Dig</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/team-sonic-racing.jpg" width="256" alt="Team Sonic Racing"><br><small><b><a href="dm/games/010092B0091D0000/README.md">Team Sonic Racing</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/well-dweller.jpg" width="256" alt="Well Dweller"><br><small><b><a href="dm/games/0100217023F6C000/README.md">Well Dweller</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/need-for-speed-hot-pursuit-remastered.jpg" width="256" alt="Need for Speed: Hot Pursuit Remastered"><br><small><b><a href="dm/games/010029B0118E8000/README.md">Need for Speed: Hot Pursuit Remastered</a></b><br>60 fps with 1.0.3</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/ea-sports-fc-27.jpg" width="256" alt="EA SPORTS FC 27"><br><small><b><a href="dm/games/0100C49025D3E000/README.md">EA SPORTS FC 27</a></b><br>60 fps with 1.8d.310c</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/portal-2.jpg" width="256" alt="Portal 2"><br><small><b><a href="dm/games/0100ABD01785C000/README.md">Portal 2</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/super-monkey-ball-banana-rumble.jpg" width="256" alt="Super Monkey Ball Banana Rumble"><br><small><b><a href="dm/games/010031F019294000/README.md">Super Monkey Ball Banana Rumble</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/atelier-ryza-dx.jpg" width="256" alt="Atelier Ryza: Ever Darkness &amp; the Secret Hideout DX"><br><small><b><a href="dm/games/0100199023B2E000/README.md">Atelier Ryza: Ever Darkness &amp; the Secret Hideout DX</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dragon-quest-iii-hd-2d-remake.jpg" width="256" alt="DRAGON QUEST III HD-2D Remake"><br><small><b><a href="dm/games/01003E601E324000/README.md">DRAGON QUEST III HD-2D Remake</a></b><br>60 fps with 1.1.2</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/hyrule-warriors-definitive-edition.jpg" width="256" alt="Hyrule Warriors: Definitive Edition"><br><small><b><a href="dm/games/0100AE00096EA000/README.md">Hyrule Warriors: Definitive Edition</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/metroid-prime-remastered.jpg" width="256" alt="Metroid Prime Remastered"><br><small><b><a href="dm/games/010012101468C000/README.md">Metroid Prime Remastered</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dragon-quest-i-ii-hd-2d-remake.jpg" width="256" alt="DRAGON QUEST I &amp; II HD-2D Remake"><br><small><b><a href="dm/games/0100D7C01F254000/README.md">DRAGON QUEST I &amp; II HD-2D Remake</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/dead-cells.jpg" width="256" alt="Dead Cells"><br><small><b><a href="dm/games/0100646009FBE000/README.md">Dead Cells</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/hollow-knight.jpg" width="256" alt="Hollow Knight"><br><small><b><a href="dm/games/0100633007D48000/README.md">Hollow Knight</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/triangle-strategy.jpg" width="256" alt="TRIANGLE STRATEGY"><br><small><b><a href="dm/games/0100CC80140F8000/README.md">TRIANGLE STRATEGY</a></b><br>60 fps with 1.1.1</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/castlevania-belmonts-curse.jpg" width="256" alt="Castlevania: Belmont's Curse"><br><small><b><a href="dm/games/0100BA4026E94000/README.md">Castlevania: Belmont's Curse</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-robot-wars-y.jpg" width="256" alt="SUPER ROBOT WARS Y"><br><small><b><a href="dm/games/010063301BD50000/README.md">SUPER ROBOT WARS Y</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/super-mario-rpg.jpg" width="256" alt="Super Mario RPG"><br><small><b><a href="dm/games/0100BC0018138000/README.md">Super Mario RPG</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/zelda-skyward-sword-hd.jpg" width="256" alt="The Legend of Zelda: Skyward Sword HD"><br><small><b><a href="dm/games/01002DA013484000/README.md">The Legend of Zelda: Skyward Sword HD</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/princess-peach-showtime.jpg" width="256" alt="Princess Peach: Showtime!"><br><small><b><a href="dm/games/01007A3009184000/README.md">Princess Peach: Showtime!</a></b><br>60 fps with 1.0.0</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/kirby-star-allies.jpg" width="256" alt="Kirby Star Allies"><br><small><b><a href="dm/games/01007E3006DDA000/README.md">Kirby Star Allies</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/dave-the-diver.jpg" width="256" alt="DAVE THE DIVER"><br><small><b><a href="dm/games/010097F018538000/README.md">DAVE THE DIVER</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/mario-luigi-brothership.jpg" width="256" alt="Mario &amp; Luigi: Brothership"><br><small><b><a href="dm/games/01006D0017F7A000/README.md">Mario &amp; Luigi: Brothership</a></b><br>up to 120 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dragon-quest-builders-2.jpg" width="256" alt="DRAGON QUEST BUILDERS 2"><br><small><b><a href="dm/games/010042000A986000/README.md">DRAGON QUEST BUILDERS 2</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/star-fox.jpg" width="256" alt="Star Fox"><br><small><b><a href="dm/games/0400E88025B1A000/README.md">Star Fox</a></b><br>Switch 2, Mac only, from a NUP</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/kirby-air-riders.jpg" width="256" alt="Kirby Air Riders"><br><small><b><a href="dm/games/040077201BE50000/README.md">Kirby Air Riders</a></b><br>Switch 2, Mac only, from a NUP</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/okami-hd.jpg" width="256" alt="ŌKAMI HD"><br><small><b><a href="dm/games/0100276009872000/README.md">ŌKAMI HD</a></b></small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/minecraft-dungeons-ii.jpg" width="256" alt="Minecraft Dungeons II"><br><small><b><a href="dm/games/0100A7C01B792000/README.md">Minecraft Dungeons II</a></b><br>60 fps, up to 120 on the Mac</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/sonic-superstars.jpg" width="256" alt="Sonic Superstars"><br><small><b><a href="dm/games/01008F701C074000/README.md">Sonic Superstars</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/dragon-ball-sparking-zero.jpg" width="256" alt="DRAGON BALL: Sparking! ZERO"><br><small><b><a href="dm/games/010035F022078000/README.md">DRAGON BALL: Sparking! ZERO</a></b><br>60 fps, up to 120 on the Mac</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/romance-of-the-three-kingdoms-xiv.jpg" width="256" alt="ROMANCE OF THE THREE KINGDOMS XIV"><br><small><b><a href="dm/games/0100ED7012DB2000/README.md">ROMANCE OF THE THREE KINGDOMS XIV</a></b></small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/the-rogue-prince-of-persia.jpg" width="256" alt="The Rogue Prince of Persia"><br><small><b><a href="dm/games/01008D9022462000/README.md">The Rogue Prince of Persia</a></b><br>60 fps, up to 120 on the Mac</small></td>
<td></td>
</tr>
</table>
<!-- end of gallery -->

### For developers

[How it works](docs/development.md) · [Game notes](dm/games/README.md#games) · [Bring-up and debugging](docs/agents/README.md) · [Front ends](docs/frontends.md) · [Contributing](CONTRIBUTING.md)

### Acknowledgements

This project is built on other people's work ([licenses](dm/third_party/README.md)):

- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT) developed this native-execution approach, for Diablo II: Resurrected. nxnative started as a copy of its generic parts: the NSO rewriter, the host that stands in for Horizon, the NVN-on-Metal layer and the iOS app shell. Fixes go both ways.
- **Ryujinx** (MIT): its shader translator (`Ryujinx.Graphics.Shader`, `Ryujinx.Common` and `Spv.Generator` 1.3.2, in `dm/third_party/ryujinx` with a few fixes listed in [its README](dm/third_party/ryujinx/README.md)) turns the games' shaders into SPIR-V. Its emulation of the kernel and system services is also a reference when the host's behaviour is in doubt.
- **[Atmosphère](https://github.com/Atmosphere-NX/Atmosphere)**: its kernel, mesosphère, is the reference for Horizon's synchronization semantics (address arbiter, condition variables).
- **[LibHac](https://github.com/Thealexbarney/LibHac)**: reads NSPs and layers updates over the base game in `dm/tools/nx_extract`.
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)**: SPIR-V to Metal Shading Language.
- **[glslang](https://github.com/KhronosGroup/glslang)** compiles the GLSL of OpenGL games to SPIR-V for it.
- **[MacNativeGames](https://github.com/ly05010419/MacNativeGames)** (MIT): the GPU widening of 8-bit indices and in-pass clears in `dm/gfx/nvn/nvn_mtl.m`, and the visibility-counter lowering in the shader translator.

### License

MIT ([LICENSE](LICENSE)). Third-party code keeps its own license ([dm/third_party](dm/third_party/README.md)).
