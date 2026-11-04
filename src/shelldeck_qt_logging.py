"""Quiet a known, repetitive Qt Wayland text-input warning in ShellDeck only.

No process environment changes: PTYs and programs launched from them keep their
normal logging settings. Qt (and the operating system) remain responsible for
all other warnings, including errors and critical messages.
"""

import os
import sys

WAYLAND_TEXTINPUT_WARNING_RULE = "qt.qpa.wayland.textinput.warning=false"


def should_quiet_wayland_textinput(environ=None, platform=None):
    """Select safe default filtering without overriding explicit diagnostics.

    Logging rules supplied by the user always take priority. Do not interfere
    with tests using offscreen Qt, native Windows/macOS, or Qt XCB sessions.
    """
    env = os.environ if environ is None else environ
    system = sys.platform if platform is None else platform
    if not system.startswith("linux"):
        return False

    qt_platform = str(env.get("QT_QPA_PLATFORM", "")).strip().lower()
    if qt_platform and not qt_platform.split(";", 1)[0].startswith("wayland"):
        return False
    if not (qt_platform.startswith("wayland")
            or env.get("WAYLAND_DISPLAY")
            or str(env.get("XDG_SESSION_TYPE", "")).lower() == "wayland"):
        return False

    # Qt permits user-defined rules from either variable to supersede rules
    # installed by QLoggingCategory.setFilterRules(). Do not fight them.
    if "QT_LOGGING_RULES" in env or "QT_LOGGING_CONF" in env:
        return False
    if str(env.get("SHELLDECK_QT_WAYLAND_TEXTINPUT_LOG", "")).strip().lower() in {
            "1", "true", "yes", "on"}:
        return False
    # An explicitly enabled focus trace is an opt-in diagnosis; keep Qt's
    # matching warnings visible so the events can be correlated.
    if str(env.get("SHELLDECK_FOCUS_TRACE_PATH", "")).strip():
        return False
    return True


def configure_wayland_textinput_logging(environ=None, platform=None, category=None):
    """Apply a category-specific warning rule before QApplication is created.

    ``category`` can be supplied by tests without importing PySide6.
    Returns True only if the Qt rule was successfully installed.
    """
    if not should_quiet_wayland_textinput(environ=environ, platform=platform):
        return False
    try:
        if category is None:
            from PySide6.QtCore import QLoggingCategory
            category = QLoggingCategory
        category.setFilterRules(WAYLAND_TEXTINPUT_WARNING_RULE)
    except (ImportError, AttributeError, RuntimeError, TypeError):
        # Log filtering is optional; failure must not prevent GUI startup.
        return False
    return True
