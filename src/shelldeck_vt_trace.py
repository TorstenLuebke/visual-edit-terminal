"""Opt-in, size-limited raw PTY output trace for VT parser diagnostics.

Captured bytes may contain credentials or private terminal content. No data is
written until the caller explicitly exports it. This class has no Qt dependency.
"""

import json
import time


class VtRawTrace:
    def __init__(self, limit=4 * 1024 * 1024):
        self.limit = int(limit)
        self.active = False
        self.truncated = False
        self._chunks = []
        self._size = 0
        self.events = []
        self._started = None
        self._last_assist_visible = None

    def start(self):
        self._chunks.clear()
        self._size = 0
        self.truncated = False
        self.events = []
        self._last_assist_visible = None
        self._started = time.monotonic()
        self.active = True

    def append(self, data):
        if not self.active or not isinstance(data, (bytes, bytearray)):
            return
        data = bytes(data)
        remaining = max(0, self.limit - self._size)
        if len(data) > remaining:
            self.truncated = True
            self.active = False
        if remaining:
            part = data[:remaining]
            if part:
                self._chunks.append(part)
                self._size += len(part)

    def event(self, name, **fields):
        """Only metadata; never raw input, command text or environment values."""
        if not self.active:
            return
        allowed = {"rows", "cols", "width", "height", "old_rows", "old_cols",
                   "visible", "alternate", "top", "bottom", "success"}
        safe = {key: value for key, value in fields.items()
                if key in allowed and type(value) in (int, bool)}
        # Record assist visibility changes, not polling ticks. Keep the first
        # sample after each start() even when the panel is initially hidden.
        if name == "assist_panel" and type(safe.get("visible")) is bool:
            visible = safe["visible"]
            if visible == self._last_assist_visible:
                return
            self._last_assist_visible = visible
        self.events.append({"ms": round((time.monotonic() - self._started) * 1000),
                            "byte_offset": self._size, "event": str(name), **safe})

    def events_jsonl(self):
        return "".join(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n"
                       for event in self.events)

    def stop(self):
        self.active = False
        return b''.join(self._chunks)

    @property
    def size(self):
        return self._size
