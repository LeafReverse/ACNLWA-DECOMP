#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import Demangle, ProjectPath, QualifiedParts, ReadSplits, ReadSymbols, WriteSymbols

def baseFunctions(objPath):
    from elftools.elf.elffile import ELFFile
    with open(objPath, "rb") as fh:
        elf = ELFFile(fh)
        table = elf.get_section_by_name(".symtab")
        if not table: return []

        return [s.name for s in table.iter_symbols() if s["st_info"]["type"] == "STT_FUNC" and s["st_shndx"] != "SHN_UNDEF" and s["st_info"]["bind"] != "STB_LOCAL"]

def keyOf(name, demangled):
    return tuple(QualifiedParts(name.split(".")[0], demangled.get(name.split(".")[0])))

def main():
    parser = argparse.ArgumentParser(description="Rename placeholder symbols to the real mangled names found in compiled base objects")
    parser.add_argument("units", nargs="*", help="unit names (default: every unit with a base object)")
    parser.add_argument("-n", "--dry-run", action="store_true")
    args = parser.parse_args()
    symbols = ReadSymbols()
    funcs = [s for s in symbols if s.Kind == "function"]
    taken = {s.Name for s in symbols}
    renamed = ambiguous = 0

    for unit in ReadSplits():
        if args.units and unit.Name not in args.units: continue

        obj = ProjectPath("build", "base", unit.Name + ".o")
        if not obj.exists(): continue

        real = [n for n in baseFunctions(obj) if n not in taken]
        members = [s for s in funcs if any(start <= s.Addr < end for _, start, end in unit.Ranges)]
        demangled = Demangle([n.split(".")[0] for n in real] + [s.Name.split(".")[0] for s in members])
        candidates = {}
        for name in real: candidates.setdefault(keyOf(name, demangled), []).append(name)
        for sym in members:
            options = candidates.get(keyOf(sym.Name, demangled), [])
            if len(options) > 1:
                ambiguous += 1
                print("  ambiguous %08X %s -> %s" % (sym.Addr, sym.Name, ", ".join(options)))
                continue

            if not options: continue

            print("  %08X %s -> %s" % (sym.Addr, sym.Name, options[0]))
            taken.discard(sym.Name)
            sym.Name = options[0]
            taken.add(sym.Name)
            candidates.pop(keyOf(sym.Name, demangled), None)
            renamed += 1

    if not args.dry_run and renamed: WriteSymbols(symbols)

    print("%d renamed, %d ambiguous (rename those by hand in config/symbols.txt)" % (renamed, ambiguous))

if __name__ == "__main__":
    main()