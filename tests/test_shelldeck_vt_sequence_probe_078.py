"""Regression checks for deterministic VT probe (patch 078)."""
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

from shelldeck_vt_sequence_probe import fixture_cases, compare_cases


def test_cases_are_distinct_and_end_on_complete_csi():
    cases = fixture_cases()
    assert len(cases) == 6
    assert all(trace.startswith(b"\x1b[?1049h") for trace in cases.values())
    assert all(trace.endswith(b"\x1b[1;58r") or trace.endswith(b"\x1b[K") or trace.endswith(b"\x1b[21X") for trace in cases.values())
    assert b"\x1b[10S" in cases["up_down_then_el"]
    assert b"\x1b[10T" in cases["up_down_then_el"]


def test_geometry_guard():
    with pytest.raises(ValueError):
        fixture_cases(10, 235)
    with pytest.raises(ValueError):
        fixture_cases(58, 20)


def test_local_pyte_render_does_not_keep_suffix():
    pytest.importorskip("pyte")
    from shelldeck_vt_vim_reference import pyte_screens
    cases = fixture_cases()
    raw = cases["shorter_with_el"]
    lines = pyte_screens(raw, 58, 235, [len(raw)])[len(raw)]
    assert lines[11].rstrip() == "1234 short"
    assert lines[0].rstrip() == "HEADER-UNCHANGED"


def test_independent_reference_agrees_on_simple_overwrite():
    pytest.importorskip("pyte")
    from shelldeck_vt_vim_reference import vim_supported
    if not vim_supported():
        pytest.skip("Vim +terminal fehlt")
    report = compare_cases()
    result = {s["case"]: s for s in report["snapshots"]}
    assert result["shorter_with_el"]["different_rows"] == 0
