#!/usr/bin/env python3
"""Untersucht vorhandene Renderer-Diagnosebinaries mit GDB (ohne Neukompilierung)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def run(root: Path, lines: int, timeout: int) -> int:
    gdb = shutil.which("gdb")
    if not gdb:
        print("FEHLER: gdb fehlt. Installation unter Ubuntu: sudo apt install gdb")
        return 2
    records = []
    for label in ("renderer-baseline", "renderer-freelist"):
        binary = root / label / "diagnose_vt_renderer_185.dist" / "diagnose_vt_renderer_185"
        dest = root / label / "gdb-native.log"
        item = {"case": label, "binary": str(binary), "log": str(dest.relative_to(root))}
        if not binary.is_file():
            item["status"] = "missing_binary"
            print(f"FEHLER: {binary} fehlt")
            records.append(item)
            continue
        cmd = [gdb, "--batch", "--quiet", "--return-child-result", "-ex", "set pagination off",
               "-ex", "set confirm off", "-ex", "set print thread-events off",
               "-ex", "handle SIGPIPE nostop noprint pass", "-ex", "run",
               "-ex", "echo \n==== NATIVE BACKTRACE ====\n",
               "-ex", "thread apply all bt 30", "-ex", "info sharedlibrary",
               "--args", str(binary), "--lines", str(lines)]
        env = os.environ.copy()
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["PYTHONFAULTHANDLER"] = "1"
        try:
            with dest.open("w", encoding="utf-8") as output:
                proc = subprocess.run(cmd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                      timeout=timeout, check=False)
            item.update(status="finished", returncode=proc.returncode)
        except subprocess.TimeoutExpired:
            item.update(status="timeout", returncode=None)
        records.append(item)
        print(f"{label}: {item['status']}, GDB-Code={item.get('returncode')}, Protokoll={dest}")
    (root / "gdb-renderer-results.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return 0 if all(r["status"] == "finished" for r in records) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--lines", type=int, default=50000)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if args.lines < 1 or args.timeout < 1:
        parser.error("lines und timeout müssen positiv sein")
    root = args.directory.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Diagnoseordner fehlt: {root}")
    return run(root, args.lines, args.timeout)


if __name__ == "__main__":
    raise SystemExit(main())
