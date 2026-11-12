#!/usr/bin/env python3
import argparse
import glob
import json
import os
import platform
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import LoadProject, ROOT
from toolchain import DataDir, LoadManifest

ARM_DIRS = ("Program Files/ARM", "Program Files (x86)/ARM")
BIN_SUBDIR = "win_32-pentium"

@dataclass
class Compiler:
    Name: str
    BinDir: Path
    IncludeDir: Path
    LibDir: Path
    License: Path
    Runner: str
    WinePrefix: Path = None
    EnvPrefix: str = "RVCT40"

    def Executable(self, program):
        return self.BinDir / (program + ".exe")

    def HostPath(self, path):
        if self.Runner != "wine": return str(path)

        return "Z:" + str(Path(path).resolve()).replace("/", "\\")

    def Environment(self):
        env = {
            self.EnvPrefix + "BIN": self.HostPath(self.BinDir),
            self.EnvPrefix + "INC": self.HostPath(self.IncludeDir),
            self.EnvPrefix + "LIB": self.HostPath(self.LibDir),
        }
        if os.environ.get("ARMLMD_LICENSE_FILE") or os.environ.get("LM_LICENSE_FILE"): return env
        if self.WinePrefix is not None and registryLicense(self.WinePrefix): return env
        if self.License.exists(): env["ARMLMD_LICENSE_FILE"] = self.HostPath(self.License)

        return env

def registryLicense(prefix):
    for name in ("user.reg", "system.reg"):
        path = Path(prefix) / name
        if path.exists() and "ARMLMD_LICENSE_FILE" in path.read_text(errors="replace"): return True

    return False

def compilerInfo(name):
    info = LoadManifest().get("compilers", {}).get(name)
    if not info: sys.exit("unknown compiler %s (see \"compilers\" in tools.json)" % name)

    return info

def hostRunner(info):
    system = {"Windows": "windows", "Darwin": "macos"}.get(platform.system(), "linux")

    return info.get("runner", {}).get(system, "native" if system == "windows" else "wine")

def fromNormalized(name, root, info, prefix=None):
    bin = root / "bin"
    if not (bin / "armcc.exe").exists(): return None

    include = root / "include" / "windows" if (root / "include" / "windows").exists() else root / "include"
    return Compiler(name, bin, include, root / "lib", root / "license.lic", hostRunner(info), prefix, info.get("env_prefix", "RVCT40"))

def fromInstall(name, armDir, info, prefix=None):
    versionDir = info.get("version_dir", "4.0/400")
    bin = armDir / "RVCT" / "Programs" / versionDir / BIN_SUBDIR
    if not (bin / "armcc.exe").exists(): return None

    data = armDir / "RVCT" / "Data" / versionDir
    return Compiler(name, bin, data / "include" / "windows", data / "lib", armDir / "Licenses" / "license.lic", hostRunner(info), prefix, info.get("env_prefix", "RVCT40"))

def registryPath():
    return DataDir() / "compilers.json"

def registeredPrefixes():
    path = registryPath()
    if not path.exists(): return []

    return json.loads(path.read_text()).get("wineprefixes", [])

def installedBuild(root):
    for readme in sorted(root.glob("Readme*eng*.htm*")):
        match = re.search(r"[Bb]uild\s+(\d+)", readme.read_text(errors="replace"))
        if match: return match.group(1)

    return None

def nintendoBuild(root):
    marker = root / "sw" / "info" / "build.txt"
    if marker.exists(): return marker.read_text().strip()

    return installedBuild(root)

def fromNintendo(name, armDir, info, prefix=None):
    for root in sorted(armDir.glob("*")):
        if not (root / "bin" / "armcc.exe").exists(): continue
        if info.get("build") and nintendoBuild(root) != info["build"]: continue

        licenses = sorted((root / "sw" / "info").glob("*.lic"))
        license = licenses[0] if licenses else root / "license.lic"
        return Compiler(name, root / "bin", root / "include", root / "lib", license, hostRunner(info), prefix, info.get("env_prefix", "ARMCC41"))

    return None

def winePrefixes():
    home = Path.home()
    candidates = [os.environ.get("WINEPREFIX"), home / ".wine"] + registeredPrefixes()
    candidates += glob.glob(str(home / ".wine*"))
    candidates += glob.glob(str(home / ".local" / "share" / "*" / "drive_c" / ".."))
    candidates += glob.glob(str(home / ".local" / "share" / "wineprefixes" / "*"))
    seen = []

    for candidate in candidates:
        if not candidate: continue

        path = Path(candidate).resolve()
        if (path / "drive_c").is_dir() and path not in seen: seen.append(path)

    return seen

def installRoots():
    if platform.system() == "Windows":
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            if os.environ.get(var): yield Path(os.environ[var]) / "ARM", None

        return

    for prefix in winePrefixes():
        for sub in ARM_DIRS: yield prefix / "drive_c" / sub, prefix

def ProjectCompilerName():
    return os.environ.get("CTR_COMPILER") or LoadProject()["compiler"]["name"]

def Find(name=None):
    name = name or ProjectCompilerName()
    info = compilerInfo(name)
    override = os.environ.get("CTR_COMPILER_DIR")
    if override:
        found = fromNormalized(name, Path(override), info) or fromInstall(name, Path(override), info)
        if not found: sys.exit("CTR_COMPILER_DIR=%s holds no %s" % (override, name))

        return found

    for root in (ROOT / "compilers" / name, DataDir() / "compilers" / name):
        found = fromNormalized(name, root, info)
        if found: return found

    locate = fromNintendo if info.get("layout") == "nintendo" else fromInstall
    for armDir, prefix in installRoots():
        found = locate(name, armDir, info, prefix)
        if found: return found

    return None

def DiscoverAll():
    found = {}
    nintendo = {"layout": "nintendo", "product": "ARMCC 4.1 for Nintendo", "env_prefix": "ARMCC41"}

    for armDir, prefix in installRoots():
        if not armDir.is_dir(): continue

        for root in sorted(armDir.glob("*")):
            build = installedBuild(root) if (root / "bin" / "armcc.exe").exists() else None
            if not build: continue

            name = "armcc-4.1-%s" % build
            compiler = fromNintendo(name, armDir, dict(nintendo, build=build), prefix)
            if compiler: found.setdefault(name, compiler)

    for name in LoadManifest().get("compilers", {}):
        if name in found: continue

        try:
            compiler = Find(name)
        except SystemExit:
            compiler = None

        if compiler: found[name] = compiler

    return found

def Require(name=None):
    found = Find(name)
    if found: return found

    name = name or ProjectCompilerName()
    sys.exit("%s not found. It is proprietary, so it cannot be downloaded: run\n  python tools/compiler.py import <your RVCT install, ARM folder or wine prefix>\nonce, or drop it into compilers/%s/ (bin/, include/, license.lic)." % (name, name))

def locateArmDir(source):
    source = Path(source).expanduser().resolve()
    for candidate in [source, source / "ARM"] + [source / "drive_c" / sub for sub in ARM_DIRS]:
        if (candidate / "RVCT").is_dir(): return candidate

    if (source / "Programs").is_dir(): return source.parent

    return None

def cmdImport(args):
    name = args.name or LoadProject()["compiler"]["name"]
    info = compilerInfo(name)
    armDir = locateArmDir(args.source)
    found = fromInstall(name, armDir, info) if armDir else fromNormalized(name, Path(args.source), info)
    if not found: sys.exit("no %s under %s" % (name, args.source))

    dest = DataDir() / "compilers" / name
    if dest.exists(): shutil.rmtree(dest)

    shutil.copytree(found.BinDir, dest / "bin")
    shutil.copytree(found.IncludeDir, dest / "include" / "windows")
    if args.with_lib and found.LibDir.exists(): shutil.copytree(found.LibDir, dest / "lib")
    if found.License.exists(): shutil.copyfile(found.License, dest / "license.lic")

    print("%s imported into %s" % (name, dest))

def cmdRegister(args):
    prefix = Path(args.prefix).expanduser().resolve()
    if not (prefix / "drive_c").is_dir(): sys.exit("%s is not a wine prefix (no drive_c/)" % prefix)

    prefixes = [p for p in registeredPrefixes() if Path(p) != prefix] + [str(prefix)]
    registryPath().parent.mkdir(parents=True, exist_ok=True)
    registryPath().write_text(json.dumps({"wineprefixes": prefixes}, indent=2) + "\n")
    print("registered %s (%d prefixes in %s)" % (prefix, len(prefixes), registryPath()))

def cmdFind(args):
    found = Find(args.name)
    if not found: sys.exit("not found")

    print("%s  runner=%s%s\n  bin      %s\n  include  %s\n  license  %s" % (found.Name, found.Runner, "  prefix=%s" % found.WinePrefix if found.WinePrefix else "", found.BinDir, found.IncludeDir, found.License))

def main():
    parser = argparse.ArgumentParser(description="Locate or import the vendor compiler named in config/project.json")
    sub = parser.add_subparsers(dest="cmd", required=True)
    find = sub.add_parser("find")
    find.add_argument("--name")
    find.set_defaults(func=cmdFind)
    imp = sub.add_parser("import", help="copy an existing install into the shared compilers directory")
    imp.add_argument("source", help="RVCT install, its ARM folder, or a wine prefix holding one")
    imp.add_argument("--name")
    imp.add_argument("--with-lib", action="store_true", help="also copy the C library (only needed to link)")
    imp.set_defaults(func=cmdImport)
    reg = sub.add_parser("register", help="remember a wine prefix that holds a compiler (searched by every project on this machine)")
    reg.add_argument("prefix")
    reg.set_defaults(func=cmdRegister)
    args = parser.parse_args()
    args.func(args)

if __name__ == "__main__":
    main()