// NVN2 task / mesh draws on a GPU without VK_EXT_mesh_shader (the stock Adreno 830 driver of a OnePlus Pad 3 has none: Ocarina of Time's depth prepass, main pass and
// foliage were all skipped there), included in gfx_vk.c after gfx_vk_mesh.inc. A draw becomes compute dispatches and an indexed draw, of the modules spv_meshemu.py makes
// from the translated kernels (<key>.cs.spv, a mesh shader's <key>.pvs.spv / .pvs.z.spv; res.json mesh_emu):
//   1. the task kernel, the draw's workgroups from its first: each writes its payload to taskout
//   2. meshlaunch.comp, one workgroup: the payloads' launch counts summed into the launch list, and the next two steps' indirect arguments
//   3. the mesh kernel, dispatched indirectly: each workgroup's records (one a vertex, or one a primitive corner when it has outputs per primitive) to vtx, its indices to idx
//   4. the program's fragment shader under the mesh shader's pass-through vertex shader (record gl_VertexIndex from vtx): an indexed indirect draw
// Without a task shader, 1 and 2 are left out: the mesh kernel runs count workgroups from first and the draw is count * ipw indices, both direct. An indirect draw's
// {count, first} record is read on the CPU first (gfx_vk_mesh.inc vk_mesh_draw), so every count is known here. The buffers are ranges of one GPU-only arena. A draw larger
// than the arena goes in parts: without a task by workgroups, with one by task workgroups, a part's mesh workgroups up to DM_VK_MESH_MAX (the launches past it are dropped).
// The kernels' own bindings are the host's task and mesh stages', as gfx_vk_mesh.inc binds them (stage_set), at set 0; the emulation's buffers are set 1
// (spv_meshemu.MESH_SET); the pass-through vertex shader's vtx is its set 0.
// The same design as DeathKhan's nx2android fork's mesh emulation (github.com/DeathKhan/nx2android: 1f7e70b, 0e3285b, defd439), written anew for this replay.
//
// The kernels ahead of the pass. Every draw used to end the pass (rp_end: its targets stored and loaded again, 70 to 90 us each at 1440x810 on an Adreno 830 / 840), run its
// kernels inside full barriers on both sides from the arena's start, and begin the pass again for its draw: Ocarina of Time's Kokiri Forest draws about 65 task / mesh draws a
// frame, so 44 to 62 single-draw pass pieces (2.6 ms of a 27 ms frame on a OnePlus Pad 3, 5.6 of 56 on a Galaxy S25 Edge) and about 200 barriers. Now, once a game has drawn
// one such draw, every render pass is recorded in a command buffer of its own, the chunk's next (gfx_vk_draw.inc rp_start, pass_sec_on), and the kernels go into the one before it,
// in the order the draws come, each draw's outputs in arena ranges of its own (a bump allocation, free again when the pass ends: memu_pass_done), so the pass is not cut and the
// GPU runs the kernels first and the pass whole (a secondary command buffer executed inside the pass cost Samsung's Adreno 830 / 840 builds 5 to 10 % of their GPU time instead). The barriers follow the dependencies: one before meshlaunch.comp (it reads the task kernel's payloads) and before the mesh
// kernel (it reads the launch list) always; before a task kernel, or a mesh kernel without one, only when the command before it is not one of these kernels (after a copy, a
// pass or a game dispatch: a full barrier, as before; after another kernel none, their arena ranges are distinct and their guest reads were ordered before the run); and one
// before the pass begins (rp_end closes the run, as cs_chain_close does for the game's dispatches: the kernels leave the run open, g_me_chain). The pass still ends first, as
// before, when the kernels read what a draw of the open pass wrote in place (draw_view and fwd_hit note it: g_dv_pass_hit), when the arena has no room left for the draw's
// ranges, or when the draw goes in parts. A draw with a task shader reserves room for DM_VK_MESH_LA_CAP mesh workgroups (its launches are known only on the GPU; meshlaunch.comp
// drops those past the cap, as DM_VK_MESH_MAX did); one without reserves what it has. The same design as Banana Native's look-ahead (its docs/reference/rendering.md "Mesh
// draws through compute"), written anew for this replay's chunks and recorder.
// DM_VK_MESH_EMU=0 (env.txt): the draws are skipped, as before. DM_VK_MESH_ARENA_MB (default 64), DM_VK_MESH_MAX (default 4096), DM_VK_MESH_LA=1: the kernels ahead of the
// pass (off by default: la_mode); DM_VK_MESH_LA_CAP=<n> (default 1024); DM_VK_MESH_STAT=1: each task draw's launch count read back (memu_stat_print)
static const uint32_t MESHLAUNCH[] = {
#include "shaders/meshlaunch_comp.inc"
};
enum { ME_HDR = 16, ME_PC = 8, ME_ALIGN = 256, ME_KBIND = 100 };   // ME_KBIND: the kernels' set 1 bindings, 100 to 103 (spv_meshemu.B_TASKOUT ...)   // launch list words before its entries (spv_meshemu.HDR); push constant bytes {first, base}
typedef struct memu_t { int task, pay, threads, nrec, nout, ipw, verts; VkPipeline p; VkPipelineLayout pl; int bad; vshader *pvs;
                        int queued; int bgdone; VkPipeline bgp; uint64_t bgns; } memu_t;   // queued: its pipeline is being built in the background (the replay's); bgdone, bgp, bgns: that build's result, under g_me_mu (memu_cpipe)
static struct { VkBuffer b; VkDeviceMemory m; VkDeviceSize size; int bad; } g_me;
static vshader g_me_kset, g_me_lset;   // their layouts alone, for ds_get's sets kept by each chunk: the kernels' set 1 (four buffers), meshlaunch.comp's set (two)
static VkDescriptorSetLayout g_me_vdsl;   // the pass-through vertex shaders' set: vtx
static VkPipeline g_me_launch; static VkPipelineLayout g_me_lpl; static int g_me_kbad;
static uint64_t g_me_draws, g_me_parts, g_me_skipped, g_me_left, g_me_kpipes, g_me_kbg, g_me_kcached;   // draws, their parts, skipped; left out while a kernel's pipeline was built; kernel pipelines made, of them in the background / from the driver's cache at once
static _Atomic uint64_t g_me_kpipe_ns;
static int memu_on(void) { static int on = -1; if (on < 0) { const char *e = getenv("DM_VK_MESH_EMU"); on = !(e && *e == '0'); } return on && !g_mesh; }
// ---- the kernels ahead of the pass (the comment above) ----
// DM_VK_MESH_LA: 0 (default) every draw cuts the pass, as before; 1 the kernels ahead of the pass; 2 (a diagnostic) the passes in command buffers of their own but every draw cutting the pass as before.
// Off by default: measured in Kokiri Forest it is worth about 0.5 ms of a OnePlus Pad 3's 27 ms GPU frame, and nothing or a loss on a Galaxy S25 Edge and Z Fold 8, where the pass
// in a command buffer of its own costs their driver builds about as much as the pass breaks did (the numbers in docs/reference/rendering.md)
static int la_mode(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_MESH_LA"); v = !e ? 0 : atoi(e); if (v) LOG("[vk] DM_VK_MESH_LA=%d: %s", v, v == 1 ? "render passes in command buffers of their own, the compute form's kernels ahead of each" : "render passes in command buffers of their own, every task / mesh draw in compute form cutting the pass as before (diagnostic)"); } return v; }
static int la_on(void) { return la_mode() == 1; }
static uint32_t la_cap(void) { static uint32_t v; if (!v) { const char *e = getenv("DM_VK_MESH_LA_CAP"); v = e && atoi(e) > 0 ? (uint32_t)atoi(e) : 1024; } return v; }
static int g_me_seen;   // a draw reached its kernels once: from then on every pass takes a command buffer of its own (gfx_vk_draw.inc rp_start, pass_sec_on); a game without such draws pays nothing
static int pass_sec_on(void) { return g_me_seen && la_mode() != 0; }
static VkDeviceSize g_me_cur;   // the arena's first free byte for the next draw's ranges; 0 again once the pass they are drawn in ended (every kernel after it is behind a barrier)
static VkDeviceSize g_me_keep;   // the end of the ranges of a draw whose kernels are recorded and whose draw is not yet (0: none): a pass ending in between (a sync inside the draw's stage_set closed the chunk) must not free them, the draw's pass comes later
static int g_me_wrote;   // a kernel of the open run writes guest memory, or reads raw global memory (which may store): the next draw's first kernel takes a barrier too
static void memu_pass_done(void) { g_me_cur = g_me_keep; }
static uint64_t g_me_la_draws, g_me_la_cut, g_me_la_breaks[3];   // draws whose kernels went ahead of their pass / that cut the pass as before; passes ended first for a dependency / for room in the arena / for a draw in parts
static VkCommandBuffer cb_pre(void) {   // where a kernel goes: the command buffer before the open pass's own (g_cbk), or the chunk's current one when no pass is open; cb() when the chunk is not begun
    if (P.active) return P.sec ? g_cbk : cb();   // (a pass in the chunk's current command buffer: it ends, as before)
    if (C && C->open) return C->cb;   // (no pass open: the primary; cb() would close a run of the game's dispatches with a barrier, which memu_kernel's own rule puts)
    return cb();
}
static int memu_chained(void) { if (!(g_cs_chain && C && C->seq == g_cs_chain_seq && g_me_chain)) g_me_wrote = 0; return g_cs_chain && C && C->seq == g_cs_chain_seq && g_me_chain; }   // the command before is one of these kernels (gfx_vk.c); a run closed by a barrier has nothing pending
static void memu_chain(void) { g_cs_chain = 1; g_cs_chain_seq = C->seq; g_cs_gbar = 1; g_me_chain = 1; }   // the run stays open: the next kernel's own rule, a game dispatch (a barrier: g_cs_gbar) or a command of another kind (cs_chain_close) ends it
static int memu_facts(vshader *s, const jv *e) {   // res.json mesh_emu (null: spv_meshemu.py could not make the compute form)
    if (!e || js_int(e, "pay", 0) <= 0) return 0;
    memu_t *m = calloc(1, sizeof *m); if (!m) return 0;
    m->pay = js_int(e, "pay", 1); m->threads = js_int(e, "threads", 32); m->task = js_int(e, "task", 0);
    m->nrec = js_int(e, "nrec", 0); m->nout = js_int(e, "nout", 0); m->ipw = js_int(e, "ipw", 0); m->verts = js_int(e, "verts", 3);
    if (s->stage == SH_MS && (m->nrec <= 0 || m->nout <= 0 || m->ipw <= 0)) { free(m); return 0; }
    s->memu = m; return 1;
}
static VkDescriptorSetLayout memu_dsl(uint32_t n, uint32_t base, VkShaderStageFlags st) {   // n storage buffers at bindings base to base + n - 1
    VkDescriptorSetLayoutBinding b[4]; for (uint32_t i = 0; i < n; i++) b[i] = (VkDescriptorSetLayoutBinding){base + i, VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, 1, st, NULL};
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
    char p[700]; int b0 = 0; snprintf(p, sizeof p, "%s/%s.pvs.spv", g_spv_dir, ms->key); v->mod = sh_module(v, p, &b0);
    { size_t nw = 0; uint32_t *w = spv_read(p, &nw); if (w) { spv_io(w, nw, &v->io_in, &v->io_out); free(w); } }
    snprintf(p, sizeof p, "%s/%s.pvs.z.spv", g_spv_dir, ms->key); v->modz = sh_module(v, p, &b0);
    if (!g_me_vdsl) g_me_vdsl = memu_dsl(1, 0, VK_SHADER_STAGE_VERTEX_BIT);
    v->dsl = g_me_vdsl; v->ndesc = 1;
    if (!v->mod || !v->dsl) { RED_ONCE(181, "mesh shader %s: no pass-through vertex shader (.pvs.spv): its draws are skipped", ms->key); free(v); return NULL; }
    v->ok = 1; return v;
}
static int memu_ready(vshader *s) { return s->stage != SH_MS || (s->memu->pvs = memu_pvs(s)) != NULL; }
static int memu_arena(void) {
    if (g_me.b || g_me.bad) return !g_me.bad;
    g_me.bad = 1; const char *e = getenv("DM_VK_MESH_ARENA_MB"); VkDeviceSize mb = e && atoi(e) > 0 ? (VkDeviceSize)atoi(e) : 64;
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = mb << 20, .sharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .usage = VK_BUFFER_USAGE_STORAGE_BUFFER_BIT | VK_BUFFER_USAGE_INDEX_BUFFER_BIT | VK_BUFFER_USAGE_INDIRECT_BUFFER_BIT | VK_BUFFER_USAGE_TRANSFER_SRC_BIT};
    if (vkCreateBuffer(g_vk.dev, &bi, NULL, &g_me.b) != VK_SUCCESS) { g_me.b = VK_NULL_HANDLE; RED_ONCE(182, "task / mesh draws in compute form: no arena buffer: skipped"); return 0; }
    VkMemoryRequirements rq; vkGetBufferMemoryRequirements(g_vk.dev, g_me.b, &rq);
    VkMemoryAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = rq.size, .memoryTypeIndex = vkb_mem_type(rq.memoryTypeBits, VK_MEMORY_PROPERTY_DEVICE_LOCAL_BIT)};
    if (ai.memoryTypeIndex == UINT32_MAX || vkAllocateMemory(g_vk.dev, &ai, NULL, &g_me.m) != VK_SUCCESS || vkBindBufferMemory(g_vk.dev, g_me.b, g_me.m, 0) != VK_SUCCESS) {
        vkDestroyBuffer(g_vk.dev, g_me.b, NULL); g_me.b = VK_NULL_HANDLE; RED_ONCE(182, "task / mesh draws in compute form: no arena memory: skipped"); return 0; }
    g_me.size = mb << 20; g_me.bad = 0;
    LOG("[vk] task / mesh draws in compute form (no VK_EXT_mesh_shader): a %llu MB arena for their outputs (DM_VK_MESH_ARENA_MB)%s", (unsigned long long)mb,
        la_on() ? "; the kernels go ahead of the pass (DM_VK_MESH_LA)" : "");
    return 1;
}
static int memu_kernels(void) {   // the emulation's set layouts and meshlaunch.comp
    if (g_me_launch || g_me_kbad) return !g_me_kbad;
    g_me_kbad = 1;
    g_me_kset.dsl = memu_dsl(4, ME_KBIND, VK_SHADER_STAGE_COMPUTE_BIT); g_me_kset.ndesc = 4; g_me_kset.ok = 1; memcpy(g_me_kset.key, "mesh-emu-kernel", 16);
    g_me_lset.dsl = memu_dsl(2, 0, VK_SHADER_STAGE_COMPUTE_BIT); g_me_lset.ndesc = 2; g_me_lset.ok = 1; memcpy(g_me_lset.key, "mesh-emu-launch", 16);
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
// A task or mesh kernel's compute pipeline: its own set, the emulation's, the pool set when it reads the pool. The compile is the driver's on a module of 100 to 560 KB,
// and Samsung's Xclipse 950 compiler takes 2 to 11 s on the larger ones: on a Galaxy Z Flip 7 Kokiri Forest's first frame made 31 of them in 52 s on the replay thread,
// the game waiting. So:
// - a kernel the driver's cache has is taken from it at once, where modules are identifiers (g_smid): asked for by the identifier, as lm_pipeline's first step, which
//   answers without a compile (43 of the forest's in 8 ms on a warm start);
// - one that needs a compile is built in the background, on the threads that build graphics pipelines met for the first time, and its draws are left out until it exists;
// - where a graphics pipeline builds at once instead (apipe_ok says no: a target not drawn every frame, whose one drawing would be lost for good), the replay waits for
//   the build, but for all kernels together at most ME_WAIT_NS a present. A small kernel (70 to 210 ms on the Flip) is there in time and drawn; a new scene's large ones
//   arrive over the next seconds instead of stopping the game for all of them, and a target drawn only once loses those, on a cold cache only.
// DM_VK_ASYNC_PIPE=0, or the queue full: compiled at once, as before. → 1 ready, 0 none (failed), -1 being built
#define ME_WAIT_NS 500000000ull
static uint64_t g_me_wait_ns, g_me_wait_frame;   // what the present g_me_wait_frame has waited for kernels' builds
static pthread_mutex_t g_me_mu = PTHREAD_MUTEX_INITIALIZER; static pthread_cond_t g_me_cv = PTHREAD_COND_INITIALIZER;   // a background build's result (memu_t bgdone, bgp, bgns)
static VkResult memu_cpipe_make(vshader *s, VkPipeline *out, uint64_t *ons) {   // with or without the replay's lock: the layout is made, the module is the shader's lmod
    memu_t *m = s->memu;
    VkComputePipelineCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .layout = m->pl,
        .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .pName = "main"}};   // its module: lm_pipeline
    const char *pbk[4] = {s->key, NULL, NULL, NULL}; int pb = pb_begin('c', pbk, 0, 0, 0, 0); uint64_t t0 = clock_gettime_nsec_np(CLOCK_MONOTONIC);
    VkResult r = lm_pipeline(NULL, &pc, &pc.stage, &s->mod, 1, out); pb_end(pb);
    uint64_t ns = clock_gettime_nsec_np(CLOCK_MONOTONIC) - t0; atomic_fetch_add(&g_me_kpipe_ns, ns); *ons = ns;
    if (r != VK_SUCCESS) { *out = VK_NULL_HANDLE; static _Atomic int n; if (atomic_fetch_add(&n, 1) < 8) LOG("[RED] [vk] compute form of task / mesh shader %s: pipeline failed (VkResult %d): its draws are skipped", s->key, r);
                             vk_start_pipe_failed(s->key, NULL); }   // the start record's count, as a compute pipeline's (vk_start.c): a kernel is made once, so it counts once
    else { static _Atomic int n; int k = atomic_fetch_add(&n, 1); if (k < 4 || ns > 500000000ull) LOG("[vk] compute form of task / mesh shader %s: pipeline made in %.1f ms", s->key, ns / 1e6); }
    return r;
}
static int memu_cpipe_cached(vshader *s, VkPipeline *out) {   // the pipeline from the driver's cache by the module's identifier, without a compile
    lmod *l = s->mod; memu_t *m = s->memu; if (!g_smid || !l->idn || atomic_load(&l->m)) return 0;
    VkPipelineShaderStageModuleIdentifierCreateInfoEXT sid = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_MODULE_IDENTIFIER_CREATE_INFO_EXT, .identifierSize = l->idn, .pIdentifier = l->id};
    VkComputePipelineCreateInfo pc = {.sType = VK_STRUCTURE_TYPE_COMPUTE_PIPELINE_CREATE_INFO, .flags = VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT_EXT, .layout = m->pl,
        .stage = {.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO, .pNext = &sid, .stage = VK_SHADER_STAGE_COMPUTE_BIT, .pName = "main"}};
    if (vkCreateComputePipelines(g_vk.dev, pcache(), 1, &pc, NULL, out) == VK_SUCCESS) return 1;
    *out = VK_NULL_HANDLE; return 0;
}
static void memu_cpipe_done(vshader *s, VkPipeline p, uint64_t ns) {   // under g_bk
    memu_t *m = s->memu; m->queued = 0;
    if (p) { m->p = p; g_me_kpipes++; pcache_made_n(ns > 250000000ull ? PC_EVERY : 1); } else m->bad = 1;   // (a long compile asks for the driver's cache file to be written: pcache_made_n)
}
static void memu_cpipe_bg(vshader *s) {   // an apipe thread (gfx_vk_draw.inc apipe_thread). Its result is handed over under g_me_mu, not the replay's lock, which the replay holds while it waits
    VkPipeline p = VK_NULL_HANDLE; uint64_t ns = 0; memu_cpipe_make(s, &p, &ns); memu_t *m = s->memu;
    pthread_mutex_lock(&g_me_mu); m->bgp = p; m->bgns = ns; m->bgdone = 1; pthread_cond_broadcast(&g_me_cv); pthread_mutex_unlock(&g_me_mu);
}
static int memu_cpipe_take(vshader *s) {   // under g_bk: the background build's result, when it is there → 1 ready, 0 failed, -1 still being built
    memu_t *m = s->memu;
    pthread_mutex_lock(&g_me_mu); int done = m->bgdone; VkPipeline p = m->bgp; uint64_t ns = m->bgns; pthread_mutex_unlock(&g_me_mu);
    if (!done) return -1;
    memu_cpipe_done(s, p, ns); g_me_kbg++; return m->p ? 1 : 0;
}
static int memu_cpipe(vshader *s) {   // under g_bk; never waits
    memu_t *m = s->memu; if (m->p) return 1; if (m->bad) return 0; if (m->queued) return memu_cpipe_take(s);
    if (!m->pl) {
        VkDescriptorSetLayout sl[SPV_NOPTR_SET + 1] = {s->dsl, g_me_kset.dsl, g_empty_dsl, g_empty_dsl, s->pool ? g_pool_dsl : g_empty_dsl, g_empty_dsl}; uint32_t nsl = s->pool ? POOL_SET + 1 : 2;
        if (s->gm && g_gm_np && !gm_np_layout(sl, &nsl, g_empty_dsl)) { m->bad = 1; return 0; }   // raw memory through the pools' descriptor array, as cpipe_make (gfx_vk_gmem_noptr.inc)
        VkPushConstantRange pr = {VK_SHADER_STAGE_COMPUTE_BIT, 0, ME_PC};
        VkPipelineLayoutCreateInfo lc = {.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO, .setLayoutCount = nsl, .pSetLayouts = sl, .pushConstantRangeCount = 1, .pPushConstantRanges = &pr};
        if (vkCreatePipelineLayout(g_vk.dev, &lc, NULL, &m->pl) != VK_SUCCESS) { m->pl = VK_NULL_HANDLE; m->bad = 1; return 0; }
    }
    { VkPipeline p = VK_NULL_HANDLE; if (memu_cpipe_cached(s, &p)) { memu_cpipe_done(s, p, 0); g_me_kcached++; return 1; } }
    if (apipe_any()) { m->queued = 1; if (apipe_queue(NULL, NULL, s)) return -1; m->queued = 0; }   // (a full queue: built now)
    VkPipeline p = VK_NULL_HANDLE; uint64_t ns = 0; memu_cpipe_make(s, &p, &ns); memu_cpipe_done(s, p, ns);
    return m->p ? 1 : 0;
}
static int memu_cpipe_wait(vshader *s) {   // under g_bk: waits for a kernel's background build while the present has some of ME_WAIT_NS left → as memu_cpipe_take
    memu_t *m = s->memu; uint64_t fr = atomic_load(&g_presents); if (fr != g_me_wait_frame) { g_me_wait_frame = fr; g_me_wait_ns = 0; }
    if (g_me_wait_ns < ME_WAIT_NS) {
        uint64_t left = ME_WAIT_NS - g_me_wait_ns, t0 = clock_gettime_nsec_np(CLOCK_MONOTONIC);
        struct timespec ts; clock_gettime(CLOCK_REALTIME, &ts);   // (pthread_cond_timedwait's clock)
        ts.tv_nsec += (long)(left % 1000000000ull); ts.tv_sec += (time_t)(left / 1000000000ull); if (ts.tv_nsec >= 1000000000L) { ts.tv_nsec -= 1000000000L; ts.tv_sec++; }
        pthread_mutex_lock(&g_me_mu); while (!m->bgdone && !pthread_cond_timedwait(&g_me_cv, &g_me_mu, &ts)) {} pthread_mutex_unlock(&g_me_mu);
        g_me_wait_ns += clock_gettime_nsec_np(CLOCK_MONOTONIC) - t0;
    }
    return memu_cpipe_take(s);
}
static VkDescriptorSet memu_set(vshader *l, uint32_t n, uint32_t base, const VkDeviceSize *off, const VkDeviceSize *len) {   // a set of l's layout over n arena ranges at bindings base on, from the current chunk
    VkDescriptorSet set = ds_get(l, 0); if (!set) return VK_NULL_HANDLE;
    VkDescriptorBufferInfo bi[4]; VkWriteDescriptorSet w[4];
    for (uint32_t i = 0; i < n; i++) { bi[i] = (VkDescriptorBufferInfo){g_me.b, off[i], len[i]};
        w[i] = (VkWriteDescriptorSet){.sType = VK_STRUCTURE_TYPE_WRITE_DESCRIPTOR_SET, .dstSet = set, .dstBinding = base + i, .descriptorCount = 1, .descriptorType = VK_DESCRIPTOR_TYPE_STORAGE_BUFFER, .pBufferInfo = &bi[i]}; }
    vkUpdateDescriptorSets(g_vk.dev, n, w, 0, NULL); return set;
}
// DM_VK_MESH_STAT=1 (env.txt; a diagnostic): each task draw's launch list header (meshlaunch.comp: its mesh workgroups, and the launches there were when more than the cap)
// copied into a host-visible ring after meshlaunch.comp ran, read with the statistics every 300 presents (memu_stat_print): per task / mesh pair, the draws, their task
// workgroups, the mesh workgroups launched (in all, the most of a draw, the most per task workgroup) and the draws past the cap. The ring holds the last ME_STAT_N task draws
enum { ME_STAT_N = 1024 };
static struct { VkBuffer b; VkDeviceMemory m; uint32_t *p; int bad; } g_me_st;
static struct { const char *tk, *mk; uint32_t n, cap; } g_me_st_rec[ME_STAT_N]; static uint32_t g_me_st_i;
static int memu_stat_on(void) { static int v = -1; if (v < 0) { const char *e = getenv("DM_VK_MESH_STAT"); v = e && *e == '1'; } return v; }
static int memu_stat_buf(void) {
    if (g_me_st.b || g_me_st.bad) return !g_me_st.bad;
    g_me_st.bad = 1;
    VkBufferCreateInfo bi = {.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO, .size = ME_STAT_N * 16, .sharingMode = VK_SHARING_MODE_EXCLUSIVE, .usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT};
    if (vkCreateBuffer(g_vk.dev, &bi, NULL, &g_me_st.b) != VK_SUCCESS) { g_me_st.b = VK_NULL_HANDLE; return 0; }
    VkMemoryRequirements rq; vkGetBufferMemoryRequirements(g_vk.dev, g_me_st.b, &rq);
    VkMemoryAllocateInfo ai = {.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO, .allocationSize = rq.size, .memoryTypeIndex = vkb_mem_type(rq.memoryTypeBits, VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)};
    void *p = NULL;
    if (ai.memoryTypeIndex == UINT32_MAX || vkAllocateMemory(g_vk.dev, &ai, NULL, &g_me_st.m) != VK_SUCCESS || vkBindBufferMemory(g_vk.dev, g_me_st.b, g_me_st.m, 0) != VK_SUCCESS ||
        vkMapMemory(g_vk.dev, g_me_st.m, 0, VK_WHOLE_SIZE, 0, &p) != VK_SUCCESS) { vkDestroyBuffer(g_vk.dev, g_me_st.b, NULL); g_me_st.b = VK_NULL_HANDLE; return 0; }
    g_me_st.p = p; memset(p, 0, ME_STAT_N * 16); g_me_st.bad = 0;
    LOG("[vk] DM_VK_MESH_STAT=1: each task draw's launch count is read back (memu_stat_print)");
    return 1;
}
static void memu_stat_copy(VkCommandBuffer c, VkDeviceSize launch, const vshader *ts, const vshader *ms, uint32_t n, uint32_t cap) {   // after meshlaunch.comp and the barrier behind it
    if (!memu_stat_on() || !memu_stat_buf()) return;
    uint32_t i = g_me_st_i++ % ME_STAT_N; g_me_st_rec[i].tk = ts->key; g_me_st_rec[i].mk = ms->key; g_me_st_rec[i].n = n; g_me_st_rec[i].cap = cap;
    VkBufferCopy cp[2] = {{launch, (VkDeviceSize)i * 16, 4}, {launch + 36, (VkDeviceSize)i * 16 + 4, 4}};   // words 0 (the mesh dispatch's count) and 9 (the launches when past the cap)
    vkCmdCopyBuffer(c, g_me.b, g_me_st.b, 2, cp);
}
static void memu_stat_print(void) {   // the statistics line (mtl_mem_stat): the ring's task draws by task / mesh pair, the most launched first
    if (!memu_stat_on() || !g_me_st.p || !g_me_st_i) return;
    struct { const char *tk, *mk; uint64_t draws, tasks, launches, most, over; double per; } a[64]; int na = 0;
    uint32_t n = g_me_st_i < ME_STAT_N ? g_me_st_i : ME_STAT_N;
    for (uint32_t i = 0; i < n; i++) { const char *tk = g_me_st_rec[i].tk, *mk = g_me_st_rec[i].mk; uint32_t m = g_me_st.p[i * 4], over = g_me_st.p[i * 4 + 1], launched = over ? over : m; int k = 0;
        while (k < na && !(a[k].tk == tk && a[k].mk == mk)) k++;
        if (k == na) { if (na == 64) continue; memset(&a[na], 0, sizeof a[na]); a[na].tk = tk; a[na].mk = mk; na++; }
        a[k].draws++; a[k].tasks += g_me_st_rec[i].n; a[k].launches += launched; if (launched > a[k].most) a[k].most = launched; if (over) a[k].over++;
        double per = g_me_st_rec[i].n ? (double)launched / g_me_st_rec[i].n : 0; if (per > a[k].per) a[k].per = per; }
    for (int x = 0; x < na; x++) for (int y = x + 1; y < na; y++) if (a[y].launches > a[x].launches) { __typeof__(a[0]) t = a[x]; a[x] = a[y]; a[y] = t; }
    LOG("[vk] task draws in compute form, the last %u (DM_VK_MESH_STAT): task / mesh pairs %d; per pair: draws, task workgroups, mesh workgroups launched (most of a draw, most per task workgroup), draws past the cap %u", n, na, la_cap());
    for (int k = 0; k < na && k < 16; k++) LOG("[vk]   %s / %s: %llu draws, %llu tasks, %llu launched (most %llu, %.1f per task), %llu past the cap", a[k].tk, a[k].mk, (unsigned long long)a[k].draws, (unsigned long long)a[k].tasks,
                                                 (unsigned long long)a[k].launches, (unsigned long long)a[k].most, a[k].per, (unsigned long long)a[k].over);
}
// one dispatch of a task or mesh kernel over the arena ranges r[4] (taskout, launch, vtx, idx): groups workgroups, or (0) the launch list header's counts at ind, at most
// `most`. A kernel whose shared memory is past the GPU's limit has it in a storage buffer (spv_tgspill, s->tgs), a region a workgroup, which stage_set sizes by g_cdim
// and takes from the compute form's arena at spill (g_tgs_b): scratch for this dispatch alone, where the chunk's arena would keep it for every dispatch of the chunk.
// la: ahead of the pass (cb_pre; dep: it reads the kernel before's outputs, so a barrier first, else one only after a command of another kind); 0: as before, in the
// chunk's commands behind a full barrier on both sides
static int memu_kernel(vshader *s, const prog_t *pr, int pst, const VkDeviceSize r[8], uint32_t first, uint32_t groups, VkDeviceSize ind, uint32_t most, VkDeviceSize spill, int la, int dep) {
    VkDescriptorSet set, es; uint32_t dyn[18]; int ok;
    g_cdim[0] = groups ? groups : most; g_cdim[1] = g_cdim[2] = 1;
    g_tgs_b = s->tgs ? g_me.b : VK_NULL_HANDLE; g_tgs_off = spill;
    for (int t = 0;; t++) {   // as vk_dispatch: the set taken again when a sync inside stage_set closed the chunk it came from
        g_bind_bad = 0; if (!cur()) return 0; uint64_t dseq = C->seq; int got = stage_set(s, 0, &set, dyn, pr, pst, 0, dseq); ok = got && !g_bind_bad;
        if (got || !ds_moved(dseq)) break;
        if (ds_again(t, 2)) return 0;
    }
    g_tgs_b = VK_NULL_HANDLE;
    if (!ok || !(es = memu_set(&g_me_kset, 4, ME_KBIND, r, r + 4))) return 0;
    VkCommandBuffer c = la ? cb_pre() : cb(); if (!c) return 0;
    if (la) { if (dep || g_me_wrote || !memu_chained()) cb_barrier_to(c); } else cb_barrier();
    memu_t *m = s->memu; uint32_t pc[2] = {first, 0};
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->p);
    vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->pl, 0, 1, &set, s->ndyn, dyn);
    vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->pl, 1, 1, &es, 0, NULL);
    if (s->pool && !pool_bind(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->pl)) return 0;
    if (s->gm && g_gm_np) gm_np_bind(c, VK_PIPELINE_BIND_POINT_COMPUTE, m->pl);   // raw memory's pools as a descriptor array (gfx_vk_gmem_noptr.inc)
    vkCmdPushConstants(c, m->pl, VK_SHADER_STAGE_COMPUTE_BIT, 0, ME_PC, pc);
    // a profiled frame's record and the breadcrumbs, as vk_dispatch's: the kernel by its key, x its workgroups (an indirect dispatch: the most it runs, z 0)
    uint32_t g[3] = {groups ? groups : most, 1, groups ? 1 : 0}; int pr_i = -1;
    if (prof_on() && C->pq && C->npq + 2 <= 512 && g_nprof < 1024) { prof_rec *q = &g_prof[pr_i = g_nprof++]; memset(q, 0, sizeof *q); q->c = C; q->ncolor = -1; q->w = g[0]; q->h = g[1]; q->draws = (int)g[2]; q->seq = g_prof_seq++; q->bigfs = s->key;
        q->s0 = C->npq++; vkCmdWriteTimestamp(c, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, C->pq, (uint32_t)q->s0); }
    uint32_t bcid = bc_on() ? bc_begin(c, s->key, g, C->seq) : 0;   // DM_VK_BC (gfx_vk_bc.inc)
    if (groups) vkCmdDispatch(c, groups, 1, 1); else vkCmdDispatchIndirect(c, g_me.b, ind);
    crumb(groups ? 'c' : 'C', s->key, NULL, groups ? groups : most, 1);
    bc_end(c, bcid);
    if (pr_i >= 0) { g_prof[pr_i].s1 = C->npq++; vkCmdWriteTimestamp(c, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT, C->pq, (uint32_t)g_prof[pr_i].s1); }
    if (la) { memu_chain(); if (s->gm) g_me_wrote = 1; else for (int i = 0; i < s->nsb; i++) if (s->sb[i].flags & 1) g_me_wrote = 1; if (s->nim) g_me_wrote = 1; } else cb_barrier();
    g_dispatches++; C->ndraw++;
    return 1;
}
static int memu_launch(const VkDeviceSize r[8], uint32_t ntask, const memu_t *ts, const memu_t *ms, uint32_t cap, int la) {   // meshlaunch.comp over taskout and launch (it reads the task kernel's payloads: a barrier first)
    if (!cur()) return 0;
    VkDescriptorSet set = memu_set(&g_me_lset, 2, 0, r, r + 4); VkCommandBuffer c = la ? cb_pre() : cb(); if (!set || !c) return 0;
    if (la) cb_barrier_to(c);
    uint32_t pc[4] = {ntask, (uint32_t)ts->pay, cap, (uint32_t)ms->ipw};
    vkCmdBindPipeline(c, VK_PIPELINE_BIND_POINT_COMPUTE, g_me_launch); vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_COMPUTE, g_me_lpl, 0, 1, &set, 0, NULL);
    vkCmdPushConstants(c, g_me_lpl, VK_SHADER_STAGE_COMPUTE_BIT, 0, 16, pc); vkCmdDispatch(c, 1, 1, 1);
    if (la) memu_chain(); else cb_barrier();
    g_dispatches++;
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
    if (!(vset = memu_set(m->pvs, 1, 0, r + 2, r + 6))) { g_drop[3]++; return 0; }
    if (!rp_start()) { g_drop[5]++; return 0; }
    VkCommandBuffer c = C->cb;
    occl_begin();
    bf_pipeline(c, pp->p);
    if (pp->alpha) vkCmdPushConstants(c, pp->pl, VK_SHADER_STAGE_FRAGMENT_BIT, 0, sizeof D.alpha_ref, &D.alpha_ref);   // the alpha test's reference, as vk_draw_
    vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pp->pl, 0, 1, &vset, 0, NULL);
    if (fs) vkCmdBindDescriptorSets(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pp->pl, (uint32_t)(fs->set & 3), 1, &fset, fs->ndyn, dyn);
    if (fs && fs->pool && !pool_bind(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pp->pl)) { g_drop[3]++; return 0; }
    if (fs && fs->gm && g_gm_np) gm_np_bind(c, VK_PIPELINE_BIND_POINT_GRAPHICS, pp->pl);   // (gfx_vk_gmem_noptr.inc)
    VkViewport v; VkRect2D sc; draw_dyn_state(c, &v, &sc, 0); (void)v; (void)sc;
    bf_ibuf(c, g_me.b, r[3], VK_INDEX_TYPE_UINT32);
    if (nidx) vkCmdDrawIndexed(c, nidx, 1, 0, 0, 0); else vkCmdDrawIndexedIndirect(c, g_me.b, r[1] + 16, 1, 20);
    crumb(nidx ? 'd' : 'D', m->pvs->key, fs ? fs->key : NULL, nidx, 1);   // (named by the pass-through vertex shader's key: the mesh shader's with its digits moved to g..v)
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
    if (!memu_arena() || !memu_kernels()) { g_drop[2]++; g_me_skipped++; return 0; }
    g_me_seen = 1;
    { vshader *vw[4] = {ms, fs, ts, NULL};   // what the stages read of guest memory: pending GPU writes to it land first; and whether a draw of the open pass wrote it in place (pass_wb_check, fwd_hit)
      g_dv_pass_chk = 1; g_dv_pass_hit = 0; draw_view(vw, NULL, 0); g_dv_pass_chk = 0;
      for (int i = 0; i < 3; i++) if (vw[i]) stage_textures(vw[i]);
      if (ms->pool || (fs && fs->pool) || (ts && ts->pool)) pool_sync(); }
    {   // the kernels' pipelines (memu_cpipe): from the driver's cache, else built in the background and the draw left out meanwhile; on a target a graphics pipeline would
        // build at once for (apipe_ok, on the draw's pass), waited for within the present's budget
        if (!rp_prepare_(0)) { g_drop[1]++; g_me_skipped++; return 0; }
        pipe_key ak; memset(&ak, 0, sizeof ak); int bg = apipe_ok(&ak);
        int km = memu_cpipe(ms), kt = ts ? memu_cpipe(ts) : 1;   // (both asked for first, so both build at once)
        if (!bg) { if (km < 0) km = memu_cpipe_wait(ms); if (kt < 0) kt = memu_cpipe_wait(ts); }
        if (!km || !kt) { g_drop[2]++; g_me_skipped++; return 0; }
        if (km < 0 || kt < 0) { g_me_left++; return 1; }
    }
    static uint32_t cap_max; if (!cap_max) { const char *e = getenv("DM_VK_MESH_MAX"); cap_max = e && atoi(e) > 0 ? (uint32_t)atoi(e) : 4096; }
    VkDeviceSize per = me_up((VkDeviceSize)m->nrec * m->nout * 16) + me_up((VkDeviceSize)m->ipw * 4) + ms->tgs;   // a mesh workgroup's records and indices, and its shared memory when that is in a storage buffer (memu_kernel)
    VkDeviceSize usable = g_me.size - 10 * ME_ALIGN, half = usable / 2;   // (the ranges' alignment)
    uint64_t room = (ts ? half : usable) / per; uint32_t cap = room < cap_max ? (uint32_t)room : cap_max; if (cap > 65535) cap = 65535;
    if (!cap) { RED_ONCE(183, "mesh shader %s: one workgroup's outputs exceed the arena (DM_VK_MESH_ARENA_MB): draw skipped", ms->key); g_me_skipped++; return 0; }
    // the arena's ranges, offsets then lengths: taskout, launch, vtx, idx
    VkDeviceSize r[8]; r[4] = ts ? 0 : ME_ALIGN; r[5] = ts ? me_up(((VkDeviceSize)ME_HDR + 2ull * cap) * 4) : ME_ALIGN;
    r[6] = (VkDeviceSize)cap * m->nrec * m->nout * 16; r[7] = (VkDeviceSize)cap * m->ipw * 4;
    uint32_t tmax = 0;
    if (ts) { VkDeviceSize left = half > r[5] ? half - r[5] : 0; uint64_t t = left / ((VkDeviceSize)ts->memu->pay * 4); tmax = t > 65535 ? 65535 : (uint32_t)t;
        if (!tmax) { RED_ONCE(183, "task shader %s: its payloads exceed the arena (DM_VK_MESH_ARENA_MB): draw skipped", ts->key); g_me_skipped++; return 0; }
        if (ts->tgs && half / ts->tgs < tmax) tmax = (uint32_t)(half / ts->tgs);   // its shared memory in a storage buffer: where the mesh kernel's outputs go afterwards
        if (!tmax) { RED_ONCE(183, "task shader %s: one workgroup's shared memory exceeds the arena (DM_VK_MESH_ARENA_MB): draw skipped", ts->key); g_me_skipped++; return 0; } }
    uint32_t first = (uint32_t)dw->first, left = (uint32_t)dw->count;
    int la = la_on() && (!P.active || P.sec);   // (a pass in the chunk's current command buffer, for lack of a free one: as before)
    if (la && (ts ? left <= tmax : left <= cap)) {   // one part: its kernels ahead of the open pass (or before the one its draw opens), the draw inside it (the comment above)
        if (P.active && P.sec && g_dv_pass_hit) {   // its kernels read what a draw of the open pass wrote in place: the pass ends first, as before
            if (g_me_la_breaks[0]++ < 4) LOG("[vk] task / mesh draw in compute form (task %s mesh %s): its kernels read a draw's in-place write of the open pass, which ends first (%d draws in it)", ts ? ts->key : "-", ms->key, C ? C->ndraw : -1);
            rp_end(); tc_clear(); }
        uint32_t n = left, capv = ts ? (la_cap() < cap ? la_cap() : cap) : n;   // the mesh workgroups the ranges hold: a draw without a task has its count, one with reserves the cap
        VkDeviceSize q[8], tsp = ts && ts->tgs ? me_up((VkDeviceSize)n * ts->tgs) : 0, msp = ms->tgs ? me_up((VkDeviceSize)capv * ms->tgs) : 0;
        q[4] = ts ? me_up((VkDeviceSize)n * ts->memu->pay * 4) : ME_ALIGN; q[5] = ts ? me_up(((VkDeviceSize)ME_HDR + 2ull * capv) * 4) : ME_ALIGN;
        q[6] = me_up((VkDeviceSize)capv * m->nrec * m->nout * 16); q[7] = me_up((VkDeviceSize)capv * m->ipw * 4);
        VkDeviceSize need = q[4] + q[5] + q[6] + q[7] + tsp + msp;
        if (g_me_cur + need > g_me.size) {   // no room left: the pass ends first (its draws read the arena; the kernels after it are behind a barrier), and the arena is free again
            if (P.active) { rp_end(); tc_clear(); g_me_la_breaks[1]++; }
            else if (g_me_cur > g_me_keep) { VkCommandBuffer c = cb_pre(); if (c) cb_barrier_to(c); g_me_cur = g_me_keep; } }   // (ranges of a draw that was not made, or of a pass that ended: free behind a barrier)
        if (g_me_cur + need <= g_me.size) {
            q[0] = g_me_cur; q[1] = q[0] + q[4]; q[2] = q[1] + q[5]; q[3] = q[2] + q[6]; VkDeviceSize at_t = q[3] + q[7], at_m = at_t + tsp; g_me_cur = g_me_keep = at_m + msp;
            int ok = 1;
            if (ts) {
                ok = memu_kernel(ts, ppr[2], pst[2], q, first, n, 0, n, at_t, 1, 0) && memu_launch(q, n, ts->memu, m, capv, 1);
                if (ok && memu_stat_on()) { VkCommandBuffer c = cb_pre(); if (c) { cb_barrier_to(c); memu_stat_copy(c, q[1], ts, ms, n, capv); } }
                ok = ok && memu_kernel(ms, ppr[0], pst[0], q, 0, 0, q[1], capv, at_m, 1, 1);
            } else ok = memu_kernel(ms, ppr[0], pst[0], q, first, n, 0, n, at_m, 1, 0);
            ok = ok && memu_draw(m, fs, ppr[1], pst[1], q, ts ? 0 : n * (uint32_t)m->ipw);
            g_me_keep = 0;   // (its draw is recorded, in the pass that will read its ranges; or it was not made)
            if (!ok) { g_me_skipped++; return 0; }
            g_me_parts++; g_me_draws++; g_me_la_draws++;
            if (g_me_draws == 1) LOG("[vk] task / mesh draws in compute form: first draw, task %s mesh %s fragment %s, %d workgroups from %d (a part's most mesh workgroups %u), its kernels ahead of the pass",
                                     ts ? ts->key : "-", ms->key, fs ? fs->key : "-", dw->count, dw->first, capv);
            if (dump_on()) LOG("[dump] pass %d draw %llu: task %s mesh %s fs %s in compute form, %d workgroups from %d, kernels ahead of the pass", g_dump_pass + 1, (unsigned long long)g_draws,
                               ts ? ts->key : "-", ms->key, fs ? fs->key : "-", dw->count, dw->first);
            return 1;
        }
    } else if (la) g_me_la_breaks[2]++;
    g_me_la_cut++;
    while (left) {   // as before: the pass cut, the kernels from the arena's start behind full barriers, the draw in a pass begun again
        uint32_t n = ts ? (left < tmax ? left : tmax) : (left < cap ? left : cap);
        if (ts) r[4] = me_up((VkDeviceSize)n * ts->memu->pay * 4);
        r[0] = 0; r[1] = me_up(r[0] + r[4]); r[2] = me_up(r[1] + r[5]); r[3] = me_up(r[2] + r[6]);
        VkDeviceSize sp = me_up(r[3] + r[7]);   // the mesh kernel's shared memory, when it is in a storage buffer; the task kernel's lies where vtx will be
        rp_end(); tc_clear(); g_me_cur = g_me_keep = 0;
        if (ts) {
            if (!memu_kernel(ts, ppr[2], pst[2], r, first, n, 0, n, r[2], 0, 0) || !memu_launch(r, n, ts->memu, m, cap, 0) || !memu_kernel(ms, ppr[0], pst[0], r, 0, 0, r[1], cap, sp, 0, 0)) { g_me_skipped++; return 0; }
        } else if (!memu_kernel(ms, ppr[0], pst[0], r, first, n, 0, n, sp, 0, 0)) { g_me_skipped++; return 0; }
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
