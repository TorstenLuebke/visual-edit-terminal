"""Persistente Schnellbefehle; Datenlogik ohne Qt, plattform- und shellbewusst.

Nur erstmalig werden zehn Vorlagen angelegt. Benutzeränderungen bleiben bei
ShellDeck-Updates erhalten. Die plattformabhängige Vorlage wird erst beim Klick
gegen den Shell-Typ des Ziel-Tabs aufgelöst.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4


# name, POSIX/Linux, macOS, PowerShell, CMD
_PRESETS = (
    ("Pfad", "pwd", "pwd", "Get-Location", "cd"),
    ("Dateien", "ls -lah", "ls -lah", "Get-ChildItem -Force", "dir"),
    ("Zurück", "cd .. && pwd", "cd .. && pwd", "Set-Location ..; Get-Location", "cd .. && cd"),
    ("Home", 'cd "$HOME" && pwd', 'cd "$HOME" && pwd', "Set-Location ~; Get-Location", "cd /d %USERPROFILE% && cd"),
    ("Leeren", "clear", "clear", "Clear-Host", "cls"),
    ("Verlauf", "history | tail -n 30", "history | tail -n 30", "Get-History | Select-Object -Last 30", "doskey /history"),
    ("Speicher", "df -h", "df -h", "Get-PSDrive -PSProvider FileSystem", 'powershell -NoProfile -Command "Get-PSDrive -PSProvider FileSystem"'),
    ("RAM", "free -h", "vm_stat", "Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize,FreePhysicalMemory", "systeminfo"),
    ("Prozesse", "ps aux --sort=-%cpu | head -n 15", "ps aux | sort -nrk 3 | head -n 15", "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15", "tasklist"),
    ("Git", "git status --short --branch", "git status --short --branch", "git status --short --branch", "git status --short --branch"),
)


def make_default_commands() -> list[dict]:
    return [
        {"id": uuid4().hex, "name": name, "command": posix,
         "variants": {"posix": posix, "mac": mac, "powershell": ps, "cmd": cmd},
         "confirm": False, "use_precommand": False, "new_tab": False,
         "shortcut": "", "number_label": False}
        for name, posix, mac, ps, cmd in _PRESETS
    ]


def shell_flavor(shell_type: str, platform: str | None = None) -> str:
    shell = str(shell_type or "").casefold()
    if shell in {"powershell", "pwsh", "powershell7"}:
        return "powershell"
    if shell in {"cmd", "cmd.exe"}:
        return "cmd"
    if (platform or os.sys.platform) == "darwin":
        return "mac"
    return "posix"


def resolved_command(item: dict, shell_type: str, platform: str | None = None) -> str:
    variants = item.get("variants")
    if isinstance(variants, dict):
        return str(variants.get(shell_flavor(shell_type, platform)) or item.get("command", "")).strip()
    return str(item.get("command", "")).strip()


def normalized_command(item: dict) -> dict:
    if not isinstance(item, dict):
        raise ValueError("Ungültiger Schnellbefehl")
    variants = item.get("variants")
    if not isinstance(variants, dict) or not variants:
        variants = None
    return {
        "id": str(item.get("id") or uuid4().hex),
        "name": str(item.get("name", "") or "").strip()[:60],
        "command": str(item.get("command", "") or ""),
        **({"variants": {str(k): str(v) for k, v in variants.items()}} if variants else {}),
        "confirm": bool(item.get("confirm", False)),
        "use_precommand": bool(item.get("use_precommand", False)),
        "new_tab": bool(item.get("new_tab", False)),
        "shortcut": str(item.get("shortcut", "") or "").strip()[:80],
        "number_label": bool(item.get("number_label", False)),
    }


def normalized_settings(payload: dict | None) -> dict:
    if not isinstance(payload, dict):
        payload = {}
    entries = payload.get("commands")
    if not isinstance(entries, list):
        entries = make_default_commands()
    commands = []
    seen = set()
    for raw in entries[:250]:
        try:
            item = normalized_command(raw)
        except ValueError:
            continue
        if item["id"] in seen:
            item["id"] = uuid4().hex
        seen.add(item["id"])
        commands.append(item)
    return {
        "schema": 1, "commands": commands,
        "visible": bool(payload.get("visible", True)),
        "pinned": bool(payload.get("pinned", True)),
        "side": "right" if str(payload.get("side", "left")) == "right" else "left",
        "compact": bool(payload.get("compact", False)),
        "shortcut": str(payload.get("shortcut", "F8") or "F8").strip()[:80],
        # Legacy flag retained for config/test compatibility; no menu option.
        "vt_warning_enabled": bool(payload.get("vt_warning_enabled", True)),
    }


def load_quick_commands(path: str | Path) -> dict:
    file = Path(path)
    try:
        return normalized_settings(json.loads(file.read_text(encoding="utf-8")))
    except (FileNotFoundError, OSError, json.JSONDecodeError, UnicodeError):
        return normalized_settings(None)


def save_quick_commands(path: str | Path, payload: dict) -> None:
    file = Path(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_suffix(file.suffix + ".tmp")
    temporary.write_text(json.dumps(normalized_settings(payload), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(file)
