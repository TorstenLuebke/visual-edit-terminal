"""Regression tests for non-leaking marker fragments and end-of-stream."""
import unittest
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder

class MarkerTransportTests(unittest.TestCase):
    def test_pending_partial_and_close(self):
        dec = BashCompletionDecoder('a'*32)
        frame = '\x1eSHELLDECK_DONE_' + 'a'*32 + ':0\x1f'
        visible, codes = dec.feed('start'+frame[:12])
        self.assertEqual((visible,codes), ('start',[]))
        self.assertTrue(dec.has_pending_prefix)
        self.assertEqual(dec.finish(), frame[:12])
        self.assertFalse(dec.has_pending_prefix)

    def test_two_successive_frames_in_one_packet(self):
        dec = BashCompletionDecoder('b'*32)
        f = '\x1eSHELLDECK_DONE_' + 'b'*32
        visible,codes = dec.feed('A'+f+':0\x1fB'+f+':2\x1fC')
        self.assertEqual((visible,codes),('ABC',[0,2]))
