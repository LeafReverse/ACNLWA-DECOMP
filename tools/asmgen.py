#!/usr/bin/env python3
import argparse
import bisect
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import LoadBinary, LoadProject, ProjectPath, ReadSplits, ReadSymbols

ARM_NOP = 0xE1A00000
CONDITIONS = ["eq", "ne", "cs", "cc", "mi", "pl", "vs", "vc", "hi", "ls", "ge", "lt", "gt", "le", "", ""]
HEADER = "; generated with 3ds-decomp tools\n    PRESERVE8\n"

def signExtend(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value

def armPoolRefs(word, pc):
    if (word & 0x0F3F0000) == 0x051F0000:
        offset = word & 0xFFF
        return [(pc + 8 + (offset if word & 0x800000 else -offset)) & ~3]

    if (word & 0x0F5F0090) == 0x015F0090 or (word & 0x0F7F00F0) == 0x014F00D0:
        offset = ((word >> 4) & 0xF0) | (word & 0xF)
        target = (pc + 8 + (offset if word & 0x800000 else -offset)) & ~3
        return [target, target + 4] if (word & 0xF0) == 0xD0 and not word & 0x100000 else [target]

    if (word & 0x0F3F0E00) == 0x0D1F0A00:
        offset = (word & 0xFF) << 2
        target = pc + 8 + (offset if word & 0x800000 else -offset)
        return [target, target + 4] if word & 0x100 else [target]

    return []

def armBranch(word, pc):
    if (word >> 25) & 7 != 5: return None

    cond = word >> 28
    offset = signExtend(word & 0xFFFFFF, 24) << 2
    if cond == 0xF: return "bl", pc + 8 + offset + ((word >> 23) & 2)

    return ("bl" if word & 0x1000000 else "b") + CONDITIONS[cond], pc + 8 + offset

def thumbPoolRefs(half, nextHalf, pc):
    if (half & 0xF800) == 0x4800: return [((pc + 4) & ~3) + ((half & 0xFF) << 2)]

    if (half & 0xFF7F) == 0xF85F:
        offset = nextHalf & 0xFFF
        return [((pc + 4) & ~3) + (offset if half & 0x80 else -offset)]

    if (half & 0xFF3F) == 0xED1F and (nextHalf & 0x0E00) == 0x0A00:
        offset = (nextHalf & 0xFF) << 2
        target = ((pc + 4) & ~3) + (offset if half & 0x80 else -offset)
        return [target, target + 4] if nextHalf & 0x100 else [target]

    return []

def thumbCall(half, nextHalf, pc):
    if (half & 0xF800) != 0xF000: return None
    if (nextHalf & 0xE800) != 0xE800: return None

    offset = signExtend(((half & 0x7FF) << 12) | ((nextHalf & 0x7FF) << 1), 23)
    base = ((pc + 4) & ~3) if not nextHalf & 0x1000 else pc + 4
    return "bl", base + offset

def isThumbWide(half):
    return (half >> 11) == 0x1E

def PoolRefs(binary, sym, length=None):
    data = binary.Read(sym.Addr, length or sym.Size)
    refs = []
    if sym.Thumb:
        count = len(data) // 2
        halves = struct.unpack_from("<%dH" % count, data)
        for i in range(count):
            refs += thumbPoolRefs(halves[i], halves[i + 1] if i + 1 < count else 0, sym.Addr + i * 2)

        return refs

    for i, word in enumerate(struct.unpack_from("<%dI" % (len(data) // 4), data)):
        refs += armPoolRefs(word, sym.Addr + i * 4)

    return refs

def CallEdges(binary, funcs):
    for sym in funcs:
        data = binary.Read(sym.Addr, sym.Size)
        if sym.Thumb:
            count = len(data) // 2
            halves = struct.unpack_from("<%dH" % count, data)
            for i in range(count - 1):
                if not isThumbWide(halves[i]): continue

                call = thumbCall(halves[i], halves[i + 1], sym.Addr + i * 2)
                if call: yield sym.Addr, call[1] & ~1, (halves[i + 1] & 0xD000) != 0xC000

            continue

        for i, word in enumerate(struct.unpack_from("<%dI" % (len(data) // 4), data)):
            branch = armBranch(word, sym.Addr + i * 4)

            if branch: yield sym.Addr, branch[1] & ~1, (word >> 28) == 0xF

class Context:
    def __init__(self, binary, symbols):
        self.Binary = binary
        self.Functions = {s.Addr: s for s in symbols if s.Kind == "function"}
        self.Objects = {s.Addr: s for s in symbols if s.Kind in ("object", "label")}
        self.Sized = sorted((s for s in symbols if s.Kind == "object" and s.Size > 0), key=lambda s: s.Addr)
        self.SizedStarts = [s.Addr for s in self.Sized]

    def CallTarget(self, addr, thumb):
        sym = self.Functions.get(addr & ~1)

        return sym.Name if sym and sym.Thumb == thumb and "linker" not in sym.Attrs else None

    def containingObject(self, value):
        index = bisect.bisect_right(self.SizedStarts, value) - 1
        if index < 0: return None

        obj = self.Sized[index]

        return "%s + 0x%X" % (obj.Name, value - obj.Addr) if value < obj.Addr + obj.Size else None

    def DataRef(self, value):
        fn = self.Functions.get(value & ~1)
        if fn and (value & 1) == (1 if fn.Thumb else 0): return fn.Name

        obj = self.Objects.get(value)
        if obj: return obj.Name
        if value & 3 or not self.Binary.InImage(value): return None

        inside = self.containingObject(value)
        if inside: return inside

        seg = self.Binary.SegmentOf(value)
        return None if seg.Kind == "code" else "lbl_%08X" % value

def quoted(name):
    return "|%s|" % name

def dataWord(ctx, word, refs):
    ref = ctx.DataRef(word)
    if not ref: return "    DCDU 0x%08X" % word

    name, _, addend = ref.partition(" + ")
    refs.add(name)

    return "    DCDU %s + %s" % (quoted(name), addend) if addend else "    DCDU %s" % quoted(name)

def emitData(ctx, data, start, offset, end, body, refs):
    while offset < end:
        if end - offset >= 4 and (start + offset) % 4 == 0:
            body.append((offset, dataWord(ctx, struct.unpack_from("<I", data, offset)[0], refs)))
            offset += 4
            continue

        body.append((offset, "    DCB 0x%02X" % data[offset]))
        offset += 1

def codeEnd(pool, count, step, keepPool=False):
    end = count * step
    if keepPool: return end

    while end > 0 and end - step in pool: end -= step

    return end

def isVfpLoad(word):
    return (word & 0x0F3F0E00) == 0x0D1F0A00

def armAdrRef(word, pc):
    if (word & 0x0FEF0000) not in (0x028F0000, 0x024F0000): return None
    if (word >> 12) & 0xF in (14, 15): return None

    rotate = ((word >> 8) & 0xF) * 2
    value = ((word & 0xFF) >> rotate | (word & 0xFF) << (32 - rotate)) & 0xFFFFFFFF if rotate else word & 0xFF

    return pc + 8 + (value if word & 0x00800000 else -value)

def adrData(sym, words, pool):
    data = set()
    for i, word in enumerate(words):
        ref = armAdrRef(word, sym.Addr + i * 4)
        if ref is None or ref <= sym.Addr + i * 4 or ref >= sym.End or ref % 4: continue

        offset = ref - sym.Addr
        while offset < len(words) * 4 and offset not in pool:
            data.add(offset)
            offset += 4

    return data

def emitArm(ctx, sym, data, body, refs):
    pool = set()
    vfpPool = set()
    doublePool = set()
    count = len(data) // 4
    words = struct.unpack_from("<%dI" % count, data)
    for i, word in enumerate(words):
        if i * 4 in pool: continue

        for ref in armPoolRefs(word, sym.Addr + i * 4):
            if not sym.Addr <= ref < sym.End: continue

            pool.add(ref - sym.Addr)
            if isVfpLoad(word): vfpPool.add(ref - sym.Addr)
            if isVfpLoad(word) and word & 0x100 and ref % 8 == 0: doublePool.add(ref - sym.Addr)

    for offset in sorted(doublePool):
        start = offset
        while start >= 8 and (start - 4 in pool or (words[start // 4 - 1] == 0 and start - 8 in pool)): start -= 4

        pool.update(range(start, offset, 4))
        pad = start - 4
        if pad >= 0 and (sym.Addr + start) % 8 == 0 and words[pad // 4] == 0: pool.add(pad)

    adrPool = adrData(sym, words, pool)
    pool |= adrPool
    i = 0
    nextFn = ctx.Functions.get(sym.End)

    while i < count:
        offset = i * 4
        if offset in pool:
            run = offset
            while run < count * 4 and run in pool: run += 4

            emitData(ctx, data, sym.Addr, offset, run, body, refs)
            i = run // 4
            continue

        word = words[i]
        branch = armBranch(word, sym.Addr + offset)
        target = ctx.CallTarget(branch[1], (word >> 28) == 0xF) if branch else None
        mnemonic = branch[0] if branch else "b"

        if i == count - 1 and word == ARM_NOP and nextFn and not nextFn.Thumb and nextFn.Name != sym.Name: target, mnemonic = nextFn.Name, "b"
        elif target == sym.Name: target = None

        if target:
            refs.add(target)
            body.append((offset, "    %s %s" % (mnemonic.upper(), quoted(target))))
        else: body.append((offset, "    DCI 0x%08X" % word))

        i += 1

    emitData(ctx, data, sym.Addr, count * 4, len(data), body, refs)
    end = codeEnd(pool, count, 4)

    return codeEnd(pool, count, 4, keepPool=any(end <= offset for offset in vfpPool | adrPool))

def emitThumb(ctx, sym, data, body, refs):
    pool = set()
    count = len(data) // 2
    halves = struct.unpack_from("<%dH" % count, data)
    for i in range(count):
        nextHalf = halves[i + 1] if i + 1 < count else 0
        for ref in thumbPoolRefs(halves[i], nextHalf, sym.Addr + i * 2):
            if sym.Addr <= ref < sym.End:
                pool.add(ref - sym.Addr)
                pool.add(ref - sym.Addr + 2)

    for offset in sorted(pool):
        pad = offset - 2
        if pad >= 0 and pad not in pool and (sym.Addr + pad) & 2 and halves[pad // 2] == 0: pool.add(pad)

    i = 0

    while i < count:
        offset = i * 2
        if offset in pool:
            run = offset
            while run < count * 2 and run in pool: run += 2

            emitData(ctx, data, sym.Addr, offset, run, body, refs)
            i = run // 2
            continue

        half = halves[i]
        if not isThumbWide(half) or i + 1 >= count:
            body.append((offset, "    DCI 0x%04X" % half))
            i += 1
            continue

        nextHalf = halves[i + 1]
        call = thumbCall(half, nextHalf, sym.Addr + offset)
        target = ctx.CallTarget(call[1], (nextHalf & 0xD000) != 0xC000) if call and call[0] == "bl" else None
        if target and target != sym.Name:
            refs.add(target)
            body.append((offset, "    BL %s" % quoted(target)))
        else: body += [(offset, "    DCI 0x%04X" % half), (offset + 2, "    DCI 0x%04X" % nextHalf)]

        i += 2

    emitData(ctx, data, sym.Addr, count * 2, len(data), body, refs)

    return codeEnd(pool, count, 2)

def renderFunction(sym, body, size):
    name = quoted(sym.Name)
    lines = ["", "    AREA |i.%s|, CODE, READONLY, ALIGN=%d" % (sym.Name, 1 if sym.Thumb else 2), "    %s" % ("THUMB" if sym.Thumb else "ARM"), "    EXPORT %s" % name, "", "%s PROC" % name]
    closed = False
    for offset, text in body:
        if not closed and offset >= size:
            lines.append("    ENDP")
            closed = True

        lines.append(text)

    if not closed: lines.append("    ENDP")

    return lines

def RenderUnit(ctx, unit):
    functions = []
    defined = set()
    refs = set()

    for section, start, end in unit.Ranges:
        if section != ".text": continue
        for addr in sorted(a for a in ctx.Functions if start <= a < end):
            sym = ctx.Functions[addr]
            if "linker" in sym.Attrs: continue

            data = ctx.Binary.Read(sym.Addr, min(sym.Size, end - sym.Addr))
            body = []
            size = emitThumb(ctx, sym, data, body, refs) if sym.Thumb else emitArm(ctx, sym, data, body, refs)
            functions += renderFunction(sym, body, size)
            defined.add(sym.Name)

    externs = sorted(refs - defined)
    lines = [HEADER] + ["    EXTERN %s" % quoted(name) for name in externs] + functions + ["", "    END"]

    return "\n".join(lines) + "\n"

def writeIfChanged(path, text):
    if path.exists() and path.read_text() == text: return False

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)

    return True

def main():
    parser = argparse.ArgumentParser(description="Write build/asm/<unit>.s (armasm syntax) from config/splits.txt")
    parser.add_argument("--unit", action="append", help="only these units")
    parser.add_argument("--out", default=str(ProjectPath("build", "asm")))
    parser.add_argument("-q", "--quiet", action="store_true")
    args = parser.parse_args()

    project = LoadProject()
    ctx = Context(LoadBinary(project), ReadSymbols())
    units = ReadSplits()
    wanted = set(args.unit or [])
    out = Path(args.out)
    written = 0
    for unit in units:
        if wanted and unit.Name not in wanted: continue

        written += writeIfChanged(out / (unit.Name + ".s"), RenderUnit(ctx, unit))

    removed = 0 if wanted else removeStale(out, {unit.Name for unit in units})
    if not args.quiet: print("%d units, %d .s files rewritten, %d stale removed" % (len(units) if not wanted else len(wanted), written, removed))

def removeStale(out, names):
    removed = 0

    for path in out.rglob("*.s"):
        if path.relative_to(out).with_suffix("").as_posix() in names: continue

        path.unlink()
        stale = Path(str(path).replace(str(out), str(out.parent / "target"), 1)).with_suffix(".o")
        if stale.exists(): stale.unlink()

        removed += 1

    return removed

if __name__ == "__main__":
    main()
