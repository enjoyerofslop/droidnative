"""NVN2 task and mesh shaders in compute form, for a GPU without VK_EXT_mesh_shader: dm/android/tools/spv_meshemu.py compute and vertex, on the kernel test_spv_mesh.py
assembles, checked with spirv-val for Vulkan 1.1 (SPIR-V 1.3). Skipped without spirv-as / spirv-val.
With DM_SPV_MESH_DIR=<a folder of the translator's task / mesh outputs and their jobs.json>, every one there is made and checked too."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spv_mesh import KERNEL, SPV_AS, SPV_VAL, mesh_info, sa, ms_   # noqa: E402  # pyright: ignore[reportMissingImports]
import spv_meshemu as me   # noqa: E402  # pyright: ignore[reportMissingImports]
import spv_mesh as sm   # noqa: E402  # pyright: ignore[reportMissingImports]

OP_TYPESTRUCT = 30


def kernel(info):
    lay, size = ms_.memory(info)
    src = KERNEL.replace('%WORDS%', str(size // 4)).replace('%AT%', str(lay[3] >> 2))
    with tempfile.TemporaryDirectory() as d:
        Path(d, 'k.spvasm').write_text(src)
        subprocess.run([SPV_AS, '--target-env', 'vulkan1.1', str(Path(d, 'k.spvasm')), '-o', str(Path(d, 'k.spv'))], check=True)
        return Path(d, 'k.spv').read_bytes(), lay


@unittest.skipUnless(SPV_AS and SPV_VAL, 'spirv-as / spirv-val not found (the NDK shader-tools or PATH)')
class SpvMeshEmu(unittest.TestCase):
    def valid(self, data, env='vulkan1.1'):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, 'm.spv'); p.write_bytes(data)
            r = subprocess.run([SPV_VAL, '--target-env', env, str(p)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return sa.parse(data)[1]

    def computed(self, data, info, lay):
        out, keep = me.compute(data, info, lay)
        hdr, ins = sa.process(out, 'cs', None, keep)[:2]
        ins = self.valid(sa.emit(hdr, ins))
        ent = [x for x in ins if x[0] == sm.OP_ENTRY]
        self.assertEqual(len(ent), 1); self.assertEqual(ent[0][1], sm.MODEL_GLCOMPUTE)
        sets = {x[1]: x[3] for x in ins if x[0] == sm.OP_DECORATE and x[2] == me.DEC_DESCRIPTORSET}
        binds = {x[1]: x[3] for x in ins if x[0] == sm.OP_DECORATE and x[2] == me.DEC_BINDING}
        self.assertEqual(sorted(binds[v] for v in keep), [me.B_TASKOUT, me.B_LAUNCH, me.B_VTX, me.B_IDX])
        self.assertTrue(all(sets[v] == me.MESH_SET for v in keep), 'the emulation\'s buffers stay at MESH_SET')
        self.assertTrue(all(s == 0 for v, s in sets.items() if v not in keep), 'the kernel\'s own bindings go to set 0')
        own = {binds[v] for v in binds if v not in keep}
        self.assertFalse(own & {binds[v] for v in keep}, 'no binding number of the emulation\'s is one of the kernel\'s: passes that find a binding by its number alone (cbsize_strip) took one for the other')
        self.assertEqual(sum(x[0] == sm.OP_VARIABLE and x[3] == sm.SC_PUSHCONSTANT for x in ins), 1)
        modes = [x for x in ins if x[0] == sm.OP_EXECMODE]
        self.assertTrue(modes and all(x[1] == ent[0][2] for x in modes), 'the kernel\'s local size moves to the new entry point')
        return ins

    def test_mesh_compute(self):
        for task in (False, True):
            for prim in (False, True):
                for verts, psiz in ((3, False), (1, True), (2, False)):
                    info = mesh_info(task, prim, verts, psiz)
                    data, lay = kernel(info)
                    with self.subTest(task=task, prim=prim, verts=verts):
                        ins = self.computed(data, info, lay)
                        f = me.facts(info)
                        self.assertEqual(f['ipw'], 32 * verts)
                        self.assertEqual(f['nrec'], 32 * verts if prim else 64, 'per-primitive outputs make a record per corner')
                        self.assertEqual(f['nout'], (2 if psiz else 1) + 2 + (1 if prim else 0), 'position, the point size, locations 0 and 2, and location 1 per primitive')
                        self.assertEqual(f['locs'], 0b111 if prim else 0b101)
                        arith = {x[2] for x in ins if x[0] in sm.FLOAT_ARITH}
                        nc = {x[1] for x in ins if x[0] == sm.OP_DECORATE and x[2] == sm.DEC_NOCONTRACTION}
                        self.assertTrue(arith and nc == arith, 'a mesh kernel computes without contraction')
                        loc = [x for x in ins if x[0] == sm.OP_VARIABLE and x[3] == sm.SC_FUNCTION]
                        self.assertTrue(loc and all(len(x) > 4 for x in loc), 'locals start at zero')

    def test_task_compute(self):
        info = {'kind': 'ts', 'threads': 32, 'payload': 256}
        data, lay = kernel(info)
        self.computed(data, info, lay)
        self.assertEqual(me.facts(info), {'kind': 'ts', 'v': me.VERSION, 'pay': 64, 'threads': 32})

    def test_vertex(self):
        for prim in (False, True):
            for verts, psiz in ((3, False), (1, True), (1, False), (2, False)):
                info = mesh_info(False, prim, verts, psiz)
                for gl in (False, True):
                    with self.subTest(prim=prim, verts=verts, psiz=psiz, gl=gl):
                        ins = self.valid(me.vertex(info, gl))
                        locs = {x[3] for x in ins if x[0] == sm.OP_DECORATE and x[2] == sm.DEC_LOCATION}
                        self.assertEqual(sum(1 << n for n in locs), me.facts(info)['locs'])
                        builtins = [x[3] for x in ins if x[0] == sm.OP_DECORATE and x[2] == sm.DEC_BUILTIN]
                        self.assertIn(sm.BI_POSITION, builtins)
                        self.assertEqual(builtins.count(sm.BI_POINTSIZE), 1 if verts == 1 else 0, 'points write a size')
                        self.assertTrue(any(x[0] == sm.OP_DECORATE and x[2] == sm.DEC_INVARIANT for x in ins))

    def test_refuses_a_location_both_ways(self):
        info = mesh_info(False, True); info['primitive'] = [(0, 0)]
        with self.assertRaises(ValueError): me.facts(info)

    def test_the_post_pass_makes_them_in_one_process_and_in_several(self):   # spv_android.py: a pool job (a spawned process, as on Windows) imports spv_mesh and spv_meshemu itself
        infos = [mesh_info(False, False), mesh_info(True, True), {'kind': 'ts', 'threads': 32, 'payload': 256}]
        made = [kernel(i) for i in infos]
        with tempfile.TemporaryDirectory() as d:
            src = Path(d, 'src'); src.mkdir(); keys = {}
            for n in range(36):   # three pool jobs' worth (sa.CHUNK a job)
                info = infos[n % 3]; data, lay = made[n % 3]; k = f'{n:016x}'; keys[k] = info
                (src / f'{k}.spv').write_bytes(data)
                (src / f'{k}.res.json').write_text(json.dumps({'stage': 'cs', 'mesh': {'info': info, 'lay': lay}}), encoding='utf-8')
            outs = {}
            for j in (1, 3):
                dst = Path(d, f'out{j}')
                r = subprocess.run([sys.executable, sa.__file__, '-j', str(j), str(src), str(dst)], capture_output=True, text=True)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(f'spv_android: {len(keys)} shaders', r.stdout); self.assertIn(f'; {len(keys)} task / mesh shaders in compute form too', r.stdout)
                outs[j] = {p.name: p.read_bytes() for p in dst.iterdir()}
            self.assertEqual(outs[1], outs[3], 'the same files from one process and from three')
            for k, info in keys.items():
                ms = info['kind'] == 'ms'
                self.assertEqual({n for n in outs[1] if n.startswith(k)}, {f'{k}.spv', f'{k}.cs.spv', f'{k}.res.json'} | ({f'{k}.z.spv', f'{k}.pvs.spv', f'{k}.pvs.z.spv'} if ms else set()))
                res = json.loads(outs[1][f'{k}.res.json'])
                self.assertEqual(res['stage'], info['kind']); self.assertNotIn('mesh', res)
                self.assertEqual(res['mesh_emu'], json.loads(json.dumps(me.facts(info))))
                self.valid(outs[1][f'{k}.cs.spv'])
                if ms: self.valid(outs[1][f'{k}.pvs.spv']); self.valid(outs[1][f'{k}.pvs.z.spv'])

    @unittest.skipUnless(os.environ.get('DM_SPV_MESH_DIR'), 'DM_SPV_MESH_DIR not set')
    def test_translated_shaders(self):   # the translator's outputs of a game's task / mesh jobs
        d = Path(os.environ['DM_SPV_MESH_DIR'])
        jobs = {j['key']: j for j in json.loads((d / 'jobs.json').read_text())}
        n = 0
        for k, j in sorted(jobs.items()):
            p = d / f'{k}.spv'
            if not p.exists() or 'mesh_stage' not in j: continue
            info = j['mesh_stage']
            with self.subTest(key=k):
                try: self.computed(p.read_bytes(), info, j['stage_memory'])
                except ValueError as e: print(f'{k}: {e}'); continue
                if info['kind'] == 'ms':
                    for gl in (False, True): self.valid(me.vertex(info, gl))
                n += 1
        self.assertGreater(n, 0)


if __name__ == '__main__':
    unittest.main()
