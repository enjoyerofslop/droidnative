// NVN2 task / mesh draws on a GPU without VK_EXT_mesh_shader (the stock Adreno 830 driver of a OnePlus Pad 3 has none: Ocarina of Time's depth prepass, main pass and
// foliage were all skipped there), included in gfx_vk.c after gfx_vk_mesh.inc. A draw becomes compute dispatches and an indexed draw, of the modules spv_meshemu.py makes
// from the translated kernels (<key>.cs.spv, a mesh shader's <key>.pvs.spv / .pvs.z.spv; res.json mesh_emu):
//   1. the task kernel, the draw's workgroups from its first: each writes its payload to taskout
//   2. meshlaunch.comp, one workgroup: the payloads' launch counts summed into the launch list, and the next two steps' indirect arguments
//   3. the mesh kernel, dispatched indirectly: each workgroup's records (one a vertex, or one a primitive corner when it has outputs per primitive) to vtx, its indices to idx
//   4. the program's fragment shader under the mesh shader's pass-through vertex shader (record gl_VertexIndex from vtx): an indexed indirect draw
// Without a task shader, 1 and 2 are left out: the mesh kernel runs count workgroups from first and the draw is count * ipw indices, both direct. An indirect draw's
// {count, first} record is read on the CPU first (gfx_vk_mesh.inc vk_mesh_draw), so every count is known here. The buffers are ranges of one GPU-only arena that every
// draw uses from its start: each step ends in a full barrier (cb_barrier) and a draw's pass ends before the next draw's dispatches (rp_end), so the outputs a draw read
// are finished with when the next one writes them. A draw larger than the arena goes in parts: without a task by workgroups, with one by task workgroups, a part's mesh
// workgroups up to DM_VK_MESH_MAX (the launches past it are dropped). The kernels' own bindings are the host's task and mesh stages', as gfx_vk_mesh.inc binds them
// (stage_set), at set 0; the emulation's buffers are set 1 (spv_meshemu.MESH_SET); the pass-through vertex shader's vtx is its set 0.
// The same design as DeathKhan's nx2android fork's mesh emulation (github.com/DeathKhan/nx2android: 1f7e70b, 0e3285b, defd439), written anew for this replay.
// DM_VK_MESH_EMU=0 (env.txt): the draws are skipped, as before. DM_VK_MESH_ARENA_MB (default 64), DM_VK_MESH_MAX (default 4096)
static const uint32_t MESHLAUNCH[] = {
#include "shaders/meshlaunch_comp.inc"
};
enum { ME_HDR = 16, ME_PC = 8, ME_ALIGN = 256 };   // launch list words before its entries (spv_meshemu.HDR); push constant bytes {first, base}
typedef struct memu_t { int task, pay, threads, nrec, nout, ipw, verts; VkPipeline p; VkPipelineLayout pl; int bad; vshader *pvs; } memu_t;
static struct { VkBuffer b; VkDeviceMemory m; VkDeviceSize size; int bad; } g_me;
static vshader g_me_kset, g_me_lset;   // their layouts alone, for ds_get's sets kept by each chunk: the kernels' set 1 (four buffers), meshlaunch.comp's set (two)
static VkDescriptorSetLayout g_me_vdsl;   // the pass-through vertex shaders' set: vtx
static VkPipeline g_me_launch; static VkPipelineLayout g_me_lpl; static int g_me_kbad;
static uint64_t g_me_draws, g_me_parts, g_me_skipped;
static int memu_on(void) { static int on = -1; if (on < 0) { const char *e = getenv("DM_VK_MESH_EMU"); on = !(e && *e == '0'); } return on && !g_mesh; }
static int memu_facts(vshader *s, const jv *e) {   // res.json mesh_emu (null: spv_meshemu.py could not make the compute form)
    if (!e || js_int(e, "pay", 0) <= 0) return 0;
    memu_t *m = calloc(1, sizeof *m); if (!m) return 0;
    m->pay = js_int(e, "pay", 1); m->threads = js_int(e, "threads", 32); m->task = js_int(e, "task", 0);
    m->nrec = js_int(e, "nrec", 0); m->nout = js_int(e, "nout", 0); m->ipw = js_int(e, "ipw", 0); m->verts = js_int(e, "verts", 3);
    if (s->stage == SH_MS && (m->nrec <= 0 || m->nout <= 0 || m->ipw <= 0)) { free(m); return 0; }
    s->memu = m; return 1;
}
static VkDescriptorSetLayout memu_dsl(uint32_t n, VkShaderStageFlags st) {   // n storage buffers at bindings 0 to n - 1
    VkDescriptorSetLayoutBinding b[4]; for (uint32_t i = 0; i < n; i++) b[i] = (VkDescriptorSetLayoutBinding){i, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, st, NULL};
    VkDescriptorSetLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO, .bindingCount = n, .pBindings = b}; VkDescriptorSetLayout l;
    return vkCreateDescriptorSetLayout(g_vk.dev, &lc, NULL, &l) == VK_SUCCESS ? l : VK_NULL_HANDLE;
}
// A pass-through vertex shader's key: its mesh shader's with each hex digit moved to 'g'..'v'. The pipeline list (prewarm_thread) records a pipeline's shaders by key and
// makes them again with sh_get, which takes this key back to the mesh shader's pass-through vertex shader; under the mesh shader's own key it made the compute form, which
// as a vertex stage crashed Qualcomm's vkCreateGraphicsPipelines at the next start (OnePlus Pad 3, Adreno 830)
static void memu_pvs_key(const char *mk, char *out) { for (int i = 0; i < 16; i++) { char c = mk[i]; out[i] = (char)('g' + (c <= '9' ? c - '0' : c - 'a' + 10)); } out[16] = 0; }
static vshader *memu_pvs_get(const char *key) {
    char mk[17]; for (int i = 0; i < 16; i++) { int d = key[i] - 'g'; if (d < 0 || d > 15) return NULL; mk[i] = (char)(d < 10 ? '0' + d : 'a' + d - 10); } mk[16] = 0;
    vshader *ms = sh_get(mk); return ms && ms->memu ? ms->memu->pvs : NULL;
}
static vshader *memu_pvs(const vshader *ms) {   // a mesh shader's pass-through vertex shader, as a vertex shader the pipelines take (pipe_get)
    vshader *v = calloc(1, sizeof *v); if (!v) return NULL;
    memu_pvs_key(ms->key, v->key); v->stage = SH_VS; v->vkstage = VK_SHADER_STAGE_VERTEX_BIT; v->set = 0; v->vid = 1;
    char p[700]; int b0 = 0; snprintf(p, sizeof p, "%s/%s.pvs.spv", g_spv_dir, ms->key); v->mod = sh_module(p, &b0);
    { size_t nw = 0; uint32_t *w = spv_read(p, &nw); if (w) { spv_io(w, nw, &v->io_in, &v->io_out); free(w); } }
    snprintf(p, sizeof p, "%s/%s.pvs.z.spv", g_spv_dir, ms->key); v->modz = sh_module(p, &b0);
    if (!g_me_vdsl) g_me_vdsl = memu_dsl(1, VK_SHADER_STAGE_VERTEX_BIT);
    v->dsl = g_me_vdsl; v->ndesc = 1;
    if (!v->mod || !v->dsl) { RED_ONCE(181, "mesh shader %s: no pass-through vertex shader (.pvs.spv): its draws are skipped", ms->key); free(v); return NULL; }
    v->ok = 1; return v;
}
static int memu_ready(vshader *s) { return s->stage != SH_MS || (s->memu->pvs = memu_pvs(s)) != NULL; }
static int memu_arena(void) {
    if (g_me.b || g_me.bad) return !g_me.bad;
    g_me.bad = 1; const char *e = getenv("DM_VK_MESH_ARENA_MB"); VkDeviceSize mb = e && atoi(e) > 0 ? (VkDeviceSize)atoi(e) : 64;
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = mb << 20, .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT | VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT};
    if (vkCreateBuffer(g_vk.dev, &bi, NULL, &g_me.b) != VK_SUCCESS) { g_me.b = VK_NULL_HANDLE; RED_ONCE(182, "task / mesh draws in compute form: no arena buffer: skipped"); return 0; }
    VkMemoryRequirements rq; vkGetBufferMemoryRequirements(g_vk.dev, g_me.b, &rq);
    VkMemoryAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = rq.size, .memoryTypeIndex = vkb_mem_type(rq.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    if (ai.memoryTypeIndex == UINT32_MAX || vkAllocateMemory(g_vk.dev, &ai, NULL, &g_me.m) != VK_SUCCESS || vkBindBufferMemory(g_vk.dev, g_me.b, g_me.m, 0) != VK_SUCCESS) {
        vkDestroyBuffer(g_vk.dev, g_me.b, NULL); g_me.b = VK_NULL_HANDLE; RED_ONCE(182, "task / mesh draws in compute form: no arena memory: skipped"); return 0; }
    g_me.size = mb << 20; g_me.bad = 0;
    LOG("[vk] task / mesh draws in compute form (no VK_EXT_mesh_shader): a %llu MB arena for their outputs (DM_VK_MESH_ARENA_MB)", (unsigned long long)mb);
    return 1;
}
static int memu_kernels(void) {   // the emulation's set layouts and meshlaunch.comp
    if (g_me_launch || g_me_kbad) return !g_me_kbad;
    g_me_kbad = 1;
    g_me_kset.dsl = memu_dsl(4, VK_SHADER_STAGE_COMPUTE_BIT); g_me_kset.ndesc = 4; g_me_kset.ok = 1; memcpy(g_me_kset.key, "mesh-emu-kernel", 16);
    g_me_lset.dsl = memu_dsl(2, VK_SHADER_STAGE_COMPUTE_BIT); g_me_lset.ndesc = 2; g_me_lset.ok = 1; memcpy(g_me_lset.key, "mesh-emu-launch", 16);
    if (!g_empty_dsl) { VkDescriptorSetLayoutCreateInfo ec = {.sType = VK_STRUCTURE_TYPE_DESCRIPTOR_SET_LAYOUT_CREATE_INFO}; vkCreateDescriptorSetLayout(g_vk.dev, &ec, NULL, &g_empty_dsl); }
    if (!g_me_kset.dsl || !g_me_lset.dsl || !g_empty_dsl) return 0;
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, 16};
    VkPipelineLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = 1, .pSetLayouts = &g_me_lset.dsl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr};
    VkShaderModuleCreateInfo mc = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = sizeof MESHLAUNCH, .pCode = MESHLAUNCH}; VkShaderModule sm;
    if (vkCreatePipelineLayout(g_vk.dev, &lc, NULL, &g_me_lpl) != VK_SUCCESS || vkCreateShaderModule(g_vk.dev, &mc, NULL, &sm) != VK_SUCCESS) return 0;
    VkComputePipelineCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = g_me_lpl,
        .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = sm, .pName = "main"}};
    VkResult r = vkCreateComputePipelines(g_vk.dev, pcache(), 1, &pc, NULL, &g_me_launch); vkDestroyShaderModule(g_vk.dev, sm, NULL);
    if (r != VK_SUCCESS) { g_me_launch = VK_NULL_HANDLE; return 0; }
    g_me_kbad = 0; return 1;
}
static int memu_cpipe(vshader *s) {   // a task or mesh kernel's compute pipeline: its own set, the emulation's, the pool set when it reads the pool
    memu_t *m = s->memu; if (m->p) return 1; if (m->bad) return 0;
    m->bad = 1;
    VkDescriptorSetLayout sl[POOL_SET + 1] = {s->dsl, g_me_kset.dsl, g_empty_dsl, g_empty_dsl, g_pool_dsl};
    VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, ME_PC};
    VkPipelineLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = s->pool ? POOL_SET + 1 : 2, .pSetLayouts = sl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr};
    if (vkCreatePipelineLayout(g_vk.dev, &lc, NULL, &m->pl) != VK_SUCCESS) return 0;
    VkComputePipelineCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = m->pl,
        .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .module = s->mod, .pName = "main"}};
    const char *pbk[4] = {s->key, NULL, NULL, NULL}; int pb = pb_begin('c', pbk, 0, 0, 0, 0);
    VkResult r = vkCreateComputePipelines(g_vk.dev, pcache(), 1, &pc, NULL, &m->p); pb_end(pb);
    if (r != VK_SUCCESS) { m->p = VK_NULL_HANDLE; static int n; if (n++ < 8) LOG("[RED] [vk] compute form of task / mesh shader %s: pipeline failed: its draws are skipped", s->key); return 0; }
    m->bad = 0; return 1;
}
static VkDescriptorSet memu_set(vshader *l, uint32_t n, const VkDeviceSize *off, const VkDeviceSize *len) {   // a set of l's layout over n arena ranges, from the current chunk
    VkDescriptorSet set = ds_get(l, 0); if (!set) return VK_NULL_HANDLE;
    VkDescriptorBufferInfo bi[4]; VkWriteDescriptorSet w[4];
    for (uint32_t i = 0; i < n; i++) { bi[i] = (VkDescriptorBufferInfo){g_me.b, off[i], len[i]};
        w[i] = (VkWriteDescriptorSet){.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = set, .dstBinding = i, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi[i]}; }
    vkUpdateDescriptorSets(g_vk.dev, n, w, 0, NULL); return set;
}
// one dispatch of a task or mesh kernel over the arena ranges r[4] (taskout, launch, vtx, idx): groups workgroups, or (0) the launch list header's counts at ind
static int memu_kernel(vshader *s, const prog_t *pr, int pst, const VkDeviceSize r[8], uint32_t first, uint32_t groups, VkDeviceSize ind) {
    VkDescriptorSet set, es; uint32_t dyn[18]; int ok;
    for (int t = 0;; t++) {   // as vk_dispatch: the set taken again when a sync inside stage_set closed the chunk it came from
        g_bind_bad = 0; if (!cur()) return 0; uint64_t dseq = C->seq; int got = stage_set(s, 0, &set, dyn, pr, pst, 0, dseq); ok = got && !g_bind_bad;
        if (got || !ds_moved(dseq)) break;
        if (ds_again(t, 2)) return 0;
    }
    if (!ok || !(es = memu_set(&g_me_kset, 4, r, r + 4))) return 0;
    VkCommandBuffer c = cb(); if (!c) return 0;
    cb_barrier();
    memu_t *m = s->memu; uint32_t pc[2] = {first, 0};
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->p);
    vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->pl, 0, 1, &set, s->ndyn, dyn);
    vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->pl, 1, 1, &es, 0, NULL);
    if (s->pool && !pool_bind(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->pl)) return 0;
    vkCmdPushConstants(c, m->pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, ME_PC, pc);
    if (groups) vkCmdDispatch(c, groups, 1, 1); else vkCmdDispatchIndirect(c, g_me.b, ind);
    cb_barrier(); g_dispatches++; C->ndraw++;
    return 1;
}
static int memu_launch(const VkDeviceSize r[8], uint32_t ntask, const memu_t *ts, const memu_t *ms, uint32_t cap) {   // meshlaunch.comp over taskout and launch
    if (!cur()) return 0;
    VkDescriptorSet set = memu_set(&g_me_lset, 2, r, r + 4); VkCommandBuffer c = cb(); if (!set || !c) return 0;
    uint32_t pc[4] = {ntask, (uint32_t)ts->pay, cap, (uint32_t)ms->ipw};
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, g_me_launch); vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, g_me_lpl, 0, 1, &set, 0, NULL);
    vkCmdPushConstants(c, g_me_lpl, VK_SHADER_STAGE_COMPUTE_BIT, 0, 16, pc); vkCmdDispatch(c, 1, 1, 1); cb_barrier(); g_dispatches++;
    return 1;
}
// the draw of a part: the fragment shader under the pass-through vertex shader, nidx indices (0: the launch list header's draw arguments)
static int memu_draw(memu_t *m, vshader *fs, const prog_t *fpr, int fpst, const VkDeviceSize r[8], uint32_t nidx) {
    pipe_key k; memset(&k, 0, sizeof k); k.sh[0] = m->pvs; k.sh[1] = fs;
    if (!rp_prepare_(0)) { g_drop[1]++; return 0; }
    g_drawing = 1;
    pipe_key_build(&k, m->verts == 3 ? 4 : m->verts == 2 ? 1 : 0);   // NVN's triangles, lines, points
    pipe_t *pp = pipe_get(&k); if (!pp) { g_drop[2]++; return 0; }
    VkDescriptorSet fset = VK_NULL_HANDLE, vset; uint32_t dyn[18];
    for (int t = 0;; t++) {
        g_bind_bad = 0; if (!cur()) { g_drop[3]++; return 0; }
        uint64_t dseq = C->seq;
        if (!fs || stage_set(fs, 0, &fset, dyn, fpr, fpst, 0, dseq)) break;
        if (!ds_moved(dseq) || ds_again(t, 0)) { g_drop[3]++; return 0; }
    }
    if (g_bind_bad) { g_drop[4]++; return 0; }
    if (!(vset = memu_set(m->pvs, 1, r + 2, r + 6))) { g_drop[3]++; return 0; }
    if (!rp_start()) { g_drop[5]++; return 0; }
    VkCommandBuffer c = C->cb;
    occl_begin();
    bf_pipeline(c, pp->p);
    vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pp->pl, 0, 1, &vset, 0, NULL);
    if (fs) vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pp->pl, (uint32_t)(fs->set & 3), 1, &fset, fs->ndyn, dyn);
    if (fs && fs->pool && !pool_bind(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pp->pl)) { g_drop[3]++; return 0; }
    VkViewport v; VkRect2D sc; draw_dyn_state(c, &v, &sc); (void)v; (void)sc;
    bf_ibuf(c, g_me.b, r[3], VK_INDEX_TYPE_UINT32);
    if (nidx) vkCmdDrawIndexed(c, nidx, 1, 0, 0, 0); else vkCmdDrawIndexedIndirect(c, g_me.b, r[1] + 16, 1, 20);
    g_draws++; C->ndraw++;
    if (g_prof_cur >= 0) g_prof[g_prof_cur].draws++;
    return 1;
}
static VkDeviceSize me_up(VkDeviceSize n) { return (n + ME_ALIGN - 1) & ~(VkDeviceSize)(ME_ALIGN - 1); }
static int vk_memu_draw_(const p_draw *dw) {
    if (!g_d_init) draw_state_reset();
    vshader *sh[3] = {0}; int pst[3] = {-1, -1, -1}; const prog_t *ppr[3] = {0};
    const prog_t *src[3] = {D.bst[4], D.bst[1], D.bst[3]}; const int want[3] = {SH_MS, SH_PS, SH_TK};   // mesh, fragment, task (gfx_vk_mesh.inc's order)
    for (int q = 0; q < 3; q++) { const prog_t *pr = src[q]; if (!pr) continue;
        for (unsigned i = 0; i < pr->nstage && i < 6; i++) {
            uint8_t key[8]; char hx[17]; if (!prog_key(pr, i, key)) continue; key_hex(key, hx);
            vshader *s = sh_get(hx); if (!s) { g_drop[0]++; g_me_skipped++; return 0; }
            if (s->stage != want[q]) continue;
            sh[q] = s; pst[q] = (int)i; ppr[q] = pr; break;
        } }
    vshader *ms = sh[0], *fs = sh[1], *ts = sh[2];
    if (!ms) { RED_ONCE(160, "DrawMeshTasks with no mesh shader bound: draw skipped"); return 0; }
    memu_t *m = ms->memu; if (!m || !m->pvs) { g_me_skipped++; return 0; }
    if (m->task && (!ts || !ts->memu)) { RED_ONCE(180, "mesh shader %s takes a task shader's payload, and its program has no task shader in compute form: draw skipped", ms->key); g_me_skipped++; return 0; }
    if (!m->task) ts = NULL;
    if (!memu_arena() || !memu_kernels() || !memu_cpipe(ms) || (ts && !memu_cpipe(ts))) { g_drop[2]++; g_me_skipped++; return 0; }
    { vshader *vw[4] = {ms, fs, ts, NULL}; draw_view(vw, NULL, 0);   // what the stages read of guest memory: pending GPU writes to it land first
      for (int i = 0; i < 3; i++) if (vw[i]) stage_textures(vw[i]);
      if (ms->pool || (fs && fs->pool) || (ts && ts->pool)) pool_sync(); }
    static uint32_t cap_max; if (!cap_max) { const char *e = getenv("DM_VK_MESH_MAX"); cap_max = e && atoi(e) > 0 ? (uint32_t)atoi(e) : 4096; }
    VkDeviceSize per = me_up((VkDeviceSize)m->nrec * m->nout * 16) + me_up((VkDeviceSize)m->ipw * 4);   // a mesh workgroup's records and indices
    VkDeviceSize usable = g_me.size - 8 * ME_ALIGN, half = usable / 2;   // (the ranges' alignment)
    uint64_t room = (ts ? half : usable) / per; uint32_t cap = room < cap_max ? (uint32_t)room : cap_max; if (cap > 65535) cap = 65535;
    if (!cap) { RED_ONCE(183, "mesh shader %s: one workgroup's outputs exceed the arena (DM_VK_MESH_ARENA_MB): draw skipped", ms->key); g_me_skipped++; return 0; }
    // the arena's ranges, offsets then lengths: taskout, launch, vtx, idx
    VkDeviceSize r[8]; r[4] = ts ? 0 : ME_ALIGN; r[5] = ts ? me_up(((VkDeviceSize)ME_HDR + 2ull * cap) * 4) : ME_ALIGN;
    r[6] = (VkDeviceSize)cap * m->nrec * m->nout * 16; r[7] = (VkDeviceSize)cap * m->ipw * 4;
    uint32_t tmax = 0;
    if (ts) { VkDeviceSize left = half > r[5] ? half - r[5] : 0; uint64_t t = left / ((VkDeviceSize)ts->memu->pay * 4); tmax = t > 65535 ? 65535 : (uint32_t)t;
        if (!tmax) { RED_ONCE(183, "task shader %s: its payloads exceed the arena (DM_VK_MESH_ARENA_MB): draw skipped", ts->key); g_me_skipped++; return 0; } }
    uint32_t first = (uint32_t)dw->first, left = (uint32_t)dw->count;
    while (left) {
        uint32_t n = ts ? (left < tmax ? left : tmax) : (left < cap ? left : cap);
        if (ts) r[4] = me_up((VkDeviceSize)n * ts->memu->pay * 4);
        r[0] = 0; r[1] = me_up(r[0] + r[4]); r[2] = me_up(r[1] + r[5]); r[3] = me_up(r[2] + r[6]);
        rp_end(); tc_clear();
        if (ts) {
            if (!memu_kernel(ts, ppr[2], pst[2], r, first, n, 0) || !memu_launch(r, n, ts->memu, m, cap) || !memu_kernel(ms, ppr[0], pst[0], r, 0, 0, r[1])) { g_me_skipped++; return 0; }
        } else if (!memu_kernel(ms, ppr[0], pst[0], r, first, n, 0)) { g_me_skipped++; return 0; }
        if (!memu_draw(m, fs, ppr[1], pst[1], r, ts ? 0 : n * (uint32_t)m->ipw)) { g_me_skipped++; return 0; }
        first += n; left -= n; g_me_parts++;
    }
    g_me_draws++;
    if (g_me_draws == 1) LOG("[vk] task / mesh draws in compute form: first draw, task %s mesh %s fragment %s, %d workgroups from %d (a part's most mesh workgroups %u)",
                             ts ? ts->key : "-", ms->key, fs ? fs->key : "-", dw->count, dw->first, cap);
    if (dump_on()) LOG("[dump] pass %d draw %llu: task %s mesh %s fs %s in compute form, %d workgroups from %d", g_dump_pass + 1, (unsigned long long)g_draws,
                       ts ? ts->key : "-", ms->key, fs ? fs->key : "-", dw->count, dw->first);
    return 1;
}
