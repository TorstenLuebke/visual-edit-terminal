"""Qt-free experimental contract for comparing terminal state engines.

Not wired into production ShellDeck. An implementation must retain ownership of
its state: consumers receive immutable snapshots, never live mutable buffers.
This interface deliberately does not prescribe a particular parser or language.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class CursorSnapshot:
    row: int
    column: int
    hidden: bool = False


@dataclass(frozen=True, slots=True)
class ScreenSnapshot:
    rows: int
    columns: int
    lines: tuple[str, ...]
    cursor: CursorSnapshot
    alternate: bool = False

    def __post_init__(self) -> None:
        if self.rows < 1 or self.columns < 1 or len(self.lines) != self.rows:
            raise ValueError("invalid terminal snapshot dimensions")
        if not 0 <= self.cursor.row < self.rows or not 0 <= self.cursor.column < self.columns:
            raise ValueError("cursor outside terminal snapshot")


@runtime_checkable
class TerminalEngineContract(Protocol):
    def feed(self, data: bytes) -> None: ...
    def resize(self, rows: int, columns: int) -> None: ...
    def snapshot(self) -> ScreenSnapshot: ...
    def transcript(self) -> str: ...


class PyteReferenceAdapter:
    """Comparison-only wrapper. Production VtScreen is not replaced."""

    def __init__(self, rows: int = 24, columns: int = 80, history: int = 2000):
        from shelldeck_vt_screen import VtScreen
        self._model = VtScreen(rows=rows, cols=columns, history=history)

    def feed(self, data: bytes) -> None:
        if not isinstance(data, bytes):
            raise TypeError("feed requires raw bytes")
        self._model.feed(data)

    def resize(self, rows: int, columns: int) -> None:
        self._model.resize(rows, columns)

    def snapshot(self) -> ScreenSnapshot:
        m = self._model
        cursor = m.cursor
        return ScreenSnapshot(
            rows=m.rows, columns=m.cols, lines=tuple(m.display()),
            cursor=CursorSnapshot(cursor["y"], cursor["x"], cursor["hidden"]),
            alternate=bool(getattr(m.screen, "is_alternate", False)),
        )

    def transcript(self) -> str:
        return self._model.transcript_text()
