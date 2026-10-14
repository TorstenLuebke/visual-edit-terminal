#!/usr/bin/env python3
"""Deterministic scroll-region oracle for the htop stale-cell investigation.

The expected text is derived from the scrolling-region operations, not from
Vim or pyte. No application code is modified by this diagnostic.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shelldeck_vt_sequence_probe import fixture_cases
from shelldeck_vt_vim_reference import pyte_screens, vim_screen, vim_supported


# Terminal rows are 1-based. DECSTBM limits scrolling to rows 12..rows-1.
# SU 10 discards the two populated top lines; SD 10 moves them to 22 and 23.
# After either operation the test writes '1234 short' at row 12 and erases
# the remainder. SU followed by SD cannot restore lines discarded by SU.
EXPECTED = {
    "shorter_with_el": {1: "HEADER-UNCHANGED", 12: "1234 short", 13: "5678 second-old-command"},
    "shorter_with_ech": {1: "HEADER-UNCHANGED", 12: "1234 short", 13: "5678 second-old-command"},
    "scroll_up_then_el": {1: "HEADER-UNCHANGED", 12: "1234 short", 13: ""},
    "scroll_down_then_el": {1: "HEADER-UNCHANGED", 12: "1234 short", 13: "", 21: "", 22: "1234 command-long-long-long", 23: "5678 second-old-command"},
    "up_down_then_el": {1: "HEADER-UNCHANGED", 12: "1234 short", 13: "", 22: "", 23: ""},
    "up_down_then_ech": {1: "HEADER-UNCHANGED", 12: "1234 short", 13: "", 22: "", 23: ""},
}


def check_rows(display: list[str], expected: dict[int, str]) -> list[dict]:
    """Return mismatches against independent, explicitly specified rows."""
    failures = []
    for row, wanted in expected.items():
        observed = display[row - 1].rstrip()
        if observed != wanted:
            failures.append({"row": row, "expected": wanted, "observed": observed})
    return failures


def run(rows: int = 58, cols: int = 235, *, use_vim: bool = True) -> dict:
    if rows < 25:
        raise ValueError("Mindestens 25 Zeilen fuer die Scroll-Orakel erforderlich")
    cases = fixture_cases(rows, cols)
    result = []
    for name, data in cases.items():
        expectation = EXPECTED[name]
        actual_pyte = pyte_screens(data, rows, cols, [len(data)])[len(data)]
        entry = {"case": name, "pyte_mismatches": check_rows(actual_pyte, expectation)}
        if use_vim and vim_supported():
            entry["vim_mismatches"] = check_rows(vim_screen(data, rows, cols), expectation)
        result.append(entry)
    return {"geometry": {"rows": rows, "cols": cols},
            "note": "Erwartete Zeilen beruhen auf der Scrollbereichs-Semantik, nicht auf Emulatorausgaben.",
            "cases": result}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rows", type=int, default=58)
    p.add_argument("--cols", type=int, default=235)
    p.add_argument("--without-vim", action="store_true")
    p.add_argument("--out", type=Path, default=Path.home() / "Downloads" / "ShellDeck_VT_Scroll_Orakel_079.json")
    args = p.parse_args()
    report = run(args.rows, args.cols, use_vim=not args.without_vim)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Bericht:", args.out)
    for item in report["cases"]:
        print(f"{item['case']}: pyte={len(item['pyte_mismatches'])} Soll-Abweichungen", end="")
        if "vim_mismatches" in item:
            print(f", vim={len(item['vim_mismatches'])}", end="")
        print()


if __name__ == "__main__":
    main()
