"""Separater, gespeicherter VT-Scrollback ohne GUI-Pflicht."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

from shelldeck_scrollback import (
    DEFAULT_VT_SCROLLBACK_LINES, MAX_VT_SCROLLBACK_LINES,
    MIN_VT_SCROLLBACK_LINES, normalize_vt_scrollback_lines,
)


class VtScrollbackSettingsTests(unittest.TestCase):
    @staticmethod
    def method(name):
        tree = ast.parse(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TerminalWindow")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        return compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                       "main.py", "exec")

    def test_dialog_updates_only_existing_grids_and_persists(self):
        code = self.method("show_vt_scrollback_dialog")
        class FakeDialog:
            response = (550, True)
            @classmethod
            def getInt(cls, *_args):
                return cls.response
        context = {
            "QInputDialog": FakeDialog,
            "normalize_vt_scrollback_lines": normalize_vt_scrollback_lines,
            "MIN_VT_SCROLLBACK_LINES": MIN_VT_SCROLLBACK_LINES,
            "MAX_VT_SCROLLBACK_LINES": MAX_VT_SCROLLBACK_LINES,
        }
        exec(code, context)
        a, b, saved = [], [], []
        tab1 = SimpleNamespace(terminal_grid=SimpleNamespace(set_history_lines=lambda x: a.append(x)))
        tab2 = SimpleNamespace(terminal_grid=None)
        tab3 = SimpleNamespace(terminal_grid=SimpleNamespace(set_history_lines=lambda x: b.append(x)))
        host = SimpleNamespace(
            vt_scrollback_lines=DEFAULT_VT_SCROLLBACK_LINES,
            all_terminal_tabs=lambda: [(None, 0, tab1), (None, 1, tab2), (None, 0, tab3)],
            save_settings=lambda: saved.append(True),
        )
        context["show_vt_scrollback_dialog"](host)
        self.assertEqual((a, b, saved), ([550], [550], [True]))
        self.assertEqual(host.vt_scrollback_lines, 550)
        FakeDialog.response = (1234, False)
        context["show_vt_scrollback_dialog"](host)
        self.assertEqual((a, b, saved, host.vt_scrollback_lines),
                         ([550], [550], [True], 550))

    def test_settings_roundtrip_has_independent_vt_field(self):
        tree = ast.parse(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TerminalWindow")
        source = ast.unparse(cls)
        self.assertIn("vt_scrollback_lines", source)
        self.assertIn("normalize_vt_scrollback_lines", source)
        self.assertIn("show_vt_scrollback_dialog", source)
        self.assertEqual(normalize_vt_scrollback_lines("999999"), MAX_VT_SCROLLBACK_LINES)


if __name__ == "__main__":
    unittest.main()
