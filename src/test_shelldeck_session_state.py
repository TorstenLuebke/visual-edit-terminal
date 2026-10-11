"""Regressionstests für Shell-Lebenszyklus ohne PySide6-Abhängigkeit."""
import unittest
from shelldeck_session_state import SessionPhase, evaluate_session_state


def snapshot(state, **kwargs):
    return evaluate_session_state(process_state=state, running_state=2,
                                  starting_state=1, engine="pty", generation=3, **kwargs)


class SessionSnapshotTests(unittest.TestCase):
    def test_not_running_clears_stale_flags_without_side_effects(self):
        value = snapshot(0, command_pending=True, interactive=True)
        self.assertEqual(value.phase, SessionPhase.STOPPED)
        self.assertFalse(value.busy)
        self.assertFalse(value.command_pending)
        self.assertFalse(value.interactive)

    def test_starting_is_not_ready(self):
        self.assertEqual(snapshot(1).phase, SessionPhase.STARTING)

    def test_idle_shell_is_ready(self):
        value = snapshot(2)
        self.assertEqual(value.phase, SessionPhase.READY)
        self.assertTrue(value.shell_running)
        self.assertFalse(value.busy)

    def test_running_command_is_busy_but_shell_is_alive(self):
        value = snapshot(2, command_pending=True)
        self.assertEqual(value.phase, SessionPhase.RUNNING)
        self.assertTrue(value.busy)
        self.assertTrue(value.shell_running)

    def test_interactive_takes_priority_over_running(self):
        value = snapshot(2, command_pending=True, interactive=True)
        self.assertEqual(value.phase, SessionPhase.INTERACTIVE)
        self.assertTrue(value.busy)

    def test_closed_tab_cannot_be_busy(self):
        self.assertEqual(snapshot(2, command_pending=True, closed=True).phase, SessionPhase.STOPPED)

    def test_snapshots_are_immutable(self):
        from dataclasses import FrozenInstanceError
        value = snapshot(2)
        with self.assertRaises(FrozenInstanceError):
            value.engine = "qprocess"

    def test_tabs_are_isolated(self):
        busy = snapshot(2, command_pending=True)
        idle = snapshot(2)
        self.assertTrue(busy.busy)
        self.assertFalse(idle.busy)
        self.assertEqual((busy.engine, busy.generation), ("pty", 3))

    def test_engine_is_preserved_for_cross_platform_backend(self):
        value = evaluate_session_state(process_state="running", running_state="running",
                                       starting_state="starting", engine="qprocess", generation=17)
        self.assertEqual(value.phase, SessionPhase.READY)
        self.assertEqual(value.engine, "qprocess")
        self.assertEqual(value.generation, 17)


class WidgetSessionBridgeTests(unittest.TestCase):
    """Prüft die GUI-Anbindung über AST, ohne Qt im Testprozess zu laden."""
    def get_state(self, *, state=2, pending=False, interactive=False,
                  prompt="busy output", closed=False, engine="pty"):
        import ast
        from pathlib import Path
        from types import SimpleNamespace
        source = Path(__file__).with_name("shelldeck_terminal_widget.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "ShellDeckTerminalWidget")
        node = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                    and n.name == "get_session_state")
        fake_qprocess = SimpleNamespace(ProcessState=SimpleNamespace(NotRunning=0, Starting=1, Running=2))
        ns = {"evaluate_session_state": evaluate_session_state, "QProcess": fake_qprocess}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(source), "exec"), ns)
        tab = SimpleNamespace(process=SimpleNamespace(state=lambda: state),
                              _shell_generation=4, _terminal_cleaned_up=closed,
                              _awaiting_command_completion=pending,
                              client_mode_active=False, password_prompt_active=False,
                              interaction_prompt_active=interactive,
                              terminal_output_text_for_state_checks=lambda: prompt,
                              output_ends_with_shell_prompt=lambda value: value.endswith("$ "),
                              actual_terminal_engine=lambda: engine)
        return ns["get_session_state"](tab), tab

    def test_widget_reports_active_command(self):
        value, tab = self.get_state(pending=True)
        self.assertEqual(value.phase, SessionPhase.RUNNING)
        self.assertTrue(tab._awaiting_command_completion)

    def test_queued_prompt_is_ready_without_mutating_flags(self):
        value, tab = self.get_state(pending=True, interactive=True, prompt="done\nbash-5.3$ ")
        self.assertEqual(value.phase, SessionPhase.READY)
        self.assertTrue(tab._awaiting_command_completion)
        self.assertTrue(tab.interaction_prompt_active)

    def test_interactive_mode_has_own_phase(self):
        value, tab = self.get_state(pending=True, interactive=True)
        self.assertEqual(value.phase, SessionPhase.INTERACTIVE)

    def test_widget_stopped_overrides_stale_command(self):
        value, tab = self.get_state(state=0, pending=True, interactive=True)
        self.assertEqual(value.phase, SessionPhase.STOPPED)
        self.assertFalse(value.busy)


if __name__ == "__main__":
    unittest.main()
