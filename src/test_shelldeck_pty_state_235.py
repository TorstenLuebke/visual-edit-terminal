"""PTY state comparison for ShellDeck's ls column anomalies (Linux only).

Run: .venv/bin/python -m pytest -v -s src/test_shelldeck_pty_state_235.py
This test neither changes production code nor writes terminal settings.
"""
from __future__ import annotations

import sys
import unittest

from test_shelldeck_pty_columns_234 import capture_ls

try:
    from shelldeck_vt_screen import VtScreen, is_available
except ImportError:
    VtScreen = None

    def is_available():
        return False


def _make_screen(cols: int) -> VtScreen:
    return VtScreen(rows=40, cols=cols, history=200)


def _feed_chunks(screen: VtScreen, raw: bytes, chunk: int) -> None:
    for offset in range(0, len(raw), chunk):
        screen.feed(raw[offset:offset + chunk])


def _nonempty_lines(screen: VtScreen) -> list[str]:
    return [line.rstrip() for line in screen.display() if line.strip()]


def _edge_fragments(screen: VtScreen) -> list[tuple[int, str, str]]:
    """Report suspicious final-column characters, without treating them as proof."""
    result = []
    lines = screen.display()
    for index, line in enumerate(lines[:-1]):
        if len(line) >= screen.cols and line[-1].isalpha():
            next_line = lines[index + 1].lstrip()
            if next_line and next_line[0].isalpha():
                result.append((index, line[-1], next_line[:24]))
    return result


@unittest.skipUnless(sys.platform.startswith('linux'), 'needs POSIX PTY and GNU ls')
@unittest.skipUnless(is_available(), 'pyte not installed')
class PtyStateComparison235(unittest.TestCase):
    def test_ls_is_invariant_to_feed_chunks_after_prompt(self):
        """Compare identical bytes after a fresh prompt across PTY read chunking."""
        for cols in (80, 118, 148, 235):
            for tabsize in (1, 8):
                with self.subTest(cols=cols, tabsize=tabsize):
                    raw = capture_ls(cols, tabsize)
                    prompt = b'((.venv) ) bash-5.3$ ls /\r\n'
                    expected = _make_screen(cols)
                    expected.feed(prompt)
                    expected.feed(raw)
                    for chunk in (1, 7, 17, 4096):
                        actual = _make_screen(cols)
                        _feed_chunks(actual, prompt + raw, chunk)
                        self.assertEqual(actual.display(), expected.display(),
                                         f'cols={cols} tabsize={tabsize} chunk={chunk}')
                        self.assertEqual(actual.cursor, expected.cursor)

    def test_readline_redraw_does_not_change_subsequent_ls_cells(self):
        """A CR/erase/readline-style redraw must not contaminate later output."""
        for cols in (80, 118, 148, 235):
            with self.subTest(cols=cols):
                raw = capture_ls(cols, 8)
                baseline = _make_screen(cols)
                baseline.feed(b'((.venv) ) bash-5.3$ ls /\r\n')
                baseline.feed(raw)
                redraw = _make_screen(cols)
                redraw.feed(b'junk prompt\r\x1b[2K')
                redraw.feed(b'((.venv) ) bash-5.3$ ls /\r\n')
                redraw.feed(raw)
                self.assertEqual(_nonempty_lines(redraw), _nonempty_lines(baseline))
                self.assertEqual(redraw.cursor, baseline.cursor)

    def test_report_edge_fragments_in_real_ls_stream(self):
        """Diagnostic only: surface suspicious edge splits in verbose pytest output."""
        for cols in (80, 118, 148, 235):
            for tabsize in (1, 8):
                with self.subTest(cols=cols, tabsize=tabsize):
                    screen = _make_screen(cols)
                    screen.feed(capture_ls(cols, tabsize))
                    fragments = _edge_fragments(screen)
                    print(f'PTY state cols={cols} tabsize={tabsize}: '
                          f'cursor={screen.cursor} edge_fragments={fragments}', flush=True)
                    self.assertEqual(screen.cols, cols)


if __name__ == '__main__':
    unittest.main()
