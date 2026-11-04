"""Patch 296: Handbuch und Terminal parallel statt modal bedienen."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

SRC = Path(__file__).with_name("main.py")
GUI = Path(__file__).with_name("shelldeck_help_dialog.py")


def _function_in_class(path: Path, class_name: str, method_name: str, globals_: dict):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body
               if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in cls.body
                  if isinstance(node, ast.FunctionDef) and node.name == method_name)
    namespace = dict(globals_)
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[method_name]


def test_f1_non_modal_and_persistent_window_integration():
    code = SRC.read_text(encoding="utf-8")
    gui = GUI.read_text(encoding="utf-8")
    method = _function_in_class(SRC, "TerminalWindow", "show_help_dialog", {})
    assert "exec" not in method.__code__.co_names
    assert "show" in method.__code__.co_names
    assert "_help_window" in method.__code__.co_names
    assert "self._help_window = None" in code
    assert "self._help_window.close()" in code
    assert "Qt.WindowType.Window" in gui
    assert "Qt.WindowModality.NonModal" in gui
    assert "Qt.WidgetAttribute.WA_DeleteOnClose, False" in gui
    assert "Qt.WidgetAttribute.WA_QuitOnClose, False" in gui
    assert 'QPushButton("▥ Nebeneinander")' in gui
    assert "dialog.raise_()" in code
    assert "dialog.activateWindow()" in code
    assert "F1" in code


def test_tiling_only_changes_window_geometry_not_shell_state():
    class Rectangle:
        def __init__(self, x, y, w, h):
            self._values = x, y, w, h
        def x(self): return self._values[0]
        def y(self): return self._values[1]
        def width(self): return self._values[2]
        def height(self): return self._values[3]

    class Window:
        def __init__(self, min_width=0):
            self.geometry_calls = []
            self.show_normal = 0
            self._minimum_width = min_width
        def minimumWidth(self): return self._minimum_width
        def setGeometry(self, *args): self.geometry_calls.append(args)
        def showNormal(self): self.show_normal += 1
        def isWindow(self): return True

    screen = SimpleNamespace(availableGeometry=lambda: Rectangle(10, 32, 1600, 900))
    terminal = Window(min_width=620)
    terminal.screen = lambda: screen
    help_window = Window(min_width=650)
    help_window.parentWidget = lambda: terminal
    help_window.raise_ = Mock()
    info = Mock()
    arrange = _function_in_class(GUI, "ShellDeckHelpDialog", "arrange_next_to_terminal", {
        "QApplication": SimpleNamespace(primaryScreen=lambda: screen),
        "QMessageBox": SimpleNamespace(information=info),
    })
    assert arrange(help_window) is True
    assert len(terminal.geometry_calls) == len(help_window.geometry_calls) == 1
    left = terminal.geometry_calls[0]
    right = help_window.geometry_calls[0]
    assert left[0] == 10 and right[0] == left[0] + left[2] + 8
    assert left[2] + right[2] + 8 == 1600
    assert left[3] == right[3] == 900
    assert terminal.show_normal == help_window.show_normal == 1
    help_window.raise_.assert_called_once()
    info.assert_not_called()

    # Auf schmalen Displays keine zwangsweise unbrauchbare Fensterbreite.
    screen.availableGeometry = lambda: Rectangle(0, 0, 900, 700)
    assert arrange(help_window) is False
    assert len(terminal.geometry_calls) == len(help_window.geometry_calls) == 1
    info.assert_called_once()


def test_help_is_reusable_and_preserves_its_search_if_pyside_is_available():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QWidget
    from shelldeck_help_dialog import ShellDeckHelpDialog
    app = QApplication.instance() or QApplication([])
    owner = QWidget()
    owner.show()
    manual = ShellDeckHelpDialog("ShellDeck 2.16\n\nOllama\n- Chat\n\nVorbefehl\n- Text", owner)
    manual.show()
    assert not manual.isModal()
    assert manual.windowFlags() & Qt.WindowType.Window
    manual.search_edit.setText("ollama")
    found = manual.status.text()
    manual.close()
    assert not manual.isVisible()
    manual.show()
    assert manual.search_edit.text() == "ollama"
    assert manual.status.text() == found
    manual.close()
    owner.close()
