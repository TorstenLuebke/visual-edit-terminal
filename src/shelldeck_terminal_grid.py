"""Qt-Renderer für das VT-Bildschirmmodell (ShellDeck).

``TerminalGridView`` zeichnet das in ``shelldeck_vt_screen.VtScreen`` gepflegte
Zellgitter monospaced: Hintergrundfarben, Vorder-/Attributdarstellung
(fett, kursiv, unterstrichen, durchgestrichen, invertiert) und einen echten
Cursor. In dieser Ausbaustufe ist es reine Anzeige — Tastatur-/Mauseingabe
folgt in einem eigenen Schritt.

Die Terminalgröße ist an dieses Widget gekoppelt: Aus Widgetgröße und
Schriftmetrik werden Zeilen/Spalten berechnet, das Modell entsprechend
skaliert und über das Signal ``sizeChanged(rows, cols)`` gemeldet, damit der
Host die PTY-Fenstergröße (TIOCSWINSZ) nachziehen kann.

Der Import ist so gestaltet, dass er ohne pyte nicht scheitert; ``is_usable()``
zeigt an, ob echte Terminaldarstellung möglich ist.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Dict, Optional

from PySide6.QtCore import Qt, QRect, QRectF, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QMenu, QWidget

from shelldeck_scrollback import normalize_vt_scrollback_lines

import shelldeck_key_encoding as keyenc
from shelldeck_mouse_protocol import encode_sgr_mouse
import shelldeck_vt_screen as vt


def _build_key_name_map():
    """Qt.Key -> abstrakter Tastenname für den Qt-freien Encoder."""
    K = Qt.Key
    names = {
        K.Key_Up: "Up", K.Key_Down: "Down", K.Key_Left: "Left", K.Key_Right: "Right",
        K.Key_Home: "Home", K.Key_End: "End", K.Key_PageUp: "PageUp",
        K.Key_PageDown: "PageDown", K.Key_Insert: "Insert", K.Key_Delete: "Delete",
        K.Key_Return: "Enter", K.Key_Enter: "Enter", K.Key_Backspace: "Backspace",
        K.Key_Tab: "Tab", K.Key_Backtab: "Backtab", K.Key_Escape: "Escape",
    }
    for i in range(1, 13):
        names[getattr(K, "Key_F%d" % i)] = "F%d" % i
    return names


_KEY_NAMES = _build_key_name_map()


# Standard-xterm-Palette (16 Farben). pyte liefert Farbnamen wie "red" oder
# "brightred"; 256-/Truecolor kommt als 6-stelliger Hex-String an.
_ANSI_PALETTE = {
    "black": "#000000", "red": "#cd0000", "green": "#00cd00",
    "brown": "#cdcd00", "yellow": "#cdcd00", "blue": "#6c9fff",
    "magenta": "#cd00cd", "cyan": "#00cdcd", "white": "#e5e5e5",
    "brightblack": "#7f7f7f", "brightred": "#ff0000", "brightgreen": "#00ff00",
    "brightbrown": "#ffff00", "brightyellow": "#ffff00", "brightblue": "#9fc2ff",
    "brightmagenta": "#ff00ff", "brightcyan": "#00ffff", "brightwhite": "#ffffff",
}
_HEXDIGITS = set("0123456789abcdefABCDEF")


@lru_cache(maxsize=256)
def _cached_terminal_color(value: str) -> QColor:
    """Cache limited to 256 explicit colors, including RGB/ANSI palette values.

    Truecolor input can contain millions of unique values, so the cache must
    not grow without bound. Default/theme colors are handled by the widget.
    """
    hexname = _ANSI_PALETTE.get(value.lower())
    if hexname:
        return QColor(hexname)
    if len(value) == 6 and all(c in _HEXDIGITS for c in value):
        return QColor("#" + value)
    return QColor(value)


def _coalesce_dirty_rows(rows, row_count: int):
    """Combine changed VT rows into inclusive intervals, ignoring invalid rows."""
    valid = sorted({int(y) for y in rows if 0 <= int(y) < row_count})
    if not valid:
        return []
    spans = []
    start = end = valid[0]
    for y in valid[1:]:
        if y == end + 1:
            end = y
        else:
            spans.append((start, end))
            start = end = y
    spans.append((start, end))
    return spans


class TerminalGridView(QWidget):
    """Rendert ein VtScreen-Modell als monospaced Terminalgitter."""

    # (rows, cols) – wird bei jeder Größenänderung des Gitters gemeldet.
    sizeChanged = Signal(int, int)
    # An das PTY zu sendende Eingabebytes (Tastatur/Paste). Der Host verbindet
    # dieses Signal mit dem Schreiben in den Terminal-Prozess.
    dataReady = Signal(object)

    def __init__(self, parent=None, rows: int = 24, cols: int = 80,
                 font: Optional[QFont] = None, enable_history: bool = True,
                 history: int = 2000):
        super().__init__(parent)
        self._model = vt.VtScreen(rows=rows, cols=cols,
                                  enable_history=enable_history, history=history) \
            if vt.is_available() else None

        base_font = font or QFont("Monospace", 11)
        base_font.setStyleHint(QFont.StyleHint.TypeWriter)
        base_font.setFixedPitch(True)
        self._font = base_font
        # Only 16 combinations of bold/italic/underline/strikethrough exist.
        # Avoid constructing a new QFont for every printed character.
        self._glyph_fonts = {}

        # Farbschema (kann vom ShellDeck-Theme gesetzt werden).
        self.default_fg = QColor("#d0d0d0")
        self.default_bg = QColor("#1e1e1e")
        self.selection_bg = QColor("#264f78")

        # Auswahlzustand (Zeile, Spalte), jeweils inklusive.
        self._sel_anchor = None
        self._sel_head = None
        self._local_mouse_selection = False

        self._cell_w = 1.0
        self._cell_h = 1.0
        self._ascent = 0.0
        self._last_cursor = None

        from shelldeck_vt_trace import VtRawTrace
        self._vt_raw_trace = VtRawTrace()
        self._vt_trace_start_snapshot = None
        self._vt_trace_start_geometry = None
        self._cursor_visible_phase = True
        self.cursor_blink = True
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(530)
        self._blink_timer.timeout.connect(self._toggle_cursor_phase)

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._recompute_metrics()

    # --- Verfügbarkeit ----------------------------------------------------
    def is_usable(self) -> bool:
        """True, wenn ein echtes VT-Modell vorhanden ist (pyte installiert)."""
        return self._model is not None

    def model(self) -> Optional[vt.VtScreen]:
        return self._model

    def set_history_lines(self, lines: int) -> bool:
        """Aendert die Scrollback-Grenze, ohne das sichtbare Gitter zu loeschen."""
        if self._model is None or not self._model.has_history():
            return False
        changed = self._model.set_history_lines(normalize_vt_scrollback_lines(lines))
        if changed:
            self.update()
        return changed

    # --- Schrift/Metrik ---------------------------------------------------
    def setFont(self, font: QFont) -> None:  # noqa: N802 (Qt-Namenskonvention)
        font.setFixedPitch(True)
        super().setFont(font)
        self._font = font
        self._glyph_fonts.clear()
        self._recompute_metrics()
        self._apply_grid_from_size()
        self.update()

    def _recompute_metrics(self) -> None:
        metrics = QFontMetricsF(self._font)
        # Monospace: horizontalAdvance("M") ist die Zellbreite.
        self._cell_w = max(1.0, metrics.horizontalAdvance("M") or metrics.averageCharWidth() or 8.0)
        self._cell_h = max(1.0, metrics.lineSpacing() or metrics.height() or 16.0)
        self._ascent = metrics.ascent()

    def cell_size(self):
        return self._cell_w, self._cell_h

    def cursor_diagnostic(self):
        """Content-free cursor geometry snapshot for VT/UI debugging.

        Never record surrounding terminal text or user input. This reports
        only the parser coordinates and pixel location used by the painter.
        """
        if self._model is None:
            return None
        state = self._model.cursor
        x, y = int(state["x"]), int(state["y"])
        return {
            "x": x, "y": y,
            "rows": int(self._model.rows), "cols": int(self._model.cols),
            "cell_width": float(self._cell_w),
            "cell_height": float(self._cell_h),
            "paint_x": int(x * self._cell_w),
            "paint_y": int(y * self._cell_h),
            "focus": bool(self.hasFocus()),
            "hidden": bool(state.get("hidden", False)),
        }

    # --- Datenzufuhr ------------------------------------------------------
    def feed(self, data) -> None:
        """Rohbytes/Text in das Modell geben und betroffene Zeilen neu zeichnen."""
        if self._model is None:
            return
        self._vt_raw_trace.append(data)
        self._model.feed(data)
        # Readline may erase a longer command with CSI K after moving the
        # cursor. Repaint the whole shell grid for erasure sequences only;
        # ordinary output keeps the fast, sparse dirty-row updates.
        raw = data if isinstance(data, bytes) else str(data).encode("utf-8", "replace")
        redraw_with_erase = b"\x1b[K" in raw or any(
            b"\x1b[" + n + b"K" in raw for n in (b"0", b"1", b"2")
        )
        self._repaint_dirty(force_shell_full=redraw_with_erase)

    def reset(self) -> None:
        if self._model is not None:
            self._model.reset()
        self.update()

    def _repaint_dirty(self, *, force_shell_full: bool = False) -> None:
        if self._model is None:
            return
        dirty = set(self._model.dirty_lines())
        cursor = self._model.cursor
        cursor_state = (cursor.get("x", 0), cursor.get("y", 0),
                        cursor.get("hidden", False))
        if cursor_state != self._last_cursor:
            # Even pure cursor-movement sequences must redraw the old/new
            # cursor cells, including movement within the same row.
            dirty.add(cursor_state[1])
            if self._last_cursor is not None:
                dirty.add(self._last_cursor[1])
        self._last_cursor = cursor_state
        self._model.clear_dirty()
        if force_shell_full and not self._model.in_alternate_screen():
            # Erasing a long Readline entry must not leave old glyphs in
            # regions missed by sparse Qt updates. Keep this exceptional.
            self.update()
            return
        if self._model.in_alternate_screen():
            # Vollbildprogramme (htop/vim/mc) zeichnen viele getrennte Bereiche
            # eines Frames gleichzeitig um, teils mit DECSTBM-Scrollregionen.
            # pytes Dirty-Zeilen beschreiben nicht in allen Faellen den ganzen
            # sichtbaren Veraenderungsbereich. Ein unvollstaendiger Qt-Repaint
            # laesst sonst alte Glyphen mitten in der Prozessliste stehen.
            # QWidget.update() fasst Aufrufe bis zum naechsten Paint-Event
            # zusammen. Der schnelle partielle Pfad fuer Shell/Scrollback
            # bleibt unten unveraendert.
            self.update()
            return
        spans = _coalesce_dirty_rows(dirty, self._model.rows)
        if not spans:
            return
        # Avoid a storm of repaint requests for heavily fragmented updates.
        if len(spans) > 8 or sum(end - start + 1 for start, end in spans) > self._model.rows // 2:
            spans = [(spans[0][0], spans[-1][1])]
        for top, bottom in spans:
            y_px = int(top * self._cell_h)
            h_px = int((bottom - top + 1) * self._cell_h) + 1
            self.update(0, y_px, self.width(), h_px)

    # --- Geometrie --------------------------------------------------------
    def _grid_size_for(self, width: int, height: int):
        cols = max(1, int(width // self._cell_w))
        rows = max(1, int(height // self._cell_h))
        return rows, cols

    def _apply_grid_from_size(self) -> None:
        if self._model is None:
            return
        rows, cols = self._grid_size_for(self.width(), self.height())
        old_rows, old_cols = self._model.rows, self._model.cols
        if self._model.resize(rows, cols):
            self.trace_event("grid_cells_changed", old_rows=old_rows, old_cols=old_cols,
                             rows=rows, cols=cols)
            # Bei einer veraenderten Zellgeometrie sind alle Zeilen neu zu
            # zeichnen, nicht nur die von Qt neu freigelegte Fensterregion.
            self._last_cursor = None
            self.update()
            self.sizeChanged.emit(rows, cols)

    def resizeEvent(self, event) -> None:
        self.trace_event("grid_widget_resize", width=self.width(), height=self.height())
        super().resizeEvent(event)
        self._apply_grid_from_size()

    def sizeHint(self) -> QSize:
        if self._model is None:
            return QSize(640, 384)
        return QSize(int(self._model.cols * self._cell_w),
                     int(self._model.rows * self._cell_h))

    # --- Fokus/Cursor-Blinken --------------------------------------------
    def focusInEvent(self, event) -> None:
        self.trace_event("grid_focus_in")
        super().focusInEvent(event)
        if self.cursor_blink:
            self._cursor_visible_phase = True
            self._blink_timer.start()
        self.update()

    def focusOutEvent(self, event) -> None:
        self.trace_event("grid_focus_out")
        super().focusOutEvent(event)
        self._blink_timer.stop()
        self._cursor_visible_phase = True
        self.update()

    def _toggle_cursor_phase(self) -> None:
        self._cursor_visible_phase = not self._cursor_visible_phase
        if self._model is None:
            return
        cur = self._model.cursor
        rect = QRect(int(cur["x"] * self._cell_w), int(cur["y"] * self._cell_h),
                     int(self._cell_w) + 1, int(self._cell_h) + 1)
        self.update(rect)

    # --- Scrollback (Mausrad) --------------------------------------------
    def wheelEvent(self, event) -> None:
        # In einem TUI mit aktivierter xterm-Maussteuerung gehoert das Rad
        # dem Programm, nicht dem pyte-Verlauf. Umschalt erzwingt Scrollback.
        delta = event.angleDelta().y()
        if self._mouse_tracking_level() and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            if delta:
                count = min(8, max(1, abs(delta) // 120))
                kind = "wheel_up" if delta > 0 else "wheel_down"
                for _ in range(count):
                    self._send_sgr_mouse(kind, event)
            event.accept()
            return
        if self._model is not None and self._model.in_alternate_screen():
            # A TUI renders its own viewport. Paging pyte.HistoryScreen here
            # would mix saved shell lines with htop/vim's live screen.
            # Xterm 1007 may instead request cursor keys for wheel events.
            if delta and self._model.alternate_scroll_mode() and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                key = b"\x1b[A" if delta > 0 else b"\x1b[B"
                steps = min(8, max(1, abs(delta) // 120))
                self.dataReady.emit(key * steps)
            event.accept()
            return
        if self._model is None or not self._model.has_history():
            super().wheelEvent(event)
            return
        if delta > 0:
            self._model.scroll_history("up")
        elif delta < 0:
            self._model.scroll_history("down")
        self.update()
        event.accept()

    # --- Farbauflösung ----------------------------------------------------
    def _resolve_color(self, value, default: QColor) -> QColor:
        if not value or value == "default":
            return default
        color = _cached_terminal_color(str(value))
        return color if color.isValid() else default

    def _font_for_cell(self, cell: Dict) -> QFont:
        """Return a reused font for the four terminal text attributes."""
        key = (bool(cell["bold"]), bool(cell["italics"]),
               bool(cell["underscore"]), bool(cell["strikethrough"]))
        result = self._glyph_fonts.get(key)
        if result is None:
            result = QFont(self._font)
            result.setBold(key[0])
            result.setItalic(key[1])
            result.setUnderline(key[2])
            result.setStrikeOut(key[3])
            self._glyph_fonts[key] = result
        return result

    # --- Tastatureingabe --------------------------------------------------
    def keyPressEvent(self, event) -> None:
        if self._model is None:
            super().keyPressEvent(event)
            return
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
        key = event.key()

        # Copy/Paste-Kurzbefehle zuerst (Terminal-Konvention: Ctrl+Shift+C/V).
        if ctrl and shift and key == Qt.Key.Key_C:
            self.copy_selection()
            event.accept()
            return
        if ctrl and shift and key == Qt.Key.Key_V:
            self.paste_clipboard()
            event.accept()
            return
        # Verbreitete zusaetzliche Terminal-Kuerzel. Ctrl+V bleibt beim
        # laufenden Programm (z. B. vim: Literal-Insert).
        if ctrl and not shift and key == Qt.Key.Key_Insert:
            self.copy_selection()
            event.accept()
            return
        if shift and not ctrl and key == Qt.Key.Key_Insert:
            self.paste_clipboard()
            event.accept()
            return

        # Reine Modifiertasten erzeugen keine Ausgabe.
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt,
                   Qt.Key.Key_Meta, Qt.Key.Key_AltGr):
            super().keyPressEvent(event)
            return

        name = _KEY_NAMES.get(key, "")
        text = event.text()
        # Manche Plattformen liefern bei Ctrl+Buchstabe keinen Text -> aus der
        # Taste rekonstruieren, damit die Ctrl-Codierung greift.
        if not name and ctrl and not text and Qt.Key.Key_A <= key <= Qt.Key.Key_Z:
            text = chr(key)

        data = keyenc.encode_key(
            name, text, ctrl=ctrl, alt=alt, shift=shift, meta=meta,
            application_cursor=self._model.application_cursor_keys(),
        )
        if data:
            self.dataReady.emit(bytes(data))
            event.accept()
        else:
            super().keyPressEvent(event)

    # --- xterm-SGR-Mausereignisse (nur nach ausdruecklicher Anforderung) --
    def _mouse_tracking_level(self) -> int:
        if self._model is None:
            return 0
        return self._model.sgr_mouse_tracking_level()

    @staticmethod
    def _button_name(button):
        if button == Qt.MouseButton.LeftButton:
            return "left"
        if button == Qt.MouseButton.MiddleButton:
            return "middle"
        if button == Qt.MouseButton.RightButton:
            return "right"
        return None

    @staticmethod
    def _drag_button(buttons):
        for qt_button, name in ((Qt.MouseButton.LeftButton, "left"),
                                (Qt.MouseButton.MiddleButton, "middle"),
                                (Qt.MouseButton.RightButton, "right")):
            if buttons & qt_button:
                return name
        return None

    def _send_sgr_mouse(self, kind, event, button="left") -> None:
        row, col = self._cell_at(event.position().toPoint())
        mods = event.modifiers()
        self.dataReady.emit(encode_sgr_mouse(
            kind, row, col, button=button,
            shift=bool(mods & Qt.KeyboardModifier.ShiftModifier),
            alt=bool(mods & Qt.KeyboardModifier.AltModifier),
            ctrl=bool(mods & Qt.KeyboardModifier.ControlModifier),
        ))

    # --- Mausauswahl / Zwischenablage ------------------------------------
    def _cell_at(self, pos):
        col = int(pos.x() // self._cell_w)
        row = int(pos.y() // self._cell_h)
        cols = self._model.cols if self._model else 1
        rows = self._model.rows if self._model else 1
        col = max(0, min(cols - 1, col))
        row = max(0, min(rows - 1, row))
        return row, col

    def mousePressEvent(self, event) -> None:
        self.setFocus()
        # Shift behält die lokale Auswahl, selbst wenn die TUI Mausberichte
        # aktiviert hat; ein Rechtsklick mit Shift oeffnet das Kontextmenue.
        button = self._button_name(event.button())
        if button and self._mouse_tracking_level() and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.clear_selection()
            self._local_mouse_selection = False
            self._send_sgr_mouse("press", event, button)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._model is not None:
            self._local_mouse_selection = True
            self._sel_anchor = self._cell_at(event.position().toPoint())
            self._sel_head = self._sel_anchor
            self.update()
            event.accept()
            return
        if event.button() == Qt.MouseButton.MiddleButton and self._model is not None:
            self.paste_clipboard(selection=True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        level = self._mouse_tracking_level()
        if level and not self._local_mouse_selection and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            pressed = self._drag_button(event.buttons())
            if level == 1003 or (level == 1002 and pressed):
                self._send_sgr_mouse("drag" if pressed else "move", event,
                                     pressed or "left")
                event.accept()
                return
        if self._sel_anchor is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self._sel_head = self._cell_at(event.position().toPoint())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        button = self._button_name(event.button())
        if button and self._mouse_tracking_level() and not self._local_mouse_selection and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self._send_sgr_mouse("release", event, button)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._sel_anchor is not None:
            self._local_mouse_selection = False
            # Reiner Klick ohne Ziehen hebt die Auswahl auf.
            if self._sel_head == self._sel_anchor:
                self.clear_selection()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _create_context_menu(self) -> QMenu:
        """Kontextmenue nur fuer die VT-Ansicht; Shell-Tasten bleiben intakt."""
        menu = QMenu(self)
        copy_action = menu.addAction("Kopieren (Strg+Umschalt+C / Strg+Einfg)")
        copy_action.setEnabled(self.has_selection())
        copy_action.triggered.connect(self.copy_selection)
        paste_action = menu.addAction("Einfuegen (Strg+Umschalt+V / Umschalt+Einfg)")
        paste_action.setEnabled(bool(QApplication.clipboard().text()))
        paste_action.triggered.connect(self.paste_clipboard)
        menu.addSeparator()
        select_action = menu.addAction("Alles Sichtbare markieren")
        select_action.setEnabled(self._model is not None)
        select_action.triggered.connect(self.select_all_visible)
        clear_action = menu.addAction("Markierung aufheben")
        clear_action.setEnabled(self.has_selection())
        clear_action.triggered.connect(self.clear_selection)
        menu.addSeparator()
        diagnostic = menu.addAction("VT-Diagnose: Modell und Ansicht speichern …")
        diagnostic.setEnabled(self._model is not None)
        diagnostic.triggered.connect(self.save_vt_diagnostic)
        trace_action = menu.addAction(
            "VT-Rohdatenaufzeichnung beenden …" if self._vt_raw_trace.active
            else "VT-Rohdatenaufzeichnung starten …"
        )
        trace_action.setEnabled(self._model is not None)
        trace_action.triggered.connect(self.toggle_vt_raw_trace)
        return menu

    def trace_event(self, event, **fields):
        trace = getattr(self, "_vt_raw_trace", None)
        if trace is not None:
            trace.event(event, **fields)

    def toggle_vt_raw_trace(self) -> None:
        """Record incoming PTY bytes only after an explicit privacy warning.

        Start recording before launching htop, so the trace contains its entire
        alternate-screen setup. Stop/export via Shift+right click. Raw data
        may contain secrets and must be inspected before sharing.
        """
        trace = self._vt_raw_trace
        if not trace.active and not trace.size:
            answer = QMessageBox.warning(
                self, "VT-Rohdaten – Datenschutz",
                "Es werden die unveraenderten Terminal-Ausgabebytes inklusive "
                "moeglicher vertraulicher Daten im Arbeitsspeicher aufgezeichnet "
                "(maximal 4 MiB). Start bitte VOR dem Start von htop ausfuehren. "
                "Die Aufzeichnung endet am Limit automatisch. Aufzeichnen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer == QMessageBox.StandardButton.Yes:
                from shelldeck_vt_diagnostic import model_snapshot
                trace.start()
                self._vt_trace_start_snapshot = model_snapshot(self._model)
                self._vt_trace_start_geometry = (self._model.rows, self._model.cols)
                trace.event("trace_started", rows=self._model.rows, cols=self._model.cols,
                            width=self.width(), height=self.height(),
                            alternate=self._model.in_alternate_screen())
            return
        trace.event("trace_stopped", rows=self._model.rows, cols=self._model.cols,
                    alternate=self._model.in_alternate_screen())
        data = trace.stop()
        filename, _ = QFileDialog.getSaveFileName(
            self, "VT-Rohdaten speichern", "ShellDeck_VT_Rohdaten.bin",
            "Binaerdaten (*.bin)",
        )
        if not filename:
            # Keep the stopped trace in memory for an explicit later export.
            return
        from pathlib import Path
        path = Path(filename)
        try:
            path.write_bytes(data)
            start_geometry = self._vt_trace_start_geometry
            info = (f"bytes={len(data)}\ntruncated={trace.truncated}\n"
                    f"rows={self._model.rows}\ncols={self._model.cols}\n"
                    f"start_rows={start_geometry[0] if start_geometry else 'unknown'}\n"
                    f"start_cols={start_geometry[1] if start_geometry else 'unknown'}\n")
            path.with_suffix('.meta.txt').write_text(info, encoding='utf-8')
            path.with_name(path.stem + '_Ereignisse.jsonl').write_text(
                trace.events_jsonl(), encoding='utf-8'
            )
            if self._vt_trace_start_snapshot is not None:
                path.with_name(path.stem + '_Startmodell.txt').write_text(
                    self._vt_trace_start_snapshot, encoding='utf-8'
                )
        except Exception as exc:
            QMessageBox.warning(self, "VT-Rohdaten", f"Speichern fehlgeschlagen: {exc}")
            return
        trace._chunks.clear()
        trace._size = 0
        self._vt_trace_start_snapshot = None
        self._vt_trace_start_geometry = None
        QMessageBox.information(
            self, "VT-Rohdaten gespeichert",
            "Rohbytes und Startmodell wurden gespeichert. Bitte vor dem Weitergeben "
            "auf vertrauliche Informationen pruefen. Ergaenzend die VT-Diagnose "
            "(Modell und Ansicht) speichern.",
        )

    def save_vt_diagnostic(self) -> None:
        """Explicit one-shot capture; never write terminal contents implicitly."""
        if self._model is None:
            return
        reply = QMessageBox.warning(
            self, "VT-Diagnose – vertrauliche Inhalte",
            "Die Diagnose speichert den sichtbaren Terminalinhalt als Text "
            "und Bildschirmfoto. Darin koennen Pfade, Prozessnamen, "
            "Eingaben oder Zugangsdaten stehen. Dateien vor dem Teilen "
            "bitte pruefen. Jetzt speichern?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, "VT-Diagnose speichern", "ShellDeck_VT_Diagnose.txt",
            "Textdateien (*.txt)",
        )
        if not filename:
            return
        from pathlib import Path
        from shelldeck_vt_diagnostic import model_snapshot
        path = Path(filename)
        try:
            # Snapshot is taken before rendering/grabbing to compare the same frame.
            snapshot = model_snapshot(self._model)
            screenshot = self.grab()
            if screenshot.isNull() or not screenshot.save(str(path.with_suffix(".png")), "PNG"):
                raise OSError("PNG konnte nicht gespeichert werden")
            path.write_text(snapshot, encoding="utf-8")
        except Exception as exc:
            QMessageBox.warning(self, "VT-Diagnose", f"Speichern fehlgeschlagen: {exc}")
            return
        QMessageBox.information(
            self, "VT-Diagnose gespeichert",
            f"Gespeichert: {path.name} und {path.with_suffix('.png').name}\n"
            "Bitte beide Dateien vor dem Weitergeben auf vertrauliche Inhalte pruefen.",
        )

    def contextMenuEvent(self, event) -> None:
        # Rechtsklick ist im Mausmodus eine Eingabe an die Anwendung.
        # Shift+Rechtsklick bietet weiterhin das ShellDeck-Kontextmenue.
        if self._mouse_tracking_level() and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            event.accept()
            return
        if self._model is None:
            super().contextMenuEvent(event)
            return
        menu = self._create_context_menu()
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()
        event.accept()

    def select_all_visible(self) -> None:
        """Nur die sichtbare VT-Seite markieren, nicht unbemerkt Scrollback."""
        if self._model is None:
            return
        self._sel_anchor = (0, 0)
        self._sel_head = (self._model.rows - 1, self._model.cols - 1)
        self.update()

    def clear_selection(self) -> None:
        if self._sel_anchor is not None or self._sel_head is not None:
            self._sel_anchor = None
            self._sel_head = None
            self.update()

    def has_selection(self) -> bool:
        return self._sel_anchor is not None and self._sel_head is not None \
            and self._sel_anchor != self._sel_head

    def _normalized_selection(self):
        if not self.has_selection():
            return None
        a, b = self._sel_anchor, self._sel_head
        return (a, b) if a <= b else (b, a)

    def _is_selected(self, x: int, y: int) -> bool:
        sel = self._normalized_selection()
        if sel is None:
            return False
        (r0, c0), (r1, c1) = sel
        if y < r0 or y > r1:
            return False
        if y == r0 and x < c0:
            return False
        if y == r1 and x > c1:
            return False
        return True

    def selected_text(self) -> str:
        sel = self._normalized_selection()
        if sel is None or self._model is None:
            return ""
        (r0, c0), (r1, c1) = sel
        lines = self._model.display()
        parts = []
        for y in range(r0, r1 + 1):
            line = lines[y] if y < len(lines) else ""
            start = c0 if y == r0 else 0
            end = (c1 + 1) if y == r1 else len(line)
            parts.append(line[start:end].rstrip())
        return "\n".join(parts)

    def copy_selection(self) -> None:
        text = self.selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def paste_clipboard(self, selection: bool = False) -> None:
        if self._model is None:
            return
        clipboard = QApplication.clipboard()
        mode = clipboard.Mode.Selection if selection and clipboard.supportsSelection() \
            else clipboard.Mode.Clipboard
        text = clipboard.text(mode)
        if not text:
            return
        data = keyenc.encode_paste(text, bracketed=self._model.bracketed_paste())
        self.dataReady.emit(bytes(data))

    # --- Zeichnen ---------------------------------------------------------
    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        try:
            self._paint_terminal(painter, event)
        finally:
            # Ein Painter muss auch nach Python-Fehlern beendet werden,
            # sonst kann Qt beim Aufraeumen nativ abstuerzen.
            painter.end()

    def _paint_terminal(self, painter: QPainter, event) -> None:
        painter.fillRect(event.rect(), self.default_bg)
        if self._model is None:
            painter.setPen(self.default_fg)
            painter.setFont(self._font)
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "pyte nicht installiert – klassische Ansicht aktiv")
            return

        cw, ch = self._cell_w, self._cell_h
        rows, cols = self._model.rows, self._model.cols
        first = max(0, int(event.rect().top() // ch))
        last = min(rows - 1, int(event.rect().bottom() // ch))

        cursor = self._model.cursor
        show_cursor = (
            self.hasFocus()
            and not cursor.get("hidden", False)
            and (not self.cursor_blink or self._cursor_visible_phase)
        )
        cur_x, cur_y = cursor.get("x", 0), cursor.get("y", 0)
        last_font = None
        last_pen = None

        for y in range(first, last + 1):
            cells = self._model.row_cells(y)
            y_px = y * ch
            # Glyphs must never paint into another terminal row. This is
            # especially relevant for italic fonts and extended graphemes.
            painter.save()
            painter.setClipRect(QRectF(0, y_px, cols * cw, ch),
                                Qt.ClipOperation.IntersectClip)
            try:
                self._paint_cells_in_row(painter, cells, y, cols, cw, ch,
                                         y_px, show_cursor, cur_x, cur_y,
                                         last_font, last_pen)
            finally:
                painter.restore()

    def _paint_cells_in_row(self, painter, cells, y, cols, cw, ch, y_px,
                            show_cursor, cur_x, cur_y, last_font, last_pen):
        """Paint one terminal row, clipping oversized glyphs to their cell."""
        for x in range(cols):
            cell = cells[x]
            fg = self._resolve_color(cell["fg"], self.default_fg)
            bg = self._resolve_color(cell["bg"], self.default_bg)
            if cell["reverse"]:
                fg, bg = bg, fg
            if self._is_selected(x, y):
                bg = self.selection_bg
            is_cursor_cell = show_cursor and x == cur_x and y == cur_y
            if is_cursor_cell:
                fg, bg = bg, fg  # Blockcursor: Zelle invertieren

            x_px = x * cw
            rect = QRect(int(x_px), int(y_px), int(cw) + 1, int(ch) + 1)
            if bg != self.default_bg or is_cursor_cell:
                painter.fillRect(rect, bg)

            char = cell["char"]
            if char and char != " ":
                glyph_font = self._font_for_cell(cell)
                if glyph_font is not last_font:
                    painter.setFont(glyph_font)
                    last_font = glyph_font
                if fg != last_pen:
                    painter.setPen(fg)
                    last_pen = fg
                # pyte normally stores one character per cell, but combining
                # sequences or a wider glyph can reach the next cell. Do not
                # allow a stale fragment to be painted over another column.
                # Keep the common ASCII path fast (htop can redraw thousands
                # of cells per frame). Non-ASCII, combined and italic glyphs
                # may extend beyond a cell and need an explicit boundary.
                needs_clip = (len(char) != 1 or ord(char) > 127 or
                              cell["italics"])
                if needs_clip:
                    painter.save()
                    painter.setClipRect(QRectF(x_px, y_px, cw, ch),
                                        Qt.ClipOperation.IntersectClip)
                painter.drawText(int(x_px), int(y_px + self._ascent), char)
                if needs_clip:
                    painter.restore()

__all__ = ["TerminalGridView"]
