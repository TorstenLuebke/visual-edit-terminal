#!/usr/bin/env python3
"""Independent, deterministic VT probes for ShellDeck's htop stale-cell issue.

Diagnostic only; uses the existing VtScreen and installed Vim +terminal.
Run with PYTHONPATH=src .venv/bin/python tools/shelldeck_vt_sequence_probe.py.
No PTY recording, GUI, or production VT modification is needed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shelldeck_vt_vim_reference import pyte_screens, vim_screen, vim_supported

ESC = b"\x1b["
ALT = ESC + b"?1049h"


def h(row: int, col: int = 1) -> bytes:
    return ESC + f"{row};{col}H".encode("ascii")


def fixture_cases(rows: int = 58, cols: int = 235) -> dict[str, bytes]:
    """Completed, fixed-size VT transactions; each ends after an entire command.

    These patterns reproduce the command *types* present in the htop capture,
    not the htop bug itself. They deliberately include both affected rows and
    unaffected sentinels, so a discrepancy is not conflated with missing data.
    """
    if rows < 15 or cols < 48:
        raise ValueError("Mindestens 15 Zeilen und 48 Spalten erforderlich")
    margins = ESC + f"12;{rows - 1}r".encode("ascii")
    full_margins = ESC + f"1;{rows}r".encode("ascii")
    baseline = ALT + ESC + b"2J" + h(1) + b"HEADER-UNCHANGED" + h(12) + b"1234 command-long-long-long" + h(13) + b"5678 second-old-command"
    cases = {
        "shorter_with_el": baseline + h(12) + b"1234 short" + ESC + b"K",
        "shorter_with_ech": baseline + h(12) + b"1234 short" + ESC + b"21X",
        "scroll_up_then_el": baseline + margins + h(12) + ESC + b"10S" + h(12) + b"1234 short" + ESC + b"K" + full_margins,
        "scroll_down_then_el": baseline + margins + h(12) + ESC + b"10T" + h(12) + b"1234 short" + ESC + b"K" + full_margins,
        "up_down_then_el": baseline + margins + h(12) + ESC + b"10S" + ESC + b"10T" + h(12) + b"1234 short" + ESC + b"K" + full_margins,
        "up_down_then_ech": baseline + margins + h(12) + ESC + b"10S" + ESC + b"10T" + h(12) + b"1234 short" + ESC + b"21X" + full_margins,
    }
    return cases


def compare_cases(rows: int = 58, cols: int = 235) -> dict:
    if not vim_supported():
        raise RuntimeError("Vim muss mit +terminal gebaut sein")
    snapshots = []
    for name, raw in fixture_cases(rows, cols).items():
        screen = pyte_screens(raw, rows, cols, [len(raw)])[len(raw)]
        reference = vim_screen(raw, rows, cols)
        differences = [
            {"row": index, "pyte": left.rstrip(), "vim": right.rstrip()}
            for index, (left, right) in enumerate(zip(screen, reference))
            if left.rstrip() != right.rstrip()
        ]
        snapshots.append({"case": name, "bytes": len(raw), "different_rows": len(differences),
                          "examples": differences[:10]})
    return {"geometry": {"rows": rows, "cols": cols},
            "purpose": "Deterministic VT behavior comparison; differences need investigation",
            "snapshots": snapshots}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=58)
    parser.add_argument("--cols", type=int, default=235)
    parser.add_argument("--out", type=Path, default=Path.home() / "Downloads" / "ShellDeck_VT_Sequenztest_078.json")
    args = parser.parse_args()
    report = compare_cases(args.rows, args.cols)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Bericht:", args.out)
    for item in report["snapshots"]:
        print(f"{item['case']}: {item['different_rows']} unterschiedliche Zeilen")
    print("Identische Ergebnisse der Kurztests schliessen einen komplexeren htop-Fehler nicht aus.")


if __name__ == "__main__":
    main()
