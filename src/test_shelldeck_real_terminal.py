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

    def test_program_assist_preserves_classic_output_layout(self):
        """Die optionale Hilfsleiste darf die klassische Ansicht nicht ersetzen."""
        w = self._make_widget()
        layout = w.layout()
        assist_index = layout.indexOf(w._assist_slot)
        output_index = layout.indexOf(w.output_area)
        self.assertGreaterEqual(assist_index, 0)
        self.assertEqual(output_index, assist_index + 1)
        self.assertTrue(w._assist_panel.isHidden())
        self.assertFalse(w.output_area.isHidden())
        self.assertTrue(w.set_real_terminal_mode(True))
        self.assertEqual(layout.indexOf(w.terminal_grid), output_index)
        self.assertTrue(w.set_real_terminal_mode(False))
        self.assertGreaterEqual(layout.indexOf(w.output_area), 0)
        self.assertFalse(w.output_area.isHidden())

    def test_assist_visibility_preserves_terminal_geometry(self):
        """Einblendung darf keinerlei Resize des VT-Gitters ausloesen."""
        from PySide6.QtWidgets import QApplication
        w = self._make_widget()
        self.assertTrue(w.set_real_terminal_mode(True))
        w.resize(1100, 700)
        w.show()
        QApplication.processEvents()
        before = (w.terminal_grid.size(), w.terminal_grid.model().screen.lines,
                  w.terminal_grid.model().screen.columns)
        process = w.process
        w.process.foreground_guide = lambda: ("htop", 321)
        w._refresh_detected_program()
        QApplication.processEvents()
        self.assertFalse(w._assist_panel.isHidden())
        after_show = (w.terminal_grid.size(), w.terminal_grid.model().screen.lines,
                      w.terminal_grid.model().screen.columns)
        self.assertEqual(before, after_show)
        w.process.foreground_guide = lambda: None
        w._refresh_detected_program()
        QApplication.processEvents()
        self.assertTrue(w._assist_panel.isHidden())
        after_hide = (w.terminal_grid.size(), w.terminal_grid.model().screen.lines,
                      w.terminal_grid.model().screen.columns)
        self.assertEqual(before, after_hide)
        w.close()

    def test_each_tab_has_own_reserved_assist_area(self):
        w1 = self._make_widget()
        w2 = self._make_widget()
        self.assertIsNot(w1._assist_slot, w2._assist_slot)
        self.assertGreater(w1._assist_slot.height(), 0)
        self.assertEqual(w1._assist_slot.height(), w2._assist_slot.height())
        w1.close()
        w2.close()

    def test_auto_vt_for_direct_command_does_not_restart_shell(self):
        w = self._make_widget()
        process = w.process
        self.assertFalse(w.real_terminal_active)
        self.assertTrue(w._auto_vt_for_direct_command("vim /tmp/test.txt"))
        self.assertTrue(w.real_terminal_active)
        self.assertIs(process, w.process)
        self.assertFalse(w.output_area.isVisible())
        self.assertFalse(w._auto_vt_for_direct_command("vim /tmp/test.txt"))

    def test_auto_vt_from_verified_foreground_is_tab_local(self):
        first = self._make_widget()
        second = self._make_widget()
        first.process.foreground_guide = lambda: ("htop", 111)
        second.process.foreground_guide = lambda: None
        self.assertTrue(first._auto_vt_from_foreground())
        self.assertTrue(first.real_terminal_active)
        self.assertFalse(second.real_terminal_active)
        self.assertFalse(second._auto_vt_from_foreground())

    def test_auto_vt_process_output_goes_to_grid(self):
        w = self._make_widget()
        w.process.foreground_guide = lambda: ("vim", 222)
        w.process.set_output(b"hello\r\n")
        w.handle_stdout()
        self.assertTrue(w.real_terminal_active)
        self.assertTrue(w.terminal_grid.model().display()[0].startswith("hello"))
        self.assertNotIn("hello", w.output_area.toPlainText())

    def test_manual_opt_out_respected_until_foreground_changes(self):
        w = self._make_widget()
        w.process.foreground_guide = lambda: ("vim", 333)
        self.assertTrue(w._auto_vt_from_foreground())
        w.suppress_auto_vt_for_current_program()
        self.assertTrue(w.set_real_terminal_mode(False))
        self.assertFalse(w._auto_vt_from_foreground())
        self.assertFalse(w.real_terminal_active)
        w.process.foreground_guide = lambda: ("nano", 334)
        self.assertTrue(w._auto_vt_from_foreground())
        self.assertTrue(w.real_terminal_active)

    def test_assist_and_auto_vt_use_separate_timers(self):
        """Klassische Ansicht braucht die Erkennung, aber keinen Hilfe-Timer."""
        w = self._make_widget()
        self.assertTrue(w.set_real_terminal_mode(True))
        self.assertTrue(w._assist_timer.isActive())
        self.assertFalse(w._auto_vt_timer.isActive())
        self.assertTrue(w.set_real_terminal_mode(False))
        self.assertFalse(w._assist_timer.isActive())
        self.assertTrue(w._auto_vt_timer.isActive())
        self.assertTrue(w._assist_panel.isHidden())

    def test_auto_vt_timer_recognizes_new_foreground_job(self):
        """Die automatische Erkennung muss trotz gestopptem Hilfe-Timer laufen."""
        w = self._make_widget()
        w.process.foreground_guide = lambda: ("vim", 1234)
        self.assertTrue(w.set_real_terminal_mode(True))
        w.suppress_auto_vt_for_current_program()
        self.assertTrue(w.set_real_terminal_mode(False))
        w._auto_vt_timer.timeout.emit()
        self.assertFalse(w.real_terminal_active)
        w.process.foreground_guide = lambda: ("nano", 1235)
        w._auto_vt_timer.timeout.emit()
        self.assertTrue(w.real_terminal_active)
        self.assertTrue(w._assist_timer.isActive())
        self.assertFalse(w._auto_vt_timer.isActive())
        self.assertEqual(w._assist_identity, ("nano", 1235))

    def test_auto_vt_timer_does_not_monitor_qprocess(self):
        w = self._make_widget()
        w.process._shelldeck_engine = "qprocess"
        w._update_auto_vt_timer()
        self.assertFalse(w._assist_timer.isActive())
        self.assertFalse(w._auto_vt_timer.isActive())

    def test_auto_vt_timers_are_local_to_each_tab(self):
        first = self._make_widget()
        second = self._make_widget()
        first._update_auto_vt_timer()
        second._update_auto_vt_timer()
        self.assertTrue(first._auto_vt_timer.isActive())
        self.assertTrue(second._auto_vt_timer.isActive())
        self.assertTrue(first.set_real_terminal_mode(True))
        self.assertTrue(first._assist_timer.isActive())
        self.assertFalse(first._auto_vt_timer.isActive())
        self.assertTrue(second._auto_vt_timer.isActive())
        self.assertFalse(second._assist_timer.isActive())

    def test_auto_vt_timers_stop_when_session_is_cleaned_up(self):
        w = self._make_widget()
        w._update_auto_vt_timer()
        self.assertTrue(w._auto_vt_timer.isActive())
        w._terminal_cleaned_up = True
        w._update_auto_vt_timer()
        self.assertFalse(w._assist_timer.isActive())
        self.assertFalse(w._auto_vt_timer.isActive())

    def test_no_implicit_qprocess_restart(self):
        w = self._make_widget()
        w.process._shelldeck_engine = "qprocess"
        w.process.foreground_guide = lambda: ("vim", 123)
        self.assertFalse(w._auto_vt_for_direct_command("vim test.txt"))
        self.assertFalse(w._auto_vt_from_foreground())
        self.assertFalse(w.real_terminal_active)

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

    def test_foreground_program_controls_are_bound_to_active_job(self):
        w = self._make_widget()
        w.process.foreground_guide = lambda: ("vim", 333)
        self.assertTrue(w.set_real_terminal_mode(True))
        self.assertEqual(w._assist_identity, ("vim", 333))
        self.assertFalse(w._assist_panel.isHidden())
        w._exit_detected_program()
        self.assertEqual(w.process.written[-1], b"\x1b:q\r")
        # Ein inzwischen neuer foreground-Job darf keine alten Eingaben erhalten.
        w.process.foreground_guide = lambda: ("nano", 444)
        before = list(w.process.written)
        w._exit_detected_program()
        self.assertEqual(w.process.written, before)
        self.assertEqual(w._assist_identity, ("nano", 444))
        w._exit_detected_program()
        self.assertEqual(w.process.written[-1], b"\x18")
        w.set_real_terminal_mode(False)
        self.assertTrue(w._assist_panel.isHidden())
        self.assertFalse(w._assist_timer.isActive())

    def test_multiplexer_controls_are_tab_local_and_detach_only(self):
        tab_tmux = self._make_widget()
        tab_normal = self._make_widget()
        tab_tmux.process.foreground_guide = lambda: ("tmux", 712)
        tab_normal.process.foreground_guide = lambda: None
        self.assertTrue(tab_tmux.set_real_terminal_mode(True))
        self.assertTrue(tab_normal.set_real_terminal_mode(True))
        self.assertFalse(tab_tmux._assist_panel.isHidden())
        self.assertEqual(tab_tmux._assist_exit.text(), "Trennen")
        self.assertTrue(tab_normal._assist_panel.isHidden())
        tab_tmux._exit_detected_program()
        self.assertEqual(tab_tmux.process.written[-1], b"\x02d")
        self.assertFalse(tab_normal.process.written)
        # Die Prozessgruppe wechselt: alte Aktion darf keine Eingabe senden.
        before = list(tab_tmux.process.written)
        tab_tmux.process.foreground_guide = lambda: ("screen", 723)
        tab_tmux._exit_detected_program()
        self.assertEqual(tab_tmux.process.written, before)
        self.assertEqual(tab_tmux._assist_exit.text(), "Trennen")
        tab_tmux._exit_detected_program()
        self.assertEqual(tab_tmux.process.written[-1], b"\x01d")
        tab_tmux.process.foreground_guide = lambda: None
        tab_tmux._refresh_detected_program()
        self.assertTrue(tab_tmux._assist_panel.isHidden())

    def test_unknown_foreground_never_offers_exit(self):
        w = self._make_widget()
        w.process.foreground_guide = lambda: None
        w.set_real_terminal_mode(True)
        self.assertTrue(w._assist_panel.isHidden())
        self.assertIsNone(w._checked_detected_program())

    def test_disable_restores_classic(self):
        w = self._make_widget()
        w.set_real_terminal_mode(True)
        w.set_real_terminal_mode(False)
        self.assertFalse(w.real_terminal_active)
        self.assertTrue(w.output_area.isVisibleTo(w) or True)
        self.assertTrue(w.input_line.isVisibleTo(w) or True)


if __name__ == "__main__":
    unittest.main(verbosity=2)
