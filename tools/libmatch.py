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

def main():
    parser = argparse.ArgumentParser(description="Identify statically linked library functions by matching the compiler's own libraries (relocations masked)")
    parser.add_argument("--lib", action="append", help="library directory or archive (default: the compiler's lib/)")
    parser.add_argument("-n", "--dry-run", action="store_true")
    parser.add_argument("--archive-id", help="with --extract: the libid recorded in symbols.txt")
    parser.add_argument("--extract", nargs=3, metavar=("ARCHIVE", "MEMBER", "OUT"), help="write one library member object to OUT (used by the build for library units)")
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

        neutraliseRelocations(Path(out))
        return

    binary = LoadBinary(LoadProject())
    textSeg = next(s for s in binary.Segments if s.Name == ".text")
    paths = libraryPaths(args.lib)
    index = ProjectPath("build", "lib", "archives.json")
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({ArchiveId(path): str(path) for path in paths}, indent=1) + "\n")
    signatures, members, count = loadLibraries(paths)
    found = scan(binary, signatures, textSeg)
    siblings = addSiblings(found, members, binary, textSeg)
    symbols = ReadSymbols()
    renamed, added, absorbed = applyMatches(symbols, found)
    libraries = {}
    for _, (_, _, _, library, _, _) in found.items(): libraries[library] = libraries.get(library, 0) + 1

    print("%d library functions from %d archives; %d found in .text (%d placed beside a matched sibling) (%s); %d renamed, %d new starts, %d inner starts absorbed" % (count, len(paths), len(found), siblings, ", ".join("%s %d" % kv for kv in sorted(libraries.items())), renamed, added, absorbed))
    if not args.dry_run: WriteSymbols(symbols)

if __name__ == "__main__":
    main()