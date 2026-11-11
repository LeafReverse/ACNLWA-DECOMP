#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import BinaryPath, DebugElfPath, LoadBinary, LoadProject, LoadSegments, ProjectPath, ReadSymbols, ToolPath
from dwarffix import ScopeResults
from symsync import readBaseObject

UNPLACED_BASE = 0x10000000
DISCARDED = ("*(.ARM.exidx*)", "*(.arm_vfe_header)", "*(.comment)")
SKIPPED_KINDS = ("label",)

def allRelocsMasked(code, relocs):
    masked = bytearray(code)
    for rel in relocs:
        if rel.Offset + 4 <= len(masked): masked[rel.Offset:rel.Offset + 4] = b"\0\0\0\0"

    return bytes(masked)

def imageSection(seg):
    return ".image%s" % seg.Name

def definedFunctions(path):
    from elftools.elf.elffile import ELFFile
    found = []
    with open(path, "rb") as fh:
        elf = ELFFile(fh)
        table = elf.get_section_by_name(".symtab")
        if not table: return found
        for sym in table.iter_symbols():
            if sym["st_info"]["type"] != "STT_FUNC" or sym["st_shndx"] == "SHN_UNDEF" or sym["st_info"]["bind"] == "STB_LOCAL": continue

            found.append((sym.name, elf.get_section(sym["st_shndx"]).name))

    return found

def undefinedSymbols(path):
    from elftools.elf.elffile import ELFFile
    with open(path, "rb") as fh:
        table = ELFFile(fh).get_section_by_name(".symtab")
        if not table: return set()

        return {s.name for s in table.iter_symbols() if s.name and s["st_shndx"] == "SHN_UNDEF" and not s.name.startswith("__ARM_") and not s.name.startswith("Lib$$")}

def quote(name):
    return '"%s"' % name

def symbolLines(sym, seg):
    name = quote(sym.Name)
    lines = [".global %s" % name]
    target = "%s + 0x%X" % (quote("__image" + seg.Name), sym.Addr - seg.Addr)
    if sym.Kind == "function":
        lines.append(".type %s, %%function" % name)
        lines.append("%s %s, %s" % (".thumb_set" if sym.Thumb else ".set", name, target))
    else:
        lines.append(".type %s, %%object" % name)
        lines.append(".set %s, %s" % (name, target))

    if sym.Size: lines.append(".size %s, 0x%X" % (name, sym.Size))
    return lines


def writeImage(path, segments, symbols, skip, binaryPath):
    lines = [".syntax unified"]
    for seg in segments:
        flags, kind = ("ax", "%progbits") if seg.Kind == "code" else (("aw", "%nobits") if seg.Kind == "bss" else ("aw", "%progbits"))
        lines += ['.section %s, "%s", %s' % (imageSection(seg), flags, kind), "%s:" % quote("__image" + seg.Name)]
        lines.append(".space 0x%X" % seg.Size if seg.Kind == "bss" else '.incbin "%s", 0x%X, 0x%X' % (binaryPath.as_posix(), seg.Offset, seg.Size))
    for sym in symbols:
        if sym.Kind in SKIPPED_KINDS or sym.Name in skip: continue

        seg = next((s for s in segments if s.Addr <= sym.Addr < s.End), None)
        if seg: lines += symbolLines(sym, seg)

    path.write_text("\n".join(lines) + "\n")


def writeScript(path, segments, placements, imageObject):
    lines = ["ENTRY(start)", "SECTIONS", "{"]
    for seg in segments:
        load = " (NOLOAD)" if seg.Kind == "bss" else ""
        lines.append('    %s 0x%08X%s : { "%s"(%s) }' % (imageSection(seg), seg.Addr, load, imageObject.as_posix(), imageSection(seg)))

    for index, (addr, objPath, section) in enumerate(placements):
        lines.append('    .src%d 0x%08X (NOLOAD) : { "%s"("%s") }' % (index, addr, objPath.as_posix(), section))

    lines += ["    /DISCARD/ : { %s }" % " ".join(DISCARDED), "}"]
    path.write_text("\n".join(lines) + "\n")


def run(cmd):
    result = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if result.returncode: sys.exit("%s failed:\n%s%s" % (Path(str(cmd[0])).name, result.stdout, result.stderr))


def main():
    parser = argparse.ArgumentParser(description="Link a debug ELF of the original image")
    parser.add_argument("objects", nargs="*", help="--debug objects (build/debug/<unit>.o)")
    parser.add_argument("-o", "--output")
    args = parser.parse_args()
    project = LoadProject()
    output = args.output or DebugElfPath(project)
    segments = LoadSegments(project)
    symbols = ReadSymbols()
    byName = {s.Name: s for s in symbols}
    output = Path(output).resolve()
    workDir = output.parent / "debugelf"
    workDir.mkdir(parents=True, exist_ok=True)
    placements = []
    defined = set()
    differing = []
    unplaced = UNPLACED_BASE
    unknown = set()
    binary = LoadBinary(project, verify=False)
    for obj in (Path(o).resolve() for o in args.objects):
        unknown.update(undefinedSymbols(obj))
        functions = {fn.Name: fn for fn in readBaseObject(obj)}
        for name, section in definedFunctions(obj):
            defined.add(name)
            sym = byName.get(name)
            if sym:
                placements.append((sym.Addr, obj, section))
                fn = functions.get(name)
                if fn and allRelocsMasked(fn.Code, fn.Relocs) != allRelocsMasked(binary.Read(sym.Addr, fn.Size), fn.Relocs): differing.append(name)

                continue

            placements.append((unplaced, obj, section))
            unplaced += 0x1000

    imageSource = workDir / "image.s"
    imageObject = workDir / "image.o"
    script = workDir / "debug.ld"
    writeImage(imageSource, segments, symbols, defined, BinaryPath(project).resolve())
    run([ToolPath("arm-none-eabi", "as"), "-march=armv6k", "-mfpu=vfp", "-meabi=5", imageSource, "-o", imageObject])
    writeScript(script, segments, placements, imageObject)
    unknown -= set(byName) | defined
    stubs = ["--defsym=%s=0" % name for name in sorted(unknown)]
    run([ToolPath("arm-none-eabi", "ld"), "-T", script, "--no-check-sections", "--unresolved-symbols=ignore-all", "--no-warn-rwx-segments", "-nostdlib", "-o", output, imageObject] + stubs + sorted({p[1] for p in placements}))
    scoped, scopedTotal = ScopeResults(output, ToolPath("arm-none-eabi", "objcopy"))
    print("%s: %d symbols, %d source functions with debug info" % (output.relative_to(ProjectPath()), len(symbols), len(placements)))
    if unknown: print("  warning: %d referenced symbols are not in config/symbols.txt yet (placed at 0): %s" % (len(unknown), ", ".join(sorted(unknown))))
    if scoped < scopedTotal: print("  warning: %d of %d late-starting variables keep a wrong value before their first assignment" % (scopedTotal - scoped, scopedTotal))

    for name in differing: print("  warning: %s differs from the original, its source lines are approximate" % name)


if __name__ == "__main__":
    main()
