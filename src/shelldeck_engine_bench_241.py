"""Independent, non-GUI ShellDeck engine comparison bench (stdlib only).

Use ``python src/shelldeck_engine_bench_241.py --json``. No production state
is touched and no outside binaries or packages are installed.
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import statistics
import time
import tracemalloc

from shelldeck_engine_contract_240 import TerminalEngineContract


def built_in_cases() -> dict[str, bytes]:
    return {
        "simple": b"Hello\r\nSecond line\r\n",
        "tabs": b"bin\tboot\tdev\troot\r\n",
        "ansi": b"\x1b[32mGreen\x1b[0m\r\n",
        "long_output": b"".join(f"{i:05d}\r\n".encode("ascii") for i in range(50000)),
        "cursor": b"abcdef\r\x1b[2Kxyz\r\n",
    }


def load_adapter(spec: str):
    """Resolve `module:Class` without evaluating arbitrary source code."""
    module_name, separator, class_name = spec.partition(":")
    if not separator or not module_name or not class_name.isidentifier():
        raise ValueError("adapter must have the form module:Class")
    adapter_class = getattr(importlib.import_module(module_name), class_name)
    return adapter_class


def run_case(factory, data: bytes, *, rows: int = 24, columns: int = 80,
             repeat: int = 3, chunk_size: int = 4096) -> dict:
    if repeat < 1 or chunk_size < 1:
        raise ValueError("repeat and chunk_size must be positive")
    elapsed = []
    peak_bytes = []
    final = None
    for _ in range(repeat):
        tracemalloc.start()
        try:
            engine = factory(rows, columns)
            if not isinstance(engine, TerminalEngineContract):
                raise TypeError("adapter does not implement TerminalEngineContract")
            start = time.perf_counter()
            for offset in range(0, len(data), chunk_size):
                engine.feed(data[offset:offset + chunk_size])
            snap = engine.snapshot()
            transcript = engine.transcript()
            duration = time.perf_counter() - start
            _current, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        elapsed.append(duration)
        peak_bytes.append(peak)
        final = {"cursor": [snap.cursor.row, snap.cursor.column],
                 "visible_nonempty": sum(bool(s.strip()) for s in snap.lines),
                 "transcript_chars": len(transcript)}
    return {"bytes": len(data), "repeat": repeat,
            "median_seconds": round(statistics.median(elapsed), 6),
            "peak_traced_bytes": max(peak_bytes), "state": final}



def run_phases(factory, data: bytes, *, rows: int = 24, columns: int = 80,
               repeat: int = 3, chunk_size: int = 4096, trace_memory: bool = False) -> dict:
    """Time feed, snapshot, transcript and resize separately; tracing is opt-in.

    Timings are wall-clock observations, not a cross-language CPU comparison.
    A fresh engine instance is used for each repetition.  The resize phase
    measures a round-trip back to the initial geometry after reading state.
    """
    if rows < 2 or columns < 2 or repeat < 1 or chunk_size < 1:
        raise ValueError("invalid benchmark geometry or count")
    phases = {name: [] for name in ("feed", "snapshot", "transcript", "resize")}
    peaks = []
    for _ in range(repeat):
        if trace_memory:
            tracemalloc.start()
        try:
            engine = factory(rows, columns)
            if not isinstance(engine, TerminalEngineContract):
                raise TypeError("adapter does not implement TerminalEngineContract")
            clock = time.perf_counter
            t = clock()
            for offset in range(0, len(data), chunk_size):
                engine.feed(data[offset:offset + chunk_size])
            phases["feed"].append(clock() - t)
            t = clock()
            snap = engine.snapshot()
            phases["snapshot"].append(clock() - t)
            t = clock()
            transcript = engine.transcript()
            phases["transcript"].append(clock() - t)
            t = clock()
            engine.resize(rows, columns - 1)
            engine.resize(rows, columns)
            phases["resize"].append(clock() - t)
            if trace_memory:
                peaks.append(tracemalloc.get_traced_memory()[1])
        finally:
            if trace_memory:
                tracemalloc.stop()
    return {
        "bytes": len(data), "repeat": repeat, "memory_tracing": trace_memory,
        "phase_median_seconds": {key: round(statistics.median(values), 6)
                                 for key, values in phases.items()},
        "peak_traced_bytes": max(peaks) if peaks else None,
        "state": {"visible_rows": len(snap.lines), "transcript_chars": len(transcript)},
    }

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", default="shelldeck_engine_contract_240:PyteReferenceAdapter")
    parser.add_argument("--case", choices=(*built_in_cases(), "all"), default="all")
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--chunk-size", type=int, default=4096)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--phases", action="store_true", help="measure phases separately")
    parser.add_argument("--trace-memory", action="store_true", help="trace Python allocations for phase benchmark")
    args = parser.parse_args(argv)
    try:
        factory = load_adapter(args.adapter)
        cases = built_in_cases()
        if args.case != "all":
            cases = {args.case: cases[args.case]}
        runner = run_phases if args.phases else run_case
        kwargs = {"repeat": args.repeat, "chunk_size": args.chunk_size}
        if args.phases:
            kwargs["trace_memory"] = args.trace_memory
        result = {key: runner(factory, value, **kwargs) for key, value in cases.items()}
    except (ValueError, ImportError, AttributeError, TypeError, RuntimeError) as exc:
        parser.exit(2, f"Engine bench could not run: {exc}\n")
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for name, measurement in result.items():
            if args.phases:
                print(f"{name}: {measurement['phase_median_seconds']}")
            else:
                print(f"{name}: {measurement['median_seconds']:.6f}s median, "
                      f"{measurement['peak_traced_bytes']} traced peak bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
