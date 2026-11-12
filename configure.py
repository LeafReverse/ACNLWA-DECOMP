#!/usr/bin/env python3
import argparse
import bisect
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "tools"))
from ctrproject import BinaryPath, ExistingPaths, ExpandPath, FetchDependencies, DebugElfPath, LoadProject, ProjectPath, ROOT, ReadSplits, ReadSymbols, ToolPath, VerifyImageHash
from editor import WriteCompileCommands, WriteVscodeConfig, WriteVscodeDebug
from emulator import DEFAULT_PORT as GDB_PORT
from manual import Apply as ApplyManual
from toolkit import IMAGE_SUFFIXES

SOURCE_EXTENSIONS = (".cpp", ".cc", ".c", ".s")
DEFAULT_ASFLAGS = ["--cpu=MPCore", "--apcs=/interwork"]
TOOL_SCRIPTS = ["tools/asmgen.py", "tools/ctrproject.py"]
DEFAULT_THUMB_FLAGS = ["--thumb"]
CONFIG_INPUTS = ["configure.py", "config/project.json", "config/splits.txt", "config/symbols.txt", "config/splits.manual.txt", "config/symbols.manual.txt", "tools.json"]
SYMSYNC_STAMP = "build/symsync.stamp"
SYMSYNC_SCRIPT = "tools/symsync.py"
DEBUGELF_SCRIPT = "tools/debugelf.py"


def ninjaPath(text):
    return str(text).replace("$", "$$").replace(" ", "$ ").replace(":", "$:")


def commandArg(text):
    text = str(text).replace("$", "$$")

    return '"%s"' % text if " " in text else text


def relative(path):
    path = Path(path).resolve()

    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def SourceRoots(project):
    roots = []

    for entry in project.get("source_roots", ["src"]):
        prefix, value = (entry.get("prefix", ""), entry["path"]) if isinstance(entry, dict) else ("", entry)

        for path in ExistingPaths(project, [value]): roots.append((prefix, path))

    return roots


def findSource(unitName, roots):
    for prefix, root in roots:
        if not unitName.startswith(prefix): continue

        for ext in SOURCE_EXTENSIONS:
            candidate = root / (unitName[len(prefix):] + ext)

            if candidate.exists(): return candidate

    return None


def unitFlags(compiler, unitName, thumb=False):
    flags = list(compiler.get("cflags", []))

    if thumb: flags += compiler.get("thumb_flags", DEFAULT_THUMB_FLAGS)

    for override in compiler.get("flag_overrides", []):
        if not unitName.startswith(override["prefix"]): continue

        if "cflags" in override: flags = list(override["cflags"])

        flags += override.get("extra", [])

    return flags


def UnitCategories(unitName, folders):
    parts = unitName.split("/")
    dirs = ["/".join(parts[:i]) for i in range(1, len(parts))]

    if unitName in folders: dirs.append(unitName)

    return dirs or [parts[0]]


def ThumbUnits(units):
    funcs = sorted((s.Addr, s.Size, s.Thumb) for s in ReadSymbols() if s.Kind == "function")
    starts = [f[0] for f in funcs]
    thumb = set()

    for unit in units:
        thumbBytes = armBytes = 0

        for _, start, end in unit.Ranges:
            for addr, size, isThumb in funcs[bisect.bisect_left(starts, start):bisect.bisect_left(starts, end)]:
                if isThumb: thumbBytes += size
                else: armBytes += size

        if thumbBytes > armBytes: thumb.add(unit.Name)

    return thumb


def LibraryUnits(units):
    funcs = sorted((s for s in ReadSymbols() if s.Kind == "function" and "linker" not in s.Attrs), key=lambda s: s.Addr)
    starts = [f.Addr for f in funcs]
    found = {}

    for unit in units:
        members = set()
        plain = 0

        for _, start, end in unit.Ranges:
            for sym in funcs[bisect.bisect_left(starts, start):bisect.bisect_left(starts, end)]:
                if "lib" in sym.Attrs: members.add((sym.Attrs["lib"], sym.Attrs.get("libid", "")))
                else: plain += 1

        if len(members) != 1: continue

        lib, libid = next(iter(members))
        archive, member = lib.split("/", 1)
        found[unit.Name] = (archive, member, plain == 0, libid)

    return found


def writeNinja(project, units, sources, includeDirs, thumbUnits, libraryUnits, debugElf):
    compiler = project["compiler"]
    binary = relative(ExpandPath(project["binary"]["path"], project))
    lines = [
        "ninja_required_version = 1.10",
        "python = %s" % commandArg(sys.executable),
        "asflags = %s" % " ".join(commandArg(f) for f in compiler.get("asflags", DEFAULT_ASFLAGS)),
        "objdiff = %s" % commandArg(ToolPath("objdiff-cli")),
        "includes = %s" % " ".join(commandArg("-I" + relative(d)) for d in includeDirs),
        "",
        "rule configure",
        "  command = $python configure.py",
        "  generator = 1",
        "  description = CONFIGURE",
        "",
        "rule asmgen",
        "  command = $python tools/asmgen.py -q",
        "  restat = 1",
        "  description = ASMGEN",
        "",
        "rule symsync",
        "  command = $python tools/symsync.py --stamp $out $in",
        "  restat = 1",
        "  description = SYMSYNC",
        "",
        "rule cc",
        "  command = $python tools/cc.py armcc --depfile $out.d $cflags $includes -c $in -o $out",
        "  depfile = $out.d",
        "  deps = gcc",
        "  description = CC $out",
        "",
        "rule ccdebug",
        "  command = $python tools/cc.py armcc --depfile $out.d $cflags --debug $includes -c $in -o $out",
        "  depfile = $out.d",
        "  deps = gcc",
        "  description = CC $out",
        "",
        "rule debugelf",
        "  command = $python tools/debugelf.py -o $out $in",
        "  description = DEBUGELF $out",
        "",
        "rule armasm",
        "  command = $python tools/cc.py armasm $asflags $in -o $out",
        "  description = ARMASM $out",
        "",
        "rule libextract",
        "  command = $python tools/libmatch.py --archive-id $libid --extract $archive $member $out",
        "  description = LIB $archive($member)",
        "",
        "rule report",
        "  command = $objdiff report generate -p . -o $out",
        "  description = REPORT",
        "",
        "rule relink",
        "  command = $python tools/relink.py",
        "  description = RELINK target objects with armlink, compare code.bin",
        "",
        "rule toolkitsplit",
        "  command = $python tools/toolkitsplit.py",
        "  description = 3DSDECOMP-TOOLKIT split + program_original.elf, compare .text",
        "",
        "build build.ninja objdiff.json: configure | %s" % " ".join(CONFIG_INPUTS),
        "",
    ]
    asmOutputs = " ".join(ninjaPath("build/asm/%s.s" % u.Name) for u in units)
    sourceBases = " ".join(ninjaPath("build/base/%s.o" % u.Name) for u in units if u.Name in sources)
    lines += ["build %s: symsync %s | %s" % (SYMSYNC_STAMP, sourceBases, SYMSYNC_SCRIPT), ""]
    lines += ["build %s: asmgen | config/splits.txt config/symbols.txt %s %s %s" % (asmOutputs, SYMSYNC_STAMP, ninjaPath(binary), " ".join(TOOL_SCRIPTS)), ""]
    targets = []
    bases = []
    debugObjects = []

    for unit in units:
        target = "build/target/%s.o" % unit.Name
        lines.append("build %s: armasm %s" % (ninjaPath(target), ninjaPath("build/asm/%s.s" % unit.Name)))
        targets.append(target)
        source = sources.get(unit.Name)
        base = "build/base/%s.o" % unit.Name

        if not source and unit.Name in libraryUnits:
            archive, member, _, libid = libraryUnits[unit.Name]
            lines += ["build %s: libextract | config/symbols.txt" % ninjaPath(base), "  archive = %s" % archive, "  member = %s" % member, "  libid = %s" % (libid or "\"\"")]
            bases.append(base)
            continue

        if not source: continue

        if source.suffix == ".s":
            lines.append("build %s: armasm %s" % (ninjaPath(base), ninjaPath(relative(source))))
        else:
            cflags = "  cflags = %s" % " ".join(commandArg(f) for f in unitFlags(compiler, unit.Name, unit.Name in thumbUnits))
            debug = "build/debug/%s.o" % unit.Name
            lines += ["build %s: cc %s" % (ninjaPath(base), ninjaPath(relative(source))), cflags]
            lines += ["build %s: ccdebug %s" % (ninjaPath(debug), ninjaPath(relative(source))), cflags]
            debugObjects.append(debug)
        bases.append(base)

    debugInputs = "config/symbols.txt %s %s %s %s tools/dwarffix.py" % (SYMSYNC_STAMP, ninjaPath(binary), DEBUGELF_SCRIPT, SYMSYNC_SCRIPT)
    lines += [
        "",
        "build %s: debugelf %s | %s" % (debugElf, " ".join(ninjaPath(d) for d in debugObjects), debugInputs),
        "build debug: phony %s" % debugElf,
        "build target: phony %s" % " ".join(ninjaPath(t) for t in targets),
        "build base: phony %s" % " ".join(ninjaPath(b) for b in bases),
        "build build/report.json: report | target base objdiff.json",
        "build progress: phony build/report.json",
        "build build/link/code.bin: relink | target tools/relink.py tools/asmgen.py",
        "build relink: phony build/link/code.bin",
        "build build/toolkit/split/program_original.elf: toolkitsplit | config/splits.txt config/symbols.txt tools/toolkitsplit.py tools/cc.py",
        "build toolkit: phony build/toolkit/split/program_original.elf",
        "default target base debug",
        "",
    ]
    ProjectPath("build.ninja").write_text("\n".join(lines))


def writeObjdiff(project, units, sources, libraryUnits):
    names = project.get("progress_categories", {})
    categories = {}
    entries = []
    folders = {u.Name.rsplit("/", 1)[0] for u in units if "/" in u.Name}

    for unit in units:
        entry = {"name": unit.Name, "target_path": "build/target/%s.o" % unit.Name}
        source = sources.get(unit.Name)
        unitCategories = UnitCategories(unit.Name, folders)

        library = libraryUnits.get(unit.Name) if not source else None

        if source or library: entry["base_path"] = "build/base/%s.o" % unit.Name

        entry["metadata"] = {
            "source_path": relative(source) if source else "src/%s%s" % (unit.Name, project.get("split", {}).get("unit_extension", ".cpp")),
            "progress_categories": unitCategories,
        }

        if library and library[2]: entry["metadata"]["complete"] = True
        entries.append(entry)

        for category in unitCategories: categories.setdefault(category, names.get(category, category))

    config = {
        "$schema": "https://raw.githubusercontent.com/encounter/objdiff/main/config.schema.json",
        "min_version": "3.0.0",
        "custom_make": str(ToolPath("ninja")),
        "build_target": True,
        "build_base": True,
        "watch_patterns": ["*.c", "*.cc", "*.cpp", "*.s", "*.h", "*.hpp", "*.inc", "*.txt", "*.json"],
        "ignore_patterns": ["build/**/*", "lib/**/*"],
        "progress_categories": [{"id": c, "name": n} for c, n in sorted(categories.items())],
        "options": project.get("objdiff", {}).get("options", {}),
        "units": entries,
    }

    with open(ProjectPath("objdiff.json"), "w") as fh:
        json.dump(config, fh, indent=1)
        fh.write("\n")

    return len(categories)


def findOriginalImage(project):
    orig = ProjectPath("orig")

    if not orig.is_dir(): return None

    candidates = sorted(p for p in orig.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    if len(candidates) != 1: return None

    VerifyImageHash(candidates[0], project)

    return candidates[0]


def ensureExtracted(project):
    binaryPath = BinaryPath(project)

    if binaryPath.exists(): return

    image = findOriginalImage(project)

    if not image: sys.exit("%s is missing and orig/ holds no .3ds/.cxi/.cia/.cci to extract it from: run tools/extract.py by hand" % binaryPath)

    print("%s missing: extracting from %s" % (binaryPath, image.name))
    subprocess.run([sys.executable, "tools/extract.py", str(image)], cwd=ROOT, check=True)


def ensureAnalysed(force, clean):
    symbols = ProjectPath("config", "symbols.txt")
    splits = ProjectPath("config", "splits.txt")

    if not force and symbols.exists() and splits.exists(): return

    import regen

    regen.Pipeline(clean)


def main():
    parser = argparse.ArgumentParser(description="Generate build.ninja and objdiff.json from config/")
    parser.add_argument("--regen", action="store_true", help="run analysis pipeline even if config/symbols.txt and config/splits.txt already exist")
    parser.add_argument("--clean", action="store_true", help="start from empty symbols/splits (old one are stored in build/backup/ dw :3)")
    parser.add_argument("--apply-manual", action="store_true", help="only apply config/symbols.manual.txt and config/splits.manual.txt onto the generated symbols/splits, then stop")
    args = parser.parse_args()

    project = LoadProject()
    ensureExtracted(project)
    ensureAnalysed(args.regen, args.clean)
    ApplyManual(verbose=args.apply_manual)

    if args.apply_manual: return

    missing = FetchDependencies(project)

    if missing: print("warning: dependencies unavailable: %s" % ", ".join(missing), file=sys.stderr)

    roots = SourceRoots(project)
    includeDirs = ExistingPaths(project, project.get("include_dirs", ["include"]))
    commands, systems = WriteCompileCommands(project, roots, includeDirs, unitFlags)
    vscode = WriteVscodeConfig(project, includeDirs, systems)
    print("%d sources: compile_commands.json%s" % (commands, ", .vscode/c_cpp_properties.json" if vscode else ""))
    debugElf = DebugElfPath(project)
    debugFiles = WriteVscodeDebug(ToolPath("arm-none-eabi", "gdb"), ToolPath("ninja"), sys.executable, debugElf, GDB_PORT)

    if debugFiles: print("debugger: %s" % ", ".join(".vscode/" + f for f in debugFiles))
    units = ReadSplits()

    if not units: sys.exit("config/splits.txt is empty: run tools/regen.py (or configure.py --regen)")

    sources = {}

    for unit in units:
        source = findSource(unit.Name, roots)

        if source: sources[unit.Name] = source

    libraryUnits = LibraryUnits(units)
    writeNinja(project, units, sources, includeDirs, ThumbUnits(units), libraryUnits, debugElf)
    count = writeObjdiff(project, units, sources, libraryUnits)
    print("%d units in %d progress categories, %d with source, %d from compiler libraries: build.ninja, objdiff.json" % (len(units), count, len(sources), sum(1 for u in libraryUnits if u not in sources)))


if __name__ == "__main__":
    main()
