import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication
import shelldeck_terminal_widget as widget


app = QApplication.instance() or QApplication([])


def run_case(label, selected_engine, expected_engine, pty_available=True):
    host = widget.DefaultTerminalHost()
    host.shell_type = "bash"
    host.terminal_engine = selected_engine

    original_availability_message = widget.PtyTerminalProcess.availability_message

    try:
        widget.PtyTerminalProcess.availability_message = staticmethod(
            lambda: "" if pty_available else "PTY für Test nicht verfügbar"
        )

        normalized = host.normalize_terminal_engine(selected_engine)
        use_pty = host.should_use_pty_backend(
            shell_type="bash",
            engine=normalized,
        )
        actual = "pty" if use_pty else "qprocess"

        ok = actual == expected_engine
        print(
            ("  OK   " if ok else "  FEHL "),
            f"{label:48s} Auswahl={normalized:8s} aktiv={actual}",
        )
        return ok
    finally:
        widget.PtyTerminalProcess.availability_message = original_availability_message


def main():
    cases = [
        (
            "Automatisch mit verfügbarem PTY",
            "auto",
            "pty",
            True,
        ),
        (
            "Bewusst QProcess gewählt",
            "qprocess",
            "qprocess",
            True,
        ),
        (
            "Bewusst PTY gewählt und verfügbar",
            "pty",
            "pty",
            True,
        ),
        (
            "Automatisch ohne verfügbares PTY",
            "auto",
            "qprocess",
            False,
        ),
        (
            "Bewusst PTY gewählt, aber nicht verfügbar",
            "pty",
            "qprocess",
            False,
        ),
    ]

    failed = 0
    for label, selected, expected, available in cases:
        if not run_case(label, selected, expected, available):
            failed += 1

    print()
    print("Plattform:", sys.platform)
    print("Reales PTY verfügbar:", widget.PtyTerminalProcess.is_available())
    print("Fehler:", failed)

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
