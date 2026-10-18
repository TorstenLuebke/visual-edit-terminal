"""Regression for the PTY tab-stop loss after startup geometry changes.

Run: python -m pytest -v src/test_shelldeck_tabstops_236.py
"""
import unittest

from shelldeck_vt_screen import VtScreen, is_available


@unittest.skipUnless(is_available(), "pyte not installed")
class TabStopsResize236(unittest.TestCase):
    def test_ls_root_stays_next_to_other_columns_after_startup_resize(self):
        model = VtScreen(rows=24, cols=80, enable_history=False)
        for rows, cols in ((2, 12), (1, 10), (28, 32), (58, 148)):
            model.resize(rows, cols)
        model.feed(
            b"bin  boot  cdrom  debug\t dev  etc  home\t lib  lib64  lost+found"
            b"\t media\tmnt  opt  proc\troot  run  sbin\t snap  srv  swap.img"
            b"  sys  tmp\tusr  var"
        )
        row = model.display()[0]
        self.assertIn("root", row)
        self.assertLess(row.index("root"), 110)
        self.assertEqual(row[-1], " ")
        self.assertEqual(model.cursor["y"], 0)

    def test_existing_custom_stops_are_preserved_on_growth(self):
        model = VtScreen(rows=4, cols=24, enable_history=False)
        normal = model.screen.normal
        normal.tabstops.discard(8)
        model.resize(4, 48)
        self.assertNotIn(8, normal.tabstops)
        self.assertIn(24, normal.tabstops)
        self.assertIn(32, normal.tabstops)
        self.assertIn(40, normal.tabstops)

    def test_alternate_screen_tab_stops_grow_too(self):
        model = VtScreen(rows=4, cols=10, enable_history=False)
        model.resize(4, 48)
        self.assertIn(40, model.screen.normal.tabstops)
        self.assertIn(40, model.screen.alternate.tabstops)
