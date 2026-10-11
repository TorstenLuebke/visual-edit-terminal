"""Qt-unabhaengige QProcess-Ausgabetests fuer portionierte Pipe-Lesezugriffe.

Die Tests ersetzen QProcess durch einen Fake-Pipe-Speicher. Reale Qt-Signale
und der Qt-interne Pipe-Puffer muessen zusaetzlich manuell geprueft werden.
"""
import ast
import codecs
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest

from shelldeck_output_buffer import TerminalOutputBuffer

SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ShellDeckTerminalWidget")


def extract(names):
    nodes = [n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name in names]
    if len(nodes) != len(names):
        raise AssertionError("Missing method")
    scope = {
        "QProcess": FakeProcess,
        "TERMINAL_QPROCESS_READ_SLICE_BYTES": 32768,
        "TERMINAL_QPROCESS_BACKPRESSURE_HIGH_CHARS": 1048576,
        "TERMINAL_QPROCESS_BACKPRESSURE_LOW_CHARS": 262144,
        "codecs": codecs,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SOURCE), "exec"), scope)
    return {name: scope[name] for name in names}


class FakeProcess:
    ProcessChannel = SimpleNamespace(StandardOutput=0, StandardError=1)

    def __init__(self, stdout=b"", stderr=b""):
        self.streams = {0: bytearray(stdout), 1: bytearray(stderr)}
        self.channel = 1
        self.read_sizes = []

    def readChannel(self):
        return self.channel

    def setReadChannel(self, channel):
        self.channel = channel

    def bytesAvailable(self):
        return len(self.streams[self.channel])

    def read(self, size):
        self.read_sizes.append(int(size))
        data = self.streams[self.channel][:size]
        del self.streams[self.channel][:size]
        return bytes(data)


class FakeTimer:
    def __init__(self):
        self.active = False
        self.starts = 0

    def isActive(self):
        return self.active

    def start(self, *_):
        self.starts += 1
        self.active = True

    def stop(self):
        self.active = False


class TestQProcessOutputPump(unittest.TestCase):
    NAMES = (
        "_take_shell_output_chunk", "_qprocess_buffered_bytes",
        "_schedule_qprocess_output_pump", "_sync_qprocess_output_backpressure",
        "_complete_qprocess_finish_if_drained", "_pump_qprocess_output",
        "handle_stdout", "handle_stderr", "handle_finished",
    )

    def make_tab(self, stdout=b"", stderr=b""):
        process = FakeProcess(stdout, stderr)
        tab = SimpleNamespace(
            process=process, _shell_generation=5, _output_queue=TerminalOutputBuffer(),
            _qprocess_output_paused=False, _qprocess_deferred_finish=None,
            _qprocess_output_timer=FakeTimer(),
            _qprocess_decoders={n: codecs.getincrementaldecoder("utf-8")("replace")
                                for n in ("stdout", "stderr")},
            sender=lambda: None, real_terminal_active=False, terminal_grid=None,
            _prompt_label_refresh_timer=FakeTimer(),
            append_command_task_output=lambda *a: None,
            handle_possible_password_prompt=lambda *_: None,
            handle_possible_interactive_prompt=lambda *_: None,
            refresh_password_prompt_state_after_output=lambda: None,
            refresh_interaction_prompt_state_after_output=lambda: None,
            finish_active_command_task_if_prompt_returned=lambda: None,
            terminal_stderr_color=lambda: "error",
        )
        for name, fn in extract(self.NAMES).items():
            setattr(tab, name, MethodType(fn, tab))
        # Farben werden im realen Widget von queue_terminal_output gesetzt;
        # im Fake pruefen wir die Reihenfolge des angenommenen Textes.
        tab.rendered = []
        def queue(text, color=None):
            tab.rendered.append((str(text), color))
            tab._output_queue.append(str(text), color)
        tab.queue_terminal_output = queue
        tab.decoded_terminal_output = lambda raw, *, qprocess_stream=None: (
            tab._qprocess_decoders[qprocess_stream].decode(bytes(raw), final=False)
            if qprocess_stream else bytes(raw).decode("utf-8", "replace"))
        tab._finalize_shell_process_finished = lambda code: tab.rendered.append((f"[exit:{code}]", None))
        return tab

    def test_channels_are_read_separately_and_in_bounded_slices(self):
        tab = self.make_tab(stdout=b"a"*100000, stderr=b"b"*70000)
        out = []
        while tab._qprocess_buffered_bytes(tab.process, "stdout"):
            out.append(tab._take_shell_output_chunk("stdout"))
        err = []
        while tab._qprocess_buffered_bytes(tab.process, "stderr"):
            err.append(tab._take_shell_output_chunk("stderr"))
        self.assertEqual(b"".join(out), b"a"*100000)
        self.assertEqual(b"".join(err), b"b"*70000)
        self.assertEqual(tab.process.channel, 1, "original Qt read channel must be restored")
        self.assertTrue(all(n <= 32768 for n in map(len, out+err)))
        self.assertEqual(set(tab.process.read_sizes), {32768})

    def test_backpressure_defers_qprocess_bytes_without_discarding(self):
        tab = self.make_tab(stdout=b"saved")
        tab._output_queue.append("x"*1048576, "std")
        tab._sync_qprocess_output_backpressure()
        self.assertTrue(tab._qprocess_output_paused)
        tab.handle_stdout()
        self.assertEqual(tab.process.streams[0], b"saved")
        self.assertFalse(tab._qprocess_output_timer.isActive())
        tab._output_queue.clear()
        tab._sync_qprocess_output_backpressure()
        self.assertFalse(tab._qprocess_output_paused)
        self.assertTrue(tab._qprocess_output_timer.isActive())
        tab._qprocess_output_timer.stop()
        tab._pump_qprocess_output()
        self.assertIn(("saved", None), tab.rendered)

    def test_utf8_across_qprocess_slice_boundary_and_late_process_finish(self):
        raw = b"X" * 32767 + "ö".encode("utf-8") + b"Z" * 35000
        tab = self.make_tab(stdout=raw, stderr=b"stderr")
        tab._qprocess_deferred_finish = (tab.process, 5, 7)
        tab.handle_stdout()
        self.assertNotIn(("[exit:7]", None), tab.rendered)
        for i in range(10):
            tab._qprocess_output_timer.stop()
            tab._pump_qprocess_output()
            if not tab.process.streams[0] and not tab.process.streams[1]:
                break
        self.assertEqual("".join(t for t, color in tab.rendered if color is None and t != "[exit:7]"),
                         raw.decode("utf-8"))
        self.assertEqual("".join(t for t, color in tab.rendered if color == "error"), "stderr")
        self.assertEqual(tab.rendered[-1], ("[exit:7]", None))
        self.assertEqual(tab._qprocess_deferred_finish, None)

    def test_old_finished_generation_is_not_applied_to_current_shell(self):
        tab = self.make_tab()
        tab._qprocess_deferred_finish = (tab.process, 4, 13)
        tab._complete_qprocess_finish_if_drained()
        self.assertEqual(tab._qprocess_deferred_finish[1], 4)
        self.assertNotIn(("[exit:13]", None), tab.rendered)

    def test_deferred_finish_marker_not_appended_before_remaining_bytes(self):
        tab = self.make_tab(stdout=b"a" * 70000)
        tab.handle_finished(0, None)
        self.assertNotIn(("[exit:0]", None), tab.rendered)
        for _ in range(5):
            tab._qprocess_output_timer.stop()
            tab._pump_qprocess_output()
        self.assertEqual("".join(t for t, _ in tab.rendered[:-1]), "a"*70000)
        self.assertEqual(tab.rendered[-1], ("[exit:0]", None))


if __name__ == "__main__":
    unittest.main()
