"""Blockgrenzen duerfen Abschlussmarker weder zeigen noch verlieren."""
import unittest

from shelldeck_qprocess_bash_protocol import BashCompletionDecoder


class BashCompletionDecoderTests(unittest.TestCase):
    def setUp(self):
        self.token = 'a' * 32
        self.frame = f'\x1eSHELLDECK_DONE_{self.token}:17\x1f'

    def test_every_possible_two_chunk_split(self):
        data = 'before\n' + self.frame + 'after\n'
        for index in range(len(data) + 1):
            with self.subTest(index=index):
                decoder = BashCompletionDecoder(self.token)
                first, statuses1 = decoder.feed(data[:index])
                second, statuses2 = decoder.feed(data[index:])
                self.assertEqual(first + second + decoder.finish(), 'before\nafter\n')
                self.assertEqual(statuses1 + statuses2, [17])

    def test_partial_marker_not_swallowed_at_end(self):
        decoder = BashCompletionDecoder(self.token)
        source = 'message' + self.frame[:13]
        shown, codes = decoder.feed(source)
        self.assertEqual(codes, [])
        self.assertEqual(shown + decoder.finish(), source)

    def test_mismatched_token_remains_visible(self):
        decoder = BashCompletionDecoder(self.token)
        other = '\x1eSHELLDECK_DONE_' + 'b' * 32 + ':0\x1f'
        shown, codes = decoder.feed(other)
        self.assertEqual(shown + decoder.finish(), other)
        self.assertEqual(codes, [])


if __name__ == '__main__':
    unittest.main()
