#!/usr/bin/env python3
import argparse
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ctrproject import LoadProject, ProjectPath, VerifyImageHash
from toolkit import IMAGE_SUFFIXES

DEFAULT_PORT = 24689
EXECUTABLES = ("azahar", "azahar.AppImage", "azahar-qt", "Azahar.AppImage")
FLATPAK_ID = "org.azahar_emu.Azahar"
SEARCH_DIRS = ("~/.local/bin", "~/Applications", "~/bin", "/opt/azahar", "/Applications/Azahar.app/Contents/MacOS", "~/AppData/Local/Programs/Azahar", "C:/Program Files/Azahar")
READY_TIMEOUT = 60
READY_LINE = "gdb stub ready on port %d"

def findEmulator():
    override = os.environ.get("AZAHAR")
    if override: return [override]
    for name in EXECUTABLES:
        found = shutil.which(name)
        if found: return [found]

    for directory in SEARCH_DIRS:
        for name in EXECUTABLES + ("azahar.exe", "azahar-qt.exe"):
            candidate = Path(directory).expanduser() / name
            if candidate.is_file(): return [str(candidate)]

    if shutil.which("flatpak") and subprocess.run(["flatpak", "info", FLATPAK_ID], capture_output=True).returncode == 0: return ["flatpak", "run", FLATPAK_ID]

    sys.exit("Azahar not found: install it (https://azahar-emu.org) or set AZAHAR=/path/to/azahar")

def findImage(explicit):
    if explicit: return Path(explicit).expanduser().resolve()

    candidates = sorted(p for p in ProjectPath("orig").iterdir() if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    if len(candidates) != 1: sys.exit("put exactly one .3ds/.cci/.cxi/.cia in orig/ (found %d) or pass --image" % len(candidates))

    VerifyImageHash(candidates[0], LoadProject())

    return candidates[0]

def listening(port):
    with socket.socket() as sock:
        sock.settimeout(0.2)

        return sock.connect_ex(("127.0.0.1", port)) == 0

def emulatorEnv():
    env = dict(os.environ)
    if sys.platform.startswith("linux") and env.get("WAYLAND_DISPLAY") and env.get("DISPLAY"): env["QT_QPA_PLATFORM"] = "xcb"

    return env

def main():
    # TODO: INSERT A COPY OF THE DECOMP CODE, INSTEAD OF USING ORIGINAL GAME, BETTER FOR RE, AND ALSO ALLOW US TO SEE WHAT WE FUCKED
    parser = argparse.ArgumentParser(description="Start with Azahar with GDB launching **original** game")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--image", help="game image (default: the only one under orig/)")
    args = parser.parse_args()
    if listening(args.port):
        print(READY_LINE % args.port, flush=True)
        return

    process = subprocess.Popen(findEmulator() + ["-g", str(args.port), str(findImage(args.image))], env=emulatorEnv())
    deadline = time.monotonic() + READY_TIMEOUT
    while not listening(args.port):
        if process.poll() is not None: sys.exit("Azahar exited with code %d before its gdb stub came up, something is fucked up tbh" % process.returncode)
        if time.monotonic() > deadline: sys.exit("Azahar's gdb stub did not open port %d within %ds :ccc" % (args.port, READY_TIMEOUT))

        time.sleep(0.2)

    print(READY_LINE % args.port, flush=True)
    process.wait()

if __name__ == "__main__":
    main()