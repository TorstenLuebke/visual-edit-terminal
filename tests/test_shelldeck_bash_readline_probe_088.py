"""Tests fuer genaue Readline-Prompt-/Cursor-Sollwerte."""
import importlib.util
from pathlib import Path

def _probe():
    path = Path(__file__).resolve().parents[1] / 'tools' / 'shelldeck_bash_readline_probe_087.py'
    spec = importlib.util.spec_from_file_location('readline087', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def test_prompt_whitespace_counts_for_cursor():
    f = _probe().evaluate_cursor_and_line
    assert f('TEST$ ' + ' '*20, 6, 'TEST$ ', '')['cursor_at_end']
    assert f('TEST$ ' + ' '*20, 6, 'TEST$ ', '')['line_matches']

def test_catches_stale_characters_and_cursor_offset():
    f = _probe().evaluate_cursor_and_line
    assert not f('TEST$ exitvenv/bin/activate', 10, 'TEST$ ', 'exit')['line_matches']
    assert not f('TEST$ exit' + ' '*10, 8, 'TEST$ ', 'exit')['cursor_at_end']

def test_colored_prompt_has_readline_nonprinting_markers():
    ps1, visible = _probe().PROMPTS['colored']
    assert ps1.count(r'\[') == ps1.count(r'\]')
    assert r'\e[' in ps1
    assert len(visible) > 25

def test_history_steps_preserved():
    assert len(_probe().STEPS) == 7
