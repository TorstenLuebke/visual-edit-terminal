"""Defensive parsing of untrusted output that resembles completion markers."""
import unittest
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder

class DecoderStatusLimitsTests(unittest.TestCase):
    def test_extremely_long_numeric_status_is_text(self):
        token = 'd'*32
        frame = '\x1eSHELLDECK_DONE_'+token+':'+'9'*10000+'\x1f'
        decoder = BashCompletionDecoder(token)
        shown, statuses = decoder.feed(frame)
        self.assertEqual(statuses, [])
        self.assertEqual(shown+decoder.finish(), frame)

    def test_valid_negative_status(self):
        token='d'*32
        decoder=BashCompletionDecoder(token)
        shown, codes=decoder.feed('A\x1eSHELLDECK_DONE_'+token+':-5\x1fB')
        self.assertEqual((shown,codes), ('AB',[-5]))
