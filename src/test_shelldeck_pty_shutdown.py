"""Regressionen fuer PTY-Shutdown und gemeinsame waitpid-Aufrufe.

Die Methoden werden per AST geladen, damit POSIX-/ConPTY-Prozesslogik ohne
PySide6 getestet werden kann. Das erspart aber keine echte GUI-Pruefung.
"""
import os
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from test_shelldeck_pty_lifecycle import extract_class, extract_method


def method(name):
    return extract_method("PtyTerminalProcess", name, {"time": time})


class FakePty:
    def __init__(self, *, exits_on_terminate=False, exits_on_kill=True):
        self.exits_on_terminate = exits_on_terminate
        self.exits_on_kill = exits_on_kill
        self.alive = True
        self.events = []

    def terminate(self):
        self.events.append("terminate")
        if self.exits_on_terminate:
            self.alive = False

    def kill(self):
        self.events.append("kill")
        if self.exits_on_kill:
            self.alive = False

    def wait_for_exit(self, timeout):
        self.events.append("wait")
        return not self.alive

    def close(self):
        self.events.append("close")


class ShutdownTests(unittest.TestCase):
    def _process(self, pty, *, reader_done=True):
        # Die aufgerufenen Methoden nutzen nur die QProcess-kompatible API.
        obj = SimpleNamespace(_pty=pty, _running=True, reader_stops=[],
                              stop_after_close=reader_done)
        obj._wait_child_exit = lambda child, ms: method("_wait_child_exit")(obj, child, ms)
        obj._stop_reader_before_pty_close = lambda ms: (
            obj.reader_stops.append(ms) or (reader_done or "close" in pty.events)
        )
        obj.waitForFinished = lambda ms: True
        obj.kill = lambda: method("kill")(obj)
        obj.terminate = lambda: pty.terminate()
        return obj

    def test_kill_waits_for_child_even_when_reader_already_stopped(self):
        pty = FakePty()
        proc = self._process(pty)
        self.assertTrue(proc.kill())
        self.assertEqual(pty.events, ["terminate", "wait", "kill", "wait", "close"])
        self.assertIsNone(proc._pty)
        self.assertFalse(proc._running)

    def test_no_sigkill_if_sigterm_ends_child(self):
        pty = FakePty(exits_on_terminate=True)
        proc = self._process(pty)
        self.assertTrue(proc.kill())
        self.assertEqual(pty.events, ["terminate", "wait", "close"])

    def test_kill_reports_failure_if_child_refuses_both_signals(self):
        pty = FakePty(exits_on_kill=False)
        proc = self._process(pty)
        self.assertFalse(proc.kill())
        self.assertIn("kill", pty.events)
        self.assertEqual(pty.events[-1], "close")

    def test_closing_master_unblocks_reader(self):
        pty = FakePty(exits_on_terminate=True)
        proc = self._process(pty, reader_done=False)
        self.assertTrue(proc.kill())
        self.assertEqual(proc.reader_stops, [250, 500])
        self.assertEqual(pty.events[-1], "close")

    def test_shutdown_cannot_report_success_only_because_reader_stopped(self):
        pty = FakePty(exits_on_kill=False)
        proc = self._process(pty)
        proc._reader = object()
        self.assertFalse(method("shutdown")(proc, graceful_ms=0, force_ms=0))
        self.assertIn("kill", pty.events)

    def test_shutdown_graceful_exit_needs_reader_cleanup(self):
        pty = FakePty(exits_on_terminate=True)
        proc = self._process(pty, reader_done=False)
        proc._reader = object()
        self.assertTrue(method("shutdown")(proc, graceful_ms=0, force_ms=0))
        self.assertEqual(pty.events, ["terminate", "wait", "close"])
        self.assertEqual(proc.reader_stops, [0, 0])

    def test_conpty_like_backend_waits_for_child_not_reader(self):
        proc = SimpleNamespace(waitForFinished=lambda ms: self.fail("Reader is no child"))
        child = SimpleNamespace(isalive=lambda: True)
        self.assertFalse(method("_wait_child_exit")(proc, child, 0))
        child.isalive = lambda: False
        self.assertTrue(method("_wait_child_exit")(proc, child, 0))


@unittest.skipUnless(os.name == "posix", "POSIX waitpid erforderlich")
class WaitpidSynchronizationTests(unittest.TestCase):
    def test_reader_and_gui_cannot_overwrite_collected_exitcode(self):
        import shlex
        child_type = extract_class("PosixPtyChild", {"os": os, "shlex": shlex})
        fake_fd_r, fake_fd_w = os.pipe()
        child = child_type(pid=999001, fd=fake_fd_r)
        first_entered = threading.Event()
        release_first = threading.Event()
        counter = []

        def fake_waitpid(pid, options):
            counter.append(pid)
            if len(counter) == 1:
                first_entered.set()
                self.assertTrue(release_first.wait(2))
                return pid, 23 << 8
            raise ChildProcessError("already reaped")

        try:
            results = []
            with mock.patch.object(os, "waitpid", side_effect=fake_waitpid):
                t1 = threading.Thread(target=lambda: results.append(child.isalive()))
                t2 = threading.Thread(target=lambda: results.append(child.isalive()))
                t1.start()
                self.assertTrue(first_entered.wait(2))
                t2.start()
                # t2 muss warten, bis t1 den echten Exit-Code eingetragen hat.
                release_first.set()
                t1.join(2)
                t2.join(2)
                self.assertFalse(t1.is_alive() or t2.is_alive())
            self.assertEqual(results, [False, False])
            self.assertEqual(child.exitstatus, 23)
            self.assertEqual(counter, [999001])
        finally:
            release_first.set()
            child.close()
            os.close(fake_fd_w)


if __name__ == "__main__":
    unittest.main()
