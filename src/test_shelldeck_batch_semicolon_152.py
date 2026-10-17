"""QProcess Batch sends compound input without splitting at semicolons."""
import ast
import subprocess
import unittest
from pathlib import Path

from shelldeck_qprocess_bash_batch import wrap_batch_command


class BatchSemicolonTests(unittest.TestCase):
    def test_gui_keeps_user_input_intact_for_batch(self):
        path = Path(__file__).with_name("shelldeck_terminal_widget.py")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        method = next(fn for cls in tree.body if isinstance(cls, ast.ClassDef)
                      for fn in cls.body if isinstance(fn, ast.FunctionDef)
                      and fn.name == "execute_command")
        found = False
        for node in ast.walk(method):
            if not isinstance(node, ast.If):
                continue
            if not (isinstance(node.test, ast.Call) and
                    isinstance(node.test.func, ast.Name) and node.test.func.id == "getattr"):
                continue
            if (len(node.test.args) >= 2 and isinstance(node.test.args[1], ast.Constant)
                    and node.test.args[1].value == "_qprocess_bash_batch"):
                found |= any(isinstance(statement, ast.Assign)
                             and any(isinstance(target, ast.Name) and target.id == "user_commands"
                                     for target in statement.targets)
                             and isinstance(statement.value, ast.List)
                             for statement in node.body)
        self.assertTrue(found, "Batch command must not be split before dispatch")

    def test_compound_shell_command_keeps_status(self):
        cmds = ["false", "status=$?; echo $status"]
        script = "".join(wrap_batch_command(cmd, f"{i:032x}")
                         for i, cmd in enumerate(cmds))
        result = subprocess.run(["bash", "--noprofile", "--norc"],
                                input=script, text=True, capture_output=True, timeout=8)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("\x1f1\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
