"""Regression of generic PTY precommands and portable clear/cls routing."""
import ast
from pathlib import Path
import unittest
from types import MethodType, SimpleNamespace

SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
WIDGET = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ShellDeckTerminalWidget")


def method(name):
    fn = next(n for n in WIDGET.body if isinstance(n, ast.FunctionDef) and n.name == name)
    ns = {"command_targets_shelldeck": lambda x: False}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(SOURCE), "exec"), ns)
    return ns[name]


class PrecommandTests(unittest.TestCase):
    def make_tab(self, shell="bash", engine="pty"):
        tab = SimpleNamespace(shell_type=shell)
        tab.process_uses_pty_engine = lambda: engine == "pty"
        tab.translate_cross_platform_command = lambda x: "clear" if x.lower() == "cls" and shell != "cmd" else x
        tab.parse_ollama_run_model = lambda x: None
        tab.parse_direct_client_command = lambda x: None
        return tab

    def test_prefix_and_user_are_one_ordered_shell_statement(self):
        tab = self.make_tab()
        tab.compose_pty_command_sequence = MethodType(method("compose_pty_command_sequence"), tab)
        import builtins
        # command_targets_shelldeck is a global of the real method.
        method("compose_pty_command_sequence").__globals__["command_targets_shelldeck"] = lambda x: False
        tab.compose_pty_command_sequence = MethodType(method("compose_pty_command_sequence"), tab)
        self.assertEqual(tab.compose_pty_command_sequence([
            ("cd /tmp", False), ("export X=1", False), ("printf %s $X", True)
        ]), "cd /tmp ; export X=1 ; printf %s $X")
        self.assertEqual(tab.compose_pty_command_sequence([("cls", False), ("pwd", True)]), "clear ; pwd")

    def test_cmd_separator_and_no_qprocess_combination(self):
        func = method("compose_pty_command_sequence")
        func.__globals__["command_targets_shelldeck"] = lambda x: False
        tab = self.make_tab("cmd")
        self.assertEqual(func(tab, [("echo first", False), ("echo second", True)]), "echo first & echo second")
        tab = self.make_tab(engine="qprocess")
        self.assertIsNone(func(tab, [("echo first", False), ("echo second", True)]))

    def test_multiline_or_shelldeck_commands_do_not_get_combined(self):
        func = method("compose_pty_command_sequence")
        func.__globals__["command_targets_shelldeck"] = lambda x: x == "shelldeck"
        tab = self.make_tab()
        self.assertIsNone(func(tab, [("echo first\necho second", False), ("ls", True)]))
        self.assertIsNone(func(tab, [("shelldeck", False), ("ls", True)]))

    def test_clear_dispatch_is_backend_sensitive(self):
        code = ast.get_source_segment(SOURCE.read_text(encoding="utf-8"),
                 next(n for n in WIDGET.body if isinstance(n, ast.FunctionDef) and n.name == "execute_command"))
        self.assertIn('command.lower() in ("cls", "clear") and not self.process_uses_pty_engine()', code)


if __name__ == "__main__":
    unittest.main()
