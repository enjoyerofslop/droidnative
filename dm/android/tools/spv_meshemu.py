# NVN2 task and mesh shaders on a GPU without VK_EXT_mesh_shader (the stock Adreno 830 driver of a OnePlus Pad 3 has none, while the Adreno 840's has it): a DrawMeshTasks
# becomes compute dispatches and an indexed draw (dm/android/gfx_vk_meshemu.inc). This makes the modules it runs, from the same translated kernel spv_mesh.wrap starts from:
#   compute(): the kernel called from a GLCompute entry point that fills its stage memory from buffers and empties it into others (the emulation's buffers, set MESH_SET):
#     task  word 0 = push constant first + its workgroup; after the kernel, its payload words go to taskout[(base + workgroup) * pay ..], payload word 1 being how many
#           mesh workgroups it launches (meshlaunch.comp lists them)
#     mesh  with a task: launch[HDR + 2 slot] = the task that launched it, launch[HDR + 2 slot + 1] = its number k among that task's launches; the task's payload is
#           copied in and word 0 = input word 0 = k (as spv_mesh.wrap's mesh shader sets them). Without one: word 0 = first + its workgroup. slot = base + its workgroup.
#           After the kernel its records go to vtx[(slot * nrec + r) * nout * 4 ..], a vec4 per output (components the SPH does not enable are (0, 0, 0, 1)), and the
#           indices to idx[slot * ipw ..] (ipw = max_p * verts, 32-bit): a primitive past the count the shader set is degenerate (every corner the workgroup's first record)
#           A mesh shader without per-primitive outputs has a record per vertex (nrec = max_v) and its primitives index them. One with them has a record per primitive
#           corner (nrec = ipw), its vertex's outputs and its primitive's together: the fragment shader then reads a per-primitive output as a vertex output that is the
#           same at all three corners
#   vertex(): a mesh shader's pass-through vertex shader: record gl_VertexIndex's vec4s from vtx (set 0, binding 0) to gl_Position (invariant, as the mesh shader's), the
#     point size and the generic outputs; gl: the -1..1 depth variant (z' = (z + w) / 2)
# The same design as DeathKhan's nx2android fork's mesh emulation (github.com/DeathKhan/nx2android: 1f7e70b, 0e3285b, defd439; shader_meshwrap.py, meshlaunch.comp),
# written anew here on spv_mesh.py's helpers. Per-primitive outputs, which theirs left out, come in as corners of their own
import struct
import spv_mesh as sm
from spv_mesh import (OP_ACCESSCHAIN, OP_BITCAST, OP_CAPABILITY, OP_COMPOSITECONSTRUCT, OP_COMPOSITEEXTRACT, OP_CONSTANT, OP_DECORATE, OP_ENTRY, OP_EXECMODE, OP_EXTINST,
                      OP_EXTINSTIMPORT, OP_FADD, OP_FMUL, OP_FUNCTION, OP_FUNCTIONCALL, OP_FUNCTIONEND, OP_IADD, OP_IEQUAL, OP_IMUL, OP_LOAD, OP_MEMBERDECORATE, OP_MEMORYMODEL,
                      OP_RETURN, OP_SHIFTLEFTLOGICAL, OP_SHIFTRIGHTLOGICAL, OP_BITWISEAND, OP_STORE, OP_TYPEARRAY, OP_TYPEFLOAT, OP_TYPEFUNCTION, OP_TYPEINT, OP_TYPEPOINTER,
                      OP_TYPEVECTOR, OP_TYPEVOID, OP_ULESSTHAN, OP_VARIABLE, MODEL_GLCOMPUTE, SC_FUNCTION, SC_INPUT, SC_OUTPUT, SC_PUSHCONSTANT, SC_WORKGROUP, DEC_BLOCK,
                      DEC_BUILTIN, DEC_INVARIANT, DEC_LOCATION, DEC_OFFSET, BI_POSITION, BI_POINTSIZE, BI_WORKGROUPID, BI_LOCALINDEX, BLOCK, GLSL_UMIN)

MESH_SET = 1   # the emulation's buffers' descriptor set in a kernel's compute pipeline: the kernel's own bindings are set 0 (gfx_vk_meshemu.inc me_cpipe)
B_TASKOUT, B_LAUNCH, B_VTX, B_IDX = 100, 101, 102, 103   # their bindings (the same in every kernel, unused ones included): past any the translator gives, as the
# transform feedback buffers are (spv_android.tf_variant). At 0 to 3 they shared numbers with the kernel's own set 0, and the passes that find a binding by its number
# alone took them for it: cbsize_strip took the index buffer for a size table at binding 3 and left the table in, which the layout (from res.json) no longer had, and
# Qualcomm's driver refused 8 of Ocarina of Time's kernels (VK_ERROR_UNKNOWN, OnePlus Pad 3)
VERSION = 2   # res.json mesh_emu 'v': spv_build.py translates again a task / mesh output whose compute form is of another version
HDR = 16   # launch list words before its entries: 0-2 the mesh dispatch's counts, 4-8 the indexed draw's arguments, 9 the launches past the list's capacity (meshlaunch.comp)
PC_BYTES = 8   # push constant {first, base}
OP_TYPESTRUCT, OP_TYPERUNTIMEARRAY, OP_UDIV, OP_SELECT, OP_SOURCE = 30, 29, 134, 169, 3
DEC_BUFFERBLOCK, DEC_ARRAYSTRIDE, DEC_BINDING, DEC_DESCRIPTORSET, DEC_NONWRITABLE = 3, 6, 33, 34, 24
SC_UNIFORM, SC_STORAGEBUFFER = 2, 12
BI_VERTEXINDEX = 42
CAP_SHADER = 1
MODEL_VERTEX = 0
VERSION_1_3 = 0x00010300


def layout(info):
    """The record a mesh workgroup writes per vertex or corner: [(name, components)], position first (name None, then the point size 'psiz', then locations), and
    nrec, nout, ipw, whether its outputs per primitive make the records corners (res.json mesh_emu, gfx_vk_meshemu.inc)"""
    vertex, primitive = [tuple(c) for c in info['vertex']], [tuple(c) for c in info.get('primitive') or []]
    def members(comps): return {n: [comps.index((n, c)) if (n, c) in comps else None for c in range(4)] for n in dict.fromkeys(n for n, _ in comps)}
    vm, pm = members(vertex), members(primitive)
    if None not in vm: raise ValueError('ms: its SPH enables no position component')
    if set(vm) & set(pm): raise ValueError('ms: a location written both per vertex and per primitive')
    order = lambda m: sorted(m, key=lambda n: (-2, 0) if n is None else (-1, 0) if n == 'psiz' else (0, n))
    rec = [(n, 'v', vm[n]) for n in order(vm)] + [(n, 'p', pm[n]) for n in order(pm)]
    verts = info.get('verts', 3)
    if verts not in (1, 2, 3): raise ValueError(f'ms: primitive vertex count {verts} is not 1, 2 or 3')
    ipw = info['max_p'] * verts
    return rec, (ipw if pm else info['max_v']), len(rec), ipw, bool(pm), len(vertex), len(primitive)


def facts(info):   # res.json mesh_emu: what the host sizes buffers and dispatches by
    pay = info['payload'] + 3 >> 2
    if info['kind'] == 'ts': return {'kind': 'ts', 'v': VERSION, 'pay': max(pay, 1), 'threads': info['threads']}
    rec, nrec, nout, ipw, corners = layout(info)[:5]
    return {'kind': 'ms', 'v': VERSION, 'pay': max(pay, 1), 'threads': info['threads'], 'task': int(bool(info.get('task'))), 'nrec': nrec, 'nout': nout, 'ipw': ipw,
            'verts': info.get('verts', 3), 'locs': sum(1 << n for n, _, _ in rec if isinstance(n, int))}


def _buffer(m, binding, nonwritable=False):
    """A uint[] storage buffer of the emulation (Uniform + BufferBlock, as the translator declares its own) at MESH_SET, binding → (variable, Uniform uint pointer)"""
    u = m.type(OP_TYPEINT, 32, 0); rt = m.new(); st = m.new()
    m.glob += [[OP_TYPERUNTIMEARRAY, rt, u], [OP_TYPESTRUCT, st, rt]]
    m.annot += [[OP_DECORATE, rt, DEC_ARRAYSTRIDE, 4], [OP_DECORATE, st, DEC_BUFFERBLOCK], [OP_MEMBERDECORATE, st, 0, DEC_OFFSET, 0]]
    if nonwritable: m.annot.append([OP_MEMBERDECORATE, st, 0, DEC_NONWRITABLE])
    v = m.var(st, SC_UNIFORM, [DEC_DESCRIPTORSET, MESH_SET], [DEC_BINDING, binding])
    return v, m.type(OP_TYPEPOINTER, SC_UNIFORM, u)


def compute(data, info, lay):
    """The compute module data (dmsh_xlate's SPIR-V of a task or mesh job) as the emulation's kernel → (SPIR-V bytes, the ids of the emulation's buffer variables, which
    spv_android.process must leave at MESH_SET)"""
    import spv_android as sa
    hdr, ins = sa.parse(data)
    kind = info['kind']
    ent = [x for x in ins if x[0] == OP_ENTRY]
    if len(ent) != 1 or ent[0][1] != MODEL_GLCOMPUTE: raise ValueError(f'{kind}: not one GLCompute entry point')
    body_fn, old_iface = ent[0][2], ent[0][3 + sa_string_len(ent[0][3:]):]
    ptr = {x[1]: (x[2], x[3]) for x in ins if x[0] == OP_TYPEPOINTER}
    arr = {x[1]: (x[2], x[3]) for x in ins if x[0] == OP_TYPEARRAY}
    uint_t = next((x[1] for x in ins if x[0] == OP_TYPEINT and x[2:] == [32, 0]), None)
    cval = {x[2]: x[3] for x in ins if x[0] == OP_CONSTANT and len(x) == 4}
    shared = [x for x in ins if x[0] == OP_VARIABLE and x[3] == SC_WORKGROUP]
    mems = [x for x in shared if ptr[x[1]][1] in arr and arr[ptr[x[1]][1]][0] == uint_t]
    if len(shared) != 1 or len(mems) != 1: raise ValueError(f'{kind}: {len(shared)} workgroup variables, not the stage memory alone')
    mem = mems[0][2]
    words = cval[arr[ptr[mems[0][1]][1]][1]]
    m = sm._Module(hdr, ins); sm._zero_locals(m, ins); fn = sm._Fn(m); u, f, b = fn.u, fn.f, fn.b
    void = m.type(OP_TYPEVOID); fty = m.type(OP_TYPEFUNCTION, void)
    pwu = m.type(OP_TYPEPOINTER, SC_WORKGROUP, u); v3u = m.type(OP_TYPEVECTOR, u, 3)
    lid_v = m.var(u, SC_INPUT, [DEC_BUILTIN, BI_LOCALINDEX]); wg_v = m.var(v3u, SC_INPUT, [DEC_BUILTIN, BI_WORKGROUPID])
    st = m.new(); m.glob.append([OP_TYPESTRUCT, st, u, u])
    m.annot += [[OP_DECORATE, st, DEC_BLOCK], [OP_MEMBERDECORATE, st, 0, DEC_OFFSET, 0], [OP_MEMBERDECORATE, st, 1, DEC_OFFSET, 4]]
    pc_v = m.var(st, SC_PUSHCONSTANT); ppc = m.type(OP_TYPEPOINTER, SC_PUSHCONSTANT, u)
    bufs = [_buffer(m, B_TASKOUT, kind == 'ms'), _buffer(m, B_LAUNCH, True), _buffer(m, B_VTX), _buffer(m, B_IDX)]
    (taskout, pu), (launch, _), (vtx, _), (idx, _) = bufs
    thr, pay = info['threads'], max(info['payload'] + 3 >> 2, 1)
    wg, inp, out, prim = lay[0] >> 2, lay[1] >> 2, lay[2] >> 2, lay[3]
    entry = m.new(); lbl = m.new()
    fn.code += [[OP_FUNCTION, void, entry, 0, fty]]; fn.label(lbl); fn.cur = lbl

    def mem_at(i): return fn.op(OP_ACCESSCHAIN, pwu, mem, i)
    def load_mem(i): return fn.op(OP_LOAD, u, mem_at(i))
    def store_mem(i, v): fn.code.append([OP_STORE, mem_at(i), v])
    def buf_at(v, i): return fn.op(OP_ACCESSCHAIN, pu, v, fn.cu(0), i)
    def add(*a):
        r = a[0]
        for x in a[1:]: r = fn.op(OP_IADD, u, r, x)
        return r
    def mul(a, c): return fn.op(OP_IMUL, u, a, c)

    lid = fn.op(OP_LOAD, u, lid_v)
    wgx = fn.op(OP_COMPOSITEEXTRACT, u, fn.op(OP_LOAD, v3u, wg_v), 0)
    first = fn.op(OP_LOAD, u, fn.op(OP_ACCESSCHAIN, ppc, pc_v, fn.cu(0)))
    slot = add(fn.op(OP_LOAD, u, fn.op(OP_ACCESSCHAIN, ppc, pc_v, fn.cu(1))), wgx)
    is0 = fn.op(OP_IEQUAL, b, lid, fn.cu(0)); step = fn.cu(thr)
    fn.loop(lid, fn.cu(words), step, lambda i: store_mem(i, fn.cu(0)))
    fn.barrier()
    if kind == 'ms' and info.get('task'):   # the launching task's payload in, then k in word 0 and input word 0
        e = add(fn.cu(HDR), mul(slot, fn.cu(2)))
        task = fn.op(OP_LOAD, u, buf_at(launch, e)); k = fn.op(OP_LOAD, u, buf_at(launch, add(e, fn.cu(1))))
        fn.loop(lid, fn.cu(pay), step, lambda i: store_mem(add(fn.cu(inp), i), fn.op(OP_LOAD, u, buf_at(taskout, add(mul(task, fn.cu(pay)), i)))))
        fn.barrier()
        fn.when(is0, lambda: (store_mem(fn.cu(wg), k), store_mem(fn.cu(inp), k)))
    else:
        fn.when(is0, lambda: store_mem(fn.cu(wg), add(first, wgx)))
    fn.barrier()
    fn.op(OP_FUNCTIONCALL, void, body_fn)
    fn.barrier()
    glsl = next((x[1] for x in ins if x[0] == OP_EXTINSTIMPORT and sa.ext_name([0] + x[2:]) == 'GLSL.std.450'), None)
    ext_import = None
    if glsl is None: glsl = m.new(); ext_import = [OP_EXTINSTIMPORT, glsl, *sm._string('GLSL.std.450')]
    def umin(a, c): return fn.op(OP_EXTINST, u, glsl, GLSL_UMIN, a, c)
    if kind == 'ts':
        fn.loop(lid, fn.cu(pay), step, lambda i: fn.code.append([OP_STORE, buf_at(taskout, add(mul(slot, fn.cu(pay)), i)), load_mem(add(fn.cu(out), i))]))
    else:
        rec, nrec, nout, ipw, corners, nvc, npc = layout(info)   # nvc, npc: the components per vertex and per primitive, which size the attribute blocks
        max_v, max_p, verts = info['max_v'], info['max_p'], info.get('verts', 3)
        v_stride, p_stride = max(nvc, 1) * BLOCK, max(npc, 1) * BLOCK
        p_out = out + (max(max_v, 1) + BLOCK - 1) // BLOCK * nvc * BLOCK   # spv_mesh.wrap's
        one = fn.cu(struct.unpack('<I', struct.pack('<f', 1.0))[0])
        np_ = umin(fn.op(OP_SHIFTRIGHTLOGICAL, u, load_mem(fn.cu(prim >> 2)), fn.cu(24)), fn.cu(max_p))

        def block(i, start, stride):   # start + (i / 32) * stride + i % 32 (spv_mesh.wrap's)
            q = fn.op(OP_SHIFTRIGHTLOGICAL, u, i, fn.cu(5)); r = fn.op(OP_BITWISEAND, u, i, fn.cu(BLOCK - 1))
            return add(fn.cu(start), mul(q, fn.cu(stride)), r)

        def write_record(r_index, vb, pb):   # record r_index: the vertex outputs from block vb, the primitive outputs from pb
            base = mul(r_index, fn.cu(nout * 4))
            for j, (n, s, comps) in enumerate(rec):
                bb = vb if s == 'v' else pb
                for c in range(4):
                    val = (one if c == 3 else fn.cu(0)) if comps[c] is None else load_mem(add(bb, fn.cu(comps[c] * BLOCK)))
                    fn.code.append([OP_STORE, buf_at(vtx, add(base, fn.cu(j * 4 + c))), val])

        def corner(n):   # index byte n of the primitive area: its vertex, max_v - 1 at most
            at = add(fn.cu(prim + 4), n)
            w = load_mem(fn.op(OP_SHIFTRIGHTLOGICAL, u, at, fn.cu(2)))
            sh = fn.op(OP_SHIFTLEFTLOGICAL, u, fn.op(OP_BITWISEAND, u, at, fn.cu(3)), fn.cu(3))
            return umin(fn.op(OP_BITWISEAND, u, fn.op(OP_SHIFTRIGHTLOGICAL, u, w, sh), fn.cu(0xff)), fn.cu(max_v - 1))

        live = mul(np_, fn.cu(verts))
        if not corners:
            fn.loop(lid, fn.cu(max_v), step, lambda v: write_record(add(mul(slot, fn.cu(nrec)), v), block(v, out, v_stride), None))
            def one_index(n):
                ok = fn.op(OP_ULESSTHAN, b, n, live)
                v = fn.op(OP_SELECT, u, ok, corner(n), fn.cu(0))
                fn.code.append([OP_STORE, buf_at(idx, add(mul(slot, fn.cu(ipw)), n)), add(mul(slot, fn.cu(nrec)), v)])
            fn.loop(lid, fn.cu(ipw), step, one_index)
        else:
            def one_corner(n):
                ok = fn.op(OP_ULESSTHAN, b, n, live)
                v = fn.op(OP_SELECT, u, ok, corner(n), fn.cu(0))
                p = fn.op(OP_SELECT, u, ok, fn.op(OP_UDIV, u, n, fn.cu(verts)), fn.cu(0))
                r = add(mul(slot, fn.cu(ipw)), n)
                write_record(r, block(v, out, v_stride), block(p, p_out, p_stride))
                fn.code.append([OP_STORE, buf_at(idx, add(mul(slot, fn.cu(ipw)), n)), fn.op(OP_SELECT, u, ok, r, mul(slot, fn.cu(ipw)))])
            fn.loop(lid, fn.cu(ipw), step, one_corner)
    fn.code += [[OP_RETURN], [OP_FUNCTIONEND]]
    if kind == 'ms': sm._no_contraction(m, ins + fn.code)
    m.hdr[3] = m.bound
    if m.hdr[1] >= sm.VERSION_1_4:   # 1.4 lists every global the entry point uses: every one
        iface = [x[2] for x in ins if x[0] == OP_VARIABLE and x[3] != SC_FUNCTION] + [x[2] for x in m.glob if x[0] == OP_VARIABLE]
    else: iface = sorted({x[2] for x in ins if x[0] == OP_VARIABLE and x[3] in (SC_INPUT, SC_OUTPUT)} | set(old_iface)) + [lid_v, wg_v]
    out_ins, placed_decor, placed_glob = [], False, False
    first_decor = next(i for i, x in enumerate(ins) if x[0] in (OP_DECORATE, OP_MEMBERDECORATE) or OP_TYPEVOID <= x[0] <= OP_TYPEFUNCTION + 6 or x[0] in (OP_CONSTANT, OP_VARIABLE))
    for i, x in enumerate(ins):
        if x[0] == OP_MEMORYMODEL and ext_import: out_ins.append(ext_import); ext_import = None
        if i == first_decor and not placed_decor: out_ins += m.annot; placed_decor = True
        if x[0] == OP_FUNCTION and not placed_glob: out_ins += m.glob; placed_glob = True
        if x[0] == OP_ENTRY: out_ins.append([OP_ENTRY, MODEL_GLCOMPUTE, entry, *sm._string('main'), *iface]); continue
        if x[0] == OP_EXECMODE and x[1] == body_fn: out_ins.append([OP_EXECMODE, entry, *x[2:]]); continue
        out_ins.append(x)
    out_ins += fn.code
    return sa.emit(m.hdr, out_ins), [v for v, _ in bufs]


def sa_string_len(words):   # the words of OpEntryPoint's name
    return sm._string_words(words)


def vertex(info, gl=False):
    """A mesh shader's pass-through vertex shader (SPIR-V 1.3 bytes): its record gl_VertexIndex from vtx (a uint[] storage buffer, set 0 binding 0) → its outputs"""
    import spv_android as sa
    rec, nrec, nout, ipw, corners = layout(info)[:5]
    m = sm._Module([0x07230203, VERSION_1_3, 0, 1, 0], []); fn = sm._Fn(m); u, f = fn.u, fn.f
    void = m.type(OP_TYPEVOID); fty = m.type(OP_TYPEFUNCTION, void); v4f = m.type(OP_TYPEVECTOR, f, 4)
    i32 = m.type(OP_TYPEINT, 32, 1)
    rt = m.new(); st = m.new(); m.glob += [[OP_TYPERUNTIMEARRAY, rt, u], [OP_TYPESTRUCT, st, rt]]
    m.annot += [[OP_DECORATE, rt, DEC_ARRAYSTRIDE, 4], [OP_DECORATE, st, DEC_BLOCK], [OP_MEMBERDECORATE, st, 0, DEC_OFFSET, 0], [OP_MEMBERDECORATE, st, 0, DEC_NONWRITABLE]]
    buf = m.var(st, SC_STORAGEBUFFER, [DEC_DESCRIPTORSET, 0], [DEC_BINDING, 0]); psu = m.type(OP_TYPEPOINTER, SC_STORAGEBUFFER, u)
    vid_v = m.var(i32, SC_INPUT, [DEC_BUILTIN, BI_VERTEXINDEX])
    outs = []
    for n, _, _ in rec:
        if n is None: outs.append(m.var(v4f, SC_OUTPUT, [DEC_BUILTIN, BI_POSITION], [DEC_INVARIANT]))
        elif n == 'psiz': outs.append(m.var(f, SC_OUTPUT, [DEC_BUILTIN, BI_POINTSIZE]))
        else: outs.append(m.var(v4f, SC_OUTPUT, [DEC_LOCATION, n]))
    psiz = None
    if info.get('verts', 3) == 1 and not any(n == 'psiz' for n, _, _ in rec): psiz = m.var(f, SC_OUTPUT, [DEC_BUILTIN, BI_POINTSIZE])   # points need one: the hardware's 1
    entry = m.new(); lbl = m.new()
    fn.code += [[OP_FUNCTION, void, entry, 0, fty]]; fn.label(lbl); fn.cur = lbl
    base = fn.op(OP_IMUL, u, fn.op(OP_BITCAST, u, fn.op(OP_LOAD, i32, vid_v)), fn.cu(nout * 4))
    for j, (n, _, _) in enumerate(rec):
        c = [fn.op(OP_BITCAST, f, fn.op(OP_LOAD, u, fn.op(OP_ACCESSCHAIN, psu, buf, fn.cu(0), fn.op(OP_IADD, u, base, fn.cu(j * 4 + k))))) for k in range(4)]
        if n == 'psiz': fn.code.append([OP_STORE, outs[j], c[0]]); continue
        if n is None and gl: c[2] = fn.op(OP_FMUL, f, fn.op(OP_FADD, f, c[2], c[3]), fn.cf(0.5))   # z' = (z + w) / 2
        fn.code.append([OP_STORE, outs[j], fn.op(OP_COMPOSITECONSTRUCT, v4f, *c)])
    if psiz: fn.code.append([OP_STORE, psiz, fn.cf(1.0)])
    fn.code += [[OP_RETURN], [OP_FUNCTIONEND]]
    m.hdr[3] = m.bound
    iface = [vid_v] + outs + ([psiz] if psiz else [])
    ins = [[OP_CAPABILITY, CAP_SHADER], [OP_MEMORYMODEL, 0, 1], [OP_ENTRY, MODEL_VERTEX, entry, *sm._string('main'), *iface]] + m.annot + m.glob + fn.code
    return sa.emit(m.hdr, ins)
