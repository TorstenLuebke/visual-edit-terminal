"""Vorsichtige Erkennung von Befehlen, die ein VT-Zellgitter brauchen.

Nur eigenstaendige Programmaufrufe erkennen; niemals Teilstrings in Skripten,
Pipelines oder Shell-Konstrukten als Befehl interpretieren. Unbekannte Programme
koennen spaeter sicher ueber den PTY-Vordergrundprozess erkannt werden.
"""

import shlex

from shelldeck_program_assist import GUIDES, canonical_program

_SHELL_OPERATORS = frozenset({";", "&", "&&", "|", "||", ">", ">>", "<", "<<", "<>"})
_NON_INTERACTIVE_FLAGS = frozenset({"--help", "--version", "-h", "-v", "-V"})


def direct_vt_program(command):
    """Programmname oder None, nur bei eindeutig direktem interaktivem Aufruf.

    Kein Shell-Parsing mit Ausfuehrung, keine Aufloesung von Variablen oder
    fremden Kommandos. Auch bei indirekten Aufrufen kann die PTY-Pruefung
    spaeter den tatsaechlichen Vordergrundprozess erkennen.
    """
    source = str(command or "").strip()
    if not source or "\n" in source or "\r" in source:
        return None
    try:
        lexer = shlex.shlex(source, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens or any(token in _SHELL_OPERATORS or token.startswith(("&&", "||", ";;")) for token in tokens):
        return None
    name = canonical_program(tokens[0])
    if name not in GUIDES:
        return None
    if any(token in _NON_INTERACTIVE_FLAGS for token in tokens[1:]):
        return None
    return name
