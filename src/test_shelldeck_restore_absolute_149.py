"""Restore commands stay anchored to their saved venv, not the new cwd."""
import ast
from pathlib import Path
import types
import unittest

SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py").read_text()
TREE = ast.parse(SOURCE)
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ShellDeckTerminalWidget")


class TestSavedVenvRestore(unittest.TestCase):
    def test_explicit_restore_prefers_known_absolute_venv(self):
        method = next(n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name == "current_restore_command")
        namespace = {}
        exec(compile(ast.Module(body=[method], type_ignores=[]), "<restore-test>", "exec"), namespace)
        tab = types.SimpleNamespace(
            restore_command=". .venv/bin/activate", shell_type="bash", venv_path="/home/test/project/.venv",
            window=types.SimpleNamespace(normalize_restore_command_for_shell=lambda command, shell: command),
            normalize_venv_path=lambda p: p,
            command_looks_like_venv_activation=lambda command: "activate" in command,
            restore_command_for_venv=lambda venv: ". '" + venv + "/bin/activate'",
        )
        result = namespace['current_restore_command'](tab)
        self.assertEqual(result, ". '/home/test/project/.venv/bin/activate'")
        self.assertEqual(tab.restore_command, result)


if __name__ == "__main__": unittest.main()
