"""Patch 294: Bash quick commands use the same Readline history and shell."""
import ast
import os
try:
    import pty
except ImportError:  # Windows has no pty module
    pty = None
import select
import shutil
import signal
import subprocess
import time
import unittest
from pathlib import Path

from shelldeck_prompt import create_bash_prompt_rc


@unittest.skipUnless(os.name == "posix" and pty is not None and shutil.which("bash"), "POSIX Bash PTY needed")
class ReadlineSameTabTests(unittest.TestCase):
    def setUp(self):
        self.directory, rc = create_bash_prompt_rc({})
        self.quick = Path(rc).with_name("grid_quick_command")
        self.ack = Path(rc).with_name("grid_quick_ack")
        self.prefix = Path(rc).with_name("grid_precommand")
        self.pid, self.fd = pty.fork()
        if self.pid == 0:
            os.environ.update(TERM="xterm-256color", HISTFILE="/dev/null")
            os.execl(shutil.which("bash"), "bash", "--noprofile", "--rcfile", rc, "-i")
        self.tail = b""
        self.until(b" \x1b[0m")

    def tearDown(self):
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
        os.close(self.fd)
        self.directory.cleanup()

    def until(self, expected, timeout=5.0):
        deadline = time.monotonic() + timeout
        buffer, self.tail = self.tail, b""
        while time.monotonic() < deadline:
            if expected in buffer:
                end = buffer.index(expected) + len(expected)
                self.tail = buffer[end:]
                return buffer[:end]
            ready, _, _ = select.select([self.fd], [], [], max(0, deadline - time.monotonic()))
            if ready:
                try:
                    buffer += os.read(self.fd, 65536)
                except OSError:
                    break
        self.fail(f"Missing {expected!r}: {buffer!r}")

    def wait_ack(self, expected, timeout=5.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.ack.read_text().strip() == expected:
                return
            time.sleep(.01)
        self.fail(f"Missing ack {expected!r}, got {self.ack.read_text()!r}")

    def request(self, command, token="a" * 24, with_prefix=False):
        self.ack.write_text("")
        self.quick.write_text(token + "\n" + ("1" if with_prefix else "0") + "\n" + command)
        os.write(self.fd, b"\x18\x07")
        return token

    def quick_command(self, command, expected, *, with_prefix=False):
        token = self.request(command, with_prefix=with_prefix)
        self.wait_ack("ready:" + token)
        self.assertEqual(self.quick.read_text(), "")
        os.write(self.fd, b"\x18\x1e")
        found = self.until(expected)
        self.until(b" \x1b[0m")
        return found

    def test_source_cd_and_export_persist_in_same_process(self):
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "activate"
            script.write_text('export SHELLDECK_294_VAR=active; cd "' + tmp + '"\n')
            self.quick_command(f"source {script}", b" \x1b[0m")
            self.quick_command('printf "__SAME__:%s:%s\\n" "$SHELLDECK_294_VAR" "$PWD"',
                               b"__SAME__:active:" + tmp.encode())

    def test_quick_command_is_added_to_bash_history(self):
        self.quick_command("printf __FROM_QUICK_294__", b"__FROM_QUICK_294__")
        os.write(self.fd, b"history 2\r")
        output = self.until(b"__FROM_QUICK_294__")
        self.assertIn(b"__FROM_QUICK_294__", output)

    def test_buffer_never_overwritten_or_accepted(self):
        os.write(self.fd, b"printf ORIGINAL")
        token = self.request("printf __MUST_NOT_RUN__")
        self.wait_ack("busy:" + token)
        self.assertEqual(self.quick.read_text(), "")
        os.write(self.fd, b"\r")
        self.until(b"ORIGINAL")
        self.until(b" \x1b[0m")

    def test_whitespace_only_input_is_not_replaced(self):
        os.write(self.fd, b"   ")
        token = self.request("printf __MUST_NOT_RUN__")
        self.wait_ack("busy:" + token)
        self.assertEqual(self.quick.read_text(), "")
        os.write(self.fd, b"\x15\r")  # clear the user's whitespace, then Enter
        self.until(b" \x1b[0m")

    def test_prefix_option_only_when_selected(self):
        self.prefix.write_text("export SDPREFIX_294=prefix", encoding="utf-8")
        self.quick_command('printf "no-prefix=%s" "${SDPREFIX_294:-no}"', b"no-prefix=no")
        self.quick_command('printf "yes-prefix=%s" "$SDPREFIX_294"', b"yes-prefix=prefix", with_prefix=True)

    def test_multi_line_command_executes(self):
        self.quick_command('printf "first_294\\n"\nprintf "second_294\\n"', b"second_294")


class StaticIntegrationTests(unittest.TestCase):
    def test_default_quick_command_keeps_current_tab(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        method = next(method for node in ast.walk(tree)
                      if isinstance(node, ast.ClassDef) and node.name == "TerminalWindow"
                      for method in node.body
                      if isinstance(method, ast.FunctionDef) and method.name == "run_quick_command")
        section = ast.get_source_segment(source, method)
        self.assertIn('use_new_tab = bool(item.get("new_tab"))', section)
        self.assertNotIn("use_new_tab = True", section)

    def test_menu_has_no_obsolete_warning_action(self):
        source = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
        self.assertNotIn("Sicherheitshinweis wieder anzeigen", source)
        self.assertNotIn("quick_commands_warning_action", source)

    def test_bash_rc_syntax_and_permissions(self):
        directory, rc = create_bash_prompt_rc({})
        try:
            checked = subprocess.run(["bash", "-n", rc], capture_output=True, text=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            for name in ("grid_quick_command", "grid_quick_ack"):
                self.assertEqual(Path(rc).with_name(name).stat().st_mode & 0o777, 0o600)
        finally:
            directory.cleanup()
