"""Regression tests for explicit QProcess-Bash crash recovery."""
import ast
import pathlib
import unittest

SOURCE = pathlib.Path(__file__).with_name("shelldeck_terminal_widget.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
CLASS = next(c for c in TREE.body if isinstance(c, ast.ClassDef) and any(isinstance(n, ast.FunctionDef) and n.name == 'restart_lost_batch_shell' for n in c.body))
METHOD = next(n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name == 'restart_lost_batch_shell')

class BatchRecoveryTests(unittest.TestCase):
    def test_requires_lost_state(self):
        self.assertIn('_batch_shell_lost_state', ast.unparse(METHOD))
        self.assertIn('process_is_running', ast.unparse(METHOD))

    def test_requires_explicit_confirmation(self):
        self.assertIn('QMessageBox.question', ast.unparse(METHOD))
        self.assertIn('QMessageBox.StandardButton.No', ast.unparse(METHOD))

    def test_context_menu_offers_recovery(self):
        menu = next(n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name == 'show_terminal_context_menu')
        self.assertIn('restart_lost_batch_shell', ast.unparse(menu))

    def test_new_start_clears_old_decoder(self):
        reset = next(n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name == '_reset_shell_transient_state')
        self.assertIn('_bash_completion_decoder', ast.unparse(reset))
        self.assertIn('_batch_shell_lost_state', ast.unparse(reset))
