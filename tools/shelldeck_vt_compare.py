#!/usr/bin/env python3
"""Compare ShellDeck's VT adapter with unmodified pyte on an htop trace.

No PTY data is executed. Uses only the existing project's pyte dependency.
The reference starts at the first alternate-screen entry and stops before exit.
"""
from __future__ import annotations

import argparse
import codecs
import json
from pathlib import Path

ENTER = b"\x1b[?1049h"
EXIT = b"\x1b[?1049l"


def alternate_interval(raw: bytes):
    start = raw.find(ENTER)
    if start < 0:
        raise ValueError("Aufzeichnung enthält keinen CSI ?1049h-Einstieg")
    start += len(ENTER)
    end = raw.find(EXIT, start)
    if end < 0:
        end = len(raw)
    return start, end


def fixed_chunks(raw: bytes, start: int, stop: int, width: int):
    if width <= 0:
        raise ValueError("Chunkgröße muss positiv sein")
    for left in range(start, stop, width):
        right = min(left + width, stop)
        yield right, raw[left:right]


def matching_geometry(events_path: Path):
    for line in events_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            if item.get("event") == "trace_started":
                rows, cols = int(item["rows"]), int(item["cols"])
                if rows < 1 or cols < 1:
                    raise ValueError("Ungültige Terminalgeometrie")
                return rows, cols
    raise ValueError("trace_started fehlt im Ereignisprotokoll")


def compare(raw, rows, cols, chunk=128, limit=20):
    import pyte
    from shelldeck_vt_screen import VtScreen

    start, end = alternate_interval(raw)
    wrapper = VtScreen(rows=rows, cols=cols, enable_history=False)
    # Feed entry to set up ShellDeck's alternate screen; the native pyte
    # screen is created clean at precisely the same start of htop content.
    wrapper.feed(raw[:start])
    reference = pyte.Screen(cols, rows)
    stream = pyte.Stream(reference)
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    first = None
    different_samples = 0
    sampled = 0
    examples = []
    for offset, data in fixed_chunks(raw, start, end, chunk):
        wrapper.feed(data)
        text = decoder.decode(data)
        if text:
            stream.feed(text)
        a = list(wrapper.display())
        b = list(reference.display)
        diffs = [(y, x, z) for y, (x, z) in enumerate(zip(a, b)) if x != z]
        sampled += 1
        if diffs:
            different_samples += 1
            if first is None:
                first = offset
            if len(examples) < limit:
                y, x, z = diffs[0]
                examples.append({"byte": offset, "row": y,
                                 "adapter": x.rstrip(), "pyte": z.rstrip()})
    return {"start": start, "stop": end, "geometry": [rows, cols],
            "chunk": chunk, "samples": sampled,
            "different_samples": different_samples,
            "first_difference_byte": first, "examples": examples,
            "equal_at_end": list(wrapper.display()) == list(reference.display)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("--chunk", type=int, default=128)
    parser.add_argument("--out", type=Path, default=Path.home() / "Downloads" / "ShellDeck_VT_Vergleich_075.json")
    args = parser.parse_args()
    rows, cols = matching_geometry(args.events)
    report = compare(args.raw.read_bytes(), rows, cols, chunk=args.chunk)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Auswertung: {args.out}")
    print(f"Verglichene Zustände: {report['samples']}; abweichend: {report['different_samples']}")
    if report["first_difference_byte"] is None:
        print("Kein Unterschied zu unverändertem pyte im aufgezeichneten htop-Intervall.")
        print("Das beweist NICHT, dass die Bildschirmanzeige korrekt ist.")
    else:
        print(f"Erste Abweichung bei Byte {report['first_difference_byte']}")


if __name__ == "__main__":
    main()
