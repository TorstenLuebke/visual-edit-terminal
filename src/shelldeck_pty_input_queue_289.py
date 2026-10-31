"""Lossless, Qt-independent POSIX PTY input staging for ShellDeck.

Writing a whole clipboard to an O_NONBLOCK PTY is not atomic: write() may
accept a prefix only, or raise EAGAIN. Keep the remainder in FIFO order and
feed it in small, timed writes via the GUI's QTimer. No user input is logged.
"""

from __future__ import annotations

from collections import deque
import errno


class PtyInputQueue:
    """A bounded byte FIFO; one non-blocking PTY write per drain call.

    The caller owns the timer and must keep calling drain_once while pending.
    The queue is not thread-safe; enqueue/drain/clear belong to the Qt GUI
    thread, not the background PTY output reader.
    """

    def __init__(self, *, chunk_bytes: int = 256,
                 max_pending_bytes: int = 32 * 1024 * 1024):
        if chunk_bytes < 1 or max_pending_bytes < 1:
            raise ValueError("PTY input queue limits must be positive")
        self.chunk_bytes = int(chunk_bytes)
        self.max_pending_bytes = int(max_pending_bytes)
        self._parts = deque()
        self._offset = 0
        self.pending_bytes = 0

    def enqueue(self, data: bytes) -> bool:
        """Accept all bytes or reject without changing the queue."""
        payload = bytes(data)
        if len(payload) > self.max_pending_bytes - self.pending_bytes:
            return False
        if payload:
            self._parts.append(payload)
            self.pending_bytes += len(payload)
        return True

    def drain_once(self, writer) -> int:
        """Attempt <= chunk_bytes; retain any bytes not actually written.

        EAGAIN/EINTR are transient: the next timer tick retries. Other errors
        are propagated so the owner can report the failure and drop the queue.
        """
        if not self._parts:
            return 0
        part = self._parts[0]
        offered = part[self._offset:self._offset + self.chunk_bytes]
        try:
            written = writer(offered)
        except OSError as exc:
            if exc.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                return 0
            raise
        if written is None:
            raise OSError("POSIX PTY write did not return a byte count")
        written = int(written)
        if written < 0 or written > len(offered):
            raise OSError("POSIX PTY returned invalid write length")
        if written:
            self._offset += written
            self.pending_bytes -= written
            if self._offset == len(part):
                self._parts.popleft()
                self._offset = 0
        return written

    def clear(self) -> None:
        """Discard unsent bytes when a session ends or the user interrupts."""
        self._parts.clear()
        self._offset = 0
        self.pending_bytes = 0
