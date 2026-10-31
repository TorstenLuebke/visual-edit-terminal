"""Opt-in, content-free audit of terminal resizing and screen mutations.

Set SHELLDECK_RESIZE_DIAG_PATH to a user-controlled local .jsonl path.
Only numeric geometry/document statistics and fixed event names are recorded.
No terminal contents, commands, paths, environment, or keypresses are logged.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from time import monotonic_ns


class ResizeAudit:
    MAX_RECORDS = 3000
    _ALLOWED_KEYS = frozenset({
        "width", "height", "rows", "cols", "old_rows", "old_cols",
        "chars", "blocks", "removed", "added", "position",
        "visible_cells", "visible_lines", "history_lines", "cursor_x",
        "cursor_y", "vt_mode", "active", "changed",
    })
    _ALLOWED_EVENTS = frozenset({
        "host_resize", "host_resize_settled", "document_change",
        "explicit_clear", "vt_resize_before", "vt_resize_after",
    })

    def __init__(self, path=""):
        self.path = str(path or "")
        self.count = 0

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get("SHELLDECK_RESIZE_DIAG_PATH", ""))

    @property
    def enabled(self):
        return bool(self.path) and self.count < self.MAX_RECORDS

    def record(self, event, **fields):
        if not self.enabled or event not in self._ALLOWED_EVENTS:
            return False
        # Restrict even internal callers to fixed field names and scalar
        # numbers/booleans: the diagnostics must never leak terminal content.
        allowed = {}
        for key, value in fields.items():
            if key in self._ALLOWED_KEYS and type(value) in (int, bool, float):
                allowed[key] = value
        payload = {"t_ns": monotonic_ns(), "event": event, **allowed}
        try:
            # Do not create any directories or pick a default output path.
            # In particular, no record is written without explicit opt-in.
            flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            handle = os.open(self.path, flags, 0o600)
            try:
                os.write(handle, (json.dumps(payload, separators=(",", ":")) + "\n").encode("ascii"))
            finally:
                os.close(handle)
        except OSError:
            return False
        self.count += 1
        return True
