"""Patch 282: reproduce the START geometry storm seen in VT startup capture.

Unit tests intentionally need neither Qt nor pyte. The real GUI remains a
necessary acceptance test; this only verifies the launcher/control contract.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest

SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
HOST = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
            and node.name == "ShellDeckTerminalWidget")


def method(name):
    node = next(node for node in HOST.body if isinstance(node, ast.FunctionDef)
                and node.name == name)
    scope = {"os": os}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(SOURCE), "exec"), scope)
    return scope[name]


class Timer:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


class FirstPtyStartLayout282(unittest.TestCase):
    def make_tab(self, *, posix_pty=True):
        events = []
        size = [2, 12]
        startup = Timer()
        deadline = Timer()
        process = SimpleNamespace(_running=False, set_window_size=lambda *xy: events.append(("resize", xy)))
        window = SimpleNamespace(default_command="printf '__INIT__'")
        tab = SimpleNamespace(
            window=window, process=process,
            real_terminal_active=posix_pty,
            _initial_pty_shell_pending=False,
            _initial_pty_size_fallback=None,
            _initial_pty_hold_small_grid=False,
            _initial_pty_start_timer=startup,
            _initial_pty_timeout_timer=deadline,
            _terminal_cleaned_up=False,
            _terminal_grid_size=lambda: tuple(size),
            process_uses_pty_engine=lambda: posix_pty,
            _vt_trace_event=lambda *a, **kw: events.append(("trace", a, kw)),
            run_startup_command=lambda cmd: events.append(("startup_command", cmd)),
        )

        def spawn():
            events.append(("spawn", tuple(size), tab._initial_pty_size_fallback))
            process._running = True

        def waiting(_milliseconds):
            return process._running

        tab.start_shell = spawn
        process.waitForStarted = waiting
        for name in (
            "_start_first_shell_after_layout", "_schedule_initial_pty_start",
            "_launch_initial_pty_shell", "_finish_initial_pty_shell_start",
            "_force_initial_pty_shell_start", "_on_terminal_grid_size",
        ):
            setattr(tab, name, MethodType(method(name), tab))
        tab._usable_initial_pty_geometry = method("_usable_initial_pty_geometry")
        return tab, size, events, startup, deadline

    def test_real_start_capture_geometry_storm_does_not_spawn_early(self):
        tab, size, events, timer, deadline = self.make_tab()
        tab._start_first_shell_after_layout()
        self.assertTrue(tab._initial_pty_shell_pending)
        # Observed size changes: 2x12 -> 1x10 -> 28x32 -> 58x235.
        for rows, cols in ((2, 12), (1, 10), (28, 32)):
            size[:] = rows, cols
            tab._on_terminal_grid_size(rows, cols)
            self.assertFalse([x for x in events if x[0] == "spawn"])
        self.assertEqual(timer.starts, 0)
        size[:] = 58, 235
        tab._on_terminal_grid_size(*size)
        self.assertEqual(timer.starts, 1)
        # 180ms without a further size change: start exactly once.
        tab._finish_initial_pty_shell_start()
        self.assertEqual([x for x in events if x[0] == "spawn"],
                         [("spawn", (58, 235), None)])
        self.assertEqual([x for x in events if x[0] == "startup_command"],
                         [("startup_command", "printf '__INIT__'")])
        tab._force_initial_pty_shell_start()
        self.assertEqual(len([x for x in events if x[0] == "spawn"]), 1)
        self.assertGreaterEqual(deadline.stops, 1)

    def test_late_small_change_resets_quiet_period(self):
        tab, size, events, timer, _ = self.make_tab()
        tab._start_first_shell_after_layout()
        size[:] = 28, 120
        tab._on_terminal_grid_size(*size)
        size[:] = 1, 10
        tab._on_terminal_grid_size(*size)
        self.assertGreaterEqual(timer.stops, 1)
        tab._finish_initial_pty_shell_start()
        self.assertEqual(events, [])

    def test_hidden_tab_fallback_keeps_safe_start_size(self):
        tab, size, events, _, _ = self.make_tab()
        tab._start_first_shell_after_layout()
        tab._force_initial_pty_shell_start()
        self.assertEqual([x for x in events if x[0] == "spawn"],
                         [("spawn", (2, 12), (24, 80))])
        self.assertTrue(tab._initial_pty_hold_small_grid)
        # Hidden tabs may not send an undersized resize after timeout.
        tab._on_terminal_grid_size(1, 10)
        self.assertFalse([x for x in events if x[0] == "resize"])
        size[:] = 58, 235
        tab._on_terminal_grid_size(*size)
        self.assertFalse(tab._initial_pty_hold_small_grid)
        self.assertEqual([x for x in events if x[0] == "resize"],
                         [("resize", (58, 235))])

    def test_non_vt_qprocess_stays_synchronous(self):
        tab, _size, events, timer, _ = self.make_tab(posix_pty=False)
        tab._start_first_shell_after_layout()
        self.assertEqual([x[0] for x in events], ["spawn"])
        self.assertEqual(timer.starts, 0)

    def test_pre_spawn_resize_must_not_fake_success(self):
        tab, _, events, _, _ = self.make_tab()
        tab._on_terminal_grid_size(1, 10)
        self.assertEqual(events, [])

    def test_real_resize_failure_does_not_cache_wrong_geometry(self):
        tab, _, events, _, _ = self.make_tab()
        tab.process._running = True
        tab.process.set_window_size = lambda *_: False
        tab._on_terminal_grid_size(58, 235)
        self.assertFalse(getattr(tab, "_last_pty_size", None))
        self.assertEqual(events[-1][2]["success"], False)

    def test_deferred_shell_not_spawned_after_cleanup(self):
        tab, size, events, _, _ = self.make_tab()
        tab._start_first_shell_after_layout()
        tab._terminal_cleaned_up = True
        size[:] = 58, 235
        tab._on_terminal_grid_size(*size)
        tab._finish_initial_pty_shell_start()
        self.assertFalse([x for x in events if x[0] == "spawn"])


if __name__ == "__main__":
    unittest.main()
