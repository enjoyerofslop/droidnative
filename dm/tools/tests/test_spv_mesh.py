"""NVN2 task and mesh shaders as Vulkan task and mesh modules: dm/android/tools/spv_mesh.py wrap, on a compute module shaped as the translator writes a task or mesh job
(its stage memory one workgroup uint array, a BufferBlock storage buffer, an early return), assembled with spirv-as (the NDK's shader-tools, else one on PATH) and checked
with spirv-val for Vulkan 1.3 (SPIR-V 1.4, which VK_EXT_mesh_shader needs). Skipped without them.
With DM_SPV_MESH_DIR=<a folder of the translator's task / mesh outputs and their jobs.json>, every one there is wrapped and checked too."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools')); sys.path.insert(0, str(REPO / 'dm/gfx/tools'))
import spv_android as sa   # noqa: E402  # pyright: ignore[reportMissingImports]
import spv_mesh   # noqa: E402  # pyright: ignore[reportMissingImports]
import dmsh_meshstage as ms_   # noqa: E402  # pyright: ignore[reportMissingImports]
from test_spv_readonly import NDK, HOST, EXE   # noqa: E402

TOOL = lambda n: (NDK / 'shader-tools' / HOST / f'{n}{EXE}') if NDK and (NDK / 'shader-tools' / HOST / f'{n}{EXE}').exists() else shutil.which(n)
SPV_AS, SPV_VAL = TOOL('spirv-as'), TOOL('spirv-val')

# The kernel: lane 0 stores a word at the stage memory's index %AT% and one into the storage buffer, twice a local it never stored; the other lanes return early.
# %WORDS% sizes the stage memory
KERNEL = '''OpCapability Shader
OpCapability GroupNonUniform
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel Logical GLSL450
OpEntryPoint GLCompute %main "main" %lane
OpExecutionMode %main LocalSize 32 1 1
OpDecorate %lane BuiltIn SubgroupLocalInvocationId
OpDecorate %rt ArrayStride 4
OpDecorate %sb BufferBlock
OpMemberDecorate %sb 0 Offset 0
OpDecorate %ssbo DescriptorSet 0
OpDecorate %ssbo Binding 1
%void = OpTypeVoid
%fn = OpTypeFunction %void
%u32 = OpTypeInt 32 0
%bool = OpTypeBool
%f32 = OpTypeFloat 32
%pff = OpTypePointer Function %f32
%c2 = OpConstant %f32 2
%c0 = OpConstant %u32 0
%cat = OpConstant %u32 %AT%
%cv = OpConstant %u32 0x03000000
%nw = OpConstant %u32 %WORDS%
%arr = OpTypeArray %u32 %nw
%parr = OpTypePointer Workgroup %arr
%mem = OpVariable %parr Workgroup
%pwu = OpTypePointer Workgroup %u32
%rt = OpTypeRuntimeArray %u32
%sb = OpTypeStruct %rt
%psb = OpTypePointer Uniform %sb
%ssbo = OpVariable %psb Uniform
%puu = OpTypePointer Uniform %u32
%pin = OpTypePointer Input %u32
%lane = OpVariable %pin Input
%main = OpFunction %void None %fn
%l0 = OpLabel
%loc = OpVariable %pff Function
%id = OpLoad %u32 %lane
%z = OpIEqual %bool %id %c0
OpSelectionMerge %l2 None
OpBranchConditional %z %l1 %l3
%l3 = OpLabel
OpReturn
%l1 = OpLabel
%p = OpAccessChain %pwu %mem %cat
OpStore %p %cv
%q = OpAccessChain %puu %ssbo %c0 %c0
%lv = OpLoad %f32 %loc
%twice = OpFMul %f32 %lv %c2
%tb = OpBitcast %u32 %twice
OpStore %q %tb
OpBranch %l2
%l2 = OpLabel
OpReturn
OpFunctionEnd
'''


def mesh_info(task, prim, verts=3, psiz=False):
    return {'kind': 'ms', 'threads': 32, 'payload': 64, 'task': task, 'verts': verts, 'max_v': 64, 'max_p': 32,
            'vertex': ([('psiz', 0)] if psiz else []) + [(None, c) for c in range(4)] + [(0, 0), (0, 1), (2, 3)], 'primitive': [(1, 0), (1, 2)] if prim else []}


@unittest.skipUnless(SPV_AS and SPV_VAL, 'spirv-as / spirv-val not found (the NDK shader-tools or PATH)')
class SpvMesh(unittest.TestCase):
    def kernel(self, info):
        lay, size = ms_.memory(info)
        src = KERNEL.replace('%WORDS%', str(size // 4)).replace('%AT%', str(lay[3] >> 2))   # the primitive count's word
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'k.spvasm').write_text(src)
            subprocess.run([SPV_AS, '--target-env', 'vulkan1.1', str(Path(d, 'k.spvasm')), '-o', str(Path(d, 'k.spv'))], check=True)
            return Path(d, 'k.spv').read_bytes(), lay

    def valid(self, data, kind):
        hdr, ins = sa.process(data, kind)[:2]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d, 'm.spv'); p.write_bytes(sa.emit(hdr, ins))
            r = subprocess.run([SPV_VAL, '--target-env', 'vulkan1.3', str(p)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return ins

    def test_mesh_shaders(self):
        for task in (False, True):
            for prim in (False, True):
                for verts, psiz in ((3, False), (1, True), (2, False)):
                    info = mesh_info(task, prim, verts, psiz)
                    data, lay = self.kernel(info)
                    for gl in (False, True):
                        with self.subTest(task=task, prim=prim, verts=verts, gl=gl):
                            out, mask = spv_mesh.wrap(data, info, lay, gl)
                            ins = self.valid(out, 'ms')
                            self.assertEqual(mask, 0b10 if prim else 0)
                            self.assertEqual(sa.parse(out)[0][1], spv_mesh.VERSION_1_4)
                            ent = [x for x in ins if x[0] == spv_mesh.OP_ENTRY]
                            self.assertEqual(len(ent), 1); self.assertEqual(ent[0][1], spv_mesh.MODEL_MESH)
                            modes = {x[2]: x[3:] for x in ins if x[0] == spv_mesh.OP_EXECMODE}
                            self.assertEqual(modes[spv_mesh.MODE_OUTPUTVERTICES], [64]); self.assertEqual(modes[spv_mesh.MODE_OUTPUTPRIMITIVES], [32])
                            self.assertIn({1: spv_mesh.MODE_OUTPUTPOINTS, 2: spv_mesh.MODE_OUTPUTLINES, 3: spv_mesh.MODE_OUTPUTTRIANGLES}[verts], modes)
                            decor = [x for x in ins if x[0] == spv_mesh.OP_DECORATE]
                            self.assertTrue(any(x[2] == spv_mesh.DEC_INVARIANT for x in decor), 'the position is invariant')
                            self.assertEqual(sum(x[2] == spv_mesh.DEC_PERPRIMITIVE for x in decor), 1 if prim else 0)
                            self.assertFalse(any(x[2] == spv_mesh.DEC_BUFFERBLOCK for x in decor), 'no BufferBlock in SPIR-V 1.4')
                            pcs = [x for x in ins if x[0] == spv_mesh.OP_VARIABLE and x[3] == spv_mesh.SC_PUSHCONSTANT]
                            self.assertEqual(len(pcs), 0 if task else 1, 'the first workgroup comes in a push constant without a task')
                            self.zeroed(ins)
                            arith = {x[2] for x in ins if x[0] in spv_mesh.FLOAT_ARITH}
                            nc = {x[1] for x in decor if x[2] == spv_mesh.DEC_NOCONTRACTION}
                            self.assertEqual(nc, arith, 'every float result of a mesh shader, the kernel\'s and the entry point\'s, is NoContraction')
                            self.assertGreaterEqual(len(arith), 3 if gl else 1)

    def test_task_shader(self):
        info = {'kind': 'ts', 'threads': 32, 'payload': 256}
        data, lay = self.kernel(info)
        out, mask = spv_mesh.wrap(data, info, lay)
        ins = self.valid(out, 'ts')
        self.assertEqual(mask, 0)
        self.assertEqual([x[1] for x in ins if x[0] == spv_mesh.OP_ENTRY], [spv_mesh.MODEL_TASK])
        self.assertEqual(sum(x[0] == spv_mesh.OP_EMITMESHTASKS for x in ins), 1)
        self.assertEqual(sum(x[0] == spv_mesh.OP_VARIABLE and x[3] == spv_mesh.SC_PAYLOAD for x in ins), 1)
        self.zeroed(ins)
        self.assertFalse(any(x[0] == spv_mesh.OP_DECORATE and x[2] == spv_mesh.DEC_NOCONTRACTION for x in ins), 'a task shader computes no position')

    def zeroed(self, ins):   # every Function variable starts at its type's zero
        nulls = {x[2]: x[1] for x in ins if x[0] == spv_mesh.OP_CONSTANTNULL}
        ptr = {x[1]: x[3] for x in ins if x[0] == spv_mesh.OP_TYPEPOINTER}
        loc = [x for x in ins if x[0] == spv_mesh.OP_VARIABLE and x[3] == spv_mesh.SC_FUNCTION]
        self.assertTrue(loc)
        for x in loc: self.assertEqual(nulls.get(x[4] if len(x) > 4 else None), ptr[x[1]], 'a local without its zero')

    def test_refuses_own_shared_memory(self):   # a second workgroup variable would lie over the stage memory
        info = mesh_info(False, False)
        lay, size = ms_.memory(info)
        src = KERNEL.replace('%WORDS%', str(size // 4)).replace('%AT%', '0').replace('%pwu = OpTypePointer Workgroup %u32', '%pwu = OpTypePointer Workgroup %u32\n%own = OpVariable %pwu Workgroup')
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'k.spvasm').write_text(src)
            subprocess.run([SPV_AS, '--target-env', 'vulkan1.1', str(Path(d, 'k.spvasm')), '-o', str(Path(d, 'k.spv'))], check=True)
            data = Path(d, 'k.spv').read_bytes()
        with self.assertRaises(ValueError): spv_mesh.wrap(data, info, lay)

    @unittest.skipUnless(os.environ.get('DM_SPV_MESH_DIR'), 'DM_SPV_MESH_DIR not set')
    def test_translated_shaders(self):   # the translator's outputs of a game's task / mesh jobs
        d = Path(os.environ['DM_SPV_MESH_DIR'])
        jobs = {j['key']: j for j in json.loads((d / 'jobs.json').read_text())}
        n = 0
        for k, j in sorted(jobs.items()):
            p = d / f'{k}.spv'
            if not p.exists(): continue
            info = j['mesh_stage']
            for gl in ((False, True) if info['kind'] == 'ms' else (False,)):
                with self.subTest(key=k, gl=gl): self.valid(spv_mesh.wrap(p.read_bytes(), info, j['stage_memory'], gl)[0], info['kind']); n += 1
        self.assertGreater(n, 0)


if __name__ == '__main__':
    unittest.main()
