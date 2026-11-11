#!/usr/bin/env python3
import os
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compiler import Require
from ctrproject import ROOT
from toolchain import DataDir

NOISE = re.compile(r"^(libEGL warning:|MESA-LOADER|pci id for fd |wine: .*\bwineboot\b|.*fixme:|\s*$)")
WINDOWS_DRIVE = re.compile(r"^([A-Za-z]):[\\/]")

def cleanStream(text):
    lines = [line.rstrip("\r") for line in text.splitlines()]
    return "\n".join(line for line in lines if not NOISE.match(line))

def winePrefix(compiler):
    return compiler.WinePrefix or DataDir() / "wineprefix"

def runnerEnv(compiler):
    env = dict(os.environ)
    env.update(compiler.Environment())
    if compiler.Runner != "wine": return env

    env["WINEPREFIX"] = str(winePrefix(compiler))
    env.setdefault("WINEDEBUG", "-all")
    env.setdefault("WINEDLLOVERRIDES", "mscoree,mshtml=")
    env.pop("DISPLAY", None)
    env.pop("WAYLAND_DISPLAY", None)

    return env

def hostDependency(path, compiler):
    if compiler.Runner != "wine": return path

    match = WINDOWS_DRIVE.match(path)
    if not match: return path

    rest = path[3:].replace("\\", "/")
    drive = match.group(1).lower()
    if drive == "z": return "/" + rest

    prefix = winePrefix(compiler)

    return str(prefix / "dosdevices" / (drive + ":") / rest)

def rewriteDepfile(raw, final, target, compiler):
    if not raw.exists(): return

    deps = []
    system = os.path.normcase(str(compiler.IncludeDir.resolve()))

    for line in raw.read_text(errors="replace").splitlines():
        _, sep, dep = line.partition(": ")
        if not sep: continue

        path = hostDependency(dep.strip().replace("\\ ", " "), compiler)
        if os.path.normcase(os.path.abspath(path)).startswith(system): continue

        deps.append(Path(path).as_posix().replace(" ", "\\ "))

    final.write_text("%s: %s\n" % (target, " \\\n  ".join(deps)))
    raw.unlink(missing_ok=True)

def main():
    if len(sys.argv) < 2: sys.exit("usage: cc.py <armcc|armasm|armlink|armar|fromelf> [--depfile out.d] args...")

    compiler = Require()
    program = sys.argv[1]
    args = sys.argv[2:]
    depfile = None
    raw = None
    if "--depfile" in args:
        index = args.index("--depfile")
        depfile = Path(args[index + 1])
        del args[index:index + 2]
        raw = Path("%s.%d.raw" % (depfile, os.getpid()))
        args += ["--depend=%s" % raw, "--depend_format=unix_escaped"]

    command = ([os.environ.get("WINE", "wine")] if compiler.Runner == "wine" else []) + [str(compiler.Executable(program))]
    result = subprocess.run(command + args, env=runnerEnv(compiler), cwd=ROOT, capture_output=True, text=True, errors="replace")
    out = cleanStream(result.stdout)
    err = cleanStream(result.stderr)
    if out: print(out)
    if err: print(err, file=sys.stderr)
    if depfile and result.returncode == 0:
        target = args[args.index("-o") + 1] if "-o" in args else ""
        rewriteDepfile(raw, depfile, target, compiler)

    sys.exit(result.returncode)

if __name__ == "__main__":
    main()