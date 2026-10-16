"""Regression for PTY read-boundary independent scroll and CSI parsing."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from shelldeck_vt_chunk_probe_082 import compare
from shelldeck_vt_sequence_probe import fixture_cases


def test_empty_recording_rejected():
    with pytest.raises(ValueError, match="empty"):
        compare(b"", 58, 235)


def test_invalid_chunk_size_rejected():
    pytest.importorskip("pyte")
    from shelldeck_vt_chunk_probe_082 import replay
    with pytest.raises(ValueError, match="chunk_size"):
        replay(b"abc", 5, 10, 0)


@pytest.mark.parametrize("case", list(fixture_cases()))
def test_scroll_fixtures_independent_of_input_chunking(case):
    pytest.importorskip("pyte")
    raw = fixture_cases()[case]
    report = compare(raw, 58, 235)
    assert all(row["different_rows"] == 0 for row in report["variants"]), (case, report)


def test_split_utf8_and_csi_with_alternate_scroll_region():
    pytest.importorskip("pyte")
    raw = (b"\x1b[?1049h\x1b[12;29r\x1b[12;1H" + "Grün".encode("utf-8")
           + b"\x1b[13;1HOLD-LONG\x1b[10S\x1b[12;1HNEW\x1b[K")
    report = compare(raw, 58, 235, sizes=(1, 2, 3, 11))
    assert all(item["different_rows"] == 0 for item in report["variants"])
