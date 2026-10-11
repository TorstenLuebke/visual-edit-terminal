"""Plattformunabhaengige Grenzen fuer die klassische QTextEdit-Ausgabe.

Der echte VT-Modus verwendet einen getrennten pyte-History-Puffer; seine
Speichergrenze wird hier bewusst nicht umgestellt.
"""

DEFAULT_SCROLLBACK_BLOCKS = 25000
MIN_SCROLLBACK_BLOCKS = 1000
MAX_SCROLLBACK_BLOCKS = 100000


def normalize_scrollback_blocks(value) -> int:
    """Einstellungen robust aus JSON und Qt-Dialogen einlesen."""
    try:
        size = int(value)
    except (TypeError, ValueError, OverflowError):
        size = DEFAULT_SCROLLBACK_BLOCKS
    return max(MIN_SCROLLBACK_BLOCKS, min(MAX_SCROLLBACK_BLOCKS, size))
