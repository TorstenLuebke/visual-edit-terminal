"""Versionsquelle fuer Fenstertitel, F1-Hilfe, Hilfe/Ueber und Builds."""

import ast
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import shelldeck_version as version


class VersionTests(unittest.TestCase):
    def test_project_version_file_is_read_by_default(self):
        project = Path(__file__).resolve().parent.parent
        self.assertTrue((project / "version.txt").is_file())
        self.assertFalse((project / "versions.txt").exists())
        self.assertEqual(version.APP_VERSION, (project / "version.txt").read_text().strip())
        self.assertEqual(version.load_version(), version.APP_VERSION)

    def test_version_change_is_read_without_code_edit(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "version.txt"
            p.write_text("3.7.12\n", encoding="utf-8")
            self.assertEqual(version.load_version(p), "3.7.12")
            p.write_text("4.0.0-rc.1\n", encoding="utf-8")
            self.assertEqual(version.load_version(p), "4.0.0-rc.1")

    def test_corrupt_or_missing_file_uses_safe_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "version.txt"
            self.assertEqual(version.load_version(p), "2.16.0")
            for content in ("", "<script>", "1.0.0\n2.0.0\n"):
                p.write_text(content, encoding="utf-8")
                self.assertEqual(version.load_version(p), "2.16.0")

    def test_new_name_takes_priority_over_old_name(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "version.txt").write_text("3.1.0\n", encoding="utf-8")
            (root / "versions.txt").write_text("1.0.0\n", encoding="utf-8")
            with patch.object(version, "__file__", str(root / "src" / "shelldeck_version.py")):
                self.assertEqual(version.load_version(), "3.1.0")

    def test_legacy_name_still_works_for_old_installations(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "versions.txt").write_text("2.99.1\n", encoding="utf-8")
            with patch.object(version, "__file__", str(root / "src" / "shelldeck_version.py")):
                self.assertEqual(version.load_version(), "2.99.1")

    def test_nuitka_executable_directory_wins(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            dist = root / "main.dist"
            dist.mkdir()
            (dist / "version.txt").write_text("5.2.4\n", encoding="utf-8")
            (root / "version.txt").write_text("3.1.0\n", encoding="utf-8")
            with (patch.object(version, "__file__", str(root / "src" / "shelldeck_version.py")),
                  patch.object(version, "__compiled__", True, create=True),
                  patch.object(version.sys, "executable", str(dist / "ShellDeck"))):
                self.assertEqual(version.load_version(), "5.2.4")

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
