"""Intermediate-screen diagnostics: identical checkpoint offsets regardless of reads."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from shelldeck_vt_checkpoint_probe_083 import checkpoint_offsets, compare, replay_checkpoints


def test_checkpoints_cover_alt_enter_exit_and_end():
    raw = b"abc\x1b[?1049hhello\x1b[?1049lprompt"
    points = checkpoint_offsets(raw, 24, count=3)
    assert len(raw) in points
    assert raw.index(b"\x1b[?1049h") + len(b"\x1b[?1049h") in points
    assert raw.index(b"\x1b[?1049l") + len(b"\x1b[?1049l") in points
    assert points == sorted(set(points))


def test_invalid_arguments():
    with pytest.raises(ValueError, match="Leere"):
        checkpoint_offsets(b"", 5)
    with pytest.raises(ValueError, match="count"):
        checkpoint_offsets(b"abc", 5, count=0)
    with pytest.raises(ValueError, match="Terminalgroesse"):
        compare(b"abc", 0, 20)
    with pytest.raises(ValueError, match="chunk_size"):
        replay_checkpoints(b"abc", 5, 20, [3], 0)


class DummyScreen:
    def __init__(self, rows, cols, enable_history):
        self.data = b""
        self.screen = self
        self.alternate_active = False
        self.rows = rows

    def feed(self, raw):
        self.data += raw
        self.alternate_active = self.data.rfind(b"\x1b[?1049h") > self.data.rfind(b"\x1b[?1049l")

    def display(self):
        return [str(len(self.data))] + [""] * (self.rows - 1)


def test_probe_compares_same_offsets_not_only_final_image():
    raw = b"\x1b[?1049h" + b"0123456789" * 10 + b"\x1b[?1049l" + b"prompt"
    report = compare(raw, 5, 80, count=5, sizes=(1, 7, 64), screen_factory=DummyScreen)
    assert report["checkpoint_count"] >= 7
    assert all(v["different_checkpoints"] == 0 for v in report["variants"])


@pytest.mark.parametrize("chunk", (1, 2, 7, 128))
def test_pyte_state_at_intermediate_boundaries(chunk):
    pytest.importorskip("pyte")
    raw = (b"\x1b[?1049h\x1b[12;29r\x1b[12;1H" + "Grün".encode() +
           b"\x1b[13;1HOLD_LONG_COMMAND\x1b[10S\x1b[12;1HNEW\x1b[K"
           b"\x1b[?1049lprompt")
    report = compare(raw, 58, 235, count=7, sizes=(chunk,))
    assert report["variants"][0]["different_checkpoints"] == 0, report
