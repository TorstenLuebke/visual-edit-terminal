"""Deterministic binary fixtures shared by independent terminal engines.

The bytes are the test inputs, not assertions about the output of any engine.
No shell processes, UI, external repositories or extra packages are required.
"""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256


@dataclass(frozen=True, slots=True)
class EngineCase:
    name: str
    data: bytes
    rows: int = 24
    columns: int = 80
    description: str = ""

    @property
    def sha256(self) -> str:
        return sha256(self.data).hexdigest()


def engine_cases() -> tuple[EngineCase, ...]:
    return (
        EngineCase("ascii", b"Hello\r\nSecond line\r\n"),
        EngineCase("utf8_split", "Grüße 🐧\r\n".encode("utf-8")),
        EngineCase("tabs", b"bin\tboot\tdev\troot\r\n", columns=148),
        EngineCase("sgr", b"\x1b[32mGreen\x1b[0m\r\n"),
        EngineCase("cursor_erase", b"abcdef\r\x1b[2Kxyz\r\n"),
        EngineCase("alternate", b"normal\r\n\x1b[?1049halt\x1b[?1049l"),
        EngineCase("long_output", b"".join(f"{i:05d}\r\n".encode("ascii") for i in range(50000))),
    )


def replay_case(engine, case: EngineCase, chunk_size: int) -> None:
    """Replay all bytes in original order, including split UTF-8 / ESC sequences."""
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    for pos in range(0, len(case.data), chunk_size):
        engine.feed(case.data[pos:pos + chunk_size])
