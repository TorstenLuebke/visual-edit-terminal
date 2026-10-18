"""Session-Bash-Prompt: keine Benutzerdateien und gueltige Shell-Syntax."""
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from shelldeck_prompt import bash_prompt_script, create_bash_prompt_rc, rgb_ansi


class PromptTests(unittest.TestCase):
    def test_rgb_validation(self):
        self.assertEqual(rgb_ansi("#86EFAC"), r"\[\e[38;2;134;239;172m\]")
        for color in ("#123", "hello", "#12345G", "#000000;rm -rf /"):
            with self.assertRaises(ValueError):
                rgb_ansi(color)

    def test_temporary_session_file_is_cleaned_up(self):
        directory, path = create_bash_prompt_rc({"prompt": "#86EFAC", "environment": "#67E8F9"})
        self.assertTrue(os.path.exists(path))
        self.assertIn("VIRTUAL_ENV", __import__("pathlib").Path(path).read_text(encoding="utf-8"))
        directory.cleanup()
        self.assertFalse(os.path.exists(path))

    @unittest.skipUnless(shutil.which("bash"), "Bash nicht vorhanden")
    def test_generated_bash_rc_is_syntax_valid(self):
        directory, path = create_bash_prompt_rc({"prompt": "#86EFAC", "environment": "#67E8F9"})
        try:
            result = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        finally:
            directory.cleanup()


if __name__ == "__main__":
    unittest.main()
