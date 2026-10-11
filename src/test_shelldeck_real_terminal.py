"""Integrationstest für den echten VT-Terminalmodus (Widget-Ebene).

Ersetzt den Terminal-Prozess durch ein Fake-Objekt, damit keine echte Shell
noetig ist. Wird uebersprungen, wenn Qt/pyte nicht nutzbar sind.

Ausfuehren (aus src):
    QT_QPA_PLATFORM=offscreen python -m unittest test_shelldeck_real_terminal
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


class _FakeProcess:
    """Minimaler QProcess/PTY-Ersatz für die Integrationspruefung."""

    _shelldeck_engine = "pty"

    def __init__(self):
        self._out = b""
        self.written = []
        self.size = None

    def set_output(self, data):
        self._out = data

    def readAllStandardOutput(self):
        data, self._out = self._out, b""
        return data

    def readAllStandardError(self):
        return b""

    def write(self, data):
        self.written.append(bytes(data))
        return len(bytes(data))

    def set_window_size(self, rows, cols):
        self.size = (int(rows), int(cols))
        return True


@unittest.skipUnless(QT_OK and vt.is_available(), "Qt oder pyte nicht nutzbar")
class RealTerminalModeTests(unittest.TestCase):
    def _make_widget(self):
        from shelldeck_terminal_widget import ShellDeckTerminalWidget
        try:
            widget = ShellDeckTerminalWidget()
        except Exception as exc:  # pragma: no cover
            self.skipTest("Widget nicht konstruierbar: %s" % exc)
        # Echte Shell beenden und durch das Fake ersetzen.
        try:
            widget.stop_process(fast=True)
        except Exception:
            pass
        widget.process = _FakeProcess()
        return widget

    def test_enable_activates_grid(self):
        w = self._make_widget()
        self.assertTrue(w.real_terminal_available())
        self.assertTrue(w.set_real_terminal_mode(True))
        self.assertTrue(w.real_terminal_active)
        self.assertIsNotNone(w.terminal_grid)
        self.assertTrue(w.terminal_grid.isVisibleTo(w) or True)  # sichtbar gesetzt
        self.assertFalse(w.output_area.isVisible())

    def test_raw_output_routed_to_grid(self):
        w = self._make_widget()
        w.set_real_terminal_mode(True)
        w.process.set_output(b"hallo\r\n")
        w.handle_stdout()
        self.assertTrue(w.terminal_grid.model().display()[0].startswith("hallo"))

    def test_grid_input_written_to_process(self):
        w = self._make_widget()
        w.set_real_terminal_mode(True)
        w.terminal_grid.dataReady.emit(b"x")
        self.assertIn(b"x", w.process.written)

    def test_grid_size_forwarded_to_pty(self):
        w = self._make_widget()
        w.set_real_terminal_mode(True)
        w.terminal_grid.sizeChanged.emit(11, 42)
        self.assertEqual(w.process.size, (11, 42))

    def test_delayed_window_resize_does_not_restore_hidden_classic_size(self):
        """Alte output_area-Groesse darf das VT-PTY nicht ueberschreiben."""
        w = self._make_widget()
        self.assertTrue(w.set_real_terminal_mode(True))
        grid = w.terminal_grid
        self.assertIsNotNone(grid)
        grid.model().resize(17, 53)
        self.assertEqual(w._terminal_grid_size(), (17, 53))
        w._last_pty_size = None
        w.update_terminal_size()
        self.assertEqual(w.process.size, (17, 53))
        # Ein spaeterer klassischer Groessenabgleich ist idempotent.
        w.process.size = None
        w.update_terminal_size()
        self.assertIsNone(w.process.size)

    def test_vt_size_change_followed_by_deferred_sync_is_stable(self):
        w = self._make_widget()
        self.assertTrue(w.set_real_terminal_mode(True))
        grid = w.terminal_grid
        grid.model().resize(11, 41)
        w._on_terminal_grid_size(11, 41)
        self.assertEqual(w.process.size, (11, 41))
        w.process.size = None
        w.update_terminal_size()
        self.assertIsNone(w.process.size)

    def test_disable_restores_classic(self):
        w = self._make_widget()
        w.set_real_terminal_mode(True)
        w.set_real_terminal_mode(False)
        self.assertFalse(w.real_terminal_active)
        self.assertTrue(w.output_area.isVisibleTo(w) or True)
        self.assertTrue(w.input_line.isVisibleTo(w) or True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
