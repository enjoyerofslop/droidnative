# Divinity: Original Sin 2 - Definitive Edition (`010027400CDC6000`)

Update 1.0.3.1 (v196608) over the base game, SDK 8.2.0. Larian Studios' Divinity Engine (`FW3.5/Gold/Stable` in its asserts' paths), NVN, Wwise sound, RakNet 15.03.26. Modules `main`, `subsdk0` and `sdk`: `subsdk0` and `sdk` are one build (`3ae34e68…`), the SDK twice. The RomFS is 48 files, 10.74 GB: Larian's LSPK packages (`Data/*.pak`, version 13), the voice and localization packages beside them.

Status: brought up on Android, on an Ayn Odin 2 (Adreno 740, Android 13). The title, the main menu, a new game (Classic mode), character creation, the opening cinematic and the first area (the Merryweather's hold, Magister Siwan's first dialogue) in play, at the game's 30 fps, and on a OnePlus Pad 3 the cabin deck after it ([First area](#first-area)); from there, on the Odin 2 by hand, the burning hold, the top deck and its first fight, won ([To the first combat](#to-the-first-combat)). Not yet played further than that; see [Open](#open).

## What it needs

| Setting | Where | Why |
|---|---|---|
| `net_loopback on` | [`game.tsv`](game.tsv), `hle_loopback.c` | single player is a RakNet server and a client in one process; without UDP on 127.0.0.1 a new game waits forever at the loading screen. See [New game](#new-game) |
| `modules main subsdk0 sdk`, `mem_reserve 0x140000000`, `mem_alias 0x60000000`, `mem_stack 0x10000000`, `app_pool 0xCD500000`, `sys_resource 0x400000`, `depth_mode zero` | `game.tsv` | the provisional profile's values from the survey and the Mac's heap check (a 2.96 GB heap); kept as they were |
| LSPK packages read by the shader split | `dm/gfx/tools/shader_split.py` `lspk_shaders` | the shaders are in the `.bshd` files of `Data/*.pak`: 11,578 of them, where a plain scan found `main`'s 73 and every frame was black ([shaders](../../../docs/reference/shaders.md)) |
| `DM_VK_SET_REUSE=1` | [`android_defaults.txt`](android_defaults.txt) | Android: descriptor sets bound again within a chunk; 2–3% of the replay's CPU time on the Pad 3, the picture the same (the file says what was measured) |

## New game

- **Resolved: New Game waited at the loading screen forever** (2026-11-10). The loading screen drew and its tips changed at 30 fps, with an empty progress bar, on the Odin, the Pad 3 and the Mac alike. The last files opened were the story's: `story_generated.div.osi` looked for in every mod and not found, then `Data/Patch1_Gold.pak`.
  - Every thread was idle or polling (`files/threads_now` on Android). The client's `GameThread` (`main+0x341350`) ran its frame handshake with the render thread, waiting 1 ms at a time on a light event (`main+0x39f40`); the `ServerWorker thread` ticked its own loop (`main+0x4f0ca0`) about 25 times a second.
  - The game state names are in two tables, the client's `ecl::EGameState` at `main+0x29d6dc0` (0 Unknown … 23 StartLoading, 25 StartServer) and the server's `esv::EGameState` at `main+0x2a170c0` (8 LoadSession, 12 Sync, 14 Running). Probes on the swap logs (`DM_PROBE=main:53fe0c,main:d17478` on the Mac, x4 and x5 the from and to names) showed the server go Init → LoadModule → LoadSession and stay there, and the client wait in StartServer.
  - LoadSession (`esv::GameStateLoadSession`, vtable `main+0x2a1c558`) runs its load on a thread, `ServerLoadSession` (`main+0xdb8220`, thread wrapper `main+0x37c90`), and its update (`main+0xdba8a0`) waits for the task's status 3. The thread ended normally (`Server Thread ended: ServerLoadSession`, status 3 set at `main+0x380d0`), so the load itself was fine.
  - The cause was the network: when the server starts, its RakNet peer (`main+0x1adc06c`, from `RakPeer.cpp`) calls `nn::socket::Socket(AF_INET, SOCK_DGRAM, 0)` twice, and the host failed every socket call. A Switch with no network still has loopback, which is how the game plays offline there.
  - Fix: `net_loopback` ([Loopback UDP needs no network](../../../docs/reference/services.md#loopback-udp-needs-no-network)). Both state machines then go on to Running: the server LoadSession → LoadLevel → Sync → Running, the client InitNetwork → InitConnection → … → SwapLevel → PrepareRunning → Running. Character creation loads 11 s after Begin on the Odin.
  - The peer opens one socket and sends one datagram, 4 bytes to itself, as it binds; the client and the server talk in process, not over UDP. Two RakNet threads run from then on: `Raknet#0` waits in `RecvFrom`, `Raknet#1` on a condition variable.
- **The route there:** Press A at the title; a Steam cross-save question comes on a fresh save (B, No: the answer is saved); Story; Single player; a difficulty (Classic is the default); Begin. `DM_KEYS=32:A,36:B,39:A,42:A,45:A,48:A,51:A` reaches the Begin press on the Odin from a launch with the save that answered the question (B at the main menu does nothing).

## Character creation

- Draws right, at 30 fps: GPU 7.5 ms a frame, 676 draws (Odin).
- **Its first tutorial box takes a held A.** A press of 150 ms (`DM_KEYS`, or adb's gamepad events) or 0.5 s does nothing there: the box stays, and no other button does anything either. A held for 1 s (`A~1.0`) closes it, and short presses work normally after that (Right changes the origin, B opens the main menu question). Seen the same in handheld and in console mode; the game reads player 1's state every frame there (`GetNpadState`, `main+0xdccc4`). Not looked into further.
- Start Game is Plus, then A on the confirmation.

## First area

- The opening cinematic (painted, narrated) plays through, then the Merryweather's hold with Magister Siwan's first dialogue. 30 fps (frame time p50 33.3 ms, p95 35.2), GPU 6.1 ms a frame, 331 draws, 1.5 GB resident in the replay (Odin).
- `DM_KEYS=32:A,36:B,39:A,42:A,45:A,48:A,51:A,70:A~1.0,76:PLUS,82:A` reaches it in about 2 minutes 30 s; the `tohold` route below does the same from a fresh save.
- Quick Save (Plus, then A) writes `Save0000/Save0000.lsv` and its thumbnail; Continue loads it again (`hold` below). The game dates each save by the network clock. Until the host answered it (`hle_time.c`), every save read 18:00:02 31/12/1969, so with several saves Continue loaded an older one; a save made on the Odin 2 after the fix reads its real date and time, and Continue loads it ([services](../../../docs/reference/services.md#time-zone-rules-calendar-conversion-and-the-network-clock)). The game autosaves on its own a few seconds into play.

- Walked by hand (2026-11-10, adb joystick events): the left stick moves the character with the camera following; the stairs at the hold's west end lead up a level to a doorway blocked by a toppled crate, the tutorial's Move puzzle (X on the crate opens the Action Menu: Pick Up, Open, Move, Attack, Examine; Pick Up clears it). The ladder in the room below asks whether to leave the Tutorial Deck; Yes loads the next level in about 25 s: the cabin deck, where Magister Siwan's dialogue moves the quest on (narrator lines, ambient remarks). 30 fps there too: frame time p50 33.3 / p95 33.8 ms, GPU 8.7 ms, 798 draws, submit 13.8 ms of CPU a frame. The way on from there to the top deck and its first fight is in [To the first combat](#to-the-first-combat). Holding the left stick in (L3) for 1 s on a tutorial box hides tutorials for the profile.
- Sound plays: Wwise mixes into AudioOut #0 (6 channels, `main+0x1bd3050`), which carries signal throughout (`DM_AUDIO_DUMP`); the audio renderer the game also opens (`main+0x162c988`) is nearly silent (436 of 24,000 frames), which is expected of it here.

## To the first combat

Played by hand on the Ayn Odin 2 from `saves/cabin` (2026-11-10, adb joystick and button events, tutorials hidden):

- Magister Payde's dialogue ("Here to register…") unlocks the stern room. Below it the Windego scene starts a turn-based fight that the scene itself ends on the enemies' turn, with no move of the player's. After it the hold burns, and the stern room's stairs come up to a deck of fires.
- The fires set whoever stands in them Burning, a few points a turn; walking into them killed the Red Prince twice (Game Over, then Load Game). Water barrels (X, then Attack) and the Water Balloon on the hotbar put them out, and Wet keeps Burning off for two turns.
- The Skull-Marked Door is not the way. Its key is on Magister Priest Medwyn's body, at the foot of the stairs up to Fane, and the door warns of Deathfog inside: its dialogue offers to pull it open or let go. Fane talks but leads nowhere further.
- The way on: from the main deck's port railing, step down onto the lower walkway beside it (a gap among fallen planks, near minimap x:41 y:-191). Walk it forward to the stairs that climb through the arch left of the Skull-Marked Door (an autosave fires there), then use the Stairs at the top (A). The top deck loads and the first fight starts at once.
- The fight: two Viscous Voidlings, turn-based, the Red Prince first. Dragon's Blaze (Y for the hotbar, the stick to aim its cone) set both of them and the deck's poison alight. Decaying Touch (R cycles its target) and plain attacks finished them in four rounds, with Restoration healing him once. The turn order, action points, targeting, damage numbers and surfaces all worked.
- 30 fps throughout, the fight included. Over the whole session (514 windows of 300 frames, about 85 minutes) the median frame time stayed between 33.1 and 33.5 ms, with a p95 median of 35.8 ms. On the top deck: GPU p50 about 16 ms, 1,677 draws and 24.5 ms of submit CPU a frame. The longest frames (125–380 ms) came at level loads and saves. In all, 1,420 draws were left out while the new areas' pipelines built in the background (`[vk] draws not made: … pipeline 1420`).
- Quick Save on the top deck after the fight (`QuickSave_1`, in-game Day 1 14:55), then Main Menu and Load: the pause menu's Load, or Story → Load campaign. It loads again where it was. Continue loaded an older save instead, since every save then read 18:00:02 31/12/1969; the network clock's answer fixed that ([First area](#first-area)).
- Sound: a 4-minute `DM_AUDIO_DUMP` from the title through loading that save. L and R about −35 dBFS, centre and LFE silent, the rear pair about −70 dBFS, no clipping, spectra like music (flatness 0.00–0.02, peaks on notes), and 0 underruns.

## Routes

[`bench_android.tsv`](bench_android.tsv), for `scripts/bench_android.py`:

- `tohold`: a fresh save through New Game, character creation, the opening cinematic and Magister Siwan's first lines, then Quick Save in the hold at about 205 s. With `--keep-save <game folder>/saves/hold` it makes the save `hold` starts from (`Story - QuickSave_0`, 3.7 MB).
- `hold`: Continue from that save (in the hold 6 s after the press), a short walk, then idling; measured from 96 s for 30 s. Odin 2, warm-up and 2 runs (2026-11-10): 30.0 fps, frame p50 33.3 / p95 33.9 / p99 34.2 ms, GPU 5.9 ms, PSS 1.38 GB, the same in all three.
- `long`: the hold from the same save for 25 minutes, walking up and down every 20 s, for slowdowns that build up over time.
- `walk`: the hold from the same save, the left stick down for 1 s at 84 s (and right at 95 s, which a camera tutorial box stops); where the first walk ends, in the shot at 90 s, shows whether the game moves by time or by frames.
- `cc`: a fresh save into character creation, for profiles of the title screen, the main menu and character creation.
- `saves/cabin` (not a route yet): a Quick Save on the cabin deck next to the murder room, past Magister Siwan's second dialogue, made by hand on the Pad 3; the way to the top deck from there is in [To the first combat](#to-the-first-combat).
- `saves/combat` (not a route yet): the save folder from the Odin 2 after the first fight. Load `QuickSave_1` by name for the top deck beside the two Voidlings; Continue picks another save.

## Frame rate

Measured on a OnePlus Pad 3 (Adreno 830, Android 16; its 144 Hz panel runs Divinity at 60 Hz), 2026-11-10, for issue #113:

- **40 fps: `DM_PRESENT_HZ=80`** (`env.txt`). The host paces the game's interval 2 in ticks of the present rate, so 80 Hz gives 25 ms frames: 40.0 fps in the hold, frame p50 25.0 / p95 26.4–29.7 ms, GPU 10.1 ms. `DM_FPS_TARGET` does not do it: it takes 30, 60 or 120, and needs a frame step or an engine limiter the host writes, which this game has neither of. On a 60 Hz display 40 fps comes out uneven, each frame on screen for 16.7 or 33.3 ms in turn (64 and 61 of 126 in `dumpsys SurfaceFlinger --latency`); an even 40 needs the display at 120 Hz, which the Pad 3 kept from it.
- **Uncapped: `DM_PRESENT_INTERVAL=display`**, one frame per 60 Hz tick: 60 fps in the hold, frame p50 16.7 / p95 19.4–20.0 ms, GPU 8.3–10 ms. The front end's FIFO present holds the game's frame, so 60 Hz is the ceiling even with `DM_PRESENT_HZ=0`.
- **The game moves by the time that really passed:** after the `walk` route's 1 s walk the character stands at the same spot at 30, 40 and 60 fps (minimap x:5 y:-304 in each), and the ambient line at 75 s comes at the same time.
- **The display's cadence:** at 60 fps every frame stays 16.7 ms (124 of 124); at 30 fps 122 of 126 stay 33.3 ms, with two 16.7 + 50 ms pairs in about 4 s, as the host's 33.3 ms grid is not tied to the display's vsync.
- **25 minutes uncapped (`long`):** 60.0 fps in every minute; GPU p50 9.9 ms falling to 6.2 ms, the replay 6.5–7.7 ms of CPU a frame, 378 draws, resident 1.55–1.56 GB, thermal status 0 and the display at 60 Hz throughout, the battery 28.6 → 29.1 °C. Nothing built up; frames over 25 ms went from none to 15–30 a minute after 20 minutes (p99 21 → 24.5 ms), all minutes still at 60.0.
- **`DM_VK_SET_REUSE=1`** in the hold, uncapped, two runs each in turn: the replay 7.5–7.7 ms of CPU a frame instead of 7.6–7.9, about 420 draws; 60 fps both ways.
- **The log** writes about a dozen timing lines every 10 s in play (and a line per long frame); the benches' tens of thousands of lines are their own `DM_FS=1` file-open lines.

- 30 fps, the game's own: it asks for present interval 2 (`WindowInitialize swap chain 2 textures, interval 2`), at 1600x900 cropped to 1280x720 in handheld mode.

## Shadows

- **`DM_VK_SKIP_SHADOWS=1` leaves the shadows out** (`env.txt`; off by default), for a cheaper frame on a slower phone: the profile's `vk_shadow_rt square512` names the game's shadow maps, and the replay drops the draws of depth-only passes on a square target of 512 or more (`gfx_vk_shadow.inc`). The game's own clears of the map still run, so every lookup reads "nothing in front" and the scene is lit throughout. A tester asked for it (issue #113): their own patch, which left out square depth passes of 512 or more, ran Fort Joy faster on an Adreno 735, with the battery under 40 °C instead of 47 °C.
- **Where the game draws them:** a 1536x1536 D16 map (`vk124`), with one empty colour slot beside it: on the title screen and the main menu behind it about 970 draws a frame in four passes, in character creation about 200; the hold and the cabin deck, lit by lanterns below deck, draw none (pass profiles, `files/prof_now`). Fort Joy's maps are not measured yet: with the switch on, the log's `shadow map … set as the target` lines name each shape caught.
- **Measured on the title screen** (`boot`, uncapped with `DM_PRESENT_INTERVAL=display`, OnePlus Pad 3, Adreno 830, two runs each in turn, 2026-11-10): the shadow passes are 915 of the frame's 2,094 draws and 3.4 ms of its 11.4–11.6 ms of pass time on the GPU (one profiled frame each). Left out: 1,123–1,132 draws a frame, the replay's CPU time 8.6–9.0 ms a frame instead of 10.0–10.4, GPU p50 9.75–9.9 ms instead of 10.2–10.5; 60 fps both ways (the display's rate). Every surface is lit instead of shaded; nothing else in the picture changed.

## Open

- On a cold pipeline cache, 25 draws of a new game's first minutes are left out while their pipelines build in the background (`[vk] draws not made: … pipeline 25`, `pipeline built in the background … draws left out meanwhile`); with the cache warm, `hold` leaves out none.
- `[nvn] [RED] SetRenderEnableConditional: the host draws anyway for now`, from the title on.
- Further into the game (past the first fight, Fort Joy) is not played yet.
