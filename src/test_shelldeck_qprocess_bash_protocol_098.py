"""Regressionstests zur geplanten dauerhaften QProcess-Bash-Sitzung."""
import os
import select
import shutil
import subprocess
import time
import unittest

from shelldeck_qprocess_bash_protocol import (
    extract_bash_completions, new_completion_token, wrap_bash_command,
)


class BashProtocolTests(unittest.TestCase):
    def test_completion_token_and_foreign_marker(self):
        token = new_completion_token()
        other = new_completion_token()
        self.assertNotEqual(token, other)
        raw = f"Ausgabe\x1eSHELLDECK_DONE_{other}:7\x1f\x1eSHELLDECK_DONE_{token}:3\x1f"
        visible, statuses = extract_bash_completions(raw, token)
        self.assertIn(other, visible)
        self.assertEqual(statuses, [3])

    def test_reject_bad_tokens_and_empty_commands(self):
        with self.assertRaises(ValueError):
            wrap_bash_command("echo okay", "123")
        with self.assertRaises(ValueError):
            wrap_bash_command("   ", "a" * 32)

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash'), 'Bash auf POSIX notwendig')
    def test_persistent_shell_state_without_job_control_warning(self):
        """Eine Bash-Pipe behaelt cwd, Variablen und Funktionen bei."""
        token = new_completion_token()
        process = subprocess.Popen(
            [shutil.which('bash'), '--noprofile', '--norc'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            bufsize=0,
        )
        pending = b''
        try:
            commands = [
                ('cd /tmp', 0),
                ('export SHELLDECK_PROBE=ready', 0),
                ('function shell_deck_probe() { printf "%s:%s\\n" "$SHELLDECK_PROBE" "$PWD"; }', 0),
                ('shell_deck_probe', 0),
                ('false', 1),
                ('true', 0),
            ]
            collected = ''
            for command, expected_code in commands:
                process.stdin.write(wrap_bash_command(command, token).encode())
                deadline = time.monotonic() + 3
                while True:
                    visible, codes = extract_bash_completions(pending.decode('utf-8', 'replace'), token)
                    if codes:
                        self.assertEqual(codes, [expected_code])
                        collected += visible
                        pending = b''
                        break
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, 'Kein Bash-Abschluss empfangen')
                    ready, _, _ = select.select([process.stdout], [], [], remaining)
                    self.assertTrue(ready, 'Bash-Pipe reagiert nicht')
                    pending += os.read(process.stdout.fileno(), 4096)
            self.assertIn('ready:/tmp', collected)
            process.stdin.close()
            self.assertEqual(process.wait(timeout=3), 0)
            self.assertNotIn('job control', process.stderr.read().decode('utf-8', 'replace').lower())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
            for pipe in (process.stdin, process.stdout, process.stderr):
                if pipe is not None and not pipe.closed:
                    pipe.close()


if __name__ == '__main__':
    unittest.main()
