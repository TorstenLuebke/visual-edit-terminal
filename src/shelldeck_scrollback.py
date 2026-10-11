"""Plattformunabhaengige Scrollback-Grenzen fuer klassische und VT-Ansicht."""

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


# Die pyte-History ist eine Sammlung formatierter Terminalzellen und daher
# speicherintensiver als normale Textzeilen. Sie bleibt separat einstellbar.
DEFAULT_VT_SCROLLBACK_LINES = 2000
MIN_VT_SCROLLBACK_LINES = 100
MAX_VT_SCROLLBACK_LINES = 20000


def normalize_vt_scrollback_lines(value) -> int:
    """Begrenzt Einstellungen fuer den VT-Historienpuffer aus JSON/Dialogen."""
    try:
        size = int(value)
    except (TypeError, ValueError, OverflowError):
        size = DEFAULT_VT_SCROLLBACK_LINES
    return max(MIN_VT_SCROLLBACK_LINES, min(MAX_VT_SCROLLBACK_LINES, size))
