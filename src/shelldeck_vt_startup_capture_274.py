"""Opt-in, bounded recording of the very first ShellDeck VT/PTY output.

The environment flag is used only for an explicitly confirmed application
restart. It is consumed before spawning the first new PTY shell. The captured
bytes may contain private data and are only written when the user presses Stop.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from secrets import token_hex

from shelldeck_startup_session import _relaunch_executable

STARTUP_TRACE_ENV = "SHELLDECK_VT_STARTUP_TRACE_DIR"
RESTART_PARENT_PID_ENV = "SHELLDECK_VT_RESTART_PARENT_PID"
STARTUP_TRACE_TARGET_ENV = "SHELLDECK_VT_STARTUP_TRACE_TAB_INDEX"
_claimed = False


def requested_startup_trace_tab_index(environ=None):
    """Saved-tab index selected before restarting; never fall back silently."""
    settings = os.environ if environ is None else environ
    value = settings.get(STARTUP_TRACE_TARGET_ENV, "")
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    return index if 0 <= index < 10000 else None


def claim_startup_trace_directory(environ=None, *, eligible=True):
    """Only the explicitly chosen restored tab can claim the recording."""
    global _claimed
    if not eligible or _claimed:
        return None
    settings = os.environ if environ is None else environ
    value = settings.get(STARTUP_TRACE_ENV, "").strip()
    if not value:
        return None
    target = Path(value).expanduser()
    if not target.is_absolute() or not target.is_dir():
        raise ValueError(f"{STARTUP_TRACE_ENV} requires an existing absolute directory")
    _claimed = True
    # Do not leak the permission to a child shell, subprocess or its children.
    settings.pop(STARTUP_TRACE_ENV, None)
    return target


def create_private_trace_directory(home=None):
    """Create a private per-run directory (no shared /tmp, no overwrites)."""
    base = Path(home) if home is not None else Path.home()
    downloads = base / "Downloads"
    parent = downloads if downloads.is_dir() else base
    return Path(tempfile.mkdtemp(prefix="ShellDeck_Startdiagnose_", dir=parent))


def _private_new_file(path: Path, data: bytes):
    """Create-only and owner-only; never overwrite a previous recording."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as output:
        output.write(data)


def export_startup_trace(directory, trace, *, start_model: str, end_model: str,
                         geometry, session_generation=0):
    """Write a bounded startup trace and the matching VT model snapshots.

    The caller stops the trace first. No implicit input recording or terminal
    state changes occur. A random capture id separates simultaneous tabs.
    """
    path = Path(directory)
    if not path.is_dir():
        raise ValueError("Startup capture directory is no longer available")
    stem = f"ShellDeck_VT_Start_{os.getpid()}_{token_hex(6)}"
    destination = path / (stem + ".bin")
    output = trace.stop()
    rows, cols = geometry
    metadata = (f"bytes={len(output)}\ntruncated={trace.truncated}\n"
                f"start_rows={rows}\nstart_cols={cols}\n"
                f"shell_generation={int(session_generation)}\n"
                f"trace_source=grid_feed\n")
    files = {
        destination: output,
        path / (stem + ".meta.txt"): metadata.encode("utf-8"),
        path / (stem + "_Ereignisse.jsonl"): trace.events_jsonl().encode("utf-8"),
        path / (stem + "_Startmodell.txt"): start_model.encode("utf-8"),
        path / (stem + "_Endmodell.txt"): end_model.encode("utf-8"),
    }
    for filename, content in files.items():
        _private_new_file(filename, content)
    return destination


def relaunch_command(argv=None):
    """Relaunch the app, not arbitrary start commands or user-supplied files."""
    args = list(sys.argv if argv is None else argv)
    if not args:
        raise ValueError("ShellDeck start target is not available")
    executable = _relaunch_executable(args)
    launcher = Path(args[0])
    if launcher.suffix.lower() in {".py", ".pyw"}:
        if not launcher.is_file():
            raise FileNotFoundError(f"ShellDeck script not found: {launcher}")
        return [executable, str(launcher.resolve())]
    return [executable]


def launch_diagnostic_restart(directory, argv=None, *, target_index=0):
    """Restart with an exact saved-tab target; do not capture another tab."""
    if not isinstance(target_index, int) or not 0 <= target_index < 10000:
        raise ValueError("Invalid ShellDeck startdiagnose tab index")
    command = relaunch_command(argv)
    env = os.environ.copy()
    env[STARTUP_TRACE_ENV] = str(Path(directory).resolve())
    env[STARTUP_TRACE_TARGET_ENV] = str(target_index)
    env[RESTART_PARENT_PID_ENV] = str(os.getpid())
    return subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                            start_new_session=(os.name == "posix"),
                            close_fds=True)


def wait_for_restarted_parent(environ=None, *, timeout=12.0):
    """Before Qt initialization, let the previous GUI save its workspace."""
    settings = os.environ if environ is None else environ
    pid_text = settings.pop(RESTART_PARENT_PID_ENV, "")
    if not pid_text:
        return
    try:
        pid = int(pid_text)
    except ValueError:
        return
    if pid <= 1 or pid == os.getpid():
        return
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            # Includes absent PIDs and platforms where signal 0 is unsupported.
            return
        time.sleep(0.05)
