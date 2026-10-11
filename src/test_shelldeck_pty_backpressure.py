"""PTY/ConPTY backpressure: Qt-unabhaengige Regressionen fuer Reader und GUI."""

import ast
from pathlib import Path
import threading
import time
import unittest
from types import SimpleNamespace


SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def method(cls_name, name, namespace=None):
    cls = next(node for node in TREE.body if isinstance(node, ast.ClassDef) and node.name == cls_name)
    fn = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    ns = dict(namespace or {})
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), str(SOURCE), "exec"), ns)
    return ns[name]


class Signal:
    def __init__(self):
        self.events = []
        self.received = threading.Event()

    def emit(self, *args):
        self.events.append(args)
        self.received.set()


class TestPtyBackpressure(unittest.TestCase):
    def make_reader(self, chunks):
        class Child:
            exitstatus = 0
            def __init__(self):
                self.chunks = list(chunks)
                self.calls = 0
            def read(self, _size):
                self.calls += 1
                if not self.chunks:
                    raise AssertionError("reader continued after EOF")
                return self.chunks.pop(0)
            def isalive(self):
                return False

        child = Child()
        interrupt = threading.Event()
        reader = SimpleNamespace(
            pty_process=child,
            output_ready=Signal(), finished_ready=Signal(), error_ready=Signal(),
            _delivery_ack=threading.Event(), _read_permission=threading.Event(),
            isInterruptionRequested=interrupt.is_set,
            msleep=lambda _n: None,
        )
        reader._delivery_ack.set()
        reader._read_permission.set()
        return reader, child, interrupt

    def test_one_signal_in_flight_then_pause_then_resume(self):
        run = method("PtyReaderThread", "run", {
            "QProcess": SimpleNamespace(ExitStatus=SimpleNamespace(NormalExit=0)),
        })
        reader, child, interrupt = self.make_reader([b"first", b"second", b""])
        worker = threading.Thread(target=run, args=(reader,), daemon=True)
        worker.start()
        try:
            self.assertTrue(reader.output_ready.received.wait(1), "first chunk never emitted")
            # Without the acknowledge() handshake the reader could generate a
            # potentially unbounded queued sequence of Qt signals.
            time.sleep(0.1)
            self.assertEqual(child.calls, 1)
            self.assertEqual(reader.output_ready.events, [(b"first",)])

            pause = method("PtyReaderThread", "set_read_paused")
            pause(reader, True)
            reader._delivery_ack.set()  # simulated GUI has processed first packet
            time.sleep(0.1)
            self.assertEqual(child.calls, 1, "PTY must not read while display is backed up")

            pause(reader, False)
            deadline = time.monotonic() + 1
            while len(reader.output_ready.events) < 2 and time.monotonic() < deadline:
                time.sleep(0.005)
            self.assertEqual(reader.output_ready.events, [(b"first",), (b"second",)])
            reader._delivery_ack.set()
            worker.join(1)
            self.assertFalse(worker.is_alive())
            self.assertEqual(reader.finished_ready.events, [(0, 0)])
            self.assertIsNone(reader.pty_process)
        finally:
            interrupt.set()
            reader._read_permission.set()
            reader._delivery_ack.set()
            worker.join(1)

    def test_reader_exits_during_pause_without_any_read(self):
        run = method("PtyReaderThread", "run", {
            "QProcess": SimpleNamespace(ExitStatus=SimpleNamespace(NormalExit=0)),
        })
        reader, child, interrupt = self.make_reader([b"unused"])
        reader._read_permission.clear()
        worker = threading.Thread(target=run, args=(reader,), daemon=True)
        worker.start()
        time.sleep(0.06)
        interrupt.set()
        worker.join(1)
        self.assertFalse(worker.is_alive(), "tab shutdown must not hang on a paused reader")
        self.assertEqual(child.calls, 0)
        self.assertEqual(reader.finished_ready.events, [(0, 0)])

    def test_reader_exits_during_unacknowledged_delivery(self):
        run = method("PtyReaderThread", "run", {
            "QProcess": SimpleNamespace(ExitStatus=SimpleNamespace(NormalExit=0)),
        })
        reader, child, interrupt = self.make_reader([b"pending", b"unused"])
        worker = threading.Thread(target=run, args=(reader,), daemon=True)
        worker.start()
        self.assertTrue(reader.output_ready.received.wait(1))
        interrupt.set()
        worker.join(1)
        self.assertFalse(worker.is_alive(), "tab shutdown must not hang waiting for Qt acknowledgement")
        self.assertEqual(child.calls, 1)
        self.assertEqual(reader.output_ready.events, [(b"pending",)])

    def test_two_independent_readers_do_not_block_each_other(self):
        run = method("PtyReaderThread", "run", {
            "QProcess": SimpleNamespace(ExitStatus=SimpleNamespace(NormalExit=0)),
        })
        first, child1, stop1 = self.make_reader([b"tab1", b""])
        second, child2, stop2 = self.make_reader([b"tab2", b""])
        first._read_permission.clear()
        t1 = threading.Thread(target=run, args=(first,), daemon=True)
        t2 = threading.Thread(target=run, args=(second,), daemon=True)
        t1.start()
        t2.start()
        try:
            self.assertTrue(second.output_ready.received.wait(1))
            second._delivery_ack.set()
            t2.join(1)
            self.assertFalse(t2.is_alive(), "another PTY tab must continue")
            self.assertEqual(second.output_ready.events, [(b"tab2",)])
            self.assertEqual(child1.calls, 0, "first tab must remain paused")
        finally:
            stop1.set()
            stop2.set()
            first._delivery_ack.set()
            second._delivery_ack.set()
            first._read_permission.set()
            second._read_permission.set()
            t1.join(1)
            t2.join(1)

    def test_gui_acknowledges_only_current_reader_even_on_error(self):
        append = method("PtyTerminalProcess", "_append_stdout")
        old, current = SimpleNamespace(acknowledge_output=Signal()), SimpleNamespace(acknowledge_output=Signal())
        ready = Signal()
        proc = SimpleNamespace(_reader=current, _stdout_buffer=bytearray(),
                               readyReadStandardOutput=ready, sender=lambda: old)
        append(proc, b"stale")
        self.assertEqual(proc._stdout_buffer, b"")
        self.assertEqual(current.acknowledge_output.events, [])

        # Signal objects are callable in Qt; here use a callback recorder.
        acks = []
        current.acknowledge_output = lambda: acks.append("ack")
        proc.sender = lambda: current
        append(proc, b"fresh")
        self.assertEqual(proc._stdout_buffer, b"fresh")
        self.assertEqual(acks, ["ack"])
        self.assertEqual(ready.events, [()])

        class BrokenSignal:
            def emit(self):
                raise RuntimeError("GUI callback failed")
        proc.readyReadStandardOutput = BrokenSignal()
        with self.assertRaisesRegex(RuntimeError, "GUI callback"):
            append(proc, b"more")
        self.assertEqual(acks, ["ack", "ack"])

    def test_gui_hysteresis_and_qprocess_unchanged(self):
        sync = method("ShellDeckTerminalWidget", "sync_pty_output_backpressure", {
            "TERMINAL_PTY_BACKPRESSURE_HIGH_CHARS": 1024,
            "TERMINAL_PTY_BACKPRESSURE_LOW_CHARS": 256,
        })
        calls = []
        queue = SimpleNamespace(pending_chars=1024)
        tab = SimpleNamespace(process=SimpleNamespace(set_output_paused=calls.append), _output_queue=queue)
        sync(tab)
        queue.pending_chars = 512
        sync(tab)
        queue.pending_chars = 256
        sync(tab)
        self.assertEqual(calls, [True, False])
        # QProcess does not expose the PTY-only flow-control method.
        tab.process = SimpleNamespace()
        sync(tab)
        tab.process = None
        sync(tab)


if __name__ == "__main__":
    unittest.main()
