"""Smoke-Test fuer das ausgelagerte ShellDeck-Terminal-Widget.

Ausfuehren (aus dem src-Ordner):

    python smoke_test_terminal_widget.py

Prueft: Import ohne Hauptfenster, Standalone-Instanz, stabile API
(run_command, append_*, set/get_working_directory, send_text/send_return,
stop_current_process, clear_output). Beendet sich selbst mit Exitcode 0
bei Erfolg. Fuer Umgebungen ohne Display: QT_QPA_PLATFORM=offscreen setzen.
"""

import sys
import time

from PySide6.QtWidgets import QApplication

from shelldeck_terminal_widget import DefaultTerminalHost, ShellDeckTerminalWidget


def main() -> int:
    app = QApplication(sys.argv)

    terminal = ShellDeckTerminalWidget()
    assert isinstance(terminal.window, DefaultTerminalHost)

    terminal.append_system_message("[Smoke-Test] Systemmeldung")
    terminal.append_output("Smoke-Test Ausgabe\n")
    terminal.append_error("Smoke-Test Fehler\n")
    for _ in range(80):
        app.processEvents()
        time.sleep(0.005)
    text = terminal.output_area.toPlainText()
    assert "[Smoke-Test] Systemmeldung" in text
    assert "Smoke-Test Ausgabe" in text
    assert "Smoke-Test Fehler" in text

    terminal.run_command("echo SMOKE_TEST_OK")
    deadline = time.time() + 10
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)
        if "SMOKE_TEST_OK" in terminal.output_area.toPlainText():
            break
    else:
        print("FEHLER: run_command lieferte keine Ausgabe")
        return 1

    assert terminal.get_working_directory()
    terminal.send_text("echo TEIL")
    terminal.send_return()
    terminal.stop_current_process()
    terminal.clear_output()
    terminal.stop_process(fast=True)

    print("Smoke-Test OK: ShellDeckTerminalWidget funktioniert ohne Hauptfenster.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
