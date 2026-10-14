"""Regression cases for DECSTBM + SU/SD on the alternate screen."""
import sys
from pathlib import Path

import pytest

pytest.importorskip("pyte")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from shelldeck_vt_screen import VtScreen
from shelldeck_vt_sequence_probe import fixture_cases
from shelldeck_vt_scroll_oracle_079 import EXPECTED, check_rows


@pytest.mark.parametrize("case", list(EXPECTED))
def test_alternate_screen_scroll_region_matches_independent_oracle(case):
    model = VtScreen(rows=58, cols=235, enable_history=False)
    model.feed(fixture_cases(58, 235)[case])
    assert model.screen.alternate_active
    assert check_rows(model.display(), EXPECTED[case]) == []


def test_scroll_uses_only_margins_and_preserves_outside_content():
    model = VtScreen(rows=30, cols=80, enable_history=False)
    esc = "\x1b["
    model.feed(esc + "?1049h" + esc + "1;1HOUTSIDE-TOP" + esc + "30;1HOUTSIDE-BOTTOM"
               + esc + "12;29r" + esc + "12;1Hfirst" + esc + "13;1Hsecond"
               + esc + "12;1H" + esc + "10T")
    lines = model.display()
    assert lines[0].rstrip() == "OUTSIDE-TOP"
    assert lines[-1].rstrip() == "OUTSIDE-BOTTOM"
    assert lines[11].rstrip() == ""
    assert lines[21].rstrip() == "first"
    assert lines[22].rstrip() == "second"


def test_scrolling_preserves_cell_attributes_and_reports_dirty_rows():
    model = VtScreen(rows=30, cols=80, enable_history=False)
    esc = "\x1b["
    model.feed(esc + "?1049h" + esc + "12;29r" + esc + "12;1H" + esc + "1;31mGREEN" + esc + "0m")
    model.clear_dirty()
    model.feed(esc + "1T")
    assert model.display()[12].startswith("GREEN")
    assert model.row_cells(12)[0]["bold"]
    assert 11 in model.dirty_lines() and 28 in model.dirty_lines()
