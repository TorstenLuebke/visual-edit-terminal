"""Regressionstests fuer POSIX-PTY-Start aus einer mehrthreadigen GUI.

Benutzt bewusst nur die stdlib: Die Startlogik laesst sich damit auch ohne
installiertes PySide6 pruefen. Der GUI-Praxistest bleibt zusaetzlich noetig.
"""
import os
import shlex
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from test_shelldeck_pty_lifecycle import extract_class


@unittest.skipUnless(sys.platform.startswith("linux"), "Direktes posix_spawn-PTY wird unter Linux geprueft")
class PosixSpawnPtyTests(unittest.TestCase):
    def setUp(self):
        self.child_type = extract_class("PosixPtyChild", {"os": os, "shlex": shlex})

    def _read_child(self, child, timeout=5):
        chunks = []
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    data = child.read(4096)
                except EOFError:
                    break
                if data:
                    chunks.append(data)
                if not child.isalive() and not data:
                    # Nach dem Kind-Exit koennen noch Bytes im Master warten.
                    continue
            self.assertTrue(child.wait_for_exit(1.0), "PTY-Child laeuft nach Timeout noch")
            return b"".join(chunks)
        finally:
            child.close()
            if child.isalive():
                child.kill()
                child.wait_for_exit(1.0)

    def test_controlling_terminal_and_exit_status(self):
        script = (
            "import os,sys; "
            "print('TTY=%s' % os.isatty(0)); "
            "print('SESSION=%s' % (os.getsid(0)==os.getpid())); "
            "print('JOB_CONTROL=%s' % (os.tcgetpgrp(0)==os.getpgrp())); "
            "sys.exit(17)"
        )
        command = shlex.join([sys.executable, "-c", script])
        child = self.child_type.spawn(command)
        output = self._read_child(child)
        self.assertIn(b"TTY=True", output)
        self.assertIn(b"SESSION=True", output)
        self.assertIn(b"JOB_CONTROL=True", output)
        self.assertEqual(child.exitstatus, 17)

    def test_working_directory_with_spaces_and_quoted_arguments(self):
        with tempfile.TemporaryDirectory(prefix="ShellDeck Ordner ") as directory:
            token = "abc ; $(echo should-not-run)"
            script = "import os,sys; print('CWD=' + os.getcwd()); print('ARG=' + sys.argv[1])"
            child = self.child_type.spawn(shlex.join([sys.executable, "-c", script, token]), cwd=directory)
            output = self._read_child(child)
            self.assertIn(("CWD=" + os.path.realpath(directory)).encode(), output)
            self.assertIn(("ARG=" + token).encode(), output)
            self.assertEqual(child.exitstatus, 0)

    def test_resizing_and_writing_to_interactive_child(self):
        script = (
            "import os,sys,struct,fcntl,termios; "
            "answer=sys.stdin.readline().strip(); "
            "size=struct.unpack('HHHH', fcntl.ioctl(0, termios.TIOCGWINSZ, "
            "struct.pack('HHHH',0,0,0,0))); "
            "print('ANSWER=' + answer); "
            "print('SIZE=%d,%d' % size[:2])"
        )
        child = self.child_type.spawn(shlex.join([sys.executable, "-c", script]))
        try:
            self.assertTrue(child.set_window_size(40, 100))
            self.assertGreater(child.write("INPUT_OK\r"), 0)
            output = self._read_child(child)
            self.assertIn(b"ANSWER=INPUT_OK", output)
            self.assertIn(b"SIZE=40,100", output)
            self.assertEqual(child.exitstatus, 0)
        finally:
            child.close()

    def test_launch_in_thread_does_not_call_forkpty(self):
        # Genau der bisher gewarnte Fall: Die Qt-App hat mehrere Threads.
        other_running = threading.Event()
        other_release = threading.Event()
        def background():
            other_running.set()
            other_release.wait(5)
        helper = threading.Thread(target=background)
        helper.start()
        self.assertTrue(other_running.wait(1))
        result = {}
        def launch():
            try:
                command = shlex.join([sys.executable, "-c", "print('WORKER_OK')"])
                child = self.child_type.spawn(command)
                result["output"] = self._read_child(child)
                result["status"] = child.exitstatus
            except BaseException as exc:
                result["error"] = exc
        try:
            with mock.patch("pty.fork", side_effect=AssertionError("forkpty im GUI-Prozess")):
                worker = threading.Thread(target=launch)
                worker.start()
                worker.join(6)
                self.assertFalse(worker.is_alive(), "PTY-Start im Worker haengt")
            if "error" in result:
                raise result["error"]
            self.assertIn(b"WORKER_OK", result["output"])
            self.assertEqual(result["status"], 0)
        finally:
            other_release.set()
            helper.join(2)

    def test_unavailable_setsid_keeps_existing_fallback(self):
        marker = object()
        with mock.patch.object(os, "posix_spawnp", side_effect=NotImplementedError), \
             mock.patch.object(self.child_type, "_spawn_with_fork", return_value=marker) as fallback:
            result = self.child_type.spawn("/bin/sh -i", cwd="/tmp")
        self.assertIs(result, marker)
        fallback.assert_called_once_with(["/bin/sh", "-i"], "/tmp")

    def test_spawn_error_closes_both_openpty_descriptors(self):
        actual_openpty = os.openpty
        opened = []
        def record_fds():
            fds = actual_openpty()
            opened.extend(fds)
            return fds
        with mock.patch.object(os, "openpty", side_effect=record_fds), \
             mock.patch.object(os, "posix_spawnp", side_effect=FileNotFoundError(2, "missing")):
            with self.assertRaises(FileNotFoundError):
                self.child_type.spawn("/binary/does-not-exist")
        self.assertEqual(len(opened), 2)
        for fd in opened:
            with self.assertRaises(OSError):
                os.fstat(fd)


if __name__ == "__main__":
    unittest.main()
