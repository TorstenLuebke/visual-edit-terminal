"""Tests für das VT-Bildschirmmodell (Qt-frei).

Ausfuehren (aus src): python -m unittest test_shelldeck_vt_screen
"""

import unittest

import shelldeck_vt_screen as vt


@unittest.skipUnless(vt.is_available(), "pyte nicht installiert")
class VtScreenTests(unittest.TestCase):
    def make(self, rows=4, cols=10, enable_history=False):
        return vt.VtScreen(rows=rows, cols=cols, enable_history=enable_history)

    def test_plain_text_and_dimensions(self):
        s = self.make()
        s.feed("hallo")
        self.assertEqual(len(s.display()), 4)
        self.assertTrue(s.display()[0].startswith("hallo"))
        self.assertEqual(s.cols, 10)
        self.assertEqual(s.rows, 4)

    def test_cursor_advances(self):
        s = self.make()
        s.feed("abc")
        self.assertEqual(s.cursor["x"], 3)
        self.assertEqual(s.cursor["y"], 0)

    def test_crlf_moves_to_next_line(self):
        s = self.make()
        s.feed("a\r\nb")
        self.assertEqual(s.cursor["y"], 1)
        self.assertTrue(s.display()[1].startswith("b"))

    def test_ansi_color_sets_fg(self):
        s = self.make()
        s.feed("\x1b[31mR\x1b[0m")
        cells = s.row_cells(0)
        self.assertEqual(cells[0]["char"], "R")
        self.assertEqual(cells[0]["fg"], "red")

    def test_bold_attribute(self):
        s = self.make()
        s.feed("\x1b[1mB\x1b[0m")
        self.assertTrue(s.row_cells(0)[0]["bold"])

    def test_clear_screen(self):
        s = self.make()
        s.feed("voll")
        s.feed("\x1b[2J\x1b[H")
        self.assertEqual(s.display()[0].strip(), "")

    def test_row_cells_length_and_blanks(self):
        s = self.make()
        s.feed("ab")
        cells = s.row_cells(0)
        self.assertEqual(len(cells), 10)          # immer cols Zellen
        self.assertEqual(cells[0]["char"], "a")
        self.assertEqual(cells[5]["char"], " ")   # unberuehrt -> Leerzeichen
        self.assertEqual(cells[5]["fg"], vt.DEFAULT_FG)

    def test_dirty_tracking(self):
        s = self.make()
        s.feed("x")
        self.assertIn(0, s.dirty_lines())
        s.clear_dirty()
        self.assertEqual(s.dirty_lines(), [])
        s.feed("\r\ny")
        self.assertIn(1, s.dirty_lines())

    def test_resize_changes_dimensions(self):
        s = self.make()
        changed = s.resize(6, 20)
        self.assertTrue(changed)
        self.assertEqual(s.rows, 6)
        self.assertEqual(s.cols, 20)
        self.assertEqual(len(s.display()), 6)
        self.assertEqual(len(s.row_cells(0)), 20)
        self.assertFalse(s.resize(6, 20))         # keine Aenderung -> False

    def test_incremental_utf8_split_bytes(self):
        s = self.make()
        # 'ä' == b'\xc3\xa4' – ueber zwei feed()-Aufrufe zerteilt.
        s.feed(b"\xc3")
        s.feed(b"\xa4")
        self.assertEqual(s.row_cells(0)[0]["char"], "ä")

    def test_cursor_hidden(self):
        s = self.make()
        s.feed("\x1b[?25l")
        self.assertTrue(s.cursor["hidden"])
        s.feed("\x1b[?25h")
        self.assertFalse(s.cursor["hidden"])

    def test_history_screen_available(self):
        s = self.make(enable_history=True)
        self.assertTrue(s.has_history())

    def test_application_cursor_keys_mode(self):
        s = self.make()
        self.assertFalse(s.application_cursor_keys())
        s.feed("\x1b[?1h")
        self.assertTrue(s.application_cursor_keys())
        s.feed("\x1b[?1l")
        self.assertFalse(s.application_cursor_keys())

    def test_sgr_mouse_reporting_requires_both_tracking_and_1006(self):
        s = self.make()
        self.assertEqual(s.sgr_mouse_tracking_level(), 0)
        s.feed("\x1b[?1000h")
        self.assertEqual(s.sgr_mouse_tracking_level(), 0)
        s.feed("\x1b[?1006h")
        self.assertEqual(s.sgr_mouse_tracking_level(), 1000)
        s.feed("\x1b[?1002h")
        self.assertEqual(s.sgr_mouse_tracking_level(), 1002)
        s.feed("\x1b[?1003h")
        self.assertEqual(s.sgr_mouse_tracking_level(), 1003)
        s.feed("\x1b[?1003l")
        self.assertEqual(s.sgr_mouse_tracking_level(), 1002)
        s.feed("\x1b[?1006l")
        self.assertEqual(s.sgr_mouse_tracking_level(), 0)

    def test_alternate_screen_preserves_shell_and_has_no_history(self):
        s = self.make(rows=5, cols=30, enable_history=True)
        s.feed("SHELL-PROMPT")
        s.feed("\x1b[?1049h")
        self.assertTrue(s.in_alternate_screen())
        self.assertTrue(s.has_history())  # Main history still exists.
        self.assertNotIn("SHELL-PROMPT", "".join(s.display()))
        s.feed("HTOP")
        self.assertIn("HTOP", s.display()[0])
        self.assertFalse(s.scroll_history("up"))
        self.assertIn("HTOP", s.display()[0])
        s.feed("\x1b[?1049l")
        self.assertFalse(s.in_alternate_screen())
        self.assertIn("SHELL-PROMPT", s.display()[0])
        self.assertNotIn("HTOP", "".join(s.display()))

    def test_alternate_screen_switch_sequences_can_be_split_across_reads(self):
        s = self.make(rows=4, cols=20, enable_history=True)
        s.feed(b"BEFORE")
        s.feed(b"\x1b[?10")
        s.feed(b"49hAFTER")
        self.assertTrue(s.in_alternate_screen())
        self.assertIn("AFTER", s.display()[0])
        s.feed(b"\x1b[?1049")
        s.feed(b"l")
        self.assertFalse(s.in_alternate_screen())
        self.assertTrue(s.display()[0].startswith("BEFORE"))

    def test_alternate_screen_scrolling_region_keeps_header_footer_stable(self):
        """DECSTBM scrolls only the process list, never header/footer."""
        s = self.make(rows=6, cols=24, enable_history=True)
        s.feed("SHELL\x1b[?1049h")
        for row, label in enumerate(
            ("HEADER", "PROCESS-A", "PROCESS-B", "PROCESS-C", "PROCESS-D", "FOOTER"), 1
        ):
            s.feed(f"\x1b[{row};1H{label}")
        # Scroll region from row 2 through 5 inclusive, like a fullscreen TUI.
        s.feed("\x1b[2;5r\x1b[5;1H\x1bD")
        lines = s.display()
        self.assertTrue(lines[0].startswith("HEADER"))
        self.assertTrue(lines[1].startswith("PROCESS-B"))
        self.assertTrue(lines[2].startswith("PROCESS-C"))
        self.assertTrue(lines[3].startswith("PROCESS-D"))
        self.assertEqual(lines[4].strip(), "")
        self.assertTrue(lines[5].startswith("FOOTER"))
        # Reverse-index must move the same region back, not a fixed half.
        s.feed("\x1b[2;1H\x1bM")
        lines = s.display()
        self.assertTrue(lines[0].startswith("HEADER"))
        self.assertEqual(lines[1].strip(), "")
        self.assertTrue(lines[2].startswith("PROCESS-B"))
        self.assertTrue(lines[5].startswith("FOOTER"))
        s.feed("\x1b[?1049l")
        self.assertTrue(s.display()[0].startswith("SHELL"))

    def test_alternate_screen_does_not_change_other_terminal_tabs(self):
        first = self.make(rows=4, cols=20, enable_history=True)
        second = self.make(rows=4, cols=20, enable_history=True)
        second.feed("OTHER")
        first.feed("\x1b[?47h")
        self.assertTrue(first.in_alternate_screen())
        self.assertFalse(second.in_alternate_screen())
        self.assertEqual(second.display()[0].strip(), "OTHER")
        first.feed("\x1b[?47l")
        self.assertFalse(first.in_alternate_screen())

    def test_alternate_scroll_is_opt_in(self):
        s = self.make()
        self.assertFalse(s.alternate_scroll_mode())
        s.feed("\x1b[?1049h")
        self.assertFalse(s.alternate_scroll_mode())
        s.feed("\x1b[?1007h")
        self.assertTrue(s.alternate_scroll_mode())
        s.feed("\x1b[?1007l")
        self.assertFalse(s.alternate_scroll_mode())

    def test_bracketed_paste_mode(self):
        s = self.make()
        self.assertFalse(s.bracketed_paste())
        s.feed("\x1b[?2004h")
        self.assertTrue(s.bracketed_paste())

    def test_bytes_and_str_feed_equivalent(self):
        a = self.make()
        b = self.make()
        a.feed("hi")
        b.feed(b"hi")
        self.assertEqual(a.display(), b.display())


class AvailabilityTests(unittest.TestCase):
    def test_is_available_is_bool(self):
        self.assertIn(vt.is_available(), (True, False))

    def test_message_when_unavailable(self):
        if not vt.is_available():
            self.assertIn("pyte", vt.availability_message())


if __name__ == "__main__":
    unittest.main(verbosity=2)
