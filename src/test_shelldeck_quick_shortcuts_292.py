"""Patch 292: System-/Doppelbelegungsprüfung ohne Qt- und OS-Abhängigkeit."""
from shelldeck_quick_shortcuts import (
    shortcut_identity, parse_gnome_bindings, system_shortcut_conflict,
)
from shelldeck_quick_commands import normalized_settings


def test_equivalent_order_and_aliases_are_identical():
    assert shortcut_identity("Alt+Ctrl+1") == shortcut_identity("Ctrl+Alt+1")
    assert shortcut_identity("Win+Shift+F9") == "SHIFT+META+F9"
    assert shortcut_identity("Ctrl+Shift+Delete") == "CTRL+SHIFT+DELETE"
    assert shortcut_identity("") == ""
    assert shortcut_identity("Ctrl+InvalidModifier+F1") == ""


def test_global_conflicts_windows_linux_macos():
    assert system_shortcut_conflict("Alt+Tab", platform="win32")
    assert system_shortcut_conflict("Meta+D", platform="win32")
    assert system_shortcut_conflict("Alt+F4", platform="win32")
    assert system_shortcut_conflict("Ctrl+Alt+T", platform="linux", gn_bindings=set())
    assert system_shortcut_conflict("Meta+Space", platform="darwin")
    assert system_shortcut_conflict("Ctrl+Alt+7", platform="win32") == ""


def test_gnome_bindings_detected():
    output = """org.gnome.desktop.wm.keybindings switch-windows ['<Alt>Tab']
org.gnome.desktop.wm.keybindings switch-to-workspace-1 ['<Primary><Alt>1']
org.gnome.settings-daemon.plugins.media-keys screenshot ['<Shift><Super>s']
"""
    parsed = parse_gnome_bindings(output)
    assert "ALT+TAB" in parsed
    assert "CTRL+ALT+1" in parsed
    assert "SHIFT+META+S" in parsed
    assert system_shortcut_conflict("Alt+Ctrl+1", platform="linux", gn_bindings=parsed)
    assert system_shortcut_conflict("Ctrl+Alt+8", platform="linux", gn_bindings=parsed) == ""


def test_security_prompt_is_enabled_by_default_and_persists():
    data = normalized_settings({"commands": []})
    assert data["vt_warning_enabled"] is True
    data = normalized_settings({**data, "vt_warning_enabled": False})
    assert data["vt_warning_enabled"] is False
