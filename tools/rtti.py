#!/usr/bin/env python3
import argparse
import bisect
import re
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import Demangle, LoadBinary, LoadProject, ReadSymbols, Symbol, WriteSymbols
from symbols import NameScore

TYPE_NAME = re.compile(rb"(?<![\x21-\x7e])(N?(?:St)?\d+[A-Za-z_][\x21-\x7e]*?)\x00")
MAX_SHARED_VTABLES = 24
MIN_OFFSET_TO_TOP = -0x100000

def scanTypeNames(binary):
    names = {}

    for seg in binary.Segments:
        if seg.Kind != "rodata" or seg.Offset is None: continue

        blob = binary.Data[seg.Offset:seg.Offset + seg.Size]
        for match in TYPE_NAME.finditer(blob):
            text = match.group(1).decode("ascii")
            if text[0] == "N" and not text.endswith("E"): continue

            names[seg.Addr + match.start(1)] = text

    demangled = Demangle("_ZTS" + t for t in names.values())
    valid = {}
    for addr, text in names.items():
        pretty = demangled.get("_ZTS" + text, "")
        if pretty.startswith("typeinfo name for "): valid[addr] = (text, pretty[len("typeinfo name for "):])

    return valid

def dataWords(binary):
    for seg in binary.Segments:
        if seg.Kind in ("code", "bss") or seg.Offset is None: continue

        count = seg.Size // 4
        yield seg, struct.unpack_from("<%dI" % count, binary.Data, seg.Offset)

def findTypeinfos(binary, names):
    typeinfos = {}
    for seg, words in dataWords(binary):
        for i in range(1, len(words)):
            name = names.get(words[i])

            if name and binary.InImage(words[i - 1]): typeinfos[seg.Addr + (i - 1) * 4] = name

    return typeinfos

def findVtables(binary, typeinfos, textSeg, names):
    vtables = []
    for seg, words in dataWords(binary):
        for i in range(1, len(words) - 1):
            if words[i] not in typeinfos: continue

            offsetToTop = words[i - 1] - (1 << 32) if words[i - 1] & 0x80000000 else words[i - 1]
            if not MIN_OFFSET_TO_TOP <= offsetToTop <= 0: continue
            if words[i - 1] in names or (seg.Addr + (i - 1) * 4) in typeinfos: continue

            slots = []
            j = i + 1
            while j < len(words) and textSeg.Addr <= words[j] < textSeg.End:
                slots.append(words[j])
                j += 1

            vtables.append((seg.Addr + (i - 1) * 4, typeinfos[words[i]], offsetToTop, slots))

    return vtables

def ownerVotes(vtables):
    votes = {}
    for _, (mangled, pretty), offsetToTop, slots in vtables:
        if offsetToTop != 0: continue
        for index, target in enumerate(slots):
            votes.setdefault(target, []).append((len(slots), mangled, pretty, index))

    return votes

def isPlaceholder(name):
    return NameScore(name) < 2 or "vfunc_" in name

def nestedPrefix(mangled):
    return mangled[1:-1] if mangled.startswith("N") else mangled

def main():
    parser = argparse.ArgumentParser(description="Recover classes from RTTI: vtable/typeinfo symbols and an owner for every virtual function")
    parser.add_argument("-n", "--dry-run", action="store_true")
    args = parser.parse_args()
    project = LoadProject()
    binary = LoadBinary(project)
    textSeg = next(s for s in binary.Segments if s.Name == ".text")
    symbols = ReadSymbols()
    names = scanTypeNames(binary)
    typeinfos = findTypeinfos(binary, names)
    vtables = findVtables(binary, typeinfos, textSeg, names)
    byAddr = {}
    for sym in symbols: byAddr.setdefault(sym.Addr, sym)

    taken = {s.Name for s in symbols}
    added = renamed = 0

    def addObject(addr, name, size):
        nonlocal added

        existing = byAddr.get(addr)
        if existing and existing.Kind == "object" and NameScore(existing.Name) >= NameScore(name):
            existing.Size = existing.Size or size
            return

        if name in taken: return

        if existing and existing.Kind in ("object", "label"):
            taken.discard(existing.Name)
            existing.Name, existing.Kind, existing.Size = name, "object", size
        else:
            seg = binary.SegmentOf(addr)
            sym = Symbol(name, seg.Name, addr, "object", size, {})
            symbols.append(sym)
            byAddr[addr] = sym

        taken.add(name)
        added += 1

    for addr, (mangled, _) in names.items(): addObject(addr, "_ZTS" + mangled, len(mangled) + 1)
    for addr, (mangled, _) in typeinfos.items(): addObject(addr, "_ZTI" + mangled, 8)

    primary = {}
    for addr, (mangled, _), offsetToTop, slots in vtables:
        if offsetToTop == 0: primary.setdefault(mangled, (addr, len(slots)))

    for mangled, (addr, count) in primary.items(): addObject(addr, "_ZTV" + mangled, 8 + 4 * count)
    for target, entries in ownerVotes(vtables).items():
        fn = byAddr.get(target & ~1)
        if not fn or fn.Kind != "function" or not isPlaceholder(fn.Name): continue
        if len({e[1] for e in entries}) > MAX_SHARED_VTABLES: continue

        _, mangled, pretty, index = min(entries)
        name = "_ZN%s%dvfunc_%dEv" % (nestedPrefix(mangled), len("vfunc_%d" % index), index)
        if name == fn.Name: continue
        if name in taken: name = "%s.%X" % (name, fn.Addr)
        if name == fn.Name: continue

        taken.discard(fn.Name)
        fn.Name = name
        taken.add(name)
        renamed += 1

    print("%d type names, %d typeinfos, %d vtables (%d primary), %d objects named, %d virtual functions given an owner" % (len(names), len(typeinfos), len(vtables), len(primary), added, renamed))

    if not args.dry_run: WriteSymbols(symbols)

if __name__ == "__main__":
    main()