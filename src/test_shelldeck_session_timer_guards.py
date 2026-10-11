"""Tests gegen verspätete Shell-Timer und Datenübernahme zwischen Tabs."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef)
             and n.name == "ShellDeckTerminalWidget")


def method(name, qtimer=None):
    func = next(n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name == name)
    scope = {"QTimer": qtimer}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])), str(SOURCE), "exec"), scope)
    return scope[name]


class TimerQueue:
    def __init__(self):
        self.pending = []

    def singleShot(self, delay, callback):
        self.pending.append((delay, callback))


class TimerIsolationTests(unittest.TestCase):
    def make_tab(self, timer):
        current = object()
        tab = SimpleNamespace(process=current, _shell_generation=7, _terminal_cleaned_up=False)
        tab._schedule_shell_callback = lambda ms, fn: method('_schedule_shell_callback', timer)(tab, ms, fn)
        return tab

    def test_callback_runs_in_same_generation(self):
        timer = TimerQueue()
        tab = self.make_tab(timer)
        called = []
        tab._schedule_shell_callback(300, lambda: called.append(True))
        self.assertEqual(timer.pending[0][0], 300)
        timer.pending[0][1]()
        self.assertEqual(called, [True])

    def test_callback_ignored_after_restart_same_process(self):
        timer = TimerQueue()
        tab = self.make_tab(timer)
        called = []
        tab._schedule_shell_callback(300, lambda: called.append(True))
        tab._shell_generation += 1
        timer.pending[0][1]()
        self.assertEqual(called, [])

    def test_callback_ignored_after_engine_change(self):
        timer = TimerQueue()
        tab = self.make_tab(timer)
        called = []
        tab._schedule_shell_callback(300, lambda: called.append(True))
        tab.process = object()
        timer.pending[0][1]()
        self.assertEqual(called, [])

    def test_callback_ignored_after_tab_close(self):
        timer = TimerQueue()
        tab = self.make_tab(timer)
        called = []
        tab._schedule_shell_callback(300, lambda: called.append(True))
        tab._terminal_cleaned_up = True
        timer.pending[0][1]()
        self.assertEqual(called, [])

    def test_two_tabs_do_not_interfere(self):
        timer = TimerQueue()
        first = self.make_tab(timer)
        second = self.make_tab(timer)
        called = []
        first._schedule_shell_callback(10, lambda: called.append("first"))
        second._schedule_shell_callback(10, lambda: called.append("second"))
        first._shell_generation += 1
        for _ms, fn in timer.pending:
            fn()
        self.assertEqual(called, ["second"])

    def test_echo_carry_timer_uses_shell_fence(self):
        timer = TimerQueue()
        tab = self.make_tab(timer)
        tab._pty_echo_carry_generation = 5
        flushed = []
        tab._flush_pty_echo_carry = flushed.append
        method('_schedule_pty_echo_carry_flush')(tab)
        self.assertEqual(timer.pending[0][0], 800)
        tab._shell_generation += 1
        timer.pending[0][1]()
        self.assertEqual(flushed, [])

    def test_reset_discards_old_echo_and_command_flags(self):
        tab = SimpleNamespace(_awaiting_command_completion=True,
                              _last_sent_shell_command="old",
                              _pending_pty_command_echoes=["stale"],
                              _pending_interactive_response_echoes=["secret"],
                              _pty_echo_carry="old echo", _pty_echo_carry_generation=9)
        method('_reset_shell_transient_state')(tab)
        self.assertFalse(tab._awaiting_command_completion)
        self.assertEqual(tab._last_sent_shell_command, "")
        self.assertEqual(tab._pending_pty_command_echoes, [])
        self.assertEqual(tab._pending_interactive_response_echoes, [])
        self.assertEqual(tab._pty_echo_carry, "")
        self.assertEqual(tab._pty_echo_carry_generation, 10)


if __name__ == "__main__":
    unittest.main()
