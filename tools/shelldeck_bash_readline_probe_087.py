"""Reproduzierbarer Bash/Readline-VT-Test fuer ShellDeck.

Nur feste, harmlose Testbefehle; keine persoenliche Bash-History oder Eingaben.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import pty
import select
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path

from shelldeck_key_encoding import encode_key
from shelldeck_vt_screen import VtScreen

STEPS = (
    ("short", b"echo short\r", "TEST$ ", None),
    ("long", b"echo a-much-longer-test-command\r", "TEST$ ", None),
    ("up-long", encode_key("Up"), "echo a-much-longer-test-command", "end"),
    ("up-short", encode_key("Up"), "echo short", "end"),
    ("down-long", encode_key("Down"), "echo a-much-longer-test-command", "end"),
    ("down-empty", encode_key("Down"), "TEST$ ", "end"),
    ("type-new", b"echo NEW", "echo NEW", "end"),
)


def _read_until_quiet(fd, quiet=0.12, deadline=2.0):
    data = bytearray()
    start = last = time.monotonic()
    while time.monotonic() - start < deadline:
        ready, _, _ = select.select([fd], [], [], 0.04)
        if ready:
            try:
                chunk = os.read(fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            data.extend(chunk)
            last = time.monotonic()
        elif time.monotonic() - last >= quiet:
            break
    return bytes(data)


# ANSI-Codes der Bash-Promptdefinition sind mit \[ und \] als nichtdruckbar
# markiert. Das entkoppelt Readlines Cursorbreite von den Escape-Bytes.
PROMPTS = {
    "plain": ("TEST$ ", "TEST$ "),
    "colored": (r"\[\e[32m\]((.venv) )\[\e[0m\] "
                r"\[\e[32m\]torsten@Ubuntu\[\e[0m\]:"
                r"\[\e[6;94m\]~/Programme/visual-edit-terminal\[\e[0m\]$ ",
                "((.venv) ) torsten@Ubuntu:~/Programme/visual-edit-terminal$ "),
}


def evaluate_cursor_and_line(display_line, cursor_x, prompt_text, command):
    """Prueft genaue sichtbare Befehlszeile und Cursor auch nach Leerzeichen.

    Nur rechte Auffuell-Leerzeichen des VT-Zellgitters werden ignoriert.
    Die Sollposition enthaelt das abschliessende Prompt-Leerzeichen.
    """
    expected = prompt_text + command
    return {
        "expected_line": expected,
        "line_matches": display_line.rstrip(" ") == expected.rstrip(" "),
        "cursor_at_end": int(cursor_x) == len(expected),
    }


def run(rows=24, cols=100, prompt_mode="plain"):
    if prompt_mode not in PROMPTS:
        raise ValueError("Unbekanntes Prompt-Profil")
    ps1, visible_prompt = PROMPTS[prompt_mode]
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', rows, cols, 0, 0))
    env = dict(os.environ, TERM="xterm-256color", HISTFILE="/dev/null",
               HISTSIZE="100", HISTFILESIZE="0", PROMPT_COMMAND="",
               PS1=ps1, PS2="> ", INPUTRC="/dev/null")
    process = subprocess.Popen(["bash", "--noprofile", "--norc", "-i"],
                               stdin=slave, stdout=slave, stderr=slave,
                               start_new_session=True, env=env, close_fds=True)
    os.close(slave)
    model = VtScreen(rows=rows, cols=cols, enable_history=True)
    report = []
    try:
        model.feed(_read_until_quiet(master, deadline=3.0))
        for label, written, expected, cursor_policy in STEPS:
            os.write(master, written)
            data = _read_until_quiet(master)
            model.feed(data)
            display = model.display()
            cursor = model.cursor
            line = display[cursor['y']].rstrip(" ")
            # Teste die gesamte Zeile, damit alte Reste hinter kurzen Befehlen auffallen.
            command = "" if label in ("short", "long", "down-empty") else expected
            verdict = evaluate_cursor_and_line(display[cursor['y']], cursor['x'],
                                                visible_prompt, command)
            report.append({"step": label, "expected": verdict["expected_line"],
                           "line": line, "cursor_x": cursor['x'],
                           "cursor_y": cursor['y'], "expected_present": verdict["line_matches"],
                           "cursor_at_end": verdict["cursor_at_end"],
                           "bytes_received": len(data)})
    finally:
        try: os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError: pass
        try: process.wait(timeout=1)
        except subprocess.TimeoutExpired: process.kill(); process.wait()
        os.close(master)
    return {"geometry": {"rows": rows, "cols": cols}, "prompt_mode": prompt_mode,
            "steps": report,
            "passed": all(s['expected_present'] and s['cursor_at_end'] for s in report)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path.home() / 'Downloads' / 'ShellDeck_Bash_Readline_087.json')
    parser.add_argument('--prompt', choices=tuple(PROMPTS), default='plain')
    args = parser.parse_args()
    report = run(prompt_mode=args.prompt)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for step in report['steps']:
        print(f"{step['step']}: text={step['expected_present']} cursor={step['cursor_at_end']}")
    print(f"Bericht: {args.output}")
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
