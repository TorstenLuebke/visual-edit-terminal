"""Regression: live theme roles leave VT feed and other ANSI colors unchanged."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from shelldeck_prompt import (
    PROMPT_ROLE_RGB, ENVIRONMENT_ROLE_RGB, bash_prompt_script, rgb_ansi,
)


class PromptRoleTests(unittest.TestCase):
    def test_role_codes_are_constant_across_theme_changes(self):
        a = bash_prompt_script({"prompt": "#86EFAC", "environment": "#67E8F9"})
        b = bash_prompt_script({"prompt": "#E5A50A", "environment": "#FF0000"})
        self.assertEqual(a, b)
        self.assertIn(rgb_ansi(PROMPT_ROLE_RGB), a)
        self.assertIn(rgb_ansi(ENVIRONMENT_ROLE_RGB), a)

    def test_role_colors_resolve_live_without_touching_model(self):
        try:
            from PySide6.QtWidgets import QApplication
            from PySide6.QtGui import QColor
            from shelldeck_terminal_grid import TerminalGridView
        except ImportError as exc:
            self.skipTest(str(exc))
        application = QApplication.instance() or QApplication([])
        grid = TerminalGridView()
        try:
            before = grid._resolve_color(PROMPT_ROLE_RGB[1:], QColor('#ffffff')).name()
            grid.set_prompt_role_colors({'prompt': '#E5A50A', 'environment': '#67E8F9'})
            after = grid._resolve_color(PROMPT_ROLE_RGB[1:], QColor('#ffffff')).name()
            env = grid._resolve_color(ENVIRONMENT_ROLE_RGB[1:], QColor('#ffffff')).name()
            external = grid._resolve_color('ff0000', QColor('#ffffff')).name()
            self.assertNotEqual(before, after)
            self.assertEqual(after, '#e5a50a')
            self.assertEqual(env, '#67e8f9')
            self.assertEqual(external, '#ff0000')
        finally:
            grid.close()
        self.assertIsNotNone(application)


if __name__ == '__main__':
    unittest.main()
