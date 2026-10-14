"""Focused VT comparison tests for patch 077 (no runtime changes)."""
from __future__ import annotations
import importlib.util
from pathlib import Path
import pytest

MODULE = Path(__file__).resolve().parents[1] / "tools" / "shelldeck_vt_vim_reference.py"
spec = importlib.util.spec_from_file_location("shelldeck_ref_077", MODULE)
ref = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ref)


def test_margin_checkpoint_positions():
    raw = ref.ENTER + b"A" + b"\x1b[2;5r" + b"B" + b"\x1b[1;8r" + b"C" + b"\x1b[1;8r" + ref.EXIT
    first = raw.index(b"\x1b[1;8r") + len(b"\x1b[1;8r")
    second = raw.rindex(b"\x1b[1;8r") + len(b"\x1b[1;8r")
    assert ref.margin_reset_checkpoints(raw, 8) == [first, second]
    assert ref.margin_reset_checkpoints(raw, 9) == []
    with pytest.raises(ValueError):
        ref.margin_reset_checkpoints(raw, 8, 0)


def test_shorter_line_is_cleared_in_pyte_and_vim():
    pytest.importorskip("pyte")
    if not ref.vim_supported():
        pytest.skip("Vim +terminal fehlt")
    trace = ref.synthetic_overwrite_trace()
    shell = ref.pyte_screens(trace, 4, 40, [len(trace)])[len(trace)]
    vim = ref.vim_screen(trace, 4, 40)
    assert shell[0].rstrip() == "1234 short"
    assert vim[0].rstrip() == "1234 short"


def test_compare_reports_margin_mode(tmp_path, monkeypatch):
    event = tmp_path / "events.jsonl"
    event.write_text('{"event":"trace_started","rows":8,"cols":40}\n')
    trace = ref.ENTER + b"abc\x1b[1;8r" + ref.EXIT
    monkeypatch.setattr(ref, "pyte_screens", lambda raw, rows, cols, offsets: {n: ["OK"] * rows for n in offsets})
    monkeypatch.setattr(ref, "vim_screen", lambda raw, rows, cols, binary="vim": ["OK"] * rows)
    report = ref.compare(trace, event, checkpoint_mode="margin")
    assert report["checkpoint_mode"] == "margin"
    assert len(report["snapshots"]) == 1
    assert report["snapshots"][0]["different_rows"] == 0
