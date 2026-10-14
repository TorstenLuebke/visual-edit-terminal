"""Alternate-buffer dispatch tests that require neither Qt nor pyte."""

import unittest

from shelldeck_vt_screen import _ScreenBuffers


class FakeScreen:
    def __init__(self):
        self.lines = 3
        self.mode = set()
        self.dirty = set()
        self.text = []
        self.reset_calls = 0
        self.history = object()

    def reset(self):
        self.reset_calls += 1
        self.text.clear()
        self.mode.clear()
        self.dirty.update(range(self.lines))

    def draw(self, text):
        self.text.append(text)

    def set_mode(self, *modes, private=False):
        self.mode.update({x << 5 if private else x for x in modes})

    def reset_mode(self, *modes, private=False):
        self.mode.difference_update({x << 5 if private else x for x in modes})

    def resize(self, rows, cols):
        self.lines = rows


class RouterTests(unittest.TestCase):
    def test_prebound_draw_follows_alternate_screen(self):
        main, alt = FakeScreen(), FakeScreen()
        router = _ScreenBuffers(main, alt)
        draw = router.draw  # Like pyte.Stream, binds event once.
        draw("MAIN")
        router.set_mode(1049, private=True)
        self.assertTrue(router.alternate_active)
        draw("HTOP")
        self.assertEqual(main.text, ["MAIN"])
        self.assertEqual(alt.text, ["HTOP"])
        router.reset_mode(1049, private=True)
        self.assertFalse(router.alternate_active)
        draw("SHELL")
        self.assertEqual(main.text, ["MAIN", "SHELL"])
        self.assertEqual(main.dirty, {0, 1, 2})

    def test_non_alternate_modes_only_change_current_screen(self):
        main, alt = FakeScreen(), FakeScreen()
        router = _ScreenBuffers(main, alt)
        router.set_mode(1049, private=True)
        router.set_mode(1006, private=True)
        self.assertIn(1006 << 5, alt.mode)
        self.assertNotIn(1006 << 5, main.mode)
        router.reset_mode(1049, private=True)
        self.assertNotIn(1006 << 5, router.mode)

    def test_hiding_and_resizing_changes_both_screen_sizes(self):
        main, alt = FakeScreen(), FakeScreen()
        router = _ScreenBuffers(main, alt)
        router.set_mode(1049, private=True)
        router.resize(8, 100)
        self.assertEqual(main.lines, 8)
        self.assertEqual(alt.lines, 8)
        router.reset_mode(1049, private=True)
        self.assertEqual(router.dirty, set(range(8)))


if __name__ == "__main__":
    unittest.main()
