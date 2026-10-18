"""Real-PTY ls/VT comparison at fixed widths; no GUI or production changes.

Run: QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -v \
    src/test_shelldeck_pty_columns_234.py
"""
from __future__ import annotations

import os
import select
import struct
import subprocess
import sys
import termios
import time
import unittest

try:
    from shelldeck_vt_screen import VtScreen, is_available
except ImportError:
    VtScreen = None
    def is_available():
        return False


def capture_ls(cols: int, tabsize: int) -> bytes:
    """Run GNU ls with PTY stdout and fixed winsize. Capture exact raw bytes."""
    master, slave = os.openpty()
    try:
        import fcntl
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack('HHHH', 32, cols, 0, 0))
        # Retain the PTY's normal output processing (notably NL -> CRLF).
        env = dict(os.environ, COLUMNS=str(cols), TERM='xterm-256color', LC_ALL='C')
        proc = subprocess.Popen(['ls', '-C', f'--tabsize={tabsize}', '--color=never', '/'],
                                stdin=subprocess.DEVNULL, stdout=slave,
                                stderr=subprocess.PIPE, env=env)
        os.close(slave)
        slave = -1
        result = bytearray()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            ready, _, _ = select.select([master], [], [], 0.05)
            if ready:
                try:
                    block = os.read(master, 65536)
                except OSError:  # PTY EOF on Linux
                    break
                if not block:
                    break
                result.extend(block)
            if proc.poll() is not None and not ready:
                break
        try:
            _, stderr = proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
            raise AssertionError('ls timed out')
        if proc.returncode:
            raise AssertionError(f'ls failed: {stderr!r}')
        return bytes(result)
    finally:
        os.close(master)
        if slave >= 0:
            os.close(slave)


def reference_layout(raw: bytes, cols: int) -> list[str]:
    """Independent printable ASCII + CR/LF/TAB reference, not pyte-based.

    This deliberately supports only the control repertoire present in ls -C
    with --color=never. Unexpected controls fail the test instead of guessing.
    """
    lines: list[list[str]] = [[' '] * cols]
    x = 0
    pending_wrap = False
    for code in raw:
        if code == 13:
            x = 0
            pending_wrap = False
        elif code == 10:
            lines.append([' '] * cols)
            pending_wrap = False
        elif code == 9:
            # VT horizontal-tab: move to next stop (every 8 columns).
            x = min(cols - 1, ((x // 8) + 1) * 8)
            pending_wrap = False
        elif 32 <= code < 127:
            if pending_wrap:
                lines.append([' '] * cols)
                x = 0
                pending_wrap = False
            lines[-1][x] = chr(code)
            if x == cols - 1:
                pending_wrap = True
            else:
                x += 1
        else:
            raise AssertionError(f'Unsupported control byte in ls output: {code:#x}')
    return [''.join(line).rstrip() for line in lines]


@unittest.skipUnless(sys.platform.startswith('linux'), 'POSIX PTY Linux reference test')
@unittest.skipUnless(is_available(), 'pyte not installed')
class RealPtyColumns234(unittest.TestCase):
    def test_ls_stream_matches_independent_terminal_layout(self):
        for cols in (80, 118, 148, 235):
            for tabsize in (1, 8):
                with self.subTest(cols=cols, tabsize=tabsize):
                    raw = capture_ls(cols, tabsize)
                    self.assertTrue(raw, 'ls returned no bytes')
                    expected = reference_layout(raw, cols)
                    model = VtScreen(rows=max(32, len(expected) + 2), cols=cols,
                                     history=200)
                    # Split bytes deliberately to test incremental PTY feeds.
                    for pos in range(0, len(raw), 17):
                        model.feed(raw[pos:pos + 17])
                    actual = [line.rstrip() for line in model.display()]
                    # Compare rows containing printed output, including empty
                    # rows between them; the rest of the screen is blank.
                    self.assertEqual(actual[:len(expected)], expected,
                                     f'width={cols} tabsize={tabsize} raw={raw!r}')

    def test_ls_raw_stream_contains_no_cursor_positioning_sequences(self):
        for tabsize in (1, 8):
            with self.subTest(tabsize=tabsize):
                raw = capture_ls(148, tabsize)
                self.assertNotIn(b'\x1b', raw,
                                 'Unexpected ANSI escape: update reference before trusting it')

if __name__ == '__main__':
    unittest.main()
