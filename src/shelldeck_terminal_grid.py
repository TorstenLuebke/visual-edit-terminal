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

from typing import Dict, Optional

from PySide6.QtCore import Qt, QRect, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter
from PySide6.QtWidgets import QApplication, QWidget

import shelldeck_key_encoding as keyenc
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
    "brown": "#cdcd00", "yellow": "#cdcd00", "blue": "#0000ee",
    "magenta": "#cd00cd", "cyan": "#00cdcd", "white": "#e5e5e5",
    "brightblack": "#7f7f7f", "brightred": "#ff0000", "brightgreen": "#00ff00",
    "brightbrown": "#ffff00", "brightyellow": "#ffff00", "brightblue": "#5c5cff",
    "brightmagenta": "#ff00ff", "brightcyan": "#00ffff", "brightwhite": "#ffffff",
}
_HEXDIGITS = set("0123456789abcdefABCDEF")


class TerminalGridView(QWidget):
    """Rendert ein VtScreen-Modell als monospaced Terminalgitter."""

    # (rows, cols) – wird bei jeder Größenänderung des Gitters gemeldet.
    sizeChanged = Signal(int, int)
    # An das PTY zu sendende Eingabebytes (Tastatur/Paste). Der Host verbindet
    # dieses Signal mit dem Schreiben in den Terminal-Prozess.
    dataReady = Signal(object)

    def __init__(self, parent=None, rows: int = 24, cols: int = 80,
                 font: Optional[QFont] = None, enable_history: bool = True):
        super().__init__(parent)
        self._model = vt.VtScreen(rows=rows, cols=cols, enable_history=enable_history) \
            if vt.is_available() else None

        base_font = font or QFont("Monospace", 11)
        base_font.setStyleHint(QFont.StyleHint.TypeWriter)
        base_font.setFixedPitch(True)
        self._font = base_font

        # Farbschema (kann vom ShellDeck-Theme gesetzt werden).
        self.default_fg = QColor("#d0d0d0")
        self.default_bg = QColor("#1e1e1e")
        self.selection_bg = QColor("#264f78")

        # Auswahlzustand (Zeile, Spalte), jeweils inklusive.
        self._sel_anchor = None
        self._sel_head = None

        self._cell_w = 1.0
        self._cell_h = 1.0
        self._ascent = 0.0
        self._last_cursor_y = 0

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

    # --- Schrift/Metrik ---------------------------------------------------
    def setFont(self, font: QFont) -> None:  # noqa: N802 (Qt-Namenskonvention)
        font.setFixedPitch(True)
        super().setFont(font)
        self._font = font
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

    # --- Datenzufuhr ------------------------------------------------------
    def feed(self, data) -> None:
        """Rohbytes/Text in das Modell geben und betroffene Zeilen neu zeichnen."""
        if self._model is None:
            return
        self._model.feed(data)
        self._repaint_dirty()

    def reset(self) -> None:
        if self._model is not None:
            self._model.reset()
        self.update()

    def _repaint_dirty(self) -> None:
        if self._model is None:
            return
        dirty = set(self._model.dirty_lines())
        cursor_y = self._model.cursor.get("y", 0)
        dirty.add(cursor_y)
        dirty.add(self._last_cursor_y)
        self._last_cursor_y = cursor_y
        self._model.clear_dirty()
        if not dirty:
            return
        top = max(0, min(dirty))
        bottom = min(self._model.rows - 1, max(dirty))
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
        if self._model.resize(rows, cols):
            self.sizeChanged.emit(rows, cols)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_grid_from_size()

    def sizeHint(self) -> QSize:
        if self._model is None:
            return QSize(640, 384)
        return QSize(int(self._model.cols * self._cell_w),
                     int(self._model.rows * self._cell_h))

    # --- Fokus/Cursor-Blinken --------------------------------------------
    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if self.cursor_blink:
            self._cursor_visible_phase = True
            self._blink_timer.start()
        self.update()

    def focusOutEvent(self, event) -> None:
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
        if self._model is None or not self._model.has_history():
            super().wheelEvent(event)
            return
        delta = event.angleDelta().y()
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
        text = str(value)
        hexname = _ANSI_PALETTE.get(text.lower())
        if hexname:
            return QColor(hexname)
        if len(text) == 6 and all(c in _HEXDIGITS for c in text):
            return QColor("#" + text)
        color = QColor(text)
        return color if color.isValid() else default

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
        if event.button() == Qt.MouseButton.LeftButton and self._model is not None:
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
        if self._sel_anchor is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            self._sel_head = self._cell_at(event.position().toPoint())
            self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._sel_anchor is not None:
            # Reiner Klick ohne Ziehen hebt die Auswahl auf.
            if self._sel_head == self._sel_anchor:
                self.clear_selection()
            event.accept()
            return
        super().mouseReleaseEvent(event)

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

        for y in range(first, last + 1):
            cells = self._model.row_cells(y)
            y_px = y * ch
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
                    glyph_font = QFont(self._font)
                    glyph_font.setBold(cell["bold"])
                    glyph_font.setItalic(cell["italics"])
                    glyph_font.setUnderline(cell["underscore"])
                    glyph_font.setStrikeOut(cell["strikethrough"])
                    painter.setFont(glyph_font)
                    painter.setPen(fg)
                    painter.drawText(int(x_px), int(y_px + self._ascent), char)


__all__ = ["TerminalGridView"]
