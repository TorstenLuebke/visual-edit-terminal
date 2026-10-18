"""Regression tests for experimental VisualEdit-inspired presentation contracts."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shelldeck_terminal_presentation_250 import (
    RepaintAccumulator, RepaintRequest, TextAnchor, TextSelection
)


class PresentationContractsTests(unittest.TestCase):
    def test_selection_survives_viewport_scroll(self):
        selected = TextSelection(TextAnchor(1, 100, 4), TextAnchor(1, 102, 8))
        self.assertTrue(selected.valid_for(1, [100, 101, 102, 103]))
        self.assertTrue(selected.valid_for(1, [99, 100, 102, 150]))

    def test_selection_invalid_on_eviction(self):
        selected = TextSelection(TextAnchor(1, 100, 4), TextAnchor(1, 102, 8))
        self.assertFalse(selected.valid_for(1, [101, 102, 103]))

    def test_generation_change_invalidates_selection(self):
        selected = TextSelection(TextAnchor(1, 100, 4), TextAnchor(1, 102, 8))
        self.assertFalse(selected.valid_for(2, [100, 102]))
        with self.assertRaises(ValueError):
            TextSelection(TextAnchor(1, 1, 1), TextAnchor(2, 1, 2))

    def test_reverse_selection_orders_endpoints(self):
        selected = TextSelection(TextAnchor(1, 50, 9), TextAnchor(1, 48, 3))
        self.assertEqual(selected.ordered()[0], TextAnchor(1, 48, 3))

    def test_repaint_requests_are_merged_and_drained(self):
        accumulator = RepaintAccumulator()
        accumulator.request(RepaintRequest(rows=frozenset([2])))
        accumulator.request(RepaintRequest(rows=frozenset([3, 2])))
        self.assertEqual(accumulator.drain().rows, frozenset([2, 3]))
        self.assertEqual(accumulator.drain(), RepaintRequest())

    def test_full_repaint_supersedes_partial(self):
        acc = RepaintAccumulator()
        acc.request(RepaintRequest(rows=frozenset([1])))
        acc.request(RepaintRequest(full=True))
        self.assertEqual(acc.drain(), RepaintRequest(full=True))

    def test_request_rejects_invalid_row(self):
        with self.assertRaises(ValueError):
            RepaintRequest(rows=frozenset([-1]))


if __name__ == "__main__":
    unittest.main()
