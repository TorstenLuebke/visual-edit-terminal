"""Qt-freies VT/ANSI-Bildschirmmodell für ShellDeck (auf Basis von pyte).

Diese Ebene macht ShellDeck zu einem echten Terminal: Sie interpretiert die
vollständigen VT/ANSI-Sequenzen (Cursorbewegung, Farben, Löschen, Scroll-
Regionen, Alternate Screen …) und pflegt daraus ein Zellgitter. Der spätere
Qt-Renderer liest nur dieses Modell — hier gibt es bewusst keinerlei Qt-Bezug,
damit das Modell eigenständig und schnell testbar bleibt.

pyte ist eine optionale, reine Python-Abhängigkeit. Fehlt sie, meldet
``is_available()`` False und ShellDeck bleibt bei der bisherigen
Textdarstellung. Es werden beim Import keine Seiteneffekte ausgelöst.
"""

from __future__ import annotations

import codecs
from collections import deque
from typing import Dict, List, Optional

from shelldeck_scrollback import normalize_vt_scrollback_lines

try:  # pyte ist optional; der Import darf ShellDeck nie am Start hindern.
    import pyte
    _PYTE_IMPORT_ERROR = ""
except Exception as exc:  # pragma: no cover - haengt von der Umgebung ab
    pyte = None
    _PYTE_IMPORT_ERROR = str(exc)


def is_available() -> bool:
    """True, wenn pyte importierbar ist und echte Emulation möglich ist."""
    return pyte is not None


def availability_message() -> str:
    """Verständliche Meldung, warum die Emulation ggf. nicht verfügbar ist."""
    if pyte is not None:
        return ""
    return (
        "pyte ist nicht installiert. Fuer die echte Terminaldarstellung: "
        "python -m pip install pyte. Details: " + (_PYTE_IMPORT_ERROR or "")
    ).strip()


# Standardwerte, die pyte für „keine besondere Farbe" verwendet.
DEFAULT_FG = "default"
DEFAULT_BG = "default"


class _PrivateSgrCompatibility:
    """Schuetzt pyte gegen private CSI-SGR-Sequenzen (z.B. ESC[?4m).

    Einige pyte-Versionen reichen ``private=True`` vom Stream an
    ``select_graphic_rendition`` weiter, obwohl die Screen-Methode dieses
    Keyword nicht annimmt. Private SGR-Codes sind keine normalen Farb-/
    Textattribute und muessen ohne Aenderung des Bildschirms ignoriert werden.
    Die Mixin-Loesung aendert keine globalen pyte-Klassen.
    """

    def select_graphic_rendition(self, *attrs, private=False):
        if private:
            return None
        return super().select_graphic_rendition(*attrs)


if pyte is not None:
    class _CompatibleHistoryScreen(_PrivateSgrCompatibility, pyte.HistoryScreen):
        """pyte-HistoryScreen mit kompatibler Behandlung privater SGR-Codes."""

    class _CompatibleScreen(_PrivateSgrCompatibility, pyte.Screen):
        """pyte-Screen ohne History mit derselben SGR-Absicherung."""


class VtScreen:
    """Dünner, rendererfreundlicher Wrapper um pyte.

    Eingabe sind rohe PTY-Bytes (oder bereits dekodierter Text). Ausgabe ist
    ein Zellgitter mit Attributen, die Cursorposition und die Menge der seit
    dem letzten ``clear_dirty()`` veränderten Zeilen.
    """

    def __init__(self, rows: int = 24, cols: int = 80,
                 history: int = 2000, enable_history: bool = True):
        if pyte is None:
            raise RuntimeError(availability_message())
        self._rows = max(1, int(rows))
        self._cols = max(1, int(cols))
        self._history_limit = normalize_vt_scrollback_lines(history)
        if enable_history:
            # ratio bestimmt, wie viele Zeilen pro Seitenwechsel gescrollt
            # werden; history die Gesamttiefe des Scrollback-Puffers.
            self.screen = _CompatibleHistoryScreen(
                self._cols, self._rows,
                history=max(self._rows, self._history_limit), ratio=0.5,
            )
        else:
            self.screen = _CompatibleScreen(self._cols, self._rows)
        self.stream = pyte.Stream(self.screen)
        # Inkrementeller UTF-8-Dekoder: Mehrbyte-Zeichen dürfen über PTY-Lese-
        # grenzen hinweg zerteilt ankommen, ohne dass Ersatzzeichen entstehen.
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")

    # --- Eingabe ----------------------------------------------------------
    def feed(self, data) -> None:
        """Füttert rohe Bytes oder Text in die Emulation."""
        if isinstance(data, (bytes, bytearray)):
            text = self._decoder.decode(bytes(data))
        else:
            text = str(data or "")
        if text:
            self.stream.feed(text)

    # --- Geometrie --------------------------------------------------------
    def resize(self, rows: int, cols: int) -> bool:
        """Ändert die Gittergröße. Gibt True zurück, wenn sich etwas geändert hat."""
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        if rows == self._rows and cols == self._cols:
            return False
        self._rows, self._cols = rows, cols
        # pyte.Screen.resize erwartet (lines, columns) — andere Reihenfolge als
        # der Konstruktor (columns, lines).
        self.screen.resize(rows, cols)
        try:
            self.screen.dirty.update(range(rows))
        except Exception:
            pass
        return True

    @property
    def history_lines(self) -> int:
        """Konfigurierter VT-Verlauf (separat vom sichtbaren Zellgitter)."""
        return self._history_limit

    def set_history_lines(self, lines: int) -> bool:
        """Aendert die pyte-History im laufenden Betrieb ohne Bildschirm-Reset.

        pyte stellt dafuer derzeit keine oeffentliche Resize-Methode bereit.
        Wir ersetzen nur seine History-Namedtuple und die begrenzten Deques;
        Stream, Cursor, Farben und Screen.buffer bleiben unveraendert.
        Bei einem unbekannten History-Layout wird nichts geaendert.
        """
        history = getattr(self.screen, "history", None)
        if history is None or not hasattr(history, "_replace"):
            return False
        size = max(self._rows, normalize_vt_scrollback_lines(lines))
        if size == history.size:
            self._history_limit = normalize_vt_scrollback_lines(lines)
            return False
        if not isinstance(history.top, deque) or not isinstance(history.bottom, deque):
            return False
        # Die oberen Zeilen sind chronologisch: beim Schrumpfen die juengsten
        # behalten. Beim Zurueckblaettern liegt in 'bottom' die Zukunft;
        # dort muessen die naechsten (linken) Zeilen erhalten bleiben.
        top = deque(history.top, maxlen=max(1, size // 2))
        bottom = deque(list(history.bottom)[:size], maxlen=size)
        distance = max(0, int(history.size) - int(history.position))
        position = max(0, size - min(size, distance))
        self.screen.history = history._replace(
            top=top, bottom=bottom, size=size, position=position,
        )
        self._history_limit = normalize_vt_scrollback_lines(lines)
        self.screen.dirty.update(range(self._rows))
        return True

    @property
    def rows(self) -> int:
        return self._rows

    @property
    def cols(self) -> int:
        return self._cols

    # --- Ausgabe/Zustand --------------------------------------------------
    @property
    def cursor(self) -> Dict[str, int]:
        cur = self.screen.cursor
        return {
            "x": int(getattr(cur, "x", 0)),
            "y": int(getattr(cur, "y", 0)),
            "hidden": bool(getattr(cur, "hidden", False)),
        }

    def display(self) -> List[str]:
        """Sichtbarer Bildschirm als Liste von Zeilen-Strings."""
        return list(self.screen.display)

    def dirty_lines(self) -> List[int]:
        """Seit dem letzten clear_dirty() veränderte Zeilenindizes."""
        return sorted(int(y) for y in self.screen.dirty)

    def clear_dirty(self) -> None:
        self.screen.dirty.clear()

    def row_cells(self, y: int) -> List[Dict]:
        """Eine Zeile als Liste von Zell-Dicts (Zeichen + Attribute).

        Unberührte Zellen liefern ein Leerzeichen mit Standardattributen, damit
        der Renderer immer genau ``cols`` Zellen je Zeile erhält.
        """
        y = int(y)
        row = self.screen.buffer[y]
        cells: List[Dict] = []
        for x in range(self._cols):
            ch = row[x]
            cells.append({
                "char": (ch.data or " "),
                "fg": ch.fg or DEFAULT_FG,
                "bg": ch.bg or DEFAULT_BG,
                "bold": bool(ch.bold),
                "italics": bool(ch.italics),
                "underscore": bool(ch.underscore),
                "strikethrough": bool(ch.strikethrough),
                "reverse": bool(ch.reverse),
                "blink": bool(ch.blink),
            })
        return cells

    def reset(self) -> None:
        """Setzt den Bildschirm zurück (wie ein frisch gestartetes Terminal)."""
        self.screen.reset()

    # --- Terminalmodi (fuer korrekte Tastencodierung) ---------------------
    def application_cursor_keys(self) -> bool:
        """True, wenn DECCKM aktiv ist (Programme erwarten \\x1bO statt \\x1b[)."""
        mode = getattr(self.screen, "mode", set())
        # pyte legt private Modi als (n << 5) ab; DECCKM ist Modus 1.
        return (1 << 5) in mode or 1 in mode

    def bracketed_paste(self) -> bool:
        """True, wenn der Bracketed-Paste-Modus (2004) aktiv ist."""
        mode = getattr(self.screen, "mode", set())
        return (2004 << 5) in mode or 2004 in mode

    # --- Scrollback (optional, nur bei HistoryScreen) ---------------------
    def has_history(self) -> bool:
        return hasattr(self.screen, "history")

    def scroll_history(self, direction: str) -> bool:
        """Blättert im Scrollback (nur HistoryScreen). direction: 'up'|'down'."""
        if direction == "up" and hasattr(self.screen, "prev_page"):
            self.screen.prev_page()
            return True
        if direction == "down" and hasattr(self.screen, "next_page"):
            self.screen.next_page()
            return True
        return False
