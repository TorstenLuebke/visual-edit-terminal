"""Protect GUI startup from unwanted reads of its caller's terminal.

This module deliberately has no Qt dependencies. It is called before importing
PySide6 so a stopped GUI can be recovered before Qt or terminal tabs start.
"""

import os
from pathlib import Path
import signal
import subprocess
import sys


def has_controlling_terminal():
    """True when a controlling terminal exists, even with stdin redirected.

    A stopped process will often have a different foreground group *after*
    bash regains control. That observation does not establish its initial
    foreground state, so comparing process groups is not a safe guard here.
    """
    if os.name != "posix":
        return False
    try:
        fd = os.open("/dev/tty", os.O_RDONLY | getattr(os, "O_NOCTTY", 0))
    except OSError:
        return False
    try:
        os.tcgetpgrp(fd)
        return True
    except (OSError, ValueError):
        return False
    finally:
        os.close(fd)


def relaunch_without_controlling_tty(argv=None):
    """Isolate GUI starts launched from a terminal, not normal desktop starts.

    Returns None if no action was needed; otherwise returns the detached child
    process's exit code. The supervising foreground command keeps waiting, so
    closing the GUI still returns control to the launching shell as usual.
    """
    if os.name != "posix":
        return None
    if not has_controlling_terminal():
        return None

    args = list(sys.argv if argv is None else argv)
    executable = sys.executable
    # Source run: python src/main.py. Nuitka standalone: sys.executable is
    # the compiled application and must NOT be given its own path as a script.
    if args and Path(args[0]).suffix.lower() in {".py", ".pyw"}:
        command = [executable, *args]
    else:
        command = [executable, *args[1:]]

    try:
        child = subprocess.Popen(
            command, stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as exc:
        print(f"ShellDeck: Start in separater Terminalsitzung fehlgeschlagen: {exc}", file=sys.stderr)
        return 1

    # Forward termination to avoid leaving a running GUI behind when the
    # original launcher (e.g. a terminal command) is cancelled.
    previous_handlers = {}

    def forward_termination(_signum, _frame):
        child.terminate()

    for name in ("SIGTERM", "SIGHUP"):
        signum = getattr(signal, name, None)
        if signum is not None:
            try:
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, forward_termination)
            except (OSError, ValueError):
                previous_handlers.pop(signum, None)
    try:
        try:
            status = child.wait()
            return 128 - status if status < 0 else status
        except KeyboardInterrupt:
            child.terminate()
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            return 130
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, previous)
