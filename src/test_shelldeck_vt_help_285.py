"""Guards for the real Help menu and identical F1/diagnostic instructions.

The business rules are testable without importing Qt or changing live PTYs.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from shelldeck_vt_diagnostics_help_283 import vt_diagnostics_help_section

SOURCE = Path(__file__).with_name("main.py")


def _window_class():
    return next(
        node for node in ast.parse(SOURCE.read_text(encoding="utf-8")).body
        if isinstance(node, ast.ClassDef) and node.name == "TerminalWindow"
    )


def _method(name):
    return next(
        node for node in _window_class().body
        if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _load_method(name):
    node = _method(name)
    code = compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                   str(SOURCE), "exec")
    namespace = {"APP_NAME": "ShellDeck Terminal", "APP_VERSION": "test",
                 "vt_diagnostics_help_section": vt_diagnostics_help_section}
    exec(code, namespace)
    return namespace[name]


def test_help_text_covers_both_capture_modes_privacy_and_stop_button():
    text = vt_diagnostics_help_section()
    for required in (
        "VT-Diagnose: Modell und Ansicht speichern",
        "VT-Rohdatenaufzeichnung starten",
        "ShellDeck neu starten + Startaufzeichnung",
        "● REC", "■ Stopp", "*_Ereignisse.jsonl",
        "*_Startmodell.txt", "*_Endmodell.txt", "4 MiB",
        "sensible Inhalte", "standardmaessig ausgeschaltet",
    ):
        assert required in text, required


def test_f1_help_contains_the_same_section_and_current_precommands():
    fake = SimpleNamespace()
    help_text = _load_method("help_text")(fake)
    assert vt_diagnostics_help_section() in help_text
    assert "In einem echten lokalen Bash-PTY" in help_text
    assert "Eingaben an laufende interaktive Programme" in help_text


def test_dedicated_help_action_calls_own_read_only_dialog():
    fake = SimpleNamespace(_show_read_only_help_dialog=Mock())
    _load_method("show_vt_diagnostics_help_dialog")(fake)
    fake._show_read_only_help_dialog.assert_called_once_with(
        "Terminaldiagnose — ShellDeck Terminal", vt_diagnostics_help_section()
    )


def test_existing_f1_action_keeps_same_destination():
    fake = SimpleNamespace(help_text=Mock(return_value="old help"),
                           _show_read_only_help_dialog=Mock())
    _load_method("show_help_dialog")(fake)
    fake._show_read_only_help_dialog.assert_called_once_with(
        "Hilfe — ShellDeck Terminal", "old help"
    )


def test_menu_wiring_is_action_not_just_text():
    constructor = _method("__init__")
    source = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), constructor)
    assert source is not None
    needle = 'QAction("Terminaldiagnose und Aufzeichnung …", self)'
    assert needle in source
    assert "vt_diagnostics_help_action.triggered.connect(self.show_vt_diagnostics_help_dialog)" in source
    assert "help_menu.addAction(vt_diagnostics_help_action)" in source
    assert 'help_action.setShortcut("F1")' in source


def test_help_contains_no_io_or_terminal_operations():
    """Documentation remains a plain function: never start capture by opening help."""
    from shelldeck_vt_diagnostics_help_283 import vt_diagnostics_help_section as func
    assert not func.__code__.co_names  # no subprocess/PTY, UI or filesystem calls


def test_documentation_mentions_consent_and_unimplemented_visualedit_import():
    docs = (SOURCE.parent.parent / "docs" / "shelldeck_vt_diagnose_benutzerhilfe_284.md").read_text(
        encoding="utf-8")
    assert "nach expliziter Zustimmung" in docs
    assert "noch **nicht** implementiert" in docs
    assert "F1" in docs


def test_read_only_dialog_uses_read_only_text_view():
    method = _method("_show_read_only_help_dialog")
    source = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"), method)
    assert source is not None
    assert "text.setReadOnly(True)" in source
    assert "dialog.exec()" in source
