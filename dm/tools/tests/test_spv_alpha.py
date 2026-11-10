"""dm/android/spv_alpha.h (NVN's alpha test rewritten into the fragment shader), built for the PC and run on modules assembled with the NDK's spirv-as;
spirv-val checks every result. Skipped without the NDK.

The cases cover what the rewrite must get right on the Vulkan replay: the shader's own OpReturn instructions are left alone (the wrapper calls the original
entry point as a function, which is no longer an entry point), the function is a specialization constant that carries SpecId 0, the reference arrives in a
push constant rather than the pipeline key, an Input decorated Location 0 is not taken for the colour, shaders without bool or signed-int types get them
added, a module with its own SpecId 0 or push-constant block is refused (the transform would collide), an integer colour 0 is refused (no alpha test, as in
OpenGL), and a SPIR-V 1.4 module lists the push constant in its entry point's interface.
With DM_SPV_DIR=<a game's packed spv folder>, also run over that game's fragment shaders: each transformed module must pass spirv-val.
"""
import ctypes
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_spv_readonly import NDK, HOST, EXE, REPO   # noqa: E402

SHIM = '''#include <stdint.h>
#include <stddef.h>
#include "spv_alpha.h"
size_t run(const uint32_t *w, size_t n, uint32_t *o, size_t cap, uint32_t *afn) { return spv_alpha(w, n, o, cap, afn); }
'''

# A fragment shader as the translator writes one: a float colour 0, two returns on two paths
BASIC = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %col %in
OpExecutionMode %main OriginUpperLeft
OpDecorate %col Location 0
OpDecorate %in Location 1
%void = OpTypeVoid
%fn = OpTypeFunction %void
%bool = OpTypeBool
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%pin = OpTypePointer Input %f32
%in = OpVariable %pin Input
%pout = OpTypePointer Output %v4
%col = OpVariable %pout Output
%t = OpConstantTrue %bool
%main = OpFunction %void None %fn
%l = OpLabel
%x = OpLoad %f32 %in
%v = OpCompositeConstruct %v4 %x %x %x %x
OpStore %col %v
OpSelectionMerge %m None
OpBranchConditional %t %a %b
%a = OpLabel
OpReturn
%b = OpLabel
OpBranch %m
%m = OpLabel
OpReturn
OpFunctionEnd
'''

# An Input and an Output both decorated Location 0: the Output is the colour
TWO_LOCATIONS = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %out %in0
OpExecutionMode %main OriginUpperLeft
OpDecorate %in0 Location 0
OpDecorate %out Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%pin = OpTypePointer Input %v4
%in0 = OpVariable %pin Input
%pout = OpTypePointer Output %v4
%out = OpVariable %pout Output
%main = OpFunction %void None %fn
%l = OpLabel
%v = OpLoad %v4 %in0
OpStore %out %v
OpReturn
OpFunctionEnd
'''

# No bool and no signed int type declared: the rewrite adds them
NO_BOOL_INT = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %col
OpExecutionMode %main OriginUpperLeft
OpDecorate %col Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%v4 = OpTypeVector %f32 4
%pout = OpTypePointer Output %v4
%col = OpVariable %pout Output
%z = OpConstant %f32 0
%main = OpFunction %void None %fn
%l = OpLabel
%v = OpCompositeConstruct %v4 %z %z %z %z
OpStore %col %v
OpReturn
OpFunctionEnd
'''

# An integer colour 0: no alpha test
INT_COLOUR = '''OpCapability Shader
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %col
OpExecutionMode %main OriginUpperLeft
OpDecorate %col Location 0
%void = OpTypeVoid
%fn = OpTypeFunction %void
%i32 = OpTypeInt 32 1
%v4i = OpTypeVector %i32 4
%pout = OpTypePointer Output %v4i
%col = OpVariable %pout Output
%main = OpFunction %void None %fn
%l = OpLabel
%z = OpConstant %i32 0
%v = OpCompositeConstruct %v4i %z %z %z %z
OpStore %col %v
OpReturn
OpFunctionEnd
'''

SPEC0 = BASIC.replace('%bool = OpTypeBool', '%bool = OpTypeBool\n%u32 = OpTypeInt 32 0\n%sc = OpSpecConstant %u32 1').replace(
    'OpDecorate %in Location 1', 'OpDecorate %in Location 1\nOpDecorate %sc SpecId 0')

PUSHCONST = BASIC.replace('%col = OpVariable %pout Output', """%col = OpVariable %pout Output
%pcstruct = OpTypeStruct %f32
%pcptr = OpTypePointer PushConstant %pcstruct
%pcv = OpVariable %pcptr PushConstant""").replace(
    'OpDecorate %in Location 1', 'OpDecorate %in Location 1\nOpDecorate %pcstruct Block\nOpMemberDecorate %pcstruct 0 Offset 0')


def words(data):
    return struct.unpack(f'<{len(data) // 4}I', data)


def opcodes(data):
    w, i, out = words(data), 5, []
    while i < len(w):
        n = w[i] >> 16
        if not n or i + n > len(w):
            raise ValueError('malformed module')
        out.append((w[i] & 0xffff, w[i:i + n]))
        i += n
    return out


def entry_function(data):
    for op, ins in opcodes(data):
        if op == 15 and ins[1] == 4:   # OpEntryPoint: execution model (Fragment), function, name, interface
            return ins[2]
    return 0


@unittest.skipUnless(NDK, 'the NDK is not installed')
class SpvAlpha(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp(prefix='spv_alpha_'))
        tools = NDK / 'shader-tools' / HOST
        cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        cc = shutil.which('cc') or shutil.which('clang')
        if not cc or not cls.spv_as.exists() or not cls.spv_val.exists():
            raise unittest.SkipTest('spirv-as, spirv-val or a C compiler is missing')
        src, so, dll = cls.tmp / 'shim.c', cls.tmp / ('shim.so' if os.name != 'nt' else 'shim.dll'), cls.tmp / 'shim.dll'
        src.write_text(SHIM)
        subprocess.run([cc, '-O1', '-shared', '-fPIC', f'-I{REPO / "dm/android"}', str(src), '-o', str(so)], check=True, capture_output=True)
        cls.lib = ctypes.CDLL(str(so if os.name != 'nt' else dll))
        cls.lib.run.restype = ctypes.c_size_t

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def assemble(self, text, env='vulkan1.1'):
        src, out = self.tmp / 'in.spvasm', self.tmp / 'in.spv'
        src.write_text(text)
        subprocess.run([str(self.spv_as), '--target-env', env, str(src), '-o', str(out)], check=True, capture_output=True)
        return out.read_bytes()

    def transform(self, data):
        w = (ctypes.c_uint32 * (len(data) // 4)).from_buffer_copy(data)
        o = (ctypes.c_uint32 * (len(data) // 4 + 256))()
        afn = ctypes.c_uint32(0)
        n = self.lib.run(w, len(data) // 4, o, len(o), ctypes.byref(afn))
        return (b''.join(struct.pack('<I', o[i]) for i in range(n)) if n else b''), afn.value

    def validate(self, data, env='vulkan1.1'):
        p = self.tmp / 'out.spv'
        p.write_bytes(data)
        r = subprocess.run([str(self.spv_val), '--target-env', env, str(p)], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_a_float_colour_gets_the_test_and_keeps_its_returns(self):
        src = self.assemble(BASIC)
        out, afn = self.transform(src)
        self.assertTrue(out)
        self.validate(out)
        self.assertNotEqual(entry_function(out), entry_function(src), 'a new entry point wraps the shader')
        before = [ins for op, ins in opcodes(src) if op == 253]   # OpReturn
        after = [ins for op, ins in opcodes(out) if op == 253]
        self.assertEqual(len(after), len(before) + 1, "the shader's own returns are untouched (only the wrapper adds one)")
        sids = [ins[3] for op, ins in opcodes(out) if op == 71 and ins[2] == 1]   # OpDecorate ... SpecId
        self.assertIn(0, sids, 'the function specialization constant carries SpecId 0')
        self.assertTrue(any(op == 59 and ins[3] == 9 for op, ins in opcodes(out)), 'the reference is a push constant')
        self.assertTrue(afn)

    def test_the_output_is_taken_when_an_input_shares_location_0(self):
        out, _ = self.transform(self.assemble(TWO_LOCATIONS))
        self.assertTrue(out)
        self.validate(out)

    def test_a_shader_without_bool_or_int_gets_them(self):
        out, _ = self.transform(self.assemble(NO_BOOL_INT))
        self.assertTrue(out)
        self.validate(out)
        kinds = [op for op, _ in opcodes(out)]
        self.assertIn(20, kinds)
        self.assertIn(21, kinds)

    def test_an_integer_colour_is_left_alone(self):
        self.assertEqual(self.transform(self.assemble(INT_COLOUR)), (b'', 0))


    def test_a_module_with_its_own_specid_0_is_refused(self):
        self.assertEqual(self.transform(self.assemble(SPEC0)), (b'', 0))

    def test_a_module_with_a_push_constant_block_is_refused(self):
        self.assertEqual(self.transform(self.assemble(PUSHCONST)), (b'', 0))

    def test_a_spirv_1_4_module_lists_the_push_constant(self):
        out, _ = self.transform(self.assemble(BASIC, 'spv1.4'))
        self.assertTrue(out)
        self.validate(out, 'vulkan1.2')   # a 1.4 module under Vulkan rules
        ins = [(op, x) for op, x in opcodes(out) if op == 15]
        self.assertEqual(len(ins), 1)
        entry = ins[0][1]
        vars_pc = {x[2] for op, x in opcodes(out) if op == 59 and x[3] == 9}   # OpVariable PushConstant
        self.assertTrue(vars_pc & set(entry[3:]), 'the push constant is in the entry point interface')

    def test_a_games_shaders(self):   # DM_SPV_DIR: every transformed fragment shader must pass spirv-val
        d = os.environ.get('DM_SPV_DIR')
        if not d:
            self.skipTest('DM_SPV_DIR is not set')
        n = bad = 0
        for f in sorted(Path(d).glob('*.res.json')):
            try:
                r = json.loads(f.read_text(encoding='utf-8'))
            except ValueError:
                continue
            if r.get('stage') != 'ps':
                continue
            spv = f.with_name(f.name[:-9] + '.spv').read_bytes()
            out, _ = self.transform(spv)
            if not out:
                continue
            n += 1
            try:
                self.validate(out)
            except AssertionError:
                bad += 1
                if bad <= 3:
                    print(f'transformed module fails spirv-val: {spv}', file=sys.stderr)
            if n >= 200:
                break
        self.assertGreater(n, 0)
        self.assertEqual(bad, 0)


if __name__ == '__main__':
    unittest.main()
