"""Qt-freie Tests der VT-History-Grenze (keine pyte-Installation noetig)."""

from collections import deque, namedtuple
import unittest

from shelldeck_scrollback import (
    DEFAULT_VT_SCROLLBACK_LINES, MAX_VT_SCROLLBACK_LINES,
    MIN_VT_SCROLLBACK_LINES, normalize_vt_scrollback_lines,
)
from shelldeck_vt_screen import VtScreen

History = namedtuple("History", "top bottom ratio size position")


class FakeScreen:
    def __init__(self, size=2000, position=None):
        self.history = History(deque(maxlen=size // 2), deque(maxlen=size),
                               0.5, size, size if position is None else position)
        self.buffer = {0: "sichtbar"}
        self.cursor = object()
        self.dirty = set()


class VtHistoryLimitTests(unittest.TestCase):
    @staticmethod
    def make(screen):
        model = VtScreen.__new__(VtScreen)
        model._rows = 24
        model._cols = 80
        model._history_limit = 2000
        model.screen = screen
        model.stream = object()
        return model

    def test_limits_clamp_json_values(self):
        self.assertEqual(normalize_vt_scrollback_lines(None), DEFAULT_VT_SCROLLBACK_LINES)
        self.assertEqual(normalize_vt_scrollback_lines("falsch"), DEFAULT_VT_SCROLLBACK_LINES)
        self.assertEqual(normalize_vt_scrollback_lines(-1), MIN_VT_SCROLLBACK_LINES)
        self.assertEqual(normalize_vt_scrollback_lines(999999), MAX_VT_SCROLLBACK_LINES)
        self.assertEqual(normalize_vt_scrollback_lines("750"), 750)

    def test_resize_preserves_screen_cursor_stream_and_last_old_lines(self):
        screen = FakeScreen(size=2000)
        screen.history.top.extend(range(1000))
        before_buffer = screen.buffer
        before_cursor = screen.cursor
        model = self.make(screen)
        before_stream = model.stream
        self.assertTrue(model.set_history_lines(200))
        self.assertEqual(model.history_lines, 200)
        self.assertEqual(list(screen.history.top), list(range(900, 1000)))
        self.assertEqual(screen.history.top.maxlen, 100)
        self.assertEqual(screen.history.bottom.maxlen, 200)
        self.assertEqual(screen.history.position, 200)
        self.assertIs(screen.buffer, before_buffer)
        self.assertIs(screen.cursor, before_cursor)
        self.assertIs(model.stream, before_stream)
        self.assertEqual(screen.dirty, set(range(24)))

    def test_resize_while_scrolled_preserves_nearby_forward_lines(self):
        screen = FakeScreen(size=2000, position=1940)
        screen.history.bottom.extend(range(400))
        model = self.make(screen)
        self.assertTrue(model.set_history_lines(150))
        self.assertEqual(list(screen.history.bottom), list(range(150)))
        self.assertEqual(screen.history.position, 90)
        self.assertTrue(model.set_history_lines(700))
        self.assertEqual(screen.history.position, 640)
        self.assertEqual(list(screen.history.bottom), list(range(150)))

    def test_unavailable_or_non_history_screen_is_unchanged(self):
        class NoHistory: pass
        no_history = NoHistory()
        model = self.make(no_history)
        self.assertFalse(model.set_history_lines(1000))
        self.assertIs(model.screen, no_history)
        old = FakeScreen(size=2000)
        model = self.make(old)
        self.assertFalse(model.set_history_lines(2000))
        self.assertEqual(old.history.size, 2000)


if __name__ == "__main__":
    unittest.main()

# Integration mit echtem pyte, sofern es in der Testumgebung vorhanden ist.
import shelldeck_vt_screen as vt


@unittest.skipUnless(vt.is_available(), "pyte nicht installiert")
class VtHistoryIntegrationTests(unittest.TestCase):
    def test_resize_existing_history_keeps_visible_content(self):
        model = vt.VtScreen(rows=4, cols=20, history=2000)
        for value in range(80):
            model.feed(f"Z{value:03d}\r\n")
        old_screen = model.screen
        old_stream = model.stream
        before = model.display()
        self.assertTrue(model.set_history_lines(100))
        self.assertIs(model.screen, old_screen)
        self.assertIs(model.stream, old_stream)
        self.assertEqual(model.display(), before)
        self.assertEqual(model.screen.history.size, 100)
        self.assertLessEqual(len(model.screen.history.top), 50)
        model.feed("WEITER")
        self.assertTrue(any("WEITER" in line for line in model.display()))
