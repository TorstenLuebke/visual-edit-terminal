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
        self.assertEqual(len(actions), 4)
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
