"""Patch 086: cursor coordinates are content-free and ANSI blue readable."""
import pytest

pytest.importorskip("PySide6")
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication
from shelldeck_terminal_grid import TerminalGridView, _cached_terminal_color


def test_ansi_blue_is_readable_on_dark_background():
    blue = _cached_terminal_color("blue")
    assert blue.isValid()
    # Avoid the old #0000ee on ShellDeck's near-black background.
    assert blue.lightness() >= 120
    assert _cached_terminal_color("0000ee") == QColor("#0000ee")  # truecolor untouched


def test_cursor_diagnostic_does_not_export_terminal_content():
    app = QApplication.instance() or QApplication([])
    widget = TerminalGridView()
    if not widget.is_usable():
        pytest.skip("pyte is not available")
    widget.feed(b"\x1b[2;4HSECRET")
    data = widget.cursor_diagnostic()
    assert set(data) == {"x", "y", "rows", "cols", "cell_width", "cell_height",
                         "paint_x", "paint_y", "focus", "hidden"}
    assert data["x"] == widget.model().cursor["x"]
    assert data["y"] == widget.model().cursor["y"]
    assert data["paint_x"] == int(data["x"] * data["cell_width"])
    assert "SECRET" not in repr(data)
