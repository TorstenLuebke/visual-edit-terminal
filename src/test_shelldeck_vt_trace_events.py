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


def test_assist_panel_events_report_transitions_only():
    trace = VtRawTrace()
    trace.start()
    trace.event("assist_panel", visible=False)
    trace.append(b"abc")
    trace.event("assist_panel", visible=False)
    trace.event("grid_focus_in")
    trace.event("assist_panel", visible=True)
    trace.event("assist_panel", visible=True)
    trace.event("assist_panel", visible=False)
    events = [json.loads(row) for row in trace.events_jsonl().splitlines()]
    assert [row["event"] for row in events] == [
        "assist_panel", "grid_focus_in", "assist_panel", "assist_panel"]
    assert [row["visible"] for row in events if row["event"] == "assist_panel"] == [False, True, False]
    assert [row["byte_offset"] for row in events] == [0, 3, 3, 3]
    assert trace.stop() == b"abc"


def test_assist_dedup_resets_when_trace_restarted():
    trace = VtRawTrace()
    trace.start()
    trace.event("assist_panel", visible=False)
    trace.stop()
    trace.start()
    trace.event("assist_panel", visible=False)
    assert len(trace.events) == 1


def test_assist_event_dedup_does_not_filter_other_events():
    trace = VtRawTrace()
    trace.start()
    trace.event("pty_resize", rows=58, cols=235)
    trace.event("pty_resize", rows=58, cols=235)
    assert len(trace.events) == 2
