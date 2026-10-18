"""Regression: verzögerter Restore darf keinen zweiten PTY-Prompt erzeugen."""
import tempfile
import unittest
from pathlib import Path
from shelldeck_restore_guard import inherited_venv_already_active


class RestoreGuardTests(unittest.TestCase):
    def test_same_inherited_venv_skips_duplicate_activation(self):
        with tempfile.TemporaryDirectory() as tmp:
            venv = Path(tmp) / ".venv"
            venv.mkdir()
            self.assertTrue(inherited_venv_already_active(str(venv), str(venv)))

    def test_other_environment_is_not_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first"
            other = Path(tmp) / "other"
            first.mkdir()
            other.mkdir()
            self.assertFalse(inherited_venv_already_active(str(first), str(other)))
            self.assertFalse(inherited_venv_already_active(str(first), ""))
            self.assertFalse(inherited_venv_already_active("", str(first)))

    def test_nonexistent_environment_is_not_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = str(Path(tmp) / "missing")
            self.assertFalse(inherited_venv_already_active(absent, absent))


if __name__ == "__main__":
    unittest.main()
