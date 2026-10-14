"""Regression tests for the opt-in independent Vim VT reference tool."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "shelldeck_vt_vim_reference.py"
spec = importlib.util.spec_from_file_location("vim_reference", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_geometry(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"event": "trace_started", "rows": 58, "cols": 235}) + "\n", encoding="utf-8")
    assert mod.start_geometry(events) == (58, 235)


def test_alternate_checkpoints():
    raw = b"before" + mod.ENTER + (b"xyz" * 100) + mod.EXIT
    marks = mod.checkpoints(raw, 4)
    assert len(marks) == 4
    assert marks == sorted(marks)
    assert marks[0] > raw.find(mod.ENTER)
    assert marks[-1] < raw.find(mod.EXIT)


def test_invalid_counts():
    import pytest
    with pytest.raises(ValueError):
        mod.checkpoints(mod.ENTER + b"hello", 0)


def test_vim_quote():
    assert mod.vim_quote("a'b") == "'a''b'"


def test_vim_renders_simple_screen():
    import pytest
    if not mod.vim_supported():
        pytest.skip("Vim +terminal nicht installiert")
    rows = mod.vim_screen(b"hello\x1b[2;1Hworld", 4, 40)
    assert rows[0].startswith("hello")
    assert rows[1].startswith("world")
