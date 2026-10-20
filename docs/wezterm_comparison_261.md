# Shared engine test entry point — Patch 261

Run from repository root:

```bash
PYTHONPATH=src .venv/bin/python src/shelldeck_engine_compare_261.py \
  --adapter shelldeck_engine_contract_240:PyteReferenceAdapter
```

A separately compiled WezTerm adapter can be supplied in the same
`module:Class` format **after it actually exists**. The runner fails if it
cannot import an adapter. It does not claim cross-engine equivalence:
`chunk_invariant` tests chunk-independent states *within* each adapter;
the listed `seconds` are exploratory wall times, not reliable speed rankings.
Matching ANSI semantics, reflow, scrollback and cursor/selection parity
need more targeted tests after an actual WezTerm backend is available.
