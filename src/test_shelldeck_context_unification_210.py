"""Regression: VT transcript is non-mutating and retains chronological scrollback."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from shelldeck_vt_screen import VtScreen, is_available


@unittest.skipUnless(is_available(), "pyte nicht installiert")
class ContextTranscriptTests(unittest.TestCase):
    def test_retained_history_and_viewport(self):
        model = VtScreen(rows=3, cols=20, history=100)
        model.feed("eins\r\nzwei\r\ndrei\r\nvier")
        before = model.display()
        text = model.transcript_text()
        self.assertIn("eins", text)
        self.assertIn("vier", text)
        self.assertLess(text.index("eins"), text.index("vier"))
        self.assertEqual(before, model.display())

    def test_alternate_screen_does_not_leak(self):
        model = VtScreen(rows=3, cols=25)
        model.feed("NORMAL")
        model.feed("\x1b[?1049hGEHEIM")
        self.assertNotIn("GEHEIM", model.transcript_text())
        self.assertIn("NORMAL", model.transcript_text())
        model.feed("\x1b[?1049l")
        self.assertIn("NORMAL", model.transcript_text())

    def test_snapshot_is_bounded_and_read_only(self):
        model = VtScreen(rows=3, cols=10, history=20)
        model.feed("".join(f"{i:04}\r\n" for i in range(500)))
        before = model.display()
        first = model.transcript_text()
        self.assertEqual(first, model.transcript_text())
        self.assertEqual(before, model.display())
        # Der VT-Scrollback wird auf mindestens 100 Zeilen normalisiert.
        # Dazu kommen die sichtbaren Bildschirmzeilen; 20 ist kein gueltiger
        # Grenzwert. Genuegend Eingabe erzeugen, um die Grenze zu erreichen.
        self.assertEqual(model.history_lines, 100)
        self.assertLessEqual(len(first.splitlines()), model.history_lines + model.rows)
        self.assertNotIn("0000", first)
        self.assertIn("0499", first)


if __name__ == "__main__":
    unittest.main()
