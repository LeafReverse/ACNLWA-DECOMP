#!/usr/bin/env python3
import argparse
import bisect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from callgraph import buildGraph
from ctrproject import Demangle, LoadBinary, LoadProject, ProjectPath, QualifiedParts, ReadSplits, ReadSymbols, SanitizeComponent, Unit, WriteSplits
from symbols import NameScore
from manual import SPLITS_PATH as MANUAL_SPLITS

RUNTIME_PREFIXES = ("__aeabi_", "__ARM_", "__rt_", "__cxa_", "__cpp_", "__dynamic_cast", "__16", "__32", "_fp_")
AFFINITY_ROUNDS = 3
TRAILING_LIBRARY_OWNER = ("runtime", "armlib")
DEFAULT_LIBRARIES = {
    "nn": "nnsdk",
    "sead": "sead",
    "nw": "nw",
    "nw4c": "nw",
    "std": "runtime/std",
    "cxxabiv1": "runtime/cxxabiv1",
    "__cxxabiv1": "runtime/cxxabiv1",
    "runtime": "runtime",
}

def callGraph(binary, funcs):
    callees, callers = buildGraph(binary, funcs)
    neighbours = {a: callees[a] | callers[a] for a in callees}
    return neighbours, callers

def assignSoleCaller(funcs, owners, callers):
    assigned = 0
    changed = True
    while changed:
        changed = False
        for sym in funcs:
            if owners.get(sym.Addr) is not None or "linker" in sym.Attrs: continue

            sources = callers.get(sym.Addr)
            if not sources: continue

            classes = {owners.get(c) for c in sources}
            if len(classes) != 1 or None in classes: continue

            owners[sym.Addr] = next(iter(classes))
            assigned += 1
            changed = True

    return assigned

def pureVote(addr, neighbours, owners):
    named = {owners[n] for n in neighbours.get(addr, ()) if owners.get(n) is not None}
    return next(iter(named)) if len(named) == 1 else None

def assignByAffinity(funcs, owners, neighbours):
    assigned = 0
    i = 0
    count = len(funcs)
    while i < count:
        if owners[funcs[i].Addr] is not None:
            i += 1
            continue

        j = i
        while j < count and owners[funcs[j].Addr] is None: j += 1

        left = owners[funcs[i - 1].Addr] if i > 0 else None
        right = owners[funcs[j].Addr] if j < count else None
        votes = [pureVote(funcs[k].Addr, neighbours, owners) for k in range(i, j)]
        leftVotes = [1 if v is not None and v == left else 0 for v in votes]
        rightVotes = [1 if v is not None and v == right else 0 for v in votes]
        if not any(leftVotes) and not any(rightVotes):
            i = j
            continue

        best, bestScore = 0, -1
        prefix = 0
        suffix = sum(rightVotes)

        for k in range(j - i + 1):
            if prefix + suffix > bestScore and (left is not None or k == 0) and (right is not None or k == j - i): best, bestScore = k, prefix + suffix
            if k < j - i:
                prefix += leftVotes[k]
                suffix -= rightVotes[k]

        lastLeft = max((k for k in range(best) if leftVotes[k]), default=-1)
        firstRight = min((k for k in range(best, j - i) if rightVotes[k]), default=j - i)

        for k in range(lastLeft + 1): owners[funcs[i + k].Addr] = left
        for k in range(firstRight, j - i): owners[funcs[i + k].Addr] = right

        assigned += (lastLeft + 1) + (j - i - firstRight)
        i = j

    return assigned

def ownerOf(sym, demangled):
    if "lib" in sym.Attrs: return ("runtime",) + tuple(SanitizeComponent(p) for p in sym.Attrs["lib"].split("/"))
    if "linker" in sym.Attrs or NameScore(sym.Name) < 2: return None

    parts = QualifiedParts(sym.Name.split(".")[0], demangled.get(sym.Name))
    if len(parts) >= 2: return tuple(SanitizeComponent(p) for p in parts[:-1])
    if sym.Name.startswith(RUNTIME_PREFIXES): return ("runtime",)

    return None

def buildRuns(funcs, owners):
    runs = []
    for sym in funcs:
        owner = owners[sym.Addr]
        if runs and runs[-1][0] == owner:
            runs[-1][1].append(sym)
            continue

        runs.append([owner, [sym]])

    return runs

def absorbUnnamed(runs, maxAbsorb, fixed=frozenset()):
    changed = True

    while changed:
        changed = False
        for i, run in enumerate(runs):
            if run[0] is not None: continue

            prev = runs[i - 1][0] if i > 0 else None
            nxt = runs[i + 1][0] if i + 1 < len(runs) else None
            prev = None if prev in fixed else prev
            nxt = None if nxt in fixed else nxt
            if prev is not None and prev == nxt: run[0] = prev
            elif prev is not None and len(run[1]) <= maxAbsorb: run[0] = prev
            elif prev is None and nxt is not None and len(run[1]) <= maxAbsorb and i == 0: run[0] = nxt
            else: continue

            changed = True

        runs = coalesce(runs)

    return runs

def coalesce(runs):
    merged = []
    for owner, funcs in runs:
        if merged and merged[-1][0] == owner:
            merged[-1][1].extend(funcs)
            continue

        merged.append([owner, list(funcs)])

    return merged

def isPrefix(shorter, longer):
    return shorter is not None and longer is not None and len(shorter) < len(longer) and longer[:len(shorter)] == shorter

def mergeNested(runs, fixed=frozenset()):
    changed = True

    while changed:
        changed = False
        for i in range(len(runs) - 1):
            a, b = runs[i][0], runs[i + 1][0]
            if a in fixed or b in fixed: continue
            if isPrefix(a, b): runs[i + 1][0] = a
            elif isPrefix(b, a): runs[i][0] = b
            else: continue

            changed = True

        runs = coalesce(runs)

    return runs

def mergeSandwiched(runs, pinned=frozenset()):
    changed = True
    while changed:
        changed = False
        for i in range(1, len(runs) - 1):
            left, mid, right = runs[i - 1], runs[i], runs[i + 1]
            if left[0] is None or left[0] != right[0] or mid[0] == left[0]: continue
            if len(mid[1]) > len(left[1]) + len(right[1]): continue
            if any(f.Addr in pinned for f in mid[1]): continue

            mid[0] = left[0]
            changed = True

        runs = coalesce(runs)

    return runs

def demoteInlineCopies(runs, maxFuncs, pinned=frozenset()):
    largest = {}
    for owner, funcs in runs:
        if owner is not None: largest[owner] = max(largest.get(owner, 0), len(funcs))

    for run in runs:
        owner, funcs = run
        if owner is None or len(funcs) > maxFuncs or largest[owner] <= len(funcs): continue
        if any(f.Addr in pinned for f in funcs): continue

        run[0] = None

    return runs

def splitPoint(funcs, left, right, neighbours, ownerAt):
    leftVotes = [sum(1 for n in neighbours.get(f.Addr, ()) if ownerAt.get(n) == left) for f in funcs]
    rightVotes = [sum(1 for n in neighbours.get(f.Addr, ()) if ownerAt.get(n) == right) for f in funcs]
    if left is None: return 0
    if right is None: return len(funcs)

    best, bestScore = len(funcs), sum(leftVotes)
    prefix = 0
    suffix = sum(rightVotes)
    for k in range(len(funcs) + 1):
        if prefix + suffix > bestScore: best, bestScore = k, prefix + suffix
        if k < len(funcs):
            prefix += leftVotes[k]
            suffix -= rightVotes[k]

    return best

def mergeUnnamed(runs, neighbours, fixed=frozenset()):
    ownerAt = {sym.Addr: owner for owner, funcs in runs for sym in funcs}
    merged = []
    for index, (owner, funcs) in enumerate(runs):
        if owner is not None:
            merged.append([owner, funcs])
            continue

        left = merged[-1][0] if merged else None
        right = runs[index + 1][0] if index + 1 < len(runs) else None
        besideLibrary = left in fixed or right in fixed
        left = None if left in fixed else left
        right = None if right in fixed else right

        if besideLibrary and not any(ownerAt.get(n) in (left, right) for f in funcs for n in neighbours.get(f.Addr, ()) if ownerAt.get(n) is not None):
            merged.append([TRAILING_LIBRARY_OWNER, funcs])
            continue

        if left is None and right is None and (merged or index + 1 < len(runs)):
            merged.append([TRAILING_LIBRARY_OWNER, funcs])
            continue

        if left is None and right is None:
            merged.append([owner, funcs])
            continue

        if right is None and index == len(runs) - 1:
            merged.append([TRAILING_LIBRARY_OWNER, funcs])
            continue

        cut = splitPoint(funcs, left, right, neighbours, ownerAt)

        for part, partOwner in ((funcs[:cut], left), (funcs[cut:], right)):
            if not part: continue

            merged.append([partOwner, part])
            for sym in part: ownerAt[sym.Addr] = partOwner

    return coalesce(merged)

def ownerPath(owner, libraries, gameRoot):
    head = libraries.get(owner[0])
    if head is not None: return [p for p in head.split("/") if p] + list(owner[1:])

    return [gameRoot] + list(owner)

def autoPath(previous, following, gameRoot, start):
    leaf = "auto_%08X" % start
    before = previous[:-1] if previous else []
    after = following[:-1] if following else []
    common = []
    for a, b in zip(before, after):
        if a != b: break

        common.append(a)

    base = common or before[:1] or after[:1] or [gameRoot]
    return "/".join(base + [leaf])

def nameUnits(runs, libraries, gameRoot):
    paths = [ownerPath(owner, libraries, gameRoot) if owner is not None else None for owner, _ in runs]
    largest = {}
    for (owner, funcs), path in zip(runs, paths):
        if path is None: continue

        key = "/".join(path)
        largest[key] = max(largest.get(key, 0), funcs[-1].End - funcs[0].Addr)

    units = []
    used = set()
    lastNamed = None
    for index, ((owner, funcs), path) in enumerate(zip(runs, paths)):
        start, end = funcs[0].Addr, funcs[-1].End
        if path is None:
            following = next((p for p in paths[index + 1:] if p is not None), None)
            name = autoPath(lastNamed, following, gameRoot, start)
        else:
            key = "/".join(path)
            primary = end - start == largest[key] and key not in used
            name = key if primary else "%s/%s_%08X" % (key, path[-1], start)
            lastNamed = path

        used.add(name)
        units.append(Unit(name, [(".text", start, end)]))

    return units

def pieceName(name, start):
    parent, _, leaf = name.rpartition("/")
    base, _, suffix = leaf.rpartition("_")
    if base and len(suffix) == 8 and parent.endswith("/" + base): return "%s/%s_%08X" % (parent, base, start)

    return "%s/%s_%08X" % (name, leaf, start)

def subtractRanges(start, end, claimed):
    pieces = [(start, end)]
    for cStart, cEnd in claimed:
        if cEnd <= start or cStart >= end: continue

        nextPieces = []
        for pStart, pEnd in pieces:
            if cEnd <= pStart or cStart >= pEnd:
                nextPieces.append((pStart, pEnd))
                continue

            if pStart < cStart: nextPieces.append((pStart, cStart))
            if cEnd < pEnd: nextPieces.append((cEnd, pEnd))

        pieces = nextPieces

    return pieces

def applyManual(units, manual):
    if not manual: return units
    claimed = sorted((r[1], r[2]) for u in manual for r in u.Ranges if r[0] == ".text")
    taken = {u.Name for u in manual}
    result = []
    for unit in units:
        kept, pieces = [], []
        for section, start, end in unit.Ranges:
            if section != ".text":
                kept.append((section, start, end))
                continue

            for pStart, pEnd in subtractRanges(start, end, claimed):
                (kept if pStart == start and unit.Name not in taken else pieces).append((section, pStart, pEnd))

        if kept: result.append(Unit(unit.Name, kept))

        result += [Unit(pieceName(unit.Name, pStart), [(section, pStart, pEnd)]) for section, pStart, pEnd in pieces]

    result += manual
    result.sort(key=lambda u: u.Ranges[0][1])
    return result

def FitToFunctions(units, funcs):
    funcs = sorted(funcs, key=lambda s: s.Addr)
    starts = [f.Addr for f in funcs]

    def snap(edge):
        i = bisect.bisect_right(starts, edge) - 1
        return funcs[i].End if i >= 0 and funcs[i].Addr < edge < funcs[i].End else edge

    fitted = []
    for unit in units:
        ranges = [(section, snap(start), snap(end)) if section == ".text" else (section, start, end) for section, start, end in unit.Ranges]
        ranges = [r for r in ranges if r[1] < r[2]]
        if ranges: fitted.append(Unit(unit.Name, ranges))

    return fitted

def main():
    parser = argparse.ArgumentParser(description="Group functions into translation units (symbols.txt 2 splits.txt)")
    parser.add_argument("--stats", action="store_true")
    args = parser.parse_args()
    project = LoadProject()
    options = project.get("split", {})
    binary = LoadBinary(project)
    segments = binary.Segments
    funcs = [s for s in ReadSymbols() if s.Kind == "function" and s.Section == ".text"]
    if not funcs: sys.exit("no functions in config/symbols.txt: run tools/toolkit.py first!!!!!!!!!!!!!!!!!!!!!!!!!")

    demangled = Demangle(s.Name.split(".")[0] for s in funcs)
    demangled = {s.Name: demangled.get(s.Name.split(".")[0]) for s in funcs}
    owners = {s.Addr: ownerOf(s, demangled) for s in funcs}
    named = sum(1 for o in owners.values() if o is not None)
    neighbours, callers = callGraph(binary, funcs)
    unowned = {a for a, o in owners.items() if o is None}
    sole = assignSoleCaller(funcs, owners, callers) if options.get("sole_caller", True) else 0
    pinned = frozenset(a for a in unowned if owners[a] is not None) | frozenset(f.Addr for f in funcs if "lib" in f.Attrs)
    inferred = 0
    for _ in range(AFFINITY_ROUNDS):
        gained = assignByAffinity(funcs, owners, neighbours)
        inferred += gained
        if not gained: break

    runs = buildRuns(funcs, owners)
    libraryOwners = frozenset(o for a, o in owners.items() if o and o[0] == "runtime" and len(o) > 2)
    runs = absorbUnnamed(runs, int(options.get("absorb_unnamed_max", 4)), libraryOwners)
    runs = mergeNested(runs, libraryOwners)
    runs = mergeSandwiched(runs, pinned)
    runs = demoteInlineCopies(runs, int(options.get("inline_copy_max", 3)), pinned)
    runs = absorbUnnamed(coalesce(runs), int(options.get("absorb_unnamed_max", 4)), libraryOwners)
    runs = mergeSandwiched(runs, pinned)
    if options.get("merge_unnamed", True): runs = mergeSandwiched(mergeUnnamed(runs, neighbours, libraryOwners), pinned)

    units = nameUnits(runs, options.get("libraries", DEFAULT_LIBRARIES), options.get("game_root", "game"))
    units = applyManual(units, ReadSplits(MANUAL_SPLITS))
    units = FitToFunctions(units, funcs)
    WriteSplits(units, segments, ext=options.get("unit_extension", ".cpp"))
    auto = sum(1 for u in units if u.Name.rsplit("/", 1)[-1].startswith("auto_"))
    print("%d functions (%d named, %d owned by class, %d call affinity) %d units (%d named, %d auto)" % (len(funcs), named, sole, inferred, len(units), len(units) - auto, auto))
    if not args.stats: return

    top = {}
    for unit in units:
        key = "/".join(unit.Name.split("/")[:2])
        top[key] = top.get(key, 0) + 1

    for key, count in sorted(top.items(), key=lambda kv: -kv[1])[:40]: print("  %-32s %d" % (key, count))

if __name__ == "__main__":
    main()