import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT_PATH = ROOT / "config" / "project.json"
PAGE_SIZE = 0x1000
SYMBOL_LINE = re.compile(r"^(?P<name>\S+)\s*=\s*(?P<section>[.\w]+):0x(?P<addr>[0-9A-Fa-f]+);\s*(?://\s*(?P<attrs>.*))?$")
SPLIT_RANGE = re.compile(r"^\s+(?P<section>[.\w]+)\s+start:0x(?P<start>[0-9A-Fa-f]+)\s+end:0x(?P<end>[0-9A-Fa-f]+)")
IDENT_BAD = re.compile(r"[^0-9A-Za-z_]")

@dataclass
class Segment:
    Name: str
    Addr: int
    Size: int
    Offset: int
    Kind: str

    @property
    def End(self):
        return self.Addr + self.Size

@dataclass
class Symbol:
    Name: str
    Section: str
    Addr: int
    Kind: str = "function"
    Size: int = 0
    Attrs: dict = field(default_factory=dict)

    @property
    def End(self):
        return self.Addr + self.Size

    @property
    def Thumb(self):
        return self.Attrs.get("mode") == "thumb"

@dataclass
class Unit:
    Name: str
    Ranges: list = field(default_factory=list)

def ProjectPath(*parts):
    return ROOT.joinpath(*parts)

def ExpandPath(value, project=None):
    text = os.path.expandvars(os.path.expanduser(value))
    for name in re.findall(r"\$\{(\w+)\}", text):
        root = DependencyRoot(project or LoadProject(), name)
        if root is None: return None

        text = text.replace("${%s}" % name, str(root))

    path = Path(text)
    return path if path.is_absolute() else ROOT / path

def DependencyRoot(project, name, fetch=False):
    dep = project.get("dependencies", {}).get(name)
    if dep is None: sys.exit("unknown dependency ${%s}" % name)

    candidates = [ROOT / p for p in dep.get("search", [])] + [ROOT / dep.get("path", "lib/" + name)]
    for candidate in candidates:
        if candidate.is_dir() and any(candidate.iterdir()): return candidate.resolve()
    if not fetch or not dep.get("repo"): return None

    target = candidates[-1]
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["git", "clone", "--depth", "1"] + (["--branch", dep["branch"]] if dep.get("branch") else []) + [dep["repo"], str(target)])

    return target.resolve() if result.returncode == 0 else None

def FetchDependencies(project):
    missing = []
    for name, dep in project.get("dependencies", {}).items():
        if DependencyRoot(project, name, fetch=True) is None and not dep.get("optional"): missing.append(name)

    return missing

def ExistingPaths(project, values):
    paths = []
    for value in values:
        path = ExpandPath(value, project)
        if path is not None and path.exists(): paths.append(path)

    return paths

def LoadProject():
    example = PROJECT_PATH.with_name("project.example.json")
    if not PROJECT_PATH.exists() and example.exists(): PROJECT_PATH.write_text(example.read_text())
    if not PROJECT_PATH.exists(): sys.exit("missing %s" % PROJECT_PATH)

    with open(PROJECT_PATH) as fh:
        return json.load(fh)

def SaveProject(project):
    with open(PROJECT_PATH, "w") as fh:
        json.dump(project, fh, indent=2)
        fh.write("\n")

def ParseInt(value):
    return int(value, 0) if isinstance(value, str) else int(value)

def pageAlign(value):
    return (value + PAGE_SIZE - 1) & ~(PAGE_SIZE - 1)

def LoadSegments(project):
    raw = project.get("segments")
    if not raw: sys.exit("project.json has no segments: run tools/extract.py with an exheader, or fill them in")

    segments = []
    offset = 0
    for entry in raw:
        size = ParseInt(entry["size"])
        kind = entry.get("kind", "code" if entry["name"] == ".text" else "data")
        fileOffset = ParseInt(entry["offset"]) if "offset" in entry else (None if kind == "bss" else offset)
        segments.append(Segment(entry["name"], ParseInt(entry["addr"]), size, fileOffset, kind))
        if kind != "bss": offset = pageAlign((fileOffset or 0) + size)

    return segments

class Binary:
    def __init__(self, data, segments):
        self.Data = data
        self.Segments = segments

    def SegmentOf(self, addr):
        for seg in self.Segments:
            if seg.Addr <= addr < seg.End: return seg

        return None

    def Read(self, addr, size):
        seg = self.SegmentOf(addr)
        if not seg or seg.Offset is None: return b""

        start = seg.Offset + addr - seg.Addr

        return self.Data[start:start + size]

    def Word(self, addr):
        return int.from_bytes(self.Read(addr, 4), "little")

    def InImage(self, addr):
        return self.SegmentOf(addr) is not None

def BinaryPath(project):
    return ExpandPath(os.environ.get("CTR_DECOMP_BIN") or project["binary"]["path"])

def DebugElfPath(project):
    return "build/%s.elf" % project.get("name", "game")

def VerifyHash(data, expected):
    for algo in ("sha1", "md5", "sha256"):
        want = expected.get(algo)
        if not want: continue

        got = hashlib.new(algo, data).hexdigest()
        if got.lower() != want.lower(): return "%s mismatch: got %s, expected %s" % (algo, got, want)

    return None

def VerifyImageHash(path, project):
    expected = project.get("image", {})
    data = path.read_bytes()
    if not any(expected.get(algo) for algo in ("sha1", "md5", "sha256")):
        project["image"] = {"md5": hashlib.md5(data).hexdigest(), "sha1": hashlib.sha1(data).hexdigest()}
        SaveProject(project)
        print("%s: no image hash pinned yet, trusting it and recording md5/sha1 in config/project.json \"image\"" % path.name, file=sys.stderr)
        return

    error = VerifyHash(data, expected)
    if error: sys.exit("%s: %s (wrong dump? check config/project.json \"image\", or delete that entry to re-pin)" % (path, error))

def LoadBinary(project, verify=True):
    path = BinaryPath(project)
    if not path.exists(): sys.exit("binary not found: %s (run tools/extract.py or set CTR_DECOMP_BIN)" % path)

    data = path.read_bytes()
    error = VerifyHash(data, project["binary"]) if verify else None
    if error: sys.exit("%s: %s" % (path, error))

    return Binary(data, LoadSegments(project))

def parseAttrs(text):
    attrs = {}
    for token in (text or "").split():
        key, sep, value = token.partition(":")
        if sep: attrs[key] = value

    return attrs

def ReadSymbols(path=None):
    path = Path(path or ProjectPath("config", "symbols.txt"))
    symbols = []
    if not path.exists(): return symbols
    for line in path.read_text().splitlines():
        match = SYMBOL_LINE.match(line.strip())
        if not match: continue

        attrs = parseAttrs(match.group("attrs"))
        kind = attrs.pop("type", "function")
        size = int(attrs.pop("size", "0"), 0)
        symbols.append(Symbol(match.group("name"), match.group("section"), int(match.group("addr"), 16), kind, size, attrs))

    symbols.sort(key=lambda s: s.Addr)
    return symbols

def WriteSymbols(symbols, path=None):
    path = Path(path or ProjectPath("config", "symbols.txt"))
    lines = []

    for sym in sorted(symbols, key=lambda s: (s.Addr, s.Name)):
        attrs = " ".join("%s:%s" % kv for kv in sym.Attrs.items())
        lines.append("%s = %s:0x%08X; // type:%s size:0x%X%s" % (sym.Name, sym.Section, sym.Addr, sym.Kind, sym.Size, (" " + attrs) if attrs else ""))

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")

def ReadSplits(path=None):
    path = Path(path or ProjectPath("config", "splits.txt"))
    units = []
    current = None
    if not path.exists(): return units
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("#"): continue
        if not line[0].isspace() and line.rstrip().endswith(":"):
            name = line.rstrip()[:-1]
            current = None if name == "Sections" else Unit(re.sub(r"\.(cpp|c|cc|s)$", "", name))
            if current: units.append(current)

            continue

        match = SPLIT_RANGE.match(line)
        if current and match: current.Ranges.append((match.group("section"), int(match.group("start"), 16), int(match.group("end"), 16)))

    return units

def WriteSplits(units, segments, path=None, ext=".cpp"):
    path = Path(path or ProjectPath("config", "splits.txt"))
    lines = ["Sections:"]
    for seg in segments:
        lines.append("\t%-12s type:%s start:0x%08X end:0x%08X" % (seg.Name, seg.Kind, seg.Addr, seg.End))

    for unit in units:
        lines += ["", unit.Name + ext + ":"]
        lines += ["\t%-12s start:0x%08X end:0x%08X" % r for r in unit.Ranges]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")

def ToolPath(name, key=None):
    sys.path.insert(0, str(ROOT / "tools"))
    import toolchain

    path = toolchain.Resolve(name, key)
    if not path and toolchain.Install(name): path = toolchain.Resolve(name, key)
    if not path: sys.exit("%s%s is unavailable on %s: see tools.json" % (name, ":" + key if key else "", toolchain.HostPlatform()))

    return path

def Demangle(names):
    names = list(names)
    mangled = [n for n in names if n.startswith("_Z")]
    if not mangled: return {n: n for n in names}

    result = subprocess.run([str(ToolPath("arm-none-eabi", "cxxfilt"))], input="\n".join(mangled) + "\n", capture_output=True, text=True, check=True)
    table = dict(zip(mangled, result.stdout.splitlines()))
    return {n: table.get(n, n) for n in names}

def SplitQualified(name):
    parts = []
    depth = 0
    start = 0
    i = 0
    length = len(name)
    while i < length:
        ch = name[i]

        if ch in "<(": depth += 1
        elif ch in ">)": depth -= 1
        elif ch == ":" and depth == 0 and name.startswith("::", i):
            parts.append(name[start:i])
            i += 2
            start = i
            continue

        i += 1

    parts.append(name[start:])
    return [p for p in parts if p]

def StripSignature(demangled):
    depth = 0
    for i, ch in enumerate(demangled):
        if ch == "<": depth += 1
        elif ch == ">": depth -= 1
        elif ch == "(" and depth == 0 and not demangled.startswith("operator", max(0, i - 8)) and i: return demangled[:i]

    return demangled

def QualifiedParts(name, demangled=None):
    text = StripSignature(demangled or name)
    if " " in text.split("<")[0] and not text.startswith("operator"): text = text.split(" ", 1)[1]

    return SplitQualified(text)

def SanitizeComponent(text):
    clean = IDENT_BAD.sub("_", text).strip("_")
    return clean or "_"

def PlaceholderName(qualified):
    parts = SplitQualified(qualified)
    if len(parts) < 2: return SanitizeComponent(qualified)

    encoded = []
    for i, part in enumerate(parts):
        clean = SanitizeComponent(part)
        if i == len(parts) - 1 and part == parts[i - 1]: encoded.append("C1")
        elif i == len(parts) - 1 and part == "~" + parts[i - 1]: encoded.append("D1")
        else: encoded.append("%d%s" % (len(clean), clean))

    return "_ZN%sEv" % "".join(encoded)
