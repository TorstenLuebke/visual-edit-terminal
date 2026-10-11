"""Persistente Scrollback-Grenzen, auch ohne installierte Qt-Bibliothek."""

import ast
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from shelldeck_scrollback import (
    DEFAULT_SCROLLBACK_BLOCKS, MIN_SCROLLBACK_BLOCKS,
    MAX_SCROLLBACK_BLOCKS, normalize_scrollback_blocks,
)


class ScrollbackSettingsTests(unittest.TestCase):
    def test_invalid_and_out_of_range_settings_are_bounded(self):
        self.assertEqual(normalize_scrollback_blocks(None), DEFAULT_SCROLLBACK_BLOCKS)
        self.assertEqual(normalize_scrollback_blocks("Fehler"), DEFAULT_SCROLLBACK_BLOCKS)
        self.assertEqual(normalize_scrollback_blocks(-1), MIN_SCROLLBACK_BLOCKS)
        self.assertEqual(normalize_scrollback_blocks(1_000_000), MAX_SCROLLBACK_BLOCKS)
        self.assertEqual(normalize_scrollback_blocks("7000"), 7000)

    def test_dialog_updates_all_tabs_and_saves_only_when_confirmed(self):
        tree = ast.parse(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TerminalWindow")
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "show_scrollback_dialog")
        code = compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), "main.py", "exec")
        context = {
            "normalize_scrollback_blocks": normalize_scrollback_blocks,
            "MIN_SCROLLBACK_BLOCKS": MIN_SCROLLBACK_BLOCKS,
            "MAX_SCROLLBACK_BLOCKS": MAX_SCROLLBACK_BLOCKS,
        }
        class FakeDialog:
            response = (5000, True)
            @staticmethod
            def getInt(*_args):
                return FakeDialog.response
        context["QInputDialog"] = FakeDialog
        exec(code, context)
        a, b = [], []
        fake_tab_a = SimpleNamespace(set_scrollback_blocks=lambda value: a.append(value))
        fake_tab_b = SimpleNamespace(set_scrollback_blocks=lambda value: b.append(value))
        saves = []
        host = SimpleNamespace(
            scrollback_blocks=DEFAULT_SCROLLBACK_BLOCKS,
            all_terminal_tabs=lambda: [(None, 0, fake_tab_a), (None, 1, fake_tab_b)],
            save_settings=lambda: saves.append(True),
        )
        context["show_scrollback_dialog"](host)
        self.assertEqual((a, b, host.scrollback_blocks, saves), ([5000], [5000], 5000, [True]))
        FakeDialog.response = (1000, False)
        context["show_scrollback_dialog"](host)
        self.assertEqual((host.scrollback_blocks, saves), (5000, [True]))


if __name__ == "__main__":
    unittest.main()
