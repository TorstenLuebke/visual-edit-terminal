"""Regression tests for backend-specific terminal focus routing."""
import os
import unittest
from unittest.mock import Mock, patch
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication, QWidget
    from main import TerminalWindow
except ImportError:
    QApplication = None


@unittest.skipUnless(QApplication is not None, "PySide6 required")
class TerminalFocusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.grid, self.editor = QWidget(), QWidget()
        self.grid.show()
        self.editor.show()
        self.addCleanup(self.grid.close)
        self.addCleanup(self.editor.close)

    def check_focus(self, real, expected):
        class FakeTab:
            pass
        tab = FakeTab()
        tab.real_terminal_active = real
        tab.terminal_grid = self.grid
        tab.input_line = self.editor
        window = Mock()
        window.current_terminal.return_value = tab
        with patch("main.TerminalTab", FakeTab), patch.object(
                QApplication, "activeModalWidget", return_value=None):
            self.assertTrue(TerminalWindow.focus_active_terminal(window))
        self.assertTrue(expected.hasFocus())

    def test_pty_focus_goes_to_grid(self):
        self.check_focus(True, self.grid)

    def test_classic_focus_goes_to_editor(self):
        self.check_focus(False, self.editor)

    def test_hidden_grid_is_not_focused(self):
        class FakeTab:
            pass
        tab = FakeTab()
        tab.real_terminal_active = True
        tab.terminal_grid = self.grid
        tab.input_line = self.editor
        self.grid.hide()
        window = Mock()
        window.current_terminal.return_value = tab
        with patch("main.TerminalTab", FakeTab), patch.object(
                QApplication, "activeModalWidget", return_value=None):
            self.assertFalse(TerminalWindow.focus_active_terminal(window))


if __name__ == "__main__":
    unittest.main()
