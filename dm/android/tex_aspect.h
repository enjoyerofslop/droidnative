// Which aspect of its image a texture slot reads (gfx_vk_draw.inc tex_aspect), as a plain function, so dm/tools/tests/test_tex_aspect.py checks it on the host.
// A depth-stencil texture reads its depth, unless it is in stencil mode: a view that sets the mode (nvnTextureViewSetDepthStencilMode) decides, else the texture's own
// (nvnTextureBuilderSetDepthStencilMode). Stencil mode reads the stencil, as nvn_mtl.m's X32_Stencil8 views do; an image with no stencil then reads its depth (*missing
// set: the caller says so). A stencil-only image reads its stencil, a colour image its colour.
#pragma once
enum { TEX_ASPECT_COLOR = 1, TEX_ASPECT_DEPTH = 2, TEX_ASPECT_STENCIL = 4 };   // VkImageAspectFlagBits' values
// img: the image's aspects; view_sets: a view sets the depth-stencil mode, view_stencil: that mode is STENCIL; tex_stencil: the texture was built in stencil mode
static inline unsigned tex_aspect_pick(unsigned img, int view_sets, int view_stencil, int tex_stencil, int *missing) {
    *missing = 0;
    if (img == TEX_ASPECT_COLOR) return TEX_ASPECT_COLOR;
    if (!(img & TEX_ASPECT_DEPTH)) return TEX_ASPECT_STENCIL;
    if (!(view_sets ? view_stencil : tex_stencil)) return TEX_ASPECT_DEPTH;
    if (!(img & TEX_ASPECT_STENCIL)) { *missing = 1; return TEX_ASPECT_DEPTH; }
    return TEX_ASPECT_STENCIL;
}
