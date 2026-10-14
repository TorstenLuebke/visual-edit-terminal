"""Verifiziert, dass die Versionshilfe den tatsaechlich implementierten Mausmodus beschreibt."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent


class MouseDocumentationTests(unittest.TestCase):
    def test_readme_and_f1_help_distinguish_mouse_reporting_from_selection(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        help_source = (ROOT / "src" / "main.py").read_text(encoding="utf-8")
        for item in ("1006", "1000", "1002", "1003", "Umschalt"):
            self.assertIn(item, readme)
        self.assertIn("xterm-SGR 1006", help_source)
        self.assertIn("Shift+Ziehen", help_source)
        self.assertIn("Aeltere Mausprotokolle", help_source)


if __name__ == "__main__":
    unittest.main()
