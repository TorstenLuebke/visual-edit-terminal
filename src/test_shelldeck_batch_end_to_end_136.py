"""Real bash subprocess integration without Qt, for the QProcess batch wire format."""
import os
import subprocess
import sys
import unittest

from shelldeck_qprocess_bash_batch import wrap_batch_command
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder, new_completion_token


@unittest.skipUnless(sys.platform.startswith("linux"), "POSIX bash integration test")
class TestBatchEndToEnd(unittest.TestCase):
    def test_persistent_shell_and_command_failure(self):
        p = subprocess.Popen(["/bin/bash", "--noprofile", "--norc"],
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            commands = ["cd /tmp", "pwd", "export SD_BATCH_136=Value136",
                        "printf '%s\n' \"$SD_BATCH_136\"", "false", "printf 'OK\n'"]
            tokens = [new_completion_token() for _ in commands]
            data = ''.join(wrap_batch_command(cmd, token) for cmd, token in zip(commands, tokens))
            stdout, stderr = p.communicate(data.encode("utf-8") + b"exit\n", timeout=10)
            self.assertEqual(p.returncode, 0, stderr.decode(errors="replace"))
            visible = stdout.decode("utf-8")
            exits = []
            for token in tokens:
                decoder = BashCompletionDecoder(token)
                visible, codes = decoder.feed(visible)
                visible += decoder.finish()
                exits.extend(codes)
            self.assertEqual(exits, [0, 0, 0, 0, 1, 0])
            self.assertIn('/tmp', visible)
            self.assertIn('Value136', visible)
            self.assertIn('OK', visible)
            self.assertNotIn('SHELLDECK_DONE_', visible)
        finally:
            if p.poll() is None: p.kill(); p.communicate()


if __name__ == '__main__': unittest.main()
