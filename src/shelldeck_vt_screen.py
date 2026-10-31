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
from collections import deque, defaultdict
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


def _is_default_blank_cell(cell):
    """True for a plain, unstyled space, including pyte's resize padding.

    pyte may materialize implicit empty cells when the viewport is resized or
    repainted.  A sparse row's highest *stored* column therefore is not a
    reliable measure of how much text was actually written there.  Styled
    spaces remain significant, as do any spaces inside a logical text line.
    """
    data = getattr(cell, "data", cell if isinstance(cell, str) else None)
    if data not in (" ", "", None):
        return False
    if getattr(cell, "fg", "default") not in ("default", "", None):
        return False
    if getattr(cell, "bg", "default") not in ("default", "", None):
        return False
    return not any(bool(getattr(cell, attr, False)) for attr in (
        "bold", "italics", "underscore", "strikethrough", "reverse", "blink"
    ))


def _row_has_text_cells(row):
    """Do not mistake only-blank, materialized pyte rows for real output."""
    return any(not _is_default_blank_cell(cell) for cell in row.values())


def _reflow_logical_rows(rows, old_cols, new_cols, soft_wrap_ids,
                         cursor_row, cursor_x):
    """Rewrap sparse VT cells, retaining Char objects and real line breaks.

    `soft_wrap_ids` contains IDs of the *row objects* (not y coordinates):
    pyte moves row objects when scrolling. Only rows joined by automatic
    wrapping are merged; explicit CR/LF still denote separate logical lines.
    The function itself is pyte-/Qt-free, allowing isolated regression tests.
    """
    out = []
    out_soft = set()
    cursor_out = None
    segment = {}
    length = 0
    segment_cursor = None

    def flush():
        nonlocal segment, length, segment_cursor, cursor_out
        count = max(1, (length + new_cols - 1) // new_cols)
        start = len(out)
        for part in range(count):
            left = part * new_cols
            out.append({x - left: char for x, char in segment.items()
                        if left <= x < left + new_cols})
            if part + 1 < count:
                out_soft.add(start + part)
        if segment_cursor is not None:
            offset = segment_cursor
            # A cursor after the final cell is pending autowrap. It belongs
            # to the previous row at x == columns, not the next blank row.
            if offset and offset % new_cols == 0:
                cursor_out = (start + offset // new_cols - 1, new_cols)
            else:
                cursor_out = (start + offset // new_cols, offset % new_cols)
        segment, length, segment_cursor = {}, 0, None

    for index, row in enumerate(rows):
        positions = {x: char for x, char in row.items()
                     if isinstance(x, int) and 0 <= x < old_cols}
        # A pyte row can contain default blank cells right up to the current
        # right margin even when nothing was printed there.  Counting those
        # cells makes each tiny drag step append another apparent line; after
        # enough steps the shell output scrolls entirely off the viewport.
        used = max((x + 1 for x, cell in positions.items()
                    if not _is_default_blank_cell(cell)), default=0)
        wrapped = id(row) in soft_wrap_ids
        if wrapped:
            # A true soft wrap is a full physical row, including deliberate
            # spaces before the continuation on the following row.
            used = max(used, old_cols)
        if index == cursor_row:
            used = max(used, max(0, min(old_cols, int(cursor_x))))
            segment_cursor = length + max(0, min(old_cols, int(cursor_x)))
        # Never copy trailing synthetic padding into the next logical line.
        # Interior default spaces are still kept to preserve layout.
        segment.update({length + x: char for x, char in positions.items()
                        if x < used})
        length += used
        if not wrapped:
            flush()
    if length or segment_cursor is not None:
        flush()
    return out, out_soft, cursor_out


if pyte is not None:
    class _SoftWrapTracking:
        """Record natural wraps without confusing them with hard newlines.

        Track row identities so regular scrolling and HistoryScreen's row
        transfers keep their wrap metadata. There is no global pyte patch.
        """

        def draw(self, data):
            # Stream normally delivers a single printable character. Handle
            # longer chunks as well, to catch wraps in the middle of a chunk.
            clusters = getattr(pyte.screens, "grapheme_clusters", None)
            for character in (clusters(data) if callable(clusters) else data):
                if (self.cursor.x == self.columns
                        and pyte.modes.DECAWM in self.mode):
                    previous = self.buffer[self.cursor.y]
                    wraps = getattr(self, "_shelldeck_softwrap_rows", None)
                    if wraps is None:
                        wraps = self._shelldeck_softwrap_rows = {}
                    wraps[id(previous)] = previous
                    # A long-running shell must not retain unbounded, already
                    # scrolled-away row objects through the wrap metadata.
                    if len(wraps) > 2400:
                        wraps.pop(next(iter(wraps)))
                super().draw(character)

        def reset(self):
            self._shelldeck_softwrap_rows = {}
            return super().reset()

        def erase_in_display(self, *args, **kwargs):
            # An explicitly erased screen is no longer one continuous line.
            self._shelldeck_softwrap_rows = {}
            return super().erase_in_display(*args, **kwargs)

        def erase_in_line(self, *args, **kwargs):
            wraps = getattr(self, "_shelldeck_softwrap_rows", None)
            if wraps is not None:
                row = self.buffer.get(self.cursor.y)
                if row is not None:
                    wraps.pop(id(row), None)
            return super().erase_in_line(*args, **kwargs)

    class _RegionScrollCompatibility:
        """Move actual cell rows for SU/SD inside DECSTBM (zero-based margins).

        The default pyte scrolling behavior differs from the VT reference for
        a partially populated scrolling region. Keep this workaround local to
        ShellDeck's alternate screen; the history-enabled shell is unchanged.
        Scrolls move *row buffers*, including styling, not rendered strings.
        """

        def _region_bounds(self):
            margins = self.margins
            if margins is None:
                return 0, self.lines - 1
            top = max(0, int(margins.top))
            bottom = min(self.lines - 1, int(margins.bottom))
            return top, bottom

        @staticmethod
        def _scroll_count(count, height):
            # CSI 0 S / CSI 0 T mean one line, just as omitted parameters do.
            amount = 1 if not count else int(count)
            return min(max(1, amount), height)

        def scroll_up(self, count=None):
            top, bottom = self._region_bounds()
            if bottom < top:
                return
            count = self._scroll_count(count, bottom - top + 1)
            old = {y: self.buffer.get(y) for y in range(top, bottom + 1)}
            for y in range(top, bottom + 1):
                source = y + count
                if source <= bottom and old[source] is not None:
                    self.buffer[y] = old[source]
                else:
                    self.buffer.pop(y, None)
            self.dirty.update(range(top, bottom + 1))

        def scroll_down(self, count=None):
            top, bottom = self._region_bounds()
            if bottom < top:
                return
            count = self._scroll_count(count, bottom - top + 1)
            old = {y: self.buffer.get(y) for y in range(top, bottom + 1)}
            for y in range(top, bottom + 1):
                source = y - count
                if source >= top and old[source] is not None:
                    self.buffer[y] = old[source]
                else:
                    self.buffer.pop(y, None)
            self.dirty.update(range(top, bottom + 1))

    class _CompatibleHistoryScreen(_SoftWrapTracking, _RegionScrollCompatibility, _PrivateSgrCompatibility, pyte.HistoryScreen):
        """Normal VT screen with history and explicit SU/SD support."""

    class _CompatibleScreen(_SoftWrapTracking, _RegionScrollCompatibility, _PrivateSgrCompatibility, pyte.Screen):
        """Alternate VT screen with isolated scroll-region and SGR fixes."""

    class _CompatibleStream(pyte.Stream):
        """Recognize SU/SD CSI commands absent from pyte's default CSI table.

        Use a subclass-local dispatch table; never mutate pyte.Stream.csi
        globally, because other applications can use pyte in this process.
        """
        csi = dict(pyte.Stream.csi, S="scroll_up", T="scroll_down")


class _ScreenBuffers:
    """Stable pyte event receiver for main and alternate VT screens.

    A single Stream must parse CSI commands across PTY read boundaries.  It
    therefore keeps one listener for its entire lifetime; changing that
    listener when receiving CSI ?1049h would reset the parser mid-stream.
    Stream binds event callables at construction time, so __getattr__ supplies
    late-dispatching methods that always target the currently active screen.
    """

    _ALT_CODES = frozenset((47, 1047, 1049))

    def __init__(self, normal, alternate):
        self.normal = normal
        self.alternate = alternate
        self._active = normal
        self._alt_modes = set()
        self._alt_was_used = False

    @property
    def alternate_active(self) -> bool:
        return self._active is self.alternate

    @property
    def history(self):
        # All saved history belongs to the normal screen, never the TUI.
        return getattr(self.normal, "history")

    @history.setter
    def history(self, value):
        self.normal.history = value

    def __getattr__(self, name):
        value = getattr(self._active, name)
        if not callable(value):
            return value

        def dispatch(*args, **kwargs):
            return getattr(self._active, name)(*args, **kwargs)
        return dispatch

    def set_mode(self, *modes, **kwargs):
        requested = self._ALT_CODES.intersection(modes) if kwargs.get("private") else set()
        if requested and not self.alternate_active:
            # DECSET 47 retains the old alternate contents; 1047 and 1049
            # start with an empty alternate viewport. A newly created buffer
            # is empty in either case.
            if not self._alt_was_used or requested.intersection((1047, 1049)):
                self.alternate.reset()
            self._alt_was_used = True
            # Keep global modes (e.g. DECCKM) active on entry, but isolate
            # subsequent changes from the normal shell's saved screen.
            self.alternate.mode.update(self.normal.mode)
            self._active = self.alternate
            self.alternate.dirty.update(range(self.alternate.lines))
        self._alt_modes.update(requested)
        self._active.set_mode(*modes, **kwargs)

    def reset_mode(self, *modes, **kwargs):
        requested = self._ALT_CODES.intersection(modes) if kwargs.get("private") else set()
        self._active.reset_mode(*modes, **kwargs)
        if requested:
            self._alt_modes.difference_update(requested)
            if not self._alt_modes and self.alternate_active:
                self._active = self.normal
                self.normal.dirty.update(range(self.normal.lines))

    def reset(self):
        self.normal.reset()
        self.alternate.reset()
        self._active = self.normal
        self._alt_modes.clear()
        self._alt_was_used = False

    @staticmethod
    def _resize_screen_with_tabs(screen, lines, columns):
        """Extend default tab stops after a terminal grows horizontally.

        pyte can keep the stops from an earlier, narrower geometry. With a
        missing stop, HT jumps to the last column and splits the following
        word across the right edge (observed with GNU ls column output).
        Preserve existing/custom stops; only populate newly exposed columns.
        """
        old_columns = int(screen.columns)
        # pyte drops cells beyond the new right margin permanently. Keep a
        # bounded, screen-local backup of those cells for simple resize replay.
        # This is NOT reflow: if terminal output arrives while narrowed, the
        # backup is invalidated rather than risking resurrection of stale text.
        tails = getattr(screen, "_shelldeck_resize_tails", None)
        if tails is None:
            tails = {}
        if columns < old_columns:
            for y, row in list(screen.buffer.items()):
                if not 0 <= y < min(int(lines), int(screen.lines)):
                    continue
                discarded = {x: cell for x, cell in row.items()
                             if isinstance(x, int) and columns <= x < old_columns}
                if discarded:
                    tails.setdefault(y, {}).update(discarded)
        screen.resize(lines, columns)
        if columns > old_columns and tails:
            for y, cells in list(tails.items()):
                if not 0 <= y < int(lines):
                    tails.pop(y, None)
                    continue
                visible = {x: cell for x, cell in cells.items() if x < columns}
                if visible:
                    screen.buffer[y].update(visible)
                    screen.dirty.add(y)
                    for x in visible:
                        cells.pop(x, None)
                if not cells:
                    tails.pop(y, None)
        screen._shelldeck_resize_tails = tails
        if columns > old_columns:
            stops = getattr(screen, "tabstops", None)
            if stops is not None:
                first = ((old_columns // 8) + 1) * 8
                # Include a newly exposed stop exactly at old_columns when
                # the old geometry ended on an 8-column boundary.
                if old_columns % 8 == 0:
                    first = old_columns
                stops.update(range(first, columns, 8))

    def resize(self, lines, columns):
        # Even a hidden screen needs the new geometry before it is restored.
        self._resize_screen_with_tabs(self.normal, lines, columns)
        self._resize_screen_with_tabs(self.alternate, lines, columns)
        self._active.dirty.update(range(lines))


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
            # Verlauf ausschliesslich auf dem normalen Bildschirm speichern.
            main_screen = _CompatibleHistoryScreen(
                self._cols, self._rows,
                history=max(self._rows, self._history_limit), ratio=0.5,
            )
        else:
            main_screen = _CompatibleScreen(self._cols, self._rows)
        self.screen = _ScreenBuffers(
            normal=main_screen,
            alternate=_CompatibleScreen(self._cols, self._rows),
        )
        self.stream = _CompatibleStream(self.screen)
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
            # Any PTY output may modify cells or scroll rows. Never restore a
            # saved horizontal tail after content may have changed.
            self.screen.normal._shelldeck_resize_tails = {}
            self.screen.alternate._shelldeck_resize_tails = {}
            self.stream.feed(text)

    # --- Geometrie --------------------------------------------------------
    @staticmethod
    def _make_row(template, cells):
        """Construct pyte-compatible sparse rows across pyte 0.8+ versions."""
        if hasattr(template, "default"):
            row = type(template)(template.default)
        elif isinstance(template, defaultdict):
            row = defaultdict(template.default_factory)
        else:
            row = type(template)()
        row.update(cells)
        return row

    def _reflow_main_screen(self, rows, cols):
        """Reconstruct normal-screen text for a new width, before pyte clips it.

        Do not reorder application/TUI screens, custom scrolling regions or a
        scrolled-back history viewport: their cursor addressing is absolute.
        """
        normal = self.screen.normal
        history = getattr(normal, "history", None)
        if (self.screen.alternate_active or normal.margins is not None
                or (history is not None and history.bottom)):
            return None
        past = list(history.top) if history is not None else []
        # Large histories must not freeze Qt during interactive window drags.
        older = past[:-2000]
        past = past[-2000:]
        visible = [normal.buffer[y] for y in range(self._rows)]
        # Mere presence of default blank cells is *not* evidence of output.
        # Otherwise the growing, empty lower viewport is repeatedly reflowed
        # and pushes actual command output into scrollback on every resize.
        last = max((i for i, line in enumerate(visible)
                    if _row_has_text_cells(line)), default=-1)
        last = max(last, min(self._rows - 1, int(normal.cursor.y)))
        source = past + visible[:last + 1]
        wraps = getattr(normal, "_shelldeck_softwrap_rows", {})
        cursor_row = len(past) + min(self._rows - 1, int(normal.cursor.y))
        return (older, *_reflow_logical_rows(source, self._cols, cols, wraps,
                                             cursor_row, int(normal.cursor.x)))

    def _apply_main_reflow(self, result, rows):
        """Replace text rows after resizing pyte's own geometry and modes."""
        older, lines, soft_indices, cursor = result
        normal = self.screen.normal
        history = getattr(normal, "history", None)
        split = max(0, len(lines) - rows)
        top_lines = older + lines[:split]
        visible_lines = lines[split:]
        sample = normal.buffer[0]
        normal.buffer.clear()
        rows_by_index = {}
        for index, cells in enumerate(visible_lines):
            row = self._make_row(sample, cells)
            normal.buffer[index] = row
            rows_by_index[split + index] = row
        if history is not None:
            new_top = [self._make_row(sample, cells) for cells in lines[:split]]
            for index, row in enumerate(new_top):
                rows_by_index[index] = row
            history.top.clear()
            history.top.extend(older)
            history.top.extend(new_top)
        normal._shelldeck_softwrap_rows = {
            id(rows_by_index[i]): rows_by_index[i] for i in soft_indices
            if i in rows_by_index
        }
        normal._shelldeck_resize_tails = {}
        if cursor is not None:
            y, x = cursor
            normal.cursor.y = max(0, min(rows - 1, y - split))
            normal.cursor.x = max(0, min(normal.columns, x))
        normal.dirty.update(range(rows))

    def resize(self, rows: int, cols: int) -> bool:
        """Ändert die Gittergröße. Gibt True zurück, wenn sich etwas geändert hat."""
        rows = max(1, int(rows))
        cols = max(1, int(cols))
        if rows == self._rows and cols == self._cols:
            return False
        # Reflow uses original cell objects. pyte.Screen.resize would clip
        # them irretrievably before we could split the logical text lines.
        reflow = self._reflow_main_screen(rows, cols) if cols != self._cols else None
        self._rows, self._cols = rows, cols
        # pyte.Screen.resize erwartet (lines, columns) — andere Reihenfolge als
        # der Konstruktor (columns, lines).
        self.screen.resize(rows, cols)
        if reflow is not None:
            self._apply_main_reflow(reflow, rows)
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

    @staticmethod
    def _snapshot_line(row, columns: int) -> str:
        """Read pyte cells without advancing scrollback or touching screen state."""
        return "".join(
            getattr(row.get(x), "data", " ") or " " for x in range(columns)
        ).rstrip()

    def transcript_lines(self) -> List[str]:
        """Bounded normal-screen history plus viewport (no alternate TUI capture).

        pyte history.top is chronological. The active viewport may already be
        scrolled upwards, in which case history.bottom contains newer rows.
        These are copied, never consumed via prev_page/next_page.
        """
        normal = self.screen.normal
        history = getattr(normal, "history", None)
        top = list(history.top) if history is not None else []
        bottom = list(history.bottom) if history is not None else []
        visible = [normal.buffer[y] for y in range(self._rows)]
        return [self._snapshot_line(row, self._cols)
                for row in top + visible + bottom]

    def transcript_text(self) -> str:
        """Return the retained normal PTY scrollback and screen as plain text."""
        return "\n".join(self.transcript_lines()).rstrip("\n")

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

    def sgr_mouse_tracking_level(self) -> int:
        """Aktiven xterm-Mausmodus zurueckgeben, oder 0 (normale Auswahl).

        ShellDeck sendet nur SGR-1006-Mausberichte: traditionelle X10- und
        UTF-8-Koordinatenformate sind absichtlich nicht stillschweigend
        mit einem unpassenden Byteformat vermischt. Fuer 1000 gelten Klicks,
        fuer 1002 zusaetzlich Ziehen und fuer 1003 jede Mausbewegung.
        """
        modes = getattr(self.screen, "mode", set())
        def enabled(code):
            return (code << 5) in modes or code in modes
        if not enabled(1006):
            return 0
        for code in (1003, 1002, 1000):
            if enabled(code):
                return code
        return 0

    # --- Scrollback (optional, nur bei HistoryScreen) ---------------------
    def has_history(self) -> bool:
        return hasattr(self.screen, "history")

    def in_alternate_screen(self) -> bool:
        """True, while a full-screen TUI owns the separate VT viewport."""
        return bool(getattr(self.screen, "alternate_active", False))

    def alternate_scroll_mode(self) -> bool:
        """Xterm 1007 explicitly asks for wheel-to-cursor-key conversion."""
        modes = getattr(self.screen, "mode", set())
        return (1007 << 5) in modes or 1007 in modes

    def scroll_history(self, direction: str) -> bool:
        """Blättert im normalen Scrollback, niemals durch eine aktive TUI."""
        if self.in_alternate_screen():
            return False
        if direction == "up" and hasattr(self.screen, "prev_page"):
            self.screen.prev_page()
            return True
        if direction == "down" and hasattr(self.screen, "next_page"):
            self.screen.next_page()
            return True
        return False
