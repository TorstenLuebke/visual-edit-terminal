"""Regression: gespeicherte Textauswahl und Cursor-Steuerklassendiagnose."""
import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
    from shelldeck_terminal_grid import TerminalGridView
    from shelldeck_vt_screen import VtScreen
except ImportError:
    QApplication = TerminalGridView = VtScreen = None


@unittest.skipIf(QApplication is None, "PySide6 oder pyte nicht vorhanden")
class SelectionRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_control_summary_does_not_record_text(self):
        result = TerminalGridView._control_sequence_summary(b"secret\x1b[1;4Hpayload\r\n")
        self.assertIn("CSI:H", result)
        self.assertNotIn("secret", result)
        self.assertNotIn("payload", result)

    def test_row_identity_survives_same_viewport(self):
        model = VtScreen(rows=4, cols=30)
        model.feed("alpha\r\nbeta")
        view = TerminalGridView(rows=4, cols=30)
        view._model.feed("alpha\r\nbeta")
        self.assertEqual(view._selection_row_id(0), id(view._model.screen.buffer[0]))
        view._sel_anchor = (0, 0)
        view._sel_head = (0, 4)
        view._sel_anchor_row_id = view._selection_row_id(0)
        view._sel_head_row_id = view._sel_anchor_row_id
        view._selection_frozen_text = view.selected_text()
        self.assertEqual(view.selected_text(), "alpha")
        view._model.feed("\r\nmore\r\nnext\r\nand another")
        self.assertEqual(view.selected_text(), "alpha")

if __name__ == "__main__":
    unittest.main()
