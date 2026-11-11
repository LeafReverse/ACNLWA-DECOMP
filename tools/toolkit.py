#!/usr/bin/env python3
import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import LoadProject, LoadSegments, ReadSymbols, Symbol, ToolPath, VerifyImageHash, WriteSymbols

IMAGE_SUFFIXES = (".3ds", ".cci", ".cxi", ".cia", ".app")
MODE_LINE = re.compile(r"^(ARM|THUMB)$")
EXPORT_LINE = re.compile(r"^EXPORT\s+\S*_([0-9A-Fa-f]+)$")
DCI_LINE = re.compile(r"^DCI\s")
DCB_LINE = re.compile(r"^DCB\s+(.*)$")

def findImage(explicit):
    if explicit: return Path(explicit).expanduser().resolve()

    orig = Path(__file__).resolve().parent.parent / "orig"
    candidates = sorted(p for p in orig.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    if len(candidates) == 1:
        VerifyImageHash(candidates[0], LoadProject())
        return candidates[0]
    
    if not candidates: sys.exit("no .3ds/.cxi/.cia/.cci image under orig/: pass one explicitly")

    sys.exit("orig/ has %d candidate images (%s): pass one explicitly" % (len(candidates), ", ".join(p.name for p in candidates)))

def runToolkit(image, keep):
    binary = ToolPath("3dsdecomp-toolkit")
    scratch = Path(tempfile.mkdtemp(prefix="3dsdecomp-toolkit-"))
    result = subprocess.run([str(binary), str(image)], cwd=scratch, capture_output=True, text=True)
    if result.stdout.strip(): print(result.stdout.strip())
    if result.returncode != 0:
        shutil.rmtree(scratch, ignore_errors=True)
        sys.exit("3dsdecomp-toolkit failed:\n" + result.stderr)

    if not keep: return scratch, scratch
    return scratch, None

def parseFunctions(outputDir):
    functions = []
    for path in sorted(outputDir.glob("*.s")):
        mode = "arm"
        addr = None
        size = 0
        for raw in path.read_text().splitlines():
            line = raw.strip()
            match = MODE_LINE.match(line)
            if match:
                mode = match.group(1).lower()
                continue

            match = EXPORT_LINE.match(line)
            if match:
                addr = int(match.group(1), 16)
                size = 0
                continue

            if addr is None: continue
            if line == "ENDP":
                functions.append((addr, mode, size))
                addr = None
                continue

            if DCI_LINE.match(line):
                size += 2 if mode == "thumb" else 4
                continue

            match = DCB_LINE.match(line)
            if match: size += len(match.group(1).split(","))

    return functions

def sectionName(segments, addr):
    seg = next((s for s in segments if s.Addr <= addr < s.End), None)
    return seg.Name if seg else None

def merge(functions, project):
    segments = LoadSegments(project)
    symbols = ReadSymbols()
    known = {s.Addr for s in symbols}
    added = 0
    for addr, mode, size in functions:
        if addr in known: continue
        section = sectionName(segments, addr)

        if section is None: continue
        attrs = {"mode": "thumb"} if mode == "thumb" else {}
        symbols.append(Symbol("sub_%X" % addr, section, addr, "function", size, attrs))
        known.add(addr)
        added += 1

    WriteSymbols(symbols)
    return added

def main():
    parser = argparse.ArgumentParser(description="Find function boundaries with 3dsdecomp-toolkit and merge them into config/symbols.txt")
    parser.add_argument("image", nargs="?", help="original .3ds/.cxi/.cia (decrypted); default: the only one under orig/")
    parser.add_argument("--dry-run", action="store_true", help="report counts, do not touch config/symbols.txt")
    parser.add_argument("--keep", action="store_true", help="keep the scratch run directory (printed) for inspection of output/, scatter.sct, build.ninja")
    args = parser.parse_args()
    image = findImage(args.image)
    print("image: %s" % image)
    cwd, scratch = runToolkit(image, args.keep)
    functions = parseFunctions(cwd / "output")
    print("%d functions parsed from %d chunk(s)" % (len(functions), len(list((cwd / "output").glob("*.s")))))
    if args.dry_run:
        print("dry run: config/symbols.txt untouched")
    else:
        added = merge(functions, LoadProject())
        print("%d new function(s) merged into config/symbols.txt" % added)

    if args.keep:
        print("scratch run kept at %s" % cwd)
    elif scratch:
        shutil.rmtree(scratch, ignore_errors=True)

if __name__ == "__main__":
    main()