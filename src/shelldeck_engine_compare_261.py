"""Deterministic cross-engine fixture checks; WezTerm is opt-in only when real.

Usage: python src/shelldeck_engine_compare_261.py --adapter shelldeck_engine_contract_240:PyteReferenceAdapter
An independent, compiled WezTerm adapter can be passed later using module:Class.
This script never silently substitutes pyte for a missing WezTerm backend.
"""
from __future__ import annotations
import argparse
import json
import time
from shelldeck_engine_bench_241 import load_adapter
from shelldeck_engine_cases_252 import engine_cases, replay_case
from shelldeck_engine_contract_240 import TerminalEngineContract

def exercise(factory, cases=None, chunk_sizes=(1, 7, 4096)) -> dict:
    cases = engine_cases() if cases is None else cases
    results = []
    for case in cases:
        snapshots = []
        durations = []
        for size in chunk_sizes:
            engine = factory(case.rows, case.columns)
            if not isinstance(engine, TerminalEngineContract):
                raise TypeError("adapter must implement TerminalEngineContract")
            start = time.perf_counter()
            replay_case(engine, case, size)
            snap = engine.snapshot()
            durations.append(time.perf_counter() - start)
            snapshots.append((snap.lines, snap.cursor, snap.alternate))
        stable = all(state == snapshots[0] for state in snapshots[1:])
        results.append({"case": case.name, "sha256": case.sha256,
                        "chunk_invariant": stable, "seconds": durations})
    return {"passed": all(item["chunk_invariant"] for item in results), "cases": results}

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, help="module:Class (no fallback)")
    args = parser.parse_args()
    result = exercise(load_adapter(args.adapter))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
