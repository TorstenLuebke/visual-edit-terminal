"""Unit tests for offline replay with a deterministic fake VT model."""
import importlib.util
from pathlib import Path

p = Path(__file__).resolve().parents[1] / 'tools' / 'shelldeck_vt_replay.py'
spec = importlib.util.spec_from_file_location('shelldeck_vt_replay', p)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FakeModel:
    def __init__(self, rows, cols):
        self.rows, self.cols = rows, cols
        self.active = False
        self.text = ''
    def feed(self, raw):
        for char in raw.decode('ascii'):
            if char == '<':
                self.active = True
                self.text = ''
            elif char == '>':
                self.active = False
                self.text = 'prompt'
            elif self.active:
                self.text += char
    def resize(self, rows, cols):
        self.rows, self.cols = rows, cols
    def in_alternate_screen(self):
        return self.active
    def display(self):
        return [self.text]


def test_preserves_active_screen_even_after_exit():
    result = module.replay(b'<BADLINES>prompt', 61, 235, chunk_size=1, model_factory=FakeModel)
    assert result['final']['alternate'] is False
    assert any(snapshot['alternate'] and 'BADLINES' in snapshot['lines'][0]
               for _, snapshot in result['samples'])


def test_resize_at_recorded_byte_offset():
    result = module.replay(b'<DATA', 61, 235, events=[(1, 58, 235)], chunk_size=1,
                           model_factory=FakeModel)
    assert result['final']['rows'] == 58
    assert any(s['rows'] == 58 for _, s in result['samples'])


def test_initial_geometry_taken_from_trace(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"event":"trace_started","rows":58,"cols":235}\n'
                     '{"event":"assist_panel","visible":true}\n', encoding="utf-8")
    assert module.resolve_geometry(trace) == (58, 235)
    assert module.resolve_geometry(trace, rows=60) == (60, 235)


def test_missing_trace_requires_explicit_geometry(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"event":"assist_panel","visible":false}\n', encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="--rows UND --cols"):
        module.resolve_geometry(trace)
    assert module.resolve_geometry(trace, rows=24, cols=80) == (24, 80)


def test_invalid_geometry_rejected(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text('{"event":"trace_started","rows":0,"cols":235}\n', encoding="utf-8")
    import pytest
    with pytest.raises(ValueError, match="Anfangsgeometrie"):
        module.resolve_geometry(trace)
