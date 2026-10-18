"""Qt-unabhängige, verlustfreie Portionierung und optionale VT-Diagnose.

Der Reader besitzt bereits ACK-Backpressure. Hier wird ausschließlich die
Arbeit eines GUI-Slots in begrenzte Parserportionen aufgeteilt; die Reihenfolge
und jedes Eingabebyte bleiben erhalten. Die pyte-Streams sind zustandsbehaftet.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

DEFAULT_FEED_SLICE_BYTES = 1024


def terminal_feed_chunks(data, size=DEFAULT_FEED_SLICE_BYTES):
    """Liefert vollständige, aufeinanderfolgende Teile; keine Dekodierung.

    Für bytes entscheidet erst das vorhandene inkrementelle VT-Modell über
    UTF-8-Grenzen. Text wird ebenfalls ohne Veränderung portioniert.
    """
    width = int(size)
    if width < 1:
        raise ValueError("feed slice must be positive")
    for start in range(0, len(data), width):
        yield data[start:start + width]


class FeedCounters:
    """Datensparsame Diagnose ohne Terminalinhalt und ohne Standard-I/O.

    Nur bei explizitem SHELLDECK_VT_FEED_DIAG_PATH werden alle 256 Aufrufe
    aggregierte Zahlen protokolliert. Schreibfehler beeinflussen den PTY
    nicht. Jeder Renderer führt seine eigenen Zähler.
    """
    def __init__(self, path=None):
        self.path = path if path is not None else os.environ.get("SHELLDECK_VT_FEED_DIAG_PATH", "")
        self.calls = 0
        self.bytes = 0
        self.parts = 0
        self.max_input = 0
        self.started = time.monotonic()

    def record(self, input_size: int, pieces: int):
        self.calls += 1
        self.bytes += input_size
        self.parts += pieces
        self.max_input = max(self.max_input, input_size)
        if not self.path or self.calls % 256:
            return
        payload = {
            "event": "vt-feed", "calls": self.calls, "input_bytes": self.bytes,
            "pieces": self.parts, "max_input": self.max_input,
            "seconds": round(time.monotonic() - self.started, 3),
        }
        try:
            with Path(self.path).open("a", encoding="utf-8") as file:
                file.write(json.dumps(payload, sort_keys=True) + "\n")
        except (OSError, ValueError):
            pass
