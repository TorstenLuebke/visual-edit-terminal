"""Patch 286: echte Zelltext-Neuformatierung statt Abschneiden beim Verkleinern.

Ausfuehren: PYTHONPATH=src .venv/bin/python -m pytest -q \
    src/test_shelldeck_vt_reflow_286.py
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from shelldeck_vt_screen import _reflow_logical_rows, VtScreen, is_available


def _row(text):
    return {x: SimpleNamespace(data=letter, fg='red') for x, letter in enumerate(text)}


def _text(row, cols):
    return ''.join(getattr(row.get(x), 'data', ' ') for x in range(cols)).rstrip()


class LogicalReflowPureTests(unittest.TestCase):
    def test_long_line_wraps_without_character_loss(self):
        original = _row('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
        out, marks, cursor = _reflow_logical_rows([original], 80, 12, set(), 0, 36)
        self.assertEqual([_text(line, 12) for line in out],
                         ['ABCDEFGHIJKL', 'MNOPQRSTUVWX', 'YZ0123456789'])
        self.assertEqual(marks, {0, 1})
        self.assertEqual(cursor, (2, 12))
        self.assertIs(out[0][0], original[0], 'SGR cell objects must survive')

    def test_resize_back_rejoins_only_softwrapped_rows(self):
        original = _row('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
        narrow, marks, _ = _reflow_logical_rows([original], 80, 12, set(), 0, 36)
        merged, markers, cursor = _reflow_logical_rows(
            narrow, 12, 80, {id(narrow[x]) for x in marks}, 2, 12)
        self.assertEqual([_text(row, 80) for row in merged],
                         ['ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'])
        self.assertEqual(markers, set())
        self.assertEqual(cursor, (0, 36))

    def test_explicit_newline_does_not_merge(self):
        first, second = _row('A' * 26), _row('B' * 13)
        out, marks, cursor = _reflow_logical_rows([first, second], 80, 10,
                                                  set(), 1, 13)
        self.assertEqual([_text(r, 10) for r in out],
                         ['A' * 10, 'A' * 10, 'A' * 6,
                          'B' * 10, 'B' * 3])
        self.assertEqual(cursor, (4, 3))
        self.assertEqual(marks, {0, 1, 3})

    def test_character_color_and_unwritten_spaces(self):
        original = {0: SimpleNamespace(data='X', fg='green'),
                    12: SimpleNamespace(data='Y', fg='red')}
        result, marks, cursor = _reflow_logical_rows([original], 80, 10,
                                                     set(), 0, 13)
        self.assertIs(result[0][0], original[0])
        self.assertIs(result[1][2], original[12])
        self.assertEqual(cursor, (1, 3))
        self.assertEqual(marks, {0})


@unittest.skipUnless(is_available(), 'pyte ist in der Testumgebung nicht installiert')
class RealPyteReflowTests(unittest.TestCase):
    def test_narrow_visible_content_and_restore(self):
        s = VtScreen(rows=9, cols=80, history=100)
        text = 'abcdefghijklmnopqrstuvwxyz0123456789' * 2
        s.feed(text)
        s.resize(9, 24)
        self.assertEqual(''.join(x.rstrip() for x in s.display()), text)
        self.assertEqual(s.cursor['x'], 24)
        self.assertEqual(s.cursor['y'], 2)
        s.resize(9, 80)
        self.assertTrue(s.display()[0].startswith(text))
        self.assertEqual(s.cursor['x'], len(text))

    def test_explicit_lines_remain_separate(self):
        s = VtScreen(rows=10, cols=80, history=100)
        s.feed('first long line ' * 3 + '\r\nSECOND')
        s.resize(10, 20)
        self.assertEqual(s.display()[0].strip(), 'first long line firs')
        self.assertEqual(s.display()[3].strip(), 'SECOND')

    def test_style_survives_wrapping(self):
        s = VtScreen(rows=9, cols=80, history=100)
        s.feed('\x1b[31m' + 'R' * 40 + '\x1b[0m')
        s.resize(9, 16)
        self.assertEqual(''.join(l.rstrip() for l in s.display()), 'R' * 40)
        self.assertTrue(all(cell['fg'] == 'red' for y in range(3)
                            for cell in s.row_cells(y) if cell['char'] == 'R'))

    def test_alt_screen_keeps_absolute_cells(self):
        s = VtScreen(rows=8, cols=80, history=100)
        s.feed('NORMAL')
        s.feed('\x1b[?1049h\x1b[1;1HHEADER\x1b[5;1HFOOTER')
        s.resize(8, 30)
        self.assertTrue(s.display()[0].startswith('HEADER'))
        self.assertTrue(s.display()[4].startswith('FOOTER'))
        s.feed('\x1b[?1049l')
        self.assertTrue(s.display()[0].startswith('NORMAL'))

    def test_scrollback_receives_overflow_after_shrinking(self):
        s = VtScreen(rows=5, cols=60, history=100)
        s.feed('0123456789' * 5)
        s.resize(5, 10)
        self.assertEqual(''.join(s.display()).strip(), '0123456789' * 5)
        s.resize(5, 8)
        self.assertTrue('0123456789' * 5 in s.transcript_text().replace('\n', ''))


class _PyteLikeDefaultDict(dict):
    """Matches the constructor semantics of pyte.StaticDefaultDict."""
    def __init__(self, default):
        super().__init__()
        self.default = default

    def __missing__(self, key):
        return self.default


class ReflowApplicationWithoutPyte(unittest.TestCase):
    def test_row_factory_accepts_pyte_static_default_dict(self):
        template = _PyteLikeDefaultDict('blank')
        result = VtScreen._make_row(template, {0: 'A'})
        self.assertIsInstance(result, _PyteLikeDefaultDict)
        self.assertEqual(result[0], 'A')
        self.assertEqual(result[4], 'blank')

    def test_main_screen_reflow_moves_extra_rows_into_history(self):
        from collections import deque, namedtuple
        History = namedtuple('History', 'top bottom ratio size position')
        original = _row('1234567890' * 5)
        default_row = lambda: _PyteLikeDefaultDict(' ')
        normal = SimpleNamespace(
            lines=4, columns=60, cursor=SimpleNamespace(x=50, y=0),
            margins=None, buffer=__import__('collections').defaultdict(default_row),
            history=History(deque(maxlen=50), deque(maxlen=100), .5, 100, 100),
            dirty=set(), _shelldeck_softwrap_rows={},
        )
        normal.buffer[0].update(original)
        normal.buffer[1]  # an empty row, as pyte exposes
        model = VtScreen.__new__(VtScreen)
        model._rows = 4
        model._cols = 60
        model.screen = SimpleNamespace(normal=normal, alternate_active=False)
        reflow = model._reflow_main_screen(4, 10)
        normal.columns = 10
        model._apply_main_reflow(reflow, 4)
        self.assertEqual(len(normal.history.top), 1)
        self.assertEqual(''.join(cell.data for cell in normal.history.top[0].values()), '1234567890')
        self.assertEqual(''.join(''.join(c.data for c in row.values())
                                 for row in normal.buffer.values()), '1234567890' * 4)
        self.assertEqual((normal.cursor.y, normal.cursor.x), (3, 10))


if __name__ == '__main__':
    unittest.main()
