"""Keep the conservative marker eligibility explicit."""
import unittest
from shelldeck_qprocess_bash_policy import command_allows_completion_marker as allowed

class BoundaryTests(unittest.TestCase):
    def test_comment_suffix_not_wrapped(self):
        for text in ('echo ready # comment','echo ready #', 'printf ok # text'):
            with self.subTest(text=text): self.assertFalse(allowed(text))
    def test_simple_state_commands_supported(self):
        for text in ('cd /tmp','export A=1','unset A','pwd'):
            with self.subTest(text=text): self.assertTrue(allowed(text))
