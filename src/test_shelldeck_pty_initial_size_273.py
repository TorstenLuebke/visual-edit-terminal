"""Patch 273: PTY size must exist before the shell renders its first prompt.

POSIX integration tests use only stdlib and inspect the child terminal with
TIOCGWINSZ as its very first action. No Qt, pyte or real GUI needed here.
"""
from __future__ import annotations

import os
import shlex
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

from test_shelldeck_pty_lifecycle import extract_class, extract_method


@unittest.skipUnless(sys.platform.startswith("linux"), "POSIX PTY Linux test")
class InitialPtyGeometry273(unittest.TestCase):
    def setUp(self):
        self.child_type = extract_class("PosixPtyChild", {"os": os, "shlex": shlex})

    def test_child_sees_initial_size_before_first_terminal_output(self):
        script = (
            "import os,fcntl,struct,termios; "
            "size=struct.unpack('HHHH',fcntl.ioctl(0,termios.TIOCGWINSZ,bytes(8))); "
            "print('INITIAL=%d,%d' % size[:2],flush=True)"
        )
        for rows, cols in ((24, 80), (46, 155)):
            with self.subTest(rows=rows, cols=cols):
                child = self.child_type.spawn(
                    shlex.join([sys.executable, "-c", script]),
                    initial_size=(rows, cols),
                )
                chunks = []
                try:
                    import time
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        try:
                            data = child.read(4096)
                        except EOFError:
                            break
                        if data:
                            chunks.append(data)
                        if not child.isalive() and not data:
                            continue
                    self.assertTrue(child.wait_for_exit(1))
                    self.assertEqual(child.exitstatus, 0)
                finally:
                    child.close()
                    if child.isalive():
                        child.kill()
                        child.wait_for_exit(1)
                self.assertIn(f"INITIAL={rows},{cols}".encode(), b"".join(chunks))

    def test_invalid_initial_size_is_rejected_before_openpty(self):
        for bad in ((0, 80), (-1, 80), (24, 0), (24, 65536), (None, 80)):
            with self.subTest(bad=bad), mock.patch.object(os, "openpty") as opened:
                with self.assertRaises(ValueError):
                    self.child_type.spawn("/bin/sh", initial_size=bad)
                opened.assert_not_called()

    def test_no_initial_size_remains_backwards_compatible(self):
        from test_shelldeck_pty_spawn import PosixSpawnPtyTests
        # Existing spawn call sites still work without a geometry argument.
        case = PosixSpawnPtyTests("test_controlling_terminal_and_exit_status")
        case.setUp()
        case.test_controlling_terminal_and_exit_status()


class InitialSizeHandoff273(unittest.TestCase):
    def test_process_rejects_invalid_geometry(self):
        setter = extract_method("PtyTerminalProcess", "set_initial_window_size", {})
        state = SimpleNamespace(_initial_window_size=None)
        self.assertFalse(setter(state, 0, 120))
        self.assertIsNone(state._initial_window_size)
        self.assertTrue(setter(state, 40, 120))
        self.assertEqual(state._initial_window_size, (40, 120))
        self.assertFalse(setter(state, "garbage", 120))
        self.assertEqual(state._initial_window_size, (40, 120))

    def test_process_forwards_initial_size_to_posix_spawn(self):
        events = []

        class Signal:
            def connect(self, _slot):
                pass

        class Reader:
            output_ready = Signal()
            error_ready = Signal()
            finished_ready = Signal()

            def __init__(self, _child, _parent):
                pass

            def start(self):
                events.append(("reader_started",))

        def spawn(command, *, cwd, initial_size):
            events.append(("spawn", command, cwd, initial_size))
            return object()

        process = SimpleNamespace(
            availability_message=lambda: "",
            _command_line=lambda program, args: "/bin/bash -i",
            _working_directory="/tmp",
            _initial_window_size=(46, 155),
            _append_stdout=lambda data: None,
            _handle_reader_error=lambda message: None,
            _handle_reader_finished=lambda *args: None,
        )
        start = extract_method("PtyTerminalProcess", "start", {
            "sys": sys,
            "PosixPtyChild": SimpleNamespace(spawn=spawn),
            "PtyReaderThread": Reader,
        })
        start(process, "/bin/bash", ["-i"])
        self.assertEqual(events, [
            ("spawn", "/bin/bash -i", "/tmp", (46, 155)),
            ("reader_started",),
        ])
        self.assertTrue(process._running)

    def _start_fake_shell(self, supports_pty):
        events = []

        class FakeProcess:
            def setWorkingDirectory(self, directory):
                events.append(("cwd", directory))

            def start(self, program, arguments):
                events.append(("start", program, tuple(arguments)))

        process = FakeProcess()
        if supports_pty:
            process.set_initial_window_size = lambda r, c: events.append(("initial", r, c))
        fake = SimpleNamespace(
            _shell_generation=0,
            _reset_shell_transient_state=lambda: None,
            window=SimpleNamespace(
                system_shell=lambda name: "/bin/bash",
                shell_start_args=lambda name: ["-i"],
                qprocess_bash_mode=None,
            ),
            shell_type="zsh",  # bypass the Bash rcfile; exercise generic wiring
            start_directory="",
            process=process,
            process_uses_pty_engine=lambda: supports_pty,
            _terminal_grid_size=lambda: (46, 155),
            _shelldeck_prompt_rc=None,
            _update_auto_vt_timer=lambda: None,
            update_terminal_size=lambda: None,
            display_shell_status=lambda *args: None,
            _last_pty_size=None,
        )
        callback = extract_method("ShellDeckTerminalWidget", "start_shell", {
            "os": os, "sys": sys,
            "QProcess": type("QProcess", (), {}),
            "batch_for_session": lambda _: False,
            "QTimer": SimpleNamespace(singleShot=lambda *args: None),
        })
        callback(fake)
        return events

    def test_host_sets_geometry_before_process_start(self):
        events = self._start_fake_shell(True)
        self.assertEqual(events[:2], [
            ("initial", 46, 155), ("start", "/bin/bash", ("-i",)),
        ])

    def test_qprocess_does_not_receive_pty_initialisation(self):
        self.assertEqual(self._start_fake_shell(False),
                         [("start", "/bin/bash", ("-i",))])


if __name__ == "__main__":
    unittest.main()
