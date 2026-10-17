"""Regression: ordinary QProcess output still decodes without completion marker."""
import ast
from pathlib import Path
import unittest


class NoMarkerPathTests(unittest.TestCase):
    def test_handle_stdout_has_decoder_fallback(self):
        module = ast.parse(Path(__file__).with_name(
            "shelldeck_terminal_widget.py").read_text(encoding="utf-8"))
        widget = next(node for node in module.body if isinstance(node, ast.ClassDef)
                      and node.name == "ShellDeckTerminalWidget")
        method = next(node for node in widget.body if isinstance(node, ast.FunctionDef)
                      and node.name == "handle_stdout")
        condition = next(node for node in ast.walk(method) if isinstance(node, ast.If)
                         and isinstance(node.test, ast.BoolOp)
                         and "decoder is not None" in ast.unparse(node.test))
        self.assertTrue(condition.orelse, "Fallback for a missing decoder is required")
        fallback = ast.unparse(ast.Module(body=condition.orelse, type_ignores=[]))
        self.assertIn("data = self.decoded_terminal_output(", fallback)
        self.assertIn("qprocess_stream", fallback)


if __name__ == "__main__":
    unittest.main()
