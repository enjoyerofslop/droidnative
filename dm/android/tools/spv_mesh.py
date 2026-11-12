# NVN2 task and mesh shaders as Vulkan task and mesh shaders (VK_EXT_mesh_shader), for the Android Vulkan replay (dm/android/gfx_vk_draw.inc vk_mesh_draw).
#
# The translator reads a task or mesh shader as compute, its SPH taken off and its stage memory in shared memory (dm/gfx/tools/dmsh_meshstage.py, which wraps
# that kernel into a Metal object or mesh function for the Mac). This does the same for SPIR-V: the translated kernel stays as it is, a void function with its
# early returns, and a new entry point (TaskEXT or MeshEXT) zeroes the stage memory, fills its inputs, calls the kernel and hands its outputs to Vulkan. The
# stage memory's layout is dmsh_meshstage.memory's, read from the same control section facts (dmsh_meshstage.info):
#   task  word 0 = the draw's first workgroup + its own; after the kernel, the payload words go to a TaskPayloadWorkgroupEXT array and OpEmitMeshTasksEXT
#         launches payload word 1 mesh workgroups
#   mesh  with a task: the payload copied in, then word 0 and input word 0 = its workgroup among the task's launches; with none: word 0 = first + its own.
#         After the kernel: OpSetMeshOutputsEXT(max vertices, the primitive count at byte 3 of the primitive area), then each thread copies vertices,
#         primitives and index bytes (lid, lid + threads, ...) out of the attribute blocks of 32
# The draw's first workgroup comes in a push constant (offset 0, gfx_vk_draw.inc MESH_PC_BYTES). Each generic output is a vec4, as the translator's vertex
# shaders write theirs; components the SPH does not enable are (0, 0, 0, 1), what the hardware gives. gl: the -1..1 depth variant (z' = (z + w) / 2, as
# spv_android.z_variant gives a vertex shader). Modules come out as SPIR-V 1.4, which VK_EXT_mesh_shader needs: every global goes in the entry point's interface.
# The design follows nxnative's Metal wrapper; Banana Native (git.eden-emu.dev/moceure/BananaNative) showed Qualcomm's Adreno 840 driver drawing NVN2 mesh
# programs through VK_EXT_mesh_shader with vec4 outputs. No code is taken from either. The zeroed locals and the mesh kernel's NoContraction are the ideas of DeathKhan's
# nx2android fork (github.com/DeathKhan/nx2android, b77d948 and fe4ca70, for its mesh shaders emulated in compute), written anew here.
import struct

# SPIR-V numbers (the unified grammar, SPV_EXT_mesh_shader)
OP_NAME, OP_EXTENSION, OP_EXTINSTIMPORT, OP_MEMORYMODEL, OP_ENTRY, OP_EXECMODE, OP_CAPABILITY = 5, 10, 11, 14, 15, 16, 17
OP_TYPEVOID, OP_TYPEBOOL, OP_TYPEINT, OP_TYPEFLOAT, OP_TYPEVECTOR, OP_TYPEARRAY, OP_TYPESTRUCT, OP_TYPEPOINTER, OP_TYPEFUNCTION = 19, 20, 21, 22, 23, 28, 30, 32, 33
OP_CONSTANTNULL = 46
OP_CONSTANT, OP_FUNCTION, OP_FUNCTIONEND, OP_FUNCTIONCALL, OP_VARIABLE, OP_LOAD, OP_STORE, OP_ACCESSCHAIN = 43, 54, 56, 57, 59, 61, 62, 65
OP_DECORATE, OP_MEMBERDECORATE, OP_COMPOSITECONSTRUCT, OP_COMPOSITEEXTRACT, OP_BITCAST, OP_IADD, OP_FADD, OP_IMUL, OP_FMUL = 71, 72, 80, 81, 124, 128, 129, 132, 133
OP_ULESSTHAN, OP_IEQUAL, OP_SHIFTRIGHTLOGICAL, OP_SHIFTLEFTLOGICAL, OP_BITWISEAND, OP_PHI, OP_LOOPMERGE, OP_SELECTIONMERGE = 176, 170, 194, 196, 199, 245, 246, 247
OP_LABEL, OP_BRANCH, OP_BRANCHCONDITIONAL, OP_RETURN, OP_CONTROLBARRIER, OP_EXTINST = 248, 249, 250, 253, 224, 12
OP_EMITMESHTASKS, OP_SETMESHOUTPUTS = 5294, 5295
MODEL_GLCOMPUTE, MODEL_TASK, MODEL_MESH = 5, 5364, 5365
CAP_MESH = 5283
MODE_OUTPUTVERTICES, MODE_OUTPUTPOINTS, MODE_OUTPUTLINES, MODE_OUTPUTPRIMITIVES, MODE_OUTPUTTRIANGLES = 26, 27, 5269, 5270, 5298
SC_INPUT, SC_OUTPUT, SC_WORKGROUP, SC_FUNCTION, SC_PUSHCONSTANT, SC_PAYLOAD = 1, 3, 4, 7, 9, 5402
DEC_BLOCK, DEC_BUILTIN, DEC_INVARIANT, DEC_NOCONTRACTION, DEC_LOCATION, DEC_OFFSET, DEC_PERPRIMITIVE = 2, 11, 18, 42, 30, 35, 5271
FLOAT_ARITH = {127, 129, 131, 133, 136, 140, 141, 142, 143, 144, 145, 146, 147, 148}   # OpFNegate .. OpDot: the instructions NoContraction applies to
BI_POSITION, BI_POINTSIZE, BI_WORKGROUPID, BI_LOCALINDEX = 0, 1, 26, 29
BI_POINT_INDICES, BI_LINE_INDICES, BI_TRIANGLE_INDICES = 5294, 5295, 5296
SCOPE_WORKGROUP, SEM_ACQREL_WORKGROUP = 2, 0x108
GLSL_UMIN = 38
VERSION_1_4 = 0x00010400
BLOCK = 32   # vertices and primitives of an attribute block (dmsh_meshstage.BLOCK)
MAX_GROUPS = 65535   # VK maxMeshWorkGroupCount[0] on every Adreno that has the extension; a task asking for more launches this many


def _string(s):
    b = s.encode() + b'\0'; b += bytes(-len(b) % 4)
    return list(struct.unpack(f'<{len(b) // 4}I', b))


def _string_words(ins_words):   # the words of a literal string at the start of ins_words
    for k, w in enumerate(ins_words):
        if w >> 24 == 0 or w & 0xff == 0 or w >> 8 & 0xff == 0 or w >> 16 & 0xff == 0: return k + 1
    return len(ins_words)


class _Module:
    """The parsed module and what the wrapper adds: types and constants found or made once, ids from the bound up."""
    def __init__(self, hdr, ins):
        self.hdr, self.ins, self.bound = list(hdr), ins, hdr[3]
        self.caps, self.exts, self.annot, self.glob = [], [], [], []   # added capabilities, extensions, decorations, declarations
        self.types = {}
        for x in ins:   # the module's own types, so none is declared twice (non-aggregate duplicates are invalid)
            if x[0] in (OP_TYPEVOID, OP_TYPEBOOL): self.types.setdefault((x[0],), x[1])
            elif x[0] in (OP_TYPEINT, OP_TYPEFLOAT, OP_TYPEVECTOR, OP_TYPEPOINTER, OP_TYPEARRAY): self.types.setdefault((x[0], *x[2:]), x[1])
            elif x[0] == OP_TYPEFUNCTION: self.types.setdefault((x[0], *x[2:]), x[1])
        self.consts = {}
        for x in ins:
            if x[0] == OP_CONSTANT and len(x) == 4: self.consts.setdefault((x[1], x[3]), x[2])
        self.nulls = {x[1]: x[2] for x in ins if x[0] == OP_CONSTANTNULL}

    def new(self):
        self.bound += 1; return self.bound - 1

    def type(self, *key):
        if key not in self.types:
            t = self.new(); self.glob.append([key[0], t, *key[1:]]); self.types[key] = t
        return self.types[key]

    def const(self, ty, bits):
        if (ty, bits) not in self.consts:
            c = self.new(); self.glob.append([OP_CONSTANT, ty, c, bits]); self.consts[(ty, bits)] = c
        return self.consts[(ty, bits)]

    def null(self, ty):
        if ty not in self.nulls:
            c = self.new(); self.glob.append([OP_CONSTANTNULL, ty, c]); self.nulls[ty] = c
        return self.nulls[ty]

    def var(self, ty, sc, *decor):
        p = self.type(OP_TYPEPOINTER, sc, ty); v = self.new(); self.glob.append([OP_VARIABLE, p, v, sc])
        for d in decor: self.annot.append([OP_DECORATE, v, *d])
        return v


class _Fn:
    """The entry function's instructions, with structured loops and ifs."""
    def __init__(self, m):
        self.m, self.code = m, []
        self.u = m.type(OP_TYPEINT, 32, 0); self.f = m.type(OP_TYPEFLOAT, 32); self.b = m.type(OP_TYPEBOOL)

    def op(self, opc, ty, *args):
        r = self.m.new(); self.code.append([opc, ty, r, *args]); return r

    def cu(self, v): return self.m.const(self.u, v & 0xffffffff)
    def cf(self, v): return self.m.const(self.f, struct.unpack('<I', struct.pack('<f', v))[0])

    def label(self, l): self.code.append([OP_LABEL, l])

    def barrier(self):
        self.code.append([OP_CONTROLBARRIER, self.cu(SCOPE_WORKGROUP), self.cu(SCOPE_WORKGROUP), self.cu(SEM_ACQREL_WORKGROUP)])

    def loop(self, start, limit, step, body):
        """for (i = start; i < limit; i += step) body(i); limit an id"""
        pre = self.cur
        head, bl, cont, merge = (self.m.new() for _ in range(4))
        self.code.append([OP_BRANCH, head]); self.label(head)
        i = self.m.new(); nxt = self.m.new()
        self.code.append([OP_PHI, self.u, i, start, pre, nxt, cont])
        c = self.op(OP_ULESSTHAN, self.b, i, limit)
        self.code += [[OP_LOOPMERGE, merge, cont, 0], [OP_BRANCHCONDITIONAL, c, bl, merge]]
        self.label(bl); self.cur = bl; body(i)
        self.code.append([OP_BRANCH, cont]); self.label(cont)
        self.code += [[OP_IADD, self.u, nxt, i, step], [OP_BRANCH, head]]
        self.label(merge); self.cur = merge

    def when(self, cond, body):
        then, merge = self.m.new(), self.m.new()
        self.code += [[OP_SELECTIONMERGE, merge, 0], [OP_BRANCHCONDITIONAL, cond, then, merge]]
        self.label(then); self.cur = then; body()
        self.code.append([OP_BRANCH, merge]); self.label(merge); self.cur = merge


SC_UNIFORM, SC_STORAGEBUFFER, DEC_BUFFERBLOCK, OP_TYPERUNTIMEARRAY, OP_INBOUNDSACCESSCHAIN, OP_PTRACCESSCHAIN, OP_COPYOBJECT, OP_FUNCTIONPARAMETER = 2, 12, 3, 29, 66, 67, 83, 55


def _storage_buffers(m, ins):
    """SPIR-V 1.4 has no BufferBlock: the translator's storage buffers (Uniform variables of BufferBlock structs) become StorageBuffer variables of Block structs,
    with the pointers made from them retyped (a Uniform pointer to a uint is shared with the constant buffers' reads)"""
    bb = {x[1] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BUFFERBLOCK}
    if not bb: return
    grew = True
    while grew:   # arrays of them too
        n = len(bb); bb |= {x[1] for x in ins if x[0] in (OP_TYPEARRAY, OP_TYPERUNTIMEARRAY) and x[2] in bb}; grew = len(bb) > n
    sbp = set()
    for x in ins:
        if x[0] == OP_DECORATE and x[2] == DEC_BUFFERBLOCK: x[2] = DEC_BLOCK
        elif x[0] == OP_TYPEPOINTER and x[2] == SC_UNIFORM and x[3] in bb:
            x[2] = SC_STORAGEBUFFER; sbp.add(x[1]); m.types.pop((OP_TYPEPOINTER, SC_UNIFORM, x[3]), None); m.types[(OP_TYPEPOINTER, SC_STORAGEBUFFER, x[3])] = x[1]
    ptr = {x[1]: x[3] for x in ins if x[0] == OP_TYPEPOINTER}
    derived = set()
    for x in ins:
        if x[0] == OP_VARIABLE and x[1] in sbp: x[3] = SC_STORAGEBUFFER; derived.add(x[2])
        elif x[0] in (OP_ACCESSCHAIN, OP_INBOUNDSACCESSCHAIN, OP_PTRACCESSCHAIN, OP_COPYOBJECT) and x[3] in derived:
            x[1] = m.type(OP_TYPEPOINTER, SC_STORAGEBUFFER, ptr[x[1]]); derived.add(x[2])
        elif x[0] == OP_FUNCTIONPARAMETER and x[1] in sbp: raise ValueError('a storage buffer passed to a function: not retyped')


def _zero_locals(m, ins):
    """Every Function variable without an initializer starts at its type's zero → how many. The translator's locals are the shader's registers, undefined until the
    first store, and a translated task or mesh kernel reads some of them on a path with no store first (Ocarina of Time's grass: task 99280b7b8aae78df, mesh
    65a079a285d693a0 and eb021183bf9b0092). On Adreno that read gets whatever the compiler left in the register, which turned the grass and leaves white"""
    ptr = {x[1]: x[3] for x in ins if x[0] == OP_TYPEPOINTER and x[2] == SC_FUNCTION}; n = 0
    for x in ins:
        if x[0] == OP_VARIABLE and len(x) == 4 and x[3] == SC_FUNCTION and x[1] in ptr: x.append(m.null(ptr[x[1]])); n += 1
    return n


def _no_contraction(m, code):
    """Every float arithmetic result is decorated NoContraction → how many. Ocarina of Time draws its foliage twice with two mesh shaders, a depth prepass and a colour
    pass tested EQUAL, so both must compute a vertex's position to the bit. Invariant on the position output doesn't do that here: the kernel computes the position
    into the stage memory and the entry point copies it out, and invariance doesn't follow a value through memory. The Adreno compiler then fused a multiply and an
    add in one kernel and not in the other, and the colour pass lost blades to the depth test (white specks). The translator writes the shader's own fused
    multiply-adds as Fma, so nothing the shader asks for is lost"""
    ids = [x[2] for x in code if x[0] in FLOAT_ARITH]
    m.annot += [[OP_DECORATE, r, DEC_NOCONTRACTION] for r in ids]
    return len(ids)


def wrap(data, info, lay, gl=False, max_groups=MAX_GROUPS):
    """The compute module data (dmsh_xlate's SPIR-V of a task or mesh job) as a task or mesh module. info: dmsh_meshstage.info; lay: dmsh_meshstage.memory's offsets.
    → (SPIR-V bytes, the mask of per-primitive output locations)"""
    import spv_android as sa
    hdr, ins = sa.parse(data)
    kind = info['kind']
    ent = [x for x in ins if x[0] == OP_ENTRY]
    if len(ent) != 1 or ent[0][1] != MODEL_GLCOMPUTE: raise ValueError(f'{kind}: not one GLCompute entry point')
    body_fn = ent[0][2]
    ptr = {x[1]: (x[2], x[3]) for x in ins if x[0] == OP_TYPEPOINTER}
    arr = {x[1]: (x[2], x[3]) for x in ins if x[0] == OP_TYPEARRAY}
    uint_t = next((x[1] for x in ins if x[0] == OP_TYPEINT and x[2:] == [32, 0]), None)
    cval = {x[2]: x[3] for x in ins if x[0] == OP_CONSTANT and len(x) == 4}
    shared = [x for x in ins if x[0] == OP_VARIABLE and x[3] == SC_WORKGROUP]
    mems = [x for x in shared if ptr[x[1]][1] in arr and arr[ptr[x[1]][1]][0] == uint_t]
    if len(shared) != 1 or len(mems) != 1: raise ValueError(f'{kind}: {len(shared)} workgroup variables, not the stage memory alone')
    mem, words = mems[0][2], cval[arr[ptr[mems[0][1]][1]][1]]
    m = _Module(hdr, ins); _storage_buffers(m, ins); _zero_locals(m, ins); fn = _Fn(m); u, f, b = fn.u, fn.f, fn.b
    void = m.type(OP_TYPEVOID); fty = m.type(OP_TYPEFUNCTION, void)
    pwu = m.type(OP_TYPEPOINTER, SC_WORKGROUP, u)
    v3u = m.type(OP_TYPEVECTOR, u, 3); v4f = m.type(OP_TYPEVECTOR, f, 4)
    lid_v = m.var(u, SC_INPUT, [DEC_BUILTIN, BI_LOCALINDEX]); wg_v = m.var(v3u, SC_INPUT, [DEC_BUILTIN, BI_WORKGROUPID])
    thr, pay = info['threads'], info['payload'] + 3 >> 2
    wg, inp, out, prim = lay[0] >> 2, lay[1] >> 2, lay[2] >> 2, lay[3]
    task = kind == 'ts' or info.get('task')
    payload_v = None
    if task:   # the task's payload, shared with the mesh shaders it launches
        pa = m.type(OP_TYPEARRAY, u, m.const(u, max(pay, 1)))
        payload_v = m.var(pa, SC_PAYLOAD)
    pc_v = None
    if kind == 'ts' or not info.get('task'):   # the draw's first workgroup
        st = m.new(); m.glob.append([OP_TYPESTRUCT, st, u]); m.annot += [[OP_DECORATE, st, DEC_BLOCK], [OP_MEMBERDECORATE, st, 0, DEC_OFFSET, 0]]
        pc_v = m.var(st, SC_PUSHCONSTANT)
    entry = m.new(); lbl = m.new()
    fn.code += [[OP_FUNCTION, void, entry, 0, fty]]; fn.label(lbl); fn.cur = lbl

    def mem_at(idx): return fn.op(OP_ACCESSCHAIN, pwu, mem, idx)
    def load_mem(idx): return fn.op(OP_LOAD, u, mem_at(idx))
    def store_mem(idx, val): fn.code.append([OP_STORE, mem_at(idx), val])

    lid = fn.op(OP_LOAD, u, lid_v)
    tg = fn.op(OP_COMPOSITEEXTRACT, u, fn.op(OP_LOAD, v3u, wg_v), 0)
    first = fn.op(OP_LOAD, u, fn.op(OP_ACCESSCHAIN, m.type(OP_TYPEPOINTER, SC_PUSHCONSTANT, u), pc_v, fn.cu(0))) if pc_v else None
    is0 = fn.op(OP_IEQUAL, b, lid, fn.cu(0))
    zero, step = fn.cu(0), fn.cu(thr)
    fn.loop(lid, fn.cu(words), step, lambda i: store_mem(i, zero))
    fn.barrier()
    if kind == 'ms' and task:   # the payload in, then this workgroup's number among the task's launches in word 0 and input word 0
        ppu = m.type(OP_TYPEPOINTER, SC_PAYLOAD, u)
        fn.loop(lid, fn.cu(pay), step, lambda i: store_mem(fn.op(OP_IADD, u, fn.cu(inp), i), fn.op(OP_LOAD, u, fn.op(OP_ACCESSCHAIN, ppu, payload_v, i))))
        fn.barrier()
        fn.when(is0, lambda: (store_mem(fn.cu(wg), tg), store_mem(fn.cu(inp), tg)))
    else:
        fn.when(is0, lambda: store_mem(fn.cu(wg), fn.op(OP_IADD, u, first, tg)))
    fn.barrier()
    fn.op(OP_FUNCTIONCALL, void, body_fn)
    fn.barrier()
    glsl = next((x[1] for x in ins if x[0] == OP_EXTINSTIMPORT and sa.ext_name([0] + x[2:]) == 'GLSL.std.450'), None)
    if glsl is None:
        glsl = m.new(); ext_import = [OP_EXTINSTIMPORT, glsl, *_string('GLSL.std.450')]
    else: ext_import = None
    def umin(a, c): return fn.op(OP_EXTINST, u, glsl, GLSL_UMIN, a, c)
    prim_mask = 0
    modes = []
    if kind == 'ts':
        ppu = m.type(OP_TYPEPOINTER, SC_PAYLOAD, u)
        fn.loop(lid, fn.cu(pay), step, lambda i: fn.code.append([OP_STORE, fn.op(OP_ACCESSCHAIN, ppu, payload_v, i), load_mem(fn.op(OP_IADD, u, fn.cu(out), i))]))
        fn.barrier()
        n = umin(load_mem(fn.cu(out + 1)), fn.cu(max_groups))
        fn.code.append([OP_EMITMESHTASKS, n, fn.cu(1), fn.cu(1), payload_v])   # a terminator: the function ends here
    else:
        vertex, primitive = [tuple(c) for c in info['vertex']], [tuple(c) for c in info['primitive']]   # (from res.json: lists)
        max_v, max_p, verts = info['max_v'], info['max_p'], info.get('verts', 3)
        if verts not in (1, 2, 3): raise ValueError(f'ms: primitive vertex count {verts} is not 1, 2 or 3')
        if None not in [n for n, _ in vertex]: raise ValueError('ms: its SPH enables no position component')
        v_blocks = (max(max_v, 1) + BLOCK - 1) // BLOCK
        v_stride, p_stride = max(len(vertex), 1) * BLOCK, max(len(primitive), 1) * BLOCK
        p_out = out + v_blocks * len(vertex) * BLOCK
        members = lambda comps: {n: [comps.index((n, c)) if (n, c) in comps else None for c in range(4)] for n in dict.fromkeys(n for n, _ in comps)}
        vm, pm = members(vertex), members(primitive)
        # the outputs: position (invariant, as a vertex shader's: Ocarina of Time draws foliage with a mesh depth prepass and a mesh colour pass tested EQUAL; with
        # _no_contraction below for the kernel's part), point size, vec4 per location
        av = m.type(OP_TYPEARRAY, v4f, m.const(u, max_v)); af = m.type(OP_TYPEARRAY, f, m.const(u, max_v))
        ap = m.type(OP_TYPEARRAY, v4f, m.const(u, max(max_p, 1)))
        pov4 = m.type(OP_TYPEPOINTER, SC_OUTPUT, v4f); pof = m.type(OP_TYPEPOINTER, SC_OUTPUT, f)
        outs_v = {}
        for n in vm:
            if n is None: outs_v[n] = m.var(av, SC_OUTPUT, [DEC_BUILTIN, BI_POSITION], [DEC_INVARIANT])
            elif n == 'psiz': outs_v[n] = m.var(af, SC_OUTPUT, [DEC_BUILTIN, BI_POINTSIZE])
            else: outs_v[n] = m.var(av, SC_OUTPUT, [DEC_LOCATION, n])
        outs_p = {n: m.var(ap, SC_OUTPUT, [DEC_LOCATION, n], [DEC_PERPRIMITIVE]) for n in pm}
        prim_mask = sum(1 << n for n in pm)
        ivec = u if verts == 1 else m.type(OP_TYPEVECTOR, u, verts)
        idx_v = m.var(m.type(OP_TYPEARRAY, ivec, m.const(u, max(max_p, 1))), SC_OUTPUT,
                      [DEC_BUILTIN, {1: BI_POINT_INDICES, 2: BI_LINE_INDICES, 3: BI_TRIANGLE_INDICES}[verts]])
        np_ = umin(fn.op(OP_SHIFTRIGHTLOGICAL, u, load_mem(fn.cu(prim >> 2)), fn.cu(24)), fn.cu(max_p))
        fn.code.append([OP_SETMESHOUTPUTS, fn.cu(max_v), np_])

        def value(base, comps, width=4):
            parts = []
            for c in range(width):
                if comps[c] is None: parts.append(fn.cf(1.0 if c == 3 else 0.0))
                else: parts.append(fn.op(OP_BITCAST, f, load_mem(fn.op(OP_IADD, u, base, fn.cu(comps[c] * BLOCK)))))
            return parts

        def block(i, start, stride):   # start + (i / 32) * stride + i % 32
            q = fn.op(OP_SHIFTRIGHTLOGICAL, u, i, fn.cu(5)); r = fn.op(OP_BITWISEAND, u, i, fn.cu(BLOCK - 1))
            return fn.op(OP_IADD, u, fn.op(OP_IADD, u, fn.cu(start), fn.op(OP_IMUL, u, q, fn.cu(stride))), r)

        def one_vertex(i):
            bb = block(i, out, v_stride)
            for n, comps in vm.items():
                if n == 'psiz':
                    fn.code.append([OP_STORE, fn.op(OP_ACCESSCHAIN, pof, outs_v[n], i), value(bb, comps, 1)[0]]); continue
                p = value(bb, comps)
                if n is None and gl:   # z' = (z + w) / 2
                    p[2] = fn.op(OP_FMUL, f, fn.op(OP_FADD, f, p[2], p[3]), fn.cf(0.5))
                fn.code.append([OP_STORE, fn.op(OP_ACCESSCHAIN, pov4, outs_v[n], i), fn.op(OP_COMPOSITECONSTRUCT, v4f, *p)])
        fn.loop(lid, fn.cu(max_v), step, one_vertex)

        def one_primitive(i):
            if pm:
                bb = block(i, p_out, p_stride)
                for n, comps in pm.items():
                    fn.code.append([OP_STORE, fn.op(OP_ACCESSCHAIN, pov4, outs_p[n], i), fn.op(OP_COMPOSITECONSTRUCT, v4f, *value(bb, comps))])
            at0 = fn.op(OP_IADD, u, fn.cu(prim + 4), fn.op(OP_IMUL, u, i, fn.cu(verts)))
            ids = []
            for k in range(verts):
                at = fn.op(OP_IADD, u, at0, fn.cu(k))
                w = load_mem(fn.op(OP_SHIFTRIGHTLOGICAL, u, at, fn.cu(2)))
                sh = fn.op(OP_SHIFTLEFTLOGICAL, u, fn.op(OP_BITWISEAND, u, at, fn.cu(3)), fn.cu(3))
                ids.append(umin(fn.op(OP_BITWISEAND, u, fn.op(OP_SHIFTRIGHTLOGICAL, u, w, sh), fn.cu(0xff)), fn.cu(max_v - 1)))
            val = ids[0] if verts == 1 else fn.op(OP_COMPOSITECONSTRUCT, ivec, *ids)
            fn.code.append([OP_STORE, fn.op(OP_ACCESSCHAIN, m.type(OP_TYPEPOINTER, SC_OUTPUT, ivec), idx_v, i), val])
        fn.loop(lid, np_, step, one_primitive)
        fn.code.append([OP_RETURN])
        modes = [[OP_EXECMODE, entry, MODE_OUTPUTVERTICES, max_v], [OP_EXECMODE, entry, MODE_OUTPUTPRIMITIVES, max_p],
                 [OP_EXECMODE, entry, {1: MODE_OUTPUTPOINTS, 2: MODE_OUTPUTLINES, 3: MODE_OUTPUTTRIANGLES}[verts]]]
    fn.code.append([OP_FUNCTIONEND])
    if kind == 'ms': _no_contraction(m, ins + fn.code)
    # the module put together: SPIR-V 1.4, the capability and extension, the new entry point over every global, the kernel's execution modes moved to it
    m.hdr[1] = VERSION_1_4; m.hdr[3] = m.bound
    globals_ = [x[2] for x in ins if x[0] == OP_VARIABLE and x[3] != SC_FUNCTION] + [x[2] for x in m.glob if x[0] == OP_VARIABLE]
    name = _string('main')
    model = MODEL_TASK if kind == 'ts' else MODEL_MESH
    out_ins, placed_caps, placed_decor, placed_glob = [], False, False, False
    have_ext = any(x[0] == OP_EXTENSION and sa.ext_name(x) == 'SPV_EXT_mesh_shader' for x in ins)
    first_decor = next(i for i, x in enumerate(ins) if x[0] in (OP_DECORATE, OP_MEMBERDECORATE) or OP_TYPEVOID <= x[0] <= OP_TYPEFUNCTION + 6 or x[0] in (OP_CONSTANT, OP_VARIABLE))
    for i, x in enumerate(ins):
        if x[0] == OP_CAPABILITY and not placed_caps:
            out_ins.append([OP_CAPABILITY, CAP_MESH]); placed_caps = True
        if x[0] in (OP_EXTINSTIMPORT, OP_MEMORYMODEL) and not have_ext:
            out_ins.append([OP_EXTENSION, *_string('SPV_EXT_mesh_shader')]); have_ext = True
        if x[0] == OP_MEMORYMODEL and ext_import: out_ins.append(ext_import); ext_import = None
        if i == first_decor and not placed_decor: out_ins += m.annot; placed_decor = True
        if x[0] == OP_FUNCTION and not placed_glob: out_ins += m.glob; placed_glob = True
        if x[0] == OP_ENTRY: out_ins += [[OP_ENTRY, model, entry, *name, *globals_]] + modes; continue
        if x[0] == OP_EXECMODE and x[1] == body_fn: out_ins.append([OP_EXECMODE, entry, *x[2:]]); continue
        out_ins.append(x)
    out_ins += fn.code
    return sa.emit(m.hdr, out_ins), prim_mask
