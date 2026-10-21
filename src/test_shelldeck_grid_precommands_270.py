"""Echte Bash-/PTY-Readline-Integration (nicht nur execute_command)."""
import ast
import os
import shutil
import signal
import time
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace

from shelldeck_prompt import create_bash_prompt_rc


@unittest.skipUnless(os.name == "posix" and shutil.which("bash"),
                     "PTY-/Bash-Regression erfordert Linux/macOS mit Bash")
class GridBashPrecommands(unittest.TestCase):
    def setUp(self):
        import pty
        self.directory, rc = create_bash_prompt_rc({"prompt": "#86EFAC", "environment": "#67E8F9"})
        self.prefix = Path(rc).with_name("grid_precommand")
        self.pid, self.master = pty.fork()
        if self.pid == 0:
            try:
                os.environ["TERM"] = "xterm-256color"
                os.execl(shutil.which("bash"), "bash", "--noprofile", "--rcfile", rc, "-i")
            except BaseException:
                os._exit(127)
        self._unread = b""
        self.wait_for_prompt()

    def tearDown(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
        except (ProcessLookupError, AttributeError):
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
        os.close(self.master)
        self.directory.cleanup()

    def wait_for(self, marker, *, timeout=5.0):
        import select
        end = time.monotonic() + timeout
        result = self._unread
        self._unread = b""
        while time.monotonic() < end:
            if marker in result:
                index = result.index(marker) + len(marker)
                self._unread = result[index:]
                return result[:index]
            ready, _, _ = select.select([self.master], [], [], max(0.0, end-time.monotonic()))
            if not ready:
                continue
            try:
                data = os.read(self.master, 16384)
            except OSError as exc:
                raise AssertionError(f"Shell/PTY beendet: {exc}; Ausgabe {result!r}") from exc
            result += data
        self.fail(f"Zeitueberschreitung bei {marker!r}; Ausgabe: {result!r}")

    def wait_for_prompt(self):
        # Der farbige Session-Prompt endet unabhaengig vom root/$-Zeichen
        # in dem vom ShellDeck-RC vorgegebenen ANSI-Reset.
        return self.wait_for(b" \x1b[0m")

    def send(self, value, *, output):
        os.write(self.master, value.encode("utf-8") + b"\r")
        # Nach dem Vorbefehl zeichnet Readline den Editierbereich erneut.
        # Dieser *Zwischen*-Prompt ist noch keine abgeschlossene Ausfuehrung.
        # Erst nach eindeutiger Befehlsausgabe auf den Schluss-Prompt warten.
        body = self.wait_for(output)
        return body + self.wait_for_prompt()

    def test_prefix_on_each_enter_change_disable_and_bash_cls(self):
        self.prefix.write_text("printf '__BEFORE__\\n'", encoding="utf-8")
        one = self.send("printf '__ONE__\\n'", output=b"__ONE__\r\n")
        two = self.send("printf '__TWO__\\n'", output=b"__TWO__\r\n")
        self.assertLess(one.index(b"__BEFORE__\r\n"), one.index(b"__ONE__\r\n"))
        self.assertLess(two.index(b"__BEFORE__\r\n"), two.index(b"__TWO__\r\n"))
        self.prefix.write_text("", encoding="utf-8")
        three = self.send("printf '__THREE__\\n'", output=b"__THREE__\r\n")
        self.assertIn(b"__THREE__", three)
        self.assertNotIn(b"__BEFORE__\r\n", three)
        aliased = self.send("declare -F cls", output=b"cls\r\n")
        self.assertIn(b"cls\r\n", aliased)
        self.prefix.write_text("clear", encoding="utf-8")
        cleared = self.send("printf '__CLEARED__\\n'", output=b"__CLEARED__\r\n")
        self.assertTrue(b"\x1b[H" in cleared or b"\x1b[2J" in cleared, cleared)

    def test_stateful_prefix_and_no_prefix_for_program_stdin(self):
        self.prefix.write_text("cd /tmp; export SHELLDECK_PRECHECK=worked", encoding="utf-8")
        result = self.send('printf "__STATE__:%s:%s\\n" "$PWD" "$SHELLDECK_PRECHECK"', output=b"__STATE__:/tmp:worked\r\n")
        self.assertIn(b"__STATE__:/tmp:worked", result)
        self.prefix.write_text("printf '__RUN__\\n'", encoding="utf-8")
        os.write(self.master, b"read -p 'ANSWER> ' answer; printf '__VALUE__:%s\\n' \"$answer\"\r")
        # Die Antwort kommt zum Shell-Builtin read, das NICHT den Bash-Readline-
        # Accept-Line-Hook ausloest. Verlaesslich pruefen wir den Gesamtauszug.
        self.wait_for(b"\rANSWER> ")
        os.write(self.master, b"secret-answer\r")
        complete = self.wait_for(b"__VALUE__:secret-answer\r\n") + self.wait_for_prompt()
        self.assertIn(b"__VALUE__:secret-answer", complete)
        self.assertNotIn(b"__RUN__\r\n__RUN__", complete)

    def test_empty_enter_does_not_run_prefix(self):
        self.prefix.write_text("printf '__EMPTY_BAD__\\n'", encoding="utf-8")
        os.write(self.master, b"\r")
        result = self.wait_for_prompt()
        self.assertNotIn(b"__EMPTY_BAD__", result)


class PromptOnlyConfigurationTests(unittest.TestCase):
    def test_no_custom_prompt_keeps_readline_hook(self):
        import subprocess
        directory, path = create_bash_prompt_rc(
            {"prompt": "#86EFAC", "environment": "#67E8F9"}, include_prompt=False)
        try:
            content = Path(path).read_text(encoding="utf-8")
            self.assertNotIn("PROMPT_COMMAND=__shelldeck_update_prompt", content)
            self.assertIn("__shelldeck_grid_before_enter", content)
            self.assertIn('cls() { command clear "$@"; }', content)
            checked = subprocess.run(["bash", "-n", path], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
        finally:
            directory.cleanup()


class WidgetInputBridgeTests(unittest.TestCase):
    """Der echte Qt-Gitterpfad muss vor dem PTY-Write synchronisieren."""

    @staticmethod
    def widget_method(name):
        source = Path(__file__).with_name("shelldeck_terminal_widget.py")
        tree = ast.parse(source.read_text(encoding="utf-8"))
        widget = next(x for x in tree.body
                      if isinstance(x, ast.ClassDef) and x.name == "ShellDeckTerminalWidget")
        method = next(x for x in widget.body
                      if isinstance(x, ast.FunctionDef) and x.name == name)
        ns = {"Path": Path}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
                     str(source), "exec"), ns)
        return ns[name]

    def test_grid_write_syncs_current_prefix_before_raw_pty_input(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "grid_precommand"
            path.write_text("")
            calls = []
            window = SimpleNamespace(active_pre_command_text=lambda: "echo PREFIX")
            class Process:
                def write(self, data):
                    calls.append((bytes(data), path.read_text()))
                    return len(data)
            tab = SimpleNamespace(
                window=window, process=Process(), shell_type="bash",
                real_terminal_active=True, _shelldeck_grid_precommand_file=str(path),
                _shelldeck_grid_precommand_last=None,
                process_uses_pty_engine=lambda: True,
            )
            tab.sync_grid_precommand_file = MethodType(self.widget_method("sync_grid_precommand_file"), tab)
            tab._write_terminal_grid_input = MethodType(self.widget_method("_write_terminal_grid_input"), tab)
            tab._write_terminal_grid_input(b"pwd\r")
            self.assertEqual(calls, [(b"pwd\r", "echo PREFIX")])
            self.assertEqual(path.read_text(), "echo PREFIX")
            tab.real_terminal_active = False
            tab._write_terminal_grid_input(b"x")
            self.assertEqual(calls[-1], (b"x", ""))
            self.assertEqual(path.read_text(), "")

    def test_no_hook_for_non_bash_or_qprocess(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "grid_precommand"
            path.write_text("old")
            tab = SimpleNamespace(
                window=SimpleNamespace(active_pre_command_text=lambda: "echo PREFIX"),
                shell_type="powershell", real_terminal_active=True,
                _shelldeck_grid_precommand_file=str(path),
                _shelldeck_grid_precommand_last=None,
                process_uses_pty_engine=lambda: True,
            )
            handler = self.widget_method("sync_grid_precommand_file")
            self.assertFalse(handler(tab))
            self.assertEqual(path.read_text(), "")
            tab.shell_type = "bash"
            tab.process_uses_pty_engine = lambda: False
            self.assertFalse(handler(tab))
            self.assertEqual(path.read_text(), "")


if __name__ == "__main__":
    unittest.main()
