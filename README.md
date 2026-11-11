<!-- The "droidnative" anchor keeps links made before the rename working: the project was droidnative until 2026-11-09. -->
# <a id="droidnative"></a>DroidPlay Core

**Nintendo Switch and Switch 2 games running natively on Android: not an emulator.** The game's own ARM64 code runs directly on the device's CPU, and its NVN
graphics are replayed on the GPU through Vulkan. Pokémon Brilliant Diamond plays at 60 fps on an Ayn Odin 2, Animal Crossing: New Horizons at 30.

- **Native, not emulated.** A Switch and an Android device both run ARM64 code: the game's code is rewritten only where the host needs it (system calls,
  thread registers), and a host answers the Switch's system calls and SDK services. There is no CPU emulation.
- **A game is an app of its own**, with its name, icon and saves, installable on any arm64 device with Vulkan, or every game in one launcher app.
- **Packed on your computer** from your own dump: NSP / XCI files, or a Switch 2 game's `.nup` or dump folder. [DroidPlay for Windows](#the-desktop-app) and
  [DroidPlay](https://github.com/enjoyerofslop/droidplay) on a Mac do it with a click; the command line works on any computer.

DroidPlay Core is [seedds/nxnative](https://github.com/seedds/nxnative) (Switch games natively on the iPhone, the iPad and the Mac) with an Android port: the engine the
DroidPlay apps build games with. The port began as [RogelioLB/nxnative-android](https://github.com/RogelioLB/nxnative-android) (the Vulkan replay of NVN, the Android
front end, the packing script); DroidPlay Core carries it on and follows nxnative's `main`, merged in regularly, so its games, fixes and Switch 2 work reach Android too. nxnative itself stays Apple-only by its
maintainer's choice: Android work belongs here, not there. Everything below the line further down is nxnative's own README (the iPhone and Mac side).

It was called droidnative until 2026-11-09, and was renamed so as not to be confused with [DroidNative](https://github.com/DroidNative/DroidNativeApp), which runs
Linux desktop apps on Android ([#40](https://github.com/enjoyerofslop/droidplay-core/issues/40)). Links to the old name lead here.

> [!IMPORTANT]
> **Bring your own game.** Nothing from any game is in this repository, and no packed game is distributed: you dump the game and the keys from **your own**
> Switch, and the app you build is for you only. Do not share APKs packed with a game (they carry its code and files), keys or firmware, and do not ask for them
> in issues. The project is not affiliated with Nintendo or any game publisher.

## Ways to play

- **DroidPlay for Windows:** download **DroidPlay-Setup-&lt;version&gt;.exe** from the [latest release](https://github.com/enjoyerofslop/droidplay-core/releases/latest)
  and run it. DroidPlay opens on **Get started**, a checklist that installs the tools it builds with, helps you set up your phone and builds your first game
  ([The desktop app](#the-desktop-app)). The same app runs on Linux and a Mac from source (`uv run scripts/nxnative_android.py`). It has DroidPlay's name and
  icon, but it is a separate app from DroidPlay on a Mac.
- **DroidPlay on a Mac:** add your games folder, then **Install on Android** (one launcher app holding every game, over adb) or **Build Game App** (an APK, or an
  XAPK for an installer app). See [DroidPlay](https://github.com/enjoyerofslop/droidplay).
- **The command line, any computer:** [Packing from the command line](#packing-from-the-command-line). `--game-apk` makes a game app; without it the game goes into
  the launcher app on a connected device.

<table>
<tr>
<td align="center" valign="top" width="50%"><img src="docs/images/windows/get-started.png" alt="DroidPlay for Windows on Get started: the keys picked, the tools for building downloading with the time left, and the phone waiting for Allow"><br><small><b>Get started</b>: your keys, the tools downloading, your phone and your first game</small></td>
<td align="center" valign="top" width="50%"><img src="docs/images/windows/library.png" alt="DroidPlay for Windows' Library: Pokémon Brilliant Diamond with its box art, ready on a Galaxy S25 Edge, with a Play button"><br><small><b>Library</b>: a game installed on the phone, ready to play</small></td>
</tr>
</table>

<!-- The "status" anchor keeps links made before the rename working: DroidPlay's README links to #status. -->
## <a id="status"></a>Game Status

Screen captures from the test runs, taken on the device. The round button at the top is DroidPlay's menu, the line at the bottom Android's gesture bar. On a
phone, DroidPlay's on-screen controls are drawn over the game.

<table>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/android/pokemon-brilliant-diamond-odin-2.jpg" width="256" alt="Pokémon Brilliant Diamond in Eterna City on an Ayn Odin 2"><br><small><b><a href="dm/games/0100000011D90000/README.md">Pokémon Brilliant Diamond</a></b><br>Ayn Odin 2: Eterna City, 60 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/android/animal-crossing-new-horizons-odin-2.jpg" width="256" alt="Animal Crossing: New Horizons outside the player's house on an Ayn Odin 2"><br><small><b><a href="dm/games/01006F8002326000/README.md">Animal Crossing: New Horizons</a></b><br>Ayn Odin 2: outside the player's house, 30 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/android/super-mario-odyssey-retroid-pocket-5.jpg" width="256" alt="Super Mario Odyssey's opening cutscene on a Retroid Pocket 5"><br><small><b><a href="dm/games/0100000000010000/README.md">Super Mario Odyssey</a></b><br>Retroid Pocket 5: the opening cutscene, 59 fps</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/android/super-smash-bros-ultimate-odin-2.jpg" width="256" alt="A Super Smash Bros. Ultimate battle on an Ayn Odin 2"><br><small><b><a href="dm/games/01006A800016E000/README.md">Super Smash Bros. Ultimate</a></b><br>Ayn Odin 2: a battle, 40–59 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/android/zelda-links-awakening-odin-2.jpg" width="256" alt="The Legend of Zelda: Link's Awakening on an Ayn Odin 2: Link in the Ancient Ruins"><br><small><b><a href="dm/games/01006BB00C6F0000/README.md">The Legend of Zelda: Link's Awakening</a></b><br>Ayn Odin 2: the Ancient Ruins, 60 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/android/zelda-skyward-sword-hd-odin-2.jpg" width="256" alt="The Legend of Zelda: Skyward Sword HD in Skyloft's plaza on an Ayn Odin 2, Link at the bird statue"><br><small><b><a href="dm/games/01002DA013484000/README.md">The Legend of Zelda: Skyward Sword HD</a></b><br>Ayn Odin 2: Skyloft at 60 fps</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/android/final-fantasy-resonance-odin-2.jpg" width="256" alt="Final Fantasy Resonance's first field at night on an Ayn Odin 2, its flames missing"><br><small><b><a href="dm/games/0100606026F12000/README.md">Final Fantasy Resonance</a></b><br>Ayn Odin 2: the first field, 42 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/android/pokemon-shield-galaxy-s25-edge.jpg" width="256" alt="Pokémon Shield on a Samsung Galaxy S25 Edge: the player at the front door of the house in Postwick, under the on-screen controls"><br><small><b><a href="dm/games/01008DB008C2C000/README.md">Pokémon Shield</a></b><br>Samsung Galaxy S25 Edge: outside the player's house in Postwick, 30 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/android/frostpunk-galaxy-s25-edge.jpg" width="256" alt="Frostpunk's city on a Samsung Galaxy S25 Edge: the snow and the crater drawn, the Generator missing but for its shadow"><br><small><b><a href="dm/games/0100B1C0249B4000/README.md">Frostpunk</a></b><br>Samsung Galaxy S25 Edge: the city, 30 fps</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/android/divinity-original-sin-2-odin-2.jpg" width="256" alt="Divinity: Original Sin 2 on an Ayn Odin 2: the player's character in the Merryweather's hold"><br><small><b><a href="dm/games/010027400CDC6000/README.md">Divinity: Original Sin 2 - Definitive Edition</a></b><br>Ayn Odin 2: the Merryweather's hold, 30 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/android/zelda-breath-of-the-wild-odin-2.jpg" width="256" alt="The Legend of Zelda: Breath of the Wild on an Ayn Odin 2: Link in the Shrine of Resurrection"><br><small><b><a href="dm/games/01007EF00011E000/README.md">The Legend of Zelda: Breath of the Wild</a></b><br>Ayn Odin 2: the Shrine of Resurrection, 30 fps</small></td>
<td align="center" valign="top" width="33%"><img src="docs/images/android/mario-kart-world-odin-2.jpg" width="256" alt="Mario Kart World's world map on an Ayn Odin 2"><br><small><b><a href="dm/games/0400C3F00006E000/README.md">Mario Kart World</a></b><br>Ayn Odin 2: the world map, about 55 fps</small></td>
</tr>
<tr>
<td align="center" valign="top" width="33%"><img src="docs/images/android/zelda-ocarina-of-time-galaxy-z-fold-8.jpg" width="256" alt="The Legend of Zelda: Ocarina of Time's title screen on a Samsung Galaxy Z Fold 8's cover display, the movie behind the logo black"><br><small><b><a href="dm/games/0400486024DEC000/README.md">The Legend of Zelda: Ocarina of Time</a></b><br>Samsung Galaxy Z Fold 8: the title, about 30 fps</small></td>
<td></td>
<td></td>
</tr>
</table>

Each row's State starts with its tier: the highest one whose conditions have all been shown.

| Tier | What has been shown |
|---|---|
| **Playable through** *a named stretch* | Played by hand (adb input counts; a scripted run alone doesn't) from a new game or a save made on the device, through the stretch named; the game's target frame rate on at least one device (a median of 95% of it or more; the Switch's rate, or the one its profile sets); nothing in that stretch that stops progress or hides the world; a save made on Android and loaded again; sound checked. A stretch that ends before the game's first battle, race or level end says so |
| **In-game** | Gameplay under the player's control, not only menus or movies, with the picture usable and at least half the target frame rate, but not every condition of Playable shown yet: a scripted run, someone else's save, below the target, saves or sound not checked |
| **In-game, blocked** | Gameplay reached, but a named bug stops normal play: the world missing or black, or under half the target frame rate |
| **Menus** | The title, menus or movies; no control of the player in gameplay |
| **Boots** | A first frame or a logo; nothing further shown |
| **Doesn't run** | Stops before its first frame, or the packing script refuses it |

The rest of each row says on which devices, how far and how (by hand, or a scripted run from a fresh or a downloaded save), the frame rate, and what has not
been tried.

| Game | Device | State |
|---|---|---|
| Pokémon Brilliant Diamond 1.3.0 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5, Samsung Galaxy S25 Edge, Samsung Galaxy Z Flip 7, Google Pixel 9 Pro XL | Playable through Lake Verity's first battle: 60 fps (the profile's rate; the Switch runs it at 30). On the Pixel 9 Pro XL (Mali), played by hand from a new game through Twinleaf, Route 201 and Lake Verity to Turtwig and the first battle, a wild Starly, won, with sound, a save made on the phone and Continue working; one minute at the starter screen ran at 50–54 fps. On the other five, In-game: 59–60 fps in Eterna City's overworld, in a scripted run from a downloaded save with the player standing by the Pokémon Center; a new game was played by hand into the overworld on the Odin 2 on 2026-11-07, before the nxnative merge, and not since. The Retroid Pocket 5 no longer crashes at launch, and its own driver now runs Eterna City as fast as [Turnip](#another-vulkan-driver-turnip) does (15 fps before) |
| Animal Crossing: New Horizons 3.0.3 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5, Samsung Galaxy S25 Edge | In-game: 30 fps (as on the Switch) on all four, in scripted runs: the new game's airport at Nook Inc.'s counter (a fresh save, no input), and outside the player's house from a downloaded save with the player standing. Not played by hand or through |
| Super Mario Odyssey 1.4.1 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5, Samsung Galaxy S25 Edge, Google Pixel 9 Pro XL | In-game: the Start menu and the opening cutscene at 59–60 fps on all five (the cutscene ran at 38 on the Retroid Pocket 5 on 2026-11-08), and play in the Cap Kingdom at 60 on the Odin 2 (one scripted run of 15 s), past the hint video that used to crash it (the host's AVC decoder, fixed; the video plays on the Pad 3 too). Not played by hand. The crash now and then while it loads is fixed. The Pixel 9 Pro XL's Mali-G715, the first GPU outside Adreno, has no BC textures, so they are decoded on the CPU (2.2 GB resident in the cutscene, against 1.64 GB) |
| Super Smash Bros. Ultimate 13.0.5 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5, Samsung Galaxy S25 Edge | In-game: boots to its opening movie at 60 fps on all four, with the hinted shared font the packer now ships (Android's Roboto made it crash); the crash in about one boot in five is fixed too. The route's battle (Mario against a random CPU fighter, the player idle; not played by hand) runs at 60 fps on the S25 Edge, 52–60 on the Pad 3 (2026-11-09) and 57–60 on the Retroid Pocket 5 (2026-11-10), by stage and fighter; 40–59 on the Odin 2 (2026-11-08, not measured since) |
| The Legend of Zelda: Link's Awakening 1.1.0 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5, Samsung Galaxy S25 Edge | In-game: from a downloaded save at the Ancient Ruins (after the fifth dungeon), Link standing, the picture right: 60 fps on the Odin 2, 38–45 on the S25 Edge, and 32–33 on the Pad 3 and the Retroid Pocket 5, where the game drops to its 30 fps interval. Not played by hand or from a new game. The boot crash it had on every launch on the Retroid Pocket 5 and now and then on the Pad 3 is fixed (checked on the Retroid Pocket 5) |
| The Legend of Zelda: Skyward Sword HD 1.0.1 | Ayn Odin 2, OnePlus Pad 3, Retroid Pocket 5, Samsung Galaxy S25 Edge | In-game: Skyloft's plaza from a downloaded 31-hour Hero Mode save, Link standing at the bird statue, its terrain in colour on all four: 59–60 fps on the Odin 2, the Pad 3 and the S25 Edge, and 43 on the Retroid Pocket 5, where the game switches between its 60 and 30 fps intervals within a run. The opening movie at 55–60 fps (41 on the Retroid Pocket 5). Not played by hand or from a new game on Android |
| Final Fantasy Resonance 1.0.1 | Ayn Odin 2, OnePlus Pad 3, Samsung Galaxy S25 Edge, Google Pixel 9 Pro XL | In-game: a new game's opening into the first field in a scripted run, then Continue from its autosave and a walk north: about 42 fps on the Odin 2 and the Pad 3 and 30–33 on the S25 Edge, with the field drawn right (10–16 fps before 0.6.0); the opening at 30 fps on the Pixel 9 Pro XL. On the Odin 2 the field's flames are missing. Not played by hand or past the first field, no battle yet; not tried on the Retroid Pocket 5 |
| Pokémon Shield 1.3.2 | Retroid Pocket 5, Samsung Galaxy S25 Edge, Google Pixel 9 Pro XL, Samsung Galaxy Z Flip 7 | Playable through the first battle: 30 fps (as on the Switch) on all four. On the Retroid Pocket 5, played by hand from a new game through the opening, Postwick, Route 1 and Wedgehurst to the starters and Hop's battle, won; on the S25 Edge and the Pixel 9 Pro XL (Mali), into Postwick, where Hop meets the player outside the house; on the Z Flip 7 (Xclipse), into the house. Sound, saves made on the phone and Continue work on all four. Not played as far as the Wild Area; not tried on the other devices |
| Frostpunk 1.0.1 | Samsung Galaxy S25 Edge | In-game, blocked: 30 fps from the title through A New Home's intro into the city and about two minutes there with live input, with sound, but the Generator, the buildings and the props are invisible: their shaders read raw global memory, which the Vulkan replay doesn't have yet. Not played past the first minutes |
| Pokémon: Let's Go, Pikachu! 1.0.0 | Samsung Galaxy Z Fold 8, Google Pixel 9 Pro XL, Samsung Galaxy Z Flip 7 | Playable through Route 1 (catches; no trainer battle yet): 30 fps (as on the Switch) on all three. On the Z Fold 8, played by hand from a save made on the phone in Pallet Town through Professor Oak's scene, getting Pikachu, his lab and the Pokédex, to two wild catches on Route 1 made with the buttons (no motion needed); the opening into Pallet Town was a scripted run there. On the Pixel 9 Pro XL (Mali), played by hand from a new game through the opening and the rival's visit into Pallet Town, and a wild Pidgey caught on Route 1 from the Z Fold 8's save. On the Z Flip 7 (Xclipse), played by hand from a new game through the opening into the bedroom. Sound (confirmed by audio dumps), a save made on the phone and Continue work on all three. Not tried: aiming with motion, trainer battles, the other devices |
| Divinity: Original Sin 2 - Definitive Edition 1.0.3.1 | Ayn Odin 2, OnePlus Pad 3 | Playable through the first combat: the game's 30 fps from a new game through character creation and the opening cinematic into the Merryweather's hold, then by hand to the cabin deck, and on the Odin 2 from a save made there through the burning hold to the top deck, where the first fight (two Voidwoken, turn-based) was won with the Red Prince's skills at 30 fps, with sound, Quick Save and the save loaded again. Continue can load an older save, as every save's time reads 31/12/1969 (Load lists them by name). On the Pad 3 it runs at 40 or 60 fps with a setting, the game moving by real time at each, and held 60 for 25 minutes ([its note](dm/games/010027400CDC6000/README.md#frame-rate)). Not played as far as Fort Joy |
| The Legend of Zelda: Breath of the Wild 1.9.0 | Ayn Odin 2, OnePlus Pad 3, Samsung Galaxy S25 Edge, Samsung Galaxy Z Fold 8 | In-game: Link standing in the Shrine of Resurrection from a save made on the Mac, not yet outdoors on Android: 30 fps on the Odin 2, the Pad 3 and the S25 Edge with its Android defaults (descriptor sets bound again, the command recorder, a 30 fps target); 24 on the Galaxy Z Fold 8, whose GPU takes 30 ms a frame. On the Pad 3 it lost the GPU at its first frame in the field, and on both Adreno 830s it drew the Shrine dark: both are fixed (the picture checked on the S25 Edge; on the Pad 3 only in a local test). 60 fps needs the replay's CPU time and the GPU's to come down |
| Persona 3 Portable 1.0.2 | Samsung Galaxy S25 Edge, Samsung Galaxy Z Flip 7 | Playable through the first battle (April 9's rooftop): 60 fps (as on the Switch) on both, played by hand from a new game through the opening, the dorm and the first school days with their point-and-click exploration, to the night of April 9 and its first battle, won with the buttons, with sound, a save made at the dorm's Sign-In Sheet and Continue working. On the S25 Edge in console mode, on the Z Flip 7 (Xclipse) in Android's default handheld mode, which works on both ([its note](dm/games/0100DCD01525A000/README.md#android)). Not played past the first battle (Tartarus); not tried on the other devices |
| SHIN MEGAMI TENSEI V: Vengeance 1.0.3 | Samsung Galaxy S25 Ultra | In-game (contributor report): a save in Mita at 30 fps, and at 60 with `DM_UE_DYNRES_BUDGET=16.7` ([its note](dm/games/010069C01AB82000/README.md#frame-rate)). Not run on the project's devices |
| Super Mario Bros. Wonder 1.2.1 | POCO X5 5G (Adreno 619) | In-game: about 30 fps of the game's 60 at render scale 0.8, in levels and on the world map; below 60 fps Piranha Plants on Parade softlocks unless the stopgap `DM_AUDIO_PACE=game` is on ([audio](docs/reference/audio.md#music-timed-sequences-on-a-device-below-the-games-frame-rate)) † |
| Super Mario 3D World + Bowser's Fury 1.2.2 | POCO X5 5G | Menus: Bowser's Fury starts and is drawn with correct colours; how far it was played isn't recorded, and one launch stopped at a black loading screen † |
| Danganronpa V3 Anniversary Edition 1.0.2 | POCO X5 5G | Menus: boots, plays its opening movie and draws its picture, from a provisional profile; not played through † |
| The Binding of Isaac: Afterbirth+ 1.7.9b | POCO X5 5G | Boots: runs from a provisional profile with its Repentance DLC, its shaders compiled at run time and captured on the phone; how far it got isn't recorded † |
| **Mario Kart World 1.8.0 (Switch 2)** | Ayn Odin 2 | **Menus** (2026-11-08, not run since): the world map at about 55 fps, then the attract drive at about 3.4 fps, with no input given. Open: sparse textures (the terrain is untextured), virtual memory pools, constant-buffer copies in the replay, no mesh shaders on the device |
| **The Legend of Zelda: Ocarina of Time v131072 (Switch 2)** | Samsung Galaxy Z Fold 8 | **In-game, blocked:** the title at about 30 fps (the movie behind the logo black), the Load screen, and Kokiri Forest from a Mac save at about 1.7 fps with the forest black: 2,247 of the game's shaders read raw global memory, which the Vulkan replay doesn't have yet. Open: raw global memory, then the CPU's 460 ms a frame and the memory (10.2 GB of the phone's 11.3) |

† Tested before DroidPlay Core merged nxnative's `main` (2026-11-08); not run since. "Not run since" with a date marks a later run on code `main` has moved on
from, and "contributor report" a run on a contributor's own device.

The rows for the first six games, Final Fantasy Resonance and Breath of the Wild are from the [Android baselines](dm/android/baselines.md): the same scripted runs on
each device, with frame times, the devices' drivers, and the known problems with what is known of their causes. The first were measured on 2026-11-08 on the Odin
2, the Pad 3 and the Retroid Pocket 5. On 2026-11-10 the Galaxy S25 Edge's column and the rows for Final Fantasy Resonance and Breath of the Wild were added, and
the Retroid Pocket 5's rows were measured again; Ocarina of Time on the Galaxy Z Fold 8 and Super Mario Odyssey on the Pixel 9 Pro XL have sections of their own
there; cells measured again since are dated (Smash's battles, Link's Awakening's Ancient Ruins, Skyward Sword HD's Skyloft). The other rows are
from the games' own notes, which the [games table](dm/games/README.md#games) links, but for three: SHIN MEGAMI TENSEI V: Vengeance's device is named in its
contributor's pull request ([#101](https://github.com/enjoyerofslop/droidplay-core/pull/101)), Mario Kart World's run of 2026-11-08 is not in its note yet, and
the POCO X5 5G rows are from the original port's README.

Every other game in the [games table](dm/games/README.md#games) has a profile and can be packed the same way, but has not been run on Android. A game without a
profile can still be packed as an *experimental build*: most likely it does not boot, but it is the starting point for porting it.

The Android host replays NVN only. A game that draws with OpenGL or makes its own Vulkan calls (OpenGL or Vulkan in the games table's Graphics column) cannot
draw on Android, since the OpenGL and Vulkan layers are the Mac's, on Metal: Balatro, Digimon Story Cyber Sleuth, Street Fighter 30th Anniversary Collection and
Well Dweller (OpenGL), and Hades and both Super Mario Galaxy games (Vulkan). The packing script stops on such a game and says why, before the rewrite and the
shaders. Super Mario 3D All-Stars still builds, since its launcher draws with NVN, but Super Mario 64 and Sunshine inside it call Vulkan and cannot draw.
The games the script refuses are in the Doesn't run tier. Street Fighter 30th Anniversary Collection stopped at its first EGL call on a Retroid Pocket 5
before the script refused it ([its note](dm/games/0100024008310000/README.md#android)).

## Testing and reporting

Help with packing and playing, and reports of how a game runs on your device, go to the [DroidPlay Discord](https://discord.gg/4wNHX3uqSU): #help
for a problem, #compatibility for a game. Its rules are this README's: no games, keys, firmware or packed APKs.

Testers and contributors are welcome. Useful reports name the device and its GPU (Settings, or `adb shell getprop ro.product.model`), Android version, the game,
its title ID and version, how it was packed (DroidPlay, the command line, game app or launcher), and attach the log: `adb logcat -s DroidPlay` (`-s nxnative` for an app older than 0.5.0), or `log.txt` in the
app's folder (`Android/data/<package>/files/`). A screenshot and the first `[RED]` lines help most. Never attach game files or keys. How changes get in, and how
DroidPlay Core stays in step with nxnative: [CONTRIBUTING.md](CONTRIBUTING.md#droidplay-core).

## How it fits together

```
 Your computer (Windows, macOS or Linux)                         Your Android phone
 ───────────────────────────────────────                         ─────────────────────────────────────
 NSP / XCI files + prod.keys                                     DroidPlay app (org.nxnative.android)
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
  On Windows, use Python 3.14 and set `PYTHONUTF8=1` for the command line (the desktop app sets it for what it runs): the scripts read and write text as UTF-8,
  which Python on Windows does by default only from 3.15, and lz4 has no Windows build for 3.15 yet.
- **On the phone:** USB debugging (or wireless debugging) turned on, so that `adb devices` lists the phone, and room for the game: its RomFS is copied as one image
  (Danganronpa V3's is 6.7 GB).

## The desktop app

`uv run scripts/nxnative_android.py` opens a window that drives the packing script and adb for you ([uv](https://docs.astral.sh/uv/) brings Python and the
modules the script names at its top; `python scripts/nxnative_android.py` works too, with them installed).

**On Windows**, from nothing:

1. Download **DroidPlay-Setup-&lt;version&gt;.exe** from the [latest release](https://github.com/enjoyerofslop/droidplay-core/releases/latest) and run it. Windows
   warns that it comes from the internet and isn't signed: **More info**, then **Run anyway**.
   - It installs DroidPlay for you only, in `%LOCALAPPDATA%\Programs\DroidPlay`, with no administrator prompt and nothing more to download: its own Python with
     the app's modules, and DroidPlay Core (Setup is about 80 MB, 600 MB installed). Each Setup has a `.sha256` beside it on the release page.
   - DroidPlay is then in the Start menu, on the desktop, and in **Settings › Apps**, which uninstalls it. Your games and their builds, the Android SDK, the
     tools and your settings stay.
   - DroidPlay says when a newer release is out, and **Update** installs it: DroidPlay downloads the new Setup, checks it against the release, runs it
     (a small Updating DroidPlay window shows its progress) and opens again. Or close DroidPlay and run the new Setup yourself.
   - **Coming from Install DroidPlay.cmd?** Close DroidPlay and run Setup: it moves your DroidPlay over and removes the copy the .cmd installed, and keeps your
     games, builds and settings. `Install DroidPlay.cmd uninstall` still removes such a copy by hand (`dm/android/windows/install_droidplay.cmd`).
   - Or from source: install [uv](https://docs.astral.sh/uv/) (`powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`), get
     DroidPlay Core (`git clone https://github.com/enjoyerofslop/droidplay-core`) and, in its folder, `uv run scripts\nxnative_android.py`.
2. DroidPlay opens on **Get started**: four steps, each saying what it needs and whether it's done. Setting up takes about half an hour the first time.
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
<td align="center" valign="top" width="36%"><img src="docs/images/windows/phone-setup.png" alt="DroidPlay for Windows' Set up your phone guide for a Samsung Galaxy: Build number, Auto Blocker, USB debugging and Allow, with the phone waiting for Allow at its foot"><br><small><b>Set up my phone</b>: the steps for your phone's brand</small></td>
<td align="center" valign="top" width="64%"><img src="docs/images/windows/build.png" alt="DroidPlay for Windows' Builds page part-way through building Pokémon Brilliant Diamond: four stages done, the shaders for Vulkan translating, with the time left"><br><small><b>Builds</b>: a first build part-way, its stages and the time left</small></td>
</tr>
</table>

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
- **Settings:** your `prod.keys`, and the requirements above with how to install what is missing (on Windows, **Install what's missing** does it).

A rebuild only does what changed: the extraction, the rewritten code and the translated shaders are reused when their inputs are the same, and the RomFS image is not
copied to the phone again when the phone already holds the same one.

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

## Another Vulkan driver (Turnip)

On a phone with an Adreno GPU, a game can run on a Vulkan driver you put on the phone instead of the system's, as in Switch emulators: usually a build of Mesa's
open-source Turnip driver, such as [Mr. Purple's](https://github.com/MrPurple666/purple-turnip/releases). The app carries what loads it
([libadrenotools](dm/third_party/libadrenotools/README.md)), so trying one needs no new build:

1. Unzip the driver package (`turnip_mrpurple_T30-toasted.adpkg.zip`, say). It holds a `.so` (`vulkan.purple.so`) and a `meta.json` that names it.
2. Copy the `.so` into `Android/data/org.nxnative.android/files/`, beside `env.txt`: `adb push vulkan.purple.so /sdcard/Android/data/org.nxnative.android/files/`.
   A game app reads its own folder, `Android/data/org.nxnative.game.t<title ID>/files/`.
3. Add `DM_VK_DRIVER=vulkan.purple.so` to `env.txt` there (a path relative to that folder, or an absolute one), then start the game.

The app copies the driver into its internal storage at start, since Android loads no code from shared storage, and copies it again when the file changes. The log
names the driver that runs: `[vk] driver: … (DM_VK_DRIVER, through libadrenotools), not the system's: PurpleVK-public Adreno (TM) 740 …`. A driver that can't run
(a wrong path, a build for another GPU) gets one `[RED] [vk] DM_VK_DRIVER …` line saying why, and the game runs on the system's driver. Remove the line from `env.txt`
(or start it with `#`) to go back. Each driver keeps its own pipeline cache, so the first start on a new driver compiles the game's pipelines again (it can take a
minute to the first frame, and it stutters until they are built), and the system driver's cache is still there afterwards.

Whether a driver helps depends on the game and the device. With Mr. Purple's T30, Super Mario Odyssey's opening runs at 60 fps on an Odin 2 (as on its own driver)
and at 40 fps on a Retroid Pocket 5 (38 on its own); Pokémon Brilliant Diamond's Eterna City runs at 58 fps on a Retroid Pocket 5 with
Turnip (15 on its own driver), and at 60 fps on an Odin 2, as on its own driver.

## Packing from the command line

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

Play your own Nintendo Switch and Switch 2 games natively on Apple silicon Macs, iPhone and iPad. One script packs your game into a Mac app or an unsigned IPA that you sideload.

It is not an emulator: the game's own code runs directly on the Apple chip, with Switch graphics rebuilt on Metal. Nothing from any game is in this repository, and the project is not affiliated with Nintendo or any game publisher.

[Games](#games) · [Community front ends](#community-front-ends) · [Requirements](#requirements) · [How to play](#how-to-play) · [Discussions](#discussions) · [For developers](#for-developers)

## Games

The full [tested games table](dm/games/README.md#games) includes original Switch games, tested builds, engines and graphics APIs. Each game's note records its tested platforms, progress and known issues.

These Switch 2 games have passed Mac gameplay testing. Build them from a [`.nup` file or a dump folder](#switch-2-games):

- [Donkey Kong Bananza](dm/games/040074A01BF12000/README.md)
- [Fire Emblem Fortune's Weave](dm/games/04007EF01F8AE000/README.md) — up to 120 fps
- [Hyrule Warriors: Age of Imprisonment](dm/games/04003F40232DE000/README.md)
- [Kirby Air Riders](dm/games/040077201BE50000/README.md)
- [Mario Kart World](dm/games/0400C3F00006E000/README.md)
- [Mario Tennis Fever](dm/games/0400D4201C6EA000/README.md)
- [Pokémon Pokopia](dm/games/0400A3A01EE4C000/README.md)
- [Splatoon Raiders](dm/games/0400380020056000/README.md)
- [Star Fox](dm/games/0400E88025B1A000/README.md)
- [The Legend of Zelda: Ocarina of Time](dm/games/0400486024DEC000/README.md)
- [Yoshi and the Mysterious Book](dm/games/0400245021D2C000/README.md)

## Community front ends

Community projects build on nxnative with tools to turn your games into apps for your iPhone, iPad or Mac without the command line, and libraries to organize and launch them. They are separate projects: questions and bugs about them go to their own pages.

- [NX2Apple](https://github.com/LNPANDY/NX2Apple) — Mac builder with a shared iPhone/iPad game library.
- [NX Play](https://github.com/varyform/nx-native-wrapper) — Mac library with device installs and save sync.
- [NxNative Launcher](https://github.com/rennan101/nxnative_Launcher) — Mac launcher with guided builds and controller mapping.
- [LumaNX](https://github.com/Xc1Ym/LumaNX) — Mac game builder with IPA export.
- [GameCase](https://github.com/Tiaoge-tou/GameCase) — iOS game library based on LiveContainer.

## Requirements

- **Mac:** Apple silicon, macOS 26.6 or later. Building games requires Xcode 27.2.
- **iPhone:** A17 Pro chip or later, with iOS 26 or later.
- **iPad:** M1 chip or later, with iPadOS 26 or later.

The games' textures are BC-compressed, which older iPhones cannot read. Switch 2 builds are tested on the Mac; check each game's note for device-specific validation.

For a game without a profile, the script writes a survey and tries a provisional build with guessed settings. That build may not start; see [Port another game](docs/development.md#port-another-game).

## How to play

Switch 2 games are built from one `.nup` file or a folder of their files, not from NSPs, and are tested on the Mac only: see [Switch 2 games](#switch-2-games).

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

**Android.** To play on an Android phone instead, see [the top of this page](#droidplay-core): a desktop app packs the game and installs it on the phone.

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

[Hyrule Warriors: Age of Imprisonment](dm/games/04003F40232DE000/README.md) is played this way: its 47 GB NUP unpacks in under five minutes. A NUP that carries the game's control data (its NACP) and icon gives the app the game's name and icon; otherwise the name comes from the game's profile and the app has no icon unless you give it one with `--icon <image>` (`ICON` in Spyder; a JPEG or PNG of any size).

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

An update's folder alone will do (no `base/`), and so will `exefs/` and `romfs/` directly in the folder, as `nup extract` writes them, which count as `base/`. The app has no icon, because the folder holds none; `--icon <image>` (`ICON` in Spyder) gives it one. To turn such a folder into a NUP: `nup pack ~/Games/DonkeyKongBananza game.nup`.

## Discussions

Questions, how a game runs on your Mac or iPhone, and ideas go in [Discussions](https://github.com/seedds/nxnative/discussions); [Issues](https://github.com/seedds/nxnative/issues) are for bugs, with the log. Ocarina of Time's performance (frame rate, resolution, which Macs hold 60 fps) is followed in [Ocarina of Time: state on main](https://github.com/seedds/nxnative/discussions/1789).

## For developers

[How it works](docs/development.md) · [Game notes](dm/games/README.md#games) · [Bring-up and debugging](docs/agents/README.md) · [Front ends](docs/frontends.md) · [Contributing](CONTRIBUTING.md)

## Acknowledgements

This project is built on other people's work ([licenses](dm/third_party/README.md)):

- **[d2r-mobile](https://github.com/jhaizhou-ops/d2r-mobile)** (MIT) developed this native-execution approach, for Diablo II: Resurrected. nxnative started as a copy of its generic parts: the NSO rewriter, the host that stands in for Horizon, the NVN-on-Metal layer and the iOS app shell. Fixes go both ways.
- **Ryujinx** (MIT): its shader translator (`Ryujinx.Graphics.Shader`, `Ryujinx.Common` and `Spv.Generator` 1.3.2, in `dm/third_party/ryujinx` with a few fixes listed in [its README](dm/third_party/ryujinx/README.md)) turns the games' shaders into SPIR-V. Its emulation of the kernel and system services is also a reference when the host's behaviour is in doubt.
- **[Atmosphère](https://github.com/Atmosphere-NX/Atmosphere)**: its kernel, mesosphère, is the reference for Horizon's synchronization semantics (address arbiter, condition variables).
- **[LibHac](https://github.com/Thealexbarney/LibHac)**: reads NSPs and layers updates over the base game in `dm/tools/nx_extract`.
- **[SPIRV-Cross](https://github.com/KhronosGroup/SPIRV-Cross)**: SPIR-V to Metal Shading Language.
- **[glslang](https://github.com/KhronosGroup/glslang)** compiles the GLSL of OpenGL games to SPIR-V for it.
- **[MacNativeGames](https://github.com/ly05010419/MacNativeGames)** (MIT): the GPU widening of 8-bit indices and in-pass clears in `dm/gfx/nvn/nvn_mtl.m`, and the visibility-counter lowering in the shader translator.

## License

MIT ([LICENSE](LICENSE)). Third-party code keeps its own license ([dm/third_party](dm/third_party/README.md)).
