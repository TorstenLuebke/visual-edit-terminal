"""Regression tests for history bar visibility after restart and PTY mode changes."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QPushButton, QTableWidget, QWidget
from shelldeck_terminal_widget import TerminalTab


class HistoryVisibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_tab(self, pty):
        # Drive the exact visibility method without starting any PTY processes.
        class StandIn:
            pass
        tab = StandIn()
        tab.process_uses_pty_engine = lambda: pty
        tab.real_terminal_active = pty
        tab.command_task_panel_visible = True
        tab.command_task_panel_expanded = True
        tab.command_task_header = QPushButton()
        tab.command_task_list = QTableWidget()
        tab.command_task_header.show()
        tab.command_task_list.show()
        return tab

    def test_pty_hidden_even_with_restored_true_preferences(self):
        tab = self.make_tab(True)
        TerminalTab.sync_command_task_panel_visibility(tab)
        self.assertTrue(tab.command_task_header.isHidden())
        self.assertTrue(tab.command_task_list.isHidden())

    def test_classic_history_preference_preserved(self):
        tab = self.make_tab(False)
        TerminalTab.sync_command_task_panel_visibility(tab)
        self.assertFalse(tab.command_task_header.isHidden())
        self.assertFalse(tab.command_task_list.isHidden())
        self.assertTrue(tab.command_task_panel_visible)


if __name__ == "__main__":
    unittest.main()
