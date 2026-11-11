#!/usr/bin/env python3
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import ExpandPath, LoadProject, ProjectPath, ROOT, ToolPath

GENERATED = ["config/symbols.txt", "config/splits.txt"]

def step(title, args):
    began = time.time()
    print("== %s" % title, flush=True)
    result = subprocess.run([sys.executable] + args, cwd=ROOT)

    if result.returncode != 0: sys.exit("%s failed (exit %d)" % (title, result.returncode))

    print("   %.0fs" % (time.time() - began), flush=True)

def backupGenerated():
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = ProjectPath("build", "backup", stamp)
    for relative in GENERATED:
        source = ProjectPath(relative)
        if not source.exists(): continue

        backup.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), backup / source.name)

    return backup

def importNames(project):
    for entry in project.get("symbol_imports", []):
        path = ExpandPath(entry["path"], project)
        if not path.exists():
            print("   skipping missing import %s" % entry["path"])
            continue

        step("import %s %s" % (entry["format"], entry["path"]), ["tools/symbols.py", "import", entry["format"], str(path)] + (["--overwrite"] if entry.get("overwrite") else []))

def hasLibraries():
    from compiler import Find
    found = Find()

    return bool(found and found.LibDir.exists())

def Pipeline(clean=False):
    project = LoadProject()
    if clean: print("previous symbols/splits moved to %s" % backupGenerated())

    step("toolkit: function boundaries via 3dsdecomp-toolkit", ["tools/toolkit.py"])
    importNames(project)
    step("rtti", ["tools/rtti.py"])
    step("veneers", ["tools/symbols.py", "veneers"])
    if hasLibraries(): step("libmatch", ["tools/libmatch.py"])

    step("tidy", ["tools/tidy.py"])
    step("split", ["tools/split.py", "--stats"])
    step("configure", ["configure.py"])

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean", action="store_true", help="start from empty symbols/splits (previous ones are moved to build/backup/)")
    parser.add_argument("--no-build", action="store_true")
    args = parser.parse_args()
    Pipeline(args.clean)
    if args.no_build: return

    print("== build", flush=True)
    if subprocess.run([str(ToolPath("ninja"))], cwd=ROOT).returncode != 0: sys.exit("build failed")

    verifier = ProjectPath("testtools", "checktargets.py")
    if verifier.exists(): step("checktargets", [str(verifier.relative_to(ROOT))])

if __name__ == "__main__":
    main()