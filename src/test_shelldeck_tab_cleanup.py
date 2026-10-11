"""Regressionen: geschlossene Tabs melden ihre Sitzungs-Timer endgueltig ab.

Die Tests extrahieren nur die Methoden von TerminalWindow. Dadurch koennen die
Aufraeumwege auch ohne Qt getestet werden; reale GUI-Tests bleiben Pflicht.
"""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest

MAIN = Path(__file__).with_name("main.py")
TREE = ast.parse(MAIN.read_text(encoding="utf-8"))
TERMINAL_WINDOW = next(node for node in TREE.body if isinstance(node, ast.ClassDef)
                       and node.name == "TerminalWindow")


class FakeTab:
    def __init__(self, name):
        self.name = name
        self.cleaned = False
        self.cleanup_calls = 0
        self.deleted = False

    def _cleanup_terminal_on_exit(self):
        self.cleaned = True
        self.cleanup_calls += 1

    def deleteLater(self):
        self.deleted = True


class FakeTabBar:
    def __init__(self, tabs):
        self.tabs = list(tabs)
        self.removed = []

    def count(self):
        return len(self.tabs)

    def widget(self, index):
        return self.tabs[index]

    def removeTab(self, index):
        self.removed.append(self.tabs.pop(index))


class FakeWindow:
    def __init__(self, tabs):
        self.tab_widget = FakeTabBar(tabs)
        self.active_tab_widget = self.tab_widget
        self.detached_windows = []
        self.new_tabs = 0
        self._closing_app = False

    def cleanup_empty_detached_windows(self):
        pass

    def total_terminal_tab_count(self):
        return self.tab_widget.count()

    def new_tab(self, target_tab_widget=None):
        self.new_tabs += 1

    def terminal_tab_widgets(self):
        return [self.tab_widget]

    def all_terminal_tabs(self):
        return [(None, index, tab) for index, tab in enumerate(self.tab_widget.tabs)]

    def carry_over_workspace_on_exit(self):
        pass

    def carry_over_profiles_on_exit_confirmed(self):
        pass

    def save_command_history(self):
        pass

    def save_settings(self):
        pass


def extract(name):
    node = next(node for node in TERMINAL_WINDOW.body
                if isinstance(node, ast.FunctionDef) and node.name == name)
    env = {"TerminalTab": FakeTab}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(MAIN), "exec"), env)
    return env[name]


class TabCleanupTests(unittest.TestCase):
    def test_close_tab_only_cleans_selected_tab(self):
        left, right = FakeTab("left"), FakeTab("right")
        window = FakeWindow([left, right])
        extract("close_tab")(window, 0)
        self.assertTrue(left.cleaned)
        self.assertTrue(left.deleted)
        self.assertEqual(left.cleanup_calls, 1)
        self.assertFalse(right.cleaned)
        self.assertEqual(window.tab_widget.tabs, [right])
        self.assertEqual(window.new_tabs, 0)

    def test_close_last_tab_opens_new_tab(self):
        last = FakeTab("last")
        window = FakeWindow([last])
        extract("close_tab")(window, 0)
        self.assertTrue(last.cleaned)
        self.assertEqual(window.new_tabs, 1)

    def test_workspace_load_closes_all_old_sessions(self):
        left, right = FakeTab("left"), FakeTab("right")
        window = FakeWindow([left, right])
        extract("clear_all_tabs_for_workspace_load")(window)
        self.assertEqual(window.tab_widget.count(), 0)
        self.assertTrue(left.cleaned and right.cleaned)
        self.assertTrue(left.deleted and right.deleted)
        self.assertIs(window.active_tab_widget, window.tab_widget)

    def test_app_close_cleans_each_open_session(self):
        left, right = FakeTab("left"), FakeTab("right")
        window = FakeWindow([left, right])
        accepted = []
        extract("closeEvent")(window, SimpleNamespace(accept=lambda: accepted.append(True)))
        self.assertTrue(window._closing_app)
        self.assertEqual((left.cleanup_calls, right.cleanup_calls), (1, 1))
        self.assertEqual(accepted, [True])


if __name__ == "__main__":
    unittest.main()
