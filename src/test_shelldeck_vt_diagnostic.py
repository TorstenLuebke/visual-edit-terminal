"""Opt-in diagnostics must inspect the model without modifying it."""
import unittest
from unittest.mock import Mock

from shelldeck_vt_diagnostic import model_snapshot


class VtDiagnosticTests(unittest.TestCase):
    def test_snapshot_preserves_columns_and_blank_cells(self):
        model = Mock()
        model.rows = 2
        model.cols = 5
        model.cursor = {"x": 3, "y": 1, "hidden": False}
        model.in_alternate_screen.return_value = True
        model.row_cells.side_effect = lambda row: [
            {"char": char} for char in ("ab   " if row == 0 else "xy  z")
        ]
        output = model_snapshot(model)
        self.assertIn("rows=2 cols=5 alternate=True", output)
        self.assertIn("0000|ab   |", output)
        self.assertIn("0001|xy  z|", output)
        self.assertEqual(model.row_cells.call_count, 2)

    def test_empty_cell_representation(self):
        model = Mock(rows=1, cols=2, cursor={"x": 0, "y": 0, "hidden": True})
        model.in_alternate_screen.return_value = False
        model.row_cells.return_value = [{"char": ""}, {"char": "X"}]
        self.assertIn("0000| X|", model_snapshot(model))
