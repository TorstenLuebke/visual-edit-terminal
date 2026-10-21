from pathlib import Path
from shelldeck_wezterm_checkout_262 import inspect_checkout


def test_missing_checkout(tmp_path):
    report = inspect_checkout(tmp_path / "missing")
    assert report["valid"] is False
    assert report["revision"] is None


def test_non_git_directory(tmp_path):
    report = inspect_checkout(tmp_path)
    assert report["valid"] is False
