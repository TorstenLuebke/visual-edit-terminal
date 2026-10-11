"""Regression tests for terminal command routing and backend safety.

Loads the specified widget methods from their AST, allowing these behavioural
checks to run in minimal CI environments without PySide6. The application
itself still uses the unchanged PySide6 classes.
"""
import ast
import os
from pathlib import Path
import re
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch


_SOURCE = Path(__file__).with_name("shelldeck_terminal_widget.py")
_TREE = ast.parse(_SOURCE.read_text(encoding="utf-8"))
_CLASS = next(node for node in _TREE.body if isinstance(node, ast.ClassDef)
              and node.name == "ShellDeckTerminalWidget")


class _QProcess:
    ProcessState = SimpleNamespace(Running=1, NotRunning=0)


def _methods(*names):
    nodes = [node for node in _CLASS.body if isinstance(node, ast.FunctionDef)
             and node.name in names]
    assert {node.name for node in nodes} == set(names)
    code = compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(_SOURCE), "exec")
    namespace = {"re": re, "os": os, "sys": sys, "Path": Path, "QProcess": _QProcess,
                 "split_on_unquoted_semicolons": lambda line: [line.strip()]}
    exec(code, namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


class _Process:
    def __init__(self, engine="qprocess"):
        self._shelldeck_engine = engine
        self.written = []

    def state(self):
        return _QProcess.ProcessState.Running

    def write(self, data):
        self.written.append(data)
        return len(data)

    def waitForBytesWritten(self, _ms):
        return True


class _Input:
    def __init__(self, value):
        self.value = value

    def toPlainText(self):
        return self.value

    def clear(self):
        self.value = ""


class TerminalControlRegressionTests(unittest.TestCase):
    def test_nested_venv_bash_prompt_is_recognized(self):
        methods = _methods("shell_prompt_patterns", "output_ends_with_shell_prompt")
        tab = SimpleNamespace(**vars(methods))
        # Bind the extracted functions like normal instance methods.
        from types import MethodType
        for name in vars(methods):
            setattr(tab, name, MethodType(getattr(methods, name), tab))
        for text in (
            "((.venv) ) bash-5.3$ ",
            "PING localhost\n((.venv) ) bash-5.3$ ",
            "(.venv) bash-5.3$ ",
        ):
            self.assertTrue(tab.output_ends_with_shell_prompt(text), text)
        self.assertFalse(tab.output_ends_with_shell_prompt("PING localhost\n64 bytes ..."))

    def test_stale_response_mode_no_longer_skips_precommand(self):
        names = ("execute_command", "shell_prompt_patterns", "output_ends_with_shell_prompt",
                 "command_appears_to_be_running", "update_command_completion_state_from_output",
                 "command_sequence_from_text")
        methods = _methods(*names)
        from types import MethodType
        tab = SimpleNamespace()
        for name in names:
            setattr(tab, name, MethodType(getattr(methods, name), tab))
        tab.input_line = _Input("echo TEST")
        tab.window = SimpleNamespace(active_pre_command_text=lambda: "echo VORBEFEHL",
                                     remember_pre_command_text=lambda text: None)
        tab.process = _Process()
        tab.client_mode_active = False
        tab.password_prompt_active = False
        tab.interaction_prompt_active = True
        tab._awaiting_command_completion = True
        tab.terminal_output_text_for_state_checks = lambda: "TEST\n((.venv) ) bash-5.3$ "
        tab.reset_interaction_prompt_mode = lambda: (setattr(tab, "interaction_prompt_active", False), tab.input_line.clear())
        tab.finish_active_command_task_if_prompt_returned = lambda: None
        tab.visible_output_waits_for_password = lambda: False
        tab.visible_output_waits_for_interaction = lambda: False
        tab.command_history = []
        tab.add_command_history = lambda cmd: tab.command_history.append(cmd)
        tab.update_restore_command_from_command = lambda cmd: None
        tab.translate_cross_platform_command = lambda cmd: cmd
        tab.parse_ollama_run_model = lambda cmd: None
        tab.parse_direct_client_command = lambda cmd: None
        tab.start_command_task = lambda *args: None
        tab.extract_interactive_prompt_from_command = lambda cmd: ""
        tab.detect_client_mode_name = lambda cmd: ""
        tab.written = []
        tab.write_shell_command = tab.written.append
        tab.execute_command()
        self.assertEqual(tab.written, ["echo VORBEFEHL", "echo TEST"])
        self.assertEqual(tab.command_history, ["echo TEST"])

    def test_pty_control_character_uses_terminal_bytes(self):
        methods = _methods("send_control_character")
        proc = _Process("pty")
        tab = SimpleNamespace(process=proc, process_uses_pty_engine=lambda: True,
                              window=SimpleNamespace(show_status=lambda msg: None))
        self.assertTrue(methods.send_control_character(tab, b"\x03"))
        self.assertEqual(proc.written, [b"\x03"])

    def test_qprocess_sigint_targets_only_shell_descendants(self):
        methods = _methods("send_control_character")
        proc = _Process()
        messages, signaled = [], []
        tab = SimpleNamespace(process=proc, process_uses_pty_engine=lambda: False,
                              qprocess_linux_descendant_pids=lambda: [123456, 123457],
                              window=SimpleNamespace(show_status=messages.append))
        with patch("os.kill", side_effect=lambda pid, sig: signaled.append(pid)):
            self.assertTrue(methods.send_control_character(tab, b"\x03"))
        self.assertEqual(signaled, [123457, 123456])
        self.assertFalse(proc.written)
        self.assertTrue(messages)

    def test_qprocess_child_lookup_does_not_include_shell_pid(self):
        methods = _methods("qprocess_linux_descendant_pids")
        proc = _Process()
        proc.processId = lambda: 400
        tab = SimpleNamespace(process=proc)
        tree = {400: "401 402", 401: "403", 402: "", 403: ""}

        def read_children(path):
            pid = int(str(path).split("/")[2])
            return tree[pid]

        with patch.object(Path, "read_text", read_children):
            children = methods.qprocess_linux_descendant_pids(tab)
        self.assertEqual(children, [401, 402, 403])
        self.assertNotIn(400, children)

    def test_replaced_process_signals_are_disconnected(self):
        methods = _methods("disconnect_shell_process")

        class FakeSignal:
            def __init__(self):
                self.slots = []

            def disconnect(self, slot):
                self.slots.append(slot)

        names = ("readyReadStandardOutput", "readyReadStandardError", "finished", "errorOccurred")
        process = SimpleNamespace(**{name: FakeSignal() for name in names})
        tab = SimpleNamespace(handle_stdout=lambda: None, handle_stderr=lambda: None,
                              handle_finished=lambda *a: None, handle_process_error=lambda *a: None)
        methods.disconnect_shell_process(tab, process)
        for name in names:
            self.assertEqual(len(getattr(process, name).slots), 1)

    def test_qprocess_other_control_bytes_not_pretended_as_signals(self):
        methods = _methods("send_control_character")
        proc = _Process()
        messages = []
        tab = SimpleNamespace(process=proc, process_uses_pty_engine=lambda: False,
                              window=SimpleNamespace(show_status=messages.append))
        self.assertFalse(methods.send_control_character(tab, b"\x1a"))
        self.assertFalse(proc.written)
        self.assertIn("PTY", messages[-1])

    def test_engine_switch_refuses_to_close_active_command(self):
        methods = _methods("set_terminal_engine")
        proc = _Process("pty")
        messages = []
        tab = SimpleNamespace(process=proc, terminal_engine="pty", client_mode_active=False,
                              password_prompt_active=False, interaction_prompt_active=False,
                              window=SimpleNamespace(normalize_terminal_engine=lambda value: value,
                                                     show_status=messages.append),
                              actual_terminal_engine=lambda: "pty",
                              command_appears_to_be_running=lambda: True,
                              stop_process=lambda **kw: self.fail("Busy process must not be stopped"))
        self.assertFalse(methods.set_terminal_engine(tab, "qprocess"))
        self.assertEqual(tab.terminal_engine, "pty")
        self.assertIn("abgelehnt", messages[-1])


if __name__ == "__main__":
    unittest.main()
