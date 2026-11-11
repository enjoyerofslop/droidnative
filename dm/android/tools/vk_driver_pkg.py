#!/usr/bin/env python3
# A Vulkan driver for DM_VK_DRIVER (dm/android/vk_driver.c), as the packing script and the desktop app take one: an AdrenoTools package (.adpkg.zip or .zip, a
# meta.json and the driver's .so at its root, as Yuzu- and Skyline-family emulators read them) or a bare .so. Nothing in it is run on the computer: read() checks
# the zip's entries and meta.json, then the library's ELF (an Android arm64 shared object that needs bionic's libraries, not glibc's, and exports HMI, the hardware
# module Android's Vulkan loader looks up and libadrenotools' hook relies on), so a Linux build, a desktop build or a file that isn't a driver is refused with why.
# Each driver goes onto the phone under a name of its own, <stem>-<first 8 hex digits of its SHA-256>.so (installed_name): builders name theirs alike
# (libvulkan_freedreno.so), and the host keeps a pipeline cache per driver file name and copies a file again only when its size or time changes.
#   python3 dm/android/tools/vk_driver_pkg.py <package or .so>     what the package holds, as JSON, or why it can't be used (exit 1)
import hashlib, io, json, posixpath, re, struct, sys, zipfile, zlib
from dataclasses import dataclass
from pathlib import Path

MAX_ENTRIES = 32           # a driver package holds a few files; more is something else
MAX_META = 64 << 10        # meta.json
MAX_LIB = 64 << 20         # the driver: Turnip builds are about 19 MB
META_FIELDS = ('schemaVersion', 'name', 'description', 'author', 'packageVersion', 'vendor', 'driverVersion', 'minApi', 'libraryName')
ENV_ALLOWED = ('TU_DEBUG', 'FD_DEV_FEATURES')   # Mesa's switches a catalog entry may set beside the driver (a 740 on One UI needs FD_DEV_FEATURES=enable_tp_ubwc_flag_hint=1)
GLIBC = ('libc.so.6', 'libm.so.6', 'libdl.so.2', 'libpthread.so.0', 'librt.so.1', 'ld-linux-aarch64.so.1')
REMOTE_DIR = 'vk_drivers'  # beside env.txt on the phone: DM_VK_DRIVER=vk_drivers/<name> in a game's defaults.txt (the host takes it relative to env.txt's folder)


class PackageError(Exception): pass


@dataclass
class Driver:
    data: bytes          # the .so
    library: str         # its name in the package (meta.json's libraryName), or the file's name
    meta: dict | None    # meta.json, when the package has one
    sha256: str          # of the .so, hex
    source: str          # the file it was read from

    @property
    def name(self): return installed_name(self.library, self.sha256)

    @property
    def min_api(self):   # the Android API level the builder says it needs (meta.json's minApi), or 0
        try: return int((self.meta or {}).get('minApi') or 0)
        except (TypeError, ValueError): return 0

    def describe(self):   # for a log line: name, version and builder, as meta.json gives them
        m = self.meta or {}
        bits = [str(m.get('name') or self.library)] + [str(m[k]) for k in ('driverVersion', 'author') if m.get(k)]
        return ' · '.join(bits)


def installed_name(library, sha256):
    stem = re.sub(r'[^A-Za-z0-9._-]+', '_', library[:-3] if library.lower().endswith('.so') else library).strip('._') or 'vk_driver'
    tag = sha256[:8].lower()
    return f'{stem}.so' if stem.endswith('-' + tag) else f'{stem}-{tag}.so'


def _plain_so(name):   # a file name at the zip's root that ends .so: no folder, no way out of it
    return bool(name) and '/' not in name and '\\' not in name and name not in ('.', '..') and name.lower().endswith('.so')


def read(path):
    """The driver in path (an AdrenoTools zip or a bare .so) → Driver, or PackageError saying why it can't be used"""
    p = Path(path)
    try:
        with p.open('rb') as f: raw_head = f.read(4)
    except OSError as e: raise PackageError(f'{p}: {e.strerror or e}') from e
    if raw_head == b'\x7fELF':
        if p.stat().st_size > MAX_LIB: raise PackageError(f'{p.name} is {p.stat().st_size >> 20} MB: a driver is at most {MAX_LIB >> 20} MB')
        data = p.read_bytes(); meta = None; library = p.name
    elif raw_head[:2] == b'PK':
        data, meta, library = _read_zip(p)
    else: raise PackageError(f'{p.name} is neither a driver package (.zip) nor a driver library (.so)')
    try: problems = check_elf(data)
    except (struct.error, IndexError, ValueError, OverflowError) as e:   # a header pointing past the file's end, say: what is malformed is said, not a traceback
        raise PackageError(f'{library}{"" if library == p.name else " in " + p.name} is a malformed ELF file ({e})') from e
    if problems: raise PackageError(f'{library}{"" if library == p.name else " in " + p.name} is not an Android arm64 Vulkan driver: ' + '; '.join(problems))
    return Driver(data, library, meta, hashlib.sha256(data).hexdigest(), str(p))


def _read_zip(p):
    try: return _read_zip_entries(p)
    except PackageError: raise
    # an encrypted entry (RuntimeError), a compression method zipfile lacks (NotImplementedError), a damaged stream: refused with why, never a traceback
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, zlib.error, EOFError, OSError, ValueError) as e: raise PackageError(f'{p.name} could not be read as a zip: {e}') from e


def _read_zip_entries(p):
    try: z = zipfile.ZipFile(p)
    except zipfile.BadZipFile as e: raise PackageError(f'{p.name} is not a readable zip: {e}') from e
    with z:
        infos = z.infolist()
        if len(infos) > MAX_ENTRIES: raise PackageError(f'{p.name} holds {len(infos)} files: a driver package holds at most {MAX_ENTRIES}')
        for i in infos:
            n = i.filename
            if n.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', n) or '..' in posixpath.normpath(n.replace('\\', '/')).split('/'):
                raise PackageError(f'{p.name} has a file outside the package: {n}')
        names = {i.filename: i for i in infos}
        meta = None
        if 'meta.json' in names:
            if names['meta.json'].file_size > MAX_META: raise PackageError(f"{p.name}'s meta.json is {names['meta.json'].file_size} bytes: at most {MAX_META}")
            try: meta = json.loads(z.read('meta.json').decode('utf-8-sig'))
            except (ValueError, UnicodeDecodeError) as e: raise PackageError(f"{p.name}'s meta.json is not JSON: {e}") from e
            if not isinstance(meta, dict): raise PackageError(f"{p.name}'s meta.json is not an object")
            missing = [k for k in META_FIELDS if k not in meta]
            if missing: raise PackageError(f"{p.name}'s meta.json lacks {', '.join(missing)}")
            if meta.get('schemaVersion') != 1: raise PackageError(f"{p.name}'s meta.json is schema {meta.get('schemaVersion')!r}: only 1 is known")
            library = meta.get('libraryName')
            if not isinstance(library, str) or not _plain_so(library): raise PackageError(f"{p.name}'s meta.json names {library!r} as its library: not a .so at the package's root")
            if library not in names: raise PackageError(f"{p.name}'s meta.json names {library}, which the package doesn't hold")
        else:   # no meta.json: a zip with one .so at its root
            sos = [n for n in names if _plain_so(n)]
            if len(sos) != 1: raise PackageError(f'{p.name} has no meta.json and {len(sos)} libraries at its root: which is the driver is not known')
            library = sos[0]
        if names[library].file_size > MAX_LIB: raise PackageError(f'{library} is {names[library].file_size >> 20} MB: a driver is at most {MAX_LIB >> 20} MB')
        with z.open(library) as f: data = f.read(MAX_LIB + 1)
        if len(data) > MAX_LIB: raise PackageError(f'{library} is over {MAX_LIB >> 20} MB')
        return data, meta, library


def check_elf(data):
    """Why data is not an Android arm64 Vulkan driver (an empty list: it is one). Read with struct, never loaded"""
    out = []
    if len(data) < 64 or data[:4] != b'\x7fELF': return ['not an ELF file']
    if data[4] != 2: out.append('not 64-bit')
    if data[5] != 1: return out + ['not little-endian']
    e_type, e_machine = struct.unpack_from('<HH', data, 16)
    if e_type != 3: out.append('not a shared object')
    if e_machine != 183: out.append(f'built for machine {e_machine}, not arm64 (183)')
    if out: return out
    e_phoff, e_shoff = struct.unpack_from('<QQ', data, 32)
    e_phentsize, e_phnum, e_shentsize, e_shnum, _ = struct.unpack_from('<HHHHH', data, 54)
    loads, dyn = [], None
    for i in range(e_phnum):
        o = e_phoff + i * e_phentsize
        if o + 56 > len(data): return ['its program headers run past its end']
        p_type, _, p_offset, p_vaddr, _, p_filesz, _ = struct.unpack_from('<IIQQQQQ', data, o)
        if p_type == 1: loads.append((p_vaddr, p_offset, p_filesz))
        elif p_type == 2: dyn = (p_offset, p_filesz)
    if not dyn: return ['no dynamic section (PT_DYNAMIC)']
    def at(vaddr):   # a virtual address → its file offset, through the PT_LOAD that holds it
        for v, o, n in loads:
            if v <= vaddr < v + n: return o + (vaddr - v)
        return None
    tags = {}; needed = []
    for o in range(dyn[0], min(dyn[0] + dyn[1], len(data) - 15), 16):
        d_tag, d_val = struct.unpack_from('<qQ', data, o)
        if d_tag == 0: break
        if d_tag == 1: needed.append(d_val)
        else: tags.setdefault(d_tag, d_val)
    strtab = at(tags[5]) if 5 in tags else None
    if strtab is None: return ['no dynamic string table']
    def cstr(off):
        end = data.find(b'\0', off)
        return data[off:end if end >= 0 else len(data)].decode('utf-8', 'replace')
    libs = [cstr(strtab + n) for n in needed]
    glibc = [n for n in libs if n in GLIBC]
    if glibc: out.append(f'needs glibc ({", ".join(glibc)}): a Linux build, not an Android one')
    elif 'libc.so' not in libs: out.append(f"doesn't need bionic's libc.so (it needs {', '.join(libs) or 'nothing'})")
    # the dynamic symbols: by the section headers when it has them, else DT_HASH's count, else the table up to the string table that follows it
    symtab = at(tags[6]) if 6 in tags else None; count = None; symstr = strtab
    for i in range(e_shnum if e_shoff and e_shentsize == 64 else 0):
        o = e_shoff + i * 64
        if o + 64 > len(data): break
        _, sh_type, _, _, sh_offset, sh_size, sh_link, _, _, sh_entsize = struct.unpack_from('<IIQQQQIIQQ', data, o)
        if sh_type == 11 and sh_entsize == 24:   # SHT_DYNSYM
            symtab, count = sh_offset, sh_size // 24
            lo = e_shoff + sh_link * 64
            if lo + 64 <= len(data): symstr = struct.unpack_from('<IIQQQQIIQQ', data, lo)[4]
            break
    h = at(tags[4]) if 4 in tags else None
    if count is None and h is not None and h + 8 <= len(data): count = struct.unpack_from('<II', data, h)[1]
    if count is None and symtab is not None and strtab > symtab: count = (strtab - symtab) // 24
    hmi = False
    if symtab is not None and count:
        for i in range(min(count, (len(data) - symtab) // 24)):
            st_name, st_info, _, st_shndx = struct.unpack_from('<IBBH', data, symtab + i * 24)
            if st_shndx and (st_info >> 4) in (1, 2) and cstr(symstr + st_name) == 'HMI': hmi = True; break
    if not hmi: out.append("doesn't export HMI, the hardware module Android's Vulkan loader looks up")
    return out


def parse_env(items):
    """--vk-driver-env K=V items → the lines, only Mesa's switches in ENV_ALLOWED"""
    out = []
    for it in items or ():
        k, sep, v = it.partition('=')
        if not sep or k not in ENV_ALLOWED or '\n' in v or '\r' in v: raise PackageError(f'--vk-driver-env {it!r}: only {", ".join(ENV_ALLOWED)} may be set beside a driver, as KEY=VALUE')
        out.append(f'{k}={v}')
    return out


def defaults_lines(path, sha256, env=()):
    """What a game's defaults.txt says for a driver at path (relative to env.txt's folder on the phone): the host checks the SHA-256 before it loads it"""
    return [f'DM_VK_DRIVER={path}', f'DM_VK_DRIVER_SHA256={sha256}', *env]


def is_driver_line(line):   # a defaults.txt line that names a driver, or one of the switches set beside it (replaced as one when the driver changes)
    return line.split('=', 1)[0].strip() in ('DM_VK_DRIVER', 'DM_VK_DRIVER_SHA256', *ENV_ALLOWED)


if __name__ == '__main__':
    if len(sys.argv) != 2: sys.exit(__doc__ or 'vk_driver_pkg.py <package or .so>')
    try: d = read(sys.argv[1])
    except PackageError as e: sys.exit(str(e))
    print(json.dumps({'library': d.library, 'installed_name': d.name, 'sha256': d.sha256, 'size': len(d.data), 'min_api': d.min_api, 'meta': d.meta}, indent=1))
