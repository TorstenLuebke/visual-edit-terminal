"""PTY lifecycle regressions; no Qt dependency, POSIX smoke check when available."""
import ast
import os
from pathlib import Path
import shlex
import sys
import time
import unittest
from types import SimpleNamespace

SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def extract_class(name, namespace):
    node = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == name)
    module = ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace[name]


def extract_method(class_name, method_name, namespace):
    cls = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace[method_name]


class RecordingSignal:
    def __init__(self):
        self.events = []

    def emit(self, *args):
        self.events.append(args)


class PtyLifecycleTests(unittest.TestCase):
    def test_reader_drains_output_after_child_exits_and_reports_its_exitcode(self):
        run = extract_method("PtyReaderThread", "run", {
            "QProcess": SimpleNamespace(ExitStatus=SimpleNamespace(NormalExit=0)),
        })

        class FinishedChild:
            exitstatus = 7

            def __init__(self):
                self.chunks = [b"letzte Ausgabe\r\n", b""]

            def read(self, _size):
                return self.chunks.pop(0)

            def isalive(self):
                return False

        child = FinishedChild()
        output = RecordingSignal()
        finish = RecordingSignal()
        reader = SimpleNamespace(pty_process=child, output_ready=output, finished_ready=finish,
                                 error_ready=RecordingSignal(), isInterruptionRequested=lambda: False,
                                 msleep=lambda _ms: None)
        run(reader)
        self.assertEqual(output.events, [(b"letzte Ausgabe\r\n",)])
        self.assertEqual(finish.events, [(7, 0)])
        self.assertIsNone(reader.pty_process)

    def test_reader_exits_when_backend_returns_none_after_exit(self):
        run = extract_method("PtyReaderThread", "run", {
            "QProcess": SimpleNamespace(ExitStatus=SimpleNamespace(NormalExit=0)),
        })

        class NoneChild:
            exitstatus = 0

            def __init__(self):
                self.read_count = 0

            def read(self, _size):
                self.read_count += 1
                if self.read_count > 3:
                    raise AssertionError("reader did not stop")
                return None

            def isalive(self):
                return False

        child = NoneChild()
        finish = RecordingSignal()
        reader = SimpleNamespace(pty_process=child, output_ready=RecordingSignal(),
                                 finished_ready=finish, error_ready=RecordingSignal(),
                                 isInterruptionRequested=lambda: False,
                                 msleep=lambda _ms: None)
        run(reader)
        self.assertEqual(child.read_count, 1)
        self.assertEqual(finish.events, [(0, 0)])

    @unittest.skipUnless(os.name == "posix", "POSIX PTY required")
    def test_posix_child_reads_tail_even_after_waitpid_reaps_child(self):
        child_type = extract_class("PosixPtyChild", {
            "os": os, "shlex": shlex,
        })
        command = shlex.join([sys.executable, "-c", "import sys; print('SHELLDECK_TAIL'); sys.exit(13)"])
        child = child_type.spawn(command)
        try:
            deadline = time.monotonic() + 5.0
            while child.isalive() and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertFalse(child.isalive(), "PTY child failed to exit")
            self.assertEqual(child.exitstatus, 13)
            chunks = []
            while time.monotonic() < deadline:
                try:
                    chunk = child.read(4096)
                except EOFError:
                    break
                if chunk:
                    chunks.append(chunk)
            self.assertIn(b"SHELLDECK_TAIL", b"".join(chunks))
        finally:
            child.close()


class PtyReaderSignalIsolationTests(unittest.TestCase):
    def test_stale_reader_cannot_change_current_process(self):
        append = extract_method("PtyTerminalProcess", "_append_stdout", {})
        error = extract_method("PtyTerminalProcess", "_handle_reader_error", {
            "QProcess": SimpleNamespace(ProcessError=SimpleNamespace(UnknownError=9)),
        })
        finished = extract_method("PtyTerminalProcess", "_handle_reader_finished", {})
        old_reader, current_reader = object(), object()
        stdout_signal, stderr_signal, error_signal, finish_signal = (
            RecordingSignal(), RecordingSignal(), RecordingSignal(), RecordingSignal()
        )
        process = SimpleNamespace(_reader=current_reader, _running=True,
                                  _stdout_buffer=bytearray(), _stderr_buffer=bytearray(),
                                  _error_string="", readyReadStandardOutput=stdout_signal,
                                  readyReadStandardError=stderr_signal, errorOccurred=error_signal,
                                  finished=finish_signal, sender=lambda: old_reader)
        append(process, b"ALT")
        error(process, "old reader error")
        finished(process, 99, 0)
        self.assertTrue(process._running)
        self.assertEqual(process._stdout_buffer, b"")
        self.assertEqual(process._stderr_buffer, b"")
        self.assertEqual(finish_signal.events, [])
        self.assertEqual(error_signal.events, [])

        process.sender = lambda: current_reader
        append(process, b"NEU")
        finished(process, 7, 0)
        finished(process, 7, 0)
        self.assertEqual(process._stdout_buffer, b"NEU")
        self.assertEqual(stdout_signal.events, [()])
        self.assertEqual(finish_signal.events, [(7, 0)])


class StaleRestoreTests(unittest.TestCase):
    def test_restore_callbacks_belong_to_one_shell_generation(self):
        callbacks = []
        timer = SimpleNamespace(singleShot=lambda delay, callback: callbacks.append(callback))
        schedule = extract_method("ShellDeckTerminalWidget", "schedule_restore_command", {"QTimer": timer})
        a, b = object(), object()
        sent = []
        tab = SimpleNamespace(process=a, _shell_generation=3, _terminal_cleaned_up=False,
                              run_restore_command=sent.append)
        self.assertTrue(schedule(tab, "source /opt/test-venv/bin/activate"))
        tab._shell_generation = 4  # restart, but QProcess object reused
        callbacks.pop(0)()
        self.assertEqual(sent, [])

        self.assertTrue(schedule(tab, "source /opt/new-venv/bin/activate"))
        tab.process = b  # engine changed
        callbacks.pop(0)()
        self.assertEqual(sent, [])

        self.assertTrue(schedule(tab, "source /opt/active-venv/bin/activate"))
        callbacks.pop(0)()
        self.assertEqual(sent, ["source /opt/active-venv/bin/activate"])

        self.assertTrue(schedule(tab, "source /opt/stale-venv/bin/activate"))
        tab._terminal_cleaned_up = True  # tab closed
        callbacks.pop(0)()
        self.assertEqual(sent, ["source /opt/active-venv/bin/activate"])


if __name__ == "__main__":
    unittest.main()
