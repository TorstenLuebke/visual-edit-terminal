"""Temporäre, lokale PTY-Bash-Prompts ohne Änderung von Benutzerdateien.

ShellDeck nutzt für Bash ohnehin --noprofile --norc. Nur für lokale
PTY-Bash-Sitzungen kann stattdessen eine isolierte --rcfile benutzt werden.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


def rgb_ansi(color: str) -> str:
    """Bash-PS1-Farbcode mit korrekten Readline-Nonprinting-Markern."""
    if not isinstance(color, str) or not _HEX.fullmatch(color):
        raise ValueError("Ungueltige RGB-Farbe")
    channels = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return r"\[\e[38;2;{};{};{}m\]".format(*channels)


# Reservierte RGB-Rollen der lokalen ShellDeck-Bash. Nur diese beiden
# Farbwerte werden im PTY-Renderer themenabhängig aufgelöst. Andere SGR-
# Farben werden weder überschrieben noch im VT-Modell verändert.
PROMPT_ROLE_RGB = "#010203"
ENVIRONMENT_ROLE_RGB = "#040506"


def bash_prompt_script(colors: dict) -> str:
    """Erstellt ein read-only zu ladendes Bash-Startskript.

    Die gestartete Bash hatte zuvor keine benutzerspezifische rc-Datei.
    Die nachträgliche Aktivierung einer venv wird über VIRTUAL_ENV erkannt.
    """
    prompt = rgb_ansi(PROMPT_ROLE_RGB)
    environment = rgb_ansi(ENVIRONMENT_ROLE_RGB)
    reset = r"\[\e[0m\]"
    return (
        "# ShellDeck: ausschliesslich lokale PTY-Bash; kein Eingriff in ~/.bashrc\n"
        "__shelldeck_update_prompt() {\n"
        "  local __shelldeck_env_prefix=''\n"
        "  if [[ -n ${VIRTUAL_ENV:-} && ${VIRTUAL_ENV_PROMPT:-} != ' ' ]]; then\n"
        "    local __shelldeck_name=${VIRTUAL_ENV_PROMPT:-${VIRTUAL_ENV##*/}}\n"
        f"    __shelldeck_env_prefix='{environment}('\"$__shelldeck_name\"') {reset}'\n"
        "  fi\n"
        '  PS1="${__shelldeck_env_prefix}"' + "'" + prompt + r'\s-\v\$ ' + reset + "'\n"
        "}\n"
        "PROMPT_COMMAND=__shelldeck_update_prompt\n"
        "__shelldeck_update_prompt\n"
    )


def create_bash_prompt_rc(colors: dict):
    """Rückgabe (TemporaryDirectory, Pfad); Besitzer hält Verzeichnis am Leben."""
    directory = tempfile.TemporaryDirectory(prefix="shelldeck-prompt-")
    path = Path(directory.name) / "bashrc"
    try:
        path.write_text(bash_prompt_script(colors), encoding="utf-8")
        path.chmod(0o600)
    except BaseException:
        directory.cleanup()
        raise
    return directory, str(path)
