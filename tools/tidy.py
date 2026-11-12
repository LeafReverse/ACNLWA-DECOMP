#!/usr/bin/env python3
import argparse
import bisect
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from asmgen import ARM_NOP, CallEdges, PoolRefs, armBranch, armPoolRefs
from ctrproject import LoadBinary, LoadProject, ReadSymbols, Symbol, WriteSymbols
from symbols import MarkVeneers, NameScore

def DropImpossibleStarts(symbols):
    funcs = sorted((s for s in symbols if s.Kind == "function"), key=lambda s: s.Addr)
    dropped = set()
    previous = None
    for sym in funcs:
        if previous is not None and sym.Addr & 3 and not previous.Thumb and previous.End == sym.Addr:
            previous.Size += sym.Size
            dropped.add(id(sym))
            continue

        previous = sym

    return [s for s in symbols if id(s) not in dropped], len(dropped)

def isPurePool(binary, sym, refs):
    addr = sym.Addr
    if addr & 2 and int.from_bytes(binary.Read(addr, 2), "little") == 0: addr += 2
    if addr & 3 or addr >= sym.End: return False

    return all(word in refs for word in range(addr, sym.End, 4))

def MergePoolStarts(binary, symbols):
    funcs = sorted((s for s in symbols if s.Kind == "function"), key=lambda s: s.Addr)
    dropped = set()
    index = 0
    while index < len(funcs):
        sym = funcs[index]
        nxt = index + 1
        while nxt < len(funcs) and funcs[nxt].Addr == sym.End and NameScore(funcs[nxt].Name) < 2:
            refs = {r & ~3 for r in PoolRefs(binary, sym) if r >= sym.Addr}
            if not isPurePool(binary, funcs[nxt], refs): break

            sym.Size = funcs[nxt].End - sym.Addr
            dropped.add(id(funcs[nxt]))
            nxt += 1

        index = nxt

    return [s for s in symbols if id(s) not in dropped], len(dropped)

def writesPc(word):
    if (word >> 26) & 3 != 0 or (word >> 12) & 0xF != 0xF: return False
    if 8 <= (word >> 21) & 0xF <= 11: return False

    return word & 0x02000090 != 0x00000090

def armEndsFlow(word):
    if word >> 28 != 0xE: return False
    if word & 0x0FFFFFF0 == 0x012FFF10: return True
    if word & 0x0E108000 == 0x08108000: return True
    if word & 0x0F000000 == 0x0A000000: return True
    if word & 0x0C10F000 == 0x0410F000: return True
    if writesPc(word): return True
    if word & 0x0FF000F0 == 0x07F000F0: return True

    return word == ARM_NOP

def looksLikeAddress(word):
    return word == 0 or 0x00100000 <= word < 0x00B00000

def lastInstruction(binary, sym):
    pool = {r & ~3 for r in PoolRefs(binary, sym)}
    addr = sym.End - 4
    while addr >= sym.Addr and (addr in pool or looksLikeAddress(binary.Word(addr))): addr -= 4

    return binary.Word(addr) if addr >= sym.Addr else None

REACH_WINDOW = 0x2000
TIDY_ROUNDS = 6

def flowContinues(binary, sym):
    if sym.Thumb or "linker" in sym.Attrs: return False

    last = lastInstruction(binary, sym)

    return last is not None and not armEndsFlow(last)

def internalReach(binary, sym, realStarts):
    reach = 0
    for offset in range(0, sym.Size, 4):
        pc = sym.Addr + offset
        branch = armBranch(binary.Word(pc), pc)
        if not branch or branch[0].startswith("bl"): continue

        target = branch[1]
        if pc < target < pc + REACH_WINDOW and target not in realStarts: reach = max(reach, target)

    return reach

def extendThroughGap(binary, sym, limit, reach, realStarts):
    limit &= ~3
    if limit <= sym.End: return

    stop = next((a for a in range(sym.End, limit, 4) if a in realStarts or pushesReturnAddress(binary.Word(a))), None)
    if reach >= limit and stop is None:
        sym.Size = limit - sym.Addr
        return

    pools = {r & ~3 for r in PoolRefs(binary, sym)}
    addr = sym.End
    while addr < limit:
        if addr in pools:
            addr += 4
            continue

        if addr in realStarts: break

        word = binary.Word(addr)
        if pushesReturnAddress(word): break

        pools.update(r & ~3 for r in armPoolRefs(word, addr))
        branch = armBranch(word, addr)
        if branch and not branch[0].startswith("bl") and addr < branch[1] < limit: reach = max(reach, branch[1])

        addr += 4
        if armEndsFlow(word) and addr > reach: break

    sym.Size = addr - sym.Addr

def pointerWords(binary):
    words = set()
    for seg in binary.Segments:
        if seg.Kind == "bss": continue

        data = binary.Read(seg.Addr, seg.End - seg.Addr)
        words.update(struct.unpack_from("<%dI" % (len(data) // 4), data))

    return words

def realStartSet(binary, funcs, pointers):
    text = next(seg for seg in binary.Segments if seg.Kind == "code")
    starts = {s.Addr for s in funcs if NameScore(s.Name) >= 2 or s.Thumb or s.Attrs.get("linker") or s.Attrs.get("lib")}
    starts.update(p for p in pointers if text.Addr <= p < text.End and p % 4 == 0)
    for sym in funcs:
        if sym.Thumb: continue

        for offset in range(0, sym.Size, 4):
            branch = armBranch(binary.Word(sym.Addr + offset), sym.Addr + offset)
            if branch and branch[0].startswith("bl"): starts.add(branch[1] & ~1)

    return starts

def callTargets(binary, funcs):
    targets = {}
    for sym in funcs:
        if sym.Thumb: continue

        for offset in range(0, sym.Size, 4):
            word = binary.Word(sym.Addr + offset)
            branch = armBranch(word, sym.Addr + offset)
            if branch and word >> 28 != 0xF: targets.setdefault((branch[1], branch[0].startswith("bl")), set()).add(sym.Addr)

    return targets

def plausibleStart(word):
    return word >> 28 == 0xE and not looksLikeAddress(word)

def PromoteCodeLabels(binary, symbols):
    funcs = sorted((s for s in symbols if s.Kind == "function"), key=lambda s: s.Addr)
    starts = [f.Addr for f in funcs]
    pointers = pointerWords(binary)
    realStarts = realStartSet(binary, funcs, pointers)
    branched = callTargets(binary, funcs)
    called = {t for t, link in branched if link}
    jumped = {t for t, link in branched if not link}
    promoted = 0
    for label in sorted((s for s in symbols if s.Kind == "label" and s.Section == ".text" and s.Addr % 4 == 0), key=lambda s: s.Addr):
        if label.Name.startswith(("def_", "loc_", "locret_", "jpt_")): continue

        index = bisect.bisect_right(starts, label.Addr) - 1
        if index >= 0 and funcs[index].Addr <= label.Addr < funcs[index].End: continue

        looksLikeFunction = NameScore(label.Name) >= 2 or label.Name.startswith(("sub_", "nullsub_", "j_"))
        if label.Addr not in called and label.Addr not in pointers and not (looksLikeFunction and label.Addr in jumped): continue
        if label.Addr not in called and not plausibleStart(binary.Word(label.Addr)): continue

        limit = funcs[index + 1].Addr if index + 1 < len(funcs) else label.Addr + 4
        label.Kind = "function"
        label.Size = 4
        label.Attrs["mode"] = "arm"
        if not armEndsFlow(binary.Word(label.Addr)): extendThroughGap(binary, label, limit, 0, realStarts - {label.Addr})

        funcs.insert(index + 1, label)
        starts.insert(index + 1, label.Addr)
        promoted += 1

    text = next(seg for seg in binary.Segments if seg.Kind == "code")
    for target in sorted({t for t, _ in branched if t % 4 == 0 and text.Addr <= t < text.End}):
        index = bisect.bisect_right(starts, target) - 1
        if index >= 0 and funcs[index].Addr <= target < funcs[index].End: continue
        if target not in called and not plausibleStart(binary.Word(target)): continue
        if target not in called and index >= 0 and branched[(target, False)] == {funcs[index].Addr}: continue

        limit = funcs[index + 1].Addr if index + 1 < len(funcs) else target + 4
        sym = Symbol("sub_%X" % target, text.Name, target, "function", 4, {"mode": "arm"})
        if not armEndsFlow(binary.Word(target)): extendThroughGap(binary, sym, limit, 0, realStarts - {target})

        symbols.append(sym)
        funcs.insert(index + 1, sym)
        starts.insert(index + 1, target)
        promoted += 1

    return promoted

def pushesReturnAddress(word):
    return word & 0xFFFF4000 == 0xE92D4000

def mergeable(binary, head, tail, members, callers, realStarts):
    if head.Thumb or "linker" in head.Attrs or head.End != tail.Addr or tail.Size % 4: return False
    if tail.Addr in realStarts or callers.get(tail.Addr, set()) - members: return False
    if pushesReturnAddress(binary.Word(tail.Addr)): return False

    return flowContinues(binary, head) or internalReach(binary, head, realStarts) > tail.Addr

def MergeFallthroughs(binary, symbols):
    funcs = sorted((s for s in symbols if s.Kind == "function"), key=lambda s: s.Addr)
    callers = {}
    for source, target, _ in CallEdges(binary, funcs): callers.setdefault(target, set()).add(source)

    realStarts = realStartSet(binary, funcs, pointerWords(binary))
    dropped = set()
    current = None
    members = set()
    for sym in funcs:
        if current is not None and not current.Thumb and "linker" not in current.Attrs and current.Size % 4 == 0 and current.End < sym.Addr:
            reach = internalReach(binary, current, realStarts)
            if reach >= current.End or flowContinues(binary, current): extendThroughGap(binary, current, sym.Addr, reach, realStarts)

        if current is None or not mergeable(binary, current, sym, members, callers, realStarts):
            current = sym
            members = {sym.Addr}
            continue

        current.Size = sym.End - current.Addr
        members.add(sym.Addr)
        dropped.add(id(sym))

    return [s for s in symbols if id(s) not in dropped], len(dropped)

def FixModes(binary, funcs, rounds=3):
    byAddr = {s.Addr: s for s in funcs}
    flipped = 0
    for _ in range(rounds):
        votes = {}
        for _, target, thumb in CallEdges(binary, funcs):
            if target not in byAddr: continue
            tally = votes.setdefault(target, [0, 0])
            tally[1 if thumb else 0] += 1

        changed = 0
        for addr, (arm, thumb) in votes.items():
            sym = byAddr[addr]
            want = thumb > arm
            if arm == thumb or want == sym.Thumb: continue
            if addr & 2 and not want: continue

            sym.Attrs["mode"] = "thumb" if want else "arm"
            changed += 1
        flipped += changed
        if not changed: break

    return flipped

def Tidy():
    binary = LoadBinary(LoadProject())
    symbols = ReadSymbols()
    flipped = FixModes(binary, [s for s in symbols if s.Kind == "function"])
    symbols, dropped = DropImpossibleStarts(symbols)
    symbols, pooled = MergePoolStarts(binary, symbols)
    veneers = MarkVeneers(binary, symbols)
    merged = promoted = 0
    for _ in range(TIDY_ROUNDS):
        symbols, roundMerged = MergeFallthroughs(binary, symbols)
        roundPromoted = PromoteCodeLabels(binary, symbols)
        veneers = MarkVeneers(binary, symbols)
        merged += roundMerged
        promoted += roundPromoted
        if not roundMerged and not roundPromoted: break

    WriteSymbols(symbols)
    print("tidy: %d modes corrected, %d impossible starts dropped, %d literal pools rejoined, %d veneers, %d fall-through fragments rejoined, %d code labels promoted to functions" % (flipped, dropped, pooled, veneers, merged, promoted))

def main():
    argparse.ArgumentParser(description="Re-check modes, impossible starts, literal pools, veneers, fall-through fragments and uncovered code labels in config/symbols.txt").parse_args()
    Tidy()

if __name__ == "__main__":
    main()