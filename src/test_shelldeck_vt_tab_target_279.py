"""Regressions: a restart records the ORIGINAL tab, not first-created grid.

The Qt-independent restore flow is exercised via its real AST to avoid having
PySide6 as a CI prerequisite. The full widget path is also guarded in 276.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

import shelldeck_vt_startup_capture_274 as capture


def test_non_target_grids_cannot_steal_capture(tmp_path, monkeypatch):
    monkeypatch.setattr(capture, "_claimed", False)
    env = {
        capture.STARTUP_TRACE_ENV: str(tmp_path),
        capture.STARTUP_TRACE_TARGET_ENV: "3",
    }
    assert capture.requested_startup_trace_tab_index(env) == 3
    # The first 3 VT grids exist before the original tab is restored.
    for _ in range(3):
        assert capture.claim_startup_trace_directory(env, eligible=False) is None
        assert capture.STARTUP_TRACE_ENV in env
    assert capture.claim_startup_trace_directory(env, eligible=True) == tmp_path
    assert capture.STARTUP_TRACE_ENV not in env
    assert capture.claim_startup_trace_directory({capture.STARTUP_TRACE_ENV: str(tmp_path)}) is None


@pytest.mark.parametrize("value", ["", "-1", "str", "10000", "1.1"])
def test_invalid_tab_index_fails_closed(value):
    assert capture.requested_startup_trace_tab_index({capture.STARTUP_TRACE_TARGET_ENV: value}) is None


def test_restart_preserves_target_index(tmp_path, monkeypatch):
    runner = tmp_path / "main.py"
    runner.write_text("pass\n")
    seen = {}

    def popen(cmd, **kwargs):
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(capture.subprocess, "Popen", popen)
    capture.launch_diagnostic_restart(tmp_path, [str(runner)], target_index=6)
    assert seen["env"][capture.STARTUP_TRACE_TARGET_ENV] == "6"
    with pytest.raises(ValueError):
        capture.launch_diagnostic_restart(tmp_path, [str(runner)], target_index=-1)


def _actual_restore_function():
    """Load the actual restored-tabs method, not a duplicate implementation."""
    source = (Path(__file__).with_name("main.py")).read_text(encoding="utf-8")
    module = ast.parse(source)
    window = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "TerminalWindow")
    method = next(n for n in window.body if isinstance(n, ast.FunctionDef) and n.name == "restore_tabs_from_settings")
    namespace = {"TerminalTab": FakeTab, "QTimer": SimpleNamespace(singleShot=lambda _ms, callback: None),
                 "QMessageBox": SimpleNamespace(warning=lambda *_: None), "os": os}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                 filename="main.py", mode="exec"), namespace)
    return namespace["restore_tabs_from_settings"]


class FakeTab:
    def __init__(self, *, capture_active=False):
        self.terminal_grid = SimpleNamespace(_vt_trace_start_snapshot="started" if capture_active else None)
        self.source_profile_name = ""

    def schedule_restore_command(self, *_):
        pass


class FakeTabPane:
    def __init__(self):
        self.current = None

    def setCurrentIndex(self, index):
        self.current = index


class FakeWindow:
    shell_type = "bash"
    terminal_engine = "pty"
    ai_features_enabled = False

    def __init__(self, n):
        self.saved_tabs = [{"title": f"Tab {index}"} for index in range(n)]
        self.calls = []
        self.tabs = []
        self.pane = FakeTabPane()
        self.active_tab_widget = None

    def normalize_shell_type(self, value):
        return value

    def system_shell(self, value):
        return "/bin/bash"

    def target_widget_for_saved_tab(self, item):
        return self.pane

    def new_tab(self, **kwargs):
        self.calls.append(kwargs)
        tab = FakeTab(capture_active=kwargs.get("startup_capture", False))
        self.tabs.append(tab)
        return tab

    def tab_widget_for_tab(self, tab):
        return (self.pane, self.tabs.index(tab))


def test_actual_restore_routes_capture_to_seventh_tab(tmp_path, monkeypatch):
    monkeypatch.setenv(capture.STARTUP_TRACE_ENV, str(tmp_path))
    monkeypatch.setenv(capture.STARTUP_TRACE_TARGET_ENV, "6")
    window = FakeWindow(7)
    _actual_restore_function()(window)
    assert [call["startup_capture"] for call in window.calls] == [False]*6 + [True]
    assert window.pane.current == 6
    assert window.active_tab_widget is window.pane
    assert capture.STARTUP_TRACE_ENV not in os.environ
    assert capture.STARTUP_TRACE_TARGET_ENV not in os.environ


def test_restore_without_opt_in_keeps_all_tabs_unrecorded(monkeypatch):
    monkeypatch.delenv(capture.STARTUP_TRACE_ENV, raising=False)
    monkeypatch.delenv(capture.STARTUP_TRACE_TARGET_ENV, raising=False)
    window = FakeWindow(4)
    _actual_restore_function()(window)
    assert not any(call["startup_capture"] for call in window.calls)
