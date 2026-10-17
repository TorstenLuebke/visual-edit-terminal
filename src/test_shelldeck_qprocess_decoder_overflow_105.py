"""An incomplete marker must not swallow unlimited application output."""
import unittest
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder

class DecoderOverflowTests(unittest.TestCase):
    def test_long_unfinished_fake_frame_is_visible(self):
        token='f'*32
        frame='\x1eSHELLDECK_DONE_'+token+':'+'x'*2000
        decoder=BashCompletionDecoder(token)
        output=[]
        for i in range(0,len(frame),17):
            shown, statuses=decoder.feed(frame[i:i+17])
            self.assertEqual(statuses, [])
            output.append(shown)
        self.assertEqual(''.join(output)+decoder.finish(),frame)
