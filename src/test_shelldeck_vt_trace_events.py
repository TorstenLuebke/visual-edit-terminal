"""Regression tests for opt-in geometry/PTY trace metadata."""
import json
from shelldeck_vt_trace import VtRawTrace


def test_events_off_by_default():
    trace = VtRawTrace()
    trace.event("grid_focus_in")
    assert trace.events_jsonl() == ""


def test_focus_does_not_modify_grid_or_bytes():
    trace = VtRawTrace()
    trace.start()
    trace.append(b"abc")
    trace.event("grid_focus_out")
    trace.event("grid_focus_in")
    assert trace.size == 3
    assert trace.stop() == b"abc"
    events = [json.loads(line) for line in trace.events_jsonl().splitlines()]
    assert [event["byte_offset"] for event in events] == [3, 3]
    assert all("rows" not in event for event in events)


def test_geometry_and_privacy_filter():
    trace = VtRawTrace()
    trace.start()
    trace.event("grid_cells_changed", old_rows=61, old_cols=235,
                rows=58, cols=235, command="SECRET", width=1600)
    event = json.loads(trace.events_jsonl())
    assert event["rows"] == 58
    assert event["old_rows"] == 61
    assert "SECRET" not in trace.events_jsonl()
    assert "command" not in event


def test_events_not_collected_after_stop():
    trace = VtRawTrace()
    trace.start()
    trace.stop()
    trace.event("pty_resize", rows=20, cols=80)
    assert trace.events_jsonl() == ""
