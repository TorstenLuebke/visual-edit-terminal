"""Lifecycle checks for abnormal batch Bash exits (no GUI required)."""
import ast
from pathlib import Path
import unittest

SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py").read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)
WIDGET = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ShellDeckTerminalWidget")

def method(name):
    return next(n for n in WIDGET.body if isinstance(n, ast.FunctionDef) and n.name == name)

class BatchExitStateTests(unittest.TestCase):
    def test_process_end_marks_state_lost_and_closes_task(self):
        code = ast.get_source_segment(SOURCE, method("_complete_qprocess_finish_if_drained"))
        self.assertIn("self._batch_shell_lost_state = True", code)
        self.assertLess(code.index("self._batch_shell_lost_state = True"), code.index("self._finalize_shell_process_finished(code)"))

    def test_restart_resets_old_decoder_and_lost_state(self):
        code = ast.get_source_segment(SOURCE, method("_reset_shell_transient_state"))
        for statement in ("self._batch_shell_lost_state = False", "self._bash_completion_pending = False", "self._bash_completion_decoder = None"):
            self.assertIn(statement, code)

    def test_dead_shell_cannot_receive_a_new_command(self):
        code = ast.get_source_segment(SOURCE, method("write_shell_command"))
        self.assertLess(code.index("_batch_shell_lost_state"), code.index("self.process.write("))

if __name__ == "__main__":
    unittest.main()
