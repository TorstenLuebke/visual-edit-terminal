"""Regression checks: focus tracing is opt-in and does not capture user input."""
import json
from types import SimpleNamespace

from shelldeck_wayland_focus_trace import install_focus_trace, describe_focus_widget


class FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)


class FakeApp:
    def __init__(self):
        self.focusChanged = FakeSignal()


def test_focus_trace_off_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("SHELLDECK_FOCUS_TRACE_PATH", raising=False)
    app = FakeApp()
    assert install_focus_trace(app) is None
    assert not app.focusChanged.callbacks
    assert not list(tmp_path.iterdir())


def test_focus_trace_records_types_only(tmp_path):
    path = tmp_path / "focus.jsonl"
    app = FakeApp()
    assert install_focus_trace(app, path=path)

    class Widget:
        text = "SECRET USER INPUT"
        objectName = "SECRET OBJECT NAME"

    app.focusChanged.callbacks[0](None, Widget())
    entry = json.loads(path.read_text(encoding="utf-8").strip())
    assert entry["old_type"] is None
    assert entry["new_type"] == "Widget"
    assert entry["event"] == "focus_changed"
    assert "SECRET" not in path.read_text(encoding="utf-8")
    assert describe_focus_widget(None) is None


def test_focus_trace_write_error_is_nonfatal(tmp_path):
    app = FakeApp()
    install_focus_trace(app, path=tmp_path / "missing" / "focus.jsonl")
    app.focusChanged.callbacks[0](SimpleNamespace(), None)
