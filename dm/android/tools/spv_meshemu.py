# NVN2 task and mesh shaders on a GPU without VK_EXT_mesh_shader (the stock Adreno 830 driver of a OnePlus Pad 3 has none, while the Adreno 840's has it): a DrawMeshTasks
# becomes compute dispatches and an indexed draw (dm/android/gfx_vk_meshemu.inc). This makes the modules it runs, from the same translated kernel spv_mesh.wrap starts from:
#   compute(): the kernel called from a GLCompute entry point that fills its stage memory from buffers and empties it into others (the emulation's buffers, set MESH_SET):
#     task  word 0 = push constant first + its workgroup; after the kernel, its payload words go to taskout[(base + workgroup) * pay ..], payload word 1 being how many
#           mesh workgroups it launches (meshlaunch.comp lists them)
#     mesh  with a task: launch[HDR + 2 slot] = the task that launched it, launch[HDR + 2 slot + 1] = its number k among that task's launches; the task's payload is
#           its input and word 0 = input word 0 = k (as spv_mesh.wrap's mesh shader sets them). Without one: word 0 = first + its workgroup. slot = base + its workgroup.
#           After the kernel its attributes are in vtx and its indices in idx[slot * ipw ..] (ipw = max_p * verts, 32-bit): a primitive past the count the shader set is
#           degenerate (every corner the workgroup's first vertex)
#           vtx holds the attribute blocks as the stage memory does (dmsh_meshstage: blocks of 32 vertices, in each the SPH's components in order, a word a vertex): vertex v's
#           component k is at vtx[(slot * max_v + v >> 5) * nvc * 32 + k * 32 + (v & 31)]. The kernel's lanes write a component of 32 vertices into one line, the pass-through
#           vertex shader's consecutive vertices read one, and nothing is stored for the components the SPH leaves out: those are the vertex shader's constants, (0, 0, 0, 1)
#           as the hardware gives
#           A mesh shader with per-primitive outputs (Ocarina of Time's HUD, 4 of its 500) gets a record per primitive corner instead (nrec = ipw), its vertex's components and
#           its primitive's together, plane by plane: word p of record r is vtx[(slot * recw + p) * ipw + r]. The fragment shader then reads a per-primitive output as a vertex
#           output that is the same at all three corners
#   Direct stores and loads (the usual case, 519 of Ocarina of Time's 520): the stage memory stays in shared memory only where the kernel needs it there. The translator writes
#     every attribute store and every payload read with its area's offset as a constant in the address ((register + C) >> 2, InstEmitAmpereMem.cs AStageOut and AIsberd), so
#     _areas tells the attribute area's stores from the payload's reads and the primitive area's byte stores; the attribute stores then go straight to vtx (the same word the
#     block layout gives), the payload reads straight to the task's payload in taskout (word 0 is k), and the shared array keeps the header and the primitive bytes alone, a few
#     dozen words. A kernel's GPU time was its shared memory: Ocarina of Time's grass kernel eb021183bf9b0092 took 11.4 KB a workgroup of 32 threads, few workgroups fit an
#     Adreno 830 shader core at once, and declaring the array twice as large doubled its time (OnePlus Pad 3, 1.7 to 3.8 ms a frame). A kernel whose addresses do not sort
#     (one task shader reads its payload back) keeps the whole stage memory in shared memory and copies its outputs out after the body, as before
#   Workgroups packed (pack, facts()): the shader's workgroup is 32 threads, half an Adreno wave of 64, so the kernel can run pack = 2 of them side by side in a workgroup of 64.
#     Each half has its own stage memory (the shared array pack times the size, a half's at half * words), its lane (SubgroupLocalInvocationId & 31), its slot (base +
#     workgroup * pack + half) and its own ballots, shuffles and votes (_rewrite: a ballot or lane mask is the half's word of the wave's, a shuffle reads within the half, any()
#     is the half's ballot). The host then dispatches ceil(count / pack) workgroups and tells the kernel count (push constant word 2; a task-launched mesh kernel reads it from
#     the launch list's word 3), and a half past the count does nothing but take the barriers. On a driver whose subgroups are 32 wide (the Xclipse 950, with the required size
#     the replay asks for) the halves are subgroups of their own and the rewrites change nothing. pack is 1 unless compute() is told otherwise: the host must know (facts pack)
#   vertex(): a mesh shader's pass-through vertex shader: gl_VertexIndex's components from vtx (set 0, binding 0) to gl_Position (invariant, as the mesh shader's), the point
#     size and the generic outputs; gl: the -1..1 depth variant (z' = (z + w) / 2)
# The same design as DeathKhan's nx2android fork's mesh emulation (github.com/DeathKhan/nx2android: 1f7e70b, 0e3285b, defd439; shader_meshwrap.py, meshlaunch.comp),
# written anew here on spv_mesh.py's helpers. Per-primitive outputs, which theirs left out, come in as corners of their own
import bisect
import collections
import struct
import spv_mesh as sm
from spv_mesh import (OP_ACCESSCHAIN, OP_BITCAST, OP_CAPABILITY, OP_COMPOSITECONSTRUCT, OP_COMPOSITEEXTRACT, OP_CONSTANT, OP_DECORATE, OP_ENTRY, OP_EXECMODE, OP_EXTINST,
                      OP_EXTINSTIMPORT, OP_FADD, OP_FMUL, OP_FUNCTION, OP_FUNCTIONCALL, OP_FUNCTIONEND, OP_IADD, OP_IEQUAL, OP_IMUL, OP_LOAD, OP_MEMBERDECORATE, OP_MEMORYMODEL,
                      OP_RETURN, OP_SHIFTLEFTLOGICAL, OP_SHIFTRIGHTLOGICAL, OP_BITWISEAND, OP_STORE, OP_TYPEARRAY, OP_TYPEFLOAT, OP_TYPEFUNCTION, OP_TYPEINT, OP_TYPEPOINTER,
                      OP_TYPEVECTOR, OP_TYPEVOID, OP_TYPEBOOL, OP_ULESSTHAN, OP_VARIABLE, OP_LABEL, OP_INBOUNDSACCESSCHAIN, OP_FUNCTIONPARAMETER, OP_COPYOBJECT, MODEL_GLCOMPUTE,
                      SC_FUNCTION, SC_INPUT, SC_OUTPUT, SC_PUSHCONSTANT, SC_WORKGROUP, DEC_BLOCK, DEC_BUILTIN, DEC_INVARIANT, DEC_LOCATION, DEC_OFFSET, BI_POSITION, BI_POINTSIZE,
                      BI_WORKGROUPID, BI_LOCALINDEX, BLOCK, GLSL_UMIN)

MESH_SET = 1   # the emulation's buffers' descriptor set in a kernel's compute pipeline: the kernel's own bindings are set 0 (gfx_vk_meshemu.inc me_cpipe)
B_TASKOUT, B_LAUNCH, B_VTX, B_IDX = 100, 101, 102, 103   # their bindings (the same in every kernel, unused ones included): past any the translator gives, as the
# transform feedback buffers are (spv_android.tf_variant). At 0 to 3 they shared numbers with the kernel's own set 0, and the passes that find a binding by its number
# alone took them for it: cbsize_strip took the index buffer for a size table at binding 3 and left the table in, which the layout (from res.json) no longer had, and
# Qualcomm's driver refused 8 of Ocarina of Time's kernels (VK_ERROR_UNKNOWN, OnePlus Pad 3)
VERSION = 3   # res.json mesh_emu 'v': spv_build.py translates again a task / mesh output whose compute form is of another version. 3: attributes in blocks, direct stores and loads
HDR = 16   # launch list words before its entries: 0-2 the mesh dispatch's counts, 3 the mesh workgroups listed (pack), 4-8 the indexed draw's arguments, 9 the launches past the list's capacity (meshlaunch.comp)
PC_BYTES = 8   # push constant {first, base}; {first, base, count} (12) for a packed kernel
PACK_SHARED = 32768   # a packed kernel's shared memory must fit the smallest limit it runs under (maxComputeSharedMemorySize: 32 KB on the Adreno 830 and 840 and the Xclipse 950)
OP_TYPESTRUCT, OP_TYPERUNTIMEARRAY, OP_UDIV, OP_UMOD, OP_ISUB, OP_SELECT, OP_SOURCE = 30, 29, 134, 137, 130, 169, 3
OP_INOTEQUAL, OP_BITWISEOR, OP_LOGICALAND, OP_VECTOREXTRACTDYNAMIC = 171, 197, 167, 77
OP_GROUPNONUNIFORMANY, OP_GROUPNONUNIFORMBALLOT, OP_GROUPNONUNIFORMSHUFFLE = 335, 339, 345
CAP_GROUPNONUNIFORMBALLOT = 64
SEM_ACQREL_WORKGROUP_UNIFORM = 0x148   # AcquireRelease | UniformMemory | WorkgroupMemory: a barrier that orders the buffer stores too
MODE_LOCALSIZE = 17
DEC_BUFFERBLOCK, DEC_ARRAYSTRIDE, DEC_BINDING, DEC_DESCRIPTORSET, DEC_NONWRITABLE = 3, 6, 33, 34, 24
SC_UNIFORM, SC_PRIVATE, SC_STORAGEBUFFER = 2, 6, 12
BI_VERTEXINDEX, BI_SUBGROUPLOCALID, BI_SUBGROUPLTMASK = 42, 41, 4420
CAP_SHADER = 1
MODEL_VERTEX = 0
VERSION_1_3 = 0x00010300


def layout(info):
    """The record a mesh workgroup writes per vertex or corner: [(name, 'v' or 'p', components)], position first (name None, then the point size 'psiz', then locations), and
    nrec, nout, ipw, whether its outputs per primitive make the records corners, the components per vertex and per primitive (res.json mesh_emu, gfx_vk_meshemu.inc)"""
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


def planes(rec):
    """A record's words in the order of the attribute blocks: [(output j, component c, 'v' or 'p', the component's index k in its block)], the vertex components by k, then
    the primitive ones by k: so a vertex component's plane is its k"""
    return sorted(((j, c, s, comps[c]) for j, (n, s, comps) in enumerate(rec) for c in range(4) if comps[c] is not None), key=lambda t: (t[2] != 'v', t[3]))


def facts(info, pack=1, direct=0):   # res.json mesh_emu: what the host sizes buffers and dispatches by (pack and direct: what compute() chose for the kernel)
    pay = info['payload'] + 3 >> 2
    if info['kind'] == 'ts': return {'kind': 'ts', 'v': VERSION, 'pay': max(pay, 1), 'threads': info['threads'], 'pack': pack, 'direct': direct}
    rec, nrec, nout, ipw, corners = layout(info)[:5]
    return {'kind': 'ms', 'v': VERSION, 'pay': max(pay, 1), 'threads': info['threads'], 'task': int(bool(info.get('task'))), 'nrec': nrec, 'nout': nout, 'ipw': ipw,
            'verts': info.get('verts', 3), 'locs': sum(1 << n for n, _, _ in rec if isinstance(n, int)), 'recw': len(planes(rec)), 'pack': pack, 'direct': direct}


def _buffer(m, binding, nonwritable=False):
    """A uint[] storage buffer of the emulation (Uniform + BufferBlock, as the translator declares its own) at MESH_SET, binding → (variable, Uniform uint pointer)"""
    u = m.type(OP_TYPEINT, 32, 0); rt = m.new(); st = m.new()
    m.glob += [[OP_TYPERUNTIMEARRAY, rt, u], [OP_TYPESTRUCT, st, rt]]
    m.annot += [[OP_DECORATE, rt, DEC_ARRAYSTRIDE, 4], [OP_DECORATE, st, DEC_BUFFERBLOCK], [OP_MEMBERDECORATE, st, 0, DEC_OFFSET, 0]]
    if nonwritable: m.annot.append([OP_MEMBERDECORATE, st, 0, DEC_NONWRITABLE])
    v = m.var(st, SC_UNIFORM, [DEC_DESCRIPTORSET, MESH_SET], [DEC_BINDING, binding])
    return v, m.type(OP_TYPEPOINTER, SC_UNIFORM, u)


def _builtin(m, ins, bi, ty):
    """The kernel's Input variable with BuiltIn bi, or a new one of type ty"""
    v = next((x[1] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BUILTIN and x[3] == bi), None)
    return v if v is not None else m.var(ty, SC_INPUT, [DEC_BUILTIN, bi])


def _areas(ins, mem, lay, words):
    """Every access to the stage memory, by the area its address names: {access chain id: (kind, area, dyn, c)} with kind 'load' / 'store' / 'atomic', area 'hdr' / 'in' /
    'out' / 'prim' or None when the address is not of the translator's form ((register + C) >> 2 or a constant), dyn the register's id (None for a constant address) and c
    the constant's bytes. A helper that takes a byte address (the translator's dmsh_shared_store8, the primitive area's) is classified by its call sites, all of which must agree"""
    inp_b, out_b, prim_b = lay[1], lay[2], lay[3]
    cval = {x[2]: x[3] for x in ins if x[0] == OP_CONSTANT and len(x) == 4}
    defs = {x[2]: (i, x) for i, x in enumerate(ins) if len(x) > 2 and x[0] in (OP_LOAD, OP_BITCAST, OP_IADD, OP_SHIFTRIGHTLOGICAL, OP_COPYOBJECT, OP_FUNCTIONPARAMETER)}
    fns, cur, fn_of, params = [], None, {}, set()
    for i, x in enumerate(ins):
        if x[0] == OP_FUNCTION: cur = [i, x[2], []]
        elif x[0] == OP_FUNCTIONPARAMETER: cur[2].append(x[2]); params.add(x[2])
        elif x[0] == OP_FUNCTIONEND: fns.append((cur[0], i, cur[1], cur[2])); cur = None
    for s, e, fid, _ in fns:
        for i in range(s, e + 1): fn_of[i] = fid
    stores = collections.defaultdict(list)
    for i, x in enumerate(ins):
        if x[0] == OP_STORE: stores[x[1]].append((i, x[2]))
    labels = [i for i, x in enumerate(ins) if x[0] == OP_LABEL]
    def block_of(i): return labels[bisect.bisect_right(labels, i) - 1]
    def last_store(var, i):   # the local's value at i: its last store in the block, or its one store in the function (the translator's registers are stored before use)
        prev = [s for s in stores.get(var, []) if s[0] < i and block_of(s[0]) == block_of(i)]
        if not prev and len(stores.get(var, [])) == 1 and fn_of.get(stores[var][0][0]) == fn_of.get(i): prev = stores[var]
        return prev[-1][1] if prev else None
    def value(v):   # v as (dyn, C bytes, parameter): through bitcasts, copies, locals and additions of constants
        for _ in range(16):
            if v in cval: return None, cval[v], None
            if v in params: return None, 0, v
            d = defs.get(v)
            if d is None: return v, 0, None
            i, x = d
            if x[0] in (OP_BITCAST, OP_COPYOBJECT): v = x[3]; continue
            if x[0] == OP_FUNCTIONPARAMETER: return None, 0, x[2]
            if x[0] == OP_LOAD:
                if x[3] in params: return None, 0, x[3]
                w = last_store(x[3], i)
                if w is None: return v, 0, None
                v = w; continue
            if x[0] == OP_IADD:
                a, b = x[3], x[4]
                if b in cval: dv, c, p = value(a); return dv, c + cval[b], p
                if a in cval: dv, c, p = value(b); return dv, c + cval[a], p
                return v, 0, None
            return v, 0, None
        return v, 0, None
    def index(idx):   # the word index → (dyn, C bytes, parameter), or None when its form is not (X + C) >> 2, a constant or a parameter's
        if idx in cval: return None, cval[idx] * 4, None
        d = defs.get(idx)
        for _ in range(8):
            if d is None: return None
            i, x = d
            if x[0] in (OP_BITCAST, OP_COPYOBJECT): d = defs.get(x[3]); continue
            if x[0] == OP_LOAD:
                if x[3] in params: return None, 0, x[3]
                w = last_store(x[3], i)
                if w is None: return None
                d = defs.get(w); continue
            if x[0] == OP_SHIFTRIGHTLOGICAL and x[4] in cval and cval[x[4]] == 2: return value(x[3])
            if x[0] == OP_FUNCTIONPARAMETER: return None, 0, x[2]
            return None
        return None
    def area(c): return 'hdr' if c < inp_b else 'in' if c < out_b else 'out' if c < prim_b else 'prim' if c < words * 4 else None
    param_area = {}
    for s, e, fid, ps in fns:
        calls = [(i, x) for i, x in enumerate(ins) if x[0] == OP_FUNCTIONCALL and x[3] == fid]
        for n, p in enumerate(ps):
            areas = set()
            for i, x in calls:
                w = last_store(x[4 + n], i)
                dv, c, q = value(w) if w is not None else (None, 0, p)
                areas.add(area(c) if q is None else None)
            param_area[p] = next(iter(areas)) if len(areas) == 1 else None
    out = {}
    for i, x in enumerate(ins):
        if x[0] in (OP_ACCESSCHAIN, OP_INBOUNDSACCESSCHAIN) and x[3] == mem and len(x) == 5:
            use = next((y for y in ins[i + 1:i + 8] if (y[0] == OP_LOAD and y[3] == x[2]) or (y[0] == OP_STORE and y[1] == x[2]) or (227 <= y[0] <= 241 and y[3] == x[2])), None)
            kind = 'load' if use and use[0] == OP_LOAD else 'store' if use and use[0] == OP_STORE else 'atomic' if use else None
            r = index(x[4])
            if r is None or kind is None: out[x[2]] = (kind, None, None, 0); continue
            dv, c, p = r
            out[x[2]] = (kind, param_area.get(p) if p is not None else area(c) if dv is None or c else None, dv, c)   # a register alone names no area
    return out


def _direct_ok(areas, info):
    """Whether the kernel can store its attributes and read its payload in place: every address sorts, nothing is read back from the attribute area or written into the
    payload's (a task shader of Ocarina of Time's reads its payload back), no per-primitive outputs (their records are corners), vertices in whole blocks"""
    if any(a is None for _, a, _, _ in areas.values()): return False
    if any(k in ('load', 'atomic') and a == 'out' or k in ('store', 'atomic') and a == 'in' for k, a, _, _ in areas.values()): return False
    if info['kind'] == 'ms': return not info.get('primitive') and info['max_v'] % BLOCK == 0 and info['max_v'] > 0
    return True


def _rewrite(m, ins, k):
    """The kernel's functions rewritten for the direct stores and loads and for pack (the comment at the top), by the context k → (the instructions, counts by kind)"""
    u = m.type(OP_TYPEINT, 32, 0); b = m.type(OP_TYPEBOOL); v4u = m.type(OP_TYPEVECTOR, u, 4)
    thr, pack, mem, areas = k['thr'], k['pack'], k['mem'], k['areas']
    typed = (OP_LOAD, OP_BITCAST, OP_IADD, OP_ISUB, OP_IMUL, OP_SHIFTRIGHTLOGICAL, OP_SHIFTLEFTLOGICAL, OP_BITWISEAND, OP_BITWISEOR, OP_UDIV, OP_UMOD, OP_SELECT,
             OP_COMPOSITEEXTRACT, OP_ACCESSCHAIN, OP_INBOUNDSACCESSCHAIN, OP_FUNCTIONPARAMETER, OP_COPYOBJECT, OP_EXTINST)
    rtype = {x[2]: x[1] for x in ins if x[0] in typed and len(x) > 2}
    rtype.update({x[2]: x[1] for x in ins if x[0] == OP_CONSTANT})   # a shuffle's constant index (a broadcast from lane 0) is already a uint: a bitcast to its own type is invalid
    pow2 = thr & (thr - 1) == 0
    c_0, c_thr = m.const(u, 0), m.const(u, thr)
    c_sh, c_thr1, c_mthr = (m.const(u, thr.bit_length() - 1), m.const(u, thr - 1), m.const(u, (-thr) & 0xffffffff)) if pow2 else (None, None, None)
    c_words = m.const(u, k['nwords']); c_shift = m.const(u, k['shift']); c_inp = m.const(u, k['inp'])
    pu = k['pu']
    out, n = [], collections.Counter()
    i = 0
    while i < len(ins):
        x = ins[i]
        if x[0] != OP_FUNCTION: out.append(x); i += 1; continue
        j = i
        while ins[j][0] != OP_LABEL: out.append(ins[j]); j += 1   # OpFunction and its parameters
        out.append(ins[j]); j += 1
        while ins[j][0] == OP_VARIABLE: out.append(ins[j]); j += 1   # the first block's variables, which must come first in it
        base = hi = q = None
        if pack > 1:   # the half and its stage memory's base, the quarter of the wave
            lid, sg, half, base, q, hi = (m.new() for _ in range(6))
            out += [[OP_LOAD, u, lid, k['lid_v']], [OP_LOAD, u, sg, k['sgid_v']]]
            if pow2: out += [[OP_SHIFTRIGHTLOGICAL, u, half, lid, c_sh], [OP_SHIFTRIGHTLOGICAL, u, q, sg, c_sh], [OP_BITWISEAND, u, hi, sg, c_mthr]]
            else: t = m.new(); out += [[OP_UDIV, u, half, lid, c_thr], [OP_UDIV, u, q, sg, c_thr], [OP_UMOD, u, t, sg, c_thr], [OP_ISUB, u, hi, sg, t]]
            out.append([OP_IMUL, u, base, half, c_words])
        def as_uint(v):
            if rtype.get(v) == u: return v
            t = m.new(); out.append([OP_BITCAST, u, t, v]); return t
        def word(vec, res, w=None):   # the quarter's word of a wave mask vec (a uvec4): as (word, 0, 0, 0) in res, or the word alone in w; by a select between the constant extracts
            # (not OpVectorExtractDynamic by the quarter: a per-lane index into a ballot's words is the kind of thing a driver's compiler gets wrong)
            w0, w1, sel = m.new(), m.new(), m.new(); w = w if w is not None else m.new()
            ins_ = [[OP_COMPOSITEEXTRACT, u, w0, vec, 0], [OP_COMPOSITEEXTRACT, u, w1, vec, 1], [OP_INOTEQUAL, b, sel, q, c_0], [OP_SELECT, u, w, sel, w1, w0]]
            return ins_ + ([[OP_COMPOSITECONSTRUCT, v4u, res, w, c_0, c_0, c_0]] if res is not None else [])
        def shifted(idx, by):   # idx + by (+ base)
            r = as_uint(idx)
            if by: t = m.new(); out.append([OP_ISUB if by < 0 else OP_IADD, u, t, r, m.const(u, abs(by))]); r = t
            if base is not None: t = m.new(); out.append([OP_IADD, u, t, r, base]); r = t
            return r
        pending = {}   # access chain id → ('in', idx, c) or ('out', dyn, c): the load or store that uses it is replaced
        while ins[j][0] != OP_FUNCTIONEND:
            y = ins[j]; j += 1
            if y[0] in (OP_ACCESSCHAIN, OP_INBOUNDSACCESSCHAIN) and y[3] == mem and len(y) == 5:
                kind, ar, dyn, c = areas[y[2]]
                if k['direct'] and ar == 'in': pending[y[2]] = ('in', y[4], c); n['in'] += 1; continue
                if k['direct'] and ar == 'out': pending[y[2]] = ('out', dyn, c); n['out'] += 1; continue
                by = -k['shift'] if k['direct'] and ar == 'prim' else 0
                out.append(y[:4] + [shifted(y[4], by)]); n['mem'] += 1
            elif y[0] == OP_LOAD and y[3] in pending:   # a payload word read in taskout: the task's payload, word 0 being k; a task's or a mesh shader's without a task reads 0
                _, idx, c = pending.pop(y[3])
                if k['task_v'] is None: out.append([OP_COPYOBJECT, y[1], y[2], m.const(y[1], 0)]); continue
                w, tb, a, p, g = (m.new() for _ in range(5))
                out += [[OP_ISUB, u, w, as_uint(idx), c_inp], [OP_LOAD, u, tb, k['task_v']], [OP_IADD, u, a, tb, w], [OP_ACCESSCHAIN, pu, p, k['taskout'], c_0, a]]
                if c - k['inp'] * 4 >= 4: out.append([OP_LOAD, y[1], y[2], p])   # never word 0
                else:
                    kk, z = m.new(), m.new(); out += [[OP_LOAD, u, g, p], [OP_LOAD, u, kk, k['k_v']], [OP_IEQUAL, b, z, w, c_0], [OP_SELECT, y[1], y[2], z, kk, g]]
            elif y[0] == OP_STORE and y[1] in pending:   # an attribute store into vtx (a task's payload store into taskout), at the same word the stage memory had past its area
                _, dyn, c = pending.pop(y[1])
                off = m.const(u, c - k['out_b'])
                if dyn is None: a = off
                else: a = m.new(); out.append([OP_IADD, u, a, as_uint(dyn), off])
                w, pb, a2, p = (m.new() for _ in range(4))
                out += [[OP_SHIFTRIGHTLOGICAL, u, w, a, m.const(u, 2)], [OP_LOAD, u, pb, k['pbase_v']], [OP_IADD, u, a2, pb, w], [OP_ACCESSCHAIN, pu, p, k['vtx'], c_0, a2], [OP_STORE, p, y[2]]]
            elif pack > 1 and y[0] == OP_LOAD and y[3] == k['sgid_v']:   # the lane within the shader's workgroup
                t = m.new(); out += [[OP_LOAD, u, t, k['sgid_v']], [OP_BITWISEAND, u, y[2], t, c_thr1] if pow2 else [OP_UMOD, u, y[2], t, c_thr]]; n['lane'] += 1
            elif pack > 1 and y[0] == OP_LOAD and y[3] == k['ltmask_v']:   # the lanes below this one, of the quarter
                t = m.new(); out.append([OP_LOAD, v4u, t, k['ltmask_v']]); out += word(t, y[2]); n['mask'] += 1
            elif pack > 1 and y[0] == OP_GROUPNONUNIFORMBALLOT:
                t = m.new(); out.append([OP_GROUPNONUNIFORMBALLOT, v4u, t, y[3], y[4]]); out += word(t, y[2]); n['ballot'] += 1
            elif pack > 1 and y[0] == OP_GROUPNONUNIFORMANY:
                t, w = m.new(), m.new(); out.append([OP_GROUPNONUNIFORMBALLOT, v4u, t, y[3], y[4]]); out += word(t, None, w) + [[OP_INOTEQUAL, b, y[2], w, c_0]]; n['any'] += 1
            elif pack > 1 and y[0] == OP_GROUPNONUNIFORMSHUFFLE:
                t = m.new(); out += [[OP_BITWISEOR, u, t, as_uint(y[5]), hi], y[:5] + [t]]; n['shuffle'] += 1
            else: out.append(y)
        if pending: raise ValueError(f'{len(pending)} stage memory accesses with no load or store after them')
        out.append(ins[j]); i = j + 1
    if n['any'] and not any(x[0] == OP_CAPABILITY and x[1] == CAP_GROUPNONUNIFORMBALLOT for x in out):
        at = next(at for at, x in enumerate(out) if x[0] == OP_CAPABILITY); out.insert(at, [OP_CAPABILITY, CAP_GROUPNONUNIFORMBALLOT])
    return out, n


def compute(data, info, lay, pack=1, direct=None):
    """The compute module data (dmsh_xlate's SPIR-V of a task or mesh job) as the emulation's kernel → (SPIR-V bytes, the ids of the emulation's buffer variables, which
    spv_android.process must leave at MESH_SET, the pack, whether the stores and loads are direct: what facts() must be told). pack: workgroups of the shader in one of the
    kernel's (the host must dispatch for it); direct: None for _direct_ok's answer, False for the stage memory whole in shared memory (a test)"""
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
    mem, mem_arr = mems[0][2], ptr[mems[0][1]][1]
    words = cval[arr[mem_arr][1]]
    thr, pay = info['threads'], max(info['payload'] + 3 >> 2, 1)
    wg, inp, out, prim = lay[0] >> 2, lay[1] >> 2, lay[2] >> 2, lay[3]
    areas = _areas(ins, mem, lay, words)
    if direct is None: direct = _direct_ok(areas, info)
    launched = kind == 'ms' and bool(info.get('task'))
    # the shared array in the direct form: the header, then the primitive bytes (a mesh shader's) moved down by shift words
    tail_w = prim >> 2 if kind == 'ms' else lay[3] >> 2
    shift, nwords = (tail_w - inp, inp + words - tail_w) if direct else (0, words)
    if pack > 1 and pack * nwords * 4 > PACK_SHARED: raise ValueError(f'{kind}: {pack} workgroups would take {pack * nwords * 4} bytes of shared memory')
    m = sm._Module(hdr, ins); sm._zero_locals(m, ins); fn = sm._Fn(m); u, f, b = fn.u, fn.f, fn.b
    void = m.type(OP_TYPEVOID); fty = m.type(OP_TYPEFUNCTION, void)
    pwu = m.type(OP_TYPEPOINTER, SC_WORKGROUP, u); v3u = m.type(OP_TYPEVECTOR, u, 3)
    lid_v = _builtin(m, ins, BI_LOCALINDEX, u); wg_v = _builtin(m, ins, BI_WORKGROUPID, v3u)
    sgid_v = _builtin(m, ins, BI_SUBGROUPLOCALID, u) if pack > 1 else None
    ltmask_v = next((x[1] for x in ins if x[0] == OP_DECORATE and x[2] == DEC_BUILTIN and x[3] == BI_SUBGROUPLTMASK), None)
    bufs = [_buffer(m, B_TASKOUT, kind == 'ms'), _buffer(m, B_LAUNCH, True), _buffer(m, B_VTX), _buffer(m, B_IDX)]
    (taskout, pu), (launch, _), (vtx, _), (idx, _) = bufs
    pbase_v = task_v = k_v = None
    if direct:   # what the body's direct stores and loads need: a Private word each, set before the body runs
        pbase_v = m.var(u, SC_PRIVATE)
        if launched: task_v = m.var(u, SC_PRIVATE); k_v = m.var(u, SC_PRIVATE)
    ctx = dict(thr=thr, pack=pack, mem=mem, areas=areas, direct=direct, shift=shift, nwords=nwords, inp=inp, out_b=lay[2], lid_v=lid_v, sgid_v=sgid_v, ltmask_v=ltmask_v,
               pu=pu, vtx=vtx if kind == 'ms' else taskout, taskout=taskout, pbase_v=pbase_v, task_v=task_v, k_v=k_v)
    rw = None
    if direct or pack > 1:
        ins, rw = _rewrite(m, ins, ctx)
        if nwords != words or pack > 1:   # the shared array's size, by a constant of its own
            at = next(i for i, x in enumerate(ins) if x[0] == OP_TYPEARRAY and x[1] == mem_arr)
            c = m.new(); ins.insert(at, [OP_CONSTANT, u, c, pack * nwords]); ins[at + 1][3] = c
    st = m.new(); m.glob.append([OP_TYPESTRUCT, st, u, u] + ([u] if pack > 1 else []))
    m.annot += [[OP_DECORATE, st, DEC_BLOCK], [OP_MEMBERDECORATE, st, 0, DEC_OFFSET, 0], [OP_MEMBERDECORATE, st, 1, DEC_OFFSET, 4]] + ([[OP_MEMBERDECORATE, st, 2, DEC_OFFSET, 8]] if pack > 1 else [])
    pc_v = m.var(st, SC_PUSHCONSTANT); ppc = m.type(OP_TYPEPOINTER, SC_PUSHCONSTANT, u)
    entry = m.new(); lbl = m.new()
    fn.code += [[OP_FUNCTION, void, entry, 0, fty]]; fn.label(lbl); fn.cur = lbl

    def add(*a):
        r = a[0]
        for x in a[1:]: r = fn.op(OP_IADD, u, r, x)
        return r
    def mul(a, c): return fn.op(OP_IMUL, u, a, c)
    def mem_at(i): return fn.op(OP_ACCESSCHAIN, pwu, mem, add(base, i) if base else i)
    def load_mem(i): return fn.op(OP_LOAD, u, mem_at(i))
    def store_mem(i, v): fn.code.append([OP_STORE, mem_at(i), v])
    def buf_at(v, i): return fn.op(OP_ACCESSCHAIN, pu, v, fn.cu(0), i)
    def pc(i): return fn.op(OP_LOAD, u, fn.op(OP_ACCESSCHAIN, ppc, pc_v, fn.cu(i)))
    def put(v, val): fn.code.append([OP_STORE, v, val])

    lid = fn.op(OP_LOAD, u, lid_v)
    wgx = fn.op(OP_COMPOSITEEXTRACT, u, fn.op(OP_LOAD, v3u, wg_v), 0)
    if pack > 1:   # the half: its lane, its stage memory's base, its workgroup of the shader
        pow2 = thr & (thr - 1) == 0
        lane = fn.op(OP_BITWISEAND, u, lid, fn.cu(thr - 1)) if pow2 else fn.op(OP_UMOD, u, lid, fn.cu(thr))
        half = fn.op(OP_SHIFTRIGHTLOGICAL, u, lid, fn.cu(thr.bit_length() - 1)) if pow2 else fn.op(OP_UDIV, u, lid, fn.cu(thr))
        base = mul(half, fn.cu(nwords)); own = add(mul(wgx, fn.cu(pack)), half)
    else: lane, base, own = lid, None, wgx
    first = pc(0); slot = add(pc(1), own)
    if pack > 1:
        count = fn.op(OP_LOAD, u, buf_at(launch, fn.cu(3))) if launched else pc(2)
        active = fn.op(OP_ULESSTHAN, b, slot, count)
    else: active = None
    def when_active(body):
        if active is None: body()
        else: fn.when(active, body)
    is0 = fn.op(OP_IEQUAL, b, lane, fn.cu(0)); step = fn.cu(thr)
    if launched and not direct:   # all zero but the payload's words, which the copy fills
        fn.loop(lane, fn.cu(inp), step, lambda i: store_mem(i, fn.cu(0)))
        fn.loop(add(lane, fn.cu(inp + pay)), fn.cu(nwords), step, lambda i: store_mem(i, fn.cu(0)))
    else: fn.loop(lane, fn.cu(nwords), step, lambda i: store_mem(i, fn.cu(0)))
    fn.barrier()
    if launched:   # the launching task's payload (copied in, or read in place), then k in word 0 and input word 0
        e = add(fn.cu(HDR), mul(slot, fn.cu(2)))
        if not direct:
            def copy_in():
                task = fn.op(OP_LOAD, u, buf_at(launch, e))
                fn.loop(lane, fn.cu(pay), step, lambda i: store_mem(add(fn.cu(inp), i), fn.op(OP_LOAD, u, buf_at(taskout, add(mul(task, fn.cu(pay)), i)))))
            when_active(copy_in)
            fn.barrier()
        def head():
            k = fn.op(OP_LOAD, u, buf_at(launch, add(e, fn.cu(1))))
            store_mem(fn.cu(wg), k)
            if direct: put(k_v, k)
            else: store_mem(fn.cu(inp), k)
        if direct:   # every lane: the Private words are its own
            def mine():
                put(task_v, mul(fn.op(OP_LOAD, u, buf_at(launch, e)), fn.cu(pay))); put(k_v, fn.op(OP_LOAD, u, buf_at(launch, add(e, fn.cu(1)))))
            when_active(mine)
        when_active(lambda: fn.when(is0, head))
    else:
        when_active(lambda: fn.when(is0, lambda: store_mem(fn.cu(wg), add(first, own))))
    if direct: put(pbase_v, mul(slot, fn.cu(pay if kind == 'ts' else (lay[3] - lay[2]) >> 2)))   # the workgroup's attribute blocks in vtx (a task's payload in taskout)
    if direct and kind == 'ts':   # the payload zero first, as the stage memory was: a task may leave words unwritten (its launch count among them) and meshlaunch.comp and the mesh read them
        pb = fn.op(OP_LOAD, u, pbase_v)
        when_active(lambda: fn.loop(lane, fn.cu(pay), step, lambda i: fn.code.append([OP_STORE, buf_at(taskout, add(pb, i)), fn.cu(0)])))
        fn.code.append([sm.OP_CONTROLBARRIER, fn.cu(sm.SCOPE_WORKGROUP), fn.cu(sm.SCOPE_WORKGROUP), fn.cu(SEM_ACQREL_WORKGROUP_UNIFORM)])   # the zeros land before the body's stores
    else: fn.barrier()
    when_active(lambda: fn.op(OP_FUNCTIONCALL, void, body_fn))
    fn.barrier()
    glsl = next((x[1] for x in ins if x[0] == OP_EXTINSTIMPORT and sa.ext_name([0] + x[2:]) == 'GLSL.std.450'), None)
    ext_import = None
    if glsl is None: glsl = m.new(); ext_import = [OP_EXTINSTIMPORT, glsl, *sm._string('GLSL.std.450')]
    def umin(a, c): return fn.op(OP_EXTINST, u, glsl, GLSL_UMIN, a, c)
    if kind == 'ts':
        if not direct: when_active(lambda: fn.loop(lane, fn.cu(pay), step, lambda i: fn.code.append([OP_STORE, buf_at(taskout, add(mul(slot, fn.cu(pay)), i)), load_mem(add(fn.cu(out), i))])))
    else:
        rec, nrec, nout, ipw, corners, nvc, npc = layout(info)   # nvc, npc: the components per vertex and per primitive, which size the attribute blocks
        max_v, max_p, verts = info['max_v'], info['max_p'], info.get('verts', 3)
        v_stride, p_stride = max(nvc, 1) * BLOCK, max(npc, 1) * BLOCK
        p_out = out + (max(max_v, 1) + BLOCK - 1) // BLOCK * nvc * BLOCK   # spv_mesh.wrap's
        pl = planes(rec); recw = len(pl); area_w = (lay[3] - lay[2]) >> 2
        pw = (prim >> 2) - shift   # the primitive area's word in the shared array

        def block(i, start, stride):   # start + (i / 32) * stride + i % 32 (spv_mesh.wrap's)
            q = fn.op(OP_SHIFTRIGHTLOGICAL, u, i, fn.cu(5)); r = fn.op(OP_BITWISEAND, u, i, fn.cu(BLOCK - 1))
            return add(fn.cu(start), mul(q, fn.cu(stride)), r)

        def corner(n):   # index byte n of the primitive area: its vertex, max_v - 1 at most
            at = add(fn.cu(4), n)
            w = load_mem(add(fn.cu(pw), fn.op(OP_SHIFTRIGHTLOGICAL, u, at, fn.cu(2))))
            sh = fn.op(OP_SHIFTLEFTLOGICAL, u, fn.op(OP_BITWISEAND, u, at, fn.cu(3)), fn.cu(3))
            return umin(fn.op(OP_BITWISEAND, u, fn.op(OP_SHIFTRIGHTLOGICAL, u, w, sh), fn.cu(0xff)), fn.cu(max_v - 1))

        def outputs():
            np_ = umin(fn.op(OP_SHIFTRIGHTLOGICAL, u, load_mem(fn.cu(pw)), fn.cu(24)), fn.cu(max_p))
            live = mul(np_, fn.cu(verts))
            if not corners:
                if not direct:   # the attribute blocks out, word by word
                    pbase = mul(slot, fn.cu(area_w))
                    fn.loop(lane, fn.cu(area_w), step, lambda i: fn.code.append([OP_STORE, buf_at(vtx, add(pbase, i)), load_mem(add(fn.cu(out), i))]))
                def one_index(n):
                    ok = fn.op(OP_ULESSTHAN, b, n, live)
                    v = fn.op(OP_SELECT, u, ok, corner(n), fn.cu(0))
                    fn.code.append([OP_STORE, buf_at(idx, add(mul(slot, fn.cu(ipw)), n)), add(mul(slot, fn.cu(nrec)), v)])
                fn.loop(lane, fn.cu(ipw), step, one_index)
            else:   # a record a corner, plane by plane
                pbase = mul(slot, fn.cu(recw * ipw))
                def one_corner(n):
                    ok = fn.op(OP_ULESSTHAN, b, n, live)
                    v = fn.op(OP_SELECT, u, ok, corner(n), fn.cu(0))
                    p = fn.op(OP_SELECT, u, ok, fn.op(OP_UDIV, u, n, fn.cu(verts)), fn.cu(0))
                    vb, pb = block(v, out, v_stride), block(p, p_out, p_stride)
                    for q, (j, c, s, kk) in enumerate(pl):
                        fn.code.append([OP_STORE, buf_at(vtx, add(pbase, fn.cu(q * ipw), n)), load_mem(add(vb if s == 'v' else pb, fn.cu(kk * BLOCK)))])
                    r = add(mul(slot, fn.cu(ipw)), n)
                    fn.code.append([OP_STORE, buf_at(idx, add(mul(slot, fn.cu(ipw)), n)), fn.op(OP_SELECT, u, ok, r, mul(slot, fn.cu(ipw)))])
                fn.loop(lane, fn.cu(ipw), step, one_corner)
        when_active(outputs)
    fn.code += [[OP_RETURN], [OP_FUNCTIONEND]]
    if kind == 'ms': sm._no_contraction(m, ins + fn.code)
    m.hdr[3] = m.bound
    if m.hdr[1] >= sm.VERSION_1_4:   # 1.4 lists every global the entry point uses: every one
        iface = [x[2] for x in ins if x[0] == OP_VARIABLE and x[3] != SC_FUNCTION] + [x[2] for x in m.glob if x[0] == OP_VARIABLE]
    else: iface = sorted({x[2] for x in ins if x[0] == OP_VARIABLE and x[3] in (SC_INPUT, SC_OUTPUT)} | set(old_iface) | {lid_v, wg_v} | ({sgid_v} if sgid_v else set()))
    out_ins, placed_decor, placed_glob = [], False, False
    first_decor = next(i for i, x in enumerate(ins) if x[0] in (OP_DECORATE, OP_MEMBERDECORATE) or OP_TYPEVOID <= x[0] <= OP_TYPEFUNCTION + 6 or x[0] in (OP_CONSTANT, OP_VARIABLE))
    for i, x in enumerate(ins):
        if x[0] == OP_MEMORYMODEL and ext_import: out_ins.append(ext_import); ext_import = None
        if i == first_decor and not placed_decor: out_ins += m.annot; placed_decor = True
        if x[0] == OP_FUNCTION and not placed_glob: out_ins += m.glob; placed_glob = True
        if x[0] == OP_ENTRY: out_ins.append([OP_ENTRY, MODEL_GLCOMPUTE, entry, *sm._string('main'), *iface]); continue
        if x[0] == OP_EXECMODE and x[1] == body_fn:
            if x[2] == MODE_LOCALSIZE and pack > 1: out_ins.append([OP_EXECMODE, entry, MODE_LOCALSIZE, x[3] * pack, x[4], x[5]])   # the shader's workgroups side by side
            else: out_ins.append([OP_EXECMODE, entry, *x[2:]])
            continue
        out_ins.append(x)
    out_ins += fn.code
    return sa.emit(m.hdr, out_ins), [v for v, _ in bufs], pack, int(bool(direct))


def sa_string_len(words):   # the words of OpEntryPoint's name
    return sm._string_words(words)


def vertex(info, gl=False):
    """A mesh shader's pass-through vertex shader (SPIR-V 1.3 bytes): gl_VertexIndex's components from vtx (a uint[] storage buffer, set 0 binding 0) → its outputs"""
    import spv_android as sa
    rec, nrec, nout, ipw, corners, nvc, npc = layout(info)
    pl = planes(rec); recw = len(pl)
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
    vid = fn.op(OP_BITCAST, u, fn.op(OP_LOAD, i32, vid_v))
    word = {(j, c): p for p, (j, c, _, _) in enumerate(pl)}
    if not corners:   # the attribute blocks: vertex v's component k at (v / 32) * nvc * 32 + k * 32 + v % 32, the blocks of every workgroup end to end
        blk = fn.op(OP_SHIFTRIGHTLOGICAL, u, vid, fn.cu(5)); lane = fn.op(OP_BITWISEAND, u, vid, fn.cu(BLOCK - 1))
        base = fn.op(OP_IADD, u, fn.op(OP_IMUL, u, blk, fn.cu(nvc * BLOCK)), lane)
        at = lambda p: fn.op(OP_IADD, u, base, fn.cu(p * BLOCK))
    else:   # a record a corner, plane by plane
        slot = fn.op(OP_UDIV, u, vid, fn.cu(ipw)); r = fn.op(OP_ISUB, u, vid, fn.op(OP_IMUL, u, slot, fn.cu(ipw)))
        base = fn.op(OP_IADD, u, fn.op(OP_IMUL, u, slot, fn.cu(recw * ipw)), r)
        at = lambda p: fn.op(OP_IADD, u, base, fn.cu(p * ipw))
    for j, (n, _, _) in enumerate(rec):
        def comp(c):
            if (j, c) not in word: return fn.cf(1.0 if c == 3 else 0.0)
            return fn.op(OP_BITCAST, f, fn.op(OP_LOAD, u, fn.op(OP_ACCESSCHAIN, psu, buf, fn.cu(0), at(word[(j, c)]))))
        if n == 'psiz': fn.code.append([OP_STORE, outs[j], comp(0)]); continue
        c = [comp(k) for k in range(4)]
        if n is None and gl: c[2] = fn.op(OP_FMUL, f, fn.op(OP_FADD, f, c[2], c[3]), fn.cf(0.5))   # z' = (z + w) / 2
        fn.code.append([OP_STORE, outs[j], fn.op(OP_COMPOSITECONSTRUCT, v4f, *c)])
    if psiz: fn.code.append([OP_STORE, psiz, fn.cf(1.0)])
    fn.code += [[OP_RETURN], [OP_FUNCTIONEND]]
    m.hdr[3] = m.bound
    iface = [vid_v] + outs + ([psiz] if psiz else [])
    ins = [[OP_CAPABILITY, CAP_SHADER], [OP_MEMORYMODEL, 0, 1], [OP_ENTRY, MODEL_VERTEX, entry, *sm._string('main'), *iface]] + m.annot + m.glob + fn.code
    return sa.emit(m.hdr, ins)
