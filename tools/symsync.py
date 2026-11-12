#!/usr/bin/env python3
import argparse
import bisect
import difflib
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ctrproject import Demangle, LoadBinary, LoadProject, ProjectPath, QualifiedParts, ReadSplits, ReadSymbols, Symbol, WriteSymbols
from manual import SYMBOLS_PATH as MANUAL_PATH
ARM_NOP = 0xE1A00000
R_ARM_PC24 = 1
R_ARM_ABS32 = 2
R_ARM_THM_CALL = 10
R_ARM_CALL = 28
R_ARM_JUMP24 = 29
R_ARM_THM_JUMP24 = 30
CALL_RELOCS = {R_ARM_PC24, R_ARM_THM_CALL, R_ARM_CALL, R_ARM_JUMP24, R_ARM_THM_JUMP24}
FUZZY_MIN_SIZE = 0x10
FUZZY_MIN_RATIO = 0.7
FUZZY_MARGIN = 0.1
BASE_PREFIX = re.compile(r"^build/base/(?P<unit>.+)\.o$")

@dataclass
class Reloc:
    Offset: int
    Type: int
    Name: str
    Addend: int
    Defined: bool

@dataclass
class BaseFunction:
    Name: str
    Thumb: bool
    Size: int
    Code: bytes
    Relocs: list = field(default_factory=list)

def readBaseObject(path):
    from elftools.elf.elffile import ELFFile
    from elftools.elf.relocation import RelocationSection

    functions = []

    with open(path, "rb") as fh:
        elf = ELFFile(fh)
        table = elf.get_section_by_name(".symtab")
        if not table: return functions

        symbols = list(table.iter_symbols())
        relocsBySection = {}
        for section in elf.iter_sections():
            if not isinstance(section, RelocationSection): continue

            relocsBySection.setdefault(section["sh_info"], []).extend(section.iter_relocations())

        for sym in symbols:
            if sym["st_info"]["type"] != "STT_FUNC" or sym["st_shndx"] == "SHN_UNDEF" or sym["st_info"]["bind"] == "STB_LOCAL": continue

            index = sym["st_shndx"]
            data = elf.get_section(index).data()
            start = sym["st_value"] & ~1
            fn = BaseFunction(sym.name, bool(sym["st_value"] & 1), sym["st_size"], data[start:start + sym["st_size"]])
            for rel in relocsBySection.get(index, []):
                offset = rel["r_offset"] - start
                if offset < 0 or offset + 4 > len(data) - start: continue

                target = symbols[rel["r_info_sym"]]
                addend = int.from_bytes(data[rel["r_offset"]:rel["r_offset"] + 4], "little") if rel["r_info_type"] == R_ARM_ABS32 else 0
                fn.Relocs.append(Reloc(offset, rel["r_info_type"], target.name, addend, target["st_shndx"] != "SHN_UNDEF"))

            functions.append(fn)

    return functions

def armBranchTarget(word, addr):
    imm = word & 0xFFFFFF
    if imm & 0x800000: imm -= 0x1000000

    dest = addr + 8 + (imm << 2)
    return dest + 2 * ((word >> 24) & 1) if (word >> 28) == 0xF else dest

def thumbBranchTarget(high, low, addr):
    sign = (high >> 10) & 1
    imm = (sign << 24) | ((1 - (((low >> 13) & 1) ^ sign)) << 23) | ((1 - (((low >> 11) & 1) ^ sign)) << 22) | ((high & 0x3FF) << 12) | ((low & 0x7FF) << 1)
    if sign: imm -= 1 << 25

    dest = addr + 4 + imm
    return dest & ~3 if (low & 0x1000) == 0 else dest

def branchTarget(binary, addr, thumb):
    if not thumb: return armBranchTarget(binary.Word(addr), addr)

    raw = binary.Read(addr, 4)
    return thumbBranchTarget(int.from_bytes(raw[:2], "little"), int.from_bytes(raw[2:], "little"), addr)

def maskedCode(code, relocs):
    masked = bytearray(code)
    for rel in relocs:
        if rel.Type not in CALL_RELOCS or rel.Offset + 4 > len(masked): continue

        masked[rel.Offset:rel.Offset + 4] = b"\0\0\0\0"

    return bytes(masked)

class SymbolTable:
    def __init__(self, symbols):
        self.Symbols = symbols
        self.ByName = {s.Name: s for s in symbols}
        self.Functions = sorted((s for s in symbols if s.Kind == "function"), key=lambda s: s.Addr)
        self.FunctionStarts = [s.Addr for s in self.Functions]
        self.ByAddr = {}
        for sym in symbols:
            current = self.ByAddr.get(sym.Addr)
            if current is None or (sym.Kind == "function" and current.Kind != "function"): self.ByAddr[sym.Addr] = sym

    def FunctionsIn(self, start, end):
        return self.Functions[bisect.bisect_left(self.FunctionStarts, start):bisect.bisect_left(self.FunctionStarts, end)]

    def Rename(self, sym, name):
        self.ByName.pop(sym.Name, None)
        sym.Name = name
        self.ByName[name] = sym

    def Add(self, sym):
        self.Symbols.append(sym)
        self.ByName[sym.Name] = sym
        self.ByAddr.setdefault(sym.Addr, sym)

class Syncer:
    def __init__(self, binary, table, baseNames):
        self.Binary = binary
        self.Table = table
        self.BaseNames = baseNames
        self.Changes = []

    def renamable(self, sym):
        if sym.Name in self.BaseNames: return False

        return "lib" not in sym.Attrs and "linker" not in sym.Attrs

    def callDestination(self, fn, sym, rel):
        addr = sym.Addr + rel.Offset
        if not fn.Thumb and rel.Offset == fn.Size - 4 and self.Binary.Word(addr) == ARM_NOP: return sym.Addr + fn.Size

        return branchTarget(self.Binary, addr, fn.Thumb)

    def relocsAgree(self, fn, sym):
        for rel in fn.Relocs:
            known = self.Table.ByName.get(rel.Name)
            if not known: continue
            if rel.Type in CALL_RELOCS:
                if rel.Offset >= fn.Size: continue

                dest = self.Table.ByAddr.get(self.callDestination(fn, sym, rel))
                if dest and "linker" in dest.Attrs: continue
                if not dest or dest.Name != rel.Name: return False
                continue

            if rel.Type != R_ARM_ABS32: continue
            value = self.Binary.Word(sym.Addr + rel.Offset)

            if (value - rel.Addend) & ~1 != known.Addr: return False

        return True

    def exactCandidates(self, fn, pool):
        code = maskedCode(fn.Code, fn.Relocs)
        found = []
        for sym in pool:
            if sym.Thumb != fn.Thumb or sym.Size != fn.Size: continue
            if maskedCode(self.Binary.Read(sym.Addr, sym.Size), fn.Relocs) != code: continue
            if not self.relocsAgree(fn, sym): continue

            found.append(sym)

        return found

    def fuzzyCandidate(self, fn, pool):
        if fn.Size < FUZZY_MIN_SIZE: return None

        step = 2 if fn.Thumb else 4
        mine = [maskedCode(fn.Code, fn.Relocs)[i:i + step] for i in range(0, fn.Size, step)]
        scored = []
        for sym in pool:
            if sym.Thumb != fn.Thumb or not fn.Size // 2 <= sym.Size <= fn.Size * 2: continue

            theirs = maskedCode(self.Binary.Read(sym.Addr, sym.Size), fn.Relocs)
            words = [theirs[i:i + step] for i in range(0, sym.Size, step)]
            scored.append((difflib.SequenceMatcher(None, mine, words, autojunk=False).ratio(), sym))

        scored.sort(key=lambda item: -item[0])
        if not scored or scored[0][0] < FUZZY_MIN_RATIO: return None
        if len(scored) > 1 and scored[0][0] - scored[1][0] < FUZZY_MARGIN: return None

        return scored[0][1]

    def record(self, sym, name, reason):
        old = sym.Name
        self.Table.Rename(sym, name)
        self.Changes.append((sym, old, reason))

    def propagate(self, fn, sym):
        for rel in fn.Relocs:
            if rel.Defined or rel.Name in self.Table.ByName: continue
            if rel.Type in CALL_RELOCS:
                if rel.Offset >= fn.Size: continue

                addr = self.callDestination(fn, sym, rel) & ~1
            elif rel.Type == R_ARM_ABS32:
                addr = (self.Binary.Word(sym.Addr + rel.Offset) - rel.Addend) & 0xFFFFFFFF
            else:
                continue

            self.nameAddress(addr, rel.Name, rel.Type == R_ARM_ABS32)

    def nameAddress(self, addr, name, isData):
        seg = self.Binary.SegmentOf(addr & ~1)
        if not seg: return

        existing = self.Table.ByAddr.get(addr & ~1) if seg.Kind == "code" else self.Table.ByAddr.get(addr)
        if existing:
            if not self.renamable(existing): return

            self.record(existing, name, "referenced")
            return

        if seg.Kind == "code" or not isData: return

        sym = Symbol(name, seg.Name, addr, "object", 0, {})
        self.Table.Add(sym)
        self.Changes.append((sym, None, "referenced"))

    def keyMatches(self, pending, pool):
        names = [fn.Name for fn in pending] + [s.Name for s in pool]
        demangled = Demangle(names)
        keys = {}
        for sym in pool: keys.setdefault(tuple(QualifiedParts(sym.Name.split(".")[0], demangled.get(sym.Name))), []).append(sym)

        matched = {}
        for fn in pending:
            options = keys.get(tuple(QualifiedParts(fn.Name, demangled.get(fn.Name))), [])
            options = [s for s in options if s.Thumb == fn.Thumb]
            if len(options) == 1: matched[fn.Name] = options[0]

        return matched

    def SyncUnit(self, unit, functions):
        pool = []
        for section, start, end in unit.Ranges:
            if section == ".text": pool += [s for s in self.Table.FunctionsIn(start, end) if self.renamable(s)]

        pending = [fn for fn in functions if fn.Name not in self.Table.ByName]
        if not pending: return
        for fn in functions:
            if fn.Name in self.Table.ByName: continue

            candidates = self.exactCandidates(fn, pool)
            if len(candidates) > 1:
                print("  ambiguous %s: %s" % (fn.Name, ", ".join("%08X" % s.Addr for s in candidates)))
                continue

            if not candidates: continue

            pool.remove(candidates[0])
            self.record(candidates[0], fn.Name, "same code")
            self.propagate(fn, candidates[0])

        pending = [fn for fn in functions if fn.Name not in self.Table.ByName]
        for name, sym in self.keyMatches(pending, pool).items():
            pool.remove(sym)
            self.record(sym, name, "same name")

        for fn in functions:
            if fn.Name in self.Table.ByName: continue

            sym = self.fuzzyCandidate(fn, pool)

            if not sym: continue

            pool.remove(sym)
            self.record(sym, fn.Name, "similar code")

def symbolLine(sym):
    attrs = dict(sym.Attrs)
    if sym.Kind == "function": attrs.setdefault("mode", "thumb" if sym.Thumb else "arm")

    return Symbol(sym.Name, sym.Section, sym.Addr, sym.Kind, sym.Size, {k: v for k, v in attrs.items() if k == "mode"})

def updateManual(changes):
    names = {sym.Name for sym, _, _ in changes}
    addrs = {sym.Addr for sym, _, _ in changes}
    manual = [s for s in ReadSymbols(MANUAL_PATH) if s.Name not in names and s.Addr not in addrs]
    manual += [symbolLine(sym) for sym, _, _ in changes]
    WriteSymbols(manual, MANUAL_PATH)

def unitOf(path):
    rel = Path(path).resolve().relative_to(ProjectPath()).as_posix()
    match = BASE_PREFIX.match(rel)
    return match.group("unit") if match else None

def touchStamp(path, changed):
    stamp = Path(path)
    if stamp.exists() and not changed: return

    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("")

def sourceObjects(units):
    from configure import SourceRoots, findSource
    roots = SourceRoots(LoadProject())
    return [str(ProjectPath("build", "base", name + ".o")) for name in units if findSource(name, roots)]

def main():
    parser = argparse.ArgumentParser(description="Give original functions the names the compiled sources use: pairs each new source function with the original by code, then names the callees and globals it references")
    parser.add_argument("objects", nargs="*", help="base objects (default: those of every unit with a source)")
    parser.add_argument("--stamp", help="touch this file when config/symbols.txt changed (or when it is missing)")
    parser.add_argument("-n", "--dry-run", action="store_true")
    args = parser.parse_args()
    units = {u.Name: u for u in ReadSplits()}
    objects = args.objects or sourceObjects(units)
    parsed = []
    for path in objects:
        name = unitOf(path)
        if name in units and Path(path).exists(): parsed.append((units[name], readBaseObject(path)))

    symbols = ReadSymbols()
    table = SymbolTable(symbols)
    baseNames = {fn.Name for _, functions in parsed for fn in functions}
    syncer = Syncer(LoadBinary(LoadProject(), verify=False), table, baseNames)
    for unit, functions in parsed: syncer.SyncUnit(unit, functions)
    for sym, old, reason in syncer.Changes: print("  %08X %s -> %s (%s)" % (sym.Addr, old or "new", sym.Name, reason))

    changed = bool(syncer.Changes) and not args.dry_run
    if changed:
        WriteSymbols(symbols)
        updateManual(syncer.Changes)

    if args.stamp: touchStamp(args.stamp, changed)

if __name__ == "__main__":
    main()
