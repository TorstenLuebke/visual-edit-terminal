"""Regression: an errexit failure must not destroy the persistent batch Bash."""
import subprocess
import unittest

from shelldeck_qprocess_bash_batch import wrap_batch_command
from shelldeck_qprocess_bash_protocol import BashCompletionDecoder


class BatchErrexitTests(unittest.TestCase):
    def test_errexit_does_not_lose_completion_or_following_command(self):
        commands = ("set -e", "false", "echo READY")
        tokens = [f"{i:032x}" for i in range(len(commands))]
        script = "".join(wrap_batch_command(cmd, token)
                         for cmd, token in zip(commands, tokens))
        result = subprocess.run(
            ["bash", "--noprofile", "--norc"], input=script,
            text=True, capture_output=True, timeout=8, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("READY", result.stdout)
        for token, expected in zip(tokens, (0, 1, 0)):
            decoder = BashCompletionDecoder(token)
            _visible, codes = decoder.feed(result.stdout)
            self.assertEqual(codes, [expected])

    def test_stdin_of_external_command_is_not_the_control_pipe(self):
        commands = ("cat", "echo STILL-HERE")
        script = "".join(wrap_batch_command(cmd, f"{i:032x}")
                         for i, cmd in enumerate(commands))
        result = subprocess.run(
            ["bash", "--noprofile", "--norc"], input=script,
            text=True, capture_output=True, timeout=8, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STILL-HERE", result.stdout)
