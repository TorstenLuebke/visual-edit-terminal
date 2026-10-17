"""Regression: rejected batch command must not change cached working directory."""
import ast
from pathlib import Path
import unittest


class TestBatchRejectedContext(unittest.TestCase):
    def test_rejection_precedes_context_update(self):
        path = Path(__file__).with_name("shelldeck_terminal_widget.py")
        module = ast.parse(path.read_text(encoding="utf-8"))
        cls = next(c for c in module.body if isinstance(c, ast.ClassDef) and
                   any(isinstance(m, ast.FunctionDef) and m.name == "write_shell_command" for m in c.body))
        fn = next(m for m in cls.body if isinstance(m, ast.FunctionDef) and m.name == "write_shell_command")
        early_statements = ast.unparse(fn.body[:5])
        self.assertIn("_bash_completion_pending", early_statements)
        self.assertIn("return", early_statements)
        self.assertLess(early_statements.index("_bash_completion_pending"), early_statements.index("update_working_context_from_shell_command"))


if __name__ == "__main__":
    unittest.main()
