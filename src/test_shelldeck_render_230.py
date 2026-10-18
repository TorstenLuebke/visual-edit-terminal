"""Regressionen fuer den Auswahl- und Leerzellen-Zeichenpfad (Patches 228/229).

Diese Tests benoetigen weder Qt-Display noch eine laufende Shell. Die
Zeichenpfad-Tests pruefen dessen Struktur, keine CPU-Laufzeitmessungen.
"""

import ast
from pathlib import Path
import unittest

GRID_SOURCE = Path(__file__).with_name('shelldeck_terminal_grid.py')


def _grid_methods():
    module = ast.parse(GRID_SOURCE.read_text(encoding='utf-8-sig'))
    grid = next(node for node in module.body
                if isinstance(node, ast.ClassDef) and node.name == 'TerminalGridView')
    return {node.name: node for node in grid.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _calls(node, name):
    return [call for call in ast.walk(node)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            and call.func.attr == name]


class RenderRegression230(unittest.TestCase):
    def test_selection_bounds_calculated_once_per_paint_frame(self):
        methods = _grid_methods()
        paint = methods['_paint_terminal']
        self.assertEqual(len(_calls(paint, '_normalized_selection')), 1)
        self.assertEqual(len(_calls(methods['_paint_cells_in_row'], '_normalized_selection')), 0)
        self.assertEqual(len(_calls(methods['_paint_cells_in_row'], '_is_selected')), 0)

    def test_cell_selection_helper_preserves_inclusive_boundaries(self):
        methods = _grid_methods()
        helper = methods['_cell_inside_selection']
        # Die isolierte Funktion besitzt keine Qt-Abhaengigkeit.
        helper.decorator_list = []
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[helper], type_ignores=[])),
                     str(GRID_SOURCE), 'exec'), namespace)
        contains = namespace['_cell_inside_selection']
        bounds = ((2, 3), (4, 5))
        for x, y, expected in [(3, 2, True), (2, 2, False), (0, 3, True),
                               (5, 4, True), (6, 4, False), (4, 5, False),
                               (3, 1, False), (2, 5, False)]:
            with self.subTest(x=x, y=y):
                self.assertEqual(contains(x, y, bounds), expected)
        self.assertFalse(contains(3, 2, None))

    def test_blank_fast_path_skips_only_unselected_default_background(self):
        methods = _grid_methods()
        row = methods['_paint_cells_in_row']
        skips = [node for node in ast.walk(row)
                 if isinstance(node, ast.If) and any(isinstance(child, ast.Continue)
                                                     for child in node.body)]
        self.assertTrue(skips, 'Leerzellen-Fast-Path fehlt')
        condition = ast.unparse(skips[0].test)
        for term in ('selected', 'is_cursor_cell', 'cell[\'reverse\']',
                     'cell[\'bg\']', 'cell[\'char\']'):
            self.assertIn(term, condition)


if __name__ == '__main__':
    unittest.main()
