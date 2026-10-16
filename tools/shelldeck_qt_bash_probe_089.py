"""Qt-Tastatur -> TerminalGridView.dataReady -> Bash-PTY -> VT-Zellen.

Nur isolierte Bash ohne Nutzer-History; der Bericht speichert ausschließlich
fest vorgegebene Testzeilen, niemals eine reale Sitzung.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import signal
import struct
import subprocess
import termios
from pathlib import Path

from shelldeck_bash_readline_probe_087 import (
    PROMPTS, _read_until_quiet, evaluate_cursor_and_line,
)

_QT_APP = None

STEPS = (
    ("short", "echo short", "enter", ""),
    ("long", "echo a-much-longer-test-command", "enter", ""),
    ("up-long", None, "up", "echo a-much-longer-test-command"),
    ("up-short", None, "up", "echo short"),
    ("down-long", None, "down", "echo a-much-longer-test-command"),
    ("down-empty", None, "down", ""),
    ("type-new", "echo NEW", "type", "echo NEW"),
    ("up-again", None, "up", "echo a-much-longer-test-command"),
    ("up-short-again", None, "up", "echo short"),
)


def run(prompt_mode="colored", rows=24, cols=100):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from shelldeck_terminal_grid import TerminalGridView

    global _QT_APP
    app = QApplication.instance() or QApplication([])
    _QT_APP = app
    ps1, visible_prompt = PROMPTS[prompt_mode]
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    env = dict(os.environ, TERM="xterm-256color", HISTFILE="/dev/null",
               HISTSIZE="100", HISTFILESIZE="0", PROMPT_COMMAND="",
               PS1=ps1, PS2="> ", INPUTRC="/dev/null")
    process = subprocess.Popen(["bash", "--noprofile", "--norc", "-i"],
                               stdin=slave, stdout=slave, stderr=slave,
                               start_new_session=True, env=env, close_fds=True)
    os.close(slave)
    grid = TerminalGridView(rows=rows, cols=cols, enable_history=False)
    # Wie im echten ShellDeck: Qt-Daten-Signal mit dem PTY-Writer verbinden.
    sent = []
    def write_to_pty(payload):
        data = bytes(payload)
        sent.append(len(data))  # Keine Speicherung eingegebener Inhalte.
        os.write(master, data)
    grid.dataReady.connect(write_to_pty)
    report = []
    try:
        grid.feed(_read_until_quiet(master, deadline=3.0))
        for label, typed, action, expected_command in STEPS:
            before = len(sent)
            if typed:
                QTest.keyClicks(grid, typed)
            if action == "enter":
                QTest.keyClick(grid, Qt.Key.Key_Return)
            elif action == "up":
                QTest.keyClick(grid, Qt.Key.Key_Up)
            elif action == "down":
                QTest.keyClick(grid, Qt.Key.Key_Down)
            app.processEvents()
            data = _read_until_quiet(master)
            grid.feed(data)
            screen = grid.model()
            cursor = screen.cursor
            line = screen.display()[cursor["y"]]
            verdict = evaluate_cursor_and_line(
                line, cursor["x"], visible_prompt, expected_command)
            paint = grid.cursor_diagnostic()
            result = {
                "step": label,
                "expected_present": verdict["line_matches"],
                "cursor_at_end": verdict["cursor_at_end"],
                "cursor_geometry_matches": paint is not None and
                     paint["x"] == cursor["x"] and paint["y"] == cursor["y"],
                "qt_write_calls": len(sent) - before,
                "pty_output_bytes": len(data),
                "cursor_x": cursor["x"], "cursor_y": cursor["y"],
            }
            report.append(result)
    finally:
        grid.close()
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.wait(timeout=1)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
        os.close(master)
    return {"mode": prompt_mode, "geometry": {"rows": rows, "cols": cols},
            "steps": report,
            "passed": all(r["expected_present"] and r["cursor_at_end"]
                          and r["cursor_geometry_matches"] for r in report)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=Path.home() / "Downloads" / "ShellDeck_Qt_Bash_089.json")
    args = parser.parse_args()
    results = {mode: run(mode) for mode in ("plain", "colored")}
    report = {"profiles": results, "passed": all(r["passed"] for r in results.values())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    for mode, result in results.items():
        print(f"{mode}: {'OK' if result['passed'] else 'ABWEICHUNG'}")
        for step in result['steps']:
            if not all(step[k] for k in ("expected_present", "cursor_at_end", "cursor_geometry_matches")):
                print("  Fehler:", step["step"])
    print("Bericht:", args.output)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
