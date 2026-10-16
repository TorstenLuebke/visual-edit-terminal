#!/usr/bin/env python3
"""Read-only counts of PTY *output* controls; never captures keyboard input.

Raw PTY output is not an input trace. BEL/BS in this stream alone cannot
prove that ShellDeck sent duplicate keystrokes. The report intentionally
contains no terminal text, command names or environment data.
"""
import argparse
import json
from collections import Counter
from pathlib import Path


def analyze(raw: bytes):
    # CSI sequences are counted for context; no assumptions about frames.
    import re
    csi = Counter(match.group(1).decode("ascii") for match in
                  re.finditer(rb"\x1b\[[0-?]*[ -/]*([@-~])", raw))
    return {"bytes": len(raw), "BEL": raw.count(b"\x07"),
            "BS": raw.count(b"\x08"), "CR": raw.count(b"\x0d"),
            "LF": raw.count(b"\x0a"),
            "CSI_S": csi["S"], "CSI_T": csi["T"],
            "CSI_K": csi["K"], "CSI_X": csi["X"],
            "CSI_r": csi["r"],
            "warning": "PTY output alone cannot establish duplicate keyboard dispatch."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw_file", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = analyze(args.raw_file.read_bytes())
    output = args.output or args.raw_file.with_name("ShellDeck_VT_Steuerzeichen_084.json")
    output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Bericht: {output}")
    print("Nur PTY-Ausgabe geprüft; keine Aussagen über tatsächlich gesendete Tastendrücke.")


if __name__ == "__main__":
    main()
