"""AnvilNext .forge archives (dm/gfx/tools/anvil_forge.py) and their place in shader_split.py: the LZO1X decoder on hand-made streams of every instruction kind and on damaged ones, a
synthetic version 27 file read back, its BNSH found through anvil_jobs / anvil_shaders, and the profile's shader_separate pairing every vertex shader. No game files needed."""
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'dm/tools/fuzz'))
import fuzz_shader_split as fz   # its BNSH builder and shader_split with a profile
ss = fz.ss
sys.path.insert(0, str(REPO / 'dm/gfx/tools'))
import anvil_forge as af   # noqa: E402

END = bytes([0x11, 0, 0])   # M4 with distance 0: the end marker


def run_bytes(t, extra):
    """A length past what the instruction holds: zero bytes of 255 each, then the rest (1..255)"""
    t -= extra; k = (t - 1) // 255
    return bytes(k) + bytes([t - 255 * k])


def lzo1x_rle(b):
    """LZO1X that writes each run of the byte before it (3 bytes or more) as an M3 match of distance 1 and the rest as literals: the matches carry the 1 to 3 literals after them in their
    low bits, longer literal runs follow a match whose low bits are 0"""
    seq, i, lit = [], 0, bytearray()
    while i < len(b):
        n = 0
        while i and i + n < len(b) and b[i + n] == b[i - 1]: n += 1
        if n >= 3: seq.append((bytes(lit), n)); lit = bytearray(); i += n
        else: lit.append(b[i]); i += 1
    seq.append((bytes(lit), 0))
    out = bytearray()
    for j, (lits, n) in enumerate(seq):
        if j == 0:
            if len(lits) <= 238: out += bytes([17 + len(lits)]) + lits if lits else b''
            else: out += b'\0' + run_bytes(len(lits) - 3, 15) + lits
        elif len(lits) >= 4: out += (bytes([len(lits) - 3]) if len(lits) - 3 <= 15 else b'\0' + run_bytes(len(lits) - 3, 15)) + lits
        else: out += lits   # 0 to 3: the previous match's low bits said so
        if n:
            after = len(seq[j + 1][0])
            out += bytes([32 | (n - 2)]) if n - 2 <= 31 else b'\x20' + run_bytes(n - 2, 31)
            out += struct.pack('<H', (0 << 2) | (after if after <= 3 else 0))   # distance 1
    return bytes(out + END)


class Lzo1x(unittest.TestCase):
    def test_instructions(self):
        lits = bytes(range(256)) * 64 + b'\x01'   # 0x4001 bytes: far enough back for M4
        cases = [
            ('a literal run at the start', bytes([17 + 5]) + b'hello' + END, b'hello'),
            ('M2: 4 bytes 4 back', bytes([17 + 4]) + b'abcd' + bytes([(3 << 5) | (3 << 2), 0]) + END, b'abcdabcd'),
            ('M2 overlapping its own output', bytes([17 + 1]) + b'a' + bytes([4 << 5, 0]) + END, b'a' * 6),
            ('M3 with an extended length', bytes([17 + 3]) + b'xyz' + bytes([0x20, 7, 2 << 2, 0]) + END, (b'xyz' * 15)[:43]),
            ('a long literal run, then M4 0x4001 back',
             b'\0' + run_bytes(len(lits) - 3, 15) + lits + bytes([16 | 3, 1 << 2, 0]) + END, lits + lits[:5]),
            ('the 3-byte match 0x801 back after a long literal run', b'\0' + run_bytes(len(lits) - 3, 15) + lits + b'\0\0' + END, lits + lits[-0x801:][:3]),
            ('a match\'s 2 literals, then the 2-byte match', bytes([17 + 4]) + b'abcd' + bytes([(3 << 5) | (3 << 2) | 2, 0]) + b'XY' + bytes([1 << 2, 0]) + END,
             b'abcdabcdXY' + b'XY'),
        ]
        for what, src, want in cases:
            with self.subTest(what): self.assertEqual(af.lzo1x(src, len(want)), want)

    def test_round_trip(self):   # a BNSH (mostly zeros) through the run encoder above: long M3 runs and literals carried in their low bits
        for b in (fz.bnsh(), bytes(0x8000), b'ab' + bytes(40) + b'cdefgh' + bytes(3) + b'i'):
            self.assertEqual(af.lzo1x(lzo1x_rle(b), len(b)), b)
            self.assertLess(len(lzo1x_rle(b)), len(b))

    def test_damaged(self):
        cases = [
            ('a match before the start', bytes([17 + 1]) + b'a' + bytes([(2 << 5) | (7 << 2), 0]) + END, 4, 'lies outside'),
            ('more output than the chunk', bytes([17 + 5]) + b'hello' + END, 4, 'runs past'),
            ('no end marker', bytes([17 + 5]) + b'hello', 5, 'without its end marker'),
            ('the end marker early', bytes([17 + 5]) + b'hello' + END, 6, 'not 0x6'),
            ('a literal run past the stream', bytes([17 + 9]) + b'abc', 9, 'runs past'),
        ]
        for what, src, n, msg in cases:
            with self.subTest(what), self.assertRaises(ValueError) as e: af.lzo1x(src, n, 'chunk')
            self.assertIn(msg, str(e.exception)); self.assertTrue(str(e.exception).startswith('chunk: '))


def block(data, compress=True, typ=af.LZO1X):
    """One block of one chunk: LZO1X when compress, else stored"""
    c = lzo1x_rle(data) if compress else data
    return af.BLOCK + struct.pack('<HBHHH', 1, typ, 0x8000, 0x8000, 1) + struct.pack('<HH', len(data), len(c)) + struct.pack('<I', 0x12345678) + c


def forge27(ents):
    """A version 27 .forge file of [(name, entry bytes)]: header, file data header, one table, the index, the name records, then the entries"""
    hdr, tab = 0x20, 0x60; idx = tab + 0x30; names = idx + af.INDEX * len(ents); data = names + af.NAME_REC * len(ents)
    d = bytearray(data)
    d[:9] = af.MAGIC; struct.pack_into('<Iq', d, 9, af.VERSION, hdr)
    struct.pack_into('<IIqIqIIq', d, hdr, len(ents), len(ents), 0, 0, -1, 5000, 1, tab)
    struct.pack_into('<IIqqIIqq', d, tab, len(ents), len(ents), idx, -1, 0, len(ents) - 1, names, data)
    for i, (name, e) in enumerate(ents):
        struct.pack_into('<qQI', d, idx + af.INDEX * i, len(d), 0x1000 + i, len(e))
        rec = names + af.NAME_REC * i; struct.pack_into('<IQ', d, rec, len(e), 0x1000 + i); d[rec + af.NAME_AT:rec + af.NAME_AT + len(name)] = name.encode()
        d += e
    return bytes(d)


TABLE = b'resource table' + bytes(30)
ENTS = [('GlobalMetaFile', b'\x01\0\0\0' * 8), ('MAT_Test', b'\x04' + bytes(7) + block(TABLE, False) + block(fz.bnsh())), ('TEX_Test', bytes(8) + block(bytes(0x400) + b'texels'))]


class Forge(unittest.TestCase):
    def test_entries_and_blocks(self):
        d = forge27(ENTS)
        self.assertEqual(af.version(d[:13]), 27); self.assertIsNone(af.version(b'BNSH' + bytes(9)))
        es = af.entries(d)
        self.assertEqual([n for _, _, n in es], ['GlobalMetaFile', 'MAT_Test', 'TEX_Test'])
        self.assertEqual(af.read(d, *es[0][:2]), [])   # no blocks: nothing
        self.assertEqual(af.read(d, *es[1][:2]), [TABLE, fz.bnsh()])   # a stored chunk and an LZO1X one
        self.assertEqual(af.read(d, *es[2][:2]), [bytes(0x400) + b'texels'])

    def test_damaged(self):
        d = forge27(ENTS)
        hdr = 0x20; tab = struct.unpack_from('<q', d, hdr + 0x24)[0]
        def changed(at, fmt, *v): b = bytearray(d); struct.pack_into(fmt, b, at, *v); return bytes(b)
        cases = [
            ('another version (the Ezio Collection\'s 31)', changed(9, '<I', 31), 'not an AnvilNext forge of version 27'),
            ('a table outside the file', changed(hdr + 0x24, '<q', len(d) + 0x100), 'outside the file'),
            ('a table that points at itself', changed(tab + 0x10, '<q', tab), 'read twice'),
            ('an entry past the end', changed(tab + 0x30 + af.INDEX, '<q', len(d) - 4), 'is outside the file'),
            ('a count the tables don\'t hold', changed(hdr, '<I', 4), 'the header counts 4'),
        ]
        for what, b, msg in cases:
            with self.subTest(what), self.assertRaises(ValueError) as e: af.entries(b, 'x.forge')
            self.assertIn(msg, str(e.exception))
        for what, ent, msg in (('a block of another type (2)', b'\x04' + bytes(7) + block(TABLE, typ=2), 'type 2'),
                               ('a chunk past its entry', b'\x04' + bytes(7) + block(fz.bnsh())[:-4], 'runs past the entry')):
            b = forge27([('E', ent)]); off, size, _ = af.entries(b)[0]
            with self.subTest(what), self.assertRaises(ValueError) as x: af.read(b, off, size, 'E')
            self.assertIn(msg, str(x.exception))

    def test_split_reads_the_bnsh(self):
        with tempfile.TemporaryDirectory() as t:
            p = os.path.join(t, 'DataNX_Test.forge'); Path(p).write_bytes(forge27(ENTS))
            other = os.path.join(t, 'Other.forge'); Path(other).write_bytes(b'scimitar\0' + struct.pack('<I', 31) + bytes(0x40))   # Scimitar's layout: not taken
            jobs, taken = ss.anvil_jobs([(p, 'DataNX_Test.forge'), (other, 'Other.forge')])
            self.assertEqual(taken, {p})
            found = []
            for path, rel, (kind, ents) in jobs: self.assertEqual(kind, ss.ANVIL); ss.anvil_shaders(path, rel, ents, found)
            self.assertEqual(sorted((w, st) for w, st, _, _ in found), [('/DataNX_Test.forge#MAT_Test#BNSH@0x0#var0', 'ps'), ('/DataNX_Test.forge#MAT_Test#BNSH@0x0#var0', 'vs')])
            self.assertEqual({(ctl, code) for _, _, ctl, code in found}, {fz.VS, fz.PS})


class Separate(unittest.TestCase):
    def test_every_vertex_shader_gets_the_cover(self):
        keys = {'v1': ('/a.forge#M#BNSH@0x0#var0', 'vs', b'', b'v1'), 'v2': ('main#BNSH@0x40#var0', 'vs', b'', b'v2'),
                'p1': ('/a.forge#N#BNSH@0x0#var0', 'ps', b'', b'p1'), 'p2': ('/a.forge#O#BNSH@0x0#var0', 'ps', b'', b'p2')}
        reads = {b'p1': {3}, b'p2': {0, 1}}
        with mock.patch.object(ss, 'ps_inputs', lambda code: reads[code]):
            with mock.patch.object(ss, 'SEPARATE', False): self.assertEqual(ss.separable_pairs(keys), (set(), []))   # BNSH pair their own stages
            with mock.patch.object(ss, 'SEPARATE', True):
                pairs, cover = ss.separable_pairs(keys)
        self.assertEqual(cover, ['p2', 'p1']); self.assertEqual(pairs, {(v, p) for v in ('v1', 'v2') for p in ('p1', 'p2')})


if __name__ == '__main__':
    unittest.main()
