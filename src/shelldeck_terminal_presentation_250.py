"""Qt-free terminal presentation contracts (experimental, not production wired).

The selection uses logical row identities supplied by an engine. Screen and
viewport offsets must never be treated as persistent identities.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, order=True, slots=True)
class TextAnchor:
    generation: int
    row_id: int
    column: int

    def __post_init__(self) -> None:
        if min(self.generation, self.row_id, self.column) < 0:
            raise ValueError("negative anchor component")


@dataclass(frozen=True, slots=True)
class TextSelection:
    start: TextAnchor
    end: TextAnchor

    def __post_init__(self) -> None:
        if self.start.generation != self.end.generation:
            raise ValueError("selection cannot cross screen generations")

    def ordered(self) -> tuple[TextAnchor, TextAnchor]:
        return tuple(sorted((self.start, self.end)))

    def valid_for(self, generation: int, retained_rows: Iterable[int]) -> bool:
        low, high = self.ordered()
        if generation != low.generation:
            return False
        retained = set(retained_rows)
        return low.row_id in retained and high.row_id in retained


@dataclass(frozen=True, slots=True)
class RepaintRequest:
    full: bool = False
    rows: frozenset[int] = frozenset()

    def __post_init__(self) -> None:
        if any(row < 0 for row in self.rows):
            raise ValueError("negative row")

    def merge(self, other: "RepaintRequest") -> "RepaintRequest":
        if not isinstance(other, RepaintRequest):
            raise TypeError("expected RepaintRequest")
        if self.full or other.full:
            return RepaintRequest(full=True)
        return RepaintRequest(rows=self.rows | other.rows)


class RepaintAccumulator:
    """Merge presentation work only; deliberately has no feed/data API."""

    def __init__(self) -> None:
        self._pending = RepaintRequest()

    def request(self, update: RepaintRequest) -> None:
        self._pending = self._pending.merge(update)

    def drain(self) -> RepaintRequest:
        update = self._pending
        self._pending = RepaintRequest()
        return update
