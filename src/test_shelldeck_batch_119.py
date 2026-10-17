import os
import subprocess
import unittest
from shelldeck_qprocess_bash_batch import wrap_batch_command
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder, new_completion_token


@unittest.skipUnless(os.name == "posix", "POSIX Bash only")
class PersistentBatchTests(unittest.TestCase):
    def test_state_exit_and_stdin_isolation(self):
        token = new_completion_token()
        proc = subprocess.Popen(["bash", "--noprofile", "--norc"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        commands = ["export SHELLDECK_BATCH_TEST=works", "printf '%s' \"$SHELLDECK_BATCH_TEST\"",
                    "cd /tmp", "pwd", "source /dev/null", "fct() { echo function_ok; }", "fct", "false", "printf 'END'"]
        payload = ''.join(wrap_batch_command(c, token) for c in commands) + "exit\n"
        stdout, stderr = proc.communicate(payload, timeout=8)
        decoder = BashCompletionDecoder(token)
        visible = []
        statuses = []
        for i in range(0, len(stdout), 3):
            v, s = decoder.feed(stdout[i:i+3]); visible.append(v); statuses += s
        visible.append(decoder.finish())
        self.assertEqual(statuses, [0, 0, 0, 0, 0, 0, 0, 1, 0])
        self.assertIn("works", ''.join(visible))
        self.assertIn("/tmp", ''.join(visible))
        self.assertIn("END", ''.join(visible))
        self.assertIn("function_ok", ''.join(visible))
        self.assertNotIn("Keine Jobsteuerung", stderr)

    def test_input_consumer_cannot_swallow_following_command(self):
        token = new_completion_token()
        proc = subprocess.Popen(["bash", "--noprofile", "--norc"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
        commands = ["cat", "echo after_cat"]
        output, _ = proc.communicate(''.join(wrap_batch_command(c, token) for c in commands) + 'exit\n', timeout=8)
        decoder = BashCompletionDecoder(token)
        visible, statuses = decoder.feed(output)
        self.assertIn('after_cat', visible)
        self.assertEqual(statuses, [0, 0])
