"""Repeated terminal prompts must never erase an answer while typing."""
import ast
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest

_SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
_TREE = ast.parse(_SOURCE.read_text(encoding="utf-8"))
_CLASS = next(x for x in _TREE.body if isinstance(x, ast.ClassDef)
              and x.name == "ShellDeckTerminalWidget")


def _method(name):
    func = next(x for x in _CLASS.body if isinstance(x, ast.FunctionDef) and x.name == name)
    scope = {}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), str(_SOURCE), "exec"), scope)
    return scope[name]


class _Entry:
    def __init__(self):
        self.value = ""
        self.cleared = 0
        self.placeholder = ""

    def clear(self):
        self.cleared += 1
        self.value = ""

    def setPlaceholderText(self, value):
        self.placeholder = value


class _Button:
    def __init__(self):
        self.label = ""
        self.enabled = False
        self.changes = 0

    def setText(self, value):
        self.label = value
        self.changes += 1

    def setEnabled(self, value):
        self.enabled = value


class PromptRepeatGuardTests(unittest.TestCase):
    def _tab(self):
        status = []
        updates = []
        tab = SimpleNamespace(client_mode_active=False, password_prompt_active=False,
                              interaction_prompt_active=False, _interaction_prompt_text="",
                              input_line=_Entry(), execute_button=_Button(),
                              window=SimpleNamespace(show_status=status.append),
                              compact_interactive_prompt_text=lambda value: value.strip(),
                              update_input_prompt_label=lambda: updates.append(True))
        tab.activate_interaction_prompt_mode = MethodType(_method("activate_interaction_prompt_mode"), tab)
        return tab, status, updates

    def test_initial_prompt_enters_reply_mode(self):
        tab, status, updates = self._tab()
        self.assertTrue(tab.activate_interaction_prompt_mode("  Antworten? "))
        self.assertEqual(tab.input_line.cleared, 1)
        self.assertTrue(tab.interaction_prompt_active)
        self.assertEqual(tab.execute_button.label, "Antwort senden")
        self.assertEqual(len(status), 1)
        self.assertEqual(len(updates), 1)

    def test_identical_repeated_prompt_preserves_typed_answer(self):
        tab, status, updates = self._tab()
        tab.activate_interaction_prompt_mode("(L)esen / (W)iederherstellen:")
        tab.input_line.value = "W"
        tab.activate_interaction_prompt_mode("(L)esen / (W)iederherstellen:")
        self.assertEqual(tab.input_line.value, "W")
        self.assertEqual(tab.input_line.cleared, 1)
        self.assertEqual(tab.execute_button.changes, 1)
        self.assertEqual(len(status), 1)
        self.assertEqual(len(updates), 1)

    def test_changed_prompt_does_not_erase_answer(self):
        tab, status, updates = self._tab()
        tab.activate_interaction_prompt_mode("Alte Frage?")
        tab.input_line.value = "ja"
        tab.activate_interaction_prompt_mode("Neue Frage?")
        self.assertEqual(tab.input_line.value, "ja")
        self.assertEqual(tab._interaction_prompt_text, "Neue Frage?")
        self.assertEqual(tab.input_line.cleared, 1)
        self.assertEqual(len(status), 1)
        self.assertEqual(len(updates), 2)

    def test_active_client_or_password_not_overridden(self):
        tab, _, _ = self._tab()
        tab.password_prompt_active = True
        self.assertFalse(tab.activate_interaction_prompt_mode("Frage?"))
        self.assertFalse(tab.interaction_prompt_active)
        tab.password_prompt_active = False
        tab.client_mode_active = True
        self.assertFalse(tab.activate_interaction_prompt_mode("Frage?"))
        self.assertEqual(tab.input_line.cleared, 0)


if __name__ == "__main__":
    unittest.main()
