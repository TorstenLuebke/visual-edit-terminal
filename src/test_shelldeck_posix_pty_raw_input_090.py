"""Patch 090: verlustfreie Eingabe zum POSIX-PTY (inklusive Bash-Pfeiltasten)."""
import os
import sys
import pytest

pytest.importorskip("PySide6")
from shelldeck_terminal_widget import PosixPtyChild, PtyTerminalProcess


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-PTY")
@pytest.mark.parametrize("payload", [
    b"\x1b[A", b"\x1b[B", b"\x1b[200~a\x1b[201~",
    b"\xc3", b"\xa4", b"\x00\xff\x80", b"echo longer\r",
])
def test_posix_child_writes_exact_bytes(monkeypatch, payload):
    child = object.__new__(PosixPtyChild)
    child._closed = False
    child.fd = 100
    child.isalive = lambda: True
    written = []
    monkeypatch.setattr(os, "write", lambda fd, data: written.append((fd, data)) or len(data))
    assert child.write(payload) == len(payload)
    assert written == [(100, payload)]


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-PTY")
def test_pty_process_forwards_bytes_without_transcoding(monkeypatch):
    child = object.__new__(PosixPtyChild)
    child._closed = False
    child.fd = 101
    child.isalive = lambda: True
    sent = []
    monkeypatch.setattr(os, "write", lambda fd, data: sent.append(bytes(data)) or len(data))
    process = PtyTerminalProcess()
    process._running = True
    process._pty = child
    for payload in (b"\x1b[A", b"\x1b[B", b"\xc3", b"\xa4", b"\xff"):
        assert process.write(payload) == len(payload)
    assert sent == [b"\x1b[A", b"\x1b[B", b"\xc3", b"\xa4", b"\xff"]
