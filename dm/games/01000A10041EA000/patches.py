# The Elder Scrolls V: Skyrim 1.1.404. The cut was found on 1.0.12 by seedds/nxnative PR #444 (joopyz) and is carried to this build here.
#
# Scene initialization mode 7 (main+0xbf7690's switch at +0xbf7cd8, 1.0.12's at +0xb551c0) clears depth through NVN, then dispatches compute
# a76fe13a8630d619, which writes the stencil through a storage buffer laid over the D24S8 texture's storage (1600x900: 6,553,600 bytes).
# The hosts keep a texture's depth and stencil in a Metal or Vulkan image of their own, which those buffer writes never reach, so the stencil
# holds whatever the last frame left there (255 from the interface, PR #444 found on 1.0.12). Inside Helgen Keep the shadow mask (f83614ab6954bec4) reads its
# shadow class from the stencil's upper three bits, and 7 picks secondary-shadow data the scene does not have: the lights flicker
# (droidplay-core#444). w21 is 1 in mode 7 and 0 in mode 1, the other case that clears this way, so NEG gives the stencil mask 0xffffffff
# in mode 7 alone: its depth clear also clears the stencil to 0, whose upper bits are what the compute writes there. The dispatch is kept;
# the lower five bits it writes are not carried into the image (on 1.0.12 the eight shaders that read this stencil take only its upper three, PR #444).
CUTS = {
    '0c0cac3fcf0f0beb9dcf79cb68e30739': [
        (0xbf7d5c, 'e3031f2a', 'e303154b', 'scene initialization mode 7: its depth clear also clears the stencil (mov w3, wzr -> neg w3, w21), which the compute pass writes only into the buffer'),
    ],
}

# How general each patch is and could be (dm/tools/docs_patches.py "Binding", listed in docs/agents/game-patches.md)
BINDING = [
    {'what': 'scene initialization mode 7: its depth clear also clears the stencil', 'now': 'build', 'goal': 'game', 'purpose': 'rendering',
     'why': "the game's own scene initializer; the same switch is at 1.0.12's main+0xb551c0, so a function-matched rule could carry it",
     'checked': "1.0.12 and 1.1.404's mains: the same mode table and clears (2026-11-13)"},
]
