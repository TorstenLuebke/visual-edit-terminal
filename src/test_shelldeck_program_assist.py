"""Regression: sichere, zustandsgebundene Bedienhilfe fuer POSIX-Vollbildprogramme."""
import json
import os
import tempfile
from pathlib import Path
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import shelldeck_program_assist as assist


class ProgramAssistTests(unittest.TestCase):
    def test_exact_supported_programs_and_aliases(self):
        self.assertEqual(assist.canonical_program("/usr/bin/vim.basic"), "vim")
        self.assertEqual(assist.canonical_program("nvim"), "vim")
        self.assertEqual(assist.canonical_program("nano"), "nano")
        self.assertEqual(assist.canonical_program("htop"), "htop")
        self.assertIsNone(assist.canonical_program("vim_instructions.txt"))
        self.assertIsNone(assist.canonical_program("ssh"))
        self.assertIsNone(assist.canonical_program("bash"))

    def test_additional_program_guides_and_safe_detach(self):
        expected = {
            "btop": (b"q", "Beenden"),
            "micro": (b"\x11", "Beenden"),
            "mc": (b"\x1b[21~", "Beenden"),
            "tmux": (b"\x02d", "Trennen"),
            "screen": (b"\x01d", "Trennen"),
        }
        for name, (data, title) in expected.items():
            with self.subTest(program=name):
                self.assertEqual(assist.canonical_program(name), name)
                self.assertEqual(assist.GUIDES[name].exit_bytes, data)
                self.assertEqual(assist.GUIDES[name].primary_label, title)
        self.assertEqual(assist.canonical_program("/usr/bin/mcedit"), "mc")
        self.assertEqual(assist.canonical_program("tmux: client"), "tmux")
        self.assertIsNone(assist.canonical_program("not-actually-screen"))

    def test_normal_vim_exit_is_not_forced(self):
        self.assertEqual(assist.GUIDES["vim"].exit_bytes, b"\x1b:q\r")
        self.assertEqual(assist.GUIDES["nano"].exit_bytes, b"\x18")
        self.assertEqual(assist.GUIDES["watch"].exit_bytes, b"\x03")

    @unittest.skipUnless(os.name == "posix", "POSIX PTY erforderlich")
    def test_same_foreground_group_is_shell_not_app(self):
        child = SimpleNamespace(fd=41, pid=500)
        with patch.object(assist.os, "tcgetpgrp", return_value=500), \
             patch.object(assist.os, "getpgid", return_value=500), \
             patch.object(assist, "_process_name", return_value="vim"):
            self.assertIsNone(assist.foreground_guide(child))

    @unittest.skipUnless(os.name == "posix", "POSIX PTY erforderlich")
    def test_only_verified_foreground_program_is_reported(self):
        child = SimpleNamespace(fd=42, pid=500)
        with patch.object(assist.os, "tcgetpgrp", return_value=601), \
             patch.object(assist.os, "getpgid", return_value=500), \
             patch.object(assist, "_process_name", return_value="vim") as probe:
            self.assertEqual(assist.foreground_guide(child), ("vim", 601))
            probe.assert_called_once_with(601)

    @unittest.skipUnless(os.name == "posix", "POSIX PTY erforderlich")
    def test_unknown_or_disappeared_process_hides_controls(self):
        child = SimpleNamespace(fd=42, pid=500)
        with patch.object(assist.os, "tcgetpgrp", return_value=601), \
             patch.object(assist.os, "getpgid", return_value=500), \
             patch.object(assist, "_process_name", return_value="ssh"):
            self.assertIsNone(assist.foreground_guide(child))
        with patch.object(assist.os, "tcgetpgrp", side_effect=OSError("PTY geschlossen")):
            self.assertIsNone(assist.foreground_guide(child))
        self.assertIsNone(assist.foreground_guide(None))

    def test_user_guide_config_is_declarative_and_restricted(self):
        data = {"programs": [
            {"name": "custompager", "label": "My Pager", "keys": ["q"],
             "help_text": "Zum Beenden q druecken.", "aliases": ["cpager"]},
            {"name": "multiplexer", "label": "Mux", "keys": ["CTRL+B", "d"],
             "help_text": "Sitzung trennen.", "button_label": "Trennen"},
            {"name": "bash", "label": "Ungesichert", "keys": ["CTRL+C"],
             "help_text": "Nicht erlaubt"},
            {"name": "vim", "label": "Ueberschreiben", "keys": ["CTRL+C"],
             "help_text": "Nicht erlaubt"},
        ]}
        with tempfile.TemporaryDirectory() as folder:
            file_path = Path(folder) / "program_guides.json"
            file_path.write_text(json.dumps(data), encoding="utf-8")
            guides, aliases, errors = assist.load_user_guides(file_path)
        self.assertEqual(set(guides), {"custompager", "multiplexer"})
        self.assertEqual(guides["multiplexer"].exit_bytes, b"\x02d")
        self.assertEqual(guides["multiplexer"].primary_label, "Trennen")
        self.assertEqual(aliases["cpager"], "custompager")
        self.assertEqual(len(errors), 2)
        self.assertEqual(assist.GUIDES["vim"].exit_bytes, b"\x1b:q\r")

    def test_user_guide_rejects_duplicate_aliases_and_arbitrary_sequences(self):
        data = {"programs": [
            {"name": "first", "label": "A", "help_text": "A", "keys": ["q"],
             "aliases": ["dupe"]},
            {"name": "second", "label": "B", "help_text": "B", "keys": ["q"],
             "aliases": ["dupe"]},
            {"name": "rawescape", "label": "C", "help_text": "C",
             "keys": ["\x1b[5n"]},
        ]}
        with tempfile.TemporaryDirectory() as folder:
            file_path = Path(folder) / "program_guides.json"
            file_path.write_text(json.dumps(data), encoding="utf-8")
            guides, _, errors = assist.load_user_guides(file_path)
        self.assertEqual(set(guides), {"first"})
        self.assertEqual(len(errors), 2)
        self.assertEqual(assist.encode_guide_keys(["F10"]), b"\x1b[21~")
        with self.assertRaises(ValueError):
            assist.encode_guide_keys(["\x1b[9m"])

    def test_missing_user_config_does_not_add_programs(self):
        with tempfile.TemporaryDirectory() as folder:
            guides, aliases, errors = assist.load_user_guides(Path(folder) / "missing.json")
        self.assertEqual((guides, aliases, errors), ({}, {}, []))
        self.assertIsNone(assist.canonical_program("bash"))

    def test_platform_unsupported_hides_controls(self):
        with patch.object(assist.os, "name", "nt"):
            self.assertIsNone(assist.foreground_guide(SimpleNamespace(fd=12, pid=11)))


if __name__ == "__main__":
    unittest.main()
