// ---------------- Shader modules made when a pipeline needs them (VK_EXT_shader_module_identifier) ----------------
// Samsung's Xclipse 950 driver does a compile's work in vkCreateShaderModule: 0.8-0.9 ms a module against about 0.1 on the Adreno 830, and its pipeline cache does
// not keep that work. Brilliant Diamond's 8,844 modules took 6-10 s of every start on a Galaxy Z Flip 7 (its first frame at 10-12 s, 3-4 on the Pad 3), while its
// 2,982 pipelines came out of the cache in 0.2-0.4 s. With VK_EXT_shader_module_identifier (and pipeline creation cache control) a module is only its identifier,
// a hash of its code (0.005 ms there), until a pipeline needs it: a pipeline is asked for from the identifiers first, with
// VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT, which the driver's cache serves (2 ms) or answers VK_PIPELINE_COMPILE_REQUIRED (0.02 ms). Only then are
// its modules made, from the files again through the same rewrites, and the pipeline compiled as before. The SPIR-V is not kept meanwhile (Brilliant Diamond's
// modules are about 28 KB each). With DM_VK_MODULE_ID=0 (env.txt), every module is made at once, as before.
// Without the extension (the Pixel 9 Pro XL's Mali-G715), a module made at once is kept for good, and the driver keeps its own copy of the code on its malloc heap:
// Brilliant Diamond makes 8,974 modules by its first frame, and the Pixel's native heap held 706 MB in Eterna City (Android 17's per-app memory limiter counts it
// against 8 GiB). There (g_lm_lazy) a module is only its path until a pipeline is built: the pipeline's modules are made for that
// build, from the files through the same rewrites, and destroyed once the pipeline exists, which Vulkan allows. A start-up list or a game's shader warm-up builds
// many pipelines in a row over a few shared vertex shaders, so the last modules made are kept for the next builds that name them (lk_take): DM_VK_MODULE_LAZY=N
// keeps N idle ones (64 by default; 1 nearly none). DM_VK_MODULE_LAZY=0: every module made at once and kept
typedef struct lmod { _Atomic(VkShaderModule) m; uint32_t miss, idn; int alpha; uint64_t e5; const spv_bmap *bm; uint8_t id[VK_MAX_SHADER_MODULE_IDENTIFIER_SIZE_EXT]; char path[]; } lmod;   // miss: ps_variant's (0: the file as it is); alpha: spv_alpha.h's test added to the code
static _Atomic uint64_t g_lm_ids, g_lm_hit, g_lm_miss, g_lm_tmp, g_lm_reuse;   // modules known by their identifier; pipelines the driver's cache gave for identifiers; pipelines that needed modules after all; g_lm_lazy's modules made for builds, and kept ones a build used again
static __thread int t_pool_info;   // what spv_pool did to the modules lm_code made since sh_get cleared it
// The module's code as it is made (to free): the file; a fragment shader variant's unwritten inputs made constants (spv_drop_inputs), else the vertex pipeline's
// storage made read-only where the GPU needs it (spv_readonly); then the pool set (spv_pool_fit), the subgroup rewrites (spv_fit) and, last, the set's binding numbers compacted (spv_bind.h). first: the module's first
// making, which tells *b0, logs and dumps (made again for a pipeline, it says nothing new)
static uint32_t *lm_code(const char *path, uint32_t miss, int alpha, uint64_t e5, const spv_bmap *bm, int first, int *b0, size_t *onw) {
    size_t n = 0; uint32_t *code = spv_read(path, &n); if (!code) return NULL;
    if (e5) {   // a compute variant whose storage images at these bindings are E5B9G9R9 textures bound through R32_UINT views (spv_e5.h): RGB9E5 packed and unpacked by the shader
        uint32_t *s = malloc(5 * (size_t)code[3] * 4), *o = NULL; size_t need = 0, k = 0; int what = 0;
        if (s) { spv_e5(code, n, e5, s, NULL, 0, &need, &what); if (need && (o = malloc(need * 4))) k = spv_e5(code, n, e5, s, o, need, &need, &what); }
        free(s); free(code);
        if (!k) { free(o); if (first) LOG("[RED] [vk] %s: its storage image at binding mask %#llx is an E5B9G9R9 texture, and spv_e5 cannot rewrite the shader for it (%s): its dispatches are skipped", path, (unsigned long long)e5, what == SPV_E5_KEPT ? "another use of the image" : "no such image"); return NULL; }
        code = o; n = k;
        if (first) LOG("[vk] %s: its storage images at binding mask %#llx are E5B9G9R9 textures: stored through R32_UINT views, RGB9E5 packed by the shader (spv_e5)", path, (unsigned long long)e5);
    }
    if (miss) {
        size_t on = 0; uint32_t *v = spv_drop_inputs(code, n, miss, &on); free(code); if (!v) return NULL; code = v; n = on;
        const char *d = getenv("DM_DUMP_DIR");   // for spirv-val
        if (first && d) { char q[700]; mkdir(d, 0777); const char *b = strrchr(path, '/'); snprintf(q, sizeof q, "%s/var_%.16s_%x.spv", d, b ? b + 1 : path, miss); FILE *f = fopen(q, "wb"); if (f) { fwrite(code, 4, n, f); fclose(f); } }
    } else {
        if (b0) *b0 |= spv_b0_used(code, n);
        if (!g_vk_feat.vertexPipelineStoresAndAtomics) {   // the Mali-G76: the vertex pipeline's storage resources must be NonWritable (spv_readonly.h)
            size_t cap = n + 3 * (size_t)code[3], on = 0; int wr = 0;
            uint32_t *s = malloc(2 * (size_t)code[3] * 4), *o = malloc(cap * 4);
            if (s && o && (on = spv_readonly(code, n, s, o, cap, &wr))) { free(code); code = o; n = on; o = NULL; }
            if (wr && first) LOG("[RED] [vk] %s writes %d storage resource(s) from the vertex pipeline: the GPU has no vertexPipelineStoresAndAtomics, the driver may refuse it", path, wr);
            free(s); free(o);
        }
    }
    uint32_t *pf = NULL; size_t pn = spv_pool_fit(code, n, path, &pf); if (pn) { free(code); code = pf; n = pn; }   // the texture pool by ID moved into the pool set
    uint32_t *fit = NULL; size_t fn = spv_fit(code, n, path, &fit); if (fn) { free(code); code = fit; n = fn; }
    uint32_t *ly = NULL; size_t ln = spv_fit_layer(code, n, path, &ly); if (ln) { free(code); code = ly; n = ln; }
    uint32_t *ts = NULL; size_t tn = spv_fit_tgs(code, n, path, &ts); if (tn) { free(code); code = ts; n = tn; }   // shared memory past the GPU's limit (spv_tgspill)
    uint32_t *pr = NULL; size_t prn = spv_fit_precise(code, n, path, &pr); if (prn) { free(code); code = pr; n = prn; }   // FMUL and FADD unfused where vertices are placed
    if (alpha) {   // NVN's alpha test, run in a wrapper entry point (spv_alpha.h); a shader it does not apply to is no module
        size_t cap = n + 256; uint32_t *o = malloc(cap * 4), fn_id = 0;
        size_t on = o ? spv_alpha(code, n, o, cap, &fn_id) : 0;
        free(code);
        if (!on) { free(o); if (first) LOG("[RED] [vk] fragment shader %s: an alpha test is set, but the shader has no float vec4 colour 0 to test (an integer target or no such output): the draw keeps the shader as it is", path); return NULL; }
        code = o; n = on;
    }
    if (bm) spv_bind_remap(code, n, bm);   // last, so every rewrite above saw the numbers the file has (spv_bind.h; sh_get gave the layout the same map)
    *onw = n; return code;
}
static VkShaderModule lm_create(const uint32_t *code, size_t nw, const char *what) {
    VkShaderModule m = VK_NULL_HANDLE; VkShaderModuleCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = nw * 4, .pCode = code};
    uint64_t t0 = clock_gettime_nsec_np(CLOCK_MONOTONIC);
    if (vkCreateShaderModule(g_vk.dev, &ci, NULL, &m) != VK_SUCCESS) { LOG("[RED] [vk] shader module %s refused by the driver", what); m = VK_NULL_HANDLE; }
    atomic_fetch_add(&g_mod_ns, clock_gettime_nsec_np(CLOCK_MONOTONIC) - t0); atomic_fetch_add(&g_mod_made, 1);
    return m;
}
// The module of a .spv file (and a fragment shader's variant): its identifier where the GPU takes identifiers, its path alone with g_lm_lazy, else made now. NULL: no
// file, or the driver refused it (with identifiers or g_lm_lazy, a refusal shows when a pipeline is built)
static lmod *lm_new_e(const char *path, uint32_t miss, int alpha, uint64_t e5, const spv_bmap *bm, int *b0) {
    size_t n = 0; uint32_t *code = lm_code(path, miss, alpha, e5, bm, 1, b0, &n); if (!code) return NULL;
    size_t pl = strlen(path) + 1; lmod *l = calloc(1, sizeof *l + pl); if (!l) { free(code); return NULL; }
    memcpy(l->path, path, pl); l->miss = miss; l->alpha = alpha; l->e5 = e5; l->bm = bm;
    if (g_smid) {
        VkShaderModuleCreateInfo ci = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO, .codeSize = n * 4, .pCode = code};
        VkShaderModuleIdentifierEXT id = {.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_IDENTIFIER_EXT};
        g_smid(g_vk.dev, &ci, &id);
        l->idn = id.identifierSize < sizeof l->id ? id.identifierSize : (uint32_t)sizeof l->id; memcpy(l->id, id.identifier, l->idn);
        if (l->idn) atomic_fetch_add(&g_lm_ids, 1);
    }
    if (!l->idn && !g_lm_lazy) { VkShaderModule m = lm_create(code, n, path); if (!m) { free(code); free(l); return NULL; } atomic_store(&l->m, m); }
    free(code); return l;
}
static lmod *lm_new_a(const char *path, uint32_t miss, int alpha, const spv_bmap *bm, int *b0) { return lm_new_e(path, miss, alpha, 0, bm, b0); }
static lmod *lm_new(const char *path, uint32_t miss, const spv_bmap *bm, int *b0) { return lm_new_a(path, miss, 0, bm, b0); }
static VkShaderModule lm_make(const lmod *l) {   // a new module from its file; VK_NULL_HANDLE: the driver refused it
    size_t n = 0; uint32_t *code = lm_code(l->path, l->miss, l->alpha, l->e5, l->bm, 0, NULL, &n); if (!code) return VK_NULL_HANDLE;
    VkShaderModule made = lm_create(code, n, l->path); free(code); return made;
}
static VkShaderModule lm_module(lmod *l) {   // the module itself, made now when it was its identifier only; VK_NULL_HANDLE: the driver refused it
    VkShaderModule m = atomic_load(&l->m); if (m) return m;
    VkShaderModule made = lm_make(l); if (!made) return VK_NULL_HANDLE;
    VkShaderModule none = VK_NULL_HANDLE;
    if (!atomic_compare_exchange_strong(&l->m, &none, made)) { vkDestroyShaderModule(g_vk.dev, made, NULL); return none; }   // another thread's pipeline made it meanwhile
    return made;
}
// g_lm_lazy's modules: made for a build, kept while any build uses them and then while among the last g_lm_lazy idle ones (the table holds a few dozen, scanned)
typedef struct { const lmod *l; VkShaderModule m; int refs; uint64_t used; } lk_slot;
static pthread_mutex_t g_lk_mu = PTHREAD_MUTEX_INITIALIZER; static lk_slot *g_lk; static int g_nlk, g_clk; static uint64_t g_lk_tick;
static VkShaderModule lk_take(const lmod *l) {   // l's module for a build, kept or made now; lk_give when the build is done. VK_NULL_HANDLE: the driver refused it
    pthread_mutex_lock(&g_lk_mu);
    for (int i = 0; i < g_nlk; i++) if (g_lk[i].l == l) { g_lk[i].refs++; g_lk[i].used = ++g_lk_tick; VkShaderModule m = g_lk[i].m; pthread_mutex_unlock(&g_lk_mu); atomic_fetch_add(&g_lm_reuse, 1); return m; }
    pthread_mutex_unlock(&g_lk_mu);
    VkShaderModule m = lm_make(l); if (!m) return VK_NULL_HANDLE;   // made outside the lock: another thread may make the same one meanwhile, kept twice for a while
    atomic_fetch_add(&g_lm_tmp, 1);
    pthread_mutex_lock(&g_lk_mu);
    if (g_nlk == g_clk) { int c = g_clk ? 2 * g_clk : 64; lk_slot *n = realloc(g_lk, (size_t)c * sizeof *n); if (n) { g_lk = n; g_clk = c; } }
    if (g_nlk < g_clk) g_lk[g_nlk++] = (lk_slot){.l = l, .m = m, .refs = 1, .used = ++g_lk_tick};   // else not kept: lk_give destroys it
    pthread_mutex_unlock(&g_lk_mu);
    return m;
}
static void lk_give(VkShaderModule m) {   // a build is done with m: idle past the last g_lm_lazy, the least recently used idle ones are destroyed
    pthread_mutex_lock(&g_lk_mu);
    int at = -1, idle = 0; for (int i = 0; i < g_nlk; i++) { if (g_lk[i].m == m) at = i; }
    if (at < 0) { pthread_mutex_unlock(&g_lk_mu); vkDestroyShaderModule(g_vk.dev, m, NULL); return; }
    g_lk[at].refs--;
    for (int i = 0; i < g_nlk; i++) idle += !g_lk[i].refs;
    while (idle > g_lm_lazy) {
        int old = -1; for (int i = 0; i < g_nlk; i++) if (!g_lk[i].refs && (old < 0 || g_lk[i].used < g_lk[old].used)) old = i;
        vkDestroyShaderModule(g_vk.dev, g_lk[old].m, NULL); g_lk[old] = g_lk[--g_nlk]; idle--;
    }
    pthread_mutex_unlock(&g_lk_mu);
}
static void lk_clear(void) {   // before the device goes (vkb_fallback): every kept module destroyed
    pthread_mutex_lock(&g_lk_mu);
    for (int i = 0; i < g_nlk; i++) vkDestroyShaderModule(g_vk.dev, g_lk[i].m, NULL);
    g_nlk = 0; pthread_mutex_unlock(&g_lk_mu);
}
// A graphics (gp) or compute (cp) pipeline whose ns stages st name the modules lms: from the identifiers of those not made yet when the driver's cache has the
// pipeline, else with the modules made now; with g_lm_lazy, with modules taken for this build (lk_take) and given back after it. Called with or without the replay's
// lock, as pipe_make and cpipe_get are
static VkResult lm_pipeline(VkGraphicsPipelineCreateInfo *gp, VkComputePipelineCreateInfo *cp, VkPipelineShaderStageCreateInfo *st, lmod *const *lms, uint32_t ns, VkPipeline *out) {
    VkPipelineShaderStageModuleIdentifierCreateInfoEXT sid[5]; VkShaderModule tmp[5] = {0}; int byid = 0; VkResult pr = VK_ERROR_INITIALIZATION_FAILED;
    VkPipelineCreateFlags *fl = gp ? &gp->flags : &cp->flags;
    for (uint32_t i = 0; i < ns && i < 5; i++) {
        if ((st[i].module = atomic_load(&lms[i]->m))) continue;
        if (lms[i]->idn) { sid[i] = (VkPipelineShaderStageModuleIdentifierCreateInfoEXT){.sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_MODULE_IDENTIFIER_CREATE_INFO_EXT,
                                                                                         .identifierSize = lms[i]->idn, .pIdentifier = lms[i]->id};
                           st[i].pNext = &sid[i]; byid = 1; continue; }
        if (!(st[i].module = tmp[i] = lk_take(lms[i]))) goto done;   // g_lm_lazy: a module for this build, kept or made now
    }
    if (byid) {
        *fl |= VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT_EXT;
        pr = gp ? vkCreateGraphicsPipelines(g_vk.dev, pcache(), 1, gp, NULL, out) : vkCreateComputePipelines(g_vk.dev, pcache(), 1, cp, NULL, out);
        *fl &= ~(VkPipelineCreateFlags)VK_PIPELINE_CREATE_FAIL_ON_PIPELINE_COMPILE_REQUIRED_BIT_EXT;
        if (pr == VK_SUCCESS) { atomic_fetch_add(&g_lm_hit, 1); goto done; }
        // VK_PIPELINE_COMPILE_REQUIRED, the cache's answer for a pipeline it does not have (any other answer is taken as that too): the modules, then a compile
        atomic_fetch_add(&g_lm_miss, 1); *out = VK_NULL_HANDLE; pr = VK_ERROR_INITIALIZATION_FAILED;
        for (uint32_t i = 0; i < ns && i < 5; i++) if (!st[i].module) { st[i].pNext = NULL; if (!(st[i].module = lm_module(lms[i]))) goto done; }
    }
    pr = gp ? vkCreateGraphicsPipelines(g_vk.dev, pcache(), 1, gp, NULL, out) : vkCreateComputePipelines(g_vk.dev, pcache(), 1, cp, NULL, out);
done:
    for (uint32_t i = 0; i < ns && i < 5; i++) if (tmp[i]) { lk_give(tmp[i]); st[i].module = VK_NULL_HANDLE; }   // the pipeline needs them no more
    return pr;
}
