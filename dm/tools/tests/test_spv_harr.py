"""dm/android/spv_harr.h (descriptor arrays longer than the Vulkan replay writes shortened to what it writes, their indices clamped again), built for the PC with the
Android NDK's clang and run on modules assembled with its spirv-as; spirv-val checks the result. Skipped without the NDK.
With DM_SPV_DIR=<a game's packed spv folder>, also run over every module there whose res.json names a texture or image array longer than 1,024 elements outside the
texture pool by ID (each result must pass spirv-val)."""
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

from test_spv_readonly import NDK, HOST, EXE   # noqa: E402

REPO = Path(__file__).resolve().parents[3]
LEN = 1024   # gfx_vk.c TEX_ARR_MAX

# A reflection shader's shape (Paper Mario: The Thousand-Year Door's 9ca1b3b6b5e824ae): a handle array from uniform slot 14 as long as a 64 KB buffer's handles, its
# index computed in an int and clamped to the last element; beside it an array in the pool set (set 4), which is left alone, and a short slot array
FS = '''OpCapability Shader
%glsl = OpExtInstImport "GLSL.std.450"
OpMemoryModel Logical GLSL450
OpEntryPoint Fragment %main "main" %uv %out %hnd
OpExecutionMode %main OriginUpperLeft
OpDecorate %uv Location 0
OpDecorate %hnd Location 1
OpDecorate %hnd Flat
OpDecorate %out Location 0
OpDecorate %arr DescriptorSet 1
OpDecorate %arr Binding 8
OpDecorate %pool DescriptorSet 4
OpDecorate %pool Binding 0
OpDecorate %slot DescriptorSet 1
OpDecorate %slot Binding 3
%NU%
%void = OpTypeVoid
%fn = OpTypeFunction %void
%f32 = OpTypeFloat 32
%v2 = OpTypeVector %f32 2
%v4 = OpTypeVector %f32 4
%u32 = OpTypeInt 32 0
%i32 = OpTypeInt 32 1
%c8k = OpConstant %u32 8192
%cmax = OpConstant %u32 8191
%c64k = OpConstant %u32 65536
%c32 = OpConstant %u32 32
%i0 = OpConstant %i32 0
%img = OpTypeImage %f32 2D 0 0 0 1 Unknown
%simg = OpTypeSampledImage %img
%aimg = OpTypeArray %simg %c8k
%apool = OpTypeArray %simg %c64k
%aslot = OpTypeArray %simg %c32
%paimg = OpTypePointer UniformConstant %aimg
%papool = OpTypePointer UniformConstant %apool
%paslot = OpTypePointer UniformConstant %aslot
%psimg = OpTypePointer UniformConstant %simg
%arr = OpVariable %paimg UniformConstant
%pool = OpVariable %papool UniformConstant
%slot = OpVariable %paslot UniformConstant
%pin2 = OpTypePointer Input %v2
%pinu = OpTypePointer Input %u32
%pout = OpTypePointer Output %v4
%uv = OpVariable %pin2 Input
%hnd = OpVariable %pinu Input
%out = OpVariable %pout Output
%main = OpFunction %void None %fn
%l0 = OpLabel
%h = OpLoad %u32 %hnd
%cl = OpExtInst %u32 %glsl UMin %h %cmax
%ii = OpBitcast %i32 %cl
%p = OpAccessChain %psimg %arr %ii
%s = OpLoad %simg %p
%t = OpLoad %v2 %uv
%r1 = OpImageSampleImplicitLod %v4 %s %t
%pp = OpAccessChain %psimg %pool %h
%sp = OpLoad %simg %pp
%r2 = OpImageSampleImplicitLod %v4 %sp %t
%ps = OpAccessChain %psimg %slot %i0
%ss = OpLoad %simg %ps
%r3 = OpImageSampleImplicitLod %v4 %ss %t
%pu = OpAccessChain %psimg %arr %h
%su = OpLoad %simg %pu
%r4 = OpImageSampleImplicitLod %v4 %su %t
%a = OpFAdd %v4 %r1 %r2
%b = OpFAdd %v4 %a %r3
%c = OpFAdd %v4 %b %r4
%EXTRA%
OpStore %out %c
OpReturn
OpFunctionEnd
'''


def words(data) -> list[int]:
    return list(struct.unpack(f'<{len(data) // 4}I', data))


def instrs(data):
    w = words(data); i = 5
    while i < len(w):
        n = w[i] >> 16; yield w[i] & 0xffff, w[i:i + n]; i += n


@unittest.skipIf(NDK is None, 'no Android NDK')
class SpvHarr(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        assert NDK is not None
        cls.tmp = Path(tempfile.mkdtemp())
        tools = NDK / 'shader-tools' / HOST; cls.spv_as, cls.spv_val = tools / f'spirv-as{EXE}', tools / f'spirv-val{EXE}'
        bin_ = NDK / 'toolchains/llvm/prebuilt' / HOST / 'bin'
        src = cls.tmp / 'h.c'
        export = '__declspec(dllexport)' if os.name == 'nt' else '__attribute__((visibility("default")))'
        src.write_text('#include "spv_harr.h"\n'
                       f'{export} size_t run(const uint32_t *w, size_t n, uint32_t len, uint32_t *s, uint32_t *o, size_t cap, size_t *need, int *info) {{\n'
                       '    return spv_harr(w, n, 4, len, s, o, cap, need, info); }\n')
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
        if os.name == 'nt':   # no C library: a DLL linked by lld alone (test_spv_pool.py)
            subprocess.run([bin_ / 'clang.exe', '--target=x86_64-pc-windows-msvc', '-ffreestanding', '-nostdlib', '-O1', '-Wall', '-I', REPO / 'dm/android', '-c', src, '-o', cls.tmp / 'h.obj'], check=True)
            subprocess.run([bin_ / 'ld.lld.exe', '-flavor', 'link', '-dll', '-noentry', f'-out:{cls.tmp / "h.dll"}', str(cls.tmp / 'h.obj')], check=True, env=env)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'h.dll'))
        else:
            cc = ['xcrun', 'clang'] if sys.platform == 'darwin' else [shutil.which('clang') or bin_ / 'clang']
            subprocess.run([*cc, '-shared', '-fPIC', '-O1', '-Wall', '-Wextra', '-Werror', '-I', REPO / 'dm/android', src, '-o', cls.tmp / 'h.so'], check=True)
            cls.lib = ctypes.CDLL(str(cls.tmp / 'h.so'))
        u32p = ctypes.POINTER(ctypes.c_uint32)
        cls.lib.run.argtypes = [u32p, ctypes.c_size_t, ctypes.c_uint32, u32p, u32p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(ctypes.c_int)]
        cls.lib.run.restype = ctypes.c_size_t

    def run_on(self, data, length=LEN):
        n = len(data) // 4; w = (ctypes.c_uint32 * n).from_buffer_copy(data); bound = w[3]
        s = (ctypes.c_uint32 * (7 * bound))(); need = ctypes.c_size_t(); info = ctypes.c_int()
        k = self.lib.run(w, n, length, s, None, 0, ctypes.byref(need), ctypes.byref(info))   # the size it asks for, then the rewrite
        if not need.value: return None, info.value
        o = (ctypes.c_uint32 * need.value)()
        k = self.lib.run(w, n, length, s, o, need.value, ctypes.byref(need), ctypes.byref(info))
        return (bytes(o)[:4 * k] if k else None), info.value

    def val(self, data, name):
        p = self.tmp / name; p.write_bytes(data)
        env = 'vulkan1.1spv1.4' if words(data)[1] >= 0x10400 else 'vulkan1.1'
        r = subprocess.run([self.spv_val, '--target-env', env, p], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def asm(self, text, name):
        p = self.tmp / f'{name}.spvasm'; p.write_text(text)
        subprocess.run([self.spv_as, '--target-env', 'vulkan1.1', p, '-o', self.tmp / f'{name}.spv'], check=True)
        return (self.tmp / f'{name}.spv').read_bytes()

    def fs(self, nu='', extra=''):
        text = FS.replace('%NU%\n', nu).replace('%EXTRA%\n', extra)
        if nu: text = text.replace('OpCapability Shader\n', 'OpCapability Shader\nOpCapability ShaderNonUniform\nOpExtension "SPV_EXT_descriptor_indexing"\n')
        return text

    def lengths(self, data):   # each variable's array length: variable id → length
        consts = {ins[2]: ins[3] for op, ins in instrs(data) if op == 43}
        arrs = {ins[1]: consts.get(ins[3]) for op, ins in instrs(data) if op == 28}
        ptrs = {ins[1]: arrs.get(ins[3]) for op, ins in instrs(data) if op == 32}
        return {ins[2]: ptrs.get(ins[1]) for op, ins in instrs(data) if op == 59 and ins[3] == 0}

    def names(self, text):   # spirv-as numbers ids in order of first appearance: the variables' ids from a module assembled with them
        data = self.asm(text, 'names')
        return [ins[2] for op, ins in instrs(data) if op == 59 and ins[3] == 0]

    def test_reflection_array(self):
        data = self.asm(self.fs(), 'fs')
        out, info = self.run_on(data)
        self.assertIsNotNone(out); self.assertEqual(info, 1)
        self.val(out, 'fs_out.spv')
        arr, pool, slot = self.names(self.fs())
        self.assertEqual(self.lengths(out), {arr: LEN, pool: 65536, slot: 32}, 'the handle array shortened, the pool set\'s and the slot array left')
        glsl = next(ins[1] for op, ins in instrs(out) if op == 11)
        consts = {ins[2]: ins[3] for op, ins in instrs(out) if op == 43}
        umins = [ins for op, ins in instrs(out) if op == 12 and ins[3] == glsl and ins[4] == 38]
        self.assertEqual(sorted(consts[u[6]] for u in umins), [LEN - 1, LEN - 1, 8191], 'both chains into the array clamped again, as an int and as a uint')

    def test_nonuniform_index(self):
        out, info = self.run_on(self.asm(self.fs(nu='OpDecorate %h NonUniform\n'), 'fsnu'))
        self.assertIsNotNone(out); self.val(out, 'fsnu_out.spv')
        nu = {ins[1] for op, ins in instrs(out) if op == 71 and ins[2] == 5300}
        self.assertEqual(len(nu), 2, 'the NonUniform index and its clamp')

    def test_short_arrays_left(self):
        self.assertEqual(self.run_on(self.asm(self.fs(), 'fsl'), length=65536), (None, 0))

    def test_whole_array_load_refused(self):
        self.assertEqual(self.run_on(self.asm(self.fs(extra='%all = OpLoad %aimg %arr\n'), 'fsall')), (None, 2))

    def test_no_glsl_import(self):
        text = self.fs().replace('%glsl = OpExtInstImport "GLSL.std.450"\n', '').replace('%cl = OpExtInst %u32 %glsl UMin %h %cmax\n', '%cl = OpCopyObject %u32 %h\n')
        out, info = self.run_on(self.asm(text, 'fsng'))
        self.assertIsNotNone(out); self.assertEqual(info, 1); self.val(out, 'fsng_out.spv')

    @unittest.skipUnless(os.environ.get('DM_SPV_DIR'), 'DM_SPV_DIR not set')
    def test_a_games_long_arrays(self):
        d = Path(os.environ['DM_SPV_DIR'])
        n = ok = 0; refused = []
        for rj in sorted(d.glob('*.res.json')):
            r = json.loads(rj.read_text(encoding='utf-8'))
            if not any((t.get('array', 1) or 1) > LEN and not (t.get('handle') == 0x40000000 and t.get('cbuf_slot') == 0) for t in r.get('textures', []) + r.get('images', [])): continue
            for sp in (d / (rj.name[:-9] + '.spv'), d / (rj.name[:-9] + '.z.spv')):
                if not sp.is_file(): continue
                n += 1; out, info = self.run_on(sp.read_bytes())
                if not out: refused.append(sp.name); continue
                ok += 1
                with self.subTest(module=sp.name): self.val(out, 'game.spv')
        print(f'{n} modules with arrays longer than {LEN}: {ok} rewritten, {len(refused)} left: {refused[:8]}')
        self.assertTrue(n); self.assertFalse(refused)


if __name__ == '__main__':
    unittest.main()
