"""Explicitly opt-in Rust transport diagnostic. NOT a TerminalEngineContract.

Never calls cargo or downloads dependencies. Invokes a prebuilt standalone
probe binary chosen by the caller; no production PTY/GUI integration.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess


def fnv1a64(data: bytes) -> str:
    digest = 0xCBF29CE484222325
    for byte in data:
        digest = ((digest ^ byte) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return f"{digest:016x}"


def verify_rust_probe(executable: str | Path, data: bytes, *, timeout: float = 15.0) -> dict:
    """Validate a versioned Rust probe against the exact input bytes.

    Does not claim terminal rendering correctness or engine performance.
    """
    if not isinstance(data, bytes):
        raise TypeError("raw bytes are required")
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    path = Path(executable)
    if not path.is_file():
        raise FileNotFoundError(path)
    probe = subprocess.run([str(path), "--probe"], capture_output=True,
                           timeout=timeout, check=True)
    identity = json.loads(probe.stdout)
    if identity != {"protocol": 1, "kind": "rust-transport", "vt_engine": False}:
        raise ValueError("unexpected Rust transport identity")
    process = subprocess.run([str(path), "--analyze"], input=data,
                             capture_output=True, timeout=timeout, check=True)
    outcome = json.loads(process.stdout)
    expected = {"protocol": 1, "bytes": len(data),
                "escapes": data.count(b"\x1b"), "newlines": data.count(b"\n"),
                "fnv1a64": fnv1a64(data)}
    if outcome != expected:
        raise ValueError(f"transport mismatch: {outcome!r} != {expected!r}")
    return outcome
