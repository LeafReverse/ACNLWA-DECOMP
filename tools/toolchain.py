#!/usr/bin/env python3
import argparse
import glob
import json
import os
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = ROOT / "tools.json"
ARCHIVE_FORMATS = {"zip": "zip", "tar.gz": "gztar", "tar.xz": "xztar", "tar.bz2": "bztar"}
CHUNK_SIZE = 1 << 20

def HostPlatform():
    system = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system())
    machine = platform.machine().lower()
    arch = {"amd64": "x86_64", "x64": "x86_64", "arm64": "aarch64" if system == "linux" else "arm64", "aarch64": "aarch64" if system != "macos" else "arm64"}.get(machine, machine)
    if system == "windows" and arch == "aarch64": arch = "arm64"

    return "%s-%s" % (system, arch)

def LoadManifest():
    with open(MANIFEST_PATH) as fh:
        return json.load(fh)

def DataDir():
    custom = os.environ.get("CTR_DECOMP_HOME")
    if custom: return Path(custom)

    system = platform.system()
    if system == "Windows": return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "ctr-decomp"
    if system == "Darwin": return Path.home() / "Library" / "Application Support" / "ctr-decomp"

    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "ctr-decomp"

def InstallDir(manifest=None):
    custom = os.environ.get("CTR_DECOMP_TOOLS")
    return Path(custom) if custom else DataDir() / "tools"

def toolDir(manifest, name):
    tool = manifest["tools"][name]
    return InstallDir(manifest) / name / tool.get("version", "system")

def pickDownload(tool):
    downloads = tool.get("downloads", {})
    return downloads.get(HostPlatform()) or downloads.get("any")

def resolvePattern(base, pattern):
    exe = ".exe" if HostPlatform().startswith("windows") else ""
    for candidate in (pattern + exe, pattern):
        hits = sorted(glob.glob(str(base / candidate), recursive=True))
        if hits: return Path(hits[0])

    return None

def Resolve(name, key=None, manifest=None):
    manifest = manifest or LoadManifest()
    tool = manifest["tools"][name]
    bins = tool.get("bin", {})
    key = key or next(iter(bins))
    override = os.environ.get("CTR_TOOL_" + key.upper().replace("-", "_"))
    if override: return Path(override)
    if tool.get("build") is not None: return resolvePattern(toolDir(manifest, name), bins[key])
    if tool.get("system") is not None or not tool.get("downloads"):
        found = shutil.which(bins.get(key, key))
        return Path(found) if found else None

    hit = resolvePattern(toolDir(manifest, name), bins[key])
    if hit: return hit

    fallback = tool.get("system_fallback")
    found = shutil.which(fallback) if fallback else None
    return Path(found) if found else None

def download(url, dest):
    request = urllib.request.Request(url, headers={"User-Agent": "ctr-decomp"})
    with urllib.request.urlopen(request, timeout=120) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(CHUNK_SIZE)

            if not chunk: break
            out.write(chunk)
            done += len(chunk)

            if total and sys.stderr.isatty(): sys.stderr.write("\r  %5.1f%% of %d MiB" % (100 * done / total, total >> 20))

    if sys.stderr.isatty(): sys.stderr.write("\n")

def markExecutable(base, tool):
    for pattern in tool.get("bin", {}).values():
        hit = resolvePattern(base, pattern)
        if not hit or not hit.is_file(): continue

        hit.chmod(hit.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    for script in base.glob("**/support/*Headless*"):
        script.chmod(script.stat().st_mode | stat.S_IXUSR)

    for script in base.glob("**/bin/*"):
        if script.is_file(): script.chmod(script.stat().st_mode | stat.S_IXUSR)

def buildFromSource(name, tool, manifest, force):
    build = tool["build"]
    base = toolDir(manifest, name)
    stamp = base / ".built"
    if stamp.exists() and not force: return True

    git = shutil.which("git")
    cmake = shutil.which("cmake")
    if not git or not cmake:
        print("%s: needs git and cmake on PATH to build from source" % name, file=sys.stderr)
        return False

    if base.exists(): shutil.rmtree(base)

    base.mkdir(parents=True)
    print("%s <- building %s@%s" % (name, build["git"], build["ref"]), file=sys.stderr)
    clone = subprocess.run([git, "clone", build["git"], str(base)], capture_output=True, text=True)
    if clone.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        sys.exit("%s: git clone failed:\n%s" % (name, clone.stderr))

    checkout = subprocess.run([git, "-C", str(base), "checkout", "--quiet", build["ref"]], capture_output=True, text=True)
    if checkout.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        sys.exit("%s: git checkout %s failed:\n%s" % (name, build["ref"], checkout.stderr))

    buildDir = base / "build"
    configureArgs = [cmake, "-S", str(base), "-B", str(buildDir), "-DCMAKE_BUILD_TYPE=Release"]
    if not HostPlatform().startswith("windows"): configureArgs.append("-DCMAKE_CXX_FLAGS=-include vector")
    configure = subprocess.run(configureArgs, capture_output=True, text=True)
    if configure.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        sys.exit("%s: cmake configure failed:\n%s" % (name, configure.stderr))

    jobs = str(os.cpu_count() or 1)
    compile = subprocess.run([cmake, "--build", str(buildDir), "--config", "Release", "--parallel", jobs], capture_output=True, text=True)
    if compile.returncode != 0:
        shutil.rmtree(base, ignore_errors=True)
        sys.exit("%s: build failed:\n%s" % (name, compile.stderr))

    markExecutable(base, tool)
    stamp.write_text(build["ref"] + "\n")

    return True

def Install(name, force=False, manifest=None, seen=None):
    manifest = manifest or LoadManifest()
    seen = seen if seen is not None else set()
    if name in seen: return True

    seen.add(name)
    tool = manifest["tools"][name]
    for dep in tool.get("depends", []): Install(dep, force, manifest, seen)
    if tool.get("build") is not None: return buildFromSource(name, tool, manifest, force)
    if tool.get("system") is not None:
        if Resolve(name, manifest=manifest): return True

        hints = tool["system"].get(HostPlatform().split("-")[0], [])
        print("%s: not found on PATH, install it with one of: %s" % (name, " | ".join(hints)), file=sys.stderr)
        return False

    entry = pickDownload(tool)
    if not entry:
        print("%s: no build published for %s" % (name, HostPlatform()), file=sys.stderr)
        return False

    base = toolDir(manifest, name)
    stamp = base / ".installed"
    if stamp.exists() and not force: return True
    if base.exists(): shutil.rmtree(base)

    base.mkdir(parents=True)
    print("%s %s <- %s" % (name, tool.get("version", ""), entry["url"]), file=sys.stderr)
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        archive = Path(tmp) / "download"
        download(entry["url"], archive)
        if entry["archive"] == "raw":
            target = base / (next(iter(tool["bin"].values())) + (".exe" if entry["url"].endswith(".exe") else ""))
            shutil.move(str(archive), target)
        else:
            shutil.unpack_archive(str(archive), str(base), ARCHIVE_FORMATS[entry["archive"]])

    markExecutable(base, tool)
    stamp.write_text(entry["url"] + "\n")

    return True

def cmdList(args):
    manifest = LoadManifest()
    host = HostPlatform()
    print("host: %s   install dir: %s" % (host, InstallDir(manifest)))
    for name, tool in manifest["tools"].items():
        path = Resolve(name, manifest=manifest)
        available = "source" if tool.get("build") is not None else ("system" if tool.get("system") is not None else ("yes" if pickDownload(tool) else "no"))
        state = str(path) if path else "-"
        print("  %-14s %-12s req=%-5s build=%-6s %s" % (name, tool.get("version", ""), tool.get("required", False), available, state))

def cmdInstall(args):
    manifest = LoadManifest()
    required = [n for n, t in manifest["tools"].items() if t.get("required")]
    names = list(args.names)
    if args.required or not names: names = required + [n for n in names if n not in required]
    if args.all: names = list(manifest["tools"])

    unknown = [n for n in names if n not in manifest["tools"]]
    if unknown: sys.exit("unknown tool(s): " + ", ".join(unknown))

    failed = [n for n in names if not Install(n, args.force, manifest)]
    if failed: sys.exit("failed: " + ", ".join(failed))

def cmdWhich(args):
    name, _, key = args.tool.partition(":")
    path = Resolve(name, key or None)
    if not path: sys.exit("%s is not installed (python tools/toolchain.py install %s)" % (args.tool, name))

    print(path)

def main():
    parser = argparse.ArgumentParser(description="Fetch and locate the tools listed in tools.json")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmdList)
    install = sub.add_parser("install")
    install.add_argument("names", nargs="*")
    install.add_argument("--required", action="store_true")
    install.add_argument("--all", action="store_true")
    install.add_argument("--force", action="store_true")
    install.set_defaults(func=cmdInstall)
    which = sub.add_parser("which")
    which.add_argument("tool", help="name or name:bin, e.g. arm-none-eabi:objdump")
    which.set_defaults(func=cmdWhich)
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()