"""Schutz der spaeteren QProcess-Protokollintegration."""
import unittest
from shelldeck_qprocess_bash_policy import command_allows_completion_marker as allowed


class QProcessBashPolicyTests(unittest.TestCase):
    def test_basic_safe_builtins(self):
        for command in ('cd /tmp', 'export LANG=C', 'pwd', 'echo hallo',
                        'unset SOME_VAR', 'false', 'deactivate'):
            with self.subTest(command=command):
                self.assertTrue(allowed(command))

    def test_stdin_consumers_remain_unwrapped(self):
        for command in ('sudo apt update', 'python', 'vim text.txt',
                        'read x', 'source .venv/bin/activate',
                        '. ./activate', 'bash -i', 'cat', 'my_script.sh'):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))

    def test_compound_commands_remain_unwrapped(self):
        for command in ('echo hi; read x', 'echo hi | cat',
                        'echo $(read x)', 'echo hi >out',
                        'echo hi\necho bye', 'printf "bad', 'export A=1 && read x'):
            with self.subTest(command=command):
                self.assertFalse(allowed(command))
