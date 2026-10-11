"""Qt-freier, linear skalierender Ausgabepuffer fuer die klassische Ansicht.

Der Puffer laesst den Text unveraendert und fuehrt erst beim zeitbudgetierten
Entnehmen benachbarte Teile gleicher Farbe zusammen. Dadurch vermeiden wir
quadratische String-Verkettungen bei vielen kleinen QProcess-Ausgaben und
lineares ``list.pop(0)`` beim Abarbeiten der Warteschlange.
"""

from __future__ import annotations

from collections import deque
from typing import Callable


class TerminalOutputBuffer:
    """FIFO mit O(1)-Zeichenzaehler; Farben und Chunk-Reihenfolge bleiben erhalten."""

    def __init__(self):
        self._chunks = deque()
        self.pending_chars = 0

    def __bool__(self):
        return bool(self._chunks)

    def __len__(self):
        return len(self._chunks)

    def __iter__(self):
        # Auch Diagnose, Prompt-Erkennung und Export lesen noch nicht
        # gezeichnete Ausgabe. Ein Snapshot verhindert Iterator-Ungueltigkeit.
        return iter(tuple(self._chunks))

    def append(self, text: str, color) -> None:
        if text:
            self._chunks.append((text, color))
            self.pending_chars += len(text)

    def clear(self) -> None:
        self._chunks.clear()
        self.pending_chars = 0

    def tail(self, limit: int) -> str:
        """Letzte ``limit`` Zeichen ohne Kopie der gesamten FIFO liefern.

        Status-/Prompt-Erkennung braucht ausschliesslich das Textende. Auch
        bei einer Millionen-Zeilen-Ausgabe wird daher nur der angeforderte
        kleine Bereich kopiert; die Warteschlange selbst bleibt unveraendert.
        """
        remaining = max(0, int(limit))
        if remaining == 0:
            return ""
        parts = []
        for chunk, _color in reversed(self._chunks):
            if not remaining:
                break
            part = chunk[-remaining:]
            parts.append(part)
            remaining -= len(part)
        return "".join(reversed(parts))

    def take(self, limit: int, split_index: Callable[[str, int], int]):
        """Bis zu ``limit`` Zeichen entnehmen, nach Farben gebuendelt.

        Der optionale Splitter darf Newline-Grenzen bevorzugen. Ein fehlerhaftes
        Null-Ergebnis wird auf mindestens ein Zeichen begrenzt, um endlose
        Timer-Drains auszuschliessen.
        """
        remaining = max(0, int(limit))
        batches = []
        parts = []
        current_color = None
        while remaining and self._chunks:
            text, color = self._chunks[0]
            amount = len(text) if len(text) <= remaining else max(
                1, min(remaining, int(split_index(text, remaining)))
            )
            value = text[:amount]
            if parts and color != current_color:
                batches.append(("".join(parts), current_color))
                parts = []
            current_color = color
            parts.append(value)
            if amount == len(text):
                self._chunks.popleft()
            else:
                self._chunks[0] = (text[amount:], color)
            self.pending_chars -= amount
            remaining -= amount
        if parts:
            batches.append(("".join(parts), current_color))
        return batches
