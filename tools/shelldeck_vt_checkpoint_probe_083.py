#!/usr/bin/env python3
"""Compare VT states at identical byte offsets across PTY read chunk sizes.

A diagnostic, not a claim of terminal-correctness. No production code changes.
Use recorded geometry, verify both normal and alternate screen transitions,
and report the earliest chunk-boundary dependent intermediate state, if any.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from shelldeck_vt_vim_reference import start_geometry, margin_reset_checkpoints


def checkpoint_offsets(raw: bytes, rows: int, count: int = 16) -> list[int]:
    if count < 1:
        raise ValueError("count muss positiv sein")
    if not raw:
        raise ValueError("Leere Aufnahme")
    offsets = {len(raw)}
    for seq in (b"\x1b[?1049h", b"\x1b[?1049l"):
        start = 0
        while True:
            pos = raw.find(seq, start)
            if pos < 0:
                break
            offsets.add(pos + len(seq))
            start = pos + len(seq)
    for index in range(1, count + 1):
        offsets.add(max(1, len(raw) * index // (count + 1)))
    try:
        offsets.update(margin_reset_checkpoints(raw, rows, count))
    except ValueError:
        pass  # Small synthetic traces may not enter alternate screen.
    return sorted(offsets)


def replay_checkpoints(raw: bytes, rows: int, cols: int, offsets: list[int],
                       chunk_size: int, screen_factory=None) -> dict[int, tuple[bool, tuple[str, ...]]]:
    if chunk_size < 1:
        raise ValueError("chunk_size muss positiv sein")
    if screen_factory is None:
        from shelldeck_vt_screen import VtScreen
        screen_factory = VtScreen
    screen = screen_factory(rows=rows, cols=cols, enable_history=False)
    prior = 0
    snapshots = {}
    for stop in offsets:
        if stop <= prior or stop > len(raw):
            raise ValueError("Pruefpunkte muessen streng aufsteigend im Datenbereich liegen")
        for position in range(prior, stop, chunk_size):
            screen.feed(raw[position:min(position + chunk_size, stop)])
        snapshots[stop] = (bool(screen.screen.alternate_active), tuple(screen.display()))
        prior = stop
    return snapshots


def compare(raw: bytes, rows: int, cols: int, count: int = 16,
            sizes=(1, 7, 128, 4096), screen_factory=None) -> dict:
    if rows < 1 or cols < 1:
        raise ValueError("Ungueltige Terminalgroesse")
    offsets = checkpoint_offsets(raw, rows, count)
    reference = replay_checkpoints(raw, rows, cols, offsets, len(raw), screen_factory)
    variants = []
    for size in sizes:
        actual = replay_checkpoints(raw, rows, cols, offsets, int(size), screen_factory)
        failures = []
        for stop in offsets:
            base_alt, base_lines = reference[stop]
            alt, lines = actual[stop]
            diff = [i + 1 for i, (a, b) in enumerate(zip(base_lines, lines)) if a != b]
            if len(lines) != len(base_lines):
                diff.append(-1)
            if alt != base_alt or diff:
                failures.append({"byte_offset": stop, "alternate_baseline": base_alt,
                                 "alternate_actual": alt, "different_rows": len(diff),
                                 "example_rows": diff[:8]})
        variants.append({"chunk_size": int(size), "different_checkpoints": len(failures),
                         "first_differences": failures[:10]})
    return {"geometry": {"rows": rows, "cols": cols}, "raw_bytes": len(raw),
            "checkpoint_count": len(offsets), "checkpoints": offsets,
            "note": "Gleiche Zwischenbilder schliessen einen gemeinsamen VT-Interpretationsfehler nicht aus.",
            "variants": variants}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument("--out", type=Path, default=Path.home() / "Downloads" /
                        "ShellDeck_VT_Zwischenvergleich_083.json")
    args = parser.parse_args()
    rows, cols = start_geometry(args.events)
    report = compare(args.raw.read_bytes(), rows, cols, count=args.count)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Bericht:", args.out)
    print("Pruefpunkte:", report["checkpoint_count"])
    for variant in report["variants"]:
        print(f"Chunk {variant['chunk_size']}: {variant['different_checkpoints']} abweichende Zwischenzustaende")


if __name__ == "__main__":
    main()
