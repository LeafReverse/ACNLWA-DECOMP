#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import LoadBinary, LoadProject, LoadSegments, ParseInt, PlaceholderName, ReadSymbols, SanitizeComponent, Symbol, WriteSymbols

MAP_LINE = re.compile(r"^\s*(?:[0-9A-Fa-f]{4}:)?([0-9A-Fa-f]{6,16})\s+(\S.*?)\s*$")
AUTO_NAME = re.compile(r"^(sub|nullsub|j_sub|loc|locret|unk|off|dword|qword|word|byte|flt|dbl|stru|asc|jpt|def|FUN|fn|LAB|DAT|PTR|lbl|data|unknown_libname)_[0-9A-Fa-f_]*\d*$|^a[A-Z0-9]")
THUMB_TO_ARM_VENEER = bytes([0x78, 0x47, 0xC0, 0x46])
LONG_BRANCH_VENEER = 0xE51FF004
VALID_SYMBOL = re.compile(r"^[A-Za-z_.$][0-9A-Za-z_.$]*$")


def NameScore(name):
    if name.startswith("_Z") and "Ev." not in name: return 4
    if name.startswith("_Z"): return 3
    if AUTO_NAME.match(name): return 0

    return 2 if VALID_SYMBOL.match(name) else 1

def readIdaMap(path):
    inPublics = False
    for line in Path(path).read_text(errors="replace").splitlines():
        if "Publics by Value" in line or "Recovered" in line:
            inPublics = True
            continue

        if not inPublics: continue

        match = MAP_LINE.match(line)
        if match: yield int(match.group(1), 16), match.group(2), None

def readUnitsJson(path):
    with open(path) as fh:
        data = json.load(fh)

    for unit in data.get("units", []):
        for fn in unit.get("functions", []):
            yield ParseInt(fn["addr"]), fn["symbol"], int(fn.get("size", 0))

    for ext in data.get("externs", []):
        yield ParseInt(ext["addr"]), ext["symbol"], None

def readSymbolsTxt(path):
    for sym in ReadSymbols(path):
        yield sym.Addr, sym.Name, sym.Size or None

READERS = {"ida-map": readIdaMap, "units-json": readUnitsJson, "symbols": readSymbolsTxt}



def ToSymbolName(raw):
    name = raw.strip()
    if name.startswith("j_") and "::" in name: name = name[2:]
    if VALID_SYMBOL.match(name): return name
    if "::" in name: return PlaceholderName(re.sub(r"\(.*$", "", name))

    return SanitizeComponent(name)

def uniqueName(name, addr, taken):
    owner = taken.get(name)
    if owner is None or owner == addr: return name

    return "%s.%X" % (name, addr)

def importNames(symbols, entries, segments, overwrite):
    byAddr = {}
    for sym in symbols:
        if sym.Kind in ("function", "label") or sym.Addr not in byAddr: byAddr[sym.Addr] = sym

    taken = {s.Name: s.Addr for s in symbols}
    added = renamed = skipped = 0
    for addr, raw, size in entries:
        seg = next((s for s in segments if s.Addr <= addr < s.End), None)
        if not seg:
            skipped += 1
            continue

        name = ToSymbolName(raw)
        sym = byAddr.get(addr)
        if sym and (overwrite or NameScore(name) > NameScore(sym.Name)):
            taken.pop(sym.Name, None)
            sym.Name = uniqueName(name, addr, taken)
            taken[sym.Name] = addr
            renamed += 1
            continue

        if sym:
            skipped += 1
            continue

        kind = "label" if seg.Kind == "code" else "object"
        sym = Symbol(uniqueName(name, addr, taken), seg.Name, addr, kind, 0, {})
        symbols.append(sym)
        byAddr[addr] = sym
        taken[sym.Name] = addr
        added += 1

    return added, renamed, skipped

def IsVeneer(binary, sym):
    if sym.Thumb:
        head = binary.Read(sym.Addr, 8)
        return len(head) == 8 and head[:4] == THUMB_TO_ARM_VENEER and head[7] == 0xEA

    first, second = binary.Word(sym.Addr), binary.Word(sym.Addr + 4)
    if first == LONG_BRANCH_VENEER: return True

    return first & 0xFFFFF000 == 0xE28FC000 and second == 0xE12FFF1C

def VeneerTarget(binary, sym):
    if sym.Thumb:
        word = binary.Word(sym.Addr + 4)
        offset = (word & 0xFFFFFF) - (1 << 24 if word & 0x800000 else 0)
        return sym.Addr + 4 + 8 + (offset << 2)

    first = binary.Word(sym.Addr)
    if first == LONG_BRANCH_VENEER: return binary.Word(sym.Addr + 4) & ~1

    return (sym.Addr + 8 + (first & 0xFF)) & ~1

def MarkVeneers(binary, symbols):
    taken = {s.Name for s in symbols}
    marked = 0
    for sym in symbols:
        if sym.Kind != "function" or not IsVeneer(binary, sym): continue

        sym.Attrs["linker"] = "veneer"
        marked += 1
        if NameScore(sym.Name) >= 2 and not sym.Name.startswith("__ARM_veneer"): continue

        name = "__ARM_veneer_%08X" % sym.Addr
        if name in taken and name != sym.Name: continue

        taken.discard(sym.Name)
        sym.Name = name
        taken.add(name)

    return marked

def main():
    parser = argparse.ArgumentParser(description="Merge names from other tools into config/symbols.txt")
    sub = parser.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="import names keyed by address")
    imp.add_argument("format", choices=sorted(READERS))
    imp.add_argument("paths", nargs="+")
    imp.add_argument("--overwrite", action="store_true", help="replace names even when the current one looks better")
    sub.add_parser("stats")
    sub.add_parser("veneers", help="mark linker-generated interworking veneers (excluded from units and progress)")
    args = parser.parse_args()
    symbols = ReadSymbols()
    if args.cmd == "veneers":
        print("%d veneers marked" % MarkVeneers(LoadBinary(LoadProject()), symbols))
        WriteSymbols(symbols)
        return
    if args.cmd == "stats":
        funcs = [s for s in symbols if s.Kind == "function"]
        named = sum(1 for s in funcs if NameScore(s.Name) >= 2)
        mangled = sum(1 for s in funcs if s.Name.startswith("_Z") and "." not in s.Name and not s.Name.endswith("Ev"))
        print("functions %d   named %d   mangled with a signature %d   other symbols %d" % (len(funcs), named, mangled, len(symbols) - len(funcs)))
        return

    segments = LoadSegments(LoadProject())
    for path in args.paths:
        added, renamed, skipped = importNames(symbols, READERS[args.format](path), segments, args.overwrite)
        print("%s: %d renamed, %d new, %d skipped" % (path, renamed, added, skipped))

    WriteSymbols(symbols)

if __name__ == "__main__":
    main()