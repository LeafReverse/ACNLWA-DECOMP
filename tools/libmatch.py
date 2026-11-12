#!/usr/bin/env python3
import argparse
import hashlib
import json
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import LoadBinary, LoadProject, ProjectPath, ReadSymbols, SanitizeComponent, Symbol, ToolPath, WriteSymbols
from symbols import NameScore

OBJDIFF_UNSUPPORTED_SECTIONS = [".ARM.attributes", ".ARM.exidx*", ".rel.ARM.exidx*", ".ARM.extab*", ".rel.ARM.extab*", ".debug_frame", ".rel.debug_frame"]
OBJDIFF_RELOCATIONS = {2, 10, 28, 29, 30}
BRANCH_RELOCATIONS = {10, 28, 29, 30}
R_ARM_REL32 = 3
MAX_SHRINK = 8
KEY_LENGTH = 8
MIN_LENGTH = 12
MIN_FIXED_BYTES = 16
SIBLING_MIN_LENGTH = 4
AR_MAGIC = b"!<arch>\n"

def neutraliseRelocations(path):
    import struct as layout
    from elftools.elf.elffile import ELFFile
    data = bytearray(path.read_bytes())
    with open(path, "rb") as fh:
        elf = ELFFile(fh)
        headerTable = elf["e_shoff"]
        headerSize = elf["e_shentsize"]
        sections = [(i, s["sh_offset"], s["sh_entsize"], s.num_relocations()) for i, s in enumerate(elf.iter_sections()) if s["sh_type"] == "SHT_REL"]

    for index, offset, entsize, count in sections:
        kept = [data[offset + n * entsize:offset + (n + 1) * entsize] for n in range(count) if data[offset + n * entsize + 4] in OBJDIFF_RELOCATIONS]
        data[offset:offset + len(kept) * entsize] = b"".join(kept)
        layout.pack_into("<I", data, headerTable + index * headerSize + 20, len(kept) * entsize)

    path.write_bytes(bytes(data))

def resolveRelativeWords(path, lib, archiveId):
    from elftools.elf.elffile import ELFFile
    data = bytearray(path.read_bytes())
    with open(path, "rb") as fh:
        elf = ELFFile(fh)
        relative = [s for s in elf.iter_sections() if s["sh_type"] == "SHT_REL" and any(r["r_info_type"] == R_ARM_REL32 for r in s.iter_relocations())]
        if not relative: return

        owners = {s.Name: s for s in ReadSymbols() if s.Kind == "function" and s.Attrs.get("lib") == lib and s.Attrs.get("libid", archiveId) == archiveId}
        if not owners: return

        table = elf.get_section_by_name(".symtab")
        placed = {}
        for sym in table.iter_symbols():
            owner = owners.get(sym.name)
            if owner is None or sym["st_info"]["type"] != "STT_FUNC" or not isinstance(sym["st_shndx"], int): continue

            placed.setdefault(sym["st_shndx"], []).append((sym["st_value"] & ~1, sym["st_size"], owner))

        binary = LoadBinary(LoadProject())
        patches = []
        implied = {}
        for section in relative:
            functions = placed.get(section["sh_info"])
            if not functions: continue

            base = elf.get_section(section["sh_info"])["sh_offset"]
            for reloc in section.iter_relocations():
                if reloc["r_info_type"] != R_ARM_REL32: continue

                offset = reloc["r_offset"]
                owner = next(((start, sym) for start, size, sym in functions if start <= offset < start + size), None)
                if owner is None: continue

                place = owner[1].Addr + offset - owner[0]
                segment = next((s for s in binary.Segments if s.Addr <= place < s.End), None)
                if segment is None: continue

                word = struct.unpack_from("<I", binary.Data, segment.Offset + place - segment.Addr)[0]
                addend = struct.unpack_from("<I", data, base + offset)[0]
                implied.setdefault(reloc["r_info_sym"], set()).add((word + place - addend) & 0xFFFFFFFF)
                patches.append((base + offset, word, reloc["r_info_sym"]))

    resolved = {key for key, targets in implied.items() if len(targets) == 1 and any(s.Addr <= next(iter(targets)) < s.End for s in binary.Segments)}
    for at, word, key in patches:
        if key in resolved: struct.pack_into("<I", data, at, word)

    path.write_bytes(bytes(data))

def archiveIndex():
    path = ProjectPath("build", "lib", "archives.json")
    return json.loads(path.read_text()) if path.exists() else {}

def FindArchiveMember(archive, member, archiveId=None):
    indexed = archiveIndex().get(archiveId) if archiveId else None
    candidates = [Path(indexed)] if indexed and Path(indexed).exists() else libraryPaths(None)
    for path in candidates:
        if path.stem != archive or (archiveId and ArchiveId(path) != archiveId): continue
        for name, blob in archiveMembers(path):
            if SanitizeComponent(name.rsplit(".", 1)[0]) == member: return blob

    return None

def archiveMembers(path):
    data = path.read_bytes()
    if not data.startswith(AR_MAGIC): return

    offset = len(AR_MAGIC)
    longNames = b""
    while offset + 60 <= len(data):
        header = data[offset:offset + 60]
        name = header[:16].decode("latin-1").rstrip()
        size = int(header[48:58].decode("latin-1").strip() or 0)
        body = data[offset + 60:offset + 60 + size]
        offset += 60 + size + (size & 1)
        if name == "//":
            longNames = body
            continue

        if name in ("/", "/SYM64/") or name.startswith("__.SYMDEF"): continue
        if name.startswith("/") and name[1:].isdigit():
            start = int(name[1:])
            name = longNames[start:longNames.index(b"/", start) if b"/" in longNames[start:] else None].decode("latin-1")

        yield name.rstrip("/"), body

def objectFunctions(blob, minLength=None, withPlacement=False):
    from io import BytesIO
    from elftools.elf.elffile import ELFFile
    if not blob.startswith(b"\x7fELF"): return

    elf = ELFFile(BytesIO(blob))
    table = elf.get_section_by_name(".symtab")
    if table is None: return

    sections = list(elf.iter_sections())
    masks = {}
    for section in sections:
        if section["sh_type"] not in ("SHT_REL", "SHT_RELA"): continue

        target = section["sh_info"]
        masks.setdefault(target, set()).update(r["r_offset"] for r in section.iter_relocations())

    bySection = {}
    for sym in table.iter_symbols():
        index = sym["st_shndx"]
        if not isinstance(index, int) or not sym.name or sym.name.startswith("$"): continue
        if sym["st_info"]["type"] not in ("STT_FUNC", "STT_NOTYPE"): continue

        section = sections[index]
        if not section["sh_flags"] & 4 or section["sh_type"] != "SHT_PROGBITS": continue

        bySection.setdefault(index, []).append(sym)

    for index, syms in bySection.items():
        section = sections[index]
        data = section.data()
        relocated = masks.get(index, set())
        syms.sort(key=lambda s: s["st_value"] & ~1)
        for i, sym in enumerate(syms):
            start = sym["st_value"] & ~1
            end = start + sym["st_size"] if sym["st_size"] else (syms[i + 1]["st_value"] & ~1 if i + 1 < len(syms) else len(data))
            end = min(end, len(data))
            if end - start < (MIN_LENGTH if minLength is None else minLength): continue

            mask = bytearray(b"\xff" * (end - start))
            for offset in relocated:
                for byte in range(offset, offset + 4):
                    if start <= byte < end: mask[byte - start] = 0

            if withPlacement: yield sym.name, bool(sym["st_value"] & 1), data[start:end], bytes(mask), index, start
            else: yield sym.name, bool(sym["st_value"] & 1), data[start:end], bytes(mask)

def ArchiveId(path):
    return hashlib.md5(path.read_bytes()).hexdigest()[:10]

def loadLibraries(paths):
    signatures = {}
    members = {}
    count = 0
    for path in paths:
        archiveId = ArchiveId(path)
        for member, blob in archiveMembers(path):
            functions = list(objectFunctions(blob, SIBLING_MIN_LENGTH, True) or ())
            members.setdefault((path.stem, member), (archiveId, functions))
            for name, thumb, code, mask, _, _ in functions:
                if len(code) < MIN_LENGTH or 0 in mask[:KEY_LENGTH]: continue

                signatures.setdefault(code[:KEY_LENGTH], []).append((name, thumb, code, mask, path.stem, member, archiveId))
                count += 1

    return signatures, members, count

def addSiblings(found, members, binary, textSeg):
    blob = binary.Data[textSeg.Offset:textSeg.Offset + textSeg.Size]
    added = 0
    queue = list(found.items())
    while queue:
        addr, (name, _, _, library, member, archiveId) = queue.pop()
        functions = members.get((library, member), (None, []))[1]
        anchor = next((f for f in functions if f[0] == name), None)
        if anchor is None: continue

        for sibling, thumb, code, mask, index, start in functions:
            if index != anchor[4] or sibling == name: continue

            predicted = addr - anchor[5] + start
            if predicted in found or not textSeg.Addr <= predicted < textSeg.End: continue
            if not matches(blob, predicted - textSeg.Addr, code, mask): continue

            found[predicted] = (sibling, thumb, len(code), library, member, archiveId)
            queue.append((predicted, found[predicted]))
            added += 1

    return added

def matches(data, offset, code, mask):
    if offset + len(code) > len(data): return False

    window = data[offset:offset + len(code)]
    return all(m == 0 or a == b for a, b, m in zip(window, code, mask))

def scan(binary, signatures, textSeg):
    blob = binary.Data[textSeg.Offset:textSeg.Offset + textSeg.Size]
    hits = {}
    for offset in range(0, len(blob) - KEY_LENGTH, 2):
        candidates = signatures.get(blob[offset:offset + KEY_LENGTH])
        if not candidates: continue

        for candidate in candidates:
            name, thumb, code, mask, library, member, archiveId = candidate
            if not thumb and offset & 2: continue
            if mask.count(0xFF) < MIN_FIXED_BYTES: continue
            if matches(blob, offset, code, mask): hits.setdefault((name, code, mask), []).append((offset, candidate))

    found = {}
    for (name, code, mask), places in hits.items():
        if len({offset for offset, _ in places}) != 1: continue

        offset, (name, thumb, code, mask, library, member, archiveId) = places[0]
        best = found.get(textSeg.Addr + offset)
        if best and best[2] >= len(code): continue

        found[textSeg.Addr + offset] = (name, thumb, len(code), library, member, archiveId)

    return found

def libraryPaths(arguments):
    if arguments: return [p for a in arguments for p in (sorted(Path(a).rglob("*.l")) + sorted(Path(a).rglob("*.a")) if Path(a).is_dir() else [Path(a)])]

    from compiler import DiscoverAll, Find
    project = LoadProject()
    wanted = project.get("library_compilers", "all")
    compilers = list(DiscoverAll().values()) if wanted == "all" else [c for c in (Find(name) for name in wanted) if c]
    paths = []
    seen = set()
    for compiler in sorted(compilers, key=lambda c: c.Name, reverse=True):
        if not compiler.LibDir.exists(): continue
        for path in sorted(compiler.LibDir.rglob("*.l")):
            key = (path.name, path.stat().st_size, hashlib.md5(path.read_bytes()).hexdigest())
            if key in seen: continue

            seen.add(key)
            paths.append(path)

    if not paths: sys.exit("no library directory: pass --lib <dir>, or install a compiler that ships lib/")

    return paths

def applyMatches(symbols, found):
    funcs = sorted((s for s in symbols if s.Kind == "function"), key=lambda s: s.Addr)
    starts = [s.Addr for s in funcs]
    byAddr = {s.Addr: s for s in funcs}
    taken = {s.Name for s in symbols}
    renamed = added = 0
    absorbed = set()
    import bisect
    for addr, (name, thumb, length, library, member, archiveId) in sorted(found.items()):
        lib = "%s/%s" % (library, SanitizeComponent(member.rsplit(".", 1)[0]))
        sym = byAddr.get(addr)
        if sym is None:
            index = bisect.bisect_right(starts, addr) - 1
            if index < 0: continue

            outer = funcs[index]
            if addr >= outer.End: continue

            sym = Symbol(name, outer.Section, addr, "function", outer.End - addr, {"mode": "thumb" if thumb else "arm"})
            outer.Size = addr - outer.Addr
            symbols.append(sym)
            funcs.insert(index + 1, sym)
            starts.insert(index + 1, addr)
            byAddr[addr] = sym
            added += 1

        sym.Attrs["lib"] = lib
        sym.Attrs["libid"] = archiveId
        index = bisect.bisect_right(starts, addr)
        while index < len(funcs) and funcs[index].Addr < addr + length and NameScore(funcs[index].Name) < 2 and "lib" not in funcs[index].Attrs:
            inner = funcs.pop(index)
            starts.pop(index)
            byAddr.pop(inner.Addr, None)
            sym.Size = inner.End - sym.Addr
            absorbed.add(id(inner))

        if sym.Name == name or name in taken: continue
        taken.discard(sym.Name)
        sym.Name = name
        taken.add(name)
        renamed += 1

    symbols[:] = [s for s in symbols if id(s) not in absorbed]
    return renamed, added, len(absorbed)

def branchTarget(binary, textSeg, addr, thumb):
    offset = textSeg.Offset + addr - textSeg.Addr
    if thumb:
        high, low = struct.unpack_from("<HH", binary.Data, offset)
        if high >> 11 != 0x1E or (low >> 11) not in (0x1F, 0x1D): return None

        sign = (high >> 10) & 1
        imm = (sign << 24) | ((1 - (((low >> 13) & 1) ^ sign)) << 23) | ((1 - (((low >> 11) & 1) ^ sign)) << 22) | ((high & 0x3FF) << 12) | ((low & 0x7FF) << 1)
        target = addr + 4 + imm - (sign << 25)
        return target & ~3 if (low >> 11) == 0x1D else target

    word = struct.unpack_from("<I", binary.Data, offset)[0]
    if (word >> 25) & 7 != 5: return None

    imm = word & 0xFFFFFF
    target = addr + 8 + ((imm - (1 << 24) if imm & 0x800000 else imm) << 2)
    return target + (((word >> 24) & 1) << 1) if word >> 28 == 0xF else target

def libraryCallees(binary, textSeg, sym, blob):
    from io import BytesIO
    from elftools.elf.elffile import ELFFile
    elf = ELFFile(BytesIO(blob))
    table = elf.get_section_by_name(".symtab")
    if table is None: return

    function = next((s for s in table.iter_symbols() if s.name == sym.Name and s["st_info"]["type"] == "STT_FUNC" and isinstance(s["st_shndx"], int)), None)
    if function is None: return

    start = function["st_value"] & ~1
    for section in elf.iter_sections():
        if section["sh_type"] != "SHT_REL" or section["sh_info"] != function["st_shndx"]: continue

        for reloc in section.iter_relocations():
            kind = reloc["r_info_type"]
            if kind not in BRANCH_RELOCATIONS or not start <= reloc["r_offset"] < start + function["st_size"]: continue

            callee = table.get_symbol(reloc["r_info_sym"])
            if not callee.name or callee["st_info"]["bind"] == "STB_LOCAL": continue

            target = branchTarget(binary, textSeg, sym.Addr + reloc["r_offset"] - start, sym.Thumb or kind == 10)
            if target is not None: yield target, callee.name

def NameCallees(symbols, binary, textSeg):
    byAddr = {s.Addr: s for s in symbols if s.Kind == "function"}
    taken = {s.Name for s in symbols}
    claims = {}
    blobs = {}
    for sym in symbols:
        lib = sym.Attrs.get("lib")
        if not lib or sym.Kind != "function": continue

        archive, member = lib.split("/", 1)
        key = (archive, member, sym.Attrs.get("libid"))
        if key not in blobs: blobs[key] = FindArchiveMember(*key)
        if blobs[key] is None: continue

        for target, name in libraryCallees(binary, textSeg, sym, blobs[key]):
            callee = byAddr.get(target)
            if callee is None or NameScore(callee.Name) >= 2: continue

            claims.setdefault(target, set()).add(name)

    owners = {}
    for target, names in claims.items():
        if len(names) == 1: owners.setdefault(next(iter(names)), []).append(target)

    renamed = 0
    for name, targets in owners.items():
        if len(targets) != 1 or name in taken: continue

        byAddr[targets[0]].Name = name
        taken.add(name)
        renamed += 1

    return renamed

def FitLibrarySizes(symbols, binary, textSeg):
    import bisect
    ordered = sorted((s for s in symbols if s.Section == ".text" and s.Kind in ("function", "label")), key=lambda s: s.Addr)
    starts = [s.Addr for s in ordered]
    blob = binary.Data[textSeg.Offset:textSeg.Offset + textSeg.Size]
    members = {}
    resized = []
    for sym in ordered:
        lib = sym.Attrs.get("lib")
        if not lib or sym.Kind != "function" or sym.Thumb: continue

        archive, member = lib.split("/", 1)
        key = (archive, member, sym.Attrs.get("libid"))
        if key not in members:
            found = FindArchiveMember(*key)
            members[key] = {name: (code, mask) for name, thumb, code, mask in objectFunctions(found, 4)} if found else {}

        code, mask = members[key].get(sym.Name, (b"", b""))
        if not code or len(code) == sym.Size or len(code) & 3 or len(code) + MAX_SHRINK < sym.Size: continue

        index = bisect.bisect_right(starts, sym.Addr)
        if index < len(starts) and sym.Addr + len(code) > starts[index]: continue
        if not matches(blob, sym.Addr - textSeg.Addr, code, mask): continue

        resized.append((sym.Name, sym.Addr, sym.Size, len(code)))
        sym.Size = len(code)

    return resized

def RefitSplits(symbols, binary):
    from split import FitToFunctions
    from ctrproject import ReadSplits, WriteSplits
    units = ReadSplits()
    if not units: return 0

    funcs = [s for s in symbols if s.Kind == "function" and s.Section == ".text"]
    fitted = FitToFunctions(units, funcs)
    names = [u.Name for u in fitted]
    if len(names) != len(set(names)): sys.exit("refit produced duplicate unit names, config/splits.txt left untouched")

    before = {u.Name: u.Ranges for u in units}
    changed = sum(1 for u in fitted for a, b in zip(before[u.Name], u.Ranges) if a != b) + len(units) - len(fitted)
    if not changed: return 0

    ext = LoadProject().get("split", {}).get("unit_extension", ".cpp")
    WriteSplits(fitted, binary.Segments, ext=ext)

    return changed

def main():
    parser = argparse.ArgumentParser(description="Identify statically linked library functions by matching the compiler's own libraries (relocations masked)")
    parser.add_argument("--lib", action="append", help="library directory or archive (default: the compiler's lib/)")
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("--archive-id", help="with --extract: the libid recorded in symbols.txt")
    parser.add_argument("--extract", nargs=3, metavar=("ARCHIVE", "MEMBER", "OUT"), help="write one library member object to OUT (used by the build for library units)")
    parser.add_argument("--refine", action="store_true", help="only name the callees and fit the sizes of already matched library functions")
    args = parser.parse_args()
    if args.extract:
        archive, member, out = args.extract
        blob = FindArchiveMember(archive, member, args.archive_id)
        if blob is None: sys.exit("%s(%s) not found in the library_compilers archives" % (archive, member))

        Path(out).parent.mkdir(parents=True, exist_ok=True)
        raw = Path(out + ".raw")
        raw.write_bytes(blob)
        strip = sum((["--remove-section", pattern] for pattern in OBJDIFF_UNSUPPORTED_SECTIONS), [])
        result = subprocess.run([str(ToolPath("arm-none-eabi", "objcopy"))] + strip + [str(raw), out], capture_output=True, text=True)
        raw.unlink()
        if result.returncode: sys.exit(result.stderr)

        resolveRelativeWords(Path(out), "%s/%s" % (archive, member), args.archive_id)
        neutraliseRelocations(Path(out))
        return

    binary = LoadBinary(LoadProject())
    textSeg = next(s for s in binary.Segments if s.Name == ".text")
    if args.refine:
        symbols = ReadSymbols()
        named = NameCallees(symbols, binary, textSeg)
        resized = FitLibrarySizes(symbols, binary, textSeg)
        print("%d library callees named, %d library functions resized" % (named, len(resized)))
        for name, addr, old, new in resized: print("  %08X %-40s 0x%X -> 0x%X" % (addr, name, old, new))
        if args.dry_run: return

        WriteSymbols(symbols)
        refitted = RefitSplits(symbols, binary)
        if refitted: print("%d unit ranges refitted in config/splits.txt" % refitted)

        return

    paths = libraryPaths(args.lib)
    index = ProjectPath("build", "lib", "archives.json")
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({ArchiveId(path): str(path) for path in paths}, indent=1) + "\n")
    signatures, members, count = loadLibraries(paths)
    found = scan(binary, signatures, textSeg)
    siblings = addSiblings(found, members, binary, textSeg)
    symbols = ReadSymbols()
    renamed, added, absorbed = applyMatches(symbols, found)
    named = NameCallees(symbols, binary, textSeg)
    resized = FitLibrarySizes(symbols, binary, textSeg)
    libraries = {}
    for _, (_, _, _, library, _, _) in found.items(): libraries[library] = libraries.get(library, 0) + 1

    print("%d library functions from %d archives; %d found in .text (%d placed beside a matched sibling) (%s); %d renamed, %d new starts, %d inner starts absorbed, %d callees named, %d sizes fitted" % (count, len(paths), len(found), siblings, ", ".join("%s %d" % kv for kv in sorted(libraries.items())), renamed, added, absorbed, named, len(resized)))
    if not args.dry_run: WriteSymbols(symbols)

if __name__ == "__main__":
    main()