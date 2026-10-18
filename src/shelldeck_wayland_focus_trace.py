"""Opt-in Qt focus diagnostics without recording user input or widget names.

Set SHELLDECK_FOCUS_TRACE_PATH to a JSONL output path before starting the GUI.
No trace file is opened or created unless that variable is explicitly set.
"""

import json
import os
import time
from pathlib import Path


def describe_focus_widget(widget):
    """Return only non-identifying Qt class information, never content."""
    if widget is None:
        return None
    try:
        return type(widget).__name__
    except (AttributeError, RuntimeError, TypeError):
        return "unavailable"


def install_focus_trace(app, path=None):
    """Connect Qt focus changes to an opt-in JSONL trace; return callback.

    A callback reference is retained on QApplication to avoid collection.
    Failures to write the optional diagnostic must never affect the GUI.
    """
    target = str(path if path is not None else os.environ.get("SHELLDECK_FOCUS_TRACE_PATH", "")).strip()
    if not target:
        return None
    target_path = Path(target).expanduser()

    def record(old, new):
        entry = {
            "event": "focus_changed",
            "monotonic_ns": time.monotonic_ns(),
            "old_type": describe_focus_widget(old),
            "new_type": describe_focus_widget(new),
        }
        try:
            with target_path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError:
            pass

    app.focusChanged.connect(record)
    app._shelldeck_focus_trace_callback = record
    return record
