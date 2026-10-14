"""Independent expectations for the VT scroll sequences added in 078."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from shelldeck_vt_scroll_oracle_079 import EXPECTED, check_rows, run
from shelldeck_vt_sequence_probe import fixture_cases


def test_oracle_covers_all_078_sequences():
    assert set(EXPECTED) == set(fixture_cases())
    assert EXPECTED["scroll_up_then_el"][13] == ""
    assert EXPECTED["scroll_down_then_el"][22] == "1234 command-long-long-long"
    assert EXPECTED["scroll_down_then_el"][23] == "5678 second-old-command"


def test_oracle_uses_one_based_rows_and_catches_stale_suffix():
    assert check_rows(["HEADER ", "shortOLD"], {1: "HEADER", 2: "short"}) == [
        {"row": 2, "expected": "short", "observed": "shortOLD"}
    ]


def test_pyte_simple_overwrites_match_oracle():
    pytest.importorskip("pyte")
    result = {item["case"]: item for item in run(use_vim=False)["cases"]}
    assert result["shorter_with_el"]["pyte_mismatches"] == []
    assert result["shorter_with_ech"]["pyte_mismatches"] == []


@pytest.mark.xfail(reason="Bis zur Korrektur: pyte-Scrollbereich gegen unabhängiges Soll prüfen", strict=False)
def test_pyte_scroll_operations_match_oracle():
    pytest.importorskip("pyte")
    result = {item["case"]: item for item in run(use_vim=False)["cases"]}
    assert all(not result[name]["pyte_mismatches"] for name in (
        "scroll_up_then_el", "scroll_down_then_el", "up_down_then_el", "up_down_then_ech"))
