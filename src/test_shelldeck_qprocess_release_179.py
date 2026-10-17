"""Release contract: labels may change, persistent identifiers must not."""
import ast
import unittest
from pathlib import Path
from shelldeck_qprocess_bash_batch import default_batch_mode, batch_mode_from_settings

ROOT = Path(__file__).resolve().parent

class QProcessReleaseTests(unittest.TestCase):
    def test_gui_label_and_stable_identifier(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        choices = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "addItem" and len(node.args) >= 2:
                if all(isinstance(arg, ast.Constant) and isinstance(arg.value, str) for arg in node.args[:2]):
                    choices.append((node.args[0].value, node.args[1].value))
        self.assertIn(("Bash: ohne Jobsteuerung", "batch"), choices)
        self.assertIn(("Bash: kompatibel", "classic"), choices)
        self.assertNotIn(("Bash: ohne Jobsteuerung (Test)", "batch"), choices)

    def test_fresh_default_and_saved_fallback(self):
        for platform in ("linux", "darwin"):
            self.assertEqual(default_batch_mode(platform), "batch")
            self.assertEqual(batch_mode_from_settings({}, platform), "batch")
            self.assertEqual(batch_mode_from_settings({"qprocess_bash_mode": "classic"}, platform), "classic")
            self.assertEqual(batch_mode_from_settings({"qprocess_bash_mode": "batch"}, platform), "batch")
        self.assertEqual(default_batch_mode("win32"), "classic")
        self.assertEqual(batch_mode_from_settings({"qprocess_bash_mode": "batch"}, "win32"), "batch")

if __name__ == "__main__":
    unittest.main()
