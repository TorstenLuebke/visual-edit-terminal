"""End-to-end Tastatureingabe ohne reale Benutzer-Historie."""
import os
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_089_sequences_cover_multiple_history_roundtrips():
    from shelldeck_qt_bash_probe_089 import STEPS
    assert [step[2] for step in STEPS].count("up") >= 3
    assert [step[2] for step in STEPS].count("down") >= 2


@pytest.mark.parametrize("mode", ("plain", "colored"))
def test_089_qt_to_bash_history_and_cursor(mode):
    pytest.importorskip("PySide6")
    pytest.importorskip("pyte")
    from shelldeck_qt_bash_probe_089 import run
    result = run(mode)
    assert result["passed"], result["steps"]
    for step in result["steps"]:
        assert step["qt_write_calls"] >= 1, step
        assert step["pty_output_bytes"] > 0, step
