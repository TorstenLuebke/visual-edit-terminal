"""The completion path must not misclassify shell control input."""
import unittest
from pathlib import Path
from shelldeck_qprocess_bash_policy import command_allows_completion_marker as allows

class CompletionSafetyTests(unittest.TestCase):
    def test_safe_builtin_commands(self):
        for cmd in ('cd /tmp','pwd','export TEST=1','unset TEST','true','false'):
            with self.subTest(cmd=cmd):self.assertTrue(allows(cmd))

    def test_unsafe_commands(self):
        for cmd in ('source .venv/bin/activate','python -i','read VALUE',
                    'X=1 cat','if true','cat /tmp/file','echo ok | cat',
                    'echo one; echo two','sudo whoami'):
            with self.subTest(cmd=cmd):self.assertFalse(allows(cmd))

    def test_live_guard_exists(self):
        path=Path(__file__).with_name('shelldeck_terminal_widget.py')
        code=path.read_text()
        self.assertIn('if getattr(self, "_bash_completion_pending", False):',code)
