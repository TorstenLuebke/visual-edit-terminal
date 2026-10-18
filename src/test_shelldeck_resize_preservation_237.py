"""Regression diagnosis: horizontal VT data across shrink/grow.

Run with: QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -v -s \
    src/test_shelldeck_resize_preservation_237.py

These tests intentionally report data loss rather than assuming pyte reflows.
They must not modify the VT implementation or require an active GUI.
"""

from __future__ import annotations

import unittest

from shelldeck_vt_screen import VtScreen, is_available


@unittest.skipUnless(is_available(), "pyte not installed")
class VtResizePreservation237(unittest.TestCase):
    @staticmethod
    def _line(screen: VtScreen, row: int = 0) -> str:
        return screen.display()[row].rstrip()

    def test_shrink_expand_reports_retained_horizontal_tail(self):
        model = VtScreen(rows=8, cols=100, history=200)
        sentence = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" * 2
        model.feed(sentence)
        before = self._line(model)
        self.assertEqual(before, sentence)

        model.resize(8, 28)
        narrow = self._line(model)
        model.resize(8, 100)
        after = self._line(model)
        print(f"resize normal: original={len(before)} narrow={len(narrow)} "
              f"restored={len(after)} lost={len(before) - len(after)}")
        if after != before:
            self.fail("VT resize loses horizontal cells: "
                      f"before={before!r}, after={after!r}")

    def test_alternate_screen_resize_does_not_corrupt_normal_screen(self):
        model = VtScreen(rows=8, cols=100, history=200)
        model.feed("NORMAL SCREEN CONTENT")
        normal_before = self._line(model)
        model.feed("\x1b[?1049h")
        model.feed("ALT CONTENT")
        model.resize(8, 28)
        model.resize(8, 100)
        model.feed("\x1b[?1049l")
        self.assertEqual(self._line(model), normal_before)

    def test_horizontal_tail_is_not_recovered_by_display_only(self):
        model = VtScreen(rows=8, cols=80, history=200)
        model.feed("12345678" * 7)
        expected = self._line(model)
        model.resize(8, 20)
        model.resize(8, 80)
        actual = self._line(model)
        print(f"resize replay: expected={expected!r} actual={actual!r}")
        self.assertEqual(actual, expected, "Shrinking discarded existing VT cells")

    def test_shrink_twice_and_expand_without_output(self):
        model = VtScreen(rows=8, cols=100, history=200)
        model.feed("A" * 72)
        model.resize(8, 48)
        model.resize(8, 20)
        model.resize(8, 48)
        model.resize(8, 100)
        self.assertEqual(self._line(model), "A" * 72)

    def test_new_terminal_output_invalidates_saved_tail(self):
        model = VtScreen(rows=8, cols=80, history=200)
        model.feed("A" * 60)
        model.resize(8, 20)
        model.feed("\rB")
        model.resize(8, 80)
        self.assertFalse(self._line(model).endswith("A" * 40))

    def test_erase_invalidates_saved_tail(self):
        model = VtScreen(rows=8, cols=80, history=200)
        model.feed("X" * 55)
        model.resize(8, 20)
        model.feed("\x1b[2J")
        model.resize(8, 80)
        self.assertNotIn("X", self._line(model))


if __name__ == "__main__":
    unittest.main()
