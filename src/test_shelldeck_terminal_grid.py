"""Offscreen-Rendertests für TerminalGridView.

Benoetigt Qt (mit ladbaren GL-Systembibliotheken) und pyte. In Umgebungen ohne
diese Voraussetzungen (z.B. CI ohne libEGL) werden die Tests uebersprungen.

Ausfuehren (aus src):
    QT_QPA_PLATFORM=offscreen python -m unittest test_shelldeck_terminal_grid
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shelldeck_vt_screen as vt


# QApplication muss waehrend des gesamten Testlaufs referenziert bleiben.
# Ein nur lokales QApplication([]) kann sofort wieder freigegeben werden.
_QT_APP = None


def _qt_usable():
    global _QT_APP
    try:
        from PySide6.QtWidgets import QApplication
        _QT_APP = QApplication.instance()
        if _QT_APP is None:
            _QT_APP = QApplication([])
        return True
    except Exception:
        return False


QT_OK = _qt_usable()


@unittest.skipUnless(QT_OK and vt.is_available(),
                     "Qt oder pyte in dieser Umgebung nicht nutzbar")
class TerminalGridViewTests(unittest.TestCase):
    def _make(self, rows=6, cols=24):
        from shelldeck_terminal_grid import TerminalGridView
        view = TerminalGridView(rows=rows, cols=cols)
        view.resize(int(cols * view.cell_size()[0]) + 4,
                    int(rows * view.cell_size()[1]) + 4)
        self.addCleanup(view.close)
        return view

    def test_usable_with_pyte(self):
        view = self._make()
        self.assertTrue(view.is_usable())

    def test_normal_shell_repaints_full_grid_after_history_redraw(self):
        """Readline redraw must not rely on incomplete dirty-row reports."""
        from shelldeck_terminal_grid import TerminalGridView

        class RecordingGrid(TerminalGridView):
            def update(self, *args):
                if hasattr(self, "repaint_requests"):
                    self.repaint_requests.append(args)
                return super().update(*args)

        view = RecordingGrid(rows=4, cols=60)
        self.addCleanup(view.close)
        view.repaint_requests = []
        view.feed(b"user$ echo a-very-long-command")
        self.assertTrue(view.repaint_requests)
        self.assertTrue(all(len(args) == 4 for args in view.repaint_requests))
        view.repaint_requests.clear()
        view.feed(b"\r\x1b[2Kuser$ ls")
        self.assertIn((), view.repaint_requests)
        self.assertIn("user$ ls", view.model().display()[0])
        self.assertNotIn("very-long-command", view.model().display()[0])

    def test_feed_and_render_no_error(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QImage, QPainter
        view = self._make()
        view.feed(b"hallo\r\n")
        view.feed(b"\x1b[31mROT\x1b[0m")
        img = QImage(view.size(), QImage.Format.Format_RGB32)
        img.fill(0)
        painter = QPainter(img)
        try:
            view.render(painter, QPoint(0, 0))
        finally:
            # Auch bei einer Ausnahme in paintEvent muss der QPainter enden.
            # Sonst kann Qt beim Aufraeumen einen nativen Crash ausloesen.
            painter.end()
        # Irgendein Pixel muss vom (schwarzen) Ausgangsbild abweichen -> es
        # wurde tatsaechlich Text/Hintergrund gezeichnet.
        distinct = {img.pixel(x, y)
                    for y in range(0, img.height(), 3)
                    for x in range(0, img.width(), 3)}
        self.assertGreater(len(distinct), 1)

    def test_renderer_reuses_fonts_and_limits_explicit_color_cache(self):
        from PySide6.QtGui import QFont
        from shelldeck_terminal_grid import _cached_terminal_color
        view = self._make()
        cell = view.model().row_cells(0)[0]
        first_font = view._font_for_cell(cell)
        self.assertIs(first_font, view._font_for_cell(cell))
        self.assertTrue(_cached_terminal_color("red").isValid())
        self.assertIs(_cached_terminal_color("red"), _cached_terminal_color("red"))
        for value in range(400):
            _cached_terminal_color(f"{value:06x}")
        self.assertLessEqual(_cached_terminal_color.cache_info().currsize, 256)
        view.setFont(QFont("Monospace", 12))
        self.assertIsNot(first_font, view._font_for_cell(cell))

    def test_renderer_cached_styles_preserve_attributes(self):
        view = self._make()
        view.feed("\x1b[1;3;4;9mX\x1b[0m")
        cell = view.model().row_cells(0)[0]
        font = view._font_for_cell(cell)
        self.assertTrue(font.bold())
        self.assertTrue(font.italic())
        self.assertTrue(font.underline())
        self.assertTrue(font.strikeOut())

    def test_dirty_row_intervals(self):
        from shelldeck_terminal_grid import _coalesce_dirty_rows
        self.assertEqual(_coalesce_dirty_rows([4, 1, 2, 1, 7, -1, 99], 8),
                         [(1, 2), (4, 4), (7, 7)])
        self.assertEqual(_coalesce_dirty_rows([], 8), [])
        self.assertEqual(_coalesce_dirty_rows([-1, 10], 8), [])

    def test_sparse_dirty_rows_schedule_separate_updates(self):
        from shelldeck_terminal_grid import TerminalGridView

        class RecordingView(TerminalGridView):
            def __init__(self):
                self.updated_rects = []
                super().__init__(rows=8, cols=24)

            def update(self, *args):
                self.updated_rects.append(args)

        view = RecordingView()
        self.addCleanup(view.close)
        model = view.model()
        model.clear_dirty()
        view._last_cursor = (model.cursor["x"], model.cursor["y"],
                             model.cursor["hidden"])
        view.updated_rects.clear()
        model.screen.dirty.update({1, 6})
        view._repaint_dirty()
        self.assertEqual(len(view.updated_rects), 2)
        self.assertLess(view.updated_rects[0][1], view.updated_rects[1][1])
        self.assertEqual(model.dirty_lines(), [])

        # No screen or cursor changes: do not schedule redundant paints.
        view.updated_rects.clear()
        view._repaint_dirty()
        self.assertEqual(view.updated_rects, [])

    def test_fullscreen_repaint_is_whole_widget_after_scrolling_updates(self):
        """TUI frames must not leave stale rows even with sparse dirty marks."""
        from shelldeck_terminal_grid import TerminalGridView

        class RecordingView(TerminalGridView):
            def __init__(self):
                self.repaints = []
                super().__init__(rows=8, cols=30)

            def update(self, *args):
                self.repaints.append(args)

        view = RecordingView()
        self.addCleanup(view.close)
        view.feed("SHELL\x1b[?1049h")
        self.assertTrue(view.model().in_alternate_screen())
        view.repaints.clear()
        view.model().clear_dirty()
        # Simulate a fullscreen program changing several rows while pyte
        # reports only a partial region (or even no dirty rows at all).
        view.feed("\x1b[4;1Hnew process")
        self.assertEqual(view.repaints, [()])
        view.repaints.clear()
        view.model().clear_dirty()
        view._repaint_dirty()
        self.assertEqual(view.repaints, [()])
        # Leaving the TUI restores the normal screen and its fast sparse path.
        view.feed("\x1b[?1049l")
        self.assertFalse(view.model().in_alternate_screen())
        view.model().clear_dirty()
        view.repaints.clear()
        view.feed("SHELL-READY")
        self.assertTrue(view.repaints)
        self.assertTrue(all(len(args) == 4 for args in view.repaints))

    def test_model_reflects_feed(self):
        view = self._make()
        view.feed("abc")
        self.assertTrue(view.model().display()[0].startswith("abc"))

    def test_resize_emits_size_and_updates_model(self):
        from PySide6.QtWidgets import QApplication
        view = self._make(rows=6, cols=24)
        # Ein noch nie angezeigtes QWidget darf resizeEvent bis zum ersten
        # show() zurueckstellen. Hier pruefen wir die aktive Terminalansicht.
        view.show()
        QApplication.processEvents()
        seen = []
        view.sizeChanged.connect(lambda r, c: seen.append((r, c)))
        cw, chh = view.cell_size()
        view.resize(int(40 * cw) + 4, int(10 * chh) + 4)
        QApplication.processEvents()
        self.assertEqual(view.model().cols, 40)
        self.assertEqual(view.model().rows, 10)
        self.assertTrue(seen and seen[-1] == (10, 40))

    def _key(self, view, qtkey, text="", mods=None):
        from PySide6.QtCore import QEvent, Qt
        from PySide6.QtGui import QKeyEvent
        modifiers = mods if mods is not None else Qt.KeyboardModifier.NoModifier
        event = QKeyEvent(QEvent.Type.KeyPress, qtkey, modifiers, text)
        got = []
        conn = view.dataReady.connect(lambda d: got.append(bytes(d)))
        view.keyPressEvent(event)
        view.dataReady.disconnect(conn)
        return got[-1] if got else b""

    def test_keypress_printable_emits_bytes(self):
        from PySide6.QtCore import Qt
        view = self._make()
        self.assertEqual(self._key(view, Qt.Key.Key_A, "a"), b"a")

    def test_keypress_arrow_emits_csi(self):
        from PySide6.QtCore import Qt
        view = self._make()
        self.assertEqual(self._key(view, Qt.Key.Key_Up, ""), b"\x1b[A")

    def test_keypress_ctrl_c(self):
        from PySide6.QtCore import Qt
        view = self._make()
        data = self._key(view, Qt.Key.Key_C, "", Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(data, b"\x03")

    def test_selection_and_copy(self):
        from PySide6.QtWidgets import QApplication
        view = self._make()
        view.feed("hello")
        view._sel_anchor = (0, 0)
        view._sel_head = (0, 4)
        self.assertTrue(view.has_selection())
        self.assertEqual(view.selected_text(), "hello")
        view.copy_selection()
        self.assertEqual(QApplication.clipboard().text(), "hello")

    def test_context_menu_copy_and_paste(self):
        from PySide6.QtWidgets import QApplication
        view = self._make()
        view.feed("hallo")
        QApplication.clipboard().setText("vorher")
        menu = view._create_context_menu()
        actions = [a for a in menu.actions() if not a.isSeparator()]
        self.assertEqual(len(actions), 6)
        self.assertEqual(actions[4].text(), "VT-Diagnose: Modell und Ansicht speichern …")
        self.assertTrue(actions[4].isEnabled())
        self.assertFalse(actions[0].isEnabled())
        self.assertTrue(actions[1].isEnabled())
        view._sel_anchor, view._sel_head = (0, 0), (0, 4)
        menu = view._create_context_menu()
        actions = [a for a in menu.actions() if not a.isSeparator()]
        actions[0].trigger()
        self.assertEqual(QApplication.clipboard().text(), "hallo")
        sent = []
        view.dataReady.connect(lambda data: sent.append(bytes(data)))
        actions[1].trigger()
        self.assertEqual(sent[-1], b"hallo")
        actions[3].trigger()
        self.assertFalse(view.has_selection())
        actions[2].trigger()
        self.assertTrue(view.has_selection())
        self.assertTrue(view.selected_text().startswith("hallo"))

    def test_ctrl_insert_copies_selection_without_forwarding_to_shell(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication

        view = self._make()
        view.feed("hallo")
        view._sel_anchor, view._sel_head = (0, 0), (0, 4)
        QApplication.clipboard().setText("vorher")
        copied = self._key(view, Qt.Key.Key_Insert, "",
                           Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(copied, b"")
        self.assertEqual(QApplication.clipboard().text(), "hallo")
        # Ctrl+C bleibt ein Signal fuer interaktive Shell-Programme.
        interrupted = self._key(view, Qt.Key.Key_C, "",
                                Qt.KeyboardModifier.ControlModifier)
        self.assertEqual(interrupted, b"\x03")

    def test_context_menu_describes_both_clipboard_shortcut_variants(self):
        view = self._make()
        menu = view._create_context_menu()
        actions = [action for action in menu.actions() if not action.isSeparator()]
        self.assertIn("Strg+Umschalt+C", actions[0].text())
        self.assertIn("Strg+Einfg", actions[0].text())
        self.assertIn("Strg+Umschalt+V", actions[1].text())
        self.assertIn("Umschalt+Einfg", actions[1].text())
        menu.deleteLater()

    def test_shift_insert_pastes_without_overriding_ctrl_v(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication
        view = self._make()
        QApplication.clipboard().setText("paste")
        pasted = self._key(view, Qt.Key.Key_Insert, "", Qt.KeyboardModifier.ShiftModifier)
        self.assertEqual(pasted, b"paste")
        # Ctrl+V wird weiterhin an vim und andere interaktive Tools gesendet.
        self.assertEqual(self._key(view, Qt.Key.Key_V, "\x16", Qt.KeyboardModifier.ControlModifier), b"\x16")

    def test_sgr_mouse_events_are_isolated_per_tab(self):
        from PySide6.QtCore import QPoint, QPointF, Qt

        class MouseEvent:
            def __init__(self, row, col, view, button=Qt.MouseButton.LeftButton,
                         buttons=None, mods=Qt.KeyboardModifier.NoModifier, delta=120):
                self._pos = QPointF((col + 0.5) * view._cell_w,
                                    (row + 0.5) * view._cell_h)
                self._button = button
                self._buttons = button if buttons is None else buttons
                self._mods = mods
                self._delta = delta
                self.accepted = False

            def position(self): return self._pos
            def button(self): return self._button
            def buttons(self): return self._buttons
            def modifiers(self): return self._mods
            def angleDelta(self): return QPoint(0, self._delta)
            def accept(self): self.accepted = True

        tracked = self._make()
        normal = self._make()
        sent_tracked, sent_normal = [], []
        tracked.dataReady.connect(lambda data: sent_tracked.append(bytes(data)))
        normal.dataReady.connect(lambda data: sent_normal.append(bytes(data)))
        # Verhandelte SGR-Berichte nur in einem Tab.
        tracked.model().screen.mode.update({1000 << 5, 1002 << 5, 1006 << 5})
        event = MouseEvent(3, 5, tracked)
        tracked.mousePressEvent(event)
        self.assertTrue(event.accepted)
        self.assertEqual(sent_tracked[-1], b"\x1b[<0;6;4M")
        tracked.mouseMoveEvent(MouseEvent(3, 6, tracked))
        self.assertEqual(sent_tracked[-1], b"\x1b[<32;7;4M")
        tracked.mouseReleaseEvent(MouseEvent(3, 6, tracked))
        self.assertEqual(sent_tracked[-1], b"\x1b[<0;7;4m")
        tracked.wheelEvent(MouseEvent(2, 2, tracked, delta=-120))
        self.assertEqual(sent_tracked[-1], b"\x1b[<65;3;3M")

        normal.mousePressEvent(MouseEvent(0, 0, normal))
        normal.mouseMoveEvent(MouseEvent(0, 2, normal))
        normal.mouseReleaseEvent(MouseEvent(0, 2, normal))
        self.assertEqual(sent_normal, [])
        self.assertTrue(normal.has_selection())
        # Auch im Mausmodus erzwingt Shift die lokale Markierung.
        count = len(sent_tracked)
        shift = Qt.KeyboardModifier.ShiftModifier
        tracked.mousePressEvent(MouseEvent(1, 1, tracked, mods=shift))
        tracked.mouseMoveEvent(MouseEvent(1, 3, tracked, mods=shift))
        tracked.mouseReleaseEvent(MouseEvent(1, 3, tracked, mods=shift))
        self.assertEqual(len(sent_tracked), count)
        self.assertTrue(tracked.has_selection())
        # Ohne SGR 1006 duerfen wir niemals ein inkompatibles Format senden.
        tracked.model().screen.mode.discard(1006 << 5)
        tracked.mousePressEvent(MouseEvent(0, 0, tracked))
        self.assertEqual(len(sent_tracked), count)

    def test_mouse_motion_requires_tracking_level(self):
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        # Echte Qt-Ereignisse verwenden: Bei nicht gemeldeten Bewegungen
        # reicht das Widget den QMouseEvent an QWidget.mouseMoveEvent weiter.
        # Ein selbstgebautes Test-Double wird von PySide6 dort abgelehnt.
        def move_without_buttons():
            return QMouseEvent(
                QEvent.Type.MouseMove,
                QPointF(3, 3),  # Position im Widget
                QPointF(3, 3),  # Position im Fenster
                QPointF(3, 3),  # Globale Position (offscreen-Test)
                Qt.MouseButton.NoButton,
                Qt.MouseButton.NoButton,
                Qt.KeyboardModifier.NoModifier,
            )

        view = self._make()
        got = []
        view.dataReady.connect(lambda data: got.append(bytes(data)))
        view.model().screen.mode.update({1002 << 5, 1006 << 5})
        view.mouseMoveEvent(move_without_buttons())
        self.assertFalse(got)
        view.model().screen.mode.add(1003 << 5)
        view.mouseMoveEvent(move_without_buttons())
        self.assertEqual(got, [b"\x1b[<35;1;1M"])

    def test_alternate_screen_wheel_never_moves_normal_scrollback(self):
        from PySide6.QtCore import QPoint, Qt

        class Wheel:
            def __init__(self, delta=120, mods=Qt.KeyboardModifier.NoModifier):
                self.delta, self.mods, self.accepted = delta, mods, False
            def angleDelta(self): return QPoint(0, self.delta)
            def modifiers(self): return self.mods
            def accept(self): self.accepted = True

        view = self._make()
        view.feed("SHELL\x1b[?1049hHTOP")
        self.assertTrue(view.model().in_alternate_screen())
        sent = []
        view.dataReady.connect(lambda data: sent.append(bytes(data)))
        before = list(view.model().display())
        wheel = Wheel()
        view.wheelEvent(wheel)
        self.assertTrue(wheel.accepted)
        self.assertEqual(view.model().display(), before)
        self.assertEqual(sent, [])

        # With xterm 1007 enabled the application, not history, scrolls.
        view.feed("\x1b[?1007h")
        view.wheelEvent(Wheel(-120))
        self.assertEqual(sent[-1], b"\x1b[B")
        sent.clear()
        view.wheelEvent(Wheel(120, Qt.KeyboardModifier.ShiftModifier))
        self.assertEqual(sent, [])
        view.feed("\x1b[?1049l")
        self.assertTrue(view.model().display()[0].startswith("SHELL"))

    def test_paste_emits_data(self):
        from PySide6.QtWidgets import QApplication
        view = self._make()
        QApplication.clipboard().setText("xy")
        got = []
        view.dataReady.connect(lambda d: got.append(bytes(d)))
        view.paste_clipboard()
        self.assertTrue(got and got[-1] == b"xy")


if __name__ == "__main__":
    unittest.main(verbosity=2)

@unittest.skipUnless(QT_OK and vt.is_available(), "Qt/pyte needed")
class VtCellPaintIsolationTests(unittest.TestCase):
    def test_extended_glyph_does_not_overwrite_neighbour_cells(self):
        """A malformed/combined pyte cell cannot paint over adjacent columns."""
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtCore import QPoint
        from shelldeck_terminal_grid import TerminalGridView

        view = TerminalGridView(rows=3, cols=12)
        self.addCleanup(view.close)
        cw, ch = view.cell_size()
        view.resize(int(12 * cw) + 3, int(3 * ch) + 3)
        old = view.model().row_cells

        def with_content(content):
            def cells(y):
                result = old(y)
                if y == 0:
                    result[0] = dict(result[0], char=content)
                return result
            view.model().row_cells = cells
            image = QImage(view.size(), QImage.Format.Format_RGB32)
            image.fill(0)
            painter = QPainter(image)
            try:
                view.render(painter, QPoint(0, 0))
            finally:
                painter.end()
            return image

        base = with_content(" ")
        oversized = with_content("MMMMMMMMMMMMMMMM")
        # All pixels beyond the first cell, and below the first row, must
        # remain exactly as before the oversized glyph was drawn.
        x_start = int(cw) + 2
        for y in range(oversized.height()):
            for x in range(oversized.width()):
                if x >= x_start or y >= int(ch) + 2:
                    self.assertEqual(oversized.pixel(x, y), base.pixel(x, y),
                                     (x, y))


class VtTraceInitialSnapshotTests(unittest.TestCase):
    """Startzustand muss bei spaeterem Rohdatenexport erhalten bleiben."""

    def test_trace_keeps_start_model_without_writing_files(self):
        from shelldeck_vt_trace import VtRawTrace
        from shelldeck_vt_diagnostic import model_snapshot
        from shelldeck_vt_screen import VtScreen
        model = VtScreen(rows=4, cols=20)
        model.feed(b"Anfang")
        trace = VtRawTrace()
        trace.start()
        initial = model_snapshot(model)
        first_geometry = (model.rows, model.cols)
        model.feed(b"-spaeter")
        trace.append(b"-spaeter")
        self.assertEqual(first_geometry, (4, 20))
        self.assertIn("Anfang", initial)
        self.assertNotIn("spaeter", initial)
        self.assertEqual(trace.stop(), b"-spaeter")
