"""Regression: Qt-Painter auch bei einem Render-Fehler beenden.

Verwendet AST-basierte Aufrufe, damit diese Tests ohne Qt laufen koennen.
"""

import ast
from pathlib import Path
import unittest
from types import SimpleNamespace


_SOURCE = Path(__file__).with_name("shelldeck_terminal_grid.py")
_TREE = ast.parse(_SOURCE.read_text(encoding="utf-8"))
_CLASS = next(node for node in _TREE.body if isinstance(node, ast.ClassDef)
              and node.name == "TerminalGridView")


class TerminalPainterLifetimeTests(unittest.TestCase):
    def _run_paint_event(self, renderer):
        method = next(node for node in _CLASS.body
                      if isinstance(node, ast.FunctionDef) and node.name == "paintEvent")

        class Painter:
            def __init__(self, _view):
                self.end_count = 0

            def end(self):
                self.end_count += 1

        painters = []

        def painter_factory(view):
            painter = Painter(view)
            painters.append(painter)
            return painter

        namespace = {"QPainter": painter_factory}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     str(_SOURCE), "exec"), namespace)
        fake_view = SimpleNamespace(_paint_terminal=renderer)
        event = object()
        return namespace["paintEvent"], fake_view, event, painters

    def test_painter_ends_on_success(self):
        rendered = []
        paint, view, event, painters = self._run_paint_event(
            lambda painter, e: rendered.append((painter, e)))
        paint(view, event)
        self.assertEqual(rendered, [(painters[0], event)])
        self.assertEqual(painters[0].end_count, 1)

    def test_painter_ends_when_renderer_raises(self):
        def broken_renderer(_painter, _event):
            raise ValueError("ungueltiger Renderzustand")

        paint, view, event, painters = self._run_paint_event(broken_renderer)
        with self.assertRaisesRegex(ValueError, "ungueltiger Renderzustand"):
            paint(view, event)
        self.assertEqual(painters[0].end_count, 1)


if __name__ == "__main__":
    unittest.main()
