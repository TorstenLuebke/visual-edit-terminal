"""Default migration must not overwrite existing user settings."""
import ast
import unittest
from pathlib import Path

from shelldeck_qprocess_bash_batch import default_batch_mode, batch_mode_from_settings


class BatchDefaultTests(unittest.TestCase):
    def test_new_install_posix_uses_batch(self):
        for platform in ("linux", "darwin"):
            with self.subTest(platform=platform):
                self.assertEqual(default_batch_mode(platform), "batch")
                self.assertEqual(batch_mode_from_settings({}, platform), "batch")

    def test_new_install_windows_stays_compatible(self):
        self.assertEqual(default_batch_mode("win32"), "classic")
        self.assertEqual(batch_mode_from_settings({}, "win32"), "classic")

    def test_saved_preferences_are_never_overwritten(self):
        for platform in ("linux", "darwin", "win32"):
            for choice in ("classic", "batch"):
                with self.subTest(platform=platform, choice=choice):
                    self.assertEqual(batch_mode_from_settings(
                        {"qprocess_bash_mode": choice}, platform), choice)

    def test_invalid_setting_falls_back_safely(self):
        self.assertEqual(batch_mode_from_settings({"qprocess_bash_mode": "garbage"}, "linux"), "batch")
        self.assertEqual(batch_mode_from_settings(None, "win32"), "classic")

    def test_gui_uses_default_and_does_not_remove_fallback(self):
        source = (Path(__file__).parent / "main.py").read_text(encoding="utf-8")
        ast.parse(source)
        self.assertIn('self.qprocess_bash_mode = default_batch_mode()', source)
        self.assertIn('self.qprocess_bash_mode = batch_mode_from_settings(settings)', source)
        self.assertIn('addItem("Bash: kompatibel", "classic")', source)
        self.assertIn('self.qprocess_bash_mode = previous', source)


if __name__ == "__main__":
    unittest.main()
