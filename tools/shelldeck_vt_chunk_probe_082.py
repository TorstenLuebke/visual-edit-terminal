#!/usr/bin/env python3
"""Compare VT results for identical bytes split into different PTY read chunks.

A clean result only rules out a read-boundary dependency; it does NOT prove
that htop's VT interpretation is correct. No production code is modified.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shelldeck_vt_vim_reference import start_geometry


def replay(raw: bytes, rows: int, cols: int, chunk_size: int) -> list[str]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    from shelldeck_vt_screen import VtScreen
    screen = VtScreen(rows=rows, cols=cols, enable_history=False)
    for offset in range(0, len(raw), chunk_size):
        screen.feed(raw[offset:offset + chunk_size])
    return screen.display()


def compare(raw: bytes, rows: int, cols: int, sizes=(1, 7, 128, 4096)) -> dict:
    if rows <= 0 or cols <= 0:
        raise ValueError("invalid terminal geometry")
    if not raw:
        raise ValueError("empty recording")
    baseline = replay(raw, rows, cols, max(1, len(raw)))
    records = []
    for size in sizes:
        actual = replay(raw, rows, cols, int(size))
        differences = [{"row": row + 1, "expected": baseline[row].rstrip(),
                        "observed": actual[row].rstrip()}
                       for row in range(rows) if baseline[row] != actual[row]]
        records.append({"chunk_size": int(size), "different_rows": len(differences),
                        "examples": differences[:8]})
    return {"rows": rows, "cols": cols, "raw_bytes": len(raw),
            "note": "Gleiche Endbilder beweisen keine korrekte VT-Interpretation.",
            "variants": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("--out", type=Path, default=Path.home() / "Downloads" /
                        "ShellDeck_VT_Chunk_Vergleich_082.json")
    args = parser.parse_args()
    rows, cols = start_geometry(args.events)
    report = compare(args.raw.read_bytes(), rows, cols)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Bericht:", args.out)
    for item in report["variants"]:
        print(f"Chunk {item['chunk_size']}: {item['different_rows']} abweichende Zeilen")


if __name__ == "__main__":
    main()
