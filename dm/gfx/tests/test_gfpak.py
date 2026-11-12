"""GFPAK archives (Game Freak), without game data: each entry's compression, Oodle through the game's own decoder."""
import hashlib
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock
import zlib

import lz4.block

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import shader_split


def gfpak(entries):
    """A GFPAK of (compression, raw length, stored bytes) entries: the 0x30-byte header, the file table, then the data"""
    table = 0x30
    data_at = table + 0x18 * len(entries)
    rows, data = b'', b''
    for ct, usz, stored in entries:
        rows += struct.pack('<HHII4xQ', 0, ct, usz, len(stored), data_at + len(data))
        data += stored
    return b'GFLXPACK' + struct.pack('<IIIIQQQ', 0x1000, 0, len(entries), 0, table, 0, 0) + rows + data


class GfpakTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.real_oodle = shader_split.oodle
        def fake_oodle(comp, n):   # stands in for the game's decoder in the Mac host (DM_OODLE_SERVE)
            self.calls.append((bytes(comp), n)); return b'K' * n
        shader_split.oodle = fake_oodle

    def tearDown(self):
        shader_split.oodle = self.real_oodle

    def test_entries_by_compression(self):
        # Sword's entries are LZ4; Pokémon Legends: Arceus's are Oodle Kraken (compression 3)
        raw = b'BNSH' + bytes(60)
        d = gfpak([(0, len(raw), raw), (1, len(raw), zlib.compress(raw)), (2, len(raw), lz4.block.compress(raw, store_size=False)),
                   (3, 0x40, b'kraken stream')])
        got = list(shader_split.gfpak_members(d, 'sample.gfpak'))
        self.assertEqual(got, [('#0', raw), ('#1', raw), ('#2', raw), ('#3', b'K' * 0x40)])
        self.assertEqual(self.calls, [(b'kraken stream', 0x40)])   # only the Oodle entry goes to the decoder

    def test_unknown_compression_stops(self):
        d = gfpak([(4, 8, b'????????')])
        with self.assertRaisesRegex(SystemExit, 'entry 0 has compression 4'):
            list(shader_split.gfpak_members(d, 'sample.gfpak'))


class GfpakFromCacheTests(unittest.TestCase):
    def test_an_oodle_entry_read_from_the_streams_decoded_before_the_split(self):   # issue #310: the Android build decodes them on the phone (scripts/android_oodle.py Cache)
        raw, kraken = b'BNSH' + bytes(60), b'\x8c\x06 kraken stream'
        d = gfpak([(3, len(raw), kraken), (3, 0x10, b'\x8c\x06 not decoded')])
        with tempfile.TemporaryDirectory() as c:
            Path(c, '1.pack').write_bytes(b'x' * 5 + raw)   # the format oodle_cached reads: decoded bytes back to back, a line per stream
            Path(c, '1.idx').write_text(f'{hashlib.blake2b(kraken, digest_size=16).hexdigest()}\t{len(raw)}\t5\n')
            with mock.patch.dict(os.environ, {'DM_OODLE_CACHE': c}), mock.patch.object(shader_split, '_CACHED', None):
                members = shader_split.gfpak_members(d, 'sample.gfpak')
                self.assertEqual(next(members), ('#0', raw))
                with self.assertRaisesRegex(SystemExit, 'not among the streams decoded before the split'): next(members)   # never zeros in a real split


if __name__ == '__main__':
    unittest.main()
