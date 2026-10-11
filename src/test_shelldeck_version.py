"""Versionsquelle fuer Fenstertitel, F1-Hilfe und Hilfe/Ueber."""

import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import shelldeck_version as version


class VersionTests(unittest.TestCase):
    def test_project_version_file_is_read_by_default(self):
        self.assertEqual(version.APP_VERSION, "2.16.0")
        self.assertEqual(version.load_version(), version.APP_VERSION)

    def test_version_change_is_read_without_code_edit(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "versions.txt"
            p.write_text("3.7.12\n", encoding="utf-8")
            self.assertEqual(version.load_version(p), "3.7.12")
            p.write_text("4.0.0-rc.1\n", encoding="utf-8")
            self.assertEqual(version.load_version(p), "4.0.0-rc.1")

    def test_corrupt_or_missing_file_uses_safe_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "versions.txt"
            self.assertEqual(version.load_version(p), "2.16.0")
            for content in ("", "<script>", "1.0.0\n2.0.0\n"):
                p.write_text(content, encoding="utf-8")
                self.assertEqual(version.load_version(p), "2.16.0")

    def test_about_help_title_use_imported_version(self):
        tree = ast.parse(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
        found = any(isinstance(n, ast.ImportFrom) and n.module == "shelldeck_version"
                    and any(a.name == "APP_VERSION" for a in n.names) for n in tree.body)
        self.assertTrue(found)
        self.assertFalse(any(isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "APP_VERSION" for t in n.targets) for n in tree.body))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "TerminalWindow")
        for name in ("__init__", "help_text", "show_about_dialog"):
            method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
            self.assertTrue(any(isinstance(node, ast.Name) and node.id == "APP_VERSION"
                                for node in ast.walk(method)), name)


if __name__ == "__main__":
    unittest.main()
