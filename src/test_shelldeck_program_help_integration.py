"""Klick auf Hilfe bleibt lesend und greift nie auf andere Tabs/Jobs zu."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

try:
    from PySide6.QtWidgets import QApplication
except ImportError:
    QApplication = None
if QApplication is not None:
    from shelldeck_terminal_widget import ShellDeckTerminalWidget


@unittest.skipUnless(QApplication is not None, 'PySide6 nicht verfuegbar')
class ProgramHelpIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_help_is_only_opened_for_checked_foreground(self):
        from shelldeck_program_assist import GUIDES
        fake = SimpleNamespace(_checked_detected_program=Mock(return_value=GUIDES['vim']),
                               real_terminal_active=False, terminal_grid=None)
        with patch('shelldeck_program_help_dialog.ProgramHelpDialog') as dialog:
            ShellDeckTerminalWidget._show_detected_program_help(fake)
            dialog.assert_called_once_with(GUIDES['vim'], fake)
            dialog.return_value.exec.assert_called_once_with()
            fake._checked_detected_program.return_value = None
            ShellDeckTerminalWidget._show_detected_program_help(fake)
            self.assertEqual(dialog.call_count, 1)
