# Pokémon: Let's Go, Pikachu! (010003F003A34000): the rewriter's patches of this game's own builds. dm/tools/patch_nso.py loads every profile's patches.py; FRAME_STEP as described
# there ("Frame step in whole vsyncs")
from nso_asm import ADRP, B

# 60 fps (30 on the Switch) on 1.0.0 (v0) main, with game time at real time. The engine is Arceus's older sibling: the same frame-time object, read through the same getter, and here the
# present interval comes from that period too, so one stub moves both to the host's frame step:
# - The frame period. The game steps its time by a stored period, not by the clock: the frame-time object (built at main+0x38b84 inside its owner, owner +0x110, vtable main+0x1529968)
#   holds two {0, ns} pairs, both 33,333,334 ns from the table {16,666,667, 33,333,334, 50,000,000, 66,666,667, 83,333,334} at main+0xf7eeb8 (GOT main+0x15fb438). Its interface
#   [0] main+0x395f0 returns the address of pair idx, [1] main+0x39600 sets a pair from the table, [2] main+0x39620 sets a pair's ns, [3] main+0x39630 returns the pair count (2).
#   The game's updates read pair 1 and turn it into seconds (main+0x5fc338, main+0x655574, main+0x687584 and the others the getter's 11 such callers have); the present reads pair 0
# - The present interval. The present (main+0x29d30, once a frame) reads pair 0 and hands clamp(period / 16,666,666, 1, 5) to main+0x358b0 → main+0x5e7960, which calls
#   nvnWindowSetPresentInterval when it differs from nvnWindowGetPresentInterval: 33,333,334 ns is interval 2. A byte at owner +0x659d skips the read and asks for interval 0 (no
#   vsync); only the owner's constructor writes it (main+0x28924, cleared with +0x659c), so the retail game never takes that path
# The stub in the getter stores the host's step (the vsyncs the frame stays on screen, state page +0x20) times 16,666,667 ns in the pair asked for, before the caller reads it: 60 fps
# steps 1/60 s and asks for interval 1, 30 fps (target 30, heat, a movie, late frames) 1/30 s and interval 2. Before the host has decided a step, and at target 0, the stored period
# stays: the game's own interval 2 and step, 30 fps as on the Switch. The getter is in this vtable only. x16 and x17: dead in a function entered through blr
# The second stub counts the vsyncs stepped where the present reads pair 0 (main+0x29e80), for the host's game time log; it replaces the adrp x8 there and makes it again after,
# so x8 is free in it
def frame_step(ctx):
    here, emit, fs_site, fs_put, FS_STATE_OFF = ctx.here, ctx.emit, ctx.site, ctx.put, ctx.state
    fs_site(0x395f0, '08d0218b00210091c0035fd6')
    start = here(); emit(0x8b21d008)                                 # add x8,x0,w1,sxtw #4   (original)
    emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400211,   # ldr w17,[x16]          target fps (float bits; 0 = off)
              0x340000f1,   # cbz w17,back (+7)
              0xb9402211,   # ldr w17,[x16,#0x20]    step in vsyncs
              0x340000b1,   # cbz w17,back (+5)      not decided yet
              0x528a0570,   # mov w16,#0x502b
              0x72a01fd0,   # movk w16,#0xfe,lsl #16 16,666,667 ns
              0x9bb07e31,   # umull x17,w17,w16
              0xf9000911):  # str x17,[x8,#0x10]     the pair's ns
        emit(w)
    emit(B(here(), 0x395f4))                                         # back: add x0,x8,#8; ret
    fs_put(0x395f0, [B(0x395f0, start)], 'frame step: the frame period read (and the present interval made from it) is the host\'s vsyncs × 16,666,667 ns (state page target fps; 0 = the stored period)')
    fs_site(0x29e80, '88ae00d0')
    start = here(); emit(ADRP(16, here(), FS_STATE_OFF))
    for w in (0xb9400211,   # ldr w17,[x16]
              0x340000d1,   # cbz w17,orig (+6)
              0xb9402211,   # ldr w17,[x16,#0x20]
              0x34000091,   # cbz w17,orig (+4)
              0xf9401a08,   # ldr x8,[x16,#0x30]
              0x8b110108,   # add x8,x8,x17
              0xf9001a08):  # str x8,[x16,#0x30]     vsyncs stepped
        emit(w)
    emit(ADRP(8, here(), 0x15fb000)); emit(B(here(), 0x29e84))      # orig: adrp x8, the period table's GOT page; back
    fs_put(0x29e80, [B(0x29e80, start)], 'frame step: counts the vsyncs each present steps')

FRAME_STEP = {'1c375692de4f4b879abe88742dc0ca60': frame_step}

# How general each patch is and could be (dm/tools/docs_patches.py "Binding", listed in docs/agents/game-patches.md): what, its binding now, the loosest it could have (goal),
# purpose, why; blocked or kept: why the gap stays open (cannot close yet, or left open on purpose); checked: what was checked on game files (else a judgement)
BINDING = [
    {'what': 'the frame period, and the present interval made from it, from the host\'s frame step', 'now': 'build', 'goal': 'game', 'purpose': 'frame rate',
     'why': "the game's own frame-time object, which Pokémon Legends: Arceus also has (the same getter bytes, setter and period table): MATCH_FRAME_STEP could carry the two stubs (the getter and the present), not tried: 1.0.0, the cartridge's, is the only build on hand. A rule keyed on the getter could serve Game Freak's other mains, each keeping its own interval part"},
]
