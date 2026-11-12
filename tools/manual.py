#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import LoadBinary, LoadProject, ProjectPath, ReadSplits, ReadSymbols, WriteSplits, WriteSymbols

SPLITS_PATH = ProjectPath("config", "splits.manual.txt")
SYMBOLS_PATH = ProjectPath("config", "symbols.manual.txt")
GENERATED_SPLITS = ProjectPath("config", "splits.txt")
GENERATED_SYMBOLS = ProjectPath("config", "symbols.txt")

def placeholder(sym):
    return "sub_%X" % sym.Addr if sym.Kind == "function" else "lbl_%08X" % sym.Addr

def ApplySymbols(symbols, manual):
    from ctrproject import Symbol
    byAddr = {}
    for sym in symbols: byAddr.setdefault((sym.Addr, sym.Kind), sym)

    byName = {sym.Name: sym for sym in symbols}
    changes = []
    for entry in manual:
        target = byAddr.get((entry.Addr, entry.Kind)) or next((s for s in symbols if s.Addr == entry.Addr), None)
        holder = byName.get(entry.Name)
        if holder is not None and holder is not target:
            byName.pop(holder.Name, None)
            holder.Name = placeholder(holder)
            byName[holder.Name] = holder
            changes.append("%08X %s -> %s (name moved to %08X)" % (holder.Addr, entry.Name, holder.Name, entry.Addr))

        if target is None:
            target = Symbol(entry.Name, entry.Section, entry.Addr, entry.Kind, entry.Size, dict(entry.Attrs))
            symbols.append(target)
            byAddr[(entry.Addr, entry.Kind)] = target
            byName[entry.Name] = target
            changes.append("%08X new %s" % (entry.Addr, entry.Name))
            continue

        before = (target.Name, target.Kind, target.Size, target.Attrs.get("mode"))
        byName.pop(target.Name, None)
        target.Name = entry.Name
        target.Kind = entry.Kind
        if entry.Size: target.Size = entry.Size
        if "mode" in entry.Attrs: target.Attrs["mode"] = entry.Attrs["mode"]

        byName[target.Name] = target
        after = (target.Name, target.Kind, target.Size, target.Attrs.get("mode"))
        fields = [label % value for label, old, value in zip(("name %s", "type %s", "size 0x%X", "mode %s"), before, after) if old != value]
        if fields: changes.append("%08X %s: %s" % (entry.Addr, before[0], ", ".join(fields)))

    return changes

def ApplySplits(units, symbols, manual):
    from split import FitToFunctions, applyManual
    funcs = [s for s in symbols if s.Kind == "function" and s.Section == ".text"]
    applied = FitToFunctions(applyManual(units, manual), funcs)
    names = [u.Name for u in applied]
    duplicates = sorted({n for n in names if names.count(n) > 1})
    if duplicates: sys.exit("manual splits produce duplicate units: %s" % ", ".join(duplicates[:10]))

    before = {u.Name: u.Ranges for u in units}
    changes = ["%s: %s" % (u.Name, ", ".join("%08X-%08X" % (s, e) for _, s, e in u.Ranges)) for u in applied if before.get(u.Name) != u.Ranges]
    changes += ["%s: removed" % name for name in sorted(set(before) - set(names))]

    return applied, changes

def Apply(verbose=False):
    symbols = ReadSymbols()
    symbolChanges = ApplySymbols(symbols, ReadSymbols(SYMBOLS_PATH))
    if symbolChanges: WriteSymbols(symbols)

    splitChanges = []
    if GENERATED_SPLITS.exists():
        units, splitChanges = ApplySplits(ReadSplits(), symbols, ReadSplits(SPLITS_PATH))
        if splitChanges:
            project = LoadProject()
            WriteSplits(units, LoadBinary(project, verify=False).Segments, ext=project.get("split", {}).get("unit_extension", ".cpp"))

    if symbolChanges or splitChanges or verbose: print("manual: %d symbol change(s) from %s, %d unit change(s) from %s" % (len(symbolChanges), SYMBOLS_PATH.name, len(splitChanges), SPLITS_PATH.name))

    if verbose:
        for line in symbolChanges + splitChanges: print("  " + line)

    return symbolChanges, splitChanges

def main():
    parser = argparse.ArgumentParser(description="Apply config/symbols.manual.txt and config/splits.manual.txt onto the generated config/symbols.txt and config/splits.txt")
    parser.parse_args()
    Apply(verbose=True)

if __name__ == "__main__":
    main()
