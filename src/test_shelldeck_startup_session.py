"""Regression tests for POSIX GUI startup and controlling-terminal sessions."""

import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import Mock, patch

import shelldeck_startup_session as startup


class StartupSessionTests(unittest.TestCase):
    def test_controlling_tty_detected_even_with_redirected_stdin(self):
        with patch.object(startup.os, "name", "posix"), \
             patch.object(startup.os, "open", return_value=42) as opened, \
             patch.object(startup.os, "close") as closed, \
             patch.object(startup.os, "tcgetpgrp", return_value=100):
            self.assertTrue(startup.has_controlling_terminal())
        opened.assert_called_once_with("/dev/tty", os.O_RDONLY | getattr(os, "O_NOCTTY", 0))
        closed.assert_called_once_with(42)

    def test_normal_desktop_launch_is_unchanged(self):
        with patch.object(startup.os, "name", "posix"), \
             patch.object(startup, "has_controlling_terminal", return_value=False), \
             patch.object(startup.subprocess, "Popen") as spawn:
            self.assertIsNone(startup.relaunch_without_controlling_tty(["src/main.py"]))
            spawn.assert_not_called()
        with patch.object(startup.os, "name", "posix"), \
             patch.object(startup.os, "open", side_effect=OSError("no tty")):
            self.assertFalse(startup.has_controlling_terminal())

    def test_detached_source_launch_preserves_arguments_and_waits(self):
        proc = Mock()
        proc.wait.return_value = 0
        with patch.object(startup.os, "name", "posix"), \
             patch.object(startup, "has_controlling_terminal", return_value=True), \
             patch.object(startup.sys, "executable", "/path/python"), \
             patch.object(startup.subprocess, "Popen", return_value=proc) as spawn:
            code = startup.relaunch_without_controlling_tty(["src/main.py", "--directory", "hello world"])
        self.assertEqual(code, 0)
        args, options = spawn.call_args
        self.assertEqual(args[0], ["/path/python", "src/main.py", "--directory", "hello world"])
        self.assertIs(options["stdin"], subprocess.DEVNULL)
        self.assertTrue(options["start_new_session"])
        proc.wait.assert_called_once_with()

    def test_compiled_application_is_not_given_python_script_path(self):
        proc = Mock()
        proc.wait.return_value = 0
        with patch.object(startup.os, "name", "posix"), \
             patch.object(startup, "has_controlling_terminal", return_value=True), \
             patch.object(startup.sys, "executable", "/opt/ShellDeck"), \
             patch.object(startup.subprocess, "Popen", return_value=proc) as spawn:
            self.assertEqual(startup.relaunch_without_controlling_tty(["/opt/ShellDeck", "--new-tab"]), 0)
        self.assertEqual(spawn.call_args.args[0], ["/opt/ShellDeck", "--new-tab"])

    def test_child_signal_is_reported_as_shell_exit_code(self):
        proc = Mock()
        proc.wait.return_value = -11
        with patch.object(startup.os, "name", "posix"), \
             patch.object(startup, "has_controlling_terminal", return_value=True), \
             patch.object(startup.subprocess, "Popen", return_value=proc):
            self.assertEqual(startup.relaunch_without_controlling_tty(["src/main.py"]), 139)

    def test_parent_process_does_not_relaunch_on_non_posix(self):
        with patch.object(startup.os, "name", "nt"), \
             patch.object(startup, "has_controlling_terminal") as check:
            self.assertIsNone(startup.relaunch_without_controlling_tty())
            check.assert_not_called()


if __name__ == "__main__":
    unittest.main()
