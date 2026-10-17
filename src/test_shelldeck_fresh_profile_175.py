"""Tests for the opt-in fresh-profile launcher (no GUI session required)."""
import importlib.util
import tempfile
import unittest
from pathlib import Path


class FreshProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parent.parent / "tools" / "run_fresh_profile.py"
        spec = importlib.util.spec_from_file_location("run_fresh_profile", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_isolates_all_home_and_xdg_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            env = self.module.isolated_environment(Path(folder), {"HOME": "/old/home", "APPDATA": "/old/appdata", "XDG_CONFIG_HOME": "/old/config", "PATH": "/bin"})
            self.assertEqual(env["PATH"], "/bin")
            for key in ("HOME", "APPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
                self.assertTrue(Path(env[key]).is_dir())
                self.assertTrue(Path(env[key]).is_relative_to(Path(folder).resolve()))
            self.assertEqual(env["HOME"], str(Path(folder).resolve() / "home"))

    def test_removes_legacy_override_only_from_child_environment(self):
        original = {"HOME": "/my/home", "SHELLDECK_QPROCESS_BASH_BATCH": "0"}
        with tempfile.TemporaryDirectory() as folder:
            env = self.module.isolated_environment(Path(folder), original)
            self.assertNotIn("SHELLDECK_QPROCESS_BASH_BATCH", env)
            self.assertEqual(original["SHELLDECK_QPROCESS_BASH_BATCH"], "0")


if __name__ == "__main__":
    unittest.main()
