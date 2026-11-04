"""Schnellbefehle: Vorlagen, Plattformwechsel, Persistenz und Einstellungen.

Lauf ohne Qt möglich: PYTHONPATH=src python -m pytest -q src/test_shelldeck_quick_commands.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from shelldeck_quick_commands import (
    make_default_commands, normalized_command, normalized_settings,
    resolved_command, load_quick_commands, save_quick_commands, shell_flavor,
)


def test_ten_default_commands_and_optional_features_off():
    commands = make_default_commands()
    assert len(commands) == 10
    assert len({item["id"] for item in commands}) == 10
    assert all(not entry["confirm"] and not entry["use_precommand"] for entry in commands)


def test_shell_specific_presets_switch_without_mutation():
    commands = make_default_commands()
    path, files, up, home, clear = commands[:5]
    assert resolved_command(path, "bash", "linux") == "pwd"
    assert resolved_command(path, "pwsh", "win32") == "Get-Location"
    assert resolved_command(files, "cmd", "win32") == "dir"
    assert resolved_command(up, "powershell", "win32") == "Set-Location ..; Get-Location"
    assert resolved_command(home, "bash", "darwin").startswith('cd "$HOME"')
    assert resolved_command(clear, "cmd", "win32") == "cls"
    assert resolved_command(clear, "zsh", "darwin") == "clear"
    assert resolved_command(clear, "gitbash", "win32") == "clear"
    assert path["command"] == "pwd"


def test_custom_command_stays_identical_on_all_platforms():
    item = normalized_command({"name": "ZIP", "command": "cd ~/Programme/visual_edit && date"})
    for shell, platform in (("bash", "linux"), ("pwsh", "win32"), ("zsh", "darwin")):
        assert resolved_command(item, shell, platform) == item["command"]


def test_persist_settings_and_preserve_user_deleted_defaults(tmp_path):
    file = tmp_path / "quick_commands.json"
    data = load_quick_commands(file)
    assert len(data["commands"]) == 10
    data["commands"].pop(0)
    data["commands"][0]["confirm"] = True
    data["commands"][0]["use_precommand"] = False
    data["pinned"] = False
    data["compact"] = True
    data["side"] = "right"
    save_quick_commands(file, data)
    restored = load_quick_commands(file)
    assert len(restored["commands"]) == 9
    assert restored["commands"][0]["confirm"] is True
    assert restored["commands"][0]["use_precommand"] is False
    assert (restored["pinned"], restored["compact"], restored["side"]) == (False, True, "right")
    # Ein ShellDeck-Update erzeugt keine zehn Buttons erneut.
    assert load_quick_commands(file) == restored


def test_empty_user_list_and_disjoint_options_survive(tmp_path):
    file = tmp_path / "quick_commands.json"
    data = normalized_settings({"commands": [], "visible": False, "pinned": False})
    save_quick_commands(file, data)
    assert load_quick_commands(file)["commands"] == []
    custom = normalized_command({"name": "Backup", "command": "date", "confirm": False,
                                 "use_precommand": True, "new_tab": True, "shortcut": "Ctrl+Alt+3"})
    assert custom["confirm"] is False
    assert custom["use_precommand"] is True
    assert custom["new_tab"] is True
    assert custom["shortcut"] == "Ctrl+Alt+3"


def test_invalid_or_duplicate_ids_are_normalized_without_removing_entries():
    item = normalized_command({"id": "same", "name": "A", "command": "pwd"})
    data = normalized_settings({"commands": [item, item]})
    assert len(data["commands"]) == 2
    assert data["commands"][0]["id"] != data["commands"][1]["id"]


def test_invalid_saved_json_falls_back_to_defaults(tmp_path):
    file = tmp_path / "quick_commands.json"
    file.write_text("{not json}")
    assert len(load_quick_commands(file)["commands"]) == 10


def test_variant_command_with_spaces_and_shell_meta_is_untouched():
    value = '''cd ~/Programme/visual_edit && mkdir -p ~/Downloads && git ls-files -co --exclude-standard -z | xargs -0 -r zip -q -9 "$HOME/Downloads/VisualEdit_GIT_ZIP_$(date +%Y%m%d-%H%M%S).zip" && git status --short --branch'''
    item = normalized_command({"name": "ZIP", "command": value})
    assert resolved_command(item, "bash", "linux") == value
