#!/usr/bin/env python3
"""Wiederholt vorhandene Nuitka-Diagnosebinaries ohne Neu-Kompilierung."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

CASES = {"model-baseline": "diagnose_vt_model_184", "model-freelist": "diagnose_vt_model_184",
         "renderer-baseline": "diagnose_vt_renderer_185", "renderer-freelist": "diagnose_vt_renderer_185"}


def run_repeat(root: Path, repeats: int, lines: int, timeout: int) -> list[dict]:
    records = []
    for label, entry in CASES.items():
        binary = root / label / f"{entry}.dist" / entry
        for attempt in range(1, repeats + 1):
            path = root / label / f"repeat-{attempt:02}.log"
            record = {"case": label, "attempt": attempt, "binary": str(binary),
                      "lines": lines, "log": str(path.relative_to(root))}
            if not binary.is_file() or not os.access(binary, os.X_OK):
                record.update(status="missing_binary", exit_code=None, seconds=0)
            else:
                env = os.environ.copy()
                if label.startswith("renderer-"):
                    env["QT_QPA_PLATFORM"] = "offscreen"
                start = time.monotonic()
                with path.open("wb") as log:
                    try:
                        proc = subprocess.run([str(binary), "--lines", str(lines)],
                                              stdout=log, stderr=subprocess.STDOUT,
                                              env=env, timeout=timeout, check=False)
                        code = proc.returncode
                        status = "passed" if code == 0 else ("signal" if code < 0 else "failed")
                    except subprocess.TimeoutExpired:
                        code, status = None, "timeout"
                record.update(status=status, exit_code=code,
                              seconds=round(time.monotonic() - start, 3))
            records.append(record)
            print(f"{label} Wiederholung {attempt}/{repeats}: {record['status']} ({record['exit_code']})", flush=True)
    (root / "repeat-results.json").write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return records


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Ordner des bestehenden Diagnose-Builds")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--lines", type=int, default=50000)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if min(args.repeats, args.lines, args.timeout) <= 0:
        parser.error("repeats, lines und timeout muessen > 0 sein")
    root = args.directory.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Ordner fehlt: {root}")
    results = run_repeat(root, args.repeats, args.lines, args.timeout)
    return 0 if all(r["status"] == "passed" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
