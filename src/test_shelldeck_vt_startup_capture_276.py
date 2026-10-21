"""Guard rails for the explicit restart-and-record startup diagnosis."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

import shelldeck_vt_startup_capture_274 as startup
from shelldeck_vt_trace import VtRawTrace


def test_disabled_by_default_and_one_shot_claim(tmp_path, monkeypatch):
    monkeypatch.setattr(startup, "_claimed", False)
    env = {}
    assert startup.claim_startup_trace_directory(env) is None
    env[startup.STARTUP_TRACE_ENV] = str(tmp_path)
    assert startup.claim_startup_trace_directory(env) == tmp_path
    assert startup.STARTUP_TRACE_ENV not in env
    assert startup.claim_startup_trace_directory({startup.STARTUP_TRACE_ENV: str(tmp_path)}) is None


def test_invalid_destination_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(startup, "_claimed", False)
    with pytest.raises(ValueError):
        startup.claim_startup_trace_directory({startup.STARTUP_TRACE_ENV: "relative/path"})
    with pytest.raises(ValueError):
        startup.claim_startup_trace_directory({startup.STARTUP_TRACE_ENV: str(tmp_path / "missing")})
    assert startup._claimed is False


def test_private_directory_and_files(tmp_path):
    download = tmp_path / "Downloads"
    download.mkdir()
    target = startup.create_private_trace_directory(tmp_path)
    assert target.parent == download
    if os.name == "posix":
        assert stat.S_IMODE(target.stat().st_mode) == 0o700
    trace = VtRawTrace(limit=10)
    trace.start()
    trace.event("trace_started", rows=24, cols=80)
    trace.append(b"abcd\r\n")
    trace.event("pty_feed", rows=24, cols=80)
    filename = startup.export_startup_trace(
        target, trace, start_model="before", end_model="after",
        geometry=(24, 80), session_generation=1,
    )
    assert not trace.active
    assert filename.read_bytes() == b"abcd\r\n"
    assert filename.with_suffix(".meta.txt").read_text().count("shell_generation=1") == 1
    assert filename.with_name(filename.stem + "_Startmodell.txt").read_text() == "before"
    assert filename.with_name(filename.stem + "_Endmodell.txt").read_text() == "after"
    events = filename.with_name(filename.stem + "_Ereignisse.jsonl").read_text().splitlines()
    assert json.loads(events[0])["byte_offset"] == 0
    assert json.loads(events[1])["byte_offset"] == 6
    if os.name == "posix":
        assert all(stat.S_IMODE(child.stat().st_mode) == 0o600
                   for child in target.iterdir())


def test_trace_limit_preserves_data_until_stop(tmp_path):
    trace = VtRawTrace(limit=4)
    trace.start()
    trace.append(b"abcdefgh")
    assert not trace.active
    assert trace.truncated
    output = startup.export_startup_trace(tmp_path, trace,
                                          start_model="a", end_model="b", geometry=(4, 5))
    assert output.read_bytes() == b"abcd"
    assert "truncated=True" in output.with_suffix(".meta.txt").read_text()


def test_restart_command_omits_user_start_arguments(tmp_path, monkeypatch):
    script = tmp_path / "main.py"
    script.write_text("pass\n")
    command = startup.relaunch_command([str(script), "--command", "rm -rf /", "other.txt"])
    assert command[1:] == [str(script.resolve())]
    assert "--command" not in command
    with pytest.raises(FileNotFoundError):
        startup.relaunch_command([str(tmp_path / "absent.py")])


def test_restart_uses_only_explicit_flag_and_wait_pid(tmp_path, monkeypatch):
    script = tmp_path / "main.py"
    script.write_text("pass\n")
    seen = {}
    def fake_popen(command, **options):
        seen.update(command=command, **options)
        return object()
    monkeypatch.setattr(startup.subprocess, "Popen", fake_popen)
    startup.launch_diagnostic_restart(tmp_path, [str(script), "--command", "nope"])
    assert seen["env"][startup.STARTUP_TRACE_ENV] == str(tmp_path)
    assert seen["env"][startup.RESTART_PARENT_PID_ENV] == str(os.getpid())
    assert seen["stdin"] == startup.subprocess.DEVNULL
    assert len(seen["command"]) == 2


def test_wait_for_prior_gui_removes_flag_without_waiting_if_no_parent(monkeypatch):
    env = {startup.RESTART_PARENT_PID_ENV: "876543"}
    def fake_kill(_pid, _sig):
        raise ProcessLookupError()
    monkeypatch.setattr(startup.os, "kill", fake_kill)
    startup.wait_for_restarted_parent(env)
    assert startup.RESTART_PARENT_PID_ENV not in env


def test_qt_overlay_and_recording_does_not_resize_terminal(tmp_path, monkeypatch):
    """Exercises the actual Qt view when PySide6 and pyte are available."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    qt = pytest.importorskip("PySide6.QtWidgets")
    import shelldeck_vt_screen as vt
    if not vt.is_available():
        pytest.skip("pyte not installed")
    from shelldeck_terminal_grid import TerminalGridView
    monkeypatch.setattr(startup, "_claimed", False)
    monkeypatch.setenv(startup.STARTUP_TRACE_ENV, str(tmp_path))
    app = qt.QApplication.instance() or qt.QApplication([])
    grid = TerminalGridView(rows=24, cols=80)
    try:
        before = (grid.model().rows, grid.model().cols)
        assert grid._vt_raw_trace.active
        assert grid._trace_badge.isVisibleTo(grid)
        assert grid._trace_button.text() == "■ Stopp"
        grid.feed(b"first output")
        assert (grid.model().rows, grid.model().cols) == before
        with patch.object(qt.QMessageBox, "information"):
            grid._trace_button.click()
        assert not grid._vt_raw_trace.active
        assert grid._vt_trace_start_snapshot is None
        assert not grid._trace_badge.isVisibleTo(grid)
        assert list(tmp_path.glob("*.bin"))
    finally:
        grid.close()
