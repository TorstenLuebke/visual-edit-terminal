"""QProcess must not add another venv prompt to an inherited one."""

import ast
from pathlib import Path
import unittest


class QProcessVenvPromptTests(unittest.TestCase):
    def test_inherited_venv_guard_is_qprocess_only(self):
        source = (Path(__file__).parent / "shelldeck_terminal_widget.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "create_shell_process":
                found.append(ast.get_source_segment(source, node))
        self.assertEqual(len(found), 1)
        method = found[0]
        self.assertLess(method.index("return process"), method.index("VIRTUAL_ENV_DISABLE_PROMPT"))
        self.assertIn('environment.contains("VIRTUAL_ENV")', method)
        self.assertIn('environment.insert("VIRTUAL_ENV_DISABLE_PROMPT", "1")', method)
        self.assertIn('not environment.contains("VIRTUAL_ENV_DISABLE_PROMPT")', method)


if __name__ == "__main__":
    unittest.main()
