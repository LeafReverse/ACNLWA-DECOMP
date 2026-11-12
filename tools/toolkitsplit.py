#!/usr/bin/env python3
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import LoadBinary, LoadProject, ProjectPath, ReadSplits, ReadSymbols, ToolPath
from toolkit import findImage

WORK_DIR = ProjectPath("build", "toolkit")
SPLIT_DIR = WORK_DIR / "split"
SHIM_DIR = WORK_DIR / "bin"
SPLITS_INPUT = WORK_DIR / "splits.txt"
FUNCTIONS_INPUT = WORK_DIR / "functions.csv"
ORIGINAL_ELF = "program_original.elf"
MAX_PIECE_BYTES = 0x10000
FILL_PREFIX = "toolkit_fill/fill_"
SHIM = """#!/usr/bin/env python3
import os, subprocess, sys
env = dict(os.environ, CC_CWD=os.getcwd())
sys.exit(subprocess.call([%r, %r, %r] + sys.argv[1:], env=env))
"""

def textRanges(units, text):
    ranges = []
    for unit in units:
        for section, start, end in unit.Ranges:
            if section != ".text": continue

            ranges.append((start & ~3, end if end == text.End else end & ~3, unit.Name))

    ranges.sort()
    placed = []
    cursor = text.Addr
    for start, end, name in ranges:
        start = max(start, cursor)
        if end <= start: continue

        if start > cursor: placed.append((cursor, start, FILL_PREFIX + "%08X" % cursor))

        placed.append((start, end, name))
        cursor = end

    if cursor < text.End: placed.append((cursor, text.End, FILL_PREFIX + "%08X" % cursor))

    return placed

def widthBands(size):
    edges = [0]
    edge = 0x10
    while edge < size:
        edges.append(edge)
        edge <<= 4

    return list(zip(edges, edges[1:] + [size]))

def blockStarts(ranges, functions, bands, text):
    starts = {start - text.Addr for start, _, _ in ranges}
    starts.update(low for low, _ in bands)
    starts.update(f.Addr - text.Addr for f in functions if f.Addr % 4 == 0 and text.Addr <= f.Addr < text.End)

    return sorted(starts)

def pieces(ranges, starts, text):
    import bisect
    result = []
    for start, end, name in ranges:
        low, high = start - text.Addr, end - text.Addr
        first = bisect.bisect_left(starts, low)
        last = bisect.bisect_left(starts, high)
        cut = low
        part = 0
        for index in range(first + 1, last):
            if starts[index] - cut < MAX_PIECE_BYTES: continue

            result.append((cut, starts[index], name, part))
            cut = starts[index]
            part += 1

        result.append((cut, high, name, part))

    return result

def unitPath(name, part):
    return "%s.cpp" % name if not part else "%s_part%02d.cpp" % (name, part)

def renderSplits(units, bands, segments, text):
    lines = ["Sections:"]
    lines += ["\ttext_%d type:code start:0x%X end:0x%X" % (index, low, high) for index, (low, high) in enumerate(bands)]
    for seg in segments:
        if seg.Kind in ("rodata", "data"): lines.append("\t%s type:%s start:0x%X end:0x%X" % (seg.Name.lstrip("."), seg.Kind, seg.Addr - text.Addr, seg.End - text.Addr))

    lines.append("")
    for path, spans in units.items():
        lines.append("%s:" % path)
        for low, high in spans:
            for index, (bandLow, bandHigh) in enumerate(bands):
                start, end = max(low, bandLow), min(high, bandHigh)
                if start < end: lines.append("\ttext_%d start:0x%X end:0x%X" % (index, start, end))

        lines.append("")

    return "\n".join(lines) + "\n"

def renderFunctions(starts, size, thumbStarts):
    bounds = starts + [size]
    return "".join("0x%X,0x%X,%s,main\n" % (low, high, "thumb" if low in thumbStarts else "arm") for low, high in zip(bounds, bounds[1:]))

def Prepare():
    binary = LoadBinary(LoadProject())
    text = next(s for s in binary.Segments if s.Kind == "code")
    functions = [s for s in ReadSymbols() if s.Kind == "function" and s.Section == ".text"]
    ranges = textRanges(ReadSplits(), text)
    bands = widthBands(text.Size)
    starts = blockStarts(ranges, functions, bands, text)
    units = {}
    for low, high, name, part in pieces(ranges, starts, text): units.setdefault(unitPath(name, part), []).append((low, high))

    thumbStarts = {f.Addr - text.Addr for f in functions if f.Thumb}
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    SPLITS_INPUT.write_text(renderSplits(units, bands, binary.Segments, text))
    FUNCTIONS_INPUT.write_text(renderFunctions(starts, text.Size, thumbStarts))
    print("toolkit input: %d units, %d blocks, %d width bands (offsets from .text 0x%X)" % (len(units), len(starts), len(bands), text.Addr))

def Split(image):
    if SPLIT_DIR.exists(): shutil.rmtree(SPLIT_DIR)

    SPLIT_DIR.mkdir(parents=True)
    command = [str(ToolPath("3dsdecomp-toolkit")), "split", str(image), str(SPLITS_INPUT), str(FUNCTIONS_INPUT), str(SPLIT_DIR)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode or result.stderr.strip(): sys.exit("3dsdecomp-toolkit split failed:\n" + result.stdout + result.stderr)

    count = sum(1 for _ in (SPLIT_DIR / "orig").rglob("*.s"))
    print("3dsdecomp-toolkit split: %d armasm units, scatter.sct, build.ninja in %s" % (count, SPLIT_DIR))

def writeShims():
    SHIM_DIR.mkdir(parents=True, exist_ok=True)
    for program in ("armasm", "armlink"):
        path = SHIM_DIR / program
        path.write_text(SHIM % (sys.executable, str(ProjectPath("tools", "cc.py")), program))
        path.chmod(0o755)

def Build(jobs):
    writeShims()
    env = dict(os.environ, PATH=str(SHIM_DIR) + os.pathsep + os.environ.get("PATH", ""))
    command = [str(ToolPath("ninja")), "-C", str(SPLIT_DIR), ORIGINAL_ELF] + (["-j", str(jobs)] if jobs else [])
    if subprocess.run(command, env=env).returncode: sys.exit("the toolkit's build.ninja failed")

def Verify():
    from elftools.elf.elffile import ELFFile
    binary = LoadBinary(LoadProject())
    text = next(s for s in binary.Segments if s.Kind == "code")
    compared = 0
    with open(SPLIT_DIR / ORIGINAL_ELF, "rb") as fh:
        for segment in ELFFile(fh).iter_segments():
            if segment["p_type"] != "PT_LOAD" or not segment["p_filesz"]: continue

            addr = text.Addr + segment["p_vaddr"]
            rebuilt = segment.data()
            original = binary.Read(addr, len(rebuilt))
            if rebuilt != original:
                first = next((i for i, (a, b) in enumerate(zip(rebuilt, original)) if a != b), min(len(rebuilt), len(original)))
                sys.exit("%s differs from the original at 0x%08X (%d bytes compared before it)" % (ORIGINAL_ELF, addr + first, compared + first))

            compared += len(rebuilt)

    if compared != text.Size: sys.exit("%s covers %d of %d .text bytes" % (ORIGINAL_ELF, compared, text.Size))

    print("%s: .text byte-identical to the original (%d bytes)" % (ORIGINAL_ELF, compared))

def main():
    parser = argparse.ArgumentParser(description="Run 3dsdecomp-toolkit split on config/splits.txt + symbols.txt, build its program_original.elf with armasm/armlink and compare it with the original")
    parser.add_argument("image", nargs="?", help="original .3ds/.cxi (decrypted); default: the only one under orig/")
    parser.add_argument("--skip-build", action="store_true", help="only write the toolkit inputs and run split")
    parser.add_argument("-j", "--jobs", type=int, help="ninja parallelism for the toolkit's build")
    args = parser.parse_args()
    Prepare()
    Split(findImage(args.image))
    if args.skip_build: return

    Build(args.jobs)
    Verify()

if __name__ == "__main__":
    main()
