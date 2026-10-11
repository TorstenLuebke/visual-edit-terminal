"""Resize storms must not flood PTY with resize signals on the GUI thread."""
import ast
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest

_SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
_TREE = ast.parse(_SOURCE.read_text(encoding="utf-8"))
_CLASS = next(x for x in _TREE.body if isinstance(x, ast.ClassDef)
              and x.name == "ShellDeckTerminalWidget")


class _Timer:
    def __init__(self):
        self.running = False
        self.starts = 0

    def start(self):
        self.running = True
        self.starts += 1


class _ImmediateTimer:
    @staticmethod
    def singleShot(delay, callback):
        if delay == 0:
            callback()


def _method(name):
    func = next(x for x in _CLASS.body if isinstance(x, ast.FunctionDef) and x.name == name)
    scope = {"QTimer": _ImmediateTimer}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), str(_SOURCE), "exec"), scope)
    return scope[name]


class ResizeDebounceTests(unittest.TestCase):
    def _tab(self):
        events = []
        tab = SimpleNamespace(_terminal_cleaned_up=False, _terminal_resize_timer=_Timer(),
                              _last_pty_size=None, real_terminal_active=False,
                              process=SimpleNamespace(set_window_size=lambda r, c: events.append((r, c))))
        tab._terminal_grid_size = lambda: (24, 80)
        tab._schedule_terminal_size_update = MethodType(_method("_schedule_terminal_size_update"), tab)
        tab.update_terminal_size = MethodType(_method("update_terminal_size"), tab)
        return tab, events

    def test_rapid_resize_events_only_schedule_timer(self):
        tab, events = self._tab()
        for _ in range(100):
            tab._schedule_terminal_size_update()
        self.assertEqual(events, [])
        self.assertEqual(tab._terminal_resize_timer.starts, 100)
        # Single-shot timer fires after resizing settles, with final dimensions.
        tab._terminal_grid_size = lambda: (29, 115)
        tab.update_terminal_size()
        self.assertEqual(events, [(29, 115)])

    def test_after_close_does_not_reschedule(self):
        tab, _events = self._tab()
        tab._terminal_cleaned_up = True
        tab._schedule_terminal_size_update()
        self.assertEqual(tab._terminal_resize_timer.starts, 0)

    def test_duplicate_pty_size_is_still_ignored(self):
        tab, events = self._tab()
        tab.update_terminal_size()
        tab.update_terminal_size()
        self.assertEqual(events, [(24, 80)])

    def test_compatibility_when_timer_not_installed(self):
        tab, events = self._tab()
        tab._terminal_resize_timer = None
        tab._schedule_terminal_size_update()
        self.assertEqual(events, [(24, 80)])


if __name__ == "__main__":
    unittest.main()
