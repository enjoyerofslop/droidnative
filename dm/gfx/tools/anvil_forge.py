#!/usr/bin/env python3
"""Ubisoft's AnvilNext archives on the Switch (Assassin's Creed: The Rebel Collection, Black Flag and Rogue): the .forge files of version 27, their entries' LZO1X blocks, and a pure
LZO1X decoder for them. Used by shader_split.py (anvil_jobs, anvil_shaders), which scans each decoded block for BNSH as it scans a loose file.

· A .forge file is 'scimitar\\0', u32 version 27, i64 offset of the file data header {u32 entry count, u32, i64, u32, i64 -1, u32 most entries (5000), u32, i64 offset of the first table at
  +0x24}. A table is {u32 entry count, u32, i64 index offset, i64 next table (-1: none), u32 first, u32 last, i64 name table offset, i64 raw data offset}; an index entry is 20 bytes {i64 offset,
  u64 id, u32 size of the whole entry}, a name record 0xc0 bytes {u32 the entry's size, u64 its id, …, the NUL-terminated name at +0x2c}. The entries carry no header of their own.
· An entry is a small table, then its blocks, the last ending exactly at the entry's end: magic 33 AA FB 57 99 FA 04 10, u16 version 1, u8 type, u16 0x8000, u16 0x8000, u16 chunk count,
  {u16 raw size, u16 stored size} per chunk, then per chunk a u32 checksum (not Adler-32 or CRC-32 of either side, so not checked) and its stored bytes. A chunk whose stored size is its raw size
  is stored as it is; the others are LZO1X (type 0, the only type in the Rebel Collection's 28 files), which main also links as LZO2A and LZO1X_999. Two blocks to an entry, a table of its
  resources and their data; the data of the material and shader entries holds BNSH files, 7,575 in DataNX_Intro.forge (5,843 different shaders).
· The Ezio Collection's Scimitar files (versions 25 and 31) share the magic but not the layout (16-byte index entries, a 0x1b8-byte entry header, Oodle blocks): version() tells them apart,
  and entries() reads version 27 only."""
import struct

MAGIC, BLOCK, VERSION = b'scimitar\0', bytes.fromhex('33aafb5799fa0410'), 27
NAME_REC, NAME_AT, INDEX = 0xc0, 0x2c, 20
LZO1X = 0


def version(head):
    """The version of a .forge file from its first 13 bytes, or None when it is not one"""
    return struct.unpack_from('<I', head, 9)[0] if head[:len(MAGIC)] == MAGIC and len(head) >= 13 else None


def entries(d, what='forge'):
    """[(offset, size, name)] of a version 27 .forge file's entries, in index order"""
    if version(d[:13]) != VERSION: raise ValueError(f'{what}: not an AnvilNext forge of version {VERSION} (header {bytes(d[:13]).hex()})')
    hdr = struct.unpack_from('<q', d, 13)[0]
    if not 0x15 <= hdr <= len(d) - 0x2c: raise ValueError(f'{what}: the file data header at {hdr:#x} is outside the file')
    count, tab = struct.unpack_from('<I', d, hdr)[0], struct.unpack_from('<q', d, hdr + 0x24)[0]
    out, seen = [], set()
    while tab != -1:
        if tab in seen or not 0 <= tab <= len(d) - 0x30: raise ValueError(f'{what}: a table at {tab:#x} is outside the file or read twice')
        seen.add(tab)
        n, _, idx, nxt, _, _, names, _ = struct.unpack_from('<IIqqIIqq', d, tab)
        if not (0 <= idx and idx + INDEX * n <= len(d) and 0 <= names and names + NAME_REC * n <= len(d)): raise ValueError(f'{what}: the {n} entries of the table at {tab:#x} run past the end')
        for i in range(n):
            off, _, size = struct.unpack_from('<qQI', d, idx + INDEX * i)
            if not 0 <= off <= len(d) - size: raise ValueError(f'{what}: entry {len(out)} ({off:#x}, {size:#x} bytes) is outside the file')
            rec = d[names + NAME_REC * i + NAME_AT:names + NAME_REC * (i + 1)]
            out.append((off, size, bytes(rec).split(b'\0')[0].decode('latin1')))
        tab = nxt
    if len(out) != count: raise ValueError(f'{what}: {len(out)} entries in the tables, the header counts {count}')
    return out


def blocks(d, off, size, what='entry'):
    """The compressed blocks of the entry at off: [[(raw size, stored size, offset of the stored bytes)]]"""
    p, end, out = off, off + size, []
    while (p := d.find(BLOCK, p, end)) >= 0:
        if p + 17 > end: raise ValueError(f'{what}: a block header at {p - off:#x} runs past the entry')
        ver, typ, _, _, n = struct.unpack_from('<HBHHH', d, p + 8)
        if ver != 1 or typ != LZO1X: raise ValueError(f'{what}: a block at {p - off:#x} of version {ver}, type {typ} (known: version 1, type {LZO1X}, LZO1X)')
        q = p + 17 + 4 * n
        if q > end: raise ValueError(f'{what}: the chunk table of the block at {p - off:#x} runs past the entry')
        chunks = []
        for i in range(n):
            raw, stored = struct.unpack_from('<HH', d, p + 17 + 4 * i)
            if stored > raw or q + 4 + stored > end: raise ValueError(f'{what}: chunk {i} of the block at {p - off:#x} ({stored:#x} of {raw:#x} bytes) runs past the entry or is larger stored')
            chunks.append((raw, stored, q + 4)); q += 4 + stored
        out.append(chunks); p = q
    return out


def read(d, off, size, what='entry'):
    """The entry's blocks decoded, one bytes each"""
    out = []
    for chunks in blocks(d, off, size, what):
        b = bytearray()
        for raw, stored, at in chunks:
            c = bytes(d[at:at + stored])
            b += c if raw == stored else lzo1x(c, raw, what)
        out.append(bytes(b))
    return out


def lzo1x(src, n, what='LZO1X'):
    """LZO1X decoded to exactly n bytes, as lzo1x_decompress_safe: any read or copy outside the stream or the output, or an end at another length, is a ValueError naming what"""
    out, ip, state = bytearray(), 0, 0

    def take(t):   # t literal bytes
        nonlocal ip
        if ip + t > len(src) or len(out) + t > n: raise ValueError(f'{what}: a literal run of {t} bytes runs past the stream or the {n:#x}-byte output')
        out.extend(src[ip:ip + t]); ip += t

    def copy(dist, t):   # t bytes from dist back; an overlapping copy repeats its pattern
        s = len(out) - dist
        if s < 0 or len(out) + t > n: raise ValueError(f'{what}: a match of {t} bytes from {dist:#x} back at {len(out):#x} lies outside the {n:#x}-byte output')
        if dist >= t: out.extend(out[s:s + t])
        else: out.extend((out[s:] * (t // dist + 1))[:t])

    def byte():
        nonlocal ip
        if ip >= len(src): raise ValueError(f'{what}: the stream ends without its end marker ({len(out):#x} of {n:#x} bytes)')
        ip += 1
        return src[ip - 1]

    def run(t, extra):   # a length of 0 is extended by zero bytes of 255 each and a last byte
        if t: return t
        while (b := byte()) == 0: t += 255
        return t + extra + b

    if src and src[0] > 17:   # the stream opens with a literal run
        t = byte() - 17; take(t); state = 4 if t >= 4 else t
    while True:
        t = byte()
        if t >= 64:   # M2: 3 to 8 bytes, up to 0x800 back
            dist = 1 + ((t >> 2) & 7) + (byte() << 3); copy(dist, (t >> 5) + 1)
        elif t >= 32:   # M3: up to 0x4000 back
            ln = run(t & 31, 31); lo = byte(); dist = 1 + ((lo | byte() << 8) >> 2); copy(dist, ln + 2); t = lo
        elif t >= 16:   # M4: 0x4000 to 0xbfff back, or the end marker
            ln = run(t & 7, 7); lo = byte(); dist = ((t & 8) << 11) + ((lo | byte() << 8) >> 2)
            if dist == 0:
                if len(out) != n: raise ValueError(f'{what}: the end marker at {len(out):#x} bytes, not {n:#x}')
                return bytes(out)
            copy(dist + 0x4000, ln + 2); t = lo
        elif state == 0:   # a literal run of 4 or more
            take(run(t, 15) + 3); state = 4; continue
        elif state == 4:   # right after a literal run of 4 or more: a 3-byte match 0x801 to 0xc00 back
            copy(1 + 0x800 + (t >> 2) + (byte() << 2), 3)
        else:   # right after a match's own 1 to 3 literals: a 2-byte match up to 0x400 back
            copy(1 + (t >> 2) + (byte() << 2), 2)
        state = t & 3   # the match's last instruction byte says how many literals follow it
        if state: take(state)
