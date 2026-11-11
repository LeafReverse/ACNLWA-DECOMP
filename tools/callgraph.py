#!/usr/bin/env python3
import argparse
import bisect
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asmgen import ARM_NOP, CallEdges
from symbols import VeneerTarget
from ctrproject import Demangle, LoadBinary, LoadProject, ProjectPath, ReadSplits, ReadSymbols

def buildGraph(binary, funcs):
    veneers = {s.Addr: VeneerTarget(binary, s) for s in funcs if "linker" in s.Attrs}
    funcs = [s for s in funcs if s.Addr not in veneers]
    starts = {s.Addr for s in funcs}
    callees = {a: set() for a in starts}
    for caller, target, _ in CallEdges(binary, funcs):
        target = veneers.get(target, target)
        if target != caller and target in starts: callees[caller].add(target)

    for sym in funcs:
        if sym.Thumb or sym.Size < 4 or sym.End not in starts: continue
        if binary.Word(sym.End - 4) == ARM_NOP: callees[sym.Addr].add(sym.End)

    callers = {a: set() for a in starts}
    for caller, targets in callees.items():
        for target in targets: callers[target].add(caller)

    return callees, callers

def stronglyConnected(nodes, edges):
    index = {}
    low = {}
    onStack = set()
    stack = []
    component = {}
    counter = 0
    count = 0
    for root in nodes:
        if root in index: continue

        work = [(root, iter(edges[root]))]
        index[root] = low[root] = counter
        counter += 1
        stack.append(root)
        onStack.add(root)
        while work:
            node, children = work[-1]
            advanced = False
            for child in children:
                if child not in index:
                    index[child] = low[child] = counter
                    counter += 1
                    stack.append(child)
                    onStack.add(child)
                    work.append((child, iter(edges[child])))
                    advanced = True
                    break

                if child in onStack: low[node] = min(low[node], index[child])

            if advanced: continue

            work.pop()
            if work: low[work[-1][0]] = min(low[work[-1][0]], low[node])
            if low[node] != index[node]: continue
            while True:
                member = stack.pop()
                onStack.discard(member)
                component[member] = count
                if member == node: break

            count += 1

    return component, count

def Heights(callees):
    component, count = stronglyConnected(list(callees), callees)
    members = [[] for _ in range(count)]
    for node, comp in component.items(): members[comp].append(node)

    height = [0] * count
    for comp in range(count):
        best = -1
        for node in members[comp]:
            for child in callees[node]:
                if component[child] != comp: best = max(best, height[component[child]])

        height[comp] = best + 1

    return {node: height[component[node]] for node in callees}, component

def Depths(callees, callers, component, entry):
    count = max(component.values()) + 1 if component else 0
    members = [[] for _ in range(count)]
    for node, comp in component.items(): members[comp].append(node)

    depth = [-1] * count
    for comp in range(count - 1, -1, -1):
        parents = [component[p] for n in members[comp] for p in callers[n] if component[p] != comp]
        isRoot = not parents or entry in members[comp]
        depth[comp] = 0 if isRoot else max(depth[p] for p in parents) + 1

    return {node: depth[component[node]] for node in callees}

def deepestChain(start, callees, heights):
    chain = [start]
    seen = {start}
    while True:
        options = [c for c in callees[chain[-1]] if c not in seen]
        if not options: return chain

        nxt = max(options, key=lambda c: (heights[c], -c))
        chain.append(nxt)
        seen.add(nxt)

def unitIndex():
    ranges = sorted((start, end, unit.Name) for unit in ReadSplits() for _, start, end in unit.Ranges)
    starts = [r[0] for r in ranges]

    def find(addr):
        i = bisect.bisect_right(starts, addr) - 1
        return ranges[i][2] if i >= 0 and addr < ranges[i][1] else "?"

    return find

def matchTable():
    path = ProjectPath("build", "report.json")
    if not path.exists(): return {}

    table = {}
    for unit in json.loads(path.read_text()).get("units", []):
        for fn in unit.get("functions", []):
            if "fuzzy_match_percent" in fn: table[fn["name"]] = fn["fuzzy_match_percent"]

    return table

def main():
    parser = argparse.ArgumentParser(description="Call-graph depth of every function")
    parser.add_argument("-p", "--prefix", default="", help="only functions in units under this path, e.g. game/ or nnsdk/os")
    parser.add_argument("-s", "--sort", choices=["height", "depth", "leaves"], default="height")
    parser.add_argument("-n", "--count", type=int, default=40)
    parser.add_argument("--todo", action="store_true", help="hide functions already at 100%%")
    parser.add_argument("--chain", help="print the deepest call chain below this function (name or 0xADDR)")
    parser.add_argument("--json", help="write every function's height/depth/unit to this file")
    args = parser.parse_args()
    project = LoadProject()
    binary = LoadBinary(project)
    funcs = [s for s in ReadSymbols() if s.Kind == "function" and s.Section == ".text"]
    allFuncs = funcs
    funcs = [s for s in funcs if "linker" not in s.Attrs]
    byAddr = {s.Addr: s for s in funcs}
    byName = {s.Name: s for s in funcs}
    callees, callers = buildGraph(binary, allFuncs)
    heights, component = Heights(callees)
    entry = int(project.get("entry", "0x100000"), 0)
    depths = Depths(callees, callers, component, entry)
    unitOf = unitIndex()
    matched = matchTable()
    pretty = Demangle(s.Name.split(".")[0] for s in funcs)
    label = lambda s: pretty.get(s.Name.split(".")[0], s.Name)

    if args.chain:
        sym = byAddr.get(int(args.chain, 16)) if args.chain.lower().startswith("0x") else byName.get(args.chain)
        if not sym: sys.exit("no function %s" % args.chain)
        for level, addr in enumerate(deepestChain(sym.Addr, callees, heights)):
            fn = byAddr[addr]
            print("%s%08X  h%-3d %-40s %s" % ("  " * level, addr, heights[addr], unitOf(addr), label(fn)))

        return

    if args.json:
        rows = [{"name": s.Name, "addr": "0x%08X" % s.Addr, "unit": unitOf(s.Addr), "height": heights[s.Addr], "depth": depths[s.Addr], "callees": len(callees[s.Addr]), "callers": len(callers[s.Addr])} for s in funcs]
        Path(args.json).write_text(json.dumps(rows, indent=1) + "\n")

    rows = [s for s in funcs if unitOf(s.Addr).startswith(args.prefix)]
    if args.todo: rows = [s for s in rows if matched.get(s.Name, 0) < 100]
    if args.sort == "leaves": rows = sorted((s for s in rows if heights[s.Addr] == 0), key=lambda s: (-len(callers[s.Addr]), s.Size))
    elif args.sort == "depth": rows = sorted(rows, key=lambda s: (-depths[s.Addr], s.Addr))
    else: rows = sorted(rows, key=lambda s: (-heights[s.Addr], s.Addr))

    print("%-10s %6s %6s %5s %5s %6s  %-40s %s" % ("addr", "height", "depth", "calls", "by", "size", "unit", "function"))
    for s in rows[:args.count]:
        score = matched.get(s.Name)
        name = label(s) + ("  [%.0f%%]" % score if score is not None else "")
        print("%08X   %6d %6d %5d %5d %6d  %-40s %s" % (s.Addr, heights[s.Addr], depths[s.Addr], len(callees[s.Addr]), len(callers[s.Addr]), s.Size, unitOf(s.Addr)[:40], name))

    leaves = sum(1 for s in funcs if heights[s.Addr] == 0)
    print("%d functions, %d leaves, deepest height %d, deepest depth %d" % (len(funcs), leaves, max(heights.values()), max(depths.values())))

if __name__ == "__main__":
    main()
