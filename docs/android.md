# DroidPlay on Android

The [README](../README.md#droidplay-core) has the short path: install DroidPlay for Windows, build a game, play it. This page has the rest: every page of
the desktop app, the app on the phone, game apps, another Vulkan driver, games that compile their shaders while they run, the command line and the files that
ask a running game for diagnostics.

> [!IMPORTANT]
> **Bring your own game.** Nothing from any game is in this repository, and no packed game is distributed: you dump the game and the keys from **your own**
> Switch, and the app you build is for you only. Do not share APKs packed with a game, keys or firmware.

- [DroidPlay for Windows](#droidplay-for-windows): [installing](#installing), [Get started](#get-started), [the pages](#the-pages), [from source](#from-source)
- [DroidPlay on a Mac](#droidplay-on-a-mac)
- [The Android app](#the-android-app)
- [Game apps](#game-apps)
- [Another Vulkan driver (Turnip)](#another-vulkan-driver-turnip)
- [Games that compile their shaders while they run](#games-that-compile-their-shaders-while-they-run)
- [Packing from the command line](#packing-from-the-command-line)
- [Seeing what a game draws](#seeing-what-a-game-draws)

## DroidPlay for Windows

DroidPlay for Windows is the desktop app in this repository, `scripts/nxnative_android.py`: it drives the packing script and adb for you. The same app runs on
Linux and a Mac [from source](#from-source). It has DroidPlay's name and icon, but it is a separate app from [DroidPlay on a Mac](#droidplay-on-a-mac).

### Installing

Download **DroidPlay-Setup-&lt;version&gt;.exe** from the [latest release](https://github.com/enjoyerofslop/droidplay-core/releases/latest) and run it. Windows
warns that it comes from the internet and isn't signed: **More info**, then **Run anyway**.

- It installs DroidPlay for you only, in `%LOCALAPPDATA%\Programs\DroidPlay`, with no administrator prompt and nothing more to download: its own Python with
  the app's modules, and DroidPlay Core (Setup is about 80 MB, 600 MB installed). Each Setup has a `.sha256` beside it on the release page.
- DroidPlay is then in the Start menu, on the desktop, and in **Settings › Apps**, which uninstalls it. Your games and their builds, the Android SDK, the
  tools and your settings stay.
- DroidPlay says when a newer release is out, and **Update** installs it: DroidPlay downloads the new Setup, checks it against the release, runs it
  (a small Updating DroidPlay window shows its progress) and opens again. Or close DroidPlay and run the new Setup yourself.
- **Coming from Install DroidPlay.cmd?** Close DroidPlay and run Setup: it moves your DroidPlay over and removes the copy the .cmd installed, and keeps your
  games, builds and settings. `Install DroidPlay.cmd uninstall` still removes such a copy by hand (`dm/android/windows/install_droidplay.cmd`).

### Get started

DroidPlay opens on **Get started**: four steps, each saying what it needs and whether it's done. Setting up takes about half an hour the first time.

- **Your keys:** pick your `prod.keys`.
- **Tools for building:** **Install tools** downloads Microsoft's JDK 21 and the .NET SDK 10 into the app's own folder (`%LOCALAPPDATA%\nxnative\android\tools`),
  and Google's Android SDK with the NDK, CMake, build-tools, platform and platform-tools into Android Studio's place, `%LOCALAPPDATA%\Android\Sdk` (about 1.5 GB
  to download, 5 GB installed), with one bar and the time left. Installing the Android SDK means accepting its
  [license](https://developer.android.com/studio/terms), which the app asks first; its usage metrics stay off. What the computer already has is kept.
  From a console: `build_android_from_nsp.py --setup --accept-android-licenses`.
- **Your phone:** plug it in with USB debugging on; the step says when the phone is waiting for you to tap **Allow**.
- **Your first game:** add the folder with its NSP or XCI files, then **Build and install**.

Until all four are done, a launch opens on the checklist and the top bar's **Setup 2 of 4** opens it; **Settings › Show the setup checklist** does any time.

<table>
<tr>
<td align="center" valign="top" width="36%"><img src="images/windows/phone-setup.png" alt="DroidPlay for Windows' Set up your phone guide for a Samsung Galaxy: Build number, Auto Blocker, USB debugging and Allow, with the phone waiting for Allow at its foot"><br><small><b>Set up my phone</b>: the steps for your phone's brand</small></td>
<td align="center" valign="top" width="64%"><img src="images/windows/build.png" alt="DroidPlay for Windows' Builds page part-way through building Pokémon Brilliant Diamond: four stages done, the shaders for Vulkan translating, with the time left"><br><small><b>Builds</b>: a first build part-way, its stages and the time left</small></td>
</tr>
</table>

### The pages

- **Library:** the games you added (**+ Build game** picks a folder with a game's NSP files), each with its box art, version and status on the phone picked at the top.
  The big button does what comes next: **Build and install**, **Install on phone** (a game built before, without building again) or **Play**. **Manage** has the rest:
  build only, update the app on the phone, remove the game. A game with no profile gets **Experimental build**: the script surveys the game, writes a guessed
  provisional profile into the game's folder and packs it; once built it is marked *Experimental* and can be installed like any other.
- **Builds:** the running build's stages, progress and messages (the bar at the bottom of every page follows it); a build started from a console shows here too.
  When a build fails, a banner says what went wrong in plain words, with the button that fixes it where there is one (**Install again** once the phone has room,
  **Choose prod.keys** for keys older than the game). Otherwise it is likely a bug: **Copy report** copies a short report to paste in #help on the Discord, and
  **Save full report** saves the whole log; both leave out your user folder, the phone's serial and anything that looks like a key.
- **Phones:** adb devices over USB and Wi-Fi (pair, connect, discover), each one's battery and free space, the app version and the games on each phone, saves
  backed up to the computer. **How to connect a phone** (also the checklist's **Set up my phone**) walks through turning on USB debugging for the phone's brand
  (Samsung's Auto Blocker, Xiaomi's Install via USB, a Pixel's driver) and what to try when the phone doesn't show up; a phone below 20% battery gets a warning,
  since a PC's USB port charges slowly and an install takes minutes.
- **Performance:** the game's log from `adb logcat`, with the frame time, GPU and CPU figures the host prints, and a frame's GPU time per pass.
- **Settings:** your `prod.keys`, and the [requirements](#what-the-command-line-needs) with how to install what is missing (on Windows, **Install what's missing** does it).

A rebuild only does what changed: the extraction, the rewritten code and the translated shaders are reused when their inputs are the same, and the RomFS image is not
copied to the phone again when the phone already holds the same one.

### From source

On Linux or a Mac, or on Windows without Setup, `uv run scripts/nxnative_android.py` opens a window that drives the packing script and adb for you ([uv](https://docs.astral.sh/uv/) brings Python and the
modules the script names at its top; `python scripts/nxnative_android.py` works too, with them installed).

To get it on Windows, install [uv](https://docs.astral.sh/uv/) (`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`), get
DroidPlay Core (`git clone https://github.com/enjoyerofslop/droidplay-core`) and, in its folder, `uv run scripts\nxnative_android.py`.

The command line's requirements are in [What the command line needs](#what-the-command-line-needs); the app's **Settings** page checks them.

## DroidPlay on a Mac

[DroidPlay](https://github.com/enjoyerofslop/droidplay) is a Mac app that builds and plays Switch games on a Mac, an iPhone and an iPad, and builds
Android games with DroidPlay Core. For Android, add your games folder, then **Install on Android** (one launcher app holding every game, over adb)
or **Build Game App** (an APK, or an XAPK for an installer app). Its README has the requirements and the setup steps.

## The Android app

- **Launcher.** Opening **DroidPlay** (its package is still `org.nxnative.android`) shows the games on the phone with their icon, name and version (a game whose
  host the installed app lacks is marked as needing an app update). Picking a game opens its **settings screen**, grouped into Game and Controls: console mode (handheld is lighter), game language, game timing, render
  scale where the game supports it, the frame-rate counter, rumble and its strength. **Play** starts the game. Lines like `DM_RENDER_SCALE=0.8` in
  `Android/data/org.nxnative.android/files/env.txt` win over the screen (they show greyed out).
- **The first start** of a game builds its pipelines for the phone's GPU, and stays on the loading screen meanwhile: 80 seconds for Brilliant Diamond on a
  Galaxy S25 Edge, 39 on a OnePlus Pad 3. Desktop DroidPlay says so the first time **Play** is pressed after an install, and the app says so when the game has no
  pipelines saved yet. Later starts take a few seconds.
- **In the game.** Touch controls are drawn over the picture in three layouts (2D, 3D and Tap, switched with the round button at the top); touches no control takes go
  to the game's touch screen. A physical controller works as player 1 and hides the touch controls; rumble goes to the controller or the phone, and shaking the phone
  shakes the controller. The **≡** button at the top (left of −) goes back to the launcher while the game keeps running behind it: **Play** on the same game resumes
  it, and picking another game asks before closing the running one.
- **Saves** stay in the app's internal storage (`saves/<title ID>`), so updating the app keeps them; the desktop app backs them up to the computer. The log is
  `Android/data/org.nxnative.android/files/log.txt` (also `adb logcat -s DroidPlay`).

## Game apps

A game can also be built as an app of its own, with its name, icon and saves, opening straight into the game. It installs on any arm64 device with Vulkan
without the DroidPlay app or a connection to your computer: copy the file over and open it. Several install side by side, apart from the DroidPlay app.

- **DroidPlay for Windows:** **Manage › Build a game app…**, then APK or XAPK. No phone needs to be connected; the file goes in the game's folder.
- **DroidPlay on a Mac:** **Build Game App**.
- **The command line:** `--game-apk`, or `--game-apk --xapk` ([Packing from the command line](#packing-from-the-command-line)).

A game whose data is more than an APK holds (2 GB) gets it beside the APK, as `<name>.romfs`: copy that file anywhere on the device or its SD card, and pick it
once when the game first starts. An XAPK carries the data as the app's OBB file instead, for an XAPK installer app. A game app is for your own devices only: it
carries the game, so never share it. How it is packed: [A game app](../dm/android/README.md#a-game-app).

## Another Vulkan driver (Turnip)

On a phone with an Adreno GPU, a game can run on a Vulkan driver you put on the phone instead of the system's, as in Switch emulators: usually a build of Mesa's
open-source Turnip driver, such as [Mr. Purple's](https://github.com/MrPurple666/purple-turnip/releases). The app carries what loads it
([libadrenotools](../dm/third_party/libadrenotools/README.md)), so trying one needs no new build:

1. Unzip the driver package (`turnip_mrpurple_T30-toasted.adpkg.zip`, say). It holds a `.so` (`vulkan.purple.so`) and a `meta.json` that names it.
2. Copy the `.so` into `Android/data/org.nxnative.android/files/`, beside `env.txt`: `adb push vulkan.purple.so /sdcard/Android/data/org.nxnative.android/files/`.
   A game app reads its own folder, `Android/data/org.nxnative.game.t<title ID>/files/`.
3. Add `DM_VK_DRIVER=vulkan.purple.so` to `env.txt` there (a path relative to that folder, or an absolute one), then start the game.

The app copies the driver into its internal storage at start, since Android loads no code from shared storage, and copies it again when the file changes. The log
names the driver that runs: `[vk] driver: … (DM_VK_DRIVER, through libadrenotools), not the system's: PurpleVK-public Adreno (TM) 740 …`. A driver that can't run
(a wrong path, a build for another GPU, one that loads but can't make the Vulkan device) gets one `[RED] [vk] DM_VK_DRIVER …` line saying why, and the game runs on
the system's driver. On a phone without an Adreno GPU (Mali, Xclipse) the line is ignored, and the log says so. Remove the line from `env.txt`
(or start it with `#`) to go back. Each driver keeps its own pipeline cache, so the first start on a new driver compiles the game's pipelines again (it can take a
minute to the first frame, and it stutters until they are built), and the system driver's cache is still there afterwards.

Whether a driver helps depends on the game and the device. With Mr. Purple's T30, Super Mario Odyssey's opening runs at 60 fps on an Odin 2 (as on its own driver)
and at 40 fps on a Retroid Pocket 5 (38 on its own); Pokémon Brilliant Diamond's Eterna City runs at 58 fps on a Retroid Pocket 5 with
Turnip (15 on its own driver), and at 60 fps on an Odin 2, as on its own driver.

## Packing from the command line

### What the command line needs

Python 3.12 or newer with `lz4`, `capstone`, `fonttools` and `backports.zstd` (not needed on Python 3.14), plus `PySide6` for the desktop app:
`pip install lz4 capstone fonttools backports.zstd PySide6`. The .NET SDK 10, the Android SDK with an NDK, CMake 3.22 and build-tools (set `ANDROID_HOME` or pass
`--sdk`), `adb`, and a JDK (for `keytool` and `javac`). The desktop app's **Settings** page checks all of this and says how to get what is missing; DroidPlay for Windows installs it for you.
On Windows, use Python 3.14 and set `PYTHONUTF8=1` for the command line (the desktop app sets it for what it runs): the scripts read and write text as UTF-8,
which Python on Windows does by default only from 3.15, and lz4 has no Windows build for 3.15 yet.

```
python scripts/build_android_from_nsp.py "<folder with your NSP / XCI files>" -k "<your prod.keys>"    build, install, copy the game
                         (a Switch 2 game: the folder with its .nup or dump, or the .nup itself; no keys needed)
    --game-apk [--xapk]  the game as an app of its own (<name>.apk, plus <name>.romfs, with its DLC after the RomFS, for a game over 2 GB, or one .xapk); no device needed
    -p v0                pack the base game instead of the newest version in the folder (a version the profile does not register is packed from a derived profile)
    -l es-419            the default game language (a code or a name)
    --serial <device>    the adb device, when more than one is connected
    --no-push            build the APK only (a game without a profile is first built this way)
    --push-only          install the app and copy a game built before, without building
python scripts/build_android_from_nsp.py --apk-only    pack the app with every game built on this computer and install it
python scripts/build_android_from_nsp.py --check       what the build needs on this computer, as JSON
```

The first build of a game takes a while (the shader translation and, on a hard disk, the RomFS image); later builds reuse what did not change.

## Games that compile their shaders while they run

Some games carry their shaders as GLSL source and compile them with Nintendo's GLSL compiler while they run (The Binding of Isaac does). Their files hold no shader to
translate, so the first build has none (`[RED] the game is packed without shaders`): the game runs but draws nothing. The app captures them on the phone by itself:

1. Play the game for a while: each shader is saved the first time the game compiles it (in the game's folder on the phone, `glslc_capture/`).
2. On the computer, the game's card in the desktop app says how many new shaders the phone has; **Manage › Update shaders from the phone** copies them, translates
   the new ones and puts them on the phone (no app build: about a minute). From the command line: `build_android_from_nsp.py "<NSP folder>" -k <prod.keys> --update-shaders`.
   Every build and **Install on phone** also picks up the new ones first.
3. Open the game again.

A scene reached later (or a DLC) can compile more shaders: repeat until the log shows no `no translated shader`. This is done for games packed from a provisional
profile; a registered profile's shader tables name the captures they were made from. DLC in the NSP folder is extracted and copied to the phone with the game.

A game packed from a registered profile has its shaders in its tables, so a shader split that fails there stops the build rather than pack the game without them ([why](reference/packing.md#an-android-build-packs-a-registered-game-without-shaders-after-a-split-error-and-succeeds)).

## Seeing what a game draws

When a game shows a black or wrong picture, these files in `Android/data/org.nxnative.android/files/` ask the running game for diagnostics (each is checked every
30 frames and removed when taken; `adb shell touch <path>` creates one):

- `shot_now`: the next presented frame as a PNG in `dump/` (`DM_NVN_SHOT=<frame>[,<frame>...]:<path>` in `env.txt` does the same for given frames).
- `dump_now`: every render target of one frame, after each pass, as `.raw` and `.png` in `dump/` (a 3D texture's slices stacked, up to 1,024 images), with each draw's shaders, bound textures, constant buffers (their first values) and blend state in the log.
- `threads_now`: every game thread's state, what it waits on and its backtrace, in the log (for a game that stops moving on).
