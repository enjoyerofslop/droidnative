# The Elder Scrolls V: Skyrim 1.1.404. The stencil cut was found on 1.0.12 by seedds/nxnative PR #444 (joopyz) and is carried to this build here.
#
# Scene initialization mode 7 (main+0xbf7690's switch at +0xbf7cd8, 1.0.12's at +0xb551c0) clears depth through NVN, then dispatches compute
# a76fe13a8630d619, which writes the stencil through a storage buffer laid over the D24S8 texture's storage (1600x900: 6,553,600 bytes).
# The hosts keep a texture's depth and stencil in a Metal or Vulkan image of their own, which those buffer writes never reach, so the stencil
# holds whatever the last frame left there (255 from the interface, PR #444 found on 1.0.12). Inside Helgen Keep the shadow mask (f83614ab6954bec4) reads its
# shadow class from the stencil's upper three bits, and 7 picks secondary-shadow data the scene does not have: the lights flicker
# (droidplay-core#444). w21 is 1 in mode 7 and 0 in mode 1, the other case that clears this way, so NEG gives the stencil mask 0xffffffff
# in mode 7 alone: its depth clear also clears the stencil to 0, whose upper bits are what the compute writes there. The dispatch is kept;
# the lower five bits it writes are not carried into the image (on 1.0.12 the eight shaders that read this stencil take only its upper three, PR #444).
#
# The audio buffer pool (the object at *main+0x219afe8) keeps two libc++ std::deque<void *> free lists: wave buffers at +0x1c0 (each an
# nn::audio::WaveBuffer over a 4 KB block of the memory pool at +0x170) and ADPCM header records at +0x1f0. Four functions are their only users:
# main+0xabd548 takes a wave buffer (pop, then nn::audio::CopyMemoryPoolData into it), main+0xabd5f0 gives one back, main+0xabd428 / +0xabd4b8
# take and give back a header record. Nothing locks them, and two threads call them at once: BSTaskManager when a sound loads (main+0xac0cd8
# then the first fill, main+0xac0f48) and LibAudioUpdate when it refills a stream (main+0xac134c) or frees one (main+0xabfaf8, any thread holding
# the last reference). Two threads in a pop and a push lose an update of the deque's start or size, after which a pop hands out a slot nothing
# filled: droidplay-core#444's two crashes (a garbage header pointer into nn::audio::ParseAdpcmHeader, pc=sdk+0x1ca880 lr=main+0xac0d24, and a
# null wave buffer, pc=main+0xabd5c8 lr=main+0xac11bc) and the Mac's one in 620 s. The Switch runs the same unlocked code; the window is a few
# instructions wide, so how often it shows depends on how often the two threads meet there. Each entry now branches to a wrapper that holds an
# nn::os::MutexType around the original function, as the voice functions beside them already hold a lock of their own (main+0x219afa8). The
# wrappers sit in the zero padding after the text, inside its executable page (text ends at +0x1265968, read-only data starts at +0x1266000);
# the mutex is the first 32 bytes after the bss the module uses (MOD0's bss end is +0x3a857d0, the NSO's bss runs to +0x3a86000, and no code or
# relocation names an address past +0x3a857cc). Zero is an unlocked, non-recursive mutex to SDK 14.3's LockMutex / UnlockMutex (InitializeMutex
# stores only zeros there but the state byte, which neither reads), which main imports (PLT +0x12634b0 / +0x12634c0).
# dm/tools/tests/test_skyrim_audio_pool.py runs the wrappers in unicorn.
from nso_asm import ADDI, ADRP, B, LDP, LDP_POST, LDRX, STP, STP_PRE, STRX

build = '0c0cac3fcf0f0beb9dcf79cb68e30739'
pool_mutex = 0x3a85800
lock_mutex, unlock_mutex = 0x12634b0, 0x12634c0
pool_wrappers = 0x1265a00   # 16-byte aligned, clear of the first 0x98 bytes of padding
# entry, its first instruction (stp x29, x30, [sp, #-N]!, moved into the wrapper), what the function does
pool_functions = [
    (0xabd428, 'fd7bbea9', 'takes an ADPCM header record (pop_front of the deque at +0x1f0)'),
    (0xabd4b8, 'fd7bbea9', 'gives an ADPCM header record back (push_back to the deque at +0x1f0)'),
    (0xabd548, 'fd7bbda9', 'takes a wave buffer (pop_front of the deque at +0x1c0) and copies the samples into it'),
    (0xabd5f0, 'fd7bbea9', 'gives a wave buffer back (push_back to the deque at +0x1c0)'),
]
ret_word = 0xd65f03c0   # ret


def bl(frm, to): return B(frm, to) | 0x80000000


def pool_wrapper(at, entry, first):
    """The words of one wrapper at `at`: lock the pool mutex, call the original function with x0-x3 as they came, unlock, return its x0.
    The callee's first instruction runs from the wrapper's tail, which branches on to entry + 4; the wrapper itself uses x0-x3 only, and LockMutex / UnlockMutex clobber nothing a caller of these functions keeps"""
    w = []
    def emit(*words): w.extend(words)
    def mutex_x0(): emit(ADRP(0, at + 4 * len(w), pool_mutex)); emit(ADDI(0, 0, pool_mutex & 0xfff))
    emit(STP_PRE(29, 30, 31, -0x30), ADDI(29, 31, 0), STP(0, 1, 31, 0x10), STP(2, 3, 31, 0x20))
    mutex_x0(); emit(bl(at + 4 * len(w), lock_mutex))
    emit(LDP(0, 1, 31, 0x10), LDP(2, 3, 31, 0x20))
    tail = at + 4 * (len(w) + 8)   # after this call, the result's save, the unlock and the return
    emit(bl(at + 4 * len(w), tail))
    emit(STRX(0, 31, 0x10 // 8))
    mutex_x0(); emit(bl(at + 4 * len(w), unlock_mutex))
    emit(LDRX(0, 31, 0x10 // 8), LDP_POST(29, 30, 31, 0x30), ret_word)
    assert at + 4 * len(w) == tail
    emit(int.from_bytes(bytes.fromhex(first), 'little'))
    emit(B(at + 4 * len(w), entry + 4))
    return w


def pool_cuts():
    rows, at = [], pool_wrappers
    for entry, first, what in pool_functions:
        words = pool_wrapper(at, entry, first)
        code = b''.join(x.to_bytes(4, 'little') for x in words)
        rows.append((at, '00' * len(code), code.hex(), f'audio pool: wrapper of main+{entry:#x}, which {what}: the pool mutex held around it'))
        rows.append((entry, first, B(entry, at).to_bytes(4, 'little').hex(), f'audio pool: main+{entry:#x} enters its locked wrapper at +{at:#x}'))
        at += (len(code) + 15) & ~15
    return rows


CUTS = {
    build: [
        (0xbf7d5c, 'e3031f2a', 'e303154b', 'scene initialization mode 7: its depth clear also clears the stencil (mov w3, wzr -> neg w3, w21), which the compute pass writes only into the buffer'),
    ] + pool_cuts(),
}

# How general each patch is and could be (dm/tools/docs_patches.py "Binding", listed in docs/agents/game-patches.md)
BINDING = [
    {'what': 'scene initialization mode 7: its depth clear also clears the stencil', 'now': 'build', 'goal': 'game', 'purpose': 'rendering',
     'why': "the game's own scene initializer; the same switch is at 1.0.12's main+0xb551c0, so a function-matched rule could carry it",
     'checked': "1.0.12 and 1.1.404's mains: the same mode table and clears (2026-11-13)"},
    {'what': "the audio buffer pool's four deque functions under one mutex", 'now': 'build', 'goal': 'game', 'purpose': 'race',
     'why': "a data race in the game's own audio pool: its free lists have no lock, and BSTaskManager and LibAudioUpdate use them at once",
     'checked': "1.1.404's main: the four functions are the only callers of the deques (8 call sites, 4 loads of the pool), the padding and the bss tail unused (2026-11-13)"},
]
