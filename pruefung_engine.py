import sys, os
sys.path.insert(0, '.')
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import shelldeck_terminal_widget as W
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])

def make(user_choice, engine):
    host = W.DefaultTerminalHost()
    host.shell_type = "bash"
    host.terminal_engine = engine
    host.terminal_engine_is_user_choice = user_choice
    tab = W.ShellDeckTerminalWidget(window=host, shell_type="bash", terminal_engine=engine)
    tab.stop_process(fast=True)
    tab.terminal_engine = engine
    proc = tab.create_shell_process()
    return tab.actual_terminal_engine(), tab.terminal_engine

cases = [
    ("Vorgabe qprocess, keine Wahl -> Auto-PTY", False, "qprocess", "pty"),
    ("bewusst qprocess gewaehlt      -> bleibt", True,  "qprocess", "qprocess"),
    ("bewusst pty gewaehlt           -> bleibt", True,  "pty",      "pty"),
    ("Vorgabe pty, keine Wahl        -> pty",    False, "pty",      "pty"),
]
bad = 0
for label, uc, engine, expect in cases:
    actual, stored = make(uc, engine)
    ok = actual == expect and stored == expect
    bad += 0 if ok else 1
    print(("  OK   " if ok else "  FEHL "), f"{label:44s} aktiv={actual:9s} gespeichert={stored}")
print()
print("PTY verfuegbar:", W.PtyTerminalProcess.is_available())
print("FEHLER:", bad)
sys.exit(1 if bad else 0)
