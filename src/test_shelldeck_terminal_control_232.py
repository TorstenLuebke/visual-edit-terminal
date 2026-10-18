"""PTY terminal erase and right-edge tests (Qt offscreen)."""
import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    from PySide6.QtWidgets import QApplication
    from shelldeck_terminal_grid import TerminalGridView
    from shelldeck_vt_screen import VtScreen
except ImportError:
    QApplication = TerminalGridView = VtScreen = None

@unittest.skipIf(QApplication is None, "PySide6 oder pyte fehlen")
class TerminalControlRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def make_selection(self):
        view = TerminalGridView(rows=5, cols=30)
        view.feed(b"hello")
        view._sel_anchor = (0, 0)
        view._sel_head = (0, 4)
        view._sel_anchor_row_id = view._selection_row_id(0)
        view._sel_head_row_id = view._sel_anchor_row_id
        view._selection_frozen_text = "hello"
        return view

    def test_clear_screen_drops_highlight_and_frozen_text(self):
        view = self.make_selection()
        view.feed(b"\x1b[2J\x1b[H")
        self.assertFalse(view.has_selection())
        self.assertEqual(view.selected_text(), "")

    def test_split_erase_drops_selection(self):
        view = self.make_selection()
        view.feed(b"\x1b[2")
        self.assertTrue(view.has_selection())
        view.feed(b"J")
        self.assertFalse(view.has_selection())

    def test_line_erase_does_not_drop_selection(self):
        view = self.make_selection()
        view.feed(b"\x1b[K")
        self.assertTrue(view.has_selection())

    def test_reset_drops_selection(self):
        view = self.make_selection()
        view.reset()
        self.assertFalse(view.has_selection())

    def test_last_column_and_wrap_are_model_consistent(self):
        model = VtScreen(rows=4, cols=12)
        model.feed("abcdefghijkl" + "m")
        lines = model.display()
        self.assertEqual(lines[0][:12], "abcdefghijkl")
        self.assertTrue(lines[1].startswith("m"))

    def test_tab_stops_do_not_teleport_past_right_edge(self):
        model = VtScreen(rows=4, cols=24)
        model.feed("a\tb\tc")
        text = model.display()[0]
        self.assertEqual(text[0], "a")
        self.assertEqual(text[8], "b")
        self.assertEqual(text[16], "c")

if __name__ == "__main__":
    unittest.main()
