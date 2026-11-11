import json
from pathlib import Path

from ctrproject import ProjectPath, ROOT

SOURCE_GLOBS = ("*.cpp", "*.cc", "*.c")
CLANG_BASE = ["--target=armv6k-none-eabi", "-mcpu=mpcore", "-marm", "-mfloat-abi=hard", "-fshort-wchar", "-fno-short-enums", "-std=gnu++11", "-ffreestanding"]
FLAG_MAP = {
    "--signed_chars": ["-fsigned-char"],
    "--unsigned_chars": ["-funsigned-char"],
    "--no_rtti": ["-fno-rtti"],
    "--no_exceptions": ["-fno-exceptions"],
    "--thumb": ["-mthumb"],
}
VSCODE_CONFIG_NAME = "ctr-decomp"
DEBUG_LAUNCH_NAME = "game gdb"
DEBUG_VERBOSE_NAME = "game gdb and log"
DEBUG_BUILD_TASK = "ninja debug"
DEBUG_EMULATOR_TASK = "azahar gdb stub"
OWNED_ENTRIES = (DEBUG_LAUNCH_NAME, DEBUG_VERBOSE_NAME, DEBUG_BUILD_TASK, DEBUG_EMULATOR_TASK)
GENERATED_MARKER = "tools/emulator.py"
EDITOR_SHIM = "include/compat/editor_shim.h"

def ClangFlags(cflags):
    flags = list(CLANG_BASE) + ["-include", str(ROOT / EDITOR_SHIM)]
    i = 0
    while i < len(cflags):
        flag = cflags[i]
        if flag == "--preinclude" and i + 1 < len(cflags):
            flags += ["-include", str(ROOT / cflags[i + 1])]
            i += 2
            continue

        if flag.startswith("--preinclude="): flags += ["-include", str(ROOT / flag.split("=", 1)[1])]
        elif flag.startswith(("-D", "-U")): flags.append(flag)
        else: flags += FLAG_MAP.get(flag, [])

        i += 1

    return flags


def sourceFiles(roots):
    seen = set()
    for _, root in roots:
        for pattern in SOURCE_GLOBS:
            for path in sorted(root.rglob(pattern)):
                resolved = path.resolve()
                if resolved in seen or "build" in resolved.relative_to(root.resolve()).parts: continue

                seen.add(resolved)
                yield resolved

def systemIncludes():
    try:
        from compiler import Find
        found = Find()
    except SystemExit:
        found = None

    return [found.IncludeDir] if found and found.IncludeDir.exists() else []

def WriteCompileCommands(project, roots, includeDirs, unitFlags):
    compiler = project["compiler"]
    systems = systemIncludes()
    entries = []

    for source in sourceFiles(roots):
        flags = ClangFlags(unitFlags(compiler, unitNameFor(source, roots)))
        args = ["clang++" if source.suffix != ".c" else "clang"] + flags
        args += ["-I" + str(d) for d in includeDirs]
        args += ["-idirafter" + str(d) for d in systems]
        args += ["-c", str(source)]
        if source.suffix == ".c": args = [a for a in args if not a.startswith("-std=")] + ["-std=gnu99"]

        entries.append({"directory": str(ROOT), "file": str(source), "arguments": args})

    with open(ProjectPath("compile_commands.json"), "w") as fh:
        json.dump(entries, fh, indent=1)
        fh.write("\n")

    return len(entries), systems

def unitNameFor(source, roots):
    for prefix, root in roots:
        try:
            return prefix + source.relative_to(root.resolve()).with_suffix("").as_posix()
        except ValueError:
            continue

    return ""

def WriteVscodeConfig(project, includeDirs, systems):
    path = ProjectPath(".vscode", "c_cpp_properties.json")
    if path.exists():
        current = json.loads(path.read_text() or "{}")
        if not any(c.get("name") == VSCODE_CONFIG_NAME for c in current.get("configurations", [])): return False

    def show(directory):
        try:
            return "${workspaceFolder}/" + Path(directory).resolve().relative_to(ROOT).as_posix()
        except ValueError:
            return Path(directory).resolve().as_posix()

    cflags = project["compiler"].get("cflags", [])
    forced = [show(ROOT / EDITOR_SHIM)] + [show(ROOT / cflags[i + 1]) for i, f in enumerate(cflags[:-1]) if f == "--preinclude"]
    config = {
        "version": 4,
        "configurations": [{
            "name": VSCODE_CONFIG_NAME,
            "compileCommands": "${workspaceFolder}/compile_commands.json",
            "includePath": [show(d) for d in includeDirs] + [show(d) for d in systems],
            "forcedInclude": forced,
            "defines": [f[2:] for f in cflags if f.startswith("-D")],
            "compilerArgs": [a for a in CLANG_BASE if a.startswith(("--target", "-m"))],
            "cStandard": "gnu99",
            "cppStandard": "gnu++11",
            "intelliSenseMode": "clang-arm",
        }],
    }
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n")

    return True

def ownedOrMissing(path, key, elf):
    if not path.exists(): return True

    current = json.loads(path.read_text() or "{}")
    return any(isGenerated(entry, elf) for entry in current.get(key, []))

def isGenerated(entry, elf):
    if entry.get("name", entry.get("label")) in OWNED_ENTRIES: return True
    if entry.get("program", "").endswith(elf): return True

    return GENERATED_MARKER in entry.get("args", [])

def WriteVscodeDebug(gdb, ninja, python, elf, port):
    launchPath = ProjectPath(".vscode", "launch.json")
    tasksPath = ProjectPath(".vscode", "tasks.json")
    written = []
    if ownedOrMissing(launchPath, "configurations", elf):
        game = {
            "name": DEBUG_LAUNCH_NAME,
            "type": "cppdbg",
            "request": "launch",
            "program": "${workspaceFolder}/%s" % elf,
            "cwd": "${workspaceFolder}",
            "MIMode": "gdb",
            "miDebuggerPath": str(gdb),
            "miDebuggerServerAddress": "localhost:%d" % port,
            "targetArchitecture": "arm",
            "stopAtEntry": False,
            "setupCommands": [{"text": "set pagination off"}, {"text": "set print pretty on"}],
            "preLaunchTask": DEBUG_EMULATOR_TASK,
        }
        verbose = dict(game, name=DEBUG_VERBOSE_NAME, logging={"engineLogging": True, "trace": True})
        launch = {"version": "0.2.0", "configurations": [game, verbose]}
        launchPath.parent.mkdir(exist_ok=True)
        launchPath.write_text(json.dumps(launch, indent=2) + "\n")
        written.append(launchPath.name)

    if ownedOrMissing(tasksPath, "tasks", elf):
        tasks = {
            "version": "2.0.0",
            "tasks": [
                {
                    "label": DEBUG_BUILD_TASK,
                        "type": "process",
                    "command": str(ninja),
                    "args": ["debug"],
                    "options": {"cwd": "${workspaceFolder}"},
                    "problemMatcher": [],
                },
                {
                    "label": DEBUG_EMULATOR_TASK,
                        "type": "process",
                    "command": str(python),
                    "args": [GENERATED_MARKER, "--port", str(port)],
                    "options": {"cwd": "${workspaceFolder}"},
                    "dependsOn": DEBUG_BUILD_TASK,
                    "isBackground": True,
                    "problemMatcher": {
                        "owner": "azahar",
                        "pattern": {"regexp": "^__never__$"},
                        "background": {"activesBegins": True, "beginsPattern": ".", "endsPattern": "gdb stub ready on port"},
                    },
                },
            ],
        }
        tasksPath.write_text(json.dumps(tasks, indent=2) + "\n")
        written.append(tasksPath.name)

    return written