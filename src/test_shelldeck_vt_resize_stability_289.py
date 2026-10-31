"""Patch 289: prevent phantom blank rows during repeated interactive VT resizes.

These tests deliberately do not require Qt or pyte.  They reproduce the
model symptom recorded by the opt-in Patch-288 resize audit: text cells stay
constant while the row count steadily grows and content enters scrollback.
"""
from __future__ import annotations

import unittest
from collections import defaultdict, deque, namedtuple
from types import SimpleNamespace

from shelldeck_vt_screen import VtScreen, _reflow_logical_rows
import shelldeck_vt_screen as _vt

_is_default_blank_cell = getattr(_vt, "_is_default_blank_cell", lambda cell: False)


def _cell(letter=" ", **style):
    return SimpleNamespace(data=letter, fg=style.pop("fg", "default"),
                           bg=style.pop("bg", "default"), **style)


def _text(row, cols):
    return "".join(getattr(row.get(x), "data", " ") for x in range(cols)).rstrip()


def _padded_row(message, cols):
    result = {x: _cell(char) for x, char in enumerate(message)}
    result.update({x: _cell() for x in range(len(message), cols)})
    return result


class _FakeNormal:
    def __init__(self, cols, rows):
        self.columns, self.lines = cols, rows
        self.cursor = SimpleNamespace(x=0, y=0)
        self.margins = None
        self.buffer = defaultdict(dict)
        self.history = namedtuple("History", "top bottom ratio size position")(
            deque(maxlen=100), deque(maxlen=100), 0.5, 100, 100
        )
        self._shelldeck_softwrap_rows = {}
        self._shelldeck_resize_tails = {}
        self.dirty = set()


class _FakeBuffers:
    alternate_active = False

    def __init__(self, normal):
        self.normal = normal
        self.dirty = set()

    def resize(self, rows, cols):
        self.normal.lines, self.normal.columns = rows, cols
        # Like a terminal grid's materialized default background cells.
        for line in self.normal.buffer.values():
            for x in range(cols):
                line.setdefault(x, _cell())


class VtResizeStability289(unittest.TestCase):
    def test_default_padding_does_not_create_fake_printed_lines(self):
        self.assertTrue(_is_default_blank_cell(_cell()))
        self.assertFalse(_is_default_blank_cell(_cell("X")))
        self.assertFalse(_is_default_blank_cell(_cell(" ", fg="red")))
        rows = [_padded_row("a", 90), _padded_row("b", 90)]
        result, soft, cursor = _reflow_logical_rows(
            rows, 90, 15, set(), cursor_row=1, cursor_x=1
        )
        self.assertEqual([_text(row, 15) for row in result], ["a", "b"])
        self.assertEqual(soft, set())
        self.assertEqual(cursor, (1, 1))

    def test_long_line_with_softwrap_and_styled_space_retained(self):
        original = _padded_row("blue    red", 80)
        original[5] = _cell(" ", fg="blue")
        result, soft, _ = _reflow_logical_rows([original], 80, 6, set(), 0, 11)
        self.assertEqual([_text(row, 6) for row in result], ["blue", "  red"])
        self.assertEqual(soft, {0})
        self.assertEqual(result[0][5].fg, "blue")

    def test_drag_150_steps_does_not_accumulate_invisible_lines(self):
        listing = "CMakeLists.txt  __pycache__  core  gui  main.py  requirements.txt  src  utils"
        lines = ["bash$ dir", listing, "bash$ "]
        current = [_padded_row(line, 220) for line in lines]
        soft_ids = set()
        cursor = (2, len(lines[-1]))
        before = 220
        for width in list(range(220, 44, -1)) + list(range(45, 221)):
            wrapped, indices, cursor = _reflow_logical_rows(
                current, before, width, soft_ids, *cursor
            )
            self.assertLessEqual(len(wrapped), 6, f"phantom rows at width={width}")
            logical_text = "".join(
                "".join(getattr(row.get(x), "data", " ") for x in range(width))
                if i in indices else _text(row, width)
                for i, row in enumerate(wrapped)
            )
            self.assertEqual(logical_text, "".join(lines).rstrip(),
                             f"text lost or duplicated at width={width}")
            self.assertEqual(cursor[0], len(wrapped) - 1)
            # Simulate blank cells being materialized by the terminal renderer.
            current = [{**row, **{x: _cell() for x in range(width)
                                if x not in row}} for row in wrapped]
            soft_ids = {id(current[i]) for i in indices}
            before = width
        self.assertEqual(len(current), 3)

    def test_viewport_ignores_unwritten_blank_rows_after_cursor(self):
        normal = _FakeNormal(180, 58)
        normal.buffer[0] = _padded_row("bash$ dir", 180)
        normal.buffer[1] = _padded_row("main.py  src  utils", 180)
        normal.buffer[2] = _padded_row("bash$ ", 180)
        normal.cursor.x, normal.cursor.y = 6, 2
        for row in range(3, 58):
            normal.buffer[row] = _padded_row("", 180)
        model = VtScreen.__new__(VtScreen)
        model._cols, model._rows = 180, 58
        model.screen = _FakeBuffers(normal)
        older, wrapped, soft, cursor = model._reflow_main_screen(58, 175)
        self.assertEqual(len(wrapped), 3)
        self.assertEqual(cursor, (2, 6))
        self.assertEqual(older, [])
        self.assertEqual(soft, set())

    def test_actual_model_repeated_resize_keeps_history_and_cursor(self):
        normal = _FakeNormal(160, 58)
        rows = ["bash$ dir", "CMakeLists.txt  __pycache__  main.py  src  utils", "bash$ "]
        for index, text in enumerate(rows):
            normal.buffer[index] = _padded_row(text, 160)
        normal.cursor = SimpleNamespace(x=6, y=2)
        for i in range(3, 58):
            normal.buffer[i] = _padded_row("", 160)
        model = VtScreen.__new__(VtScreen)
        model._cols, model._rows = 160, 58
        model.screen = _FakeBuffers(normal)
        for width in list(range(159, 49, -1)) + list(range(51, 161)):
            model.resize(58, width)
            rendered = [_text(normal.buffer[i], width) for i in range(58)]
            self.assertEqual(len(normal.history.top), 0)
            self.assertTrue(any("bash$ dir" in t for t in rendered), width)
            self.assertTrue(any("bash$ " in t for t in rendered), width)
            self.assertLessEqual(normal.cursor.y, 4)
        self.assertEqual(normal.cursor.x, 6)
        self.assertEqual(normal.cursor.y, 2)


if __name__ == "__main__":
    unittest.main()
