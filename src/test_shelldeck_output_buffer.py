"""Last- und Reihenfolgetests fuer ShellDecks Qt-freie Ausgabewarteschlange."""

import unittest

from shelldeck_output_buffer import TerminalOutputBuffer


def split_at_newline(text, limit):
    newline = text.rfind("\n", 0, limit)
    return newline + 1 if newline >= limit // 2 else limit


class OutputBufferTests(unittest.TestCase):
    def test_fifo_colors_unicode_and_partial_slices(self):
        queue = TerminalOutputBuffer()
        queue.append("Hallo ", "weiss")
        queue.append("ä🙂\n", "weiss")
        queue.append("ROT", "rot")
        self.assertEqual(queue.pending_chars, len("Hallo ä🙂\nROT"))
        self.assertEqual(queue.take(8, split_at_newline), [("Hallo ä🙂", "weiss")])
        self.assertEqual(queue.pending_chars, len("\nROT"))
        self.assertEqual(queue.take(100, split_at_newline), [("\n", "weiss"), ("ROT", "rot")])
        self.assertFalse(queue)
        self.assertEqual(queue.pending_chars, 0)

    def test_many_tiny_chunks_preserve_exact_output(self):
        queue = TerminalOutputBuffer()
        for index in range(30000):
            queue.append("x" if index % 2 else "\n", "normal")
        self.assertEqual(len(queue), 30000)
        self.assertEqual(queue.pending_chars, 30000)
        pieces = []
        while queue:
            batches = queue.take(4096, split_at_newline)
            self.assertLessEqual(sum(len(text) for text, _ in batches), 4096)
            self.assertEqual(len(batches), 1)
            pieces.extend(text for text, _ in batches)
        self.assertEqual("".join(pieces), "\nx" * 15000)
        self.assertEqual(queue.pending_chars, 0)

    def test_pending_output_can_be_inspected_before_drain(self):
        queue = TerminalOutputBuffer()
        queue.append("Prompt: ", "a")
        queue.append("$ ", "a")
        self.assertEqual("".join(item[0] for item in queue), "Prompt: $ ")
        queue.take(3, split_at_newline)
        self.assertEqual("".join(item[0] for item in queue), "mpt: $ ")
        queue.clear()
        self.assertEqual(list(queue), [])
        self.assertEqual(queue.pending_chars, 0)

    def test_zero_splitter_does_not_stall(self):
        queue = TerminalOutputBuffer()
        queue.append("12345", "a")
        self.assertEqual(queue.take(2, lambda *_: 0), [("12", "a")])
        self.assertEqual(queue.pending_chars, 3)


if __name__ == "__main__":
    unittest.main()
