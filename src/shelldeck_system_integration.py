"""Zentrale, UI-freie Logik für die Systemintegration von ShellDeck.

Trennung der Verantwortlichkeiten:

* Dieses Modul kapselt ausschließlich den Systemzugriff (Linux
  ``update-alternatives`` bzw. Windows-Registry). Es enthält keinerlei
  Qt-/UI-Code und ist damit gut testbar.
* Beim reinen Import werden **niemals** Systemänderungen ausgelöst.
* Alle verändernden Funktionen sind idempotent: mehrfaches Installieren
  erzeugt keine Duplikate, mehrfaches Entfernen keinen Fehler.
* Linux- und Windows-Zweige sind sauber getrennt. Windows-spezifische Module
  (``winreg``) werden nur innerhalb der Windows-Funktionen importiert, damit
  der Import unter Linux nicht fehlschlägt.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


# --- Konstanten -------------------------------------------------------------

# Name des Kontextmenü-/Alternativen-Eintrags. Bewusst eindeutig, damit beim
# Entfernen nur ShellDeck-eigene Einträge betroffen sind.
LINUX_ALTERNATIVE_NAME = "x-terminal-emulator"
LINUX_ALTERNATIVE_LINK = "/usr/bin/x-terminal-emulator"
# Bewusst niedrige Priorität: ShellDeck drängt sich nicht als Standard auf.
LINUX_ALTERNATIVE_PRIORITY = 40
LINUX_DEFAULT_LAUNCHER = "/usr/bin/shelldeck"

WINDOWS_MENU_LABEL = "In ShellDeck öffnen"
# Eindeutiger, klar ShellDeck-eigener Registry-Schlüsselname.
WINDOWS_KEY_NAME = "ShellDeck"
WINDOWS_CLASSES_BASE = r"Software\Classes"


@dataclass
class IntegrationResult:
    """Einheitliches, verständliches Ergebnis einer Integrationsaktion."""

    success: bool
    changed: bool
    message: str
    details: str = ""


@dataclass
class RegistryEntry:
    """Ein einzelner geplanter Registry-Eintrag (rein beschreibend)."""

    hive: str          # z.B. "HKCU"
    path: str          # Unterschlüssel unterhalb der Hive
    values: Dict[str, str] = field(default_factory=dict)  # "" == (Standard)


# --- Plattform-Hilfen -------------------------------------------------------

def is_windows() -> bool:
    return os.name == "nt" or sys.platform.startswith("win")


def is_linux() -> bool:
    return sys.platform.startswith("linux")


def current_executable_path() -> str:
    """Bestmöglicher Pfad zur laufenden ShellDeck-Programmdatei.

    Bei einem kompilierten Build (Nuitka/PyInstaller: ``sys.frozen``) ist das
    die ausführbare Datei selbst. Im Quelllauf wird der Interpreterpfad bzw.
    ``sys.argv[0]`` verwendet. Der Wert dient nur zur Anzeige und als
    Vorschlag; die tatsächlich zu registrierende Datei kann davon abweichen.
    """
    if getattr(sys, "frozen", False):
        try:
            return str(Path(sys.executable).resolve())
        except (OSError, RuntimeError):
            return sys.executable
    try:
        return str(Path(sys.argv[0]).resolve())
    except (OSError, RuntimeError, IndexError):
        return sys.argv[0] if sys.argv else ""


def default_linux_launcher_path() -> str:
    """Pfad, der als ``x-terminal-emulator`` registriert werden soll.

    Bevorzugt der installierte Wrapper ``/usr/bin/shelldeck`` (reicht Argumente
    weiter). Existiert er nicht (z.B. Quelllauf), wird auf die laufende
    Programmdatei zurückgegriffen.
    """
    if os.path.exists(LINUX_DEFAULT_LAUNCHER):
        return LINUX_DEFAULT_LAUNCHER
    exe = current_executable_path()
    return exe or LINUX_DEFAULT_LAUNCHER


def detect_platform_integration() -> dict:
    """Überblick über die verfügbare Integration der aktuellen Plattform."""
    info = {
        "platform": sys.platform,
        "is_windows": is_windows(),
        "is_linux": is_linux(),
        "executable_path": current_executable_path(),
        "linux_alternatives_available": False,
        "windows_registry_available": False,
    }
    if is_linux():
        info["linux_alternatives_available"] = find_update_alternatives() is not None
        info["linux_launcher_path"] = default_linux_launcher_path()
    if is_windows():
        info["windows_registry_available"] = True
    return info


# --- Linux: update-alternatives --------------------------------------------

def find_update_alternatives() -> Optional[str]:
    """Pfad zu ``update-alternatives`` oder ``None``, falls nicht vorhanden."""
    return shutil.which("update-alternatives")


def build_install_alternative_command(
    launcher_path: str,
    priority: int = LINUX_ALTERNATIVE_PRIORITY,
    update_alternatives: str = "update-alternatives",
) -> List[str]:
    """Argumentliste für die Registrierung (rein, gut testbar)."""
    return [
        update_alternatives,
        "--install",
        LINUX_ALTERNATIVE_LINK,
        LINUX_ALTERNATIVE_NAME,
        str(launcher_path),
        str(int(priority)),
    ]


def build_remove_alternative_command(
    launcher_path: str,
    update_alternatives: str = "update-alternatives",
) -> List[str]:
    """Argumentliste für das Entfernen genau der ShellDeck-Alternative."""
    return [
        update_alternatives,
        "--remove",
        LINUX_ALTERNATIVE_NAME,
        str(launcher_path),
    ]


def build_config_alternative_command() -> List[str]:
    """Befehl zur interaktiven Auswahl des Standardterminals (Anzeige)."""
    return ["sudo", "update-alternatives", "--config", LINUX_ALTERNATIVE_NAME]


def _run_process(args: List[str], timeout: int = 20):
    """Führt einen Prozess sicher aus (shell=False, Argumentliste)."""
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        text=True,
        timeout=timeout,
        check=False,
    )


def get_linux_terminal_alternative_status(
    launcher_path: Optional[str] = None,
) -> IntegrationResult:
    """Ermittelt, ob und wie ShellDeck als ``x-terminal-emulator`` registriert ist."""
    if not is_linux():
        return IntegrationResult(False, False, "Nur unter Linux verfügbar.")
    ua = find_update_alternatives()
    if ua is None:
        return IntegrationResult(
            False, False,
            "»update-alternatives« ist nicht verfügbar. Die Terminal-Registrierung "
            "wird auf diesem System nicht unterstützt.",
        )
    launcher = launcher_path or default_linux_launcher_path()
    try:
        result = _run_process([ua, "--query", LINUX_ALTERNATIVE_NAME])
    except (OSError, subprocess.SubprocessError) as exc:
        return IntegrationResult(False, False,
                                 "Status konnte nicht ermittelt werden.", str(exc))
    if result.returncode != 0:
        # Kein Eintrag vorhanden -> Gruppe existiert noch nicht.
        return IntegrationResult(
            True, False,
            "ShellDeck ist derzeit nicht als Terminal-Alternative registriert.",
            (result.stderr or "").strip(),
        )
    text = result.stdout or ""
    registered = launcher in text
    selected_value = ""
    for line in text.splitlines():
        if line.startswith("Value:"):
            selected_value = line.split(":", 1)[1].strip()
            break
    is_selected = bool(selected_value) and selected_value == launcher
    if registered and is_selected:
        msg = "ShellDeck ist registriert und aktuell als Standardterminal ausgewählt."
    elif registered:
        msg = ("ShellDeck ist als Terminal-Alternative registriert, aber nicht als "
               "Standard ausgewählt.")
    else:
        msg = "ShellDeck ist derzeit nicht als Terminal-Alternative registriert."
    return IntegrationResult(True, False, msg, text.strip())


def install_linux_terminal_alternative(
    launcher_path: Optional[str] = None,
    priority: int = LINUX_ALTERNATIVE_PRIORITY,
    use_pkexec: bool = False,
) -> IntegrationResult:
    """Registriert ShellDeck als auswählbare Terminal-Alternative.

    Setzt ShellDeck **nicht** automatisch als Standard. Idempotent: eine
    erneute Registrierung mit gleichem Pfad aktualisiert nur die Priorität.
    """
    if not is_linux():
        return IntegrationResult(False, False, "Nur unter Linux verfügbar.")
    ua = find_update_alternatives()
    if ua is None:
        return IntegrationResult(
            False, False,
            "»update-alternatives« ist nicht verfügbar. Die Registrierung wird "
            "auf diesem System nicht unterstützt.",
        )
    launcher = launcher_path or default_linux_launcher_path()
    command = build_install_alternative_command(launcher, priority, ua)
    if use_pkexec:
        pkexec = shutil.which("pkexec")
        if pkexec is None:
            return IntegrationResult(
                False, False,
                "»pkexec« ist nicht verfügbar. Bitte den Befehl manuell mit "
                "Administratorrechten ausführen.",
                " ".join(build_install_alternative_command(launcher, priority)),
            )
        command = [pkexec] + command
    try:
        result = _run_process(command)
    except (OSError, subprocess.SubprocessError) as exc:
        return IntegrationResult(
            False, False,
            "Die Registrierung konnte nicht ausgeführt werden.",
            str(exc),
        )
    if result.returncode == 0:
        return IntegrationResult(
            True, True,
            "ShellDeck wurde als Terminal-Alternative registriert. Das bisherige "
            "Standardterminal bleibt unverändert.",
            (result.stdout or "").strip(),
        )
    # Häufigster Fehlerfall: fehlende Rechte.
    hint = ("Fehlende Berechtigung. Bitte mit Administratorrechten ausführen:\n"
            "sudo " + " ".join(build_install_alternative_command(launcher, priority)))
    return IntegrationResult(
        False, False,
        "Die Registrierung ist fehlgeschlagen (vermutlich fehlende Rechte).",
        (result.stderr or "").strip() + "\n\n" + hint,
    )


def remove_linux_terminal_alternative(
    launcher_path: Optional[str] = None,
    use_pkexec: bool = False,
) -> IntegrationResult:
    """Entfernt genau die ShellDeck-Alternative. Idempotent."""
    if not is_linux():
        return IntegrationResult(False, False, "Nur unter Linux verfügbar.")
    ua = find_update_alternatives()
    if ua is None:
        return IntegrationResult(
            False, False,
            "»update-alternatives« ist nicht verfügbar.",
        )
    launcher = launcher_path or default_linux_launcher_path()
    command = build_remove_alternative_command(launcher, ua)
    if use_pkexec:
        pkexec = shutil.which("pkexec")
        if pkexec is None:
            return IntegrationResult(
                False, False,
                "»pkexec« ist nicht verfügbar. Bitte den Befehl manuell mit "
                "Administratorrechten ausführen.",
                " ".join(build_remove_alternative_command(launcher)),
            )
        command = [pkexec] + command
    try:
        result = _run_process(command)
    except (OSError, subprocess.SubprocessError) as exc:
        return IntegrationResult(
            False, False,
            "Das Entfernen konnte nicht ausgeführt werden.",
            str(exc),
        )
    if result.returncode == 0:
        return IntegrationResult(
            True, True,
            "Die ShellDeck-Terminal-Alternative wurde entfernt. Andere Terminals "
            "bleiben unverändert.",
            (result.stdout or "").strip(),
        )
    hint = ("Fehlende Berechtigung. Bitte mit Administratorrechten ausführen:\n"
            "sudo " + " ".join(build_remove_alternative_command(launcher)))
    return IntegrationResult(
        False, False,
        "Das Entfernen ist fehlgeschlagen (vermutlich fehlende Rechte).",
        (result.stderr or "").strip() + "\n\n" + hint,
    )


# --- Windows: Explorer-Kontextmenü -----------------------------------------

def _windows_command_for(executable_path: str, placeholder: str) -> str:
    """Erzeugt eine korrekt gequotete Kommandozeile für die Registry."""
    exe = str(executable_path or "").strip().strip('"')
    return '"{exe}" --working-directory "{ph}"'.format(exe=exe, ph=placeholder)


def build_windows_registry_entries(
    executable_path: str,
    include_drives: bool = False,
) -> List[RegistryEntry]:
    """Beschreibt alle zu setzenden Registry-Einträge (rein, gut testbar).

    Verwendet ausschließlich den benutzerbezogenen Zweig
    ``HKCU\\Software\\Classes`` und ändert nichts systemweit.
    """
    exe = str(executable_path or "").strip().strip('"')
    icon_value = '"{exe}",0'.format(exe=exe)
    base = WINDOWS_CLASSES_BASE
    key = WINDOWS_KEY_NAME
    entries: List[RegistryEntry] = []

    # Rechtsklick auf einen Ordner -> %1 ist der Ordnerpfad.
    entries.append(RegistryEntry(
        "HKCU", r"{b}\Directory\shell\{k}".format(b=base, k=key),
        {"": WINDOWS_MENU_LABEL, "Icon": icon_value},
    ))
    entries.append(RegistryEntry(
        "HKCU", r"{b}\Directory\shell\{k}\command".format(b=base, k=key),
        {"": _windows_command_for(exe, "%1")},
    ))

    # Rechtsklick auf den freien Hintergrund -> %V ist der aktuelle Ordner.
    entries.append(RegistryEntry(
        "HKCU", r"{b}\Directory\Background\shell\{k}".format(b=base, k=key),
        {"": WINDOWS_MENU_LABEL, "Icon": icon_value},
    ))
    entries.append(RegistryEntry(
        "HKCU", r"{b}\Directory\Background\shell\{k}\command".format(b=base, k=key),
        {"": _windows_command_for(exe, "%V")},
    ))

    if include_drives:
        # Rechtsklick auf ein Laufwerk -> %V ist der Laufwerksstamm.
        entries.append(RegistryEntry(
            "HKCU", r"{b}\Drive\shell\{k}".format(b=base, k=key),
            {"": WINDOWS_MENU_LABEL, "Icon": icon_value},
        ))
        entries.append(RegistryEntry(
            "HKCU", r"{b}\Drive\shell\{k}\command".format(b=base, k=key),
            {"": _windows_command_for(exe, "%V")},
        ))
    return entries


def windows_registry_key_paths(include_drives: bool = True) -> List[str]:
    """Oberste ShellDeck-Schlüssel (für sauberes, begrenztes Entfernen)."""
    base = WINDOWS_CLASSES_BASE
    key = WINDOWS_KEY_NAME
    paths = [
        r"{b}\Directory\shell\{k}".format(b=base, k=key),
        r"{b}\Directory\Background\shell\{k}".format(b=base, k=key),
    ]
    if include_drives:
        paths.append(r"{b}\Drive\shell\{k}".format(b=base, k=key))
    return paths


def get_windows_explorer_integration_status(
    executable_path: Optional[str] = None,
) -> IntegrationResult:
    """Prüft, ob das ShellDeck-Kontextmenü existiert und aktuell ist."""
    if not is_windows():
        return IntegrationResult(False, False, "Nur unter Windows verfügbar.")
    import winreg  # nur unter Windows importieren

    exe = (executable_path or current_executable_path()).strip().strip('"')
    folder_cmd_path = r"{b}\Directory\shell\{k}\command".format(
        b=WINDOWS_CLASSES_BASE, k=WINDOWS_KEY_NAME)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, folder_cmd_path) as handle:
            value, _ = winreg.QueryValueEx(handle, "")
    except FileNotFoundError:
        return IntegrationResult(
            True, False,
            "Der Explorer-Eintrag »In ShellDeck öffnen« ist nicht installiert.",
        )
    except OSError as exc:
        return IntegrationResult(False, False,
                                 "Status konnte nicht gelesen werden.", str(exc))
    up_to_date = exe and exe in str(value)
    if up_to_date:
        msg = "Der Explorer-Eintrag »In ShellDeck öffnen« ist installiert und aktuell."
    else:
        msg = ("Der Explorer-Eintrag ist installiert, verweist aber auf einen anderen "
               "Programmpfad. Eine erneute Installation aktualisiert ihn.")
    return IntegrationResult(True, False, msg, str(value))


def install_windows_explorer_integration(
    executable_path: Optional[str] = None,
    include_drives: bool = False,
) -> IntegrationResult:
    """Legt das benutzerbezogene Explorer-Kontextmenü an bzw. aktualisiert es.

    Idempotent: bestehende Schlüssel werden überschrieben, ein geänderter
    Programmpfad wird korrekt aktualisiert. Erzeugt keine Duplikate.
    """
    if not is_windows():
        return IntegrationResult(False, False, "Nur unter Windows verfügbar.")
    import winreg  # nur unter Windows importieren

    exe = (executable_path or current_executable_path()).strip().strip('"')
    if not exe:
        return IntegrationResult(False, False,
                                 "Kein Programmpfad für ShellDeck ermittelbar.")
    # Vor dem Neuschreiben veraltete Schlüssel entfernen (auch Laufwerke), damit
    # ein abgewählter Laufwerkseintrag nicht zurückbleibt.
    _delete_windows_keys(winreg, windows_registry_key_paths(include_drives=True))
    entries = build_windows_registry_entries(exe, include_drives=include_drives)
    try:
        for entry in entries:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, entry.path) as handle:
                for name, value in entry.values.items():
                    winreg.SetValueEx(handle, name, 0, winreg.REG_SZ, value)
    except OSError as exc:
        return IntegrationResult(False, False,
                                 "Der Explorer-Eintrag konnte nicht angelegt werden.",
                                 str(exc))
    scope = "Ordner, Ordnerhintergründe" + (", Laufwerke" if include_drives else "")
    return IntegrationResult(
        True, True,
        "Der Explorer-Eintrag »In ShellDeck öffnen« wurde installiert (" + scope + ").",
        exe,
    )


def remove_windows_explorer_integration() -> IntegrationResult:
    """Entfernt ausschließlich die ShellDeck-eigenen Registry-Schlüssel. Idempotent."""
    if not is_windows():
        return IntegrationResult(False, False, "Nur unter Windows verfügbar.")
    import winreg  # nur unter Windows importieren

    removed = _delete_windows_keys(winreg, windows_registry_key_paths(include_drives=True))
    if removed:
        return IntegrationResult(True, True,
                                 "Der Explorer-Eintrag »In ShellDeck öffnen« wurde entfernt.")
    return IntegrationResult(True, False,
                             "Es war kein ShellDeck-Explorer-Eintrag vorhanden.")


def _delete_windows_keys(winreg, top_paths) -> bool:
    """Löscht die genannten Schlüssel samt Unterschlüsseln rekursiv.

    Nur die übergebenen, klar ShellDeck-eigenen Pfade werden angefasst.
    Rückgabe: True, wenn mindestens ein Schlüssel entfernt wurde.
    """
    any_removed = False
    for path in top_paths:
        if _delete_windows_key_tree(winreg, winreg.HKEY_CURRENT_USER, path):
            any_removed = True
    return any_removed


def _delete_windows_key_tree(winreg, root, path) -> bool:
    """Rekursives Löschen eines Registry-Teilbaums. Fehlt er, kein Fehler."""
    try:
        handle = winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS)
    except FileNotFoundError:
        return False
    except OSError:
        return False
    try:
        while True:
            try:
                child = winreg.EnumKey(handle, 0)
            except OSError:
                break
            _delete_windows_key_tree(winreg, root, path + "\\" + child)
    finally:
        winreg.CloseKey(handle)
    try:
        winreg.DeleteKey(root, path)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
