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
