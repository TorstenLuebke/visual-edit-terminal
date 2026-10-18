#!/usr/bin/env python3
"""Startet das installierte ShellDeck zur manuellen Reproduktion unter GDB."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess


def run(directory: Path, executable: str, platform: str) -> int:
    gdb = shutil.which("gdb")
    binary = shutil.which(executable) if "/" not in executable else executable
    if not gdb:
        print("FEHLER: gdb fehlt. Ubuntu: sudo apt install gdb")
        return 2
    if not binary or not Path(binary).is_file():
        print(f"FEHLER: ausführbare Datei nicht gefunden: {executable}")
        return 2
    directory.mkdir(parents=True, exist_ok=True)
    command_file = directory / "gdb-shelldeck-commands.txt"
    log_file = directory / "gdb-shelldeck-native.log"
    command_file.write_text("set pagination off\nset confirm off\nset print thread-events off\n"
                            "set logging file " + str(log_file) + "\n"
                            "set logging overwrite on\nset logging enabled on\n"
                            "handle SIGPIPE nostop noprint pass\n"
                            "run\nthread apply all bt 40\ninfo sharedlibrary\nquit\n", encoding="utf-8")
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = platform
    env["PYTHONFAULTHANDLER"] = "1"
    print("ShellDeck öffnet sich unter GDB. Dort im PTY-Tab `seq 1 50000` ausführen.", flush=True)
    print("Wenn kein Absturz auftritt, ShellDeck normal schließen. GDB schreibt nach:", log_file, flush=True)
    return subprocess.call([gdb, "-q", "-x", str(command_file), "--args", str(binary)], env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--binary", default="shelldeck")
    parser.add_argument("--platform", choices=("xcb", "wayland"), default="xcb")
    args = parser.parse_args()
    return run(args.directory.expanduser().resolve(), args.binary, args.platform)


if __name__ == "__main__":
    raise SystemExit(main())
