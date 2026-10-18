#!/usr/bin/env python3
"""Isolierter echter TerminalGridView-Paint-Test ohne PTY/QProcess.

QT_QPA_PLATFORM=offscreen .venv/bin/python tools/diagnose_vt_renderer_185.py
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
from PySide6.QtWidgets import QApplication
from shelldeck_terminal_grid import TerminalGridView


def run(lines=50000, batch=128):
    app = QApplication.instance() or QApplication([])
    grid = TerminalGridView(rows=30, cols=100)
    if not grid.is_usable():
        raise RuntimeError("pyte/VT-Modell nicht verfuegbar")
    grid.resize(920, 560)
    grid.show()
    app.processEvents()
    start = time.monotonic()
    renders = 0
    for base in range(0, lines, batch):
        raw = b"".join(f"{n:06d} Renderer Diagnose abcdefghijklmnopqrstuvwxyz\r\n".encode()
                       for n in range(base + 1, min(base + batch, lines) + 1))
        grid.feed(raw)
        # Explizite Event-Verarbeitung simuliert tatsaechliches Zeichnen.
        app.processEvents()
        renders += 1
        if (base // batch) % 50 == 0:
            print(f"PROGRESS {min(base + batch, lines)}/{lines}", flush=True)
    app.processEvents()
    result = {"ok": True, "scenario": "qt-renderer", "lines": lines,
              "event_cycles": renders, "gc_count": list(gc.get_count()),
              "seconds": round(time.monotonic() - start, 3),
              "executable": sys.executable, "pid": os.getpid()}
    print("RESULT " + json.dumps(result, sort_keys=True), flush=True)
    grid.close()
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
