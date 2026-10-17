"""Small regression tests for QProcess batch UI state transitions."""
import ast
import pathlib
import unittest


_SOURCE = pathlib.Path(__file__).with_name("shelldeck_terminal_widget.py")


class BatchGuiStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = _SOURCE.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def test_second_command_guard_precedes_running_state_assignment(self):
        cls = next(c for c in self.tree.body if isinstance(c, ast.ClassDef) and any(
            isinstance(n, ast.FunctionDef) and n.name == "write_shell_command" for n in c.body))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "write_shell_command")
        # Check the guard's actual control flow rather than a comment's wording.
        guard = next(
            node for node in method.body
            if isinstance(node, ast.If)
            and "_qprocess_bash_batch" in ast.unparse(node.test)
            and "_bash_completion_pending" in ast.unparse(node.test)
        )
        self.assertTrue(any(isinstance(node, ast.Return) for node in guard.body))
        context_update = next(
            node for node in method.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and node.value.func.attr == "update_working_context_from_shell_command"
        )
        running_state = next(
            node for node in method.body
            if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Attribute)
                    and target.attr == "_awaiting_command_completion"
                    for target in node.targets)
        )
        self.assertLess(guard.lineno, context_update.lineno)
        self.assertLess(guard.lineno, running_state.lineno)

    def test_process_exit_clears_batch_wait_flag(self):
        self.assertIn('self._awaiting_command_completion = False\n        self._finalize_shell_process_finished(code)', self.source)

    def test_interactive_input_blocked_while_batch_pending(self):
        self.assertIn('A batch command reads from /dev/null', self.source)
