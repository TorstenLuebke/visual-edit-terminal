"""Systemkürzel-Prüfung für Schnellbefehle (Qt-unabhängig und defensiv).

Qt-Kürzel sind *fensterlokal*. Andere Anwendungen und der Desktop können
Shortcuts systemweit abfangen, ohne dass Qt das melden kann. Deshalb werden
bekannte Reservierungen gesperrt und GNOME-Bindings nach Möglichkeit gelesen.
Ein plattformübergreifend vollständiges Verzeichnis globaler Kürzel gibt es
nicht; die UI darf eine solche Garantie nicht behaupten.
"""
from __future__ import annotations

from functools import lru_cache
import os
import re
import shutil
import subprocess
import sys


_MOD_ALIASES = {
    "CONTROL": "CTRL", "PRIMARY": "CTRL", "CTRL": "CTRL",
    "OPTION": "ALT", "MOD1": "ALT", "ALT": "ALT",
    "SHIFT": "SHIFT", "SUPER": "META", "WIN": "META",
    "MOD4": "META", "COMMAND": "META", "CMD": "META", "META": "META",
}
_KEY_ALIASES = {"ESC": "ESCAPE", "DEL": "DELETE", "PGUP": "PAGEUP", "PGDOWN": "PAGEDOWN",
                "ISO_LEFT_TAB": "TAB", "SPACE": "SPACE", "ENTER": "RETURN"}
_ORDER = ("CTRL", "ALT", "SHIFT", "META")


def shortcut_identity(sequence: str) -> str:
    """Für Gleichheit nur die Modifier-Reihenfolge vereinheitlichen.

    Qt liefert zuvor das PortableText-Format. Ohne Qt kann dieses Format
    ebenfalls für unit tests und GNOME-Keybinding-Abgleich verwendet werden.
    """
    parts = [part.strip().upper() for part in str(sequence or "").split("+")]
    if not parts or not parts[-1]:
        return ""
    modifiers = set()
    for part in parts[:-1]:
        mod = _MOD_ALIASES.get(part)
        if mod is None:
            return ""
        modifiers.add(mod)
    key = _KEY_ALIASES.get(parts[-1], parts[-1])
    return "+".join([*(mod for mod in _ORDER if mod in modifiers), key])


def _gnome_binding_to_identity(binding: str) -> str:
    """Beispiel: <Primary><Alt>Delete, <Super>Tab, <Shift><Alt>F1."""
    binding = str(binding).strip()
    mods = re.findall(r"<([^>]+)>", binding)
    key = re.sub(r"<[^>]+>", "", binding).strip()
    if not key or key.lower() in {"disabled", "none"}:
        return ""
    return shortcut_identity("+".join([*mods, key]))


def parse_gnome_bindings(output: str) -> set[str]:
    """Parst die Stringwerte von `gsettings list-recursively` (GVariant)."""
    reserved = set()
    for line in str(output).splitlines():
        # GVariant bindet Belegungen als '...'; Keys in Arrays werden ebenfalls
        # einzeln mit einfachen Anführungszeichen ausgegeben.
        for value in re.findall(r"'([^']*)'", line):
            identity = _gnome_binding_to_identity(value)
            if identity:
                reserved.add(identity)
    return reserved


@lru_cache(maxsize=4)
def gnome_reserved_shortcuts(desktop: str = "") -> frozenset[str]:
    """Best-effort. Fehler/Time-outs blockieren die ShellDeck-Oberfläche nicht."""
    name = (desktop or os.environ.get("XDG_CURRENT_DESKTOP", "")).upper()
    if "GNOME" not in name or not shutil.which("gsettings"):
        return frozenset()
    reserved = set()
    for schema in (
        "org.gnome.desktop.wm.keybindings",
        "org.gnome.mutter.keybindings",
        "org.gnome.shell.keybindings",
        "org.gnome.settings-daemon.plugins.media-keys",
    ):
        try:
            result = subprocess.run(
                ["gsettings", "list-recursively", schema], capture_output=True,
                text=True, timeout=1.5, check=False,
            )
            if result.returncode == 0:
                reserved.update(parse_gnome_bindings(result.stdout))
        except (OSError, subprocess.TimeoutExpired):
            continue
    # Individuelle GNOME-Bindings leben in relocatable schemas und werden mit
    # list-recursively der Hauptschema nicht automatisch erfasst.
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys", "custom-keybindings"],
            capture_output=True, text=True, timeout=1.5, check=False,
        )
        if result.returncode == 0:
            paths = re.findall(r"'(/[^']+/)'", result.stdout)[:64]
            for path in paths:
                try:
                    custom = subprocess.run(
                        ["gsettings", "get", f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{path}", "binding"],
                        capture_output=True, text=True, timeout=0.3, check=False,
                    )
                    if custom.returncode == 0:
                        reserved.update(parse_gnome_bindings(custom.stdout))
                except (OSError, subprocess.TimeoutExpired):
                    continue
    except (OSError, subprocess.TimeoutExpired):
        pass
    return frozenset(reserved)


def system_shortcut_conflict(sequence: str, *, platform: str | None = None,
                             desktop: str | None = None, gn_bindings: set[str] | None = None) -> str:
    """Deutsche Fehlermeldung oder leer. Unbekannte globale Belegungen bleiben möglich."""
    identity = shortcut_identity(sequence)
    if not identity:
        return "Die Tastenkombination ist ungültig."
    os_name = str(platform or sys.platform).lower()
    common = {
        "ALT+TAB", "ALT+SHIFT+TAB", "CTRL+ALT+DELETE", "CTRL+SHIFT+ESCAPE",
        "CTRL+SPACE",  # verbreitete Eingabemethoden / Desktop-Umschaltung
    }
    if identity in common:
        return "Diese Tastenkombination ist üblicherweise systemweit reserviert."

    if os_name.startswith("win"):
        if "META" in identity.split("+")[:-1] or identity in {"ALT+F4", "ALT+SPACE", "ALT+ESCAPE"}:
            return "Diese Windows-Tastenkombination wird vom Betriebssystem verwendet."
    elif os_name == "darwin":
        mac = {"META+TAB", "META+SPACE", "CTRL+SPACE", "META+SHIFT+3",
               "META+SHIFT+4", "META+SHIFT+5", "META+ALT+ESCAPE"}
        if identity in mac:
            return "Diese macOS-Tastenkombination wird vom Betriebssystem verwendet."
    else:
        if "META" in identity.split("+")[:-1] or identity in {"ALT+F4", "ALT+SPACE", "CTRL+ALT+T"}:
            return "Diese Tastenkombination wird häufig vom Linux-Desktop abgefangen."
        existing = gn_bindings if gn_bindings is not None else gnome_reserved_shortcuts(desktop or "")
        if identity in existing:
            return "Diese Tastenkombination ist bereits in den GNOME-Systemeinstellungen belegt."
    return ""
