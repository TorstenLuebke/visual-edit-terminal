"""Kommandozeilenauswertung für ShellDeck.

Dieses Modul ist bewusst klein, ohne Qt-Abhängigkeit und ohne Seiteneffekte,
damit es eigenständig testbar bleibt. Es bildet die von einem Terminal-Emulator
üblichen Aufrufe ab, ohne die vorhandene Architektur umzubauen:

    shelldeck --working-directory "/pfad"
    shelldeck --new-tab "/pfad"
    shelldeck -e git status
    shelldeck --execute git status
    shelldeck --working-directory "/tmp" -e pwd

Grundsätze:

* Es werden nur Argumente ausgewertet, kein System verändert.
* ``-e``/``--execute``/``-x`` verschlingen wie bei ``x-terminal-emulator``
  üblich den kompletten Rest der Befehlszeile als auszuführenden Befehl.
  Dadurch bleiben Argumentgrenzen erhalten (kein erneutes String-Splitting).
* Häufige Kompatibilitätsoptionen anderer Terminals (``--title``, ``--geometry``
  …) werden ruhig geschluckt, damit ShellDeck als Ersatzterminal nicht an einem
  unbekannten Argument scheitert.
"""

from __future__ import annotations

import os
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Tuple


# Optionen, die ein Verzeichnis erwarten.
_WORKDIR_OPTS = {"--working-directory", "--work-directory", "--workdir"}
_NEWTAB_OPTS = {"--new-tab"}
# Alles nach diesen Optionen ist der auszuführende Befehl.
_EXECUTE_OPTS = {"-e", "--execute", "-x", "--command"}

# Kompatibilitätsoptionen anderer Terminal-Emulatoren, die einen Wert
# mitbringen und für ShellDeck ohne Bedeutung sind. Sie werden geschluckt,
# damit ein fremder Aufrufer ShellDeck nicht mit einem unbekannten Argument
# zum Absturz bringt.
_IGNORED_VALUE_OPTS = {
    "-T", "--title", "--geometry", "--role", "--class", "--name",
    "--display", "--window-with-profile", "--profile", "--zoom",
}
# Kompatibilitäts-Schalter ohne Wert.
_IGNORED_FLAG_OPTS = {
    "--hold", "--tab", "--window", "--maximize", "--fullscreen",
    "--wait", "--sm-client-disable",
}


@dataclass
class LaunchOptions:
    """Ergebnis der Kommandozeilenauswertung."""

    # Rohwert von --working-directory bzw. --new-tab (noch nicht aufgelöst).
    working_directory: str = ""
    new_tab: bool = False
    new_tab_directory: str = ""
    # Tokens des auszuführenden Befehls (bereits als Argumentliste).
    execute_command: List[str] = field(default_factory=list)
    execute_requested: bool = False
    # Geschluckte Kompatibilitätsoptionen (nur zur Diagnose/Tests).
    ignored: List[str] = field(default_factory=list)
    # Unbekannte Optionen, die nicht zugeordnet werden konnten.
    unknown: List[str] = field(default_factory=list)
    # Verständliche deutsche Meldungen für die Oberfläche.
    errors: List[str] = field(default_factory=list)

    @property
    def has_directory(self) -> bool:
        return bool(self.working_directory or self.new_tab_directory)

    @property
    def requested_directory(self) -> str:
        """Bevorzugt --working-directory, sonst --new-tab-Verzeichnis."""
        return self.working_directory or self.new_tab_directory


def split_command_string(value: str) -> List[str]:
    """Zerlegt einen einzelnen Befehls-String tolerant in Argumente."""
    text = str(value or "").strip()
    if not text:
        return []
    try:
        return shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        return text.split()


def _option_name_and_inline_value(arg: str) -> Tuple[str, str, bool]:
    """Zerlegt ``--opt=wert`` in (name, wert, hat_inline_wert)."""
    if arg.startswith("--") and "=" in arg:
        name, value = arg.split("=", 1)
        return name, value, True
    return arg, "", False


def parse_launch_arguments(argv) -> LaunchOptions:
    """Wertet die Argumentliste (ohne Programmnamen) aus.

    Die Funktion verändert nichts am System und wirft keine Ausnahmen bei
    fehlerhaften Eingaben, sondern sammelt verständliche Meldungen in
    ``LaunchOptions.errors``.
    """
    opts = LaunchOptions()
    args = list(argv or [])
    index = 0
    count = len(args)

    while index < count:
        raw = args[index]
        name, inline_value, has_inline = _option_name_and_inline_value(raw)

        if name in _EXECUTE_OPTS:
            opts.execute_requested = True
            if has_inline:
                command = split_command_string(inline_value)
                command.extend(args[index + 1:])
            else:
                command = list(args[index + 1:])
            opts.execute_command = command
            if not command:
                opts.errors.append(
                    "Nach »{opt}« wurde kein Befehl angegeben.".format(opt=name)
                )
            # Rest der Zeile gehört zum Befehl -> Auswertung beenden.
            break

        if name in _WORKDIR_OPTS:
            value, consumed = _consume_value(name, inline_value, has_inline, args, index)
            if value is None:
                opts.errors.append(
                    "Für »{opt}« wurde kein Verzeichnis angegeben.".format(opt=name)
                )
            else:
                opts.working_directory = value
            index += consumed
            continue

        if name in _NEWTAB_OPTS:
            opts.new_tab = True
            value, consumed = _consume_value(name, inline_value, has_inline, args, index)
            if value is not None:
                opts.new_tab_directory = value
            index += consumed
            continue

        if name in _IGNORED_VALUE_OPTS:
            _, consumed = _consume_value(name, inline_value, has_inline, args, index)
            opts.ignored.append(name)
            index += consumed
            continue

        if name in _IGNORED_FLAG_OPTS:
            opts.ignored.append(name)
            index += 1
            continue

        if raw.startswith("-") and raw != "-":
            opts.unknown.append(raw)
            index += 1
            continue

        # Positionsargument ohne Option: als Arbeitsverzeichnis deuten, wenn
        # noch keines gesetzt wurde. So funktioniert auch ein simpler Aufruf
        # »shelldeck /pfad«.
        if not opts.working_directory and not opts.new_tab_directory:
            opts.working_directory = raw
        else:
            opts.unknown.append(raw)
        index += 1

    return opts


def _consume_value(name, inline_value, has_inline, args, index):
    """Liefert (wert, verbrauchte_tokens) für eine wertnehmende Option."""
    if has_inline:
        return inline_value, 1
    following = index + 1
    if following < len(args) and not _looks_like_option(args[following]):
        return args[following], 2
    return None, 1


def _looks_like_option(token: str) -> bool:
    text = str(token or "")
    # Ein einzelnes "-" ist ein Wert (stdin), keine Option. Negative Zahlen
    # sind hier praktisch irrelevant, ein führendes "--" markiert eine Option.
    return text.startswith("-") and text != "-"


def resolve_directory(raw_path: str) -> Tuple[str, bool]:
    """Normalisiert einen Verzeichnispfad plattformübergreifend.

    Rückgabe: (aufgelöster_pfad, existiert_als_verzeichnis). ``~`` und
    Umgebungsvariablen werden aufgelöst, relative Pfade absolut gemacht.
    Bei leerer Eingabe wird ("", False) zurückgegeben. Es findet kein
    Zugriff statt, der ShellDeck blockieren könnte.
    """
    text = str(raw_path or "").strip().strip('"').strip("'")
    if not text:
        return "", False
    try:
        expanded = os.path.expandvars(os.path.expanduser(text))
        path = Path(expanded)
        if not path.is_absolute():
            path = Path.cwd() / path
        resolved = os.path.normpath(str(path))
        exists = os.path.isdir(resolved)
        return resolved, exists
    except (OSError, ValueError):
        return text, False
