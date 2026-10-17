import unittest
from shelldeck_qprocess_bash_batch import batch_requested, wrap_batch_command
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder


class BatchConfigurationTests(unittest.TestCase):
    def test_explicit_opt_in_only(self):
        self.assertFalse(batch_requested({}))
        self.assertFalse(batch_requested({'SHELLDECK_QPROCESS_BASH_BATCH':'0'}))
        self.assertTrue(batch_requested({'SHELLDECK_QPROCESS_BASH_BATCH':'1'}))

    def test_shell_input_is_quoted(self):
        token = 'a' * 32
        source = "echo hello; echo quoted"
        wrapped = wrap_batch_command(source, token)
        self.assertIn("eval 'echo hello; echo quoted' </dev/null", wrapped)
        self.assertIn('SHELLDECK_DONE_', wrapped)
        with self.assertRaises(ValueError):
            wrap_batch_command('echo\x00bad', token)
        with self.assertRaises(ValueError):
            wrap_batch_command(source, 'invalid')
