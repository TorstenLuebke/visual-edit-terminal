"""Inhaltsfreie Diagnose der PTY-Eingabeschreibaufrufe (Patch 085).

Opt-in: SHELLDECK_INPUT_TRACE_PATH=/sicherer/pfad/trace.jsonl
Es werden NIEMALS Bytes, Tastennamen, Zeichen, Befehle oder Passwoerter
protokolliert. Fehlt die Umgebungsvariable, erfolgen keine Datei-I/Os.
"""
import json
import os
from pathlib import Path


class InputWriteAudit:
    def __init__(self, path=None):
        self.path = Path(path) if path else None
        self.counter = 0

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("SHELLDECK_INPUT_TRACE_PATH") or None)

    def record(self, *, bytes_count, status, result=None):
        self.counter += 1
        if self.path is None:
            return
        entry = {"event": "grid_pty_write", "sequence": self.counter,
                 "bytes_count": int(bytes_count), "status": str(status)}
        if result is not None:
            entry["write_result"] = int(result)
        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        except OSError:
            # Diagnose darf PTY-Eingabe niemals blockieren.
            pass
