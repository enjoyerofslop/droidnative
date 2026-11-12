"""A vertex shader's position made of constant buffer reads, read at run-time rows: dm/android/tools/spv_android.py pos_rows, on modules assembled with spirv-as in
the translator's form (every value in a Function variable, the position a member of a gl_PerVertex block, the constant buffers vec4[4096]), and its main(), whose
res.json extents are those of the reads before the change. Checked with spirv-val where there is one. Skipped without spirv-as (the NDK's shader-tools, else one on PATH)."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/android/tools'))
import spv_android as sa   # noqa: E402  # pyright: ignore[reportMissingImports]  # dm/android/tools, put on the path above
from test_spv_cbsize import SPV_AS, SPV_VAL   # noqa: E402

# clip x = world x * c3[0].x + world y * c3[1].x + c3[3].x (an Fma), as Unreal's last transform, c3[3] read as the merged translator bounds it (a select, its test true); world x is stored once, world y twice (a phi: the walk stops there,
# so c3[5], which it adds, keeps its constant row); c5[2] goes to another output. %IFACE%, %IDEC% and %IVAR% add a gl_InstanceIndex of the shader's own
MODULE = '''OpCapability Shader
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel Logical GLSL450
OpEntryPoint Vertex %main "main" %in %out %pv%IFACE%
OpDecorate %in Location 0
OpDecorate %out Location 0
OpMemberDecorate %pvt 0 BuiltIn Position
OpMemberDecorate %pvt 1 BuiltIn PointSize
OpDecorate %pvt Block
OpDecorate %arr ArrayStride 16
OpDecorate %blk Block
OpMemberDecorate %blk 0 Offset 0
OpDecorate %c3 DescriptorSet 0
OpDecorate %c3 Binding 14
OpDecorate %c5 DescriptorSet 0
OpDecorate %c5 Binding 10
%IDEC%
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%i32 = OpTypeInt 32 1
%u32 = OpTypeInt 32 0
%n4096 = OpConstant %u32 4096
%arr = OpTypeArray %v4 %n4096
%blk = OpTypeStruct %arr
%pblk = OpTypePointer Uniform %blk
%c3 = OpVariable %pblk Uniform
%c5 = OpVariable %pblk Uniform
%pu = OpTypePointer Uniform %f32
%pin = OpTypePointer Input %v4
%in = OpVariable %pin Input
%pout = OpTypePointer Output %v4
%out = OpVariable %pout Output
%pvt = OpTypeStruct %v4 %f32
%ppv = OpTypePointer Output %pvt
%pv = OpVariable %ppv Output
%pof = OpTypePointer Output %f32
%pfn = OpTypePointer Function %f32
%i0 = OpConstant %i32 0
%i1 = OpConstant %i32 1
%i2 = OpConstant %i32 2
%i3 = OpConstant %i32 3
%i5 = OpConstant %i32 5
%f1 = OpConstant %f32 1
%f0 = OpConstant %f32 0
%bool = OpTypeBool
%true = OpConstantTrue %bool
%IVAR%
%main = OpFunction %void None %fn
%entry = OpLabel
%wx = OpVariable %pfn Function
%wy = OpVariable %pfn Function
%cx = OpVariable %pfn Function
%a = OpLoad %v4 %in
%ax = OpCompositeExtract %f32 %a 0
%ay = OpCompositeExtract %f32 %a 1
OpStore %wx %ax
%o5p = OpAccessChain %pu %c3 %i0 %i5 %i0
%o5 = OpLoad %f32 %o5p
%wy0 = OpFAdd %f32 %ay %o5
OpStore %wy %wy0
OpStore %wy %ay
%m0p = OpAccessChain %pu %c3 %i0 %i0 %i0
%m0 = OpLoad %f32 %m0p
%m1p = OpAccessChain %pu %c3 %i0 %i1 %i0
%m1 = OpLoad %f32 %m1p
%m3p = OpAccessChain %pu %c3 %i0 %i3 %i0
%m3r = OpLoad %f32 %m3p
%m3 = OpSelect %f32 %true %m3r %f0
%lx = OpLoad %f32 %wx
%ly = OpLoad %f32 %wy
%t0 = OpFMul %f32 %lx %m0
%t1 = OpFMul %f32 %ly %m1
%t01 = OpFAdd %f32 %t0 %t1
%t3 = OpExtInst %f32 %glsl Fma %f1 %m3 %t01
OpStore %cx %t3
%px = OpAccessChain %pof %pv %i0 %i0
%lcx = OpLoad %f32 %cx
OpStore %px %lcx
%k5p = OpAccessChain %pu %c5 %i0 %i2 %i1
%k5 = OpLoad %f32 %k5p
%ov = OpCompositeConstruct %v4 %k5 %k5 %k5 %k5
OpStore %out %ov
OpReturn
OpFunctionEnd
'''
OWN_IID = {'%IFACE%': ' %iid', '%IDEC%': 'OpDecorate %iid BuiltIn InstanceIndex', '%IVAR%': '%pii = OpTypePointer Input %i32\n%iid = OpVariable %pii Input'}


@unittest.skipIf(SPV_AS is None, 'no spirv-as')
class PosRows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def asm(self, subst=None, text=MODULE):
        for k, v in {'%IFACE%': '', '%IDEC%': '', '%IVAR%': '', **(subst or {})}.items(): text = text.replace(k, v)
        p = self.tmp / 't.spvasm'; p.write_text(text)
        subprocess.run([str(SPV_AS), '--target-env', 'vulkan1.1', str(p), '-o', str(self.tmp / 't.spv')], check=True)
        return (self.tmp / 't.spv').read_bytes()

    def valid(self, data):
        if not SPV_VAL: return
        (self.tmp / 'v.spv').write_bytes(data)
        r = subprocess.run([str(SPV_VAL), '--target-env', 'vulkan1.1', str(self.tmp / 'v.spv')], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def rows(self, ins):
        """{(binding, column): the row operand's defining instruction, or the constant's value} of every chain into a constant buffer"""
        bind = {x[1]: x[3] for x in ins if x[0] == sa.OP_DECORATE and x[2] == sa.DEC_BINDING}
        const = {x[2]: x[3] for x in ins if x[0] == sa.OP_CONSTANT}
        defs = {x[2]: x for x in ins if x[0] not in (sa.OP_DECORATE, sa.OP_MEMBERDECORATE, sa.OP_ENTRY, sa.OP_STORE) and len(x) > 2}
        return {(bind[x[3]], const.get(x[5], x[5]) if x[5] in const else 'run', const[x[6]]): defs.get(x[5]) for x in ins
                if x[0] == sa.OP_ACCESSCHAIN and x[3] in bind}

    def check_runtime_rows(self, ins, iid):
        const = {x[2]: x[3] for x in ins if x[0] == sa.OP_CONSTANT}
        bound = {x[1] for x in ins if x[0] == sa.OP_DECORATE and x[2] == sa.DEC_BINDING}
        defs = {x[2]: x for x in ins if x[0] in (sa.OP_IADD, sa.OP_SELECT, sa.OP_SLESSTHAN, sa.OP_LOAD, sa.OP_BITCAST)}
        specid = {x[1]: x[3] for x in ins if x[0] == sa.OP_DECORATE and x[2] == sa.DEC_SPECID}
        spec = {x[2] for x in ins if x[0] == sa.OP_SPECCONSTANTFALSE and specid.get(x[2]) == sa.POS_ROWS_SPEC}   # false unless the host sets it
        got = []
        for x in ins:
            if x[0] != sa.OP_ACCESSCHAIN or x[3] not in bound or x[5] in const: continue   # chains into the constant buffers with a run-time row
            add = defs[x[5]]; self.assertEqual(add[0], sa.OP_IADD)
            row, z = add[3], add[4]; gate = defs[z]   # on ? min(i, 0) : 0
            self.assertEqual((gate[0], gate[3] in spec, const.get(gate[5])), (sa.OP_SELECT, True, 0))
            sel = defs[gate[4]]; lt = defs[sel[3]]
            self.assertEqual((sel[0], lt[0], sel[4], lt[3], const.get(sel[5]), const.get(lt[4])), (sa.OP_SELECT, sa.OP_SLESSTHAN, lt[3], sel[4], 0, 0))   # min(i, 0)
            self.assertEqual((defs[lt[3]][0], defs[lt[3]][3]), (sa.OP_LOAD, iid))
            got.append(const[row])
        return sorted(got)

    def instance_var(self, ins):
        return next(x[1] for x in ins if x[0] == sa.OP_DECORATE and x[2] == sa.DEC_BUILTIN and x[3] == sa.BUILTIN_INSTANCEINDEX)

    def test_the_transform_reads_its_rows_at_run_time(self):
        hdr, ins = sa.parse(self.asm())
        hdr, ins, n = sa.pos_rows(hdr, ins)
        self.assertEqual(n, 3)
        iid = self.instance_var(ins)
        self.assertIn(iid, next(x for x in ins if x[0] == sa.OP_ENTRY)[3:], 'gl_InstanceIndex is not in the interface')
        self.assertEqual(self.check_runtime_rows(ins, iid), [0, 1, 3])
        self.valid(sa.emit(hdr, ins))

    def test_other_reads_keep_their_constant_rows(self):   # c3[5] through the twice-stored world y, c5[2] for the other output
        hdr, ins = sa.parse(self.asm())
        rows = self.rows(sa.pos_rows(hdr, ins)[1])
        self.assertIn((14, 5, 0), rows); self.assertIn((10, 2, 1), rows)
        self.assertNotIn((14, 0, 0), rows)

    def test_the_shaders_own_instance_index(self):
        hdr, ins = sa.parse(self.asm(OWN_IID))
        iid = self.instance_var(ins); nvar = sum(1 for x in ins if x[0] == sa.OP_VARIABLE)
        hdr, ins, n = sa.pos_rows(hdr, ins)
        self.assertEqual((n, self.instance_var(ins), sum(1 for x in ins if x[0] == sa.OP_VARIABLE)), (3, iid, nvar))
        self.assertEqual(self.check_runtime_rows(ins, iid), [0, 1, 3])
        self.valid(sa.emit(hdr, ins))

    def test_a_position_of_no_constant_buffer_is_left(self):
        data = self.asm(text=MODULE.replace('OpStore %px %lcx', 'OpStore %px %ax'))
        hdr, ins = sa.parse(data)
        h2, i2, n = sa.pos_rows(hdr, ins)
        self.assertEqual((n, sa.emit(h2, i2)), (0, data))

    def test_main_keeps_the_extents_and_the_variants_read_at_run_time(self):
        src, dst = self.tmp / 'src', self.tmp / 'dst'; src.mkdir(exist_ok=True)
        (src / 'k.spv').write_bytes(self.asm())
        (src / 'k.res.json').write_text(json.dumps({'key': 'k', 'stage': 'vs', 'cbufs': [{'binding': 14, 'slot': 3}, {'binding': 10, 'slot': 5}]}))
        r = subprocess.run([sys.executable, str(REPO / 'dm/android/tools/spv_android.py'), str(src), str(dst)], check=True, capture_output=True, text=True)
        self.assertIn('position rows read at run time in 1 vertex shaders (3 reads)', r.stdout)
        res = json.loads((dst / 'k.res.json').read_text())
        self.assertEqual({c['binding']: c['ext'] for c in res['cbufs']}, {14: 96, 10: 48})   # rows 0-5 of c3, 0-2 of c5: not the whole buffers
        self.assertEqual(res['vin'], {'0': 'f'})
        for f in ('k.spv', 'k.z.spv'):
            ins = sa.parse((dst / f).read_bytes())[1]
            self.assertEqual(self.check_runtime_rows(ins, self.instance_var(ins)), [0, 1, 3], f)
            self.valid((dst / f).read_bytes())


if __name__ == '__main__':
    unittest.main()
