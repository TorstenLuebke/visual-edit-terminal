"""Patch 293: Wayland log filtering never touches shell output or user rules."""
import ast
from pathlib import Path
import sys

from shelldeck_qt_logging import (
    WAYLAND_TEXTINPUT_WARNING_RULE,
    should_quiet_wayland_textinput,
    configure_wayland_textinput_logging,
)


class _FakeQLoggingCategory:
    calls = []

    @classmethod
    def setFilterRules(cls, value):
        cls.calls.append(value)


def _wayland_env():
    return {"WAYLAND_DISPLAY": "wayland-0", "XDG_SESSION_TYPE": "wayland"}


def test_linux_wayland_target_category_only():
    _FakeQLoggingCategory.calls.clear()
    assert should_quiet_wayland_textinput(environ=_wayland_env(), platform="linux")
    assert configure_wayland_textinput_logging(
        environ=_wayland_env(), platform="linux", category=_FakeQLoggingCategory)
    assert _FakeQLoggingCategory.calls == [
        "qt.qpa.wayland.textinput.warning=false"]
    assert WAYLAND_TEXTINPUT_WARNING_RULE == _FakeQLoggingCategory.calls[0]


def test_does_not_affect_other_os_or_non_wayland_qt():
    for platform in ("win32", "darwin", "linux"):
        env = _wayland_env() if platform != "linux" else {"XDG_SESSION_TYPE": "x11"}
        assert not should_quiet_wayland_textinput(environ=env, platform=platform)
    for qpa in ("xcb", "offscreen", "minimal"):
        env = {**_wayland_env(), "QT_QPA_PLATFORM": qpa}
        assert not should_quiet_wayland_textinput(environ=env, platform="linux")
    assert should_quiet_wayland_textinput(
        environ={"QT_QPA_PLATFORM": "wayland"}, platform="linux")


def test_respects_user_logging_and_diagnostic_requests():
    for key, value in (
        ("QT_LOGGING_RULES", "*.debug=true"),
        ("QT_LOGGING_CONF", "/tmp/qtlogging.ini"),
        ("SHELLDECK_QT_WAYLAND_TEXTINPUT_LOG", "1"),
        ("SHELLDECK_FOCUS_TRACE_PATH", "/tmp/trace.jsonl"),
    ):
        env = {**_wayland_env(), key: value}
        assert not should_quiet_wayland_textinput(environ=env, platform="linux")
        _FakeQLoggingCategory.calls.clear()
        assert not configure_wayland_textinput_logging(
            environ=env, platform="linux", category=_FakeQLoggingCategory)
        assert _FakeQLoggingCategory.calls == []


def test_does_not_export_or_modify_process_environment(monkeypatch):
    for key in ("QT_LOGGING_RULES", "QT_LOGGING_CONF"):
        monkeypatch.delenv(key, raising=False)
    before = dict(__import__("os").environ)
    configure_wayland_textinput_logging(
        environ=_wayland_env(), platform="linux", category=_FakeQLoggingCategory)
    assert dict(__import__("os").environ) == before


def test_filtered_only_before_qapplication():
    source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main_function = next(node for node in tree.body
                         if isinstance(node, ast.FunctionDef) and node.name == "main")
    lines = source.splitlines()
    call_index = next(i for i, line in enumerate(lines)
                      if "    configure_wayland_textinput_logging()" in line)
    app_index = next(i for i, line in enumerate(lines)
                     if "    app = QApplication(sys.argv)" in line)
    assert main_function.lineno - 1 < call_index < app_index
