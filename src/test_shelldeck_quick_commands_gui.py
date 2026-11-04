"""Qt-GUI-Checks (mit QT_QPA_PLATFORM=offscreen starten).

Ein direktes real-PTY/ConPTY-Regressionstest bleibt auf den Zielplattformen nötig.
"""
import os
import sys
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMainWindow, QTextEdit
from PySide6.QtCore import Qt
from shelldeck_quick_commands_ui import QuickCommandsDock
from shelldeck_quick_commands import make_default_commands


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    instance = QApplication.instance() or QApplication([])
    yield instance


def test_dock_resize_does_not_clear_text_or_recreate_document(app):
    window = QMainWindow()
    terminal = QTextEdit()
    terminal.setPlainText("LANGE ZEILE " * 40 + "\n" + "historie\n" * 70)
    doc = terminal.document()
    original = terminal.toPlainText()
    window.setCentralWidget(terminal)
    dock = QuickCommandsDock(window)
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, dock)
    dock.populate(make_default_commands(), "bash")
    window.resize(900, 650)
    window.show()
    app.processEvents()
    try:
        dock.set_pinned(False)
        for _ in range(40):
            dock.expand()
            app.processEvents()
            dock.collapse()
            app.processEvents()
            assert terminal.document() is doc
            assert terminal.toPlainText() == original
        dock.set_pinned(True)
        app.processEvents()
        assert terminal.toPlainText() == original
    finally:
        window.close()
