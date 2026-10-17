"""Mixed output and completion marker chunk boundaries."""
import unittest
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder

class CompletionCycleTests(unittest.TestCase):
    def test_each_character_boundary_and_trailing_text(self):
        token='e'*32
        marker='\x1eSHELLDECK_DONE_'+token+':0\x1f'
        data='start '+marker+' end'
        decoder=BashCompletionDecoder(token)
        visible=[]; codes=[]
        for char in data:
            v,c=decoder.feed(char);visible.append(v);codes.extend(c)
        self.assertEqual(''.join(visible)+decoder.finish(),'start  end')
        self.assertEqual(codes,[0])
    def test_partial_false_prefix_retained_as_output(self):
        token='e'*32
        decoder=BashCompletionDecoder(token)
        raw='hi\x1eSHELLDECK_DON\nother'
        output=[]
        for x in raw:
            shown,codes=decoder.feed(x)
            self.assertEqual(codes,[])
            output.append(shown)
        self.assertEqual(''.join(output)+decoder.finish(),raw)
