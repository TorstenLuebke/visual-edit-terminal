# Rust comparison gate – Phase 248

`wezterm-term` is the **preferred evaluation candidate**, not yet a dependency.
The isolated Rust probe verifies byte transport only; it is **not** an engine
and **must not** be benchmarked against pyte as if VT parsing occurred.

Run Python tests from repository root:

```sh
.venv/bin/python -m pytest -v src/test_shelldeck_rust_transport_248.py
```

When `cargo` is available, one test builds and checks Rust using `--offline`
into a temporary target folder; otherwise that test is explicitly skipped.

## Requirements before real WezTerm integration

1. Pin an actual `wezterm-term` source revision and document build/API details.
2. Resolve Cargo dependencies in a separate review environment, retain Cargo.lock.
3. Audit ALL resolved licenses and bundled assets for commercial distribution.
4. Confirm builds on Ubuntu, Windows 11 and macOS; no silently required SDKs.
5. Provide a versioned binary interface and correctness tests: VT parser,
   alt screen, resize/reflow, stable selection/scrollback, Unicode, colors.
6. Only then implement `TerminalEngineContract` and run identical benchmarks.

No package installation, network access or production-engine switch is
performed by patches 246–248.
