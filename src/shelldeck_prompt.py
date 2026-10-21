"""Temporäre, lokale PTY-Bash-Prompts ohne Änderung von Benutzerdateien.

ShellDeck nutzt für Bash ohnehin --noprofile --norc. Nur für lokale
PTY-Bash-Sitzungen kann stattdessen eine isolierte --rcfile benutzt werden.
"""
from __future__ import annotations

import re
import shlex
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


def bash_prompt_script(colors: dict, *, precommand_file: str | None = None,
                       include_prompt: bool = True) -> str:
    """Erstellt ein read-only zu ladendes Bash-Startskript.

    Die gestartete Bash hatte zuvor keine benutzerspezifische rc-Datei.
    Die nachträgliche Aktivierung einer venv wird über VIRTUAL_ENV erkannt.
    """
    prompt = rgb_ansi(PROMPT_ROLE_RGB)
    environment = rgb_ansi(ENVIRONMENT_ROLE_RGB)
    reset = r"\[\e[0m\]"
    # Readline (nicht Qt) kennt den Unterschied zwischen dem fertigen
    # Shell-Befehl und Eingaben an laufende TTY-Programme. Der Handler wird
    # ausschliesslich beim Accept-Line der interaktiven Bash aufgerufen.
    # Er fuehrt den Vorbefehl in derselben Bash aus (cd/export bleiben erhalten),
    # ohne die eigentliche READLINE_LINE oder die Bash-Historie umzuschreiben.
    before_enter = ""
    if precommand_file is not None:
        if not precommand_file or "\x00" in precommand_file or "\n" in precommand_file:
            raise ValueError("Ungueltiger Pfad fuer PTY-Vorbefehle")
        before_enter = (
            "__shelldeck_grid_precommand_file=" + shlex.quote(precommand_file) + "\n"
            "__shelldeck_grid_before_enter() {\n"
            "  [[ -n ${READLINE_LINE//[[:space:]]/} ]] || return 0\n"
            "  [[ -s $__shelldeck_grid_precommand_file ]] || return 0\n"
            "  local __shelldeck_before_text\n"
            "  __shelldeck_before_text=$(< \"$__shelldeck_grid_precommand_file\")\n"
            "  [[ -n $__shelldeck_before_text ]] || return 0\n"
            "  eval \"$__shelldeck_before_text\"\n"
            "}\n"
            # The macro first invokes the command in the *current* Bash, then
            # accepts the unchanged readline buffer. We deliberately do not
            # overwrite READLINE_LINE or parse keystrokes in the Qt grid.
            "bind -x '\"\\C-x\\C-]\": __shelldeck_grid_before_enter'\n"
            "bind '\"\\C-x\\C-^\": accept-line'\n"
            "bind '\"\\C-m\": \"\\C-x\\C-]\\C-x\\C-^\"'\n"
            "bind '\"\\C-j\": \"\\C-x\\C-]\\C-x\\C-^\"'\n"
        )
    prompt_setup = (
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
    return (
        (prompt_setup if include_prompt else "# ShellDeck: PTY-Bash ohne eigene Promptfarben\n")
        + "cls() { command clear \"$@\"; }\n"
        + before_enter
    )


def create_bash_prompt_rc(colors: dict, *, include_prompt: bool = True):
    """Rückgabe (TemporaryDirectory, Pfad); Besitzer hält Verzeichnis am Leben."""
    directory = tempfile.TemporaryDirectory(prefix="shelldeck-prompt-")
    path = Path(directory.name) / "bashrc"
    prefix_file = Path(directory.name) / "grid_precommand"
    try:
        prefix_file.write_text("", encoding="utf-8")
        prefix_file.chmod(0o600)
        path.write_text(bash_prompt_script(colors, precommand_file=str(prefix_file),
                                           include_prompt=include_prompt), encoding="utf-8")
        path.chmod(0o600)
    except BaseException:
        directory.cleanup()
        raise
    return directory, str(path)
