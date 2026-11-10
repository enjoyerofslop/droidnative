// NVN's alpha test for the Vulkan replay: the alpha the fragment shader writes to colour 0 is compared with the reference by the
// function the game set (nvnColorStateSetAlphaTest / nvnCommandBufferSetAlphaRef) and the fragment is discarded when the comparison
// fails. Vulkan has no fixed-function alpha test (Metal has none either: nvn_mtl.m builds per-shader entry points), so the module is
// rewritten here once, when it is first used with a test set.
//   The rewrite adds a new entry point ("main") whose body calls the shader's original entry point as a function and then runs the
// test, so the shader's own OpReturn instructions are never touched: rewriting them broke structured control flow in 874 of 5,811
// fragment shaders. The original function is no longer an entry point (OpEntryPoint and OpExecutionMode move to the wrapper), so
// calling it is an ordinary call.
//   The test's function is a specialization constant with SpecId 0, which the pipeline creation sets (VkSpecializationInfo), so one
// module serves every function; the reference is a float in a push-constant block, set per draw (vkCmdPushConstants), so it is data
// and not part of the pipeline key (an animated dissolve does not build a pipeline a frame).
//   Self-contained (no libc), as spv_readonly.h, so dm/tools/tests can build it alone and run it over a game's shaders on the PC.
//   The tested value is the variable at Output location 0 (only an Output variable counts: an Input decorated Location 0 is not it),
//   loaded in the wrapper once the original entry point has returned; its stores may sit on several paths. An integer colour 0 has no
//   alpha test, as in OpenGL, and its shader keeps the module as it is.
//   → the new module's word count (0: not a fragment shader, no float colour 0, or the output is not a vec4 of float), with *afn the
//     id of the function specialization constant the pipeline sets. The input is left untouched.
#include <stdint.h>
#include <stddef.h>

#define SPV_MAGIC 0x07230203u
#define SPV_OP_ENTRY 15
#define SPV_OP_EXECMODE 16
#define SPV_OP_EXECMODEID 331
#define SPV_OP_DECORATE 71
#define SPV_OP_MEMBERDECORATE 72
#define SPV_OP_TYPEVOID 19
#define SPV_OP_TYPEBOOL 20
#define SPV_OP_TYPEINT 21
#define SPV_OP_TYPEFLOAT 22
#define SPV_OP_TYPEVECTOR 23
#define SPV_OP_TYPESTRUCT 30
#define SPV_OP_TYPEPOINTER 32
#define SPV_OP_TYPEFUNCTION 33
#define SPV_OP_CONSTANT 43
#define SPV_OP_CONSTANTTRUE 41
#define SPV_OP_CONSTANTFALSE 42
#define SPV_OP_SPECCONSTANT 50
#define SPV_OP_FUNCTION 54
#define SPV_OP_FUNCTIONEND 56
#define SPV_OP_VARIABLE 59
#define SPV_OP_LOAD 61
#define SPV_OP_ACCESSCHAIN 65
#define SPV_OP_FUNCTIONCALL 57
#define SPV_OP_COMPOSITEEXTRACT 81
#define SPV_OP_SELECT 169
#define SPV_OP_IEQUAL 170
#define SPV_OP_SELECTIONMERGE 247
#define SPV_OP_LABEL 248
#define SPV_OP_BRANCHCONDITIONAL 250
#define SPV_OP_KILL 252
#define SPV_OP_RETURN 253
#define SPV_OP_FORDEQUAL 180
#define SPV_OP_FORDNOTEQUAL 182
#define SPV_OP_FUNORDNOTEQUAL 183
#define SPV_OP_FORDLESSTHAN 184
#define SPV_OP_FORDGREATERTHAN 186
#define SPV_OP_FORDLESSTHANEQUAL 188
#define SPV_OP_FORDGREATERTHANEQUAL 190
#define SPV_EXEC_FRAGMENT 4
#define SPV_STORAGE_OUTPUT 3
#define SPV_STORAGE_PUSHCONSTANT 9
#define SPV_DEC_LOCATION 30
#define SPV_DEC_BLOCK 2
#define SPV_DEC_OFFSET 35
#define SPV_DEC_SPECID 1

static size_t spv_alpha(const uint32_t *w, size_t n, uint32_t *o, size_t cap, uint32_t *afn) {
    if (!w || n < 5 || w[0] != SPV_MAGIC || !afn) return 0;
    uint32_t entry = 0, fn_type = 0, vt = 0, btype = 0, itype = 0, ftype = 0; int spec0 = 0;
    const int v14 = w[1] >= 0x00010400u;   // SPIR-V 1.4 and later list every global variable the entry point uses in its interface
    uint32_t loc[8]; int nloc = 0;   // every Location 0 decoration: only the one on an Output variable is the colour
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        const uint32_t *a = w + i + 1;
        if (op == SPV_OP_ENTRY && len >= 3 && a[0] == SPV_EXEC_FRAGMENT) entry = a[1];
        else if (op == SPV_OP_DECORATE && len >= 4 && a[1] == SPV_DEC_LOCATION && a[2] == 0 && nloc < 8) loc[nloc++] = a[0];
        else if (op == SPV_OP_DECORATE && len >= 4 && a[1] == SPV_DEC_SPECID && a[2] == 0) spec0 = 1;   // the game's own specialization constant 0: the transform would override it
        else if (op == SPV_OP_TYPEVOID && len >= 2 && !vt) vt = a[0];
        else if (op == SPV_OP_TYPEBOOL && len >= 2 && !btype) btype = a[0];
        else if (op == SPV_OP_TYPEINT && len >= 4 && a[1] == 32 && a[2] == 1 && !itype) itype = a[0];   // OpTypeInt: result id, width, signed
        i += len;
    }
    if (!entry || !nloc) return 0;
    // The output variable at location 0 (an OpVariable in Output storage; an Input may carry the same location), its pointer type and that type a vec4 of float.
    uint32_t outvar = 0, ptr = 0, v4 = 0;
    for (size_t i = 5; i < n && !outvar; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == SPV_OP_VARIABLE && len >= 4 && w[i + 3] == SPV_STORAGE_OUTPUT)
            for (int k = 0; k < nloc; k++) if (w[i + 2] == loc[k]) { outvar = w[i + 2]; ptr = w[i + 1]; }
        i += len;
    }
    if (!outvar) return 0;
    for (size_t i = 5; i < n && !v4; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == SPV_OP_TYPEPOINTER && len >= 4 && w[i + 1] == ptr) v4 = w[i + 3];   // OpTypePointer: result id, storage class, type
        i += len;
    }
    if (!v4) return 0;
    uint32_t comp = 0, ncomp = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        if (op == SPV_OP_TYPEVECTOR && len >= 4 && w[i + 1] == v4) { comp = w[i + 2]; ncomp = w[i + 3]; }
        i += len;
    }
    int comp_float = 0, has_pc = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff; if (!len || i + len > n) return 0;
        if (op == SPV_OP_TYPEFLOAT && len >= 3 && w[i + 1] == comp) comp_float = 1;   // OpTypeFloat: result id, width
        if (op == SPV_OP_VARIABLE && len >= 4 && w[i + 3] == SPV_STORAGE_PUSHCONSTANT) has_pc = 1;
        i += len;
    }
    if (!comp || ncomp != 4 || !comp_float) return 0;   // a vec4 of a float type (an integer colour takes no alpha test)
    if (spec0 || has_pc) return 0;                      // the module already has a SpecId 0 or a push-constant block: declaring ours would collide
    ftype = comp;
    // The entry function's result type (the wrapper has the same one, void) and its function type
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == SPV_OP_FUNCTION && len >= 5 && w[i + 2] == entry) { vt = w[i + 1]; fn_type = w[i + 4]; }   // OpFunction: result type, result id, control, type
        i += len;
    }
    if (!fn_type || !vt) return 0;
    // An existing PushConstant pointer to the float type (no variable uses it: a module with one is refused above), or a new one
    uint32_t pf32 = 0;
    for (size_t i = 5; i < n && !pf32; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (op == SPV_OP_TYPEPOINTER && len >= 4 && w[i + 2] == SPV_STORAGE_PUSHCONSTANT && w[i + 3] == ftype) pf32 = w[i + 1];
        i += len;
    }
    uint32_t id = w[3];
    uint32_t wrapper = id++, lbl_entry = id++, lbl_ok = id++, lbl_dead = id++;
    uint32_t afn_id = id++, ctrue = id++, cfalse = id++;
    uint32_t ci[9]; for (int k = 1; k <= 8; k++) ci[k] = id++;
    uint32_t cmpv[8], eqv[8], selv[8];
    for (int k = 1; k <= 7; k++) { cmpv[k] = id++; eqv[k] = id++; selv[k] = id++; }
    uint32_t v_4 = id++, v_alpha = id++, v_ref = id++, ac_ref = id++, zero = id++, call_res = id++;
    int new_pf32 = !pf32;   // declared below, not found in the module
    if (!pf32) pf32 = id++;
    uint32_t pstruct = id++, pblock = id++, pv = id++;
    int new_btype = !btype, new_itype = !itype;
    if (!btype) btype = id++;
    if (!itype) itype = id++;
    if (cap < n + 200) return 0;
    for (size_t i = 0; i < cap; i++) o[i] = 0;
    o[0] = w[0]; o[1] = w[1]; o[2] = w[2]; o[3] = id; o[4] = w[4];
    size_t on = 5;
    #define SPV_INS(...) do { const uint32_t _x[] = {__VA_ARGS__}; uint32_t _n = (uint32_t)(sizeof _x / sizeof _x[0]); \
        if (on + _n > cap) return 0; o[on++] = (_n << 16) | _x[0]; for (uint32_t _i = 1; _i < _n; _i++) o[on++] = _x[_i]; } while (0)
    int ann_done = 0, decl_done = 0;
    for (size_t i = 5; i < n; ) {
        uint32_t len = w[i] >> 16, op = w[i] & 0xffff;
        if (!len || i + len > n) return 0;
        if (!ann_done && op >= SPV_OP_TYPEVOID && op <= 39) {   // the annotations section ends where the types begin: the decorations go there
            ann_done = 1;
            SPV_INS(SPV_OP_DECORATE, afn_id, SPV_DEC_SPECID, 0);
            SPV_INS(SPV_OP_DECORATE, pstruct, SPV_DEC_BLOCK); SPV_INS(SPV_OP_MEMBERDECORATE, pstruct, 0, SPV_DEC_OFFSET, 0);
        }
        if (op == SPV_OP_FUNCTION && !decl_done) {   // after every global declaration, before the first function
            decl_done = 1;
            if (new_btype) SPV_INS(SPV_OP_TYPEBOOL, btype);
            if (new_itype) SPV_INS(SPV_OP_TYPEINT, itype, 32, 1);
            if (new_pf32) SPV_INS(SPV_OP_TYPEPOINTER, pf32, SPV_STORAGE_PUSHCONSTANT, ftype);
            SPV_INS(SPV_OP_TYPESTRUCT, pstruct, ftype); SPV_INS(SPV_OP_TYPEPOINTER, pblock, SPV_STORAGE_PUSHCONSTANT, pstruct); SPV_INS(SPV_OP_VARIABLE, pblock, pv, SPV_STORAGE_PUSHCONSTANT);
            SPV_INS(SPV_OP_SPECCONSTANT, itype, afn_id, 8);   // NVN_ALPHA_FUNC_ALWAYS, the value the pipeline overrides
            for (int k = 1; k <= 8; k++) SPV_INS(SPV_OP_CONSTANT, itype, ci[k], (uint32_t)k);
            SPV_INS(SPV_OP_CONSTANT, itype, zero, 0);
            SPV_INS(SPV_OP_CONSTANTTRUE, btype, ctrue);
            SPV_INS(SPV_OP_CONSTANTFALSE, btype, cfalse);
        }
        if (op == SPV_OP_ENTRY && len >= 3 && w[i + 2] == entry) {   // the wrapper becomes the entry point; SPIR-V 1.4 lists the push constant the wrapper reads
            uint32_t nl = len + (v14 ? 1u : 0u);
            if (on + nl > cap) return 0;
            o[on++] = (nl << 16) | SPV_OP_ENTRY; o[on++] = w[i + 1]; o[on++] = wrapper;
            for (uint32_t k = 3; k < len; k++) o[on++] = w[i + k];
            if (v14) o[on++] = pv;
            i += len; continue;
        }
        if ((op == SPV_OP_EXECMODE || op == SPV_OP_EXECMODEID) && len >= 2 && w[i + 1] == entry) {   // its execution modes move with it (OpExecutionMode: entry point, mode, literals)
            if (on + len > cap) return 0;
            o[on++] = (len << 16) | op; o[on++] = wrapper;
            for (uint32_t k = 2; k < len; k++) o[on++] = w[i + k]; i += len; continue;
        }
        if (on + len > cap) return 0;
        for (uint32_t k = 0; k < len; k++) o[on++] = w[i + k];
        i += len;
    }
    if (!decl_done) return 0;
    // The wrapper: call the shader, then test what it wrote to colour 0
    SPV_INS(SPV_OP_FUNCTION, vt, wrapper, 0, fn_type);
    SPV_INS(SPV_OP_LABEL, lbl_entry);
    SPV_INS(SPV_OP_FUNCTIONCALL, vt, call_res, entry);
    SPV_INS(SPV_OP_LOAD, v4, v_4, outvar);
    SPV_INS(SPV_OP_COMPOSITEEXTRACT, ftype, v_alpha, v_4, 3);                              // its alpha
    SPV_INS(SPV_OP_ACCESSCHAIN, pf32, ac_ref, pv, zero);
    SPV_INS(SPV_OP_LOAD, ftype, v_ref, ac_ref);                                            // the reference, from the push constant
    SPV_INS(SPV_OP_FORDLESSTHAN, btype, cmpv[2], v_alpha, v_ref);
    SPV_INS(SPV_OP_FORDEQUAL, btype, cmpv[3], v_alpha, v_ref);
    SPV_INS(SPV_OP_FORDLESSTHANEQUAL, btype, cmpv[4], v_alpha, v_ref);
    SPV_INS(SPV_OP_FORDGREATERTHAN, btype, cmpv[5], v_alpha, v_ref);
    SPV_INS(SPV_OP_FUNORDNOTEQUAL, btype, cmpv[6], v_alpha, v_ref);   // NOTEQUAL is true when either is NaN, as Maxwell and Metal have it
    SPV_INS(SPV_OP_FORDGREATERTHANEQUAL, btype, cmpv[7], v_alpha, v_ref);
    for (int k = 1; k <= 7; k++) SPV_INS(SPV_OP_IEQUAL, btype, eqv[k], afn_id, ci[k]);
    // pass = true, and for each function pass = func == k ? cmp[k] : pass
    uint32_t acc = ctrue;
    for (int k = 1; k <= 7; k++) { SPV_INS(SPV_OP_SELECT, btype, selv[k], eqv[k], k == 1 ? cfalse : cmpv[k], acc); acc = selv[k]; }
    SPV_INS(SPV_OP_SELECTIONMERGE, lbl_ok, 0);
    SPV_INS(SPV_OP_BRANCHCONDITIONAL, acc, lbl_ok, lbl_dead);
    SPV_INS(SPV_OP_LABEL, lbl_dead);
    SPV_INS(SPV_OP_KILL);
    SPV_INS(SPV_OP_LABEL, lbl_ok);
    SPV_INS(SPV_OP_RETURN);
    SPV_INS(SPV_OP_FUNCTIONEND);
    #undef SPV_INS
    *afn = afn_id;
    return on;
}
