#!/usr/bin/env python3
"""Isolierter pyte/ShellDeck-VT-Stresstest ohne Qt und ohne PTY.

Aufruf: .venv/bin/python tools/diagnose_vt_model_184.py --lines 50000
Nach Nuitka-Kompilierung denselben Parameter fuer das Binary verwenden.
"""
import argparse
import gc
import json
import os
import sys
import time
from pathlib import Path

# In der Quellausfuehrung liegen die Module unter ../src. Im Nuitka-Standalone-
# Build sind sie einkompiliert; dort muss kein Quellordner existieren.
for candidate in (Path(__file__).resolve().parent / "src",
                  Path(__file__).resolve().parents[1] / "src"):
    if candidate.is_dir():
        sys.path.insert(0, str(candidate))
        break
from shelldeck_vt_screen import VtScreen


def run(lines=50000, batch=128, paint_every=256):
    model = VtScreen(rows=30, cols=100, history=2000)
    start = time.monotonic()
    painted = 0
    for base in range(0, lines, batch):
        chunk = b"".join(f"{n:06d} Diagnose Terminalausgabe abcdefghijklmnopqrstuvwxyz\r\n".encode()
                         for n in range(base + 1, min(base + batch, lines) + 1))
        model.feed(chunk)
        if (base // batch) % max(1, paint_every // batch) == 0:
            for y in range(model.rows):
                row = model.row_cells(y)
                if len(row) != model.cols:
                    raise AssertionError("ungueltige Zellbreite")
            painted += 1
        if (base // batch) % 50 == 0:
            print(f"PROGRESS {min(base + batch, lines)}/{lines}", flush=True)
    screen = model.display()
    assert len(screen) == model.rows
    result = {"ok": True, "scenario": "vt-model", "lines": lines,
              "paint_snapshots": painted, "gc_count": list(gc.get_count()),
              "seconds": round(time.monotonic() - start, 3),
              "executable": sys.executable, "pid": os.getpid()}
    print("RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lines", type=int, default=50000)
    parser.add_argument("--batch", type=int, default=128)
    args = parser.parse_args()
    if args.lines < 1 or args.batch < 1:
        parser.error("--lines und --batch muessen positiv sein")
    run(args.lines, args.batch)


if __name__ == "__main__":
    main()
