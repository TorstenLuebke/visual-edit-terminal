#!/usr/bin/env python3
"""Offline replay of ShellDeck VT captures. Reads untrusted PTY bytes; never executes them."""
from __future__ import annotations
import argparse
import json
from pathlib import Path


def initial_geometry(path: Path | None):
    """Return initial PTY grid geometry from a matching ShellDeck trace.

    The terminal must start at the same dimensions used while recording.
    Starting with a different height changes scroll-region semantics even
    when the trace contains no resize events.
    """
    if path is None:
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("event") == "trace_started":
            rows, cols = int(record["rows"]), int(record["cols"])
            if rows < 1 or cols < 1:
                raise ValueError("Ungültige Anfangsgeometrie im Ereignisprotokoll")
            return rows, cols
    return None


def resolve_geometry(events_path, rows=None, cols=None):
    recorded = initial_geometry(events_path)
    if recorded is None:
        if rows is None or cols is None:
            raise ValueError("Ohne trace_started bitte --rows UND --cols angeben")
        return rows, cols
    return (recorded[0] if rows is None else rows,
            recorded[1] if cols is None else cols)


def resize_events(path: Path | None, raw_length: int):
    if path is None:
        return []
    result = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        if item.get("event") != "grid_cells_changed":
            continue
        position = int(item.get("byte_offset", -1))
        if 0 <= position <= raw_length:
            result.append((position, int(item["rows"]), int(item["cols"])))
    return sorted(result)


def screen_lines(model):
    return [str(line).rstrip() for line in model.display()]


def capture(model, byte_offset):
    return {"offset": byte_offset, "alternate": bool(model.in_alternate_screen()),
            "rows": model.rows, "cols": model.cols, "lines": screen_lines(model)}


def replay(raw, rows, cols, events=(), apply_resize=True, chunk_size=256,
           max_samples=12, model_factory=None):
    if model_factory is None:
        from shelldeck_vt_screen import VtScreen
        model_factory = lambda r, c: VtScreen(rows=r, cols=c, enable_history=False)
    model = model_factory(rows, cols)
    events = sorted(events) if apply_resize else []
    boundaries = [0] + [pos for pos, _, _ in events] + [len(raw)]
    # Split *before* and *after* the actual VT screen switches. This avoids
    # losing the last alternate frame when exit and shell output share a read.
    for sequence in (b"\x1b[?1049l", b"\x1b[?1047l", b"\x1b[?47l",
                     b"\x1b[?1049h", b"\x1b[?1047h", b"\x1b[?47h"):
        pos = raw.find(sequence)
        while pos != -1:
            boundaries.extend((pos, pos + len(sequence)))
            pos = raw.find(sequence, pos + 1)
    boundaries = sorted(set(boundaries))
    snapshots = []
    last_alternate = None
    last_active = None
    sample_count = 0
    processed = 0
    event_i = 0
    for start, stop in zip(boundaries, boundaries[1:]):
        while event_i < len(events) and events[event_i][0] == start:
            _, r, c = events[event_i]
            model.resize(r, c)
            event_i += 1
        for left in range(start, stop, chunk_size):
            right = min(stop, left + chunk_size)
            model.feed(raw[left:right])
            processed = right
            active = model.in_alternate_screen()
            if active:
                last_active = capture(model, right)
            if last_alternate is not None and last_alternate != active:
                # Capture transition without losing the last active frame.
                if last_alternate and last_active is not None:
                    snapshots.append(("last-active-before-exit", last_active))
                if active:
                    snapshots.append(("alternate-entered", capture(model, right)))
            if active and sample_count < max_samples and right >= ((sample_count + 1) * len(raw) // (max_samples + 1)):
                snapshots.append(("sample", capture(model, right)))
                sample_count += 1
            last_alternate = active
    while event_i < len(events) and events[event_i][0] == len(raw):
        _, r, c = events[event_i]
        model.resize(r, c)
        event_i += 1
    # Preserve the last active frame also if the alternate screen remained active.
    if last_active is not None and not any(label == "last-active-before-exit" for label, _ in snapshots):
        snapshots.append(("last-active", last_active))
    return {"samples": snapshots, "final": capture(model, len(raw)), "processed": processed}


def summarize(result, output, raw_len, events):
    with output.open("w", encoding="utf-8") as handle:
        handle.write(f"Rohdatenbytes: {raw_len}\nResize-Ereignisse: {len(events)}\n")
        for pos, r, c in events:
            handle.write(f"Resize byte={pos}: {r}x{c}\n")
        for label, sample in result["samples"] + [("final", result["final"])]:
            handle.write(f"\n=== {label} bei Byte {sample['offset']} | alternate={sample['alternate']} | {sample['rows']}x{sample['cols']} ===\n")
            for i, line in enumerate(sample["lines"]):
                if line:
                    handle.write(f"{i:03d}|{line}\n")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("events", type=Path, nargs="?")
    parser.add_argument("--rows", type=int, default=None, help="Anfangshöhe; Standard aus trace_started")
    parser.add_argument("--cols", type=int, default=None, help="Anfangsbreite; Standard aus trace_started")
    parser.add_argument("--chunk", type=int, default=128)
    parser.add_argument("--samples", type=int, default=12)
    parser.add_argument("--out", type=Path, default=Path.home() / "Downloads" / "ShellDeck_Replay_Zwischenstaende.txt")
    args = parser.parse_args()
    if args.chunk < 1 or args.samples < 1:
        parser.error("--chunk und --samples müssen positiv sein")
    raw = args.raw.read_bytes()
    try:
        rows, cols = resolve_geometry(args.events, args.rows, args.cols)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    events = resize_events(args.events, len(raw))
    report = replay(raw, rows, cols, events, chunk_size=args.chunk, max_samples=args.samples)
    summarize(report, args.out, len(raw), events)
    print(f"Anfangsgeometrie: {rows} Zeilen x {cols} Spalten")
    print(f"Bericht: {args.out}")
    print(f"Zwischenstände: {len(report['samples'])}; Endzustand alternate={report['final']['alternate']}")


if __name__ == "__main__":
    main()
