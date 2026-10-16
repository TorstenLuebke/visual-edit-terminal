"""Regression safeguards for the content-safe Readline probe."""
import importlib.util
from pathlib import Path


def _load():
    path = Path(__file__).resolve().parents[1] / "tools" / "shelldeck_bash_readline_probe_087.py"
    spec = importlib.util.spec_from_file_location("bash_readline_probe_087", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_probe_covers_history_directions_and_fresh_input():
    steps = _load().STEPS
    labels = [step[0] for step in steps]
    assert labels == ["short", "long", "up-long", "up-short", "down-long", "down-empty", "type-new"]


def test_probe_does_not_read_user_history():
    source = (_load().__file__ and Path(_load().__file__).read_text(encoding="utf-8"))
    assert 'HISTFILE="/dev/null"' in source
    assert '"--noprofile", "--norc"' in source


def test_probe_uses_same_terminal_key_encoding_as_grid():
    from shelldeck_key_encoding import encode_key
    steps = _load().STEPS
    assert steps[2][1] == encode_key("Up")
    assert steps[4][1] == encode_key("Down")
