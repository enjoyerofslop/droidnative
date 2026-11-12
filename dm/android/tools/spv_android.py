# SPIR-V from dmsh_xlate (dm/gfx/tools/dmsh_xlate: Ryujinx's translator, Vulkan SPIR-V, every resource in set 0) made ready for the Android Vulkan replay
# (dm/android/gfx_vk.c), as dmsh_build.py post-processes the MSL for Metal; the translator itself is shared and left as it is:
#   the descriptor set becomes the stage's own (vertex 0, fragment 1, geometry 2, tessellation 3, compute 0): stages number their bindings from the same start,
#     so they cannot share one set;
#   storage images without a format get the capabilities Vulkan wants for them (StorageImageWrite / ReadWithoutFormat);
#   fragment shader interlock (FragmentShaderPixelInterlockEXT, its execution modes and the begin / end instructions) is removed: mobile GPUs lack it, and
#     the translator declares it on hosts that have it (the order it gives overlapping fragments' image accesses is lost; such a shader is reported);
#   for a vertex shader with transform feedback (res.json "tf", spv_build.py from the control section), also <key>.tf.spv: before every return, the captured
#     outputs stored as their bits into storage buffers (set 0, binding 100 + feedback buffer), vertex v at v × stride (nvn_mtl.m's main0_tf; the Adreno has no
#     VK_EXT_transform_feedback): the host draws it as points with rasterization off, the vertex buffers shifted so v counts from the draw's first vertex;
#   for a vertex shader, also <key>.z.spv: before every return of the entry point, position z becomes (z + w) / 2, the -1..1 depth of NVN's default depth mode
#     mapped to Vulkan's 0..1 (nvn_mtl.m adds the same as its main0_z entry point; Vulkan without VK_EXT_depth_clip_control has no other way);
#   the uniform slots' size table (bank 25, which the translator's TranslationFlags.MetalUniformBounds reads before each read of c[3..16]) is taken out, its bound
#     tests made true and its binding dropped from res.json (cbsize_strip): the reads are the ones the translator wrote before the table;
#   res.json cbufs[].ext: how many bytes of each constant buffer the shader can read (cb_extents; the .z / .tf variants add no constant buffer read);
#   for a vertex shader, the constant buffer reads its position is made of can read their row through a value known only at run time (pos_rows), after cb_extents,
#     which these reads would otherwise make the whole buffer: Qualcomm's Adreno 740 driver lost those rows in the position-only copy of a shader it bins with.
#     A specialization constant the host sets only where it is needed turns them on; off, the rows are the constant ones.
#   a task or mesh shader (res.json "mesh", spv_build.py), translated as compute, made a Vulkan task or mesh module (spv_mesh.py), a mesh shader's .z.spv with the depth
#   -1..1 mapping as a vertex shader's; res.json stage 'ts' / 'ms' and prim_locs, the locations it writes per primitive.
# Usage: spv_android.py [-j N] <dmsh_xlate output dir> <out dir> [key ...]   (all keys of the input dir by default); prints a line for each shader with a problem, and a summary
#   The shaders are done in N processes (default: one per CPU), each writing its own shaders' files: a shader's files depend only on its own inputs, so they are the same as one
#   process makes, and the lines come out in key order. This is pure Python, about 20 shaders a second on one core (most of it cb_extents), so in one process it was most of a
#   big game's translation time: Ocarina of Time's 42,328 shaders took about 33 minutes after 3 of translating.
import concurrent.futures as cf, functools, itertools, json, multiprocessing, os, struct, sys
from pathlib import Path

ANDROID_CHAIN = 6   # res.json 'android': bumped when this post-pass or spv_build.py's translation changes what they make (spv_build.py translates older outputs again).
                    # 5: the size table taken out (cbsize_strip), so a chain 4 output of the merged translator, which reads it, is translated again
                    # 6: a vertex shader's position can read its constant buffer rows at run time (pos_rows, behind a specialization constant); with it, the translator types sampled array layers S32
                    #    (StructuredProgram.GetSourceVarType), so a layer no longer goes through float locals (#135 and #147 shipped together)
EXT_FROM = 3   # 4 added res.json cbufs[].ext (cb_extents) and nothing else: spv_build.py brings an output of chain 3 up to date from its .spv (add_ext), without the translator,
               # only while ANDROID_CHAIN is EXT_FROM + 1 (upgrade stamps that chain, so a later bump for a change to the .spv translates chain 3's outputs again)
SET_OF = {'vs': 0, 'ps': 1, 'gs': 2, 'tc': 3, 'te': 3, 'cs': 0, 'ms': 0, 'ts': 2}   # a mesh pipeline: mesh in the vertex shader's set, task in the geometry shader's
OP_CAP, OP_EXT, OP_EXECMODE, OP_ENTRY, OP_DECORATE, OP_MEMBERDECORATE = 17, 10, 16, 15, 71, 72
OP_FUNCTION, OP_FUNCTIONEND, OP_RETURN, OP_VARIABLE, OP_TYPEPOINTER, OP_TYPEINT, OP_TYPEFLOAT, OP_TYPEVECTOR, OP_CONSTANT = 54, 56, 253, 59, 32, 21, 22, 23, 43
OP_ACCESSCHAIN, OP_LOAD, OP_STORE, OP_COMPOSITEEXTRACT, OP_COMPOSITEINSERT, OP_FADD, OP_FMUL, OP_LABEL = 65, 61, 62, 81, 82, 129, 133, 248
INTERLOCK_CAPS = {5363, 5372, 5378}             # FragmentShaderSampleInterlockEXT, ShadingRateInterlockEXT, FragmentShaderPixelInterlockEXT
INTERLOCK_MODES = {5366, 5367, 5368, 5369, 5370, 5371}
INTERLOCK_OPS = {5364, 5365}
OP_TYPEIMAGE, OP_IMAGEREAD, OP_IMAGEWRITE, CAP_READ_NOFMT, CAP_WRITE_NOFMT = 25, 98, 99, 55, 56                    # OpBeginInvocationInterlockEXT, OpEndInvocationInterlockEXT
STORAGE_OUTPUT, DEC_BUILTIN, DEC_DESCRIPTORSET, BUILTIN_POSITION = 3, 11, 34, 0

def parse(data):
    w = list(struct.unpack('<%dI' % (len(data) // 4), data))
    assert w[0] == 0x07230203, 'not SPIR-V'
    hdr, ins, i = w[:5], [], 5
    while i < len(w):
        n, op = w[i] >> 16, w[i] & 0xffff
        assert n and i + n <= len(w), 'bad instruction length'
        ins.append([op] + w[i + 1:i + n]); i += n
    return hdr, ins

def unreadable(data):
    """Why data isn't a whole SPIR-V module, or None. The translator writes each output with File.WriteAllBytes, which creates the file before it writes: a write that fails,
    as on a full disk, leaves it empty or cut short, and parse stopped the post-pass at the first one (IndexError at w[0], droidplay-core#307). A module cut at an
    instruction's end still parses, but no longer ends in OpFunctionEnd, as every module with a function does"""
    if not data: return 'empty (0 bytes)'
    if len(data) % 4 or len(data) < 24: return f'cut short ({len(data):,} bytes)'
    w = struct.unpack('<%dI' % (len(data) // 4), data)
    if w[0] != 0x07230203: return f'not SPIR-V ({len(data):,} bytes)'
    i, last = 5, None
    while i < len(w):
        n = w[i] >> 16
        if not n or i + n > len(w): return f'cut short ({len(data):,} bytes: an instruction runs past the end)'
        last, i = w[i] & 0xffff, i + n
    if last != OP_FUNCTIONEND: return f'cut short ({len(data):,} bytes: it does not end in OpFunctionEnd)'
    return None

def emit(hdr, ins):
    out = list(hdr)
    for x in ins: out.append((len(x) << 16) | x[0]); out.extend(x[1:])
    return struct.pack('<%dI' % len(out), *out)

def ext_name(x):   # OpExtension's literal string
    return b''.join(struct.pack('<I', v) for v in x[1:]).split(b'\0')[0].decode()

def process(data, stage, cbsize=None, keep=()):
    """→ (header, instructions, interlock removed, size table taken out: None when the shader has none, else True, or False when its use was not the translator's).
    keep: variables whose descriptor set stays as it is (spv_meshemu.compute's buffers)"""
    hdr, ins = parse(data)
    stripped = None
    if cbsize is not None: hdr, ins, stripped = cbsize_strip(hdr, ins, cbsize)
    s = SET_OF.get(stage, 0); interlock = False
    out = []
    for x in ins:
        op = x[0]
        if op == OP_DECORATE and x[2] == DEC_DESCRIPTORSET and x[1] not in keep: x = x[:3] + [s]
        if op == OP_CAP and x[1] in INTERLOCK_CAPS: interlock = True; continue
        if op == OP_EXT and ext_name(x) == 'SPV_EXT_fragment_shader_interlock': continue
        if op == OP_EXECMODE and x[2] in INTERLOCK_MODES: continue
        if op in INTERLOCK_OPS: continue
        out.append(x)
    # storage images declared without a format (the translator declares them so for Metal, which reads and writes any format): Vulkan wants
    # StorageImageWriteWithoutFormat / ReadWithoutFormat for their stores / loads
    if any(x[0] == OP_TYPEIMAGE and x[7] == 2 and x[8] == 0 for x in out):
        have = {x[1] for x in out if x[0] == OP_CAP}
        need = [c for c, o in ((CAP_WRITE_NOFMT, OP_IMAGEWRITE), (CAP_READ_NOFMT, OP_IMAGEREAD)) if c not in have and any(x[0] == o for x in out)]
        at = next(i for i, x in enumerate(out) if x[0] == OP_CAP)
        out[at + 1:at + 1] = [[OP_CAP, c] for c in need]
    hdr, out = dyn_components(hdr, out)
    return hdr, out, interlock, stripped

# ---- Dynamic vector components ----
OP_TYPEBOOL, OP_TYPESTRUCT_, OP_TYPEARRAY, OP_TYPERUNTIMEARRAY_, OP_SELECT, OP_IEQUAL = 20, 30, 28, 29, 169, 170
def dyn_components(hdr, ins):
    """A load through an access chain whose last index picks a vector's component with a value (not a constant) — the translator's read of c[n] word by word,
    `cb[0][w >> 2][w & 3]`, as Nintendo's layout library reads its texture coordinates, colours and positions from the uniform buffer — becomes a load of the whole
    vector and a choice among its four components (OpCompositeExtract with constants, OpSelect on the index). The Adreno 619's driver (Vulkan 1.1.128) reads such a
    component wrong: Super Mario Bros. Wonder's title and menus came out as vertical stripes (each quad's v the same as its u, the texture read along its diagonal).
    Only pointers that are only loaded are changed"""
    bound = hdr[3]
    def new():
        nonlocal bound; bound += 1; return bound - 1
    ty = {x[1]: x for x in ins if x[0] in (OP_TYPEINT, OP_TYPEFLOAT, OP_TYPEVECTOR, OP_TYPEBOOL, OP_TYPESTRUCT_, OP_TYPEARRAY, OP_TYPERUNTIMEARRAY_)}
    ptr = {x[1]: (x[2], x[3]) for x in ins if x[0] == OP_TYPEPOINTER}
    const = {x[2]: x[3] for x in ins if x[0] == OP_CONSTANT}
    rtype = {}   # result id → its type, for the instructions with both
    var_ty = {x[2]: x[1] for x in ins if x[0] == OP_VARIABLE}
    for x in ins:
        if x[0] in (OP_ACCESSCHAIN, OP_LOAD, OP_CONSTANT, OP_BITCAST, OP_IADD, OP_IMUL, OP_COMPOSITEEXTRACT, OP_VARIABLE) or (x[0] >= 124 and x[0] <= 200 and len(x) > 2):
            if len(x) > 2: rtype[x[2]] = x[1]
    loads = {}; others = set()
    for x in ins:
        if x[0] == OP_LOAD: loads.setdefault(x[3], []).append(x)
        elif x[0] == OP_STORE: others.update(x[1:])
        elif x[0] not in (OP_DECORATE, OP_MEMBERDECORATE, 5, 6): others.update(x[3:])   # operands after the result type and id (OpName / OpMemberName: debug names only)
    chains = {}   # chain id → (vector pointer type or None, vector type, component type, the chain without its last index, index id)
    want_ptr = {}
    for x in ins:
        if x[0] != OP_ACCESSCHAIN or len(x) < 6 or x[-1] in const: continue
        if x[2] in others or x[2] not in loads: continue   # used other than by OpLoad
        base = x[3]; bt = var_ty.get(base) or rtype.get(base)
        if bt not in ptr: continue
        storage, t = ptr[bt]; ok = True
        for idx in x[4:-1]:
            d = ty.get(t)
            if d is None: ok = False; break
            if d[0] == OP_TYPESTRUCT_:
                if idx not in const: ok = False; break
                t = d[2 + const[idx]]
            elif d[0] in (OP_TYPEARRAY, OP_TYPERUNTIMEARRAY_): t = d[2]
            else: ok = False; break
        d = ty.get(t)
        if not ok or d is None or d[0] != OP_TYPEVECTOR or d[3] != 4: continue
        it = rtype.get(x[-1])
        if it not in ty or ty[it][0] != OP_TYPEINT: continue
        chains[x[2]] = (storage, t, d[2], x[:-1], x[-1], it)
    if not chains: return hdr, ins
    glob = []
    pv = {}
    for s, t, *_ in chains.values():
        if (s, t) in pv: continue
        p = next((k for k, v in ptr.items() if v == (s, t)), None)
        if p is None: p = new(); glob.append([OP_TYPEPOINTER, p, s, t])
        pv[(s, t)] = p
    tb = next((x[1] for x in ins if x[0] == OP_TYPEBOOL), None)
    if tb is None: tb = new(); glob.insert(0, [OP_TYPEBOOL, tb])
    cn = {}
    def cint(it, n):
        if (it, n) not in cn: c = new(); cn[(it, n)] = c; glob.append([OP_CONSTANT, it, c, n])
        return cn[(it, n)]
    for c in chains.values():
        for n in (1, 2, 3): cint(c[5], n)
    out, done_glob = [], False
    for x in ins:
        if x[0] == OP_FUNCTION and not done_glob: out.extend(glob); done_glob = True
        if x[0] == OP_ACCESSCHAIN and x[2] in chains:
            s, t, ct, pre, idx, it = chains[x[2]]
            out.append([OP_ACCESSCHAIN, pv[(s, t)]] + pre[2:]); continue   # the same result id, now a pointer to the vector
        if x[0] == OP_LOAD and x[3] in chains:
            s, t, ct, pre, idx, it = chains[x[3]]
            v = new(); e = [new() for _ in range(4)]; out.append([OP_LOAD, t, v, x[3]] + x[4:])
            out += [[OP_COMPOSITEEXTRACT, ct, e[i], v, i] for i in range(4)]
            cur = e[0]
            for i in (1, 2, 3):
                b = new(); r = x[2] if i == 3 else new()
                out += [[OP_IEQUAL, tb, b, idx, cint(it, i)], [OP_SELECT, ct, r, b, e[i], cur]]; cur = r
            continue
        out.append(x)
    hdr = list(hdr); hdr[3] = bound
    return hdr, out

# ---- The uniform slots' size table taken out ----
# The translator bounds every read of a game uniform slot (c[3..16]) for Metal, which has no bounds of its own (TranslationFlags.MetalUniformBounds,
# Instructions.cs TryGenerateBoundedUniformLoad): it loads the slot's size from the table in bank 25, tests the word against it and selects 0 past it. Every
# operand of such a test is a constant buffer's, so the test is the same for the whole draw, and the Adreno 830's driver (0x80320001) faults the GPU on a vertex
# shader with about 270 of them or more: the context is lost (vkQueueSubmit -4) and nothing is drawn after (Pokémon Brilliant Diamond, whose vertex shaders have up
# to 295; docs/reference/rendering.md, "Uniform bound tests in a vertex shader lose the device on the Adreno 830"). Taken out here: the replay binds a slot's buffer
# as the game bound it, so a read past it is undefined on Vulkan, as it was before the table, and the code is as fast as it was then
CBSIZE_BANK = 25   # dm/gfx/nvn/dmsh_abi.h DMSH_CBSIZE_BANK
OP_NAME, OP_CONSTANTTRUE, OP_INBOUNDSACCESSCHAIN, OP_ULESSTHAN, OP_SHIFTRIGHTLOGICAL = 5, 41, 66, 176, 194
def cbsize_strip(hdr, ins, binding):
    """The size table (constant buffer `binding`, bank 25) taken out of a shader: each load of a slot's size becomes 65536 (the whole 64 KB of a constant buffer) and
    each bound test on it, `word < size >> 2`, true (any word an index into the 4096-element array can reach); the table's variable, access chains, name and
    decorations go. What is left is the read the translator wrote before the table (the selects of true fold away).
    → (header, instructions, True); the module as it was and None when it has no such table, or False when the table has a use the translator does not make"""
    var = {x[1] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BINDING and x[3] == binding} & {x[2] for x in ins if x[0] == OP_VARIABLE}
    if not var: return hdr, ins, None
    chains = {x[2] for x in ins if x[0] in (OP_ACCESSCHAIN, OP_INBOUNDSACCESSCHAIN) and x[3] in var}
    loads = {x[2] for x in ins if x[0] == OP_LOAD and x[3] in chains}
    words = {x[2] for x in ins if x[0] == OP_SHIFTRIGHTLOGICAL and x[3] in loads}
    infn = False
    for x in ins:   # in the functions, the variable is only the base of access chains and a chain only the pointer of a load (Instructions.cs TryGenerateBoundedUniformLoad)
        op = x[0]
        if op == OP_FUNCTION: infn = True
        elif op == OP_FUNCTIONEND: infn = False
        if not infn: continue
        for q in range(1, len(x)):
            w = x[q]
            if spv_lit(op, q) or (op not in NO_RESULT and q <= 2): continue
            if (w in var and not (op in (OP_ACCESSCHAIN, OP_INBOUNDSACCESSCHAIN) and q == 3)) or (w in chains and not (op == OP_LOAD and q == 3)): return hdr, ins, False
    bound = hdr[3]
    tu = next(x[1] for x in ins if x[0] == OP_LOAD and x[2] in loads)
    tb = next((x[1] for x in ins if x[0] == OP_TYPEBOOL), None)
    c64k = next((x[2] for x in ins if x[0] == OP_CONSTANT and x[1] == tu and x[3] == 0x10000), None)
    ctrue = next((x[2] for x in ins if x[0] == OP_CONSTANTTRUE and x[1] == tb), None) if tb is not None else None
    glob = []
    if c64k is None: c64k = bound; bound += 1; glob.append([OP_CONSTANT, tu, c64k, 0x10000])
    if ctrue is None and tb is not None: ctrue = bound; bound += 1; glob.append([OP_CONSTANTTRUE, tb, ctrue])
    out = []
    for x in ins:
        op = x[0]
        if op == OP_LOAD and x[2] in loads: out.append([OP_COPYOBJECT, x[1], x[2], c64k]); continue
        if op == OP_ULESSTHAN and x[4] in words and ctrue is not None: out.append([OP_COPYOBJECT, x[1], x[2], ctrue]); continue
        if op in (OP_ACCESSCHAIN, OP_INBOUNDSACCESSCHAIN) and x[2] in chains: continue
        if (op == OP_VARIABLE and x[2] in var) or (op in (OP_DECORATE, OP_NAME) and x[1] in var): continue
        if op == OP_ENTRY:   # a SPIR-V 1.4 module lists every global variable in the interface, after the entry point's name (its last word holds a zero byte)
            e = 3
            while e < len(x) and all(x[e] >> s & 0xff for s in (0, 8, 16, 24)): e += 1
            x = x[:e + 1] + [w for w in x[e + 1:] if w not in var]
        out.append(x)
    at = next(i for i, x in enumerate(out) if x[0] == OP_FUNCTION)
    out[at:at] = glob
    dead = lambda x: (x[0] == OP_SHIFTRIGHTLOGICAL and x[2] in words) or (x[0] == OP_COPYOBJECT and x[2] in loads)
    while True:   # the sizes and their shifts that no compare reads any more go too
        used = set()
        for x in out:
            if x[0] not in (OP_NAME, OP_DECORATE, OP_MEMBERDECORATE): used.update(x[1:] if x[0] in NO_RESULT else x[3:])
        keep = [x for x in out if not (dead(x) and x[2] not in used)]
        if len(keep) == len(out): break
        out = keep
    hdr = list(hdr); hdr[3] = bound
    return hdr, out, True

def pos_var(ins):
    """→ (the position's Output variable, its member index in a gl_PerVertex block or None for a variable of its own), or None"""
    member_pos = {x[1]: x[2] for x in ins if x[0] == OP_MEMBERDECORATE and x[3] == DEC_BUILTIN and x[4] == BUILTIN_POSITION}   # struct id → member index
    direct_pos = {x[1] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BUILTIN and x[3] == BUILTIN_POSITION}
    ptr_pointee = {x[1]: (x[2], x[3]) for x in ins if x[0] == OP_TYPEPOINTER}   # pointer type → (storage, pointee)
    found = None
    for x in ins:
        if x[0] == OP_VARIABLE and x[3] == STORAGE_OUTPUT:
            st, pointee = ptr_pointee[x[1]]
            if x[2] in direct_pos: found = (x[2], None)
            elif pointee in member_pos: found = (x[2], member_pos[pointee])
    return found

def z_variant(hdr, ins):
    """Before each OpReturn of the entry point: position.z = (position.z + position.w) * 0.5"""
    bound = hdr[3]
    def new():
        nonlocal bound; bound += 1; return bound - 1
    entry = next(x[2] for x in ins if x[0] == OP_ENTRY)
    pv = pos_var(ins)
    if pv is None: return None
    var, idx = pv
    tf = next((x[1] for x in ins if x[0] == OP_TYPEFLOAT and x[2] == 32), None)
    tv4 = next((x[1] for x in ins if x[0] == OP_TYPEVECTOR and x[2] == tf and x[3] == 4), None)
    ti = next((x[1] for x in ins if x[0] == OP_TYPEINT and x[2] == 32 and x[3] == 1), None)
    if tf is None or tv4 is None: return None
    glob = []   # declarations added before the first function
    pv4 = next((x[1] for x in ins if x[0] == OP_TYPEPOINTER and x[2] == STORAGE_OUTPUT and x[3] == tv4), None)
    if pv4 is None: pv4 = new(); glob.append([OP_TYPEPOINTER, pv4, STORAGE_OUTPUT, tv4])
    half = new(); glob.append([OP_CONSTANT, tf, half, struct.unpack('<I', struct.pack('<f', 0.5))[0]])
    if idx is not None:
        if ti is None: ti = new(); glob.insert(0, [OP_TYPEINT, ti, 32, 1])
        cidx = new(); glob.append([OP_CONSTANT, ti, cidx, idx])
    out, in_entry, done_glob = [], False, False
    for x in ins:
        if x[0] == OP_FUNCTION and not done_glob: out.extend(glob); done_glob = True
        if x[0] == OP_FUNCTION: in_entry = x[2] == entry
        if x[0] == OP_FUNCTIONEND: in_entry = False
        if x[0] == OP_RETURN and in_entry:
            ptr = var
            if idx is not None: ptr = new(); out.append([OP_ACCESSCHAIN, pv4, ptr, var, cidx])
            p, z, w, sm, h, q = (new() for _ in range(6))
            out += [[OP_LOAD, tv4, p, ptr], [OP_COMPOSITEEXTRACT, tf, z, p, 2], [OP_COMPOSITEEXTRACT, tf, w, p, 3], [OP_FADD, tf, sm, z, w],
                    [OP_FMUL, tf, h, sm, half], [OP_COMPOSITEINSERT, tv4, q, h, p, 2], [OP_STORE, ptr, q]]
        out.append(x)
    hdr = list(hdr); hdr[3] = bound
    return emit(hdr, out)

# ---- The position's constant buffer rows read at run time (pos_rows) ----
OP_EXTINST, OP_FNEGATE, OP_FSUB, OP_SLESSTHAN, OP_COMPOSITECONSTRUCT, OP_COPYOBJECT_ = 12, 127, 131, 177, 80, 83
STORAGE_UNIFORM, STORAGE_FUNCTION, BUILTIN_INSTANCEINDEX, GLSL_FMA = 2, 7, 43, 50
OP_SPECCONSTANTFALSE, DEC_SPECID = 49, 1
POS_ROWS_SPEC = 7401   # the specialization constant (a bool, false unless the host sets it) that turns the run-time rows on: gfx_vk_posrows.inc POS_ROWS_SPEC_ID
def pos_rows(hdr, ins):
    """→ (header, instructions, reads changed). A vertex shader's constant buffer reads that its position is made of by arithmetic alone (OpFAdd, OpFSub, OpFMul,
    OpFNegate, Fma, copies, selects, and the Function variables the translator keeps each value in, when stored once) read their row as row + (on ? min(gl_InstanceIndex, 0) : 0):
    the same row (an instance index counts up from the draw's base instance, never below 0). `on` is a specialization constant (SpecId POS_ROWS_SPEC),
    false unless the host sets it: false, the zero is a constant and the row folds back to the constant one, so a GPU the host leaves alone compiles the
    shader as it did; true, the row is one the driver's compiler cannot know. Qualcomm's Adreno 740 driver
    (V@0676.32, the Ayn Odin 2) bins a pass with a position-only copy of each vertex shader that has other outputs; in Final Fantasy Resonance's vertex shader
    19274e72bf8f5d0d that copy read c3's rows 0-3 (Unreal's TranslatedWorldToClip, constant indices it loads ahead into constant registers) as garbage, the cards'
    triangles were binned nowhere and the field's flames never drew; the full shader read them right, as Turnip and the Adreno 830 did. A run-time row is loaded
    when it is read. These are the matrix the last transform multiplies by (16 reads in a shader of Unreal's); a value stored in more than one place ends the walk.
    Run-time rows cost GPU time (on in every vertex shader, Animal Crossing's island took 25% more on the Odin 2), so the host turns them on only on Qualcomm's
    Adreno 7xx driver and only for the vertex shaders a game's profile names (vk_pos_rows; gfx_vk_posrows.inc)"""
    pv = pos_var(ins)
    if pv is None: return hdr, ins, 0
    var, member = pv
    bound = hdr[3]
    def new():
        nonlocal bound; bound += 1; return bound - 1
    entry = next(x[2] for x in ins if x[0] == OP_ENTRY)
    const = {x[2]: x[3] for x in ins if x[0] == OP_CONSTANT}
    ctype = {x[2]: x[1] for x in ins if x[0] == OP_CONSTANT}
    ty = {x[1]: x for x in ins if x[0] in (OP_TYPEINT, OP_TYPEFLOAT, OP_TYPEVECTOR, OP_TYPEBOOL, OP_TYPESTRUCT_, OP_TYPEARRAY, OP_TYPERUNTIMEARRAY_)}
    ptr = {x[1]: (x[2], x[3]) for x in ins if x[0] == OP_TYPEPOINTER}
    glsl = {x[1] for x in ins if x[0] == 11 and ext_name([0, *x[2:]]) == 'GLSL.std.450'}
    defs, stores, fn = {}, {}, None   # result id → (instruction, function); pointer → the values stored through it
    for x in ins:
        op = x[0]
        if op == OP_FUNCTION: fn = x[2]
        elif op == OP_FUNCTIONEND: fn = None
        if op in (OP_LOAD, OP_ACCESSCHAIN, OP_FADD, OP_FSUB, OP_FMUL, OP_FNEGATE, OP_EXTINST, OP_COPYOBJECT_, OP_COMPOSITEEXTRACT, OP_COMPOSITECONSTRUCT, OP_SELECT, OP_VARIABLE):
            defs[x[2]] = (x, fn)
        elif op == OP_STORE: stores.setdefault(x[1], []).append(x[2])
    def row_of(c):   # an access chain into member 0 (an array) of a Uniform block, every index a constant of a 32-bit integer: → its row index, else None
        b = defs.get(c[3])
        if len(c) < 6 or not b or b[0][0] != OP_VARIABLE or b[0][3] != STORAGE_UNIFORM or const.get(c[4]) != 0 or any(i not in const for i in c[5:]): return None
        s = ty.get(ptr.get(b[0][1], (0, 0))[1])
        if not s or s[0] != OP_TYPESTRUCT_ or ty.get(s[2], [0])[0] != OP_TYPEARRAY: return None
        t = ty.get(ctype[c[5]])
        return c[5] if t and t[0] == OP_TYPEINT and t[2] == 32 else None
    todo = []   # the values stored into the position (the variable, or a chain into it: its member, then a component)
    for x in ins:
        if x[0] != OP_STORE: continue
        d = defs.get(x[1])
        if (x[1] == var and member is None) or (d and d[0][0] == OP_ACCESSCHAIN and d[0][3] == var and (member is None or const.get(d[0][4]) == member)):
            todo.append(x[2])
    marked, seen = set(), set()
    while todo:
        v = todo.pop()
        if v in seen or v not in defs: continue
        seen.add(v); x, f = defs[v]; op = x[0]
        if f != entry: continue
        if op in (OP_FADD, OP_FSUB, OP_FMUL): todo += x[3:5]
        elif op in (OP_FNEGATE, OP_COPYOBJECT_, OP_COMPOSITEEXTRACT): todo.append(x[3])
        elif op == OP_COMPOSITECONSTRUCT: todo += x[3:]
        elif op == OP_SELECT: todo += x[4:6]   # either value: the merged translator's bounded read, (test ? read : 0), cbsize_strip leaves with its test true
        elif op == OP_EXTINST and x[3] in glsl and x[4] == GLSL_FMA: todo += x[5:8]
        elif op == OP_LOAD and x[3] in defs:
            y, g = defs[x[3]]
            if y[0] == OP_ACCESSCHAIN and g == entry and row_of(y) is not None: marked.add(y[2])
            elif y[0] == OP_VARIABLE and y[3] == STORAGE_FUNCTION and len(stores.get(y[2], ())) == 1: todo.append(stores[y[2]][0])
    if not marked: return hdr, ins, 0
    glob, decs = [], []   # declarations added before the first function, decorations after the last
    tb = next((x[1] for x in ins if x[0] == OP_TYPEBOOL), None)
    if tb is None: tb = new(); glob.append([OP_TYPEBOOL, tb])
    iv = next((x[1] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BUILTIN and x[3] == BUILTIN_INSTANCEINDEX), None)
    it = ty.get(ptr.get(defs[iv][0][1], (0, 0))[1]) if iv in defs else None
    if it is None or it[0] != OP_TYPEINT or it[2] != 32:   # no gl_InstanceIndex: one is declared (a signed int, an Input of the entry point)
        rt = sorted({ctype[row_of(defs[c][0])] for c in marked})[0]
        pi = next((x[1] for x in ins if x[0] == OP_TYPEPOINTER and x[2] == STORAGE_INPUT and x[3] == rt), None)
        if pi is None: pi = new(); glob.append([OP_TYPEPOINTER, pi, STORAGE_INPUT, rt])
        iv = new(); glob.append([OP_VARIABLE, pi, iv, STORAGE_INPUT]); decs.append([OP_DECORATE, iv, DEC_BUILTIN, BUILTIN_INSTANCEINDEX]); it = ty[rt]; add_iv = True
    else: add_iv = False
    zero, head = {}, []   # row type → its zero, computed at the top of the entry point: on ? min(gl_InstanceIndex, 0) : 0
    on = new(); glob.append([OP_SPECCONSTANTFALSE, tb, on]); decs.append([OP_DECORATE, on, DEC_SPECID, POS_ROWS_SPEC])
    li = new(); head.append([OP_LOAD, it[1], li, iv])
    for t in sorted({ctype[row_of(defs[c][0])] for c in marked}):
        c0 = next((x[2] for x in ins if x[0] == OP_CONSTANT and x[1] == t and x[3] == 0), None)
        if c0 is None: c0 = new(); glob.append([OP_CONSTANT, t, c0, 0])
        v = li
        if t != it[1]: v = new(); head.append([OP_BITCAST, t, v, li])
        lt, m, z = new(), new(), new(); head += [[OP_SLESSTHAN, tb, lt, v, c0], [OP_SELECT, t, m, lt, v, c0], [OP_SELECT, t, z, on, m, c0]]; zero[t] = z
    last_dec = max(i for i, x in enumerate(ins) if x[0] in (OP_DECORATE, OP_MEMBERDECORATE))
    out, in_entry, labelled, done_glob = [], False, False, False
    for i, x in enumerate(ins):
        op = x[0]
        if op == OP_FUNCTION and not done_glob: out.extend(glob); done_glob = True
        if op == OP_FUNCTION: in_entry = x[2] == entry; labelled = False
        elif op == OP_FUNCTIONEND: in_entry = False
        if in_entry and labelled and head and op != OP_VARIABLE: out.extend(head); head = []   # after the first block's variables
        if in_entry and op == OP_LABEL: labelled = True
        if op == OP_ENTRY and add_iv: x = x + [iv]
        if op == OP_ACCESSCHAIN and in_entry and x[2] in marked:
            r = row_of(x); n = new(); out.append([OP_IADD, ctype[r], n, r, zero[ctype[r]]]); x = x[:5] + [n] + x[6:]
        out.append(x)
        if i == last_dec: out.extend(decs)
    hdr = list(hdr); hdr[3] = bound
    return hdr, out, len(marked)

OP_TYPEINT_, OP_TYPESTRUCT, OP_TYPERUNTIMEARRAY, OP_BITCAST, OP_IMUL, OP_IADD = 21, 30, 29, 124, 132, 128
STORAGE_INPUT, STORAGE_SB, DEC_LOCATION, DEC_BLOCK, DEC_ARRAYSTRIDE, DEC_OFFSET, DEC_BINDING, BUILTIN_VERTEXINDEX = 1, 12, 30, 2, 6, 35, 33, 42
def tf_variant(hdr, ins, tf):
    """Before each OpReturn of the entry point: buffer b's captured outputs (generic output n, its first c components) stored as uint bits at vertex × stride / 4 + their place"""
    bound = hdr[3]
    def new():
        nonlocal bound; bound += 1; return bound - 1
    entry_ins = next(x for x in ins if x[0] == OP_ENTRY); entry = entry_ins[2]
    loc = {x[1]: x[3] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_LOCATION}
    builtin = {x[1]: x[3] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BUILTIN}
    ptr = {x[1]: (x[2], x[3]) for x in ins if x[0] == OP_TYPEPOINTER}
    outs, vidx = {}, None
    for x in ins:
        if x[0] != OP_VARIABLE: continue
        if x[3] == STORAGE_OUTPUT and x[2] in loc: outs[loc[x[2]]] = (x[2], ptr[x[1]][1])
        if x[3] == STORAGE_INPUT and builtin.get(x[2]) == BUILTIN_VERTEXINDEX: vidx = (x[2], ptr[x[1]][1])
    tf_ = next((x[1] for x in ins if x[0] == OP_TYPEFLOAT and x[2] == 32), None)
    tv4 = next((x[1] for x in ins if x[0] == OP_TYPEVECTOR and x[2] == tf_ and x[3] == 4), None)
    ti = next((x[1] for x in ins if x[0] == OP_TYPEINT_ and x[2] == 32 and x[3] == 1), None)
    tu = next((x[1] for x in ins if x[0] == OP_TYPEINT_ and x[2] == 32 and x[3] == 0), None)
    glob, deco, iface = [], [], []
    if ti is None: ti = new(); glob.append([OP_TYPEINT_, ti, 32, 1])
    if tu is None: tu = new(); glob.append([OP_TYPEINT_, tu, 32, 0])
    if vidx is None:   # gl_VertexIndex, declared and listed in the entry point's interface
        pin = new(); v = new(); glob += [[OP_TYPEPOINTER, pin, STORAGE_INPUT, ti], [OP_VARIABLE, pin, v, STORAGE_INPUT]]
        deco.append([OP_DECORATE, v, DEC_BUILTIN, BUILTIN_VERTEXINDEX]); iface.append(v); vidx = (v, ti)
    consts = {}
    def cu(n):
        if n not in consts: c = new(); consts[n] = c; glob.append([OP_CONSTANT, tu, c, n])
        return consts[n]
    ci0 = new(); glob.append([OP_CONSTANT, ti, ci0, 0])
    rta, st, pst, pu = new(), new(), new(), new()
    glob += [[OP_TYPERUNTIMEARRAY, rta, tu], [OP_TYPESTRUCT, st, rta], [OP_TYPEPOINTER, pst, STORAGE_SB, st], [OP_TYPEPOINTER, pu, STORAGE_SB, tu]]
    deco += [[OP_DECORATE, rta, DEC_ARRAYSTRIDE, 4], [OP_DECORATE, st, DEC_BLOCK], [OP_MEMBERDECORATE, st, 0, DEC_OFFSET, 0]]
    bufs = {}
    for b, e in enumerate(tf):
        if not e: continue
        v = new(); glob.append([OP_VARIABLE, pst, v, STORAGE_SB]); deco += [[OP_DECORATE, v, DEC_DESCRIPTORSET, 0], [OP_DECORATE, v, DEC_BINDING, 100 + b]]; bufs[b] = v
    cu(0)
    for b, e in enumerate(tf):   # make the constants before the code uses them
        if not e: continue
        cu(e[1] // 4); at = 0
        for o, n in e[0]:
            for i in range(n): cu(at + i)
            at += n
    out, in_entry, done_glob, done_deco = [], False, False, False
    for x in ins:
        if x[0] == OP_ENTRY and x[2] == entry: x = x + iface
        if x[0] == OP_DECORATE and not done_deco: out.extend(deco); done_deco = True
        if x[0] == OP_FUNCTION and not done_glob: out.extend(glob); done_glob = True
        if x[0] == OP_FUNCTION: in_entry = x[2] == entry
        if x[0] == OP_FUNCTIONEND: in_entry = False
        if x[0] == OP_RETURN and in_entry:
            vi, vu = new(), new(); out += [[OP_LOAD, vidx[1], vi, vidx[0]], [OP_BITCAST, tu, vu, vi]]
            for b, e in enumerate(tf):
                if not e: continue
                base = new(); out.append([OP_IMUL, tu, base, vu, cu(e[1] // 4)]); at = 0
                for o, n in e[0]:
                    src = outs.get(o)
                    val = None
                    if src and src[1] == tv4: val = new(); out.append([OP_LOAD, tv4, val, src[0]])
                    for i in range(n):
                        bits = new()
                        if val is not None: c = new(); out += [[OP_COMPOSITEEXTRACT, tf_, c, val, i], [OP_BITCAST, tu, bits, c]]
                        else: bits = cu(0)   # an output the shader does not write: 0, as main0_tf stores
                        idx, p_ = new(), new()
                        out += [[OP_IADD, tu, idx, base, cu(at + i)], [OP_ACCESSCHAIN, pu, p_, bufs[b], ci0, idx], [OP_STORE, p_, bits]]
                    at += n
        out.append(x)
    hdr = list(hdr); hdr[3] = bound
    return emit(hdr, out)

# ---- Vertex inputs (gfx_vk_draw.inc pipe_get matches the vertex formats to them; spv_build.py re-translates integer inputs) ----
OP_TYPEPTR_, OP_COPYOBJECT = 32, 83
def vin_types(ins):
    """{location: 'f' | 'u' | 's'}: the component type of each vertex input as the shader declares it"""
    loc = {x[1]: x[3] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_LOCATION}
    builtin = {x[1] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BUILTIN}
    scal = {}
    for x in ins:
        if x[0] == OP_TYPEFLOAT: scal[x[1]] = 'f'
        elif x[0] == OP_TYPEINT_: scal[x[1]] = 's' if x[3] else 'u'
        elif x[0] == OP_TYPEVECTOR and x[2] in scal: scal[x[1]] = scal[x[2]]
    ptr = {x[1]: x[3] for x in ins if x[0] == OP_TYPEPTR_}
    return {str(loc[x[2]]): scal.get(ptr.get(x[1]), 'f') for x in ins if x[0] == OP_VARIABLE and x[3] == STORAGE_INPUT and x[2] in loc and x[2] not in builtin}
def int_inputs(ins):
    """Float-declared vertex inputs that the shader only uses as integers (every use a bit cast to an integer type, or a copy): {location: 'uint'} — dmsh_build.py
    int_inputs on the SPIR-V itself. Maxwell's fetch puts an integer format's bits into the register as they are (bone indices RGBA8UI); under a float declaration the
    translator's bit cast of a converted float gives garbage and skinned models stretch into streaks"""
    loc = {x[1]: x[3] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_LOCATION}
    builtin = {x[1] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BUILTIN}
    intty = {x[1] for x in ins if x[0] == OP_TYPEINT_}
    intty |= {x[1] for x in ins if x[0] == OP_TYPEVECTOR and x[2] in intty}
    fvars = {x[2] for x in ins if x[0] == OP_VARIABLE and x[3] == 7}   # Function storage: temporaries of the translator's debug mode
    vin = vin_types(ins); out = {}
    for x in ins:
        if not (x[0] == OP_VARIABLE and x[3] == STORAGE_INPUT and x[2] in loc and x[2] not in builtin and vin.get(str(loc[x[2]])) == 'f'): continue
        ptrs, vals, nint, bad = {x[2]}, set(), 0, False
        for _ in range(8):   # to a fixed point: chains, loads, extracts, copies through temporaries
            n0 = len(ptrs) + len(vals)
            for y in ins:
                op = y[0]
                if op == OP_ACCESSCHAIN and y[3] in ptrs: ptrs.add(y[2])
                elif op == OP_LOAD and y[3] in ptrs: vals.add(y[2])
                elif op in (OP_COMPOSITEEXTRACT, OP_COPYOBJECT) and y[3] in vals: vals.add(y[2])
                elif op == OP_STORE and y[2] in vals and y[1] in fvars: ptrs.add(y[1])
            if len(ptrs) + len(vals) == n0: break
        for y in ins:
            op = y[0]
            if op in (OP_ACCESSCHAIN, OP_LOAD, OP_COMPOSITEEXTRACT, OP_COPYOBJECT, OP_DECORATE, OP_ENTRY, OP_VARIABLE, OP_MEMBERDECORATE): continue
            if op == OP_STORE:
                if y[2] in vals and y[1] not in fvars: bad = True   # stored elsewhere as a float
                continue
            if op == OP_BITCAST and y[3] in vals:
                if y[1] in intty: nint += 1
                else: bad = True
                continue
            if any(w in vals for w in y[3:]): bad = True
        if not bad and nint: out[str(loc[x[2]])] = 'uint'
    return out

# ---- How much of each constant buffer the shader reads (res.json cbufs[].ext; gfx_vk_draw.inc sh_get prefers it to its own scan) ----
# The translator declares every constant buffer as 4096 vec4 (64 KB) and the replay copies, for every draw, as many bytes of the bound buffer as the shader can read. The host's
# SPIR-V scan (spv_cb_ext2) takes the largest constant element index; an index computed at run time keeps the whole buffer. Here such an index is evaluated: the integer slice of
# each function (32-bit scalars in SSA values and in Function / Private variables only loaded and stored, the translator's debug-mode registers) is run along every path with
# each value a small set (up to CB_SET values, one along a path that only met known values), a branch on a known value taking its side and one on an unknown value (a float
# compare, a uniform) both; each block keeps the distinct states it was entered with (only the values live there), so a loop with a known trip count is unrolled, its exit
# predicate tested wherever the code tests it. Breath of the Wild's vertex shader 5ee9a682fff60855 counts %116 from 2 down in a do-while whose exit test, %122 <= 1, is a bool
# local set in the body and branched on in the latch (%584): an interval analysis widening at the header leaves the counter unbounded below, (i << 4) + 352 able to wrap
# anywhere; run so the counter is 2 or 1 and c3 reads elements 0-24, 400 bytes instead of 64 KB (222 draws a frame on the Odin 2, 29 MB of copies with ucopy's shadow).
# A value stays unknown where it comes from a float, a vector, a call or an op not modelled, or a variable read before any store; an unknown operand still bounds x & m, x % c,
# x >> s, a bit field and a select (_cb_eval); a block entered with more than CB_STATES states joins them (each value the union, unknown past CB_SET), so a loop bounded by a
# uniform ends. Sound by construction: an unknown index (the whole declared array), an index outside the array, an access chain in a block the run never reached, any use of
# the variable other than an access chain from member 0, a layout other than vec4 at stride 16, or a run past CB_STEPS keeps the whole buffer (ext 0, as the host reads a missing
# one). Breath of the Wild's 19,592 shaders: of 63,480 constant buffer bindings the old word-match scan bounded 41,837, spv_cb_ext2 59,263 and this 59,965, never below either
# (and, on the 17,734 keys the Mac's cb_extent.tsv shares, never below its extent, 631 bounded where it has none); its dumped frame reads 26.2 MB of constant buffers with the old
# extents, 21.0 MB with spv_cb_ext2's, 6.6 MB with these
CB_STATES, CB_STEPS, CB_SET, CB_BITS = 64, 3_000_000, 16, 4
M32 = 0xffffffff
TERMINATORS = {249, 250, 251, 252, 253, 254, 255, 4416, 4448, 4449, 5294}
NO_RESULT = {0, 8, 56, 62, 63, 64, 99, 218, 219, 220, 221, 224, 225, 228, 246, 247, 248, 256, 257, 317, 5364, 5365, 5380} | TERMINATORS

def spv_lit(op, q):
    """Word q of an instruction with opcode op in a function body is a literal, never an id (gfx_vk_draw.inc spv_lit, the same table): an unknown opcode has every
    word taken for an id, which can only make a use seen where there is none"""
    if op in (8, 317): return True
    if op == 12: return q == 4
    if op in (54, 59): return q == 3
    if op == 61: return q >= 4
    if op in (62, 63): return q >= 3
    if op == 64: return q >= 4
    if op in (79, 82): return q >= 5
    if op == 81: return q >= 4
    if op == 246: return q >= 3
    if op in (247, 256, 257): return q == 2
    if op == 250: return q >= 4
    if op == 251: return q >= 3
    if op in (87, 88, 91, 92, 95, 98, 305, 306, 309, 310, 313, 320): return q == 5
    if op in (89, 90, 93, 94, 96, 97, 307, 308, 311, 312, 314, 315): return q == 6
    if op == 99: return q == 4
    if op == 342: return q == 4
    return 349 <= op <= 364 and q == 4

def _s32(v): return v - (1 << 32) if v & 0x80000000 else v

def _bin(op, a, b):
    """A 32-bit binary op on known operands (raw bits), None if undefined or not modelled"""
    if op == 128: return (a + b) & M32
    if op == 130: return (a - b) & M32
    if op == 132: return (a * b) & M32
    if op == 134: return a // b if b else None
    if op == 137: return a % b if b else None
    if op in (135, 138, 139):
        sa, sb = _s32(a), _s32(b)
        if not sb or (sa == -0x80000000 and sb == -1): return None
        q = abs(sa) // abs(sb) * (1 if (sa < 0) == (sb < 0) else -1)
        if op == 135: return q & M32
        r = sa - q * sb   # OpSRem: the dividend's sign
        if op == 139 and r and (r < 0) != (sb < 0): r += sb   # OpSMod: the divisor's sign
        return r & M32
    if op in (194, 195, 196):   # shifts: a shift by the width or more is undefined
        if b >= 32: return None
        return a >> b if op == 194 else (_s32(a) >> b) & M32 if op == 195 else (a << b) & M32
    if op == 197: return a | b
    if op == 198: return a ^ b
    if op == 199: return a & b
    if op == 164: return int(a == b)
    if op == 165: return int(a != b)
    if op == 166: return int(bool(a or b))
    if op == 167: return int(bool(a and b))
    if op == 170: return int(a == b)
    if op == 171: return int(a != b)
    if op == 172: return int(a > b)
    if op == 173: return int(_s32(a) > _s32(b))
    if op == 174: return int(a >= b)
    if op == 175: return int(_s32(a) >= _s32(b))
    if op == 176: return int(a < b)
    if op == 177: return int(_s32(a) < _s32(b))
    if op == 178: return int(a <= b)
    if op == 179: return int(_s32(a) <= _s32(b))
    return None
BIN_OPS = {128, 130, 132, 134, 135, 137, 138, 139, 164, 165, 166, 167, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 194, 195, 196, 197, 198, 199}

def cb_extents(ins, bindings, why=None):
    """{binding: bytes the shader can read of that constant buffer, a multiple of 16; 0 = all of it} for the bindings listed (res.json cbufs); why, a dict, gets the reason
    for each binding left whole"""
    want = set(bindings); full = {b: '' for b in want}; high = {b: -1 for b in want}
    def whole(b, r): full[b] = full[b] or r
    if any(x[0] in (73, 74, 75, 67, 70) for x in ins):   # decoration groups, pointer arithmetic: not followed
        if why is not None: why.update({b: 'decoration groups or pointer arithmetic' for b in want})
        return {b: 0 for b in want}
    bind, stride, off_nz, types, consts, glsl = {}, {}, set(), {}, {}, set()
    for x in ins:
        op = x[0]
        if op == 71 and len(x) >= 4 and x[2] == 33: bind[x[1]] = x[3]
        elif op == 71 and len(x) >= 4 and x[2] == 6: stride[x[1]] = x[3]
        elif op == 72 and len(x) >= 5 and x[2] == 0 and x[3] == 35 and x[4]: off_nz.add(x[1])
        elif 19 <= op <= 39: types[x[1]] = x
        elif op == 43 and len(x) == 4: consts[x[2]] = x[3]
        elif op == 41: consts[x[2]] = 1
        elif op == 42 or op == 46: consts[x[2]] = 0   # OpConstantNull: kept only for the scalar types below
        elif op == 11 and ext_name([0, *x[2:]]) == 'GLSL.std.450': glsl.add(x[1])
    def sc32(t):   # a 32-bit scalar (bool as 0 / 1)
        d = types.get(t)
        return d is not None and (d[0] == 20 or (d[0] in (21, 22) and d[2] == 32))
    for x in ins:   # only 32-bit scalars' constants are held (an 8- or 16-bit one is one word too)
        if x[0] in (41, 42, 43, 46) and not sc32(x[1]): consts.pop(x[2], None)
    # the buffers' variables: Uniform, member 0 an array of 4-component 32-bit vectors at stride 16
    cbvar, arrlen = {}, {}
    for x in ins:
        if x[0] != 59 or bind.get(x[2]) not in want: continue
        b = bind[x[2]]; cbvar[x[2]] = b
        p = types.get(x[1]); s = types.get(p[3]) if p and p[0] == 32 else None
        a = types.get(s[2]) if s and s[0] == 30 and len(s) > 2 and s[1] not in off_nz else None
        e = types.get(a[2]) if a and a[0] == 28 and stride.get(a[1]) == 16 and a[3] in consts else None
        if x[3] != 2 or not e or e[0] != 23 or e[3] != 4 or not sc32(e[2]) or types[e[2]][0] == 20: whole(b, 'layout')
        else: arrlen[x[2]] = consts[a[3]]
    if not cbvar: return {b: 16 for b in want}   # declared, never read: the descriptor wants a range, the shader reads none of it
    # the integer registers: Function / Private variables of a 32-bit scalar, used only as the pointer of OpLoad and OpStore
    reg = {x[2]: x[3] for x in ins if x[0] == 59 and x[3] in (6, 7) and types.get(x[1], [0])[0] == 32 and sc32(types[x[1]][3])}
    init = {x[2]: consts[x[4]] for x in ins if x[0] == 59 and x[2] in reg and len(x) >= 5 and x[4] in consts}
    chains = []   # (function index, block index, instruction index, variable, element id) of the access chains whose element is not a constant
    funcs, fn, blk = [], None, None
    entry = {x[2] for x in ins if x[0] == 15} - {x[3] for x in ins if x[0] == 57}   # entry points no call reaches: the Private registers start from their initializers there
    for x in ins:
        op = x[0]
        if op == 54: fn = {'blocks': [], 'entry': x[2] in entry}; funcs.append(fn); continue
        if fn is None:
            if op == 59 and len(x) >= 5 and x[4] in cbvar: whole(cbvar[x[4]], 'initializer')   # a global variable initialized with it
            continue
        if op == 56: fn = blk = None; continue
        if op == 248: blk = [x[1], []]; fn['blocks'].append(blk); continue
        if op == 55: continue   # a parameter: unknown
        for q in range(1, len(x)):
            w = x[q]
            if spv_lit(op, q) or (op == 59 and q == 2): continue   # (a Function variable's own declaration)
            if w in reg and not ((op == 61 and q == 3) or (op == 62 and q == 1)): del reg[w]
            if w in cbvar:
                b = cbvar[w]
                if op in (65, 66) and q == 3 and len(x) >= 6 and consts.get(x[4], 1) == 0 and w in arrlen:
                    if x[5] in consts:
                        if consts[x[5]] >= arrlen[w]: whole(b, 'constant index past the array')
                        else: high[b] = max(high[b], consts[x[5]])
                    elif blk is not None: chains.append((len(funcs) - 1, len(fn['blocks']) - 1, len(blk[1]), w, x[5]))
                    else: whole(b, 'access chain outside a block')
                else: whole(b, 'used other than by an access chain from member 0')
        if blk is not None: blk[1].append(x)
    chains = [c for c in chains if not full[cbvar[c[3]]]]
    if chains:
        seen = _cb_run(funcs, chains, consts, reg, init, glsl, sc32)
        for c in chains:
            b = cbvar[c[3]]
            if seen is None: whole(b, 'run past CB_STEPS'); continue
            v = seen.get(c, 'unreached')
            if v == 'unreached': whole(b, 'index in a block the run never reached')
            elif v is None:   # any element of the declared array
                if 16 * arrlen[c[3]] >= 0x10000: whole(b, 'index unknown')
                else: high[b] = max(high[b], arrlen[c[3]] - 1)
            elif v >= arrlen[c[3]]: whole(b, 'index past the array')
            else: high[b] = max(high[b], v)
    for b in want:
        if not full[b] and 16 * (high[b] + 1) >= 0x10000: whole(b, 'reads the last element')
    if why is not None: why.update({b: r for b, r in full.items() if r})
    return {b: 0 if full[b] else 16 * max(high[b] + 1, 1) for b in want}

def _cb_join(a, b):
    out = {}
    for k, v in a.items():
        w = b.get(k)
        if w is not None and len(v | w) <= CB_SET: out[k] = v | w
    return out

def _submasks(m):
    out, s = [], m
    while True:
        out.append(s)
        if not s: return out
        s = (s - 1) & m

def _cb_one(x, a, glsl):
    """Instruction x's 32-bit result for known operand values a (x[3:], an OpExtInst's x[5:]); None if undefined or not modelled"""
    op = x[0]
    if op in BIN_OPS: return _bin(op, a[0], a[1]) if len(a) == 2 else None
    if op in (124, 83): return a[0] if len(a) == 1 else None   # a known value is a 32-bit scalar's (nothing else is held), so its bits are the result's
    if op == 126: return -a[0] & M32
    if op == 200: return ~a[0] & M32
    if op == 168: return 1 - a[0]
    if op == 205: return bin(a[0]).count('1')
    if op == 169 and len(a) == 3: return a[1] if a[0] else a[2]
    if op in (202, 203) and len(a) == 3:
        v, o, n = a
        if o + n > 32: return None
        r = (v >> o) & ((1 << n) - 1) if n else 0
        return (r - (1 << n)) & M32 if op == 202 and n and r >> (n - 1) & 1 else r
    if op == 201 and len(a) == 4:
        v, ins_, o, n = a
        if o + n > 32: return None
        m = ((1 << n) - 1) << o; return (v & ~m | ins_ << o & m) & M32
    if op == 12 and x[3] in glsl:
        e = x[4]
        if e == 5 and len(a) == 1: return abs(_s32(a[0])) & M32   # SAbs
        if e in (38, 41) and len(a) == 2: return (min if e == 38 else max)(a)   # UMin, UMax
        if e in (39, 42) and len(a) == 2: return (min if e == 39 else max)(a, key=_s32)   # SMin, SMax
        if e == 44 and len(a) == 3 and a[1] <= a[2]: return min(max(a[0], a[1]), a[2])   # UClamp (undefined for min > max)
        if e == 45 and len(a) == 3 and _s32(a[1]) <= _s32(a[2]): return min(max(a[0], a[1], key=_s32), a[2], key=_s32)   # SClamp
    return None

def _cb_eval(x, val, glsl):
    """The set of values instruction x (a 32-bit scalar result) can take, None if unknown: each combination of its operands' known values, or what an operand left
    unknown still allows (x & m: the submasks of m; x % c and x >> s: the values below c and 2^(32 - s); a field of n bits: the values below 2^n; a select of known
    values: either; a product or an AND with 0, an AND with false, an OR with true)"""
    op = x[0]
    if not (op in BIN_OPS or op in (124, 83, 126, 200, 168, 205, 169, 201, 202, 203) or (op == 12 and x[3] in glsl)): return None
    args = [val(w) for w in (x[5:] if op == 12 else x[3:])]
    if None not in args:
        n = 1
        for v in args: n *= len(v)
        if n > CB_SET * CB_SET: return None
        out = set()
        for a in itertools.product(*args):
            r = _cb_one(x, a, glsl)
            if r is None: return None
            out.add(r)
        return frozenset(out) if len(out) <= CB_SET else None
    one = lambda k: next(iter(args[k])) if args[k] is not None and len(args[k]) == 1 else None
    if len(args) == 2 and op in (132, 199, 167) and frozenset((0,)) in args: return frozenset((0,))
    if len(args) == 2 and op == 166 and frozenset((1,)) in args: return frozenset((1,))
    if len(args) == 2 and op == 199:
        m = one(0) if args[0] is not None else one(1)
        if m is not None and bin(m).count('1') <= CB_BITS: return frozenset(_submasks(m))
    if len(args) == 2 and op == 137 and args[0] is None and one(1) is not None and 0 < one(1) <= CB_SET: return frozenset(range(one(1)))
    if len(args) == 2 and op == 194 and args[0] is None and one(1) is not None and 32 - CB_BITS <= one(1) < 32: return frozenset(range(1 << (32 - one(1))))
    if len(args) == 3 and op == 203 and args[0] is None and one(1) is not None and one(2) is not None and one(2) <= CB_BITS and one(1) + one(2) <= 32: return frozenset(range(1 << one(2)))
    if len(args) == 3 and op == 169 and args[1] is not None and args[2] is not None and len(args[1] | args[2]) <= CB_SET: return args[1] | args[2]
    return None

def _cb_run(funcs, chains, consts, reg, init, glsl, sc32):
    """{chain: the largest element index it takes (unsigned), None if unknown} for the chains whose block the run reached; None after CB_STEPS instructions"""
    want = {}
    for c in chains: want.setdefault((c[0], c[1], c[2]), []).append(c)
    out, steps = {}, 0
    rtype = {}
    for f in funcs:
        for _, body in f['blocks']:
            for x in body:
                if x[0] not in NO_RESULT and len(x) > 2: rtype[x[2]] = x[1]
    private = [v for v, cls in reg.items() if cls == 6]
    names = set(reg) | {r for r, t in rtype.items() if sc32(t)}   # what a state holds: registers, 32-bit scalar SSA values
    for fi, f in enumerate(funcs):
        blocks = f['blocks']
        if not blocks: continue
        at = {lab: i for i, (lab, _) in enumerate(blocks)}
        # liveness of those names: a state entering a block keeps only the live ones, so paths that differ in dead temporaries meet again; a value dropped is only
        # unknown, so this decides precision, never soundness
        gen, kill, succ = [], [], []
        for lab, body in blocks:
            g, k = set(), set()
            for x in body:
                op = x[0]
                if op == 62:
                    if x[2] in names and x[2] not in k: g.add(x[2])
                    if x[1] in reg: k.add(x[1])
                    continue
                first = 1 if op in NO_RESULT else 3
                for w in x[first:]:
                    if w in names and w not in k: g.add(w)
                if op not in NO_RESULT and len(x) > 2 and x[2] in names: k.add(x[2])
                if op == 245:   # an OpPhi's operands are read on the edges into its block, not in it
                    for w in x[3:]: g.discard(w)
            t = body[-1] if body else [253]
            s = [at[w] for w in (t[2:4] if t[0] == 250 else t[1:2] if t[0] == 249 else t[2:] if t[0] == 251 else []) if w in at]
            gen.append(g); kill.append(k); succ.append(s)
        phis = [[x for x in body if x[0] == 245] for _, body in blocks]
        for i, ps in enumerate(phis):   # the phi operands are live out of their predecessors
            for x in ps:
                for j in range(3, len(x) - 1, 2):
                    if x[j + 1] in at and x[j] in names: gen[at[x[j + 1]]].add(x[j])
        live = [set() for _ in blocks]
        changed = True
        while changed:
            changed = False
            for i in range(len(blocks) - 1, -1, -1):
                lo = set()
                for s in succ[i]: lo |= live[s]
                li = gen[i] | (lo - kill[i])
                if li != live[i]: live[i] = li; changed = True
        st0 = {v: frozenset((init[v],)) for v in private if v in init} if f['entry'] else {}   # a state holds sets of values, as the stores and declarations put them
        seen = [set() for _ in blocks]; wide = [None] * len(blocks)
        work = [(0, st0)]
        def enter(i, st):
            st = {k: v for k, v in st.items() if k in live[i]}
            if wide[i] is not None:
                j = _cb_join(wide[i], st)
                if j != wide[i]: wide[i] = j; work.append((i, j))
                return
            key = frozenset(st.items())
            if key in seen[i]: return
            seen[i].add(key)
            if len(seen[i]) > CB_STATES:   # joined: each value the union of the states' (unknown past CB_SET values or where one state has none)
                j = None
                for k2 in seen[i]: j = dict(k2) if j is None else _cb_join(j, dict(k2))
                wide[i] = j; work.append((i, j))
            else: work.append((i, st))
        while work:
            i, st = work.pop()
            d = dict(st); body = blocks[i][1]
            steps += len(body)
            if steps > CB_STEPS: return None
            def val(w): return frozenset((consts[w],)) if w in consts else d.get(w)
            for n, x in enumerate(body):
                op = x[0]
                if (fi, i, n) in want:
                    for c in want[(fi, i, n)]:
                        v = val(c[4]); o = out.get(c, -1)
                        out[c] = None if v is None or o is None else max(o, max(v))
                if op == 61:
                    if x[3] in reg and x[3] in d: d[x[2]] = d[x[3]]
                    else: d.pop(x[2], None)
                    continue
                if op == 62:
                    if x[1] in reg:
                        v = val(x[2])
                        if v is None: d.pop(x[1], None)
                        else: d[x[1]] = v
                    continue
                if op == 59:
                    if x[2] in reg and len(x) >= 5 and x[4] in consts: d[x[2]] = frozenset((consts[x[4]],))
                    else: d.pop(x[2], None)
                    continue
                if op == 57:   # a call: its result unknown, and what it may have stored in the Private registers
                    for v in private: d.pop(v, None)
                    d.pop(x[2], None); continue
                if op in NO_RESULT or op == 245 or len(x) < 3: continue
                r = _cb_eval(x, val, glsl) if sc32(x[1]) else None
                if r is None: d.pop(x[2], None)
                else: d[x[2]] = r
            t = body[-1] if body else [253]
            if t[0] == 249: nxt = [t[1]]
            elif t[0] == 250:
                c = val(t[1]); nxt = [t[2], t[3]] if c is None else [t[2]] * (1 in c) + [t[3]] * (0 in c)
            elif t[0] == 251:
                c = val(t[1])
                if c is None: nxt = [w for w in t[2:] if w in at]   # every word that names a block: the cases' labels and perhaps a literal, more successors only
                else:   # known, so a 32-bit selector: one word per case literal, t = [251, selector, default, literal 1, label 1, literal 2, label 2, ...]
                    case = {t[j]: t[j + 1] for j in range(len(t) - 2, 2, -2)}   # the pairs from the last down, so the first of equal literals wins
                    nxt = sorted({case.get(v, t[2]) for v in c})
            else: nxt = []
            for lab in nxt:
                if lab not in at: continue
                j = at[lab]; s2 = dict(d)
                for x in phis[j]:
                    v = None
                    for k in range(3, len(x) - 1, 2):
                        if x[k + 1] == blocks[i][0]: v = val(x[k]) if sc32(x[1]) else None
                    if v is None: s2.pop(x[2], None)
                    else: s2[x[2]] = v
                enter(j, s2)
    return out

def add_ext(res, ins):
    """res.json's cbufs get their ext (cb_extents); → (bounded, whole) counts"""
    cb = res.get('cbufs') or []
    ext = cb_extents(ins, [c['binding'] for c in cb])
    for c in cb: c['ext'] = ext[c['binding']]
    return sum(1 for c in cb if c['ext']), sum(1 for c in cb if not c['ext'])

def upgrade(out, key):
    """An output of chain EXT_FROM made this chain's: its res.json gets the extents of its .spv (spv_build.py)"""
    rp = out / f'{key}.res.json'; res = json.loads(rp.read_text(encoding='utf-8'))
    add_ext(res, parse((out / f'{key}.spv').read_bytes())[1]); res['android'] = EXT_FROM + 1   # the chain this makes, not ANDROID_CHAIN: after a later bump, retranslated
    rp.write_text(json.dumps(res), encoding='utf-8')

def post(src, dst, k):
    """Shader k of folder src made ready, its files written into dst → (its counts for main's summary: depth variant, without one, extents known, read whole, size table
    taken out, run-time row reads, a compute form made; the lines it prints). A pool job's result is these few numbers and lines, never the shader's bytes"""
    try: return post_one(src, dst, k)
    except Exception as e: e.add_note(f'shader {k} in {src}'); raise   # the pool runs shaders out of order: the traceback names the one that stopped it

def put(p, data):   # a file written whole or not at all: to a temporary name, then renamed (a full disk midway leaves no cut-short file under the real name)
    t = p.with_name(p.name + '.tmp'); t.write_bytes(data); os.replace(t, p)

def lost(dst, k, why):   # a shader whose translator output can't be read: its line, and no res.json of an older run left, so it counts as not translated and is translated again
    (dst / f'{k}.res.json').unlink(missing_ok=True)
    return (0, 0, 0, 0, 0, 0, 0), [f"[RED] {k}: the translator's output can't be read: {why} (a write that failed, as on a full disk): not translated"]

def post_one(src, dst, k):
    try: res = json.loads((src / f'{k}.res.json').read_text(encoding='utf-8'))
    except FileNotFoundError: return lost(dst, k, 'no .res.json')
    except ValueError: return lost(dst, k, '.res.json empty or cut short')
    data = (src / f'{k}.spv').read_bytes()
    if why := unreadable(data): return lost(dst, k, f'.spv {why}')
    stage = res.get('stage', 'vs'); lines = []; nz = bad = ncs = nrows = nemu = 0; files = {}   # its files besides res.json, written before it (put): res.json makes it translated
    cs = next((c['binding'] for c in res.get('cbufs') or [] if c.get('slot') == CBSIZE_BANK), None)
    if res.get('mesh'):   # a task or mesh shader translated as compute (spv_build.py): the stage module, and a mesh shader's depth -1..1 variant
        import spv_mesh
        mesh = res.pop('mesh'); stage = res['stage'] = mesh['info']['kind']
        kernel = data
        try:
            plain, res['prim_locs'] = spv_mesh.wrap(data, mesh['info'], mesh['lay'])
            zdata = spv_mesh.wrap(data, mesh['info'], mesh['lay'], gl=True)[0] if stage == 'ms' else None
        except ValueError as e:
            return (0, 1, 0, 0, 0, 0, 0), [f'[RED] {k}: {e}: no {"task" if stage == "ts" else "mesh"} module']
        data = plain
        if zdata:
            zh, zi, _, _ = process(zdata, stage, cs); files['.z.spv'] = emit(zh, zi); nz = 1
        try:   # the emulation's forms (spv_meshemu.py): what a GPU without VK_EXT_mesh_shader runs instead (gfx_vk_meshemu.inc)
            import spv_meshemu
            cdata, keep = spv_meshemu.compute(kernel, mesh['info'], mesh['lay'])
            ch, ci, _, _ = process(cdata, 'cs', cs, keep); files['.cs.spv'] = emit(ch, ci)
            if stage == 'ms':
                files['.pvs.spv'] = spv_meshemu.vertex(mesh['info'])
                files['.pvs.z.spv'] = spv_meshemu.vertex(mesh['info'], gl=True)
            res['mesh_emu'] = spv_meshemu.facts(mesh['info']); nemu = 1
        except ValueError as e:
            lines.append(f'[RED] {k}: {e}: no compute form (a GPU without VK_EXT_mesh_shader skips its draws)'); res['mesh_emu'] = None
    hdr, ins, interlock, stripped = process(data, stage, cs)
    if interlock: res.setdefault('notes', []).append('android: fragment shader interlock removed (no ordering of overlapping fragments)')
    if stripped: res['cbufs'] = [c for c in res['cbufs'] if c.get('slot') != CBSIZE_BANK]; ncs = 1
    elif stripped is False: lines.append(f'[RED] {k}: the uniform slots\' size table (c{CBSIZE_BANK}) is used other than the translator\'s bound tests use it: left in (it loses the device on Adreno 830)')
    res['set'] = SET_OF.get(stage, 0); res['android'] = ANDROID_CHAIN
    eb, ew = add_ext(res, ins)
    if stage == 'vs':   # after add_ext: a run-time row would keep the whole buffer, and it reads the rows the constant one did
        hdr, ins, nrows = pos_rows(hdr, ins)
        res['vin'] = vin_types(ins)
    files['.spv'] = emit(hdr, ins)
    if stage == 'vs' and res.get('tf'):
        files['.tf.spv'] = tf_variant(hdr, ins, res['tf'])
    if stage == 'vs':
        z = z_variant(hdr, ins)
        if z: files['.z.spv'] = z; nz = 1
        else: bad = 1; lines.append(f'[RED] {k}: no position output found, no depth -1..1 variant')
    for suffix, b in files.items(): put(dst / f'{k}{suffix}', b)
    put(dst / f'{k}.res.json', json.dumps(res).encode())   # last: a shader whose res.json is there has all its files (spv_build.py skips it on the next run)
    return (nz, bad, eb, ew, ncs, nrows, nemu), lines

CHUNK = 16   # shaders per pool job: ~0.8 s of work on average, so the pipe's round trips cost nothing and the last jobs still spread over the processes

def jobs_default():
    return (getattr(os, 'process_cpu_count', None) or os.cpu_count)() or 4   # the CPUs this process may use (3.13+), else the machine's

def pool_size(j, n):   # processes for n shaders with -j j: 1 means none started
    if sys.platform == 'win32': j = min(j, 61)   # ProcessPoolExecutor's limit on Windows (WaitForMultipleObjects); spv_build.py passes os.cpu_count()
    return max(1, min(j, -(-n // CHUNK)))   # no more processes than jobs: a few shaders (an update's) are done here, with no pool to start

def main():
    a = sys.argv[1:]; j = jobs_default()
    if a[:1] == ['-j']: j = int(a[1]); a = a[2:]
    src, dst = Path(a[0]), Path(a[1]); dst.mkdir(parents=True, exist_ok=True)
    keys = a[2:] or sorted(p.stem for p in src.glob('*.spv') if not p.name.endswith('.reader.spv'))
    one = functools.partial(post, src, dst)
    nz = bad = eb = ew = ncs = npr = nrows = nemu = 0
    ex = None
    if (n := pool_size(j, len(keys))) > 1:   # spawn on every host, as Windows has only spawn: the Mac's runs and tests cover what Windows runs
        ex = cf.ProcessPoolExecutor(n, mp_context=multiprocessing.get_context('spawn'))
    try:
        for (z, b, e, w, c, r, m), lines in (ex.map(one, keys, chunksize=CHUNK) if ex else map(one, keys)):   # in key order, as one process prints them
            for ln in lines: print(ln)
            nz += z; bad += b; eb += e; ew += w; ncs += c; nrows += r; npr += r > 0; nemu += m
    except BaseException:
        if ex: ex.shutdown(cancel_futures=True)   # a shader that stops the post-pass stops it at once, not after every other job
        raise
    if ex: ex.shutdown()
    print(f'spv_android: {len(keys)} shaders, {nz} depth variants, {bad} without one; constant buffers: {eb} with a known extent, {ew} read whole; the size table taken out of {ncs}; position rows read at run time in {npr} vertex shaders ({nrows} reads)'
          + (f'; {nemu} task / mesh shaders in compute form too' if nemu else ''))

if __name__ == '__main__':
    main()
