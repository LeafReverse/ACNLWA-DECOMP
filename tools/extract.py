#!/usr/bin/env python3
import argparse
import hashlib
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import ExpandPath, LoadProject, SaveProject, ToolPath, VerifyHash

IMAGE_TYPES = {".cia": "cia", ".3ds": "ncsd", ".cci": "ncsd", ".cxi": "ncch", ".app": "ncch"}
EXHEADER_MIN_SIZE = 0x40

def ParseExheader(blob):
    if len(blob) < EXHEADER_MIN_SIZE: sys.exit("exheader too short (%d bytes)" % len(blob))

    title = blob[0:8].rstrip(b"\0").decode("ascii", "replace")
    flags = blob[0x0D]
    textAddr, _, textSize = struct.unpack_from("<III", blob, 0x10)
    roAddr, _, roSize = struct.unpack_from("<III", blob, 0x20)
    dataAddr, _, dataSize = struct.unpack_from("<III", blob, 0x30)
    bssSize = struct.unpack_from("<I", blob, 0x3C)[0]
    return {
        "title": title,
        "compressed": bool(flags & 1),
        "segments": [
            {"name": ".text", "kind": "code", "addr": "0x%X" % textAddr, "size": "0x%X" % textSize},
            {"name": ".rodata", "kind": "rodata", "addr": "0x%X" % roAddr, "size": "0x%X" % roSize},
            {"name": ".data", "kind": "data", "addr": "0x%X" % dataAddr, "size": "0x%X" % dataSize},
            {"name": ".bss", "kind": "bss", "addr": "0x%X" % (dataAddr + dataSize), "size": "0x%X" % bssSize},
        ],
    }

def runCtrtool(args):
    result = subprocess.run([str(ToolPath("ctrtool"))] + args, capture_output=True, text=True)

    if result.returncode != 0: sys.exit("ctrtool failed:\n" + result.stdout + result.stderr)

def extractImage(image, workdir, keys):
    kind = IMAGE_TYPES.get(image.suffix.lower())
    if not kind: sys.exit("unknown image type %s (expected .cia/.3ds/.cci/.cxi or a code.bin)" % image.suffix)

    exefs = workdir / "exefs"
    exheader = workdir / "exheader.bin"
    runCtrtool(keys + ["-t", kind, "-n", "0", "--exheader=%s" % exheader, "--exefsdir=%s" % exefs, str(image)])
    code = exefs / "code.bin"
    if not code.exists(): code = exefs / ".code.bin"
    if not code.exists(): sys.exit("ctrtool produced no code.bin; is the image decrypted or are keys/seeddb supplied?")

    return code, exheader if exheader.exists() else None

def decompressCode(code, workdir):
    out = workdir / "code.decompressed.bin"
    runCtrtool(["-t", "lzss", "--lzssout=%s" % out, str(code)])
    return out

def main():
    parser = argparse.ArgumentParser(description="Bring a 3DS executable into the project: orig/code.bin + orig/exheader.bin")
    parser.add_argument("input", help="code.bin, or a .cia/.3ds/.cci/.cxi image")
    parser.add_argument("--exheader", help="exheader.bin matching a bare code.bin")
    parser.add_argument("--seeddb", help="seeddb.bin for seed-encrypted titles")
    parser.add_argument("--dev", action="store_true", help="development-unit crypto")
    parser.add_argument("--no-verify", action="store_true")
    args = parser.parse_args()
    project = LoadProject()
    source = Path(args.input).expanduser().resolve()
    destCode = ExpandPath(project["binary"]["path"])
    destExheader = ExpandPath(project["binary"].get("exheader", str(destCode.parent / "exheader.bin")))
    destCode.parent.mkdir(parents=True, exist_ok=True)
    keys = (["--seeddb=%s" % args.seeddb] if args.seeddb else []) + (["-d"] if args.dev else [])

    with tempfile.TemporaryDirectory() as tmp:
        workdir = Path(tmp)
        isImage = source.suffix.lower() in IMAGE_TYPES
        code, exheader = extractImage(source, workdir, keys) if isImage else (source, Path(args.exheader).expanduser() if args.exheader else None)
        info = ParseExheader(exheader.read_bytes()) if exheader else None
        if info and info["compressed"] and not isImage: code = decompressCode(code, workdir)

        data = code.read_bytes()
        if not args.no_verify:
            error = VerifyHash(data, project["binary"])
            if error: sys.exit("%s: %s" % (source, error))

        if code != destCode: shutil.copyfile(code, destCode)
        if exheader and exheader.resolve() != destExheader.resolve(): shutil.copyfile(exheader, destExheader)

    print("code.bin  %s  md5=%s sha1=%s" % (destCode, hashlib.md5(data).hexdigest(), hashlib.sha1(data).hexdigest()))
    pinned = not any(project["binary"].get(k) for k in ("md5", "sha1", "sha256"))

    if pinned:
        project["binary"]["md5"] = hashlib.md5(data).hexdigest()
        project["binary"]["sha1"] = hashlib.sha1(data).hexdigest()
        SaveProject(project)
        print("  hashes pinned in config/project.json")

    if not info:
        if not project.get("segments"): print("no exheader: fill config/project.json \"segments\" by hand", file=sys.stderr)
        return

    project["segments"] = info["segments"]
    project.setdefault("title", info["title"])
    SaveProject(project)

    for seg in info["segments"]: print("  %-8s %s size %s" % (seg["name"], seg["addr"], seg["size"]))

if __name__ == "__main__":
    main()