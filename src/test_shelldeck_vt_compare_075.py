"""Basic integrity tests for the offline native-pyte comparison."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from shelldeck_vt_compare import alternate_interval, fixed_chunks, matching_geometry


def test_alt_interval_excludes_exit():
    raw = b"bash" + b"\x1b[?1049h" + b"screen" + b"\x1b[?1049l" + b"prompt"
    a, b = alternate_interval(raw)
    assert raw[a:b] == b"screen"


def test_chunk_boundaries_lossless():
    raw = b"abcdefghij"
    parts = list(fixed_chunks(raw, 2, 9, 3))
    assert parts == [(5, b"cde"), (8, b"fgh"), (9, b"i")]
    assert b"".join(part for _, part in parts) == raw[2:9]


def test_geometry_from_trace(tmp_path):
    p = tmp_path / "events.jsonl"
    p.write_text('{"event":"trace_started","rows":58,"cols":235}\n', encoding="utf-8")
    assert matching_geometry(p) == (58, 235)
