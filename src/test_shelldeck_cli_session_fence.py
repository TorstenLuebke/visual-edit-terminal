"""Verzoegerte --execute-Befehle sind an den urspruenglichen Terminal-Tab gebunden."""
import ast
from pathlib import Path
import shlex
import subprocess
import sys
from types import SimpleNamespace
import unittest

MAIN = Path(__file__).with_name("main.py")
TREE = ast.parse(MAIN.read_text(encoding="utf-8"))
WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
              and node.name == "TerminalWindow")


class FakeTimer:
    def __init__(self):
        self.pending = []

    def singleShot(self, delay, callback):
        self.pending.append((delay, callback))

    def run_next(self):
        delay, callback = self.pending.pop(0)
        callback()
        return delay


class FakeProcess:
    def __init__(self, state):
        self.current_state = state

    def state(self):
        return self.current_state


class FakeTab:
    def __init__(self, process):
        self.process = process
        self._shell_generation = 1
        self._terminal_cleaned_up = False
        self.commands = []

    def run_text_command(self, command):
        self.commands.append(command)


def extract(timer):
    func = next(node for node in WINDOW.body if isinstance(node, ast.FunctionDef)
                and node.name == "_schedule_launch_command")
    env = {
        "QTimer": timer,
        "QProcess": SimpleNamespace(ProcessState=SimpleNamespace(Running=2)),
        "command_targets_shelldeck": lambda _command: False,
        "subprocess": subprocess,
        "shlex": shlex,
        "sys": sys,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[func], type_ignores=[])),
                 str(MAIN), "exec"), env)
    return env[func.name]


class CliSessionFenceTests(unittest.TestCase):
    def make(self, running=True):
        timer = FakeTimer()
        messages = []
        window = SimpleNamespace(show_status=messages.append)
        proc = FakeProcess(2 if running else 0)
        tab = FakeTab(proc)
        return extract(timer), window, tab, timer, messages

    def test_running_shell_receives_start_command_once(self):
        schedule, window, tab, timer, _messages = self.make()
        schedule(window, tab, ["echo", "two words"])
        self.assertEqual(timer.run_next(), 300)
        self.assertEqual(tab.commands, ["echo 'two words'"])
        self.assertEqual(timer.pending, [])

    def test_waits_until_original_shell_is_running(self):
        schedule, window, tab, timer, _messages = self.make(running=False)
        schedule(window, tab, ["echo", "ok"])
        timer.run_next()
        self.assertEqual(tab.commands, [])
        tab.process.current_state = 2
        timer.run_next()
        self.assertEqual(tab.commands, ["echo ok"])

    def test_cancel_after_closed_tab(self):
        schedule, window, tab, timer, _messages = self.make()
        schedule(window, tab, ["echo", "should-not-run"])
        tab._terminal_cleaned_up = True
        timer.run_next()
        self.assertEqual(tab.commands, [])
        self.assertEqual(timer.pending, [])

    def test_cancel_after_shell_restart_on_same_process(self):
        schedule, window, tab, timer, _messages = self.make()
        schedule(window, tab, ["echo", "should-not-run"])
        tab._shell_generation += 1
        timer.run_next()
        self.assertEqual(tab.commands, [])

    def test_cancel_after_engine_switch(self):
        schedule, window, tab, timer, _messages = self.make()
        schedule(window, tab, ["echo", "should-not-run"])
        tab.process = FakeProcess(2)
        timer.run_next()
        self.assertEqual(tab.commands, [])

    def test_failed_shell_never_receives_command(self):
        schedule, window, tab, timer, messages = self.make(running=False)
        schedule(window, tab, ["echo", "should-not-run"])
        # Insgesamt 21 Pruefungen (initial + 20 Versuche) ohne GUI-Eventloop.
        for _ in range(21):
            self.assertTrue(timer.pending)
            timer.run_next()
        self.assertEqual(timer.pending, [])
        self.assertEqual(tab.commands, [])
        self.assertEqual(len(messages), 1)
        self.assertIn("Shell", messages[0])

    def test_two_tabs_execute_independently(self):
        schedule, window, first, timer, _messages = self.make()
        second = FakeTab(FakeProcess(2))
        schedule(window, first, ["echo", "first"])
        schedule(window, second, ["echo", "second"])
        first._terminal_cleaned_up = True
        timer.run_next()
        timer.run_next()
        self.assertEqual(first.commands, [])
        self.assertEqual(second.commands, ["echo second"])


if __name__ == "__main__":
    unittest.main()
