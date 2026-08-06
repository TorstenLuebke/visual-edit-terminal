"""Tests der Kommandozeilenauswertung (ohne Qt).

Ausfuehren (aus dem src-Ordner):

    python -m unittest test_shelldeck_cli
    # oder
    python test_shelldeck_cli.py
"""

import os
import tempfile
import unittest
from pathlib import Path

from shelldeck_cli import (
    LaunchOptions,
    parse_launch_arguments,
    resolve_directory,
    split_command_string,
)


class WorkingDirectoryTests(unittest.TestCase):
    def test_working_directory_linux_path(self):  # Fall 1
        opts = parse_launch_arguments(["--working-directory", "/home/torsten/Downloads"])
        self.assertEqual(opts.working_directory, "/home/torsten/Downloads")
        self.assertFalse(opts.errors)

    def test_working_directory_windows_path(self):  # Fall 2
        opts = parse_launch_arguments(["--working-directory", r"C:\Users\Torsten\Downloads"])
        self.assertEqual(opts.working_directory, r"C:\Users\Torsten\Downloads")

    def test_path_with_spaces(self):  # Fall 3
        opts = parse_launch_arguments(["--working-directory", "/home/torsten/Meine Projekte"])
        self.assertEqual(opts.working_directory, "/home/torsten/Meine Projekte")

    def test_inline_equals_form(self):
        opts = parse_launch_arguments(["--working-directory=/tmp/x y"])
        self.assertEqual(opts.working_directory, "/tmp/x y")

    def test_relative_path_resolsolves_to_absolute(self):  # Fall 4
        resolved, exists = resolve_directory(".")
        self.assertTrue(os.path.isabs(resolved))
        self.assertTrue(exists)

    def test_tilde_expansion(self):  # Fall 5
        resolved, exists = resolve_directory("~")
        self.assertEqual(resolved, os.path.normpath(str(Path.home())))
        self.assertTrue(exists)

    def test_nonexistent_directory(self):  # Fall 6
        resolved, exists = resolve_directory("/pfad/gibt/es/nicht/12345")
        self.assertFalse(exists)
        self.assertTrue(resolved)  # Absturzfrei, Pfad wird trotzdem geliefert

    def test_file_instead_of_directory(self):  # Fall 7
        with tempfile.NamedTemporaryFile() as handle:
            resolved, exists = resolve_directory(handle.name)
            self.assertFalse(exists)

    def test_env_var_expansion(self):
        os.environ["SHELLDECK_TEST_DIR"] = str(Path.home())
        resolved, exists = resolve_directory("$SHELLDECK_TEST_DIR")
        self.assertTrue(exists)


class NewTabTests(unittest.TestCase):
    def test_new_tab_with_path(self):  # Fall 8
        opts = parse_launch_arguments(["--new-tab", "/home/torsten/Downloads"])
        self.assertTrue(opts.new_tab)
        self.assertEqual(opts.new_tab_directory, "/home/torsten/Downloads")
        self.assertEqual(opts.requested_directory, "/home/torsten/Downloads")

    def test_new_tab_without_path(self):
        opts = parse_launch_arguments(["--new-tab"])
        self.assertTrue(opts.new_tab)
        self.assertEqual(opts.new_tab_directory, "")


class ExecuteTests(unittest.TestCase):
    def test_execute_short(self):  # Fall 9
        opts = parse_launch_arguments(["-e", "git", "status"])
        self.assertTrue(opts.execute_requested)
        self.assertEqual(opts.execute_command, ["git", "status"])

    def test_execute_long(self):  # Fall 10
        opts = parse_launch_arguments(["--execute", "git", "status"])
        self.assertTrue(opts.execute_requested)
        self.assertEqual(opts.execute_command, ["git", "status"])

    def test_execute_multiple_arguments_preserved(self):  # Fall 11
        argv = ["-e", "git", "commit", "-m", "Nachricht mit Leerzeichen"]
        opts = parse_launch_arguments(argv)
        self.assertEqual(
            opts.execute_command,
            ["git", "commit", "-m", "Nachricht mit Leerzeichen"],
        )

    def test_working_directory_and_command_combined(self):  # Fall 12
        argv = ["--working-directory", "/tmp", "-e", "pwd"]
        opts = parse_launch_arguments(argv)
        self.assertEqual(opts.working_directory, "/tmp")
        self.assertEqual(opts.execute_command, ["pwd"])

    def test_missing_command_after_e(self):  # Fall 13
        opts = parse_launch_arguments(["-e"])
        self.assertTrue(opts.execute_requested)
        self.assertEqual(opts.execute_command, [])
        self.assertTrue(opts.errors)

    def test_execute_does_not_split_option_like_tokens(self):
        # Ein "-l" nach dem Befehl gehoert zum Befehl, nicht zu ShellDeck.
        opts = parse_launch_arguments(["-e", "ls", "-l", "-a"])
        self.assertEqual(opts.execute_command, ["ls", "-l", "-a"])

    def test_execute_inline_string(self):
        opts = parse_launch_arguments(["--command=git status"])
        self.assertEqual(opts.execute_command, ["git", "status"])


class CompatibilityTests(unittest.TestCase):
    def test_unknown_arguments_collected(self):  # Fall 14
        opts = parse_launch_arguments(["--voellig-unbekannt", "--working-directory", "/tmp"])
        self.assertIn("--voellig-unbekannt", opts.unknown)
        self.assertEqual(opts.working_directory, "/tmp")

    def test_ignored_compat_options(self):
        opts = parse_launch_arguments(["--title", "Fenster", "--geometry", "80x24",
                                       "--working-directory", "/tmp"])
        self.assertIn("--title", opts.ignored)
        self.assertIn("--geometry", opts.ignored)
        self.assertEqual(opts.working_directory, "/tmp")

    def test_bare_positional_is_directory(self):
        opts = parse_launch_arguments(["/home/torsten"])
        self.assertEqual(opts.working_directory, "/home/torsten")

    def test_x_alias_executes(self):
        opts = parse_launch_arguments(["-x", "htop"])
        self.assertTrue(opts.execute_requested)
        self.assertEqual(opts.execute_command, ["htop"])

    def test_split_command_string(self):
        self.assertEqual(split_command_string('git commit -m "a b"'),
                         ["git", "commit", "-m", "a b"])
        self.assertEqual(split_command_string(""), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
