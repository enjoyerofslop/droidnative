// H.264 sequence parameter sets for Android's movie decoder (media_android.c): whether a stream's pictures leave the decoder in the order they go in.
// They do when the SPS's VUI says max_num_reorder_frames 0 (bitstream_restriction, E.2.1), and without that when pic_order_cnt_type is 2 (output order is decode order,
// H.264 8.2.1.3) or the profile is Baseline (no B slices): the rule hle_movie_avc.c avc_reorder_depth holds no picture back by on Apple. Donkey Kong Country Returns HD 1.0.0's
// opening movie (GI.mp4: Main profile, pic_order_cnt_type 2, a VUI without bitstream_restriction) is such a stream. Plain C on bytes, for dm/tools/tests/test_avc_sps.py.
#pragma once
#include <stddef.h>
#include <stdint.h>
#include <string.h>

typedef struct { uint8_t b[600]; size_t n, bit; int bad; } avc_rbsp;   // an SPS's RBSP (emulation prevention bytes taken out) and a read position in bits
typedef struct { int profile, poc_type, refs, vui, br, reorder; size_t vui_at, br_at; } avc_sps;   // vui_at / br_at: the bit of vui_parameters_present_flag / bitstream_restriction_flag

static unsigned avr_u(avc_rbsp *r, unsigned n) {
    unsigned v = 0;
    if (n > 32 || r->bit + n > r->n * 8) { r->bad = 1; return 0; }
    while (n--) { v = v << 1 | (r->b[r->bit / 8] >> (7 - r->bit % 8) & 1); r->bit++; }
    return v;
}
static unsigned avr_ue(avc_rbsp *r) {
    unsigned z = 0;
    while (!r->bad && !avr_u(r, 1)) if (++z > 31) { r->bad = 1; return 0; }
    return r->bad ? 0 : (unsigned)((1ull << z) - 1 + avr_u(r, z));
}
static void avr_hrd(avc_rbsp *r) {   // hrd_parameters (E.1.2)
    unsigned cpb = avr_ue(r); avr_u(r, 8);
    for (unsigned i = 0; i <= cpb && i < 32 && !r->bad; i++) { avr_ue(r); avr_ue(r); avr_u(r, 1); }
    avr_u(r, 20);
}
// The SPS NAL unit (its header byte, no start code) → its fields (7.3.2.1.1, E.1.1); 0 when it is not an SPS or is cut short
static int avc_sps_parse(const uint8_t *nal, size_t n, avc_rbsp *r, avc_sps *s) {
    memset(r, 0, sizeof *r); memset(s, 0, sizeof *s);
    if (n < 4 || (nal[0] & 31) != 7) return 0;
    for (size_t i = 1, z = 0; i < n; i++) {   // emulation_prevention_three_byte: 00 00 03 → 00 00
        if (z >= 2 && nal[i] == 3) { z = 0; continue; }
        if (r->n == sizeof r->b) return 0;
        r->b[r->n++] = nal[i]; z = nal[i] ? 0 : z + 1;
    }
    s->profile = (int)avr_u(r, 8); avr_u(r, 16); avr_ue(r);   // constraint flags and level_idc, seq_parameter_set_id
    switch (s->profile) {
    case 100: case 110: case 122: case 244: case 44: case 83: case 86: case 118: case 128: case 138: case 139: case 134: case 135: {
        unsigned chroma = avr_ue(r);
        if (chroma == 3) avr_u(r, 1);
        avr_ue(r); avr_ue(r); avr_u(r, 1);   // bit depths, qpprime_y_zero_transform_bypass_flag
        if (avr_u(r, 1)) for (unsigned i = 0; i < (chroma == 3 ? 12u : 8u) && !r->bad; i++) {   // seq_scaling_list_present_flag[i], scaling_list (7.3.2.1.1.1)
            if (!avr_u(r, 1)) continue;
            int last = 8, next = 8;
            for (unsigned j = 0; j < (i < 6 ? 16u : 64u) && next && !r->bad; j++) {
                unsigned c = avr_ue(r); int d = c & 1 ? (int)((c + 1) / 2) : -(int)(c / 2);
                next = (last + d + 256) % 256; if (next) last = next;
            }
        }
        break;
    }
    default: break;
    }
    avr_ue(r);   // log2_max_frame_num_minus4
    s->poc_type = (int)avr_ue(r);
    if (s->poc_type == 0) avr_ue(r);
    else if (s->poc_type == 1) { avr_u(r, 1); avr_ue(r); avr_ue(r); unsigned k = avr_ue(r); for (unsigned i = 0; i < k && i < 256 && !r->bad; i++) avr_ue(r); }
    s->refs = (int)avr_ue(r); avr_u(r, 1); avr_ue(r); avr_ue(r);   // max_num_ref_frames, gaps_in_frame_num_value_allowed_flag, picture size in macroblocks
    if (!avr_u(r, 1)) avr_u(r, 1);   // frame_mbs_only_flag, else mb_adaptive_frame_field_flag
    avr_u(r, 1);   // direct_8x8_inference_flag
    if (avr_u(r, 1)) { avr_ue(r); avr_ue(r); avr_ue(r); avr_ue(r); }   // frame cropping
    s->vui_at = r->bit; s->vui = (int)avr_u(r, 1);
    if (s->vui) {
        if (avr_u(r, 1) && avr_u(r, 8) == 255) avr_u(r, 32);   // aspect ratio, Extended_SAR
        if (avr_u(r, 1)) avr_u(r, 1);   // overscan
        if (avr_u(r, 1)) { avr_u(r, 4); if (avr_u(r, 1)) avr_u(r, 24); }   // video signal type, colour description
        if (avr_u(r, 1)) { avr_ue(r); avr_ue(r); }   // chroma sample locations
        if (avr_u(r, 1)) { avr_u(r, 32); avr_u(r, 32); avr_u(r, 1); }   // timing
        int nal_hrd = (int)avr_u(r, 1); if (nal_hrd) avr_hrd(r);
        int vcl_hrd = (int)avr_u(r, 1); if (vcl_hrd) avr_hrd(r);
        if (nal_hrd || vcl_hrd) avr_u(r, 1);   // low_delay_hrd_flag
        avr_u(r, 1);   // pic_struct_present_flag
        s->br_at = r->bit; s->br = (int)avr_u(r, 1);
        if (s->br) { avr_u(r, 1); avr_ue(r); avr_ue(r); avr_ue(r); avr_ue(r); s->reorder = (int)avr_ue(r); avr_ue(r); }
    }
    return !r->bad;
}
// Pictures leave in decode order: as the SPS's bitstream_restriction says, else by pic_order_cnt_type 2 or the Baseline profile
static int avc_sps_decode_order(const avc_sps *s) { return s->br ? s->reorder == 0 : s->poc_type == 2 || s->profile == 66; }
// The same from the NAL unit; 0 for one that does not parse
static int avc_decode_order(const uint8_t *nal, size_t n) { avc_rbsp r; avc_sps s; return avc_sps_parse(nal, n, &r, &s) && avc_sps_decode_order(&s); }
