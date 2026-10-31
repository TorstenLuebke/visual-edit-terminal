"""Patch 290: lossless long PTY paste, partial writes and GUI-thread staging.

Runs without PySide6; terminal process methods are extracted via AST so the
central PTY routing is still tested when the GUI toolkit is unavailable.
"""

import ast
import errno
import os
from pathlib import Path
import select
import threading
import time
from types import SimpleNamespace
import unittest

from shelldeck_pty_input_queue_289 import PtyInputQueue
from shelldeck_key_encoding import encode_paste


SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))


def extract_method(name, namespace):
    cls = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
               and node.name == "PtyTerminalProcess")
    fn = next(node for node in cls.body if isinstance(node, ast.FunctionDef)
              and node.name == name)
    ns = dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 str(SOURCE), "exec"), ns)
    return ns[name]


class FakeTimer:
    def __init__(self):
        self.active = False
    def start(self):
        self.active = True
    def stop(self):
        self.active = False
    def isActive(self):
        return self.active


class FakeSignal:
    def __init__(self):
        self.events = []
    def emit(self, *args):
        self.events.append(args)


class Child:
    def __init__(self, write_impl):
        self.calls = []
        self.write_impl = write_impl
    def write(self, payload):
        self.calls.append(bytes(payload))
        return self.write_impl(payload)


class TestPtyInputQueue(unittest.TestCase):
    def test_short_write_is_retried_exactly_without_duplicates(self):
        queue = PtyInputQueue(chunk_bytes=17)
        data = ("Ä🧪data\n" * 200).encode()
        self.assertTrue(queue.enqueue(data))
        out = bytearray()
        calls = 0
        def writer(buf):
            nonlocal calls
            calls += 1
            if calls % 7 == 0:
                raise BlockingIOError(errno.EAGAIN, "busy")
            n = min(3, len(buf))
            out.extend(buf[:n])
            return n
        for _ in range(len(data) * 2):
            if not queue.pending_bytes:
                break
            queue.drain_once(writer)
        self.assertEqual(bytes(out), data)
        self.assertEqual(queue.pending_bytes, 0)

    def test_fifo_order_preserved_when_more_input_arrives(self):
        queue = PtyInputQueue(chunk_bytes=2)
        self.assertTrue(queue.enqueue(b"abcdef"))
        out = bytearray()
        def writer(buf):
            out.extend(buf)
            return len(buf)
        queue.drain_once(writer)
        self.assertTrue(queue.enqueue(b"CTRL"))
        while queue.pending_bytes:
            queue.drain_once(writer)
        self.assertEqual(bytes(out), b"abcdefCTRL")

    def test_queue_full_rejects_all_without_partial_append(self):
        queue = PtyInputQueue(chunk_bytes=4, max_pending_bytes=10)
        self.assertTrue(queue.enqueue(b"12345678"))
        self.assertFalse(queue.enqueue(b"ABC"))
        self.assertEqual(queue.pending_bytes, 8)
        out = bytearray()
        while queue.pending_bytes:
            queue.drain_once(lambda b: out.extend(b) or len(b))
        self.assertEqual(out, b"12345678")

    def test_unexpected_write_error_propagates_without_losing_queue(self):
        queue = PtyInputQueue(chunk_bytes=8)
        queue.enqueue(b"123456789")
        with self.assertRaisesRegex(OSError, "device"):
            queue.drain_once(lambda _: (_ for _ in ()).throw(OSError(errno.EIO, "device")))
        self.assertEqual(queue.pending_bytes, 9)
        queue.clear()
        self.assertEqual(queue.pending_bytes, 0)

    def test_234_line_heredoc_and_10000_line_paste_preserved(self):
        for line_count in (234, 1000, 10_000):
            with self.subTest(lines=line_count):
                script = "python3 - <<'PY'\n" + "".join(
                    f"print({i})\n" for i in range(line_count)) + "PY\n"
                data = encode_paste(script, bracketed=True)
                self.assertTrue(data.startswith(b"\x1b[200~"))
                self.assertTrue(data.endswith(b"\x1b[201~"))
                queue = PtyInputQueue()
                self.assertTrue(queue.enqueue(data))
                out = bytearray()
                while queue.pending_bytes:
                    queue.drain_once(lambda chunk: out.extend(chunk) or len(chunk))
                self.assertEqual(out, data)

    @unittest.skipUnless(os.name == "posix", "POSIX PTY required")
    def test_real_posix_pty_receives_234_lines_without_loss(self):
        # Use an actual PTY input channel, not only a fake writer. The slave
        # is raw; a separate reader drains it while the master gets chunks.
        import termios
        import tty
        master, slave = os.openpty()
        previous = termios.tcgetattr(slave)
        done = threading.Event()
        output = bytearray()
        script = "python3 - <<'PY'\n" + "".join(
            f"print({i})\n" for i in range(234)) + "PY\n"
        payload = encode_paste(script, bracketed=True)
        try:
            tty.setraw(slave)
            os.set_blocking(master, False)
            os.set_blocking(slave, False)
            def reader():
                deadline = time.monotonic() + 5
                while len(output) < len(payload) and time.monotonic() < deadline:
                    readable, _, _ = select.select([slave], [], [], 0.05)
                    if readable:
                        try:
                            output.extend(os.read(slave, 8192))
                        except BlockingIOError:
                            pass
                done.set()
            worker = threading.Thread(target=reader, daemon=True)
            worker.start()
            queue = PtyInputQueue()
            queue.enqueue(payload)
            deadline = time.monotonic() + 5
            while queue.pending_bytes and time.monotonic() < deadline:
                queue.drain_once(lambda chunk: os.write(master, chunk))
                time.sleep(0.001)
            self.assertEqual(queue.pending_bytes, 0)
            self.assertTrue(done.wait(5))
            self.assertEqual(bytes(output), payload)
        finally:
            termios.tcsetattr(slave, termios.TCSANOW, previous)
            os.close(master)
            os.close(slave)


class TestPtyProcessRouting(unittest.TestCase):
    @staticmethod
    def make_process(write_impl):
        class PosixPtyChild:  # Exact marker class for isinstance in extracted code.
            def __init__(self):
                self.calls = []
            def write(self, value):
                self.calls.append(bytes(value))
                return write_impl(value)
        class QProcess:
            class ProcessError:
                WriteError = "WriteError"
        ns = {"PosixPtyChild": PosixPtyChild, "QProcess": QProcess}
        for name in ("_clear_posix_input", "_drain_posix_input", "write"):
            ns[name] = extract_method(name, ns)
        fake = SimpleNamespace(_running=True, _pty=PosixPtyChild(),
                               _input_timer=FakeTimer(), _input_queue=PtyInputQueue(),
                               errorOccurred=FakeSignal(), _error_string="",
                               _input_bracketed_paste_pending=False)
        for name in ("_clear_posix_input", "_drain_posix_input", "write"):
            setattr(fake, name, ns[name].__get__(fake))
        return fake

    def test_long_write_is_queued_and_emitted_in_order(self):
        sent = bytearray()
        fake = self.make_process(lambda part: sent.extend(part) or len(part))
        raw = b"print(123)\r" * 500
        self.assertEqual(fake.write(raw), len(raw))
        self.assertEqual(len(sent), 256)
        self.assertTrue(fake._input_timer.isActive())
        self.assertEqual(fake.write(b"more"), 4)
        while fake._input_timer.isActive():
            fake._drain_posix_input()
        self.assertEqual(sent, raw + b"more")
        self.assertEqual(fake.errorOccurred.events, [])

    def test_partial_then_eagain_retries_on_next_tick(self):
        sent = bytearray()
        calls = 0
        def writer(part):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise BlockingIOError(errno.EAGAIN, "busy")
            n = min(41, len(part))
            sent.extend(part[:n])
            return n
        fake = self.make_process(writer)
        data = b"X" * 700
        self.assertEqual(fake.write(data), 700)
        while fake._input_timer.isActive():
            fake._drain_posix_input()
        self.assertEqual(sent, data)

    def test_ctrl_c_drops_remaining_paste_and_is_sent_immediately(self):
        sent = bytearray()
        fake = self.make_process(lambda part: sent.extend(part) or len(part))
        fake.write(b"paste" * 1000)
        self.assertTrue(fake._input_queue.pending_bytes)
        self.assertEqual(fake.write(b"\x03"), 1)
        self.assertFalse(fake._input_timer.isActive())
        self.assertEqual(sent[-1:], b"\x03")
        self.assertEqual(fake._input_queue.pending_bytes, 0)

    def test_ctrl_c_closes_incomplete_bracketed_paste(self):
        sent = bytearray()
        fake = self.make_process(lambda part: sent.extend(part) or len(part))
        payload = b"\x1b[200~" + (b"print(1)\r" * 1000) + b"\x1b[201~"
        fake.write(payload)
        self.assertTrue(fake._input_bracketed_paste_pending)
        self.assertEqual(fake.write(b"\x03"), 1)
        self.assertEqual(sent[-7:], b"\x1b[201~\x03")
        self.assertFalse(fake._input_bracketed_paste_pending)
        self.assertFalse(fake._input_timer.isActive())

    def test_write_errors_are_reported_and_queue_reset(self):
        fake = self.make_process(lambda _: (_ for _ in ()).throw(OSError(errno.EIO, "gone")))
        self.assertEqual(fake.write(b"paste" * 300), -1)
        self.assertEqual(fake.errorOccurred.events, [("WriteError",)])
        self.assertEqual(fake._input_queue.pending_bytes, 0)

    def test_queue_limit_reports_error_without_sending_extra_bytes(self):
        fake = self.make_process(lambda part: len(part))
        fake._input_queue = PtyInputQueue(max_pending_bytes=16)
        self.assertEqual(fake.write(b"x" * 32), -1)
        self.assertEqual(fake._input_queue.pending_bytes, 0)
        self.assertEqual(fake.errorOccurred.events, [("WriteError",)])


if __name__ == "__main__":
    unittest.main()
