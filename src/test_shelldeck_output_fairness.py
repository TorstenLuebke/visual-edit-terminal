"""GUI-aehnliche Last- und Timer-Regressionen ohne Qt-Runtime."""

import ast
from pathlib import Path
from types import MethodType, SimpleNamespace
import unittest

from shelldeck_output_buffer import TerminalOutputBuffer


SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
TREE = ast.parse(SOURCE.read_text(encoding="utf-8"))
CLASS = next(n for n in TREE.body if isinstance(n, ast.ClassDef) and n.name == "ShellDeckTerminalWidget")


def extract(names, globals):
    nodes = [n for n in CLASS.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == len(names)
    ns = dict(globals)
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(SOURCE), "exec"), ns)
    return {name: ns[name] for name in names}


class FakeTimer:
    def __init__(self):
        self.active = False
        self.starts = 0
        self.stops = 0

    def isActive(self):
        return self.active

    def start(self, *_):
        self.active = True
        self.starts += 1

    def stop(self):
        self.active = False
        self.stops += 1


class FakeCharFormat:
    def __init__(self):
        self.color = None

    def setForeground(self, color):
        self.color = color


class FakeTextCursor:
    MoveOperation = SimpleNamespace(End=1)
    inserted = []

    def __init__(self, _document):
        pass

    def movePosition(self, *_):
        pass

    def setPosition(self, *_):
        pass

    def beginEditBlock(self):
        pass

    def endEditBlock(self):
        pass

    def insertText(self, text, fmt):
        assert len(text) <= 8192
        self.inserted.append((text, fmt.color))


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def perf_counter(self):
        self.value += 0.01
        return self.value


class OutputFairnessTests(unittest.TestCase):
    def test_drain_in_small_slices_keeps_colors_and_all_bytes(self):
        env = {"QTextCursor": FakeTextCursor,
               "QTextCharFormat": FakeCharFormat,
               "TERMINAL_OUTPUT_DRAIN_TIME_BUDGET_MS": 5,
               "TERMINAL_OUTPUT_DRAIN_SLICE_CHARS": 8192,
               "TERMINAL_OUTPUT_LARGE_CHUNK_CHARS": 60000,
               "time": FakeClock()}
        method = extract(["drain_terminal_output_queue"], env)["drain_terminal_output_queue"]
        queue = TerminalOutputBuffer()
        queue.append("A" * 51000, "red")
        queue.append("B" * 51000, "blue")
        queue.append("C" * 51000, "red")
        pending = queue.pending_chars
        drain_timer = FakeTimer()
        highlight_timer = FakeTimer()
        FakeTextCursor.inserted = []
        editor = SimpleNamespace(
            document=lambda: object(), setUpdatesEnabled=lambda value: None,
            verticalScrollBar=lambda: SimpleNamespace(setValue=lambda _: None, maximum=lambda: 5),
            setTextColor=lambda _: None, moveCursor=lambda _: None, ensureCursorVisible=lambda: None)
        tab = SimpleNamespace(_output_queue=queue,
            _output_drain_timer=drain_timer, _highlighter_restore_timer=highlight_timer,
            output_area=editor, inline_output_insert_position=lambda: None,
            inline_mode_active=lambda: False,
            suspend_terminal_highlighter_for_bulk_output=lambda: None,
            terminal_stdout_color=lambda: "default",
            terminal_queue_split_index=lambda text, n: n)
        drain = MethodType(method, tab)
        rounds = 0
        while queue:
            before = queue.pending_chars
            drain()
            rounds += 1
            self.assertLessEqual(before - queue.pending_chars, 8192)
            self.assertLess(rounds, 100)
        self.assertEqual(pending, 153000)
        self.assertGreater(rounds, 10)
        self.assertEqual("".join(part for part, _ in FakeTextCursor.inserted),
                         "A" * 51000 + "B" * 51000 + "C" * 51000)
        self.assertEqual(
            "".join("R" if color == "red" else "B" for part, color in FakeTextCursor.inserted for _ in part),
            "R" * 51000 + "B" * 51000 + "R" * 51000,
        )
        self.assertFalse(drain_timer.isActive())
        self.assertEqual(queue.pending_chars, 0)
        self.assertTrue(highlight_timer.isActive())

    def test_task_output_updates_batched_but_final_state_immediate(self):
        import time
        names = ["append_command_task_output", "refresh_active_command_task_output", "finish_active_command_task"]
        funcs = extract(names, {"time": time})
        timer = FakeTimer()
        snapshots = []
        finished = []
        tab = SimpleNamespace(_task_output_refresh_timer=timer,
            active_command_task={"status": "läuft", "started_at": time.time(), "stdout": "", "stderr": ""},
            trim_command_task_text=lambda text: text[-4000:],
            update_command_task_item=lambda task: snapshots.append((task["status"],task.get("stdout"))),
            window=SimpleNamespace(register_completed_command_task=lambda tab, task: finished.append(task)))
        for name, fn in funcs.items():
            setattr(tab, name, MethodType(fn, tab))
        for i in range(1000):
            tab.append_command_task_output("stdout", str(i) + "\n")
        self.assertEqual(timer.starts, 1)
        self.assertEqual(snapshots, [])
        tab.refresh_active_command_task_output()
        self.assertEqual(len(snapshots), 1)
        tab.finish_active_command_task(status="erfolgreich", exit_code=0)
        self.assertEqual(snapshots[-1][0], "erfolgreich")
        self.assertEqual(len(finished), 1)
        self.assertIsNone(tab.active_command_task)
        self.assertEqual(timer.stops, 1)

    def test_output_timing_constants_leave_event_loop_room(self):
        constants = {target.id: node.value.value for node in TREE.body if isinstance(node, ast.Assign)
                     and isinstance(node.value, ast.Constant)
                     for target in node.targets if isinstance(target, ast.Name)}
        self.assertLessEqual(constants["TERMINAL_OUTPUT_DRAIN_SLICE_CHARS"], 8192)
        self.assertGreaterEqual(constants["TERMINAL_OUTPUT_DRAIN_INTERVAL_MS"], 1)
        self.assertLessEqual(constants["TERMINAL_OUTPUT_DRAIN_TIME_BUDGET_MS"], 8)


if __name__ == "__main__":
    unittest.main()
