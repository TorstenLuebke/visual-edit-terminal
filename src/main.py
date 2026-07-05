
import sys
import re
import json
import os
import traceback
import faulthandler
import shutil
import subprocess
import shlex
import socket
import getpass
import urllib.error
import urllib.request
from pathlib import Path
from shelldeck_profiles import normalize_profile, normalize_profiles, profile_display_label, profile_from_tab
from shelldeck_workspaces import normalize_workspace, normalize_workspaces, workspace_display_label, workspace_from_tabs
from shelldeck_ollama import build_generate_payload, extract_generate_response, list_ollama_models, ollama_api_error_message, markdown_chat_export, normalize_system_prompt
from shelldeck_file_context import append_file_context_to_prompt, build_file_context_block, read_text_file_context
from shelldeck_markdown import extract_code_blocks, ollama_answer_to_html
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget,
    QPlainTextEdit, QFontDialog, QColorDialog, QInputDialog, QPushButton,
    QDialog, QFormLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox, QSlider,
    QDialogButtonBox, QCheckBox, QTabWidget, QMenu, QFileDialog,
    QLineEdit, QListWidget, QListWidgetItem, QSplitter
)
from PySide6.QtCore import Qt, QProcess, QEvent, QThread, Signal, QTimer, QByteArray
from PySide6.QtGui import (
    QTextCursor, QTextDocument, QFont, QTextCharFormat, QColor, QSyntaxHighlighter,
    QAction, QShortcut, QPalette
)


LOG_FILE = Path.home() / "TerminalApp.log"
_LOG_HANDLE = None
APP_NAME = "ShellDeck Terminal"
APP_VERSION = "2.16.0"


def install_crash_logging():
    global _LOG_HANDLE
    try:
        _LOG_HANDLE = LOG_FILE.open("a", encoding="utf-8")
        faulthandler.enable(file=_LOG_HANDLE, all_threads=True)
    except OSError:
        _LOG_HANDLE = None

    def handle_exception(exc_type, exc_value, exc_tb):
        try:
            with LOG_FILE.open("a", encoding="utf-8") as log:
                log.write("\nUnbehandelte Python-Ausnahme:\n")
                log.write("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = handle_exception


class TerminalHighlighter(QSyntaxHighlighter):
    def __init__(self, parent=None, colors=None):
        super().__init__(parent)
        self.colors = dict(colors or {})
        self.rebuild_rules()

    def color_value(self, key, fallback):
        value = str(self.colors.get(key, fallback) or fallback).strip()
        return value.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else fallback

    def rebuild_rules(self):
        self.highlighting_rules = []

        error_format = QTextCharFormat()
        error_format.setForeground(QColor(self.color_value("error_word", "#FCA5A5")))
        self.highlighting_rules.append((re.compile(r"error", re.IGNORECASE), error_format))

        command_format = QTextCharFormat()
        command_format.setForeground(QColor(self.color_value("command", "#7DD3FC")))
        self.highlighting_rules.append((re.compile(r"\b(cd|ls|pwd|mkdir|rm|cp|mv|grep|find|cat|echo|exit|git|python|pip|ollama)\b"), command_format))

        path_format = QTextCharFormat()
        path_format.setForeground(QColor(self.color_value("path", "#86EFAC")))
        self.highlighting_rules.append((re.compile(r"[\w\-\_/\.]+[/\\]"), path_format))

        number_format = QTextCharFormat()
        number_format.setForeground(QColor(self.color_value("number", "#C084FC")))
        self.highlighting_rules.append((re.compile(r"\b\d+\b"), number_format))

    def set_terminal_colors(self, colors):
        self.colors = dict(colors or {})
        self.rebuild_rules()
        self.rehighlight()

    def highlightBlock(self, text):
        for pattern, fmt in self.highlighting_rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, fmt)


class OllamaApiWorker(QThread):
    response_ready = Signal(str, object)
    error_ready = Signal(str)

    def __init__(self, model, prompt, context=None, system_prompt="", parent=None):
        super().__init__(parent)
        self.model = str(model or "").strip()
        self.prompt = str(prompt or "")
        self.context = context if isinstance(context, list) else []
        self.system_prompt = normalize_system_prompt(system_prompt)

    def run(self):
        payload = build_generate_payload(
            self.model,
            self.prompt,
            context=self.context,
            system_prompt=self.system_prompt,
        )
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                raw = response.read().decode("utf-8", errors="replace")
            if self.isInterruptionRequested():
                return
            answer, context = extract_generate_response(raw)
            if not self.isInterruptionRequested():
                self.response_ready.emit(answer, context)

        except Exception as exc:
            self.error_ready.emit(ollama_api_error_message(exc))


class PtyReaderThread(QThread):
    output_ready = Signal(bytes)
    finished_ready = Signal(int, object)
    error_ready = Signal(str)

    def __init__(self, pty_process, parent=None):
        super().__init__(parent)
        self.pty_process = pty_process

    def run(self):
        exit_code = 0
        try:
            while not self.isInterruptionRequested():
                proc = self.pty_process
                if proc is None:
                    break
                try:
                    is_alive = bool(proc.isalive()) if hasattr(proc, "isalive") else False
                except Exception:
                    is_alive = False
                if not is_alive:
                    break

                try:
                    chunk = proc.read(4096)
                except EOFError:
                    break
                except Exception as exc:
                    if not self.isInterruptionRequested():
                        self.error_ready.emit(str(exc))
                    exit_code = 1
                    break

                if chunk is None:
                    self.msleep(20)
                    continue
                data = chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8", errors="replace")
                if data:
                    self.output_ready.emit(data)
                else:
                    self.msleep(20)
        finally:
            self.finished_ready.emit(exit_code, QProcess.ExitStatus.NormalExit)


class PosixPtyChild:
    """Kleiner POSIX-PTY-Adapter für Linux/macOS.

    Er stellt die wenigen Methoden bereit, die PtyReaderThread und
    PtyTerminalProcess bereits vom Windows-pywinpty-Objekt erwarten. Dadurch
    kann ShellDeck unter Linux eine echte Terminal-Sitzung mit Job-Control,
    TTY-Erkennung und interaktiven Programmen nutzen.
    """

    def __init__(self, pid, fd):
        self.pid = int(pid)
        self.fd = int(fd)
        self.exitstatus = None
        try:
            os.set_blocking(self.fd, False)
        except Exception:
            pass

    @classmethod
    def spawn(cls, command_line, cwd=None):
        import pty

        pid, fd = pty.fork()
        if pid == 0:
            try:
                if cwd:
                    os.chdir(cwd)
                os.environ.setdefault("TERM", "xterm-256color")
                args = shlex.split(str(command_line or ""), posix=True)
                if not args:
                    os._exit(127)
                os.execvp(args[0], args)
            except BaseException:
                os._exit(127)
        return cls(pid, fd)

    def isalive(self):
        if self.exitstatus is not None:
            return False
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
        except ChildProcessError:
            self.exitstatus = 0
            return False
        except OSError:
            self.exitstatus = 1
            return False
        if pid == 0:
            return True
        if os.WIFEXITED(status):
            self.exitstatus = os.WEXITSTATUS(status)
        elif os.WIFSIGNALED(status):
            self.exitstatus = 128 + os.WTERMSIG(status)
        else:
            self.exitstatus = 0
        return False

    def read(self, size=4096):
        import select

        if not self.isalive():
            raise EOFError()
        ready, _, _ = select.select([self.fd], [], [], 0.05)
        if not ready:
            return b""
        try:
            return os.read(self.fd, int(size))
        except BlockingIOError:
            return b""
        except OSError:
            raise EOFError()

    def write(self, text):
        if not self.isalive():
            raise OSError("PTY-Prozess läuft nicht.")
        raw = str(text or "").encode("utf-8", errors="replace")
        return os.write(self.fd, raw)

    def terminate(self):
        import signal

        if not self.isalive():
            return
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGTERM)
        except Exception:
            try:
                os.kill(self.pid, signal.SIGTERM)
            except Exception:
                pass

    def kill(self):
        import signal

        if not self.isalive():
            return
        try:
            os.killpg(os.getpgid(self.pid), signal.SIGKILL)
        except Exception:
            try:
                os.kill(self.pid, signal.SIGKILL)
            except Exception:
                pass

    def close(self):
        try:
            os.close(self.fd)
        except Exception:
            pass



class PtyTerminalProcess(QThread):
    """Optionaler PTY/ConPTY-Adapter mit QProcess-ähnlicher Oberfläche.

    Der vorhandene QProcess-Pfad bleibt Standard. Dieser Adapter wird nur
    benutzt, wenn die experimentelle Terminal-Engine gewählt wurde. Unter
    Windows nutzt er pywinpty, unter Linux/macOS ein echtes POSIX-PTY.
    """

    readyReadStandardOutput = Signal()
    readyReadStandardError = Signal()
    finished = Signal(int, object)
    errorOccurred = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pty = None
        self._reader = None
        self._stdout_buffer = bytearray()
        self._stderr_buffer = bytearray()
        self._working_directory = ""
        self._error_string = ""
        self._running = False
        self._shelldeck_engine = "pty"

    @staticmethod
    def availability_message():
        if sys.platform == "win32":
            try:
                import winpty  # noqa: F401
                return ""
            except Exception as exc:
                return (
                    "pywinpty ist nicht installiert. Installiere es im App-Interpreter mit: "
                    "python -m pip install pywinpty. Details: " + str(exc)
                )
        if os.name == "posix":
            if Path("/dev/ptmx").exists() or Path("/dev/pts").exists():
                return ""
            return "Kein POSIX-PTY-Gerät gefunden (/dev/ptmx oder /dev/pts fehlt)."
        return "PTY ist auf diesem Betriebssystem noch nicht unterstützt."

    @classmethod
    def is_available(cls):
        return not cls.availability_message()

    def setWorkingDirectory(self, directory):
        text = str(directory or "").strip()
        if text and Path(text).exists():
            self._working_directory = text

    def workingDirectory(self):
        return self._working_directory

    def _command_line(self, program, args):
        values = [str(program or "").strip(), *[str(arg) for arg in (args or [])]]
        values = [value for value in values if value]
        if not values:
            return ""
        if sys.platform == "win32":
            return subprocess.list2cmdline(values)
        try:
            return shlex.join(values)
        except AttributeError:
            return " ".join(shlex.quote(value) for value in values)

    def start(self, program, args=None):
        message = self.availability_message()
        if message:
            self._error_string = message
            self._running = False
            QTimer.singleShot(0, lambda: self.errorOccurred.emit(QProcess.ProcessError.FailedToStart))
            return

        command_line = self._command_line(program, args or [])
        if not command_line:
            self._error_string = "Kein Startbefehl für PTY/ConPTY angegeben."
            self._running = False
            QTimer.singleShot(0, lambda: self.errorOccurred.emit(QProcess.ProcessError.FailedToStart))
            return

        try:
            cwd = self._working_directory or None
            if sys.platform == "win32":
                from winpty import PtyProcess
                try:
                    self._pty = PtyProcess.spawn(command_line, cwd=cwd)
                except TypeError:
                    old_cwd = os.getcwd()
                    try:
                        if cwd:
                            os.chdir(cwd)
                        self._pty = PtyProcess.spawn(command_line)
                    finally:
                        os.chdir(old_cwd)
            else:
                self._pty = PosixPtyChild.spawn(command_line, cwd=cwd)
            self._running = True
            self._error_string = ""
            self._reader = PtyReaderThread(self._pty, self)
            self._reader.output_ready.connect(self._append_stdout)
            self._reader.error_ready.connect(self._handle_reader_error)
            self._reader.finished_ready.connect(self._handle_reader_finished)
            self._reader.start()
        except Exception as exc:
            self._error_string = str(exc)
            self._running = False
            QTimer.singleShot(0, lambda: self.errorOccurred.emit(QProcess.ProcessError.FailedToStart))

    def _append_stdout(self, data):
        self._stdout_buffer.extend(bytes(data or b""))
        self.readyReadStandardOutput.emit()

    def _handle_reader_error(self, message):
        self._error_string = str(message or "Unbekannter PTY/ConPTY-Fehler")
        self._stderr_buffer.extend(("\n[PTY/ConPTY-Fehler] " + self._error_string + "\n").encode("utf-8", errors="replace"))
        self.readyReadStandardError.emit()
        self.errorOccurred.emit(QProcess.ProcessError.UnknownError)

    def _handle_reader_finished(self, exit_code, exit_status):
        self._running = False
        self.finished.emit(int(exit_code), exit_status)

    def readAllStandardOutput(self):
        data = bytes(self._stdout_buffer)
        self._stdout_buffer.clear()
        return data

    def readAllStandardError(self):
        data = bytes(self._stderr_buffer)
        self._stderr_buffer.clear()
        return data

    def state(self):
        return QProcess.ProcessState.Running if self._running else QProcess.ProcessState.NotRunning

    def waitForStarted(self, msecs=30000):
        return self._running

    def write(self, data):
        if not self._running or self._pty is None:
            self._error_string = "PTY/ConPTY-Prozess läuft nicht."
            return -1
        raw = bytes(data or b"")
        for encoding in ("utf-8", "cp1252", "cp850", "latin-1"):
            try:
                text = raw.decode(encoding)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        text = text.replace("\r\n", "\n").replace("\n", "\r")
        try:
            self._pty.write(text)
            return len(raw)
        except Exception as exc:
            self._error_string = str(exc)
            self.errorOccurred.emit(QProcess.ProcessError.WriteError)
            return -1

    def write_bracketed_paste(self, text):
        """Write a command as bracketed paste to reduce PSReadLine redraw noise.

        PowerShell/PSReadLine repaints long input lines character by character
        in a PTY. QTextEdit is not a terminal emulator, so those redraws can
        become visible. Bracketed paste lets PSReadLine receive the whole
        command as one paste operation and then execute it with Enter.
        """
        if not self._running or self._pty is None:
            self._error_string = "PTY/ConPTY-Prozess läuft nicht."
            return -1
        value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        value = value.rstrip("\n")
        if not value:
            return 0
        payload = "\x1b[200~" + value + "\x1b[201~\r"
        try:
            self._pty.write(payload)
            return len(value.encode("utf-8", errors="replace"))
        except Exception as exc:
            self._error_string = str(exc)
            self.errorOccurred.emit(QProcess.ProcessError.WriteError)
            return -1

    def waitForBytesWritten(self, msecs=30000):
        return self._running

    def terminate(self):
        if not self._pty:
            return
        try:
            self._pty.write("exit\r")
        except Exception:
            self.kill()

    def kill(self):
        if self._reader is not None and self._reader.isRunning():
            self._reader.requestInterruption()
        if self._pty is not None:
            for name in ("terminate", "kill", "close"):
                method = getattr(self._pty, name, None)
                if callable(method):
                    try:
                        method()
                        break
                    except Exception:
                        continue
        self._running = False

    def waitForFinished(self, msecs=30000):
        if self._reader is None:
            return True
        return self._reader.wait(max(0, int(msecs)))

    def errorString(self):
        return self._error_string


class TerminalTab(QWidget):
    def __init__(self, window, title="Terminal", shell_type=None, custom_title=None, start_directory=None, command_history=None, restore_command="", venv_path="", terminal_engine=None):
        super().__init__(window)
        self.window = window
        normalize_shell = getattr(window, "normalize_shell_type", None)
        requested_shell = shell_type or window.shell_type
        self.shell_type = normalize_shell(requested_shell) if callable(normalize_shell) else requested_shell
        self.terminal_engine = self.window.normalize_terminal_engine(terminal_engine or getattr(window, "terminal_engine", "qprocess"))
        self.custom_title = custom_title or ""
        self.start_directory = self.normalize_start_directory(start_directory)
        self.current_working_directory = self.start_directory or str(Path.cwd())
        self.title = title
        self.history_index = -1
        self.current_command = ""
        self.command_history = self.normalize_command_history(command_history)
        self.restore_command = str(restore_command or "").strip()
        self.venv_path = self.normalize_venv_path(venv_path)
        self.client_mode_active = False
        self.client_mode_name = ""
        self.client_mode_kind = ""
        self.ollama_model = ""
        self.ollama_context = []
        self.ollama_system_prompt = ""
        self.ollama_worker = None
        self.client_process = None
        self.direct_client_exit_command = "exit"
        self.direct_client_label = "Client"
        self.direct_client_start_error_reported = False
        self.output_search_text = ""
        self.last_ollama_code_blocks = []
        self._pending_pty_command_echoes = []
        self._pending_interactive_response_echoes = []
        self.password_prompt_active = False
        self._password_dialog_open = False
        self._password_prompt_tail = ""
        self.interaction_prompt_active = False
        self._interaction_prompt_tail = ""
        self._interaction_prompt_text = ""
        self._awaiting_command_completion = False
        self._last_sent_shell_command = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setFont(self.window.terminal_font)
        self.output_area.setTextInteractionFlags(
            self.output_area.textInteractionFlags() | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.output_area.viewport().installEventFilter(self)
        self.output_area.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.output_area.customContextMenuRequested.connect(self.show_terminal_context_menu)
        layout.addWidget(self.output_area)

        self.highlighter = TerminalHighlighter(self.output_area.document(), self.window.terminal_colors())

        self.input_prompt_label = QLineEdit()
        self.input_prompt_label.setReadOnly(True)
        self.input_prompt_label.setFont(self.window.terminal_font)
        self.input_prompt_label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.input_prompt_label.setCursorPosition(0)
        layout.addWidget(self.input_prompt_label)

        self.input_line = QPlainTextEdit()
        self.input_line.setMaximumHeight(110)
        self.input_line.setFont(self.window.terminal_font)
        self.input_line.installEventFilter(self)
        self.input_line.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.input_line.customContextMenuRequested.connect(self.show_terminal_context_menu)
        layout.addWidget(self.input_line)
        self.update_input_prompt_label()

        self.execute_button = QPushButton("Befehl ausführen")
        self.execute_button.clicked.connect(self.execute_command)
        layout.addWidget(self.execute_button)

        self.process = self.create_shell_process()
        self.connect_shell_process(self.process)

        self.apply_theme()
        self.start_shell()

        if self.window.default_command and self.process.waitForStarted(2000):
            self.run_startup_command(self.window.default_command)

    def compact_display_path(self, path_text):
        text = str(path_text or "").strip()
        if not text:
            return ""
        try:
            path = Path(text).expanduser()
            home = Path.home().resolve()
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            try:
                rel = resolved.relative_to(home)
                return "~" if not str(rel) else "~/" + str(rel)
            except ValueError:
                return str(resolved)
        except OSError:
            return text

    def terminal_user_host_label(self):
        try:
            user = getpass.getuser()
        except Exception:
            user = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
        try:
            host = socket.gethostname().split(".", 1)[0]
        except Exception:
            host = os.environ.get("HOSTNAME") or "host"
        return f"{user}@{host}"

    def active_venv_label(self):
        venv_text = str(getattr(self, "venv_path", "") or "").strip()
        if venv_text:
            try:
                return Path(venv_text).name or "venv"
            except OSError:
                return "venv"
        restore = str(getattr(self, "restore_command", "") or "")
        if re.search(r"(?:^|[\\/\s])\.venv(?:[\\/\s]|$)", restore):
            return ".venv"
        if re.search(r"(?:^|[\\/\s])venv(?:[\\/\s]|$)", restore):
            return "venv"
        output = ""
        area = getattr(self, "output_area", None)
        if area is not None:
            try:
                output = area.toPlainText()
            except Exception:
                output = ""
        match = re.search(r"\(([^()\s]+venv[^()\s]*)\)", output, re.IGNORECASE)
        return match.group(1) if match else ""

    def input_prompt_text(self):
        directory = str(getattr(self, "current_working_directory", "") or "").strip()
        path_label = self.compact_display_path(directory) if directory else "ShellDeck"
        prefix = ""
        venv_name = self.active_venv_label()
        if venv_name:
            prefix = f"({venv_name}) "
        return f"{prefix}{self.terminal_user_host_label()}: {path_label} $"

    def update_input_prompt_label(self):
        prompt = getattr(self, "input_prompt_label", None)
        if prompt is not None:
            full_path = str(getattr(self, "current_working_directory", "") or "")
            if getattr(self, "password_prompt_active", False):
                prompt_text = "Passwort erwartet"
                tooltip = "Die nächste Eingabe wird als Passwort roh an den laufenden Prozess gesendet."
            elif getattr(self, "interaction_prompt_active", False):
                question = str(getattr(self, "_interaction_prompt_text", "") or "").strip()
                if question:
                    prompt_text = f"Antwort/Eingabe erwartet: {question}"
                    tooltip = question
                else:
                    prompt_text = "Antwort/Eingabe an laufenden Prozess"
                    tooltip = "Die nächste Eingabe wird roh an den laufenden Prozess gesendet."
            elif self.command_appears_to_be_running():
                prompt_text = "Laufender Prozess aktiv – Eingabe wird an den Prozess gesendet"
                tooltip = "Solange kein normaler Shell-Prompt zurück ist, kann die nächste Eingabe als Antwort/Interaktion gesendet werden."
            else:
                prompt_text = self.input_prompt_text()
                tooltip = full_path
            prompt.setText(prompt_text)
            prompt.setToolTip(tooltip)
            try:
                prompt.setCursorPosition(0)
            except Exception:
                pass

    def shell_command_words(self, command):
        text = str(command or "").strip()
        if not text:
            return []
        try:
            return shlex.split(text, posix=(sys.platform != "win32"))
        except ValueError:
            return text.split()

    def translate_cross_platform_command(self, command):
        """Translate common commands between Windows and POSIX shells.

        ShellDeck keeps the user's intent portable: commands like ``cls`` should
        clear the screen on Linux too, while ``clear`` should work in CMD. This
        is intentionally conservative and only maps small, unambiguous shell
        conveniences.
        """
        text = str(command or "").strip()
        if not text or "\n" in text or "\r" in text:
            return text
        words = self.shell_command_words(text)
        if not words:
            return text
        first = str(words[0] or "").lower()
        lower_shell = str(self.shell_type or "").lower()
        if sys.platform != "win32" and lower_shell in {"bash", "zsh", "fish", "sh"}:
            if first == "cls":
                return "clear"
            if first == "dir":
                rest = words[1:]
                if rest:
                    return "ls -la " + " ".join(shlex.quote(str(item)) for item in rest)
                return "ls -la"
        if sys.platform == "win32" and lower_shell == "cmd" and first == "clear":
            return "cls"
        return text

    def run_startup_command(self, command_text):
        for command in self.command_sequence_from_text(command_text, include_prefix=False):
            translated = self.translate_cross_platform_command(command)
            if translated.lower() in {"cls", "clear"}:
                self.output_area.clear()
                self.update_input_prompt_label()
                continue
            if self.process.state() == QProcess.ProcessState.Running:
                self.update_working_context_from_shell_command(translated)
                self.write_shell_command(translated)

    def update_working_directory_from_cd_command(self, command):
        text = str(command or "").strip()
        if not text:
            return False
        try:
            parts = shlex.split(text, posix=(sys.platform != "win32"))
        except ValueError:
            parts = text.split()
        if not parts or str(parts[0]).lower() not in {"cd", "chdir"}:
            return False
        if len(parts) == 1:
            target = str(Path.home())
        else:
            target = str(parts[1]).strip()
        if not target:
            target = str(Path.home())
        try:
            if target == "-":
                return False
            candidate = Path(target).expanduser()
            if not candidate.is_absolute():
                candidate = Path(self.current_working_directory or Path.cwd()) / candidate
            candidate = candidate.resolve()
            if candidate.exists() and candidate.is_dir():
                self.current_working_directory = str(candidate)
                self.update_input_prompt_label()
                return True
        except OSError:
            return False
        return False

    def update_venv_path_from_activation_command(self, command):
        text = str(command or "").strip()
        if not self.command_looks_like_venv_activation(text):
            return False
        try:
            parts = shlex.split(text, posix=(sys.platform != "win32"))
        except ValueError:
            parts = text.split()
        if not parts:
            return False

        script_text = ""
        if str(parts[0]).lower() in {"source", "."} and len(parts) >= 2:
            script_text = str(parts[1])
        elif "activate" in str(parts[0]).lower():
            script_text = str(parts[0])
        if not script_text:
            return False

        try:
            script_path = Path(script_text).expanduser()
            if not script_path.is_absolute():
                script_path = Path(self.current_working_directory or Path.cwd()) / script_path
            script_path = script_path.resolve()
            if script_path.name.startswith("activate"):
                venv_dir = script_path.parent.parent
                if venv_dir.exists() and venv_dir.is_dir():
                    self.venv_path = str(venv_dir)
                    project_dir = venv_dir.parent
                    if project_dir.exists() and project_dir.is_dir():
                        self.current_working_directory = str(project_dir)
                    self.update_input_prompt_label()
                    return True
        except OSError:
            return False
        return False

    def split_shell_commands_for_context(self, command):
        text = str(command or "").replace("\r\n", "\n").replace("\r", "\n")
        result = []
        for line in text.split("\n"):
            for part in line.split(";"):
                clean = part.strip()
                if clean:
                    result.append(clean)
        return result

    def update_working_context_from_shell_command(self, command):
        changed = False
        for part in self.split_shell_commands_for_context(command):
            if self.update_working_directory_from_cd_command(part):
                changed = True
                continue
            if self.update_venv_path_from_activation_command(part):
                changed = True
        if changed:
            self.update_input_prompt_label()
        return changed

    def shell_supports_context_probe(self):
        if sys.platform == "win32":
            return False
        return str(self.shell_type or "").lower() in {"bash", "zsh", "sh", "fish"}

    def shell_context_probe_command(self):
        # Die Ausgabe wird in consume_shell_context_markers() sofort wieder
        # aus dem Terminaltext entfernt. Sie dient nur dazu, den echten
        # Arbeitsordner nach cd/pushd/popd exakt von der laufenden Shell zu lesen.
        return "printf '__SHELLDECK_CONTEXT__%s\\t%s\\n' \"$PWD\" \"$VIRTUAL_ENV\""

    def shell_command_needs_context_probe(self, command_text):
        """Return True only for commands where a post-command cwd probe is useful.

        A probe is an extra line sent to the live shell. For commands that ask
        questions (rm -i, apt, git clean, overwrite prompts, etc.) that extra
        line can accidentally become the answer to the prompt. Therefore
        ShellDeck only appends the probe for shell-state commands where it is
        needed to keep the displayed working directory/venv in sync.
        """
        text = str(command_text or "").replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip():
            return False
        for part in self.split_shell_commands_for_context(text):
            lowered = part.strip().lower()
            if not lowered:
                continue
            first = lowered.split(None, 1)[0]
            if first in {"cd", "chdir", "pushd", "popd", "deactivate"}:
                return True
            if first in {"source", "."}:
                return True
            if self.command_looks_like_venv_activation(part):
                return True
        return False

    def append_shell_context_probe(self, command_text):
        text = str(command_text or "").replace("\r\n", "\n").replace("\r", "\n")
        if not text.strip() or not self.shell_supports_context_probe():
            return text
        if "__SHELLDECK_CONTEXT__" in text:
            return text
        if not self.shell_command_needs_context_probe(text):
            return text
        # Für interaktive Clients ist der Probe-Befehl unerwünscht, weil er dort
        # als Eingabe beim Client landen könnte. Diese Fälle werden normalerweise
        # vor write_shell_command() abgefangen; die Prüfung bleibt als Schutz.
        first_line = text.strip().splitlines()[0] if text.strip() else ""
        if self.detect_client_mode_name(first_line):
            return text
        return text.rstrip("\n") + "\n" + self.shell_context_probe_command() + "\n"

    def consume_shell_context_markers(self, text):
        marker = "__SHELLDECK_CONTEXT__"
        value = str(text or "")
        if marker not in value:
            return value

        kept = []
        changed = False
        for line in value.splitlines(True):
            body = line.rstrip("\r\n")
            if marker not in body:
                kept.append(line)
                continue
            payload = body.split(marker, 1)[1]
            parts = payload.split("\t", 1)
            pwd = parts[0].strip() if parts else ""
            venv = parts[1].strip() if len(parts) > 1 else ""
            try:
                if pwd:
                    candidate = Path(pwd).expanduser().resolve()
                    if candidate.exists() and candidate.is_dir():
                        self.current_working_directory = str(candidate)
                        changed = True
                if venv:
                    venv_path = Path(venv).expanduser().resolve()
                    if venv_path.exists() and venv_path.is_dir():
                        self.venv_path = str(venv_path)
                        changed = True
                else:
                    # Eine leere VIRTUAL_ENV-Marke bedeutet: Die Shell hat keine
                    # aktive venv mehr. Der Restore-Befehl bleibt erhalten, aber
                    # die Statusanzeige soll dann kein (.venv) vortäuschen.
                    if str(getattr(self, "venv_path", "") or ""):
                        self.venv_path = ""
                        changed = True
            except OSError:
                pass
        if changed:
            QTimer.singleShot(0, self.update_input_prompt_label)
        return "".join(kept)

    def normalize_start_directory(self, directory):
        text = str(directory or "").strip().strip('"')
        if not text:
            return ""
        try:
            path = Path(text).expanduser()
            if path.exists() and path.is_dir():
                return str(path)
        except OSError:
            pass
        return ""

    def normalize_venv_path(self, value):
        text = str(value or "").strip().strip('"')
        if not text:
            return ""
        try:
            path = Path(text).expanduser()
            if path.exists() and path.is_dir():
                return str(path)
        except OSError:
            pass
        return ""

    def path_is_same_or_child(self, path, parent):
        try:
            candidate = Path(path).resolve()
            base = Path(parent).resolve()
            return candidate == base or base in candidate.parents
        except OSError:
            return False

    def local_project_venv_path(self, directory=None):
        base_text = str(directory or self.refresh_current_working_directory() or "").strip()
        if not base_text:
            return ""
        try:
            base = Path(base_text)
        except OSError:
            return ""
        for candidate in (base / ".venv", base / "venv"):
            if candidate.exists() and candidate.is_dir():
                return str(candidate)
        return ""

    def inherited_venv_path_for_directory(self, directory=None):
        env_path = self.normalize_venv_path(os.environ.get("VIRTUAL_ENV", ""))
        if not env_path:
            return ""
        base_text = str(directory or self.refresh_current_working_directory() or "").strip()
        if not base_text:
            return env_path
        try:
            project_root = Path(env_path).resolve().parent
            if self.path_is_same_or_child(base_text, project_root):
                return env_path
        except OSError:
            return ""
        return ""

    def restore_command_for_venv(self, venv_path, directory=None):
        venv_text = self.normalize_venv_path(venv_path)
        if not venv_text:
            return ""
        venv = Path(venv_text)
        shell = str(self.shell_type or "").lower()
        base_text = str(directory or self.refresh_current_working_directory() or "").strip()

        def relative_or_absolute(script_path, command_prefix=""):
            try:
                base = Path(base_text) if base_text else Path.cwd()
                rel = script_path.resolve().relative_to(base.resolve())
                text = str(rel).replace("/", "\\")
                if not text.startswith("."):
                    text = ".\\" + text
                return command_prefix + text
            except (OSError, ValueError):
                return command_prefix + str(script_path)

        def posix_activation_command(script_path):
            # POSIX-sh kennt kein "source". Bash/Zsh können es, aber "." ist
            # ebenfalls gültig und funktioniert auch in /bin/sh. Damit bleiben
            # Workspace-/Profil-Restore-Befehle auf Linux robust, egal ob der
            # Tab als Bash oder sh gestartet wurde.
            return relative_or_absolute(script_path, ". ").replace("\\", "/")

        if sys.platform == "win32" and shell in {"powershell", "pwsh"}:
            script = venv / "Scripts" / "Activate.ps1"
            if script.exists():
                return relative_or_absolute(script)
            script = venv / "Scripts" / "activate"
            if script.exists():
                return relative_or_absolute(script)
        elif sys.platform == "win32" and shell == "cmd":
            script = venv / "Scripts" / "activate.bat"
            if script.exists():
                return relative_or_absolute(script)
        elif shell == "fish":
            script = venv / "bin" / "activate.fish"
            if script.exists():
                return relative_or_absolute(script, "source ").replace("\\", "/")
        else:
            script = venv / "bin" / "activate"
            if script.exists():
                return posix_activation_command(script)
            script = venv / "Scripts" / "activate"
            if script.exists():
                return posix_activation_command(script)
        return ""

    def refresh_current_working_directory(self):
        directory = self.guess_current_directory()
        if directory:
            self.current_working_directory = directory
            self.update_input_prompt_label()
        return self.current_working_directory

    def send_control_character(self, byte_value):
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.write(byte_value)
            self.process.waitForBytesWritten(1000)

    def show_terminal_context_menu(self, pos):
        sender = self.sender()
        if not hasattr(sender, "mapToGlobal"):
            return

        menu = QMenu(self)

        menu.setToolTipsVisible(True)
        if sender is self.output_area:
            copy_action = QAction("Kopieren", self)
            copy_action.setToolTip("Markierten Text aus der Ausgabe kopieren")
            copy_action.setEnabled(bool(self.output_area.textCursor().hasSelection()))
            copy_action.triggered.connect(self.output_area.copy)
            menu.addAction(copy_action)

            copy_all_action = QAction("Alles kopieren", self)
            copy_all_action.setToolTip("Gesamte Ausgabe kopieren")
            copy_all_action.triggered.connect(self.copy_all_output)
            menu.addAction(copy_all_action)

            copy_plain_action = QAction("Kopieren ohne Steuerzeichen", self)
            copy_plain_action.setToolTip("Markierten Text ohne Steuerzeichen kopieren")
            copy_plain_action.setEnabled(bool(self.output_area.textCursor().hasSelection()))
            copy_plain_action.triggered.connect(self.copy_output_plain_text)
            menu.addAction(copy_plain_action)

            copy_all_plain_action = QAction("Alles kopieren ohne Steuerzeichen", self)
            copy_all_plain_action.setToolTip("Gesamte Ausgabe ohne Steuerzeichen kopieren")
            copy_all_plain_action.triggered.connect(self.copy_all_output_plain_text)
            menu.addAction(copy_all_plain_action)

            clear_action = QAction("Ausgabe leeren", self)
            clear_action.setToolTip("Ausgabe des Terminals leeren")
            clear_action.triggered.connect(self.output_area.clear)
            menu.addAction(clear_action)

            save_output_action = QAction("Ausgabe speichern...", self)
            save_output_action.setToolTip("Aktuelle Ausgabe in eine Datei speichern")
            save_output_action.triggered.connect(self.window.save_current_output)
            menu.addAction(save_output_action)

            save_markdown_action = QAction("Ausgabe als Markdown speichern", self)
            save_markdown_action.setToolTip("Ausgabe im Markdown-Format speichern")
            save_markdown_action.triggered.connect(lambda: self.window.save_current_output("md"))
            menu.addAction(save_markdown_action)

            save_text_action = QAction("Ausgabe als Text speichern", self)
            save_text_action.setToolTip("Ausgabe im Klartext-Format speichern")
            save_text_action.triggered.connect(lambda: self.window.save_current_output("txt"))
            menu.addAction(save_text_action)

            if self.client_mode_kind == "ollama_api":
                save_ollama_md_action = QAction("Ollama-Chat als Markdown speichern", self)
                save_ollama_md_action.setToolTip("Aktuellen Ollama-Chat im Markdown-Format speichern")
                save_ollama_md_action.triggered.connect(self.window.save_current_ollama_chat_markdown)
                menu.addAction(save_ollama_md_action)

                stop_ollama_action = QAction("Ollama-Antwort stoppen", self)
                stop_ollama_action.setToolTip("Laufende Ollama-Antwort abbrechen")
                stop_ollama_action.setEnabled(self.ollama_worker is not None and self.ollama_worker.isRunning())
                stop_ollama_action.triggered.connect(self.window.stop_current_ollama_response)
                menu.addAction(stop_ollama_action)

                copy_last_code_action = QAction("Letzten Codeblock kopieren", self)
                copy_last_code_action.setToolTip("Letzten Codeblock aus der Ausgabe kopieren")
                copy_last_code_action.setEnabled(bool(self.last_ollama_code_blocks))
                copy_last_code_action.triggered.connect(self.copy_last_ollama_code_block)
                menu.addAction(copy_last_code_action)

            search_action = QAction("Suchen", self)
            search_action.setToolTip("In der Ausgabe suchen")
            search_action.setShortcut("Ctrl+F")
            search_action.triggered.connect(self.show_output_search_dialog)
            menu.addAction(search_action)

            find_next_action = QAction("Nächster Treffer", self)
            find_next_action.setToolTip("Nächsten Suchtreffer in der Ausgabe finden")
            find_next_action.setShortcut("F3")
            find_next_action.setEnabled(bool(self.output_search_text))
            find_next_action.triggered.connect(lambda: self.find_output_text(backward=False))
            menu.addAction(find_next_action)

            find_previous_action = QAction("Vorheriger Treffer", self)
            find_previous_action.setToolTip("Vorherigen Suchtreffer in der Ausgabe finden")
            find_previous_action.setShortcut("Shift+F3")
            find_previous_action.setEnabled(bool(self.output_search_text))
            find_previous_action.triggered.connect(lambda: self.find_output_text(backward=True))
            menu.addAction(find_previous_action)

            menu.addSeparator()

        elif sender is self.input_line:
            copy_action = QAction("Kopieren", self)
            copy_action.setToolTip("Markierten Text aus der Eingabe kopieren")
            copy_action.setEnabled(bool(self.input_line.textCursor().hasSelection()))
            copy_action.triggered.connect(self.input_line.copy)
            menu.addAction(copy_action)

            paste_action = QAction("Einfügen", self)
            paste_action.setToolTip("Inhalt aus der Zwischenablage einfügen")
            paste_action.triggered.connect(self.input_line.paste)
            menu.addAction(paste_action)

            paste_execute_action = QAction("Einfügen + Ausführen", self)
            paste_execute_action.setToolTip("Inhalt aus der Zwischenablage einfügen und ausführen")
            paste_execute_action.triggered.connect(self.paste_and_execute_command)
            menu.addAction(paste_execute_action)

            cut_action = QAction("Ausschneiden", self)
            cut_action.setToolTip("Markierten Text aus der Eingabe ausschneiden")
            cut_action.setEnabled(bool(self.input_line.textCursor().hasSelection()))
            cut_action.triggered.connect(self.input_line.cut)
            menu.addAction(cut_action)

            select_all_action = QAction("Alles auswählen", self)
            select_all_action.setToolTip("Gesamte Eingabe auswählen")
            select_all_action.triggered.connect(self.input_line.selectAll)
            menu.addAction(select_all_action)

            attach_file_action = QAction("Datei anhängen", self)
            attach_file_action.triggered.connect(self.window.attach_file_to_current_prompt)
            menu.addAction(attach_file_action)

            menu.addSeparator()

        new_tab_action = QAction("Neuer Tab", self)
        new_tab_action.triggered.connect(self.window.new_tab)
        menu.addAction(new_tab_action)

        duplicate_tab_action = QAction("Tab duplizieren", self)
        duplicate_tab_action.triggered.connect(self.window.duplicate_current_tab)
        menu.addAction(duplicate_tab_action)

        rename_tab_action = QAction("Tab umbenennen", self)
        rename_tab_action.triggered.connect(self.window.rename_current_tab)
        menu.addAction(rename_tab_action)

        command_palette_action = QAction("Befehlspalette", self)
        command_palette_action.setShortcut("Ctrl+Shift+P")
        command_palette_action.triggered.connect(self.window.show_command_palette)
        menu.addAction(command_palette_action)

        update_directory_action = QAction("Tab-Ordner aktualisieren", self)
        update_directory_action.triggered.connect(self.window.update_current_tab_directory)
        menu.addAction(update_directory_action)

        if self.client_mode_active:
            stop_client_action = QAction("Client-Modus beenden", self)
            stop_client_action.triggered.connect(self.exit_client_mode)
            menu.addAction(stop_client_action)

        close_tab_action = QAction("Aktuellen Tab schließen", self)
        close_tab_action.triggered.connect(self.window.close_current_tab)
        menu.addAction(close_tab_action)

        signal_menu = menu.addMenu("Signal senden")
        sigint_action = signal_menu.addAction("Strg+C (SIGINT)")
        sigint_action.triggered.connect(lambda: self.send_control_character(b"\x03"))
        sigtstp_action = signal_menu.addAction("Strg+Z (SIGTSTP/Pause)")
        sigtstp_action.triggered.connect(lambda: self.send_control_character(b"\x1a"))
        eof_action = signal_menu.addAction("Strg+D (EOF)")
        eof_action.triggered.connect(lambda: self.send_control_character(b"\x04"))
        sigquit_action = signal_menu.addAction("Strg+\\ (SIGQUIT)")
        sigquit_action.triggered.connect(lambda: self.send_control_character(b"\x1c"))

        menu.exec(sender.mapToGlobal(pos))

    def show_output_search_dialog(self):
        text, ok = QInputDialog.getText(
            self,
            "Ausgabe durchsuchen",
            "Suchtext:",
            text=self.output_search_text,
        )
        if ok and text:
            self.output_search_text = text
            self.find_output_text(backward=False, restart=True)

    def find_output_text(self, backward=False, restart=False):
        query = str(self.output_search_text or "")
        if not query:
            self.show_output_search_dialog()
            return

        flags = QTextDocument.FindFlag.FindBackward if backward else QTextDocument.FindFlag(0)
        if restart:
            cursor = self.output_area.textCursor()
            cursor.movePosition(
                QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
            )
            self.output_area.setTextCursor(cursor)

        if self.output_area.find(query, flags):
            self.window.statusBar().showMessage(f"Treffer: {query}")
            return

        cursor = self.output_area.textCursor()
        cursor.movePosition(
            QTextCursor.MoveOperation.End if backward else QTextCursor.MoveOperation.Start
        )
        self.output_area.setTextCursor(cursor)
        if self.output_area.find(query, flags):
            self.window.statusBar().showMessage(f"Treffer nach Umbruch: {query}")
        else:
            self.window.statusBar().showMessage(f"Nicht gefunden: {query}")

    def selected_output_text(self):
        cursor = self.output_area.textCursor()
        return cursor.selectedText().replace("\u2029", "\n") if cursor.hasSelection() else ""

    def output_text_for_copy(self, selected_only=False):
        if selected_only:
            return self.selected_output_text()
        return self.output_area.toPlainText()

    def copy_all_output(self):
        self.output_area.selectAll()
        self.output_area.copy()

    def copy_output_plain_text(self):
        text = self.output_text_for_copy(selected_only=True)
        if not text:
            return
        QApplication.clipboard().setText(self.window.clean_output_text(text))
        self.window.show_status("Auswahl ohne Steuerzeichen kopiert")

    def copy_all_output_plain_text(self):
        text = self.output_text_for_copy(selected_only=False)
        if not text:
            return
        QApplication.clipboard().setText(self.window.clean_output_text(text))
        self.window.show_status("Ausgabe ohne Steuerzeichen kopiert")

    def paste_and_execute_command(self):
        text = QApplication.clipboard().text().strip()
        if not text:
            return
        self.input_line.setPlainText(text)
        self.input_line.moveCursor(QTextCursor.MoveOperation.End)
        self.execute_command()

    def command_sequence_from_text(self, command_text, *, include_prefix=True):
        commands = []

        def append_split_commands(text_block):
            for line in str(text_block or "").splitlines():
                for cmd in line.split(";"):
                    text = cmd.strip()
                    if text:
                        commands.append(text)

        if include_prefix and not self.client_mode_active:
            prefix_commands = self.window.active_pre_command_text()
            if prefix_commands:
                self.window.remember_pre_command_text(prefix_commands)
                append_split_commands(prefix_commands)

        raw_command_text = str(command_text or "").strip()
        if not raw_command_text:
            return commands

        # Mehrzeilige Shell-Eingaben müssen als Block an die Shell gehen.
        # Sonst zerlegt ShellDeck z.B. PowerShell-Kommandos mit Backtick-
        # Fortsetzung in einzelne Zeilen und PowerShell bleibt im ">>"-Prompt
        # hängen. Einzeilige Befehle werden weiter wie bisher an Semikolon
        # getrennt, damit Vorbefehl und Spezialerkennung stabil bleiben.
        if "\n" in raw_command_text or "\r" in raw_command_text:
            commands.append(raw_command_text.replace("\r\n", "\n").replace("\r", "\n"))
        else:
            append_split_commands(raw_command_text)
        return commands

    def run_text_command(self, command):
        self.input_line.setPlainText(command)
        self.input_line.moveCursor(QTextCursor.MoveOperation.End)
        self.execute_command()

    def guess_current_directory(self):
        text = self.output_area.toPlainText()
        patterns = [
            r"PS\s+([^>]+)>\s*$",
            r"^([A-Za-z]:\\[^>]+)>\s*$",
            r"^([A-Za-z]:/[^>]+)>\s*$",
            r"^[^@\s]+@[^:]+:([^#$]+)[#$]\s*$",
        ]
        for line in reversed(text.splitlines()):
            stripped = line.strip()
            for pattern in patterns:
                match = re.search(pattern, stripped)
                if match:
                    candidate = match.group(1).strip().replace("\\", os.sep)
                    if candidate.startswith("~"):
                        candidate = os.path.expanduser(candidate)
                    if Path(candidate).exists():
                        return str(Path(candidate))
        # Bei PTY-Shells liefert process.workingDirectory() nur das Start-
        # verzeichnis des Adapter-Prozesses, nicht zuverlässig den aktuellen
        # Ordner der laufenden Shell. Deshalb zuerst den von ShellDeck gepflegten
        # Zustand verwenden. Sonst kann ein Speichern/Umschalten der Vorbefehle
        # die Anzeige wieder auf den Home-Ordner zurücksetzen.
        current_dir = str(getattr(self, "current_working_directory", "") or "").strip()
        if current_dir and Path(current_dir).exists():
            return current_dir
        working_dir = self.process.workingDirectory()
        if working_dir and Path(working_dir).exists():
            return working_dir
        return str(Path.cwd())

    def create_shell_process(self):
        requested_engine = self.window.normalize_terminal_engine(getattr(self, "terminal_engine", "qprocess"))
        if sys.platform != "win32" and str(self.shell_type or "").lower() in {"bash", "zsh", "fish", "sh"}:
            # Auf Linux/macOS sollen interaktive Shells standardmäßig über ein
            # echtes PTY laufen. QProcess-Pipes erzeugen bei Bash sonst Meldungen
            # wie "Keine Jobsteuerung in dieser Shell".
            if PtyTerminalProcess.is_available():
                requested_engine = "pty"
                self.terminal_engine = "pty"
        if self.window.should_use_pty_backend(self.shell_type, engine=requested_engine):
            process = PtyTerminalProcess(self)
            self.output_area.append("[PTY/ConPTY/Linux-PTY experimentell aktiv]\n")
            return process
        process = QProcess(self)
        process._shelldeck_engine = "qprocess"
        if requested_engine == "pty":
            self.terminal_engine = "qprocess"
        return process

    def connect_shell_process(self, process):
        if process is None:
            return
        process.readyReadStandardOutput.connect(self.handle_stdout)
        process.readyReadStandardError.connect(self.handle_stderr)
        process.finished.connect(self.handle_finished)
        process.errorOccurred.connect(self.handle_process_error)

    def actual_terminal_engine(self):
        process_engine = str(getattr(getattr(self, "process", None), "_shelldeck_engine", "") or "").lower().strip()
        if process_engine in {"qprocess", "pty"}:
            return process_engine
        return self.window.normalize_terminal_engine(getattr(self, "terminal_engine", "qprocess"))

    def set_terminal_engine(self, engine, *, restart=True):
        new_engine = self.window.normalize_terminal_engine(engine)
        old_engine = self.actual_terminal_engine()
        self.terminal_engine = new_engine
        if not restart or new_engine == old_engine:
            self.display_shell_status()
            return True

        current_dir = self.refresh_current_working_directory()
        restore_command = self.current_restore_command()
        self.stop_process(fast=False)
        old_process = getattr(self, "process", None)
        if old_process is not None:
            try:
                old_process.deleteLater()
            except Exception:
                pass
        self.output_area.clear()
        self.current_working_directory = current_dir or self.current_working_directory
        self.start_directory = current_dir or self.start_directory
        self.process = self.create_shell_process()
        self.connect_shell_process(self.process)
        self.start_shell()
        if restore_command:
            self.restore_command = restore_command
            self.schedule_restore_command(restore_command)
        return True

    def start_shell(self):
        shell_path = self.window.system_shell(self.shell_type)
        if not shell_path:
            shell_path = self.window.system_shell("powershell" if sys.platform == "win32" else "bash")
        if self.start_directory:
            try:
                self.process.setWorkingDirectory(self.start_directory)
            except Exception:
                pass
        shell_args = self.window.shell_start_args(self.shell_type)
        if self.process_uses_pty_engine() and str(self.shell_type or "").lower() in {"powershell", "pwsh"}:
            # PSReadLine repaints long input lines in a real terminal using
            # carriage-return redraws. QTextEdit is not a terminal emulator and
            # would show those intermediate redraws as duplicated fragments.
            # In ShellDeck the lower input widget already handles editing and
            # history, so disabling PSReadLine only for the experimental PTY
            # PowerShell path keeps command output readable without affecting
            # the standard QProcess engine.
            shell_args = [
                "-NoLogo",
                "-NoProfile",
                "-NoExit",
                "-Command",
                "try { Remove-Module PSReadLine -ErrorAction SilentlyContinue } catch {}",
            ]
        self.process.start(shell_path, shell_args)
        self.display_shell_status(shell_path)

    def restart_shell(self):
        if self.process.state() == QProcess.ProcessState.Running:
            self.stop_process(fast=False)
        self.output_area.clear()
        self.start_shell()

    def process_is_running(self, process):
        return process is not None and process.state() == QProcess.ProcessState.Running

    def finish_process_quickly(self, process, fast=False):
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return

        terminate_timeout = 250 if fast else 1200
        kill_timeout = 250 if fast else 800

        process.terminate()
        if process.waitForFinished(terminate_timeout):
            return

        QApplication.processEvents()
        if process.state() == QProcess.ProcessState.NotRunning:
            return

        process.kill()
        process.waitForFinished(kill_timeout)
        QApplication.processEvents()

    def stop_ollama_worker(self, fast=False):
        worker = self.ollama_worker
        if worker is None:
            return
        if worker.isRunning():
            worker.requestInterruption()
            worker.terminate()
            worker.wait(250 if fast else 1200)
        worker.deleteLater()
        self.ollama_worker = None

    def stop_process(self, fast=False):
        self.stop_ollama_worker(fast=fast)
        self.stop_client_process(fast=fast)
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.finish_process_quickly(self.process, fast=fast)

    def interrupt_current_command(self):
        if self.client_mode_active and self.client_mode_kind == "ollama_api":
            self.output_area.append("\n[Ollama-API-Modus beendet]\n")
            self.set_client_mode(False)
            return
        if self.client_mode_active and self.client_mode_kind == "direct_process":
            self.output_area.append(f"\n[{self.client_mode_name or 'Client'} wird unterbrochen]\n")
            self.stop_client_process()
            self.set_client_mode(False)
            return
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.write(b"\x03")
            self.process.waitForBytesWritten(1000)
            if self.client_mode_active:
                self.set_client_mode(False)
        else:
            self.output_area.append("Kein laufender Prozess zum Unterbrechen.")

    def exit_client_mode(self):
        if not self.client_mode_active:
            return

        if self.client_mode_kind in {"ollama_prompt", "ollama_api"}:
            self.output_area.append("\n[Ollama-Modus beendet]\n")
            self.set_client_mode(False)
            return

        if self.client_mode_kind == "direct_process":
            if self.client_process is not None and self.client_process.state() == QProcess.ProcessState.Running:
                exit_command = getattr(self, "direct_client_exit_command", "exit") or "exit"
                self.client_process.write(exit_command.encode() + b"\n")
                self.client_process.waitForBytesWritten(1000)
            else:
                self.set_client_mode(False)
            return

        label = self.client_mode_name.lower()
        exit_command = "exit"
        if "sqlite" in label or "node" in label:
            exit_command = ".exit"
        elif "postgres" in label or "psql" in label:
            exit_command = "\\q"
        elif "sql" in label and "sqlcmd" in label:
            exit_command = "exit"

        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.write(exit_command.encode() + b"\n")
            self.process.waitForBytesWritten(1000)

        self.set_client_mode(False)

    def display_shell_status(self, shell_path=None):
        backend_label = self.window.shell_backend_label(self.shell_type)
        engine_label = self.window.terminal_engine_label_for_process(getattr(self, "process", None))
        self.title = self.custom_title or backend_label
        self.window.update_tab_title(self)
        self.window.statusBar().showMessage(f"Shell-Backend: {backend_label} | Engine: {engine_label}")

    def eventFilter(self, source, event):
        """Handle terminal/input events safely during widget construction.

        Qt can already deliver events while a TerminalTab is still being
        constructed. At that point output_area may exist while input_line does
        not yet exist. Access both widgets through getattr() so startup never
        fails with AttributeError.
        """
        output_area = getattr(self, "output_area", None)
        input_line = getattr(self, "input_line", None)

        if (
            output_area is not None
            and source is output_area.viewport()
            and event.type() == QEvent.Type.MouseButtonRelease
        ):
            if getattr(event, "button", lambda: None)() == Qt.MouseButton.LeftButton:
                try:
                    pos = event.position().toPoint()
                except AttributeError:
                    pos = event.pos()
                anchor = output_area.anchorAt(pos)
                if str(anchor).startswith("shelldeck-copy-code:"):
                    index_text = str(anchor).split(":", 1)[1]
                    self.copy_ollama_code_block(index_text)
                    return True

        if (
            input_line is not None
            and source is input_line
            and event.type() == QEvent.Type.KeyPress
        ):
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self.execute_command()
                return True
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                input_line.insertPlainText("\n")
                return True
            if event.key() == Qt.Key.Key_Up:
                self.show_previous_command()
                return True
            if event.key() == Qt.Key.Key_Down:
                self.show_next_command()
                return True
        return super().eventFilter(source, event)


    def normalize_command_history(self, history):
        if not isinstance(history, list):
            return []
        result = []
        for item in history:
            text = str(item or "").strip()
            if text and (not result or result[-1] != text):
                result.append(text)
        return result[-max(1, int(getattr(self.window, "max_history_size", 1000))):]

    def tab_history(self):
        return self.command_history

    def command_history_text(self, command):
        text = str(command or "").strip()
        marker = "\n\n---\nAngehängte Datei als Kontext:"
        if marker in text:
            text = text.split(marker, 1)[0].strip() or "[Prompt mit angehängter Datei]"
        if len(text) > 2000:
            text = text[:2000].rstrip() + " …"
        return text

    def add_command_history(self, command):
        text = self.command_history_text(command)
        if not text:
            return
        if not self.command_history or self.command_history[-1] != text:
            self.command_history.append(text)
        limit = max(1, int(getattr(self.window, "max_history_size", 1000)))
        self.command_history = self.command_history[-limit:]
        if text and (not self.window.history or self.window.history[-1] != text):
            self.window.history.append(text)
            self.window.history = self.window.history[-limit:]
            self.window.save_history()
        self.window.save_settings()

    def command_looks_like_venv_activation(self, command):
        text = str(command or "").strip()
        lower = text.lower().replace("/", "\\")
        if "activate" not in lower:
            return False
        return (
            "venv" in lower
            or ".venv" in lower
            or "scripts\\activate" in lower
            or "bin\\activate" in lower
        )

    def update_restore_command_from_command(self, command):
        text = str(command or "").strip()
        if self.command_looks_like_venv_activation(text):
            normalizer = getattr(self.window, "normalize_restore_command_for_shell", None)
            self.restore_command = normalizer(text, self.shell_type) if callable(normalizer) else text
            detected = self.local_project_venv_path() or self.inherited_venv_path_for_directory()
            if detected:
                self.venv_path = detected

    def infer_venv_restore_command(self):
        for command in reversed(self.command_history):
            if self.command_looks_like_venv_activation(command):
                detected = self.local_project_venv_path() or self.inherited_venv_path_for_directory()
                if detected:
                    self.venv_path = detected
                return str(command).strip()

        directory = self.refresh_current_working_directory()
        if not directory:
            return ""

        candidates = [
            self.venv_path,
            self.inherited_venv_path_for_directory(directory),
        ]

        output = self.output_area.toPlainText()
        prompt_looks_active = "(.venv)" in output or "(venv)" in output
        if prompt_looks_active or bool(os.environ.get("VIRTUAL_ENV")):
            candidates.append(self.local_project_venv_path(directory))

        # Workspace restore should restore project state, not only a title/path.
        # If a saved tab points at a project root containing .venv/venv, derive the
        # matching activation command after the old shell process has gone away.
        candidates.append(self.local_project_venv_path(directory))

        for candidate in candidates:
            normalized = self.normalize_venv_path(candidate)
            if not normalized:
                continue
            command = self.restore_command_for_venv(normalized, directory)
            if command:
                self.venv_path = normalized
                return command
        return ""

    def current_restore_command(self):
        explicit = str(self.restore_command or "").strip()
        if explicit:
            normalizer = getattr(self.window, "normalize_restore_command_for_shell", None)
            normalized = normalizer(explicit, self.shell_type) if callable(normalizer) else explicit
            if normalized != explicit:
                self.restore_command = normalized
            return normalized
        inferred = self.infer_venv_restore_command()
        if inferred:
            normalizer = getattr(self.window, "normalize_restore_command_for_shell", None)
            inferred = normalizer(inferred, self.shell_type) if callable(normalizer) else inferred
            self.restore_command = inferred
        return inferred

    def current_venv_path(self):
        if self.venv_path:
            return self.venv_path
        self.current_restore_command()
        return self.venv_path

    def schedule_restore_command(self, command=None, delay_ms=650):
        text = str(command or "").strip() or self.current_restore_command()
        if not text:
            return False
        QTimer.singleShot(int(delay_ms), lambda t=text: self.run_restore_command(t))
        return True

    def run_restore_command(self, command=None):
        text = str(command or "").strip() or self.current_restore_command()
        if not text:
            return False
        normalizer = getattr(self.window, "normalize_restore_command_for_shell", None)
        if callable(normalizer):
            text = normalizer(text, self.shell_type)
        self.restore_command = text
        if self.client_mode_active:
            return False
        if self.process.state() != QProcess.ProcessState.Running:
            self.process.waitForStarted(2500)
        if self.process.state() != QProcess.ProcessState.Running:
            self.output_area.append(f"\n[Wiederherstellungsbefehl konnte nicht ausgeführt werden: Shell ist nicht aktiv] {text}\n")
            return False
        self.update_working_context_from_shell_command(text)
        self.output_area.append(f"\n[Restore] Führe aus: {text}\n")
        self.process.write(text.encode() + b"\n")
        self.process.waitForBytesWritten(1000)
        QTimer.singleShot(250, self.update_input_prompt_label)
        return True

    def show_previous_command(self):
        history = self.tab_history()
        if not history:
            return
        if self.history_index == -1:
            self.current_command = self.input_line.toPlainText()
            self.history_index = len(history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
        self.input_line.setPlainText(history[self.history_index])
        self.input_line.moveCursor(QTextCursor.MoveOperation.End)

    def show_next_command(self):
        history = self.tab_history()
        if not history:
            return
        if self.history_index < len(history) - 1:
            self.history_index += 1
            self.input_line.setPlainText(history[self.history_index])
            self.input_line.moveCursor(QTextCursor.MoveOperation.End)
        elif self.history_index == len(history) - 1:
            self.history_index = -1
            self.input_line.setPlainText(self.current_command)
            self.input_line.moveCursor(QTextCursor.MoveOperation.End)

    def parse_ollama_run_model(self, command):
        text = str(command or "").strip()
        if not text:
            return ""
        try:
            parts = shlex.split(text, posix=False)
        except ValueError:
            parts = text.split()
        if len(parts) == 3 and Path(str(parts[0]).strip('"')).name.lower() == "ollama" and str(parts[1]).lower() == "run":
            return str(parts[2]).strip('"')
        return ""

    def parse_direct_client_command(self, command):
        text = str(command or "").strip()
        if not text:
            return None
        try:
            parts = shlex.split(text, posix=False)
        except ValueError:
            parts = text.split()
        if not parts:
            return None

        executable_text = str(parts[0]).strip('"')
        executable_name = Path(executable_text).name.lower()
        args = [str(part).strip('"') for part in parts[1:]]

        def resolved_program(name):
            return shutil.which(executable_text) or shutil.which(name) or executable_text

        python_names = {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}
        if executable_name in python_names:
            interactive = len(args) == 0 or any(arg.lower() == "-i" for arg in args)
            if not interactive:
                return None
            normalized_args = list(args)
            if not any(arg.lower() == "-i" for arg in normalized_args):
                normalized_args.insert(0, "-i")
            if executable_name not in {"py", "py.exe"} and not any(arg.lower() == "-u" for arg in normalized_args):
                normalized_args.insert(0, "-u")
            return {
                "program": resolved_program(executable_name),
                "args": normalized_args,
                "label": "Python",
                "exit_command": "exit()",
            }

        if executable_name in {"node", "node.exe"}:
            # Node.js erkennt bei QProcess-Pipes nicht immer automatisch einen
            # interaktiven REPL. Mit -i wird der REPL-Modus erzwungen, damit
            # Eingaben sofort ausgeführt werden und .exit zuverlässig beendet.
            normalized_args = list(args)
            if normalized_args and not all(str(arg).lower() in {"-i", "--interactive"} for arg in normalized_args):
                return None
            if not any(str(arg).lower() in {"-i", "--interactive"} for arg in normalized_args):
                normalized_args.insert(0, "-i")
            return {
                "program": resolved_program(executable_name),
                "args": normalized_args,
                "label": "Node.js",
                "exit_command": ".exit",
            }

        sql_clients = {
            "sqlite3": ("SQLite", ".exit"),
            "sqlite3.exe": ("SQLite", ".exit"),
            "psql": ("PostgreSQL", "\\q"),
            "psql.exe": ("PostgreSQL", "\\q"),
            "mysql": ("MySQL", "quit"),
            "mysql.exe": ("MySQL", "quit"),
            "mariadb": ("MariaDB", "quit"),
            "mariadb.exe": ("MariaDB", "quit"),
            "sqlcmd": ("SQLCMD", "exit"),
            "sqlcmd.exe": ("SQLCMD", "exit"),
        }
        if executable_name in sql_clients:
            label, exit_command = sql_clients[executable_name]
            return {
                "program": resolved_program(executable_name),
                "args": args,
                "label": label,
                "exit_command": exit_command,
            }

        return None

    def start_direct_client_process(self, client_info):
        if not isinstance(client_info, dict):
            return False
        program = str(client_info.get("program", "") or "").strip()
        args = list(client_info.get("args", []) or [])
        label = str(client_info.get("label", "Client") or "Client")
        if not program:
            return False

        if self.client_process is not None:
            self.stop_client_process()

        self.direct_client_label = label
        self.direct_client_start_error_reported = False
        self.client_process = QProcess(self)
        self.client_process.readyReadStandardOutput.connect(self.handle_client_stdout)
        self.client_process.readyReadStandardError.connect(self.handle_client_stderr)
        self.client_process.finished.connect(self.handle_client_finished)
        self.client_process.errorOccurred.connect(self.handle_client_error)
        working_dir = self.refresh_current_working_directory()
        if working_dir and Path(working_dir).exists():
            self.client_process.setWorkingDirectory(working_dir)

        self.client_process.start(program, args)
        if not self.client_process.waitForStarted(2500):
            error_text = self.client_process.errorString() if self.client_process is not None else "Unbekannter Fehler"
            self.direct_client_start_error_reported = True
            self.output_area.append(self.direct_client_start_error_message(label, program, error_text))
            self.client_process.deleteLater()
            self.client_process = None
            return False

        self.direct_client_exit_command = str(client_info.get("exit_command", "exit") or "exit")
        self.output_area.append(
            f"\n[{label}-Client direkt gestartet] "
            "Eingaben unten werden direkt an diesen Prozess gesendet. "
            "/bye, exit oder quit beendet den Modus.\n"
        )
        self.set_client_mode(True, label, kind="direct_process")
        return True

    def direct_client_start_error_message(self, label, program, error_text):
        label = str(label or "Client").strip() or "Client"
        program = str(program or "").strip()
        error_text = str(error_text or "Unbekannter Fehler").strip()
        lower_label = label.lower()
        lower_program = Path(program).name.lower()

        hint = ""
        if lower_label == "sqlite" or lower_program in {"sqlite3", "sqlite3.exe"}:
            hint = (
                "\nHinweis: sqlite3.exe wurde nicht gefunden. Installiere das SQLite-CLI-Tool "
                "oder teste SQLite über Python mit dem Modul sqlite3."
            )
        elif lower_label == "python" or lower_program in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
            hint = "\nHinweis: Prüfe mit 'python --version' oder 'py --version', ob Python im PATH gefunden wird."
        elif lower_label == "node.js" or lower_program in {"node", "node.exe"}:
            hint = "\nHinweis: Prüfe mit 'node --version', ob Node.js im PATH gefunden wird."

        return f"\n[Client-Fehler] {label} konnte nicht gestartet werden: {error_text}{hint}\n"

    def stop_client_process(self, fast=False):
        if self.client_process is None:
            return
        if self.client_process.state() == QProcess.ProcessState.Running:
            self.finish_process_quickly(self.client_process, fast=fast)
        self.client_process.deleteLater()
        self.client_process = None

    def send_direct_client_input(self, text):
        payload = str(text or "").rstrip("\n")
        if not payload:
            return
        if self.client_process is None or self.client_process.state() != QProcess.ProcessState.Running:
            self.output_area.append("\n[Der direkte Client-Prozess läuft nicht mehr.]\n")
            self.set_client_mode(False)
            return

        if self.is_client_exit_command(payload):
            exit_command = getattr(self, "direct_client_exit_command", "exit") or "exit"
            self.client_process.write(exit_command.encode() + b"\n")
            self.client_process.waitForBytesWritten(1000)
            self.input_line.clear()
            return

        self.add_command_history(payload)
        self.update_restore_command_from_command(payload)
        self.history_index = -1
        self.current_command = ""
        self.client_process.write(payload.encode() + b"\n")
        self.client_process.waitForBytesWritten(1000)
        self.input_line.clear()

    def handle_client_stdout(self):
        if self.client_process is None:
            return
        data = self._decode_process_output(self.client_process.readAllStandardOutput())
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.insertPlainText(data)
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.ensureCursorVisible()

    def handle_client_stderr(self):
        if self.client_process is None:
            return
        data = self._decode_process_output(self.client_process.readAllStandardError())
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.setTextColor(QColor(self.window.terminal_color("stderr", "#FCA5A5")))
        self.output_area.insertPlainText(data)
        self.output_area.setTextColor(QColor(self.window.terminal_color("stdout", "#FFFFFF")))
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.ensureCursorVisible()

    def handle_client_finished(self, exit_code, exit_status):
        label = self.client_mode_name or "Client"
        self.output_area.append(f"\n[{label}-Client beendet, Exitcode {exit_code}]\n")
        if self.client_process is not None:
            self.client_process.deleteLater()
            self.client_process = None
        if self.client_mode_kind == "direct_process":
            self.set_client_mode(False)

    def handle_client_error(self, error):
        if self.direct_client_start_error_reported:
            return
        label = self.client_mode_name or self.direct_client_label or "Client"
        message = self.client_process.errorString() if self.client_process is not None else "Unbekannter Fehler"
        self.output_area.append(self.direct_client_start_error_message(label, "", message))
        if self.client_mode_kind == "direct_process":
            self.set_client_mode(False)

    def quote_argument_for_shell(self, text):
        value = str(text or "")
        lower_shell = str(self.shell_type or "").lower()
        if sys.platform == "win32" and lower_shell in {"powershell", "pwsh"}:
            return "'" + value.replace("'", "''") + "'"
        if sys.platform == "win32" and lower_shell == "cmd":
            return '"' + value.replace('"', '\\"') + '"'
        return "'" + value.replace("'", "'\\''") + "'"

    def start_ollama_prompt_mode(self, model_name, system_prompt=""):
        self.ollama_model = str(model_name or "").strip()
        self.ollama_context = []
        self.ollama_system_prompt = normalize_system_prompt(system_prompt)
        if not self.ollama_model:
            return False
        prompt_note = " mit Systemprompt" if self.ollama_system_prompt else ""
        self.output_area.append(
            f"\n[Ollama-API-Modus aktiv: {self.ollama_model}{prompt_note}] "
            "Eingaben unten werden direkt an die lokale Ollama-API gesendet. "
            "/bye, exit oder quit beendet den Modus.\n"
        )
        self.set_client_mode(True, f"Ollama: {self.ollama_model}", kind="ollama_api")
        return True

    def send_ollama_prompt(self, text):
        prompt = str(text or "").strip()
        if not prompt:
            return
        if self.is_client_exit_command(prompt):
            self.input_line.clear()
            self.output_area.append("\n[Ollama-API-Modus beendet]\n")
            self.set_client_mode(False)
            return
        if self.ollama_worker is not None and self.ollama_worker.isRunning():
            self.output_area.append("\n[Ollama verarbeitet noch eine Anfrage. Bitte kurz warten.]\n")
            return
        self.add_command_history(prompt)
        self.history_index = -1
        self.current_command = ""
        self.output_area.append(f"\nDu → {prompt}\n")
        self.input_line.clear()
        self.execute_button.setEnabled(False)
        self.execute_button.setText("Ollama antwortet …")
        self.window.statusBar().showMessage(f"Ollama antwortet: {self.ollama_model}")

        self.ollama_worker = OllamaApiWorker(
            self.ollama_model,
            prompt,
            context=self.ollama_context,
            system_prompt=self.ollama_system_prompt,
            parent=self,
        )
        self.ollama_worker.response_ready.connect(self.handle_ollama_response)
        self.ollama_worker.error_ready.connect(self.handle_ollama_error)
        self.ollama_worker.finished.connect(self.handle_ollama_finished)
        self.ollama_worker.start()

    def handle_ollama_response(self, answer, context):
        if isinstance(context, list):
            self.ollama_context = context
        text = str(answer or "").strip()
        if text:
            self.last_ollama_code_blocks = extract_code_blocks(text)
            html = ollama_answer_to_html(text)
            self.output_area.moveCursor(QTextCursor.MoveOperation.End)
            if html:
                self.output_area.insertHtml(html)
                self.output_area.insertPlainText("\n")
            else:
                self.output_area.insertPlainText(f"\nOllama → {text}\n")
            self.output_area.moveCursor(QTextCursor.MoveOperation.End)
            self.output_area.ensureCursorVisible()
        else:
            self.output_area.append("\n[Ollama hat keine sichtbare Antwort geliefert.]\n")

    def copy_ollama_code_block(self, index=-1):
        if not self.last_ollama_code_blocks:
            self.window.show_status("Kein Codeblock zum Kopieren gefunden")
            return
        try:
            block_index = int(index)
        except (TypeError, ValueError):
            block_index = -1
        if block_index < 0 or block_index >= len(self.last_ollama_code_blocks):
            block_index = len(self.last_ollama_code_blocks) - 1
        block = self.last_ollama_code_blocks[block_index]
        QApplication.clipboard().setText(str(block.get("code", "") or ""))
        language = str(block.get("language", "Code") or "Code")
        self.window.show_status(f"{language}-Codeblock kopiert")

    def copy_last_ollama_code_block(self):
        self.copy_ollama_code_block(-1)

    def handle_ollama_error(self, message):
        self.output_area.append(f"\n[Ollama-Fehler] {message}\n")

    def handle_ollama_finished(self):
        if self.client_mode_active and self.client_mode_kind == "ollama_api":
            self.execute_button.setEnabled(True)
            self.execute_button.setText(self.client_send_button_text())
            self.window.statusBar().showMessage(f"Client-Modus aktiv: Ollama: {self.ollama_model}")
        else:
            self.execute_button.setEnabled(True)
            self.execute_button.setText("Befehl ausführen")
        if self.ollama_worker is not None:
            self.ollama_worker.deleteLater()
            self.ollama_worker = None
        self.client_process = None

    def stop_ollama_response(self):
        if self.ollama_worker is None or not self.ollama_worker.isRunning():
            self.window.show_status("Keine laufende Ollama-Antwort")
            return
        self.stop_ollama_worker(fast=True)
        self.execute_button.setEnabled(True)
        self.execute_button.setText(self.client_send_button_text())
        self.output_area.append("\n[Ollama-Antwort gestoppt]\n")
        self.window.show_status("Ollama-Antwort gestoppt")

    def is_client_exit_command(self, text):
        command = str(text or "").strip().lower()
        return command in {"/bye", "/exit", "exit", "quit", ".exit"}

    def detect_client_mode_name(self, command):
        text = str(command or "").strip()
        if not text:
            return ""

        try:
            parts = shlex.split(text, posix=False)
        except ValueError:
            parts = text.split()

        if not parts:
            return ""

        executable = Path(str(parts[0]).strip('"')).name.lower()
        lower_text = text.lower()

        if executable == "ollama" and len(parts) >= 3 and str(parts[1]).lower() == "run":
            # "ollama run <model> <prompt>" is usually a one-shot request.
            # "ollama run <model>" starts an interactive client.
            if len(parts) <= 3:
                model_name = str(parts[2]).strip('"')
                return f"Ollama: {model_name}"
            return ""

        if executable in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
            if len(parts) == 1 or any(str(part).lower() == "-i" for part in parts[1:]):
                return "Python"

        if executable in {"node", "node.exe"}:
            if len(parts) == 1:
                return "Node.js"

        sql_clients = {
            "sqlite3": "SQLite",
            "sqlite3.exe": "SQLite",
            "psql": "PostgreSQL",
            "psql.exe": "PostgreSQL",
            "mysql": "MySQL",
            "mysql.exe": "MySQL",
            "mariadb": "MariaDB",
            "mariadb.exe": "MariaDB",
        }
        if executable in sql_clients:
            return sql_clients[executable]

        if lower_text.startswith("sqlcmd"):
            return "SQL"

        return ""

    def client_send_button_text(self):
        label = (self.client_mode_name or "Client").strip()
        kind = (self.client_mode_kind or "").strip()
        if kind in {"ollama_prompt", "ollama_api"}:
            return "An Ollama senden"
        if kind == "direct_process":
            clean = label.replace(":", "").strip() or "Client"
            return f"An {clean} senden"
        return "An Client senden"

    def set_client_mode(self, active, name="", kind=""):
        self.client_mode_active = bool(active)
        self.client_mode_name = str(name or "").strip()
        self.client_mode_kind = str(kind or "").strip() if self.client_mode_active else ""

        # Ollama-Antworten enthalten formatiertes HTML und Codeblöcke.
        # Der Terminal-Syntaxhighlighter würde diese HTML-Formatierung teilweise
        # überschreiben und erzeugt dann unruhige Zeilenfarben. Deshalb wird er
        # nur für echte Shell-/Client-Ausgaben verwendet, nicht im Ollama-Chat.
        if self.client_mode_active and self.client_mode_kind == "ollama_api":
            if self.highlighter.document() is not None:
                self.highlighter.setDocument(None)
        elif self.highlighter.document() is None:
            self.highlighter.setDocument(self.output_area.document())
            self.highlighter.set_terminal_colors(self.window.terminal_colors())

        if self.client_mode_active:
            label = self.client_mode_name or "interaktiver Client"
            self.execute_button.setText(self.client_send_button_text())
            self.input_line.setPlaceholderText(f"Eingabe an {label} …  /bye, exit oder quit beendet")
            self.window.statusBar().showMessage(f"Client-Modus aktiv: {label}")
        else:
            self.client_mode_name = ""
            self.client_mode_kind = ""
            self.ollama_model = ""
            self.ollama_context = []
            self.ollama_system_prompt = ""
            self.execute_button.setEnabled(True)
            self.execute_button.setText("Befehl ausführen")
            self.input_line.setPlaceholderText("")
            self.interaction_prompt_active = False
            self._interaction_prompt_tail = ""
            self._interaction_prompt_text = ""
            self._awaiting_command_completion = False
            engine_label = self.window.terminal_engine_label_for_process(getattr(self, "process", None))
            self.window.statusBar().showMessage(f"Shell-Backend: {self.window.shell_backend_label(self.shell_type)} | Engine: {engine_label}")

    def password_prompt_patterns(self):
        """Erkennungsregeln für interaktive Passwortabfragen.

        sudo/ssh/passphrase-Prompts schreiben bewusst kein lokales Echo. ShellDeck
        nutzt dafür keinen normalen Befehlsmodus, sondern sendet die nächste
        Eingabe roh an den laufenden PTY/QProcess. So werden Vorbefehle,
        Verlauf, Kontext-Probes und Log-Ausgabe nicht mit dem Passwort vermischt.

        Die Muster sind absichtlich tolerant: lokalisierte sudo-Ausgaben können
        durch Terminal-Encoding/Font-Fallbacks leicht anders aussehen
        (z.B. "Passwort fuer", "Passwort für" oder mojibake). Entscheidend ist,
        dass eine frische Zeile wie ein Passwort-Prompt endet.
        """
        return [
            re.compile(r"(?:^|\n)\s*\[sudo\].{0,160}(?:password|passwort|kennwort|passphrase).{0,160}:\s*$", re.IGNORECASE | re.DOTALL),
            re.compile(r"(?:^|\n)\s*(?:password|passwort|kennwort)\s*(?:for|fuer|für)?\s*[^:\n]*:\s*$", re.IGNORECASE),
            re.compile(r"(?:^|\n)\s*enter\s+passphrase\s+for\s+[^:\n]+:\s*$", re.IGNORECASE),
            re.compile(r"(?:^|\n)\s*passphrase\s*(?:for)?\s*[^:\n]*:\s*$", re.IGNORECASE),
        ]

    def output_contains_password_prompt(self, text):
        value = str(text or "")
        if not value.strip():
            return False
        tail = value[-2000:]
        return any(pattern.search(tail) for pattern in self.password_prompt_patterns())

    def visible_output_waits_for_password(self):
        """Return True if the visible terminal tail currently ends in a password prompt."""
        try:
            return self.output_contains_password_prompt(self.output_area.toPlainText())
        except Exception:
            return False

    def handle_possible_password_prompt(self, text):
        # PTY-Ausgaben kommen oft in kleinen Chunks. Bei sudo kann die aktuelle
        # Ausgabe nur das Ende des Prompts enthalten, waehrend der Anfang bereits
        # im QTextEdit steht. Deshalb gegen Chunk + sichtbares Terminalende
        # pruefen, nicht nur gegen den aktuellen Chunk. Zusaetzlich merken wir
        # einen kleinen Tail, weil sudo den Prompt typischerweise ohne Newline
        # ausgibt und Qt/PTY ihn in mehrere readyRead-Ereignisse aufteilen kann.
        combined = str(getattr(self, "_password_prompt_tail", "") or "") + str(text or "")
        try:
            current_tail = self.output_area.toPlainText()[-2000:]
            combined = current_tail + combined
        except Exception:
            pass
        self._password_prompt_tail = combined[-3000:]
        if not self.output_contains_password_prompt(combined):
            return
        self.activate_password_prompt_mode(open_dialog=True)

    def activate_password_prompt_mode(self, *, open_dialog=True):
        if getattr(self, "client_mode_active", False):
            return False
        self.password_prompt_active = True
        self.input_line.clear()
        self.input_line.setPlaceholderText("Passwort wird angefordert – Eingabe wird nicht gespeichert")
        self.execute_button.setText("Passwort senden")
        self.execute_button.setEnabled(True)
        if open_dialog and not getattr(self, "_password_dialog_open", False):
            # sudo gibt den Prompt ohne Zeilenumbruch aus. Ein kurzer Delay sorgt
            # dafuer, dass der Prompt sichtbar ist, bevor der Dialog den Fokus
            # nimmt. Dadurch entstehen keine leeren/versehentlichen Antworten.
            QTimer.singleShot(180, self.show_password_prompt_dialog)
        return True

    def reset_password_prompt_mode(self, status_message=""):
        """Return the tab to normal command mode after a password prompt ended.

        This is intentionally separate from set_client_mode(False), because
        sudo/ssh password prompts are not a real ShellDeck client mode. It also
        prevents a stale password dialog from sending text after sudo has
        already finished and the shell prompt is visible again.
        """
        self.password_prompt_active = False
        self._password_prompt_tail = ""
        self.input_line.clear()
        self.input_line.setPlaceholderText("")
        self.execute_button.setText("Befehl ausführen")
        self.execute_button.setEnabled(True)
        if status_message:
            try:
                self.window.show_status(status_message)
            except Exception:
                pass

    def password_prompt_still_visible(self):
        return self.password_prompt_active and self.visible_output_waits_for_password()

    def refresh_password_prompt_state_after_output(self):
        """Clear stale password mode once normal command output/prompt appears."""
        if not getattr(self, "password_prompt_active", False):
            return
        if getattr(self, "_password_dialog_open", False):
            # The dialog may still be open while sudo already finished. Do not
            # close it forcefully here; send_password_input() will reject stale
            # input before anything can be written to the shell.
            return
        if not self.visible_output_waits_for_password():
            self.reset_password_prompt_mode()

    def show_password_prompt_dialog(self):
        if not getattr(self, "password_prompt_active", False):
            return
        if getattr(self, "_password_dialog_open", False):
            return
        if self.process is None or self.process.state() != QProcess.ProcessState.Running:
            self.reset_password_prompt_mode()
            return
        if not self.visible_output_waits_for_password():
            # A delayed dialog can become stale if the command already finished
            # or if sudo accepted a password entered through the lower field.
            self.reset_password_prompt_mode()
            return

        self._password_dialog_open = True
        dialog = QDialog(self)
        dialog.setWindowTitle("Passwort benötigt")
        dialog.setModal(True)

        layout = QVBoxLayout(dialog)
        label = QLabel(
            "Die laufende Shell fordert ein Passwort an.\n"
            "Es wird direkt an den Prozess gesendet und nicht im Verlauf gespeichert."
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        password_edit = QLineEdit(dialog)
        password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        password_edit.setPlaceholderText("Passwort eingeben")
        layout.addWidget(password_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        QTimer.singleShot(0, password_edit.setFocus)
        try:
            result = dialog.exec()
            if result == QDialog.DialogCode.Accepted:
                password = password_edit.text()
                if password:
                    # Before sending, verify again that the terminal still ends
                    # in a password prompt. This prevents a delayed/stale dialog
                    # from turning the password into a normal shell command after
                    # sudo has already completed.
                    if self.visible_output_waits_for_password():
                        self.send_password_input(password)
                    else:
                        self.reset_password_prompt_mode("Veraltete Passworteingabe ignoriert")
                else:
                    # Leere OK-Klicks nicht als Passwort senden. Genau das kann
                    # bei sudo sonst wie ein falscher erster Versuch wirken und
                    # eine zweite Passwortabfrage erzeugen.
                    self.window.show_status("Leere Passworteingabe ignoriert")
                    if self.visible_output_waits_for_password():
                        self.activate_password_prompt_mode(open_dialog=False)
                    else:
                        self.reset_password_prompt_mode()
            else:
                self.output_area.append("\n[Passworteingabe abgebrochen]\n")
                self.reset_password_prompt_mode()
        finally:
            self._password_dialog_open = False

    def send_password_input(self, password):
        if self.process is None or self.process.state() != QProcess.ProcessState.Running:
            self.output_area.append("\nShell ist nicht aktiv; Passwort wurde nicht gesendet.\n")
            self.reset_password_prompt_mode()
            return
        if not self.visible_output_waits_for_password():
            # The prompt has disappeared since the dialog/input mode was opened.
            # Do not write the secret to the normal shell.
            self.reset_password_prompt_mode("Veraltete Passworteingabe ignoriert")
            return
        payload = str(password or "") + "\n"
        self.process.write(payload.encode("utf-8", errors="replace"))
        self.process.waitForBytesWritten(1000)
        self.reset_password_prompt_mode("Passwort wurde an den laufenden Prozess gesendet")

    def shell_prompt_patterns(self):
        return [
            re.compile(r"(?:^|\n)\s*PS\s+[^\r\n>]+>\s*$"),
            re.compile(r"(?:^|\n)\s*\([^\r\n()]+\)\s*PS\s+[^\r\n>]+>\s*$"),
            re.compile(r"(?:^|\n)\s*[A-Za-z]:[\\/][^\r\n>]*>\s*$"),
            re.compile(r"(?:^|\n)\s*(?:\([^\r\n()]+\)\s*)?[^@\s:\r\n]+@[^:\r\n]+:[^\r\n#$]*[#$]\s*$"),
        ]

    def output_ends_with_shell_prompt(self, text):
        value = str(text or "")
        if not value.strip():
            return False
        tail = value[-2500:]
        return any(pattern.search(tail) for pattern in self.shell_prompt_patterns())

    def output_ends_with_continuation_prompt(self, text):
        value = str(text or "")
        if not value.strip():
            return False
        tail = value[-1200:].replace("\r", "\n")
        lines = [line.rstrip() for line in tail.split("\n") if line.strip()]
        if not lines:
            return False
        last = lines[-1]
        return bool(re.search(r"^(?:>>|\.\.>|>>>|\.\.\.|dquote>|quote>|pipe>)\s*$", last, re.IGNORECASE))

    def command_appears_to_be_running(self):
        if not getattr(self, "_awaiting_command_completion", False):
            return False
        if getattr(self, "client_mode_active", False) or getattr(self, "password_prompt_active", False):
            return False
        try:
            output = self.output_area.toPlainText()
        except Exception:
            return False
        return not self.output_ends_with_shell_prompt(output)

    def update_command_completion_state_from_output(self):
        try:
            output = self.output_area.toPlainText()
        except Exception:
            output = ""
        if self.output_ends_with_shell_prompt(output):
            self._awaiting_command_completion = False
            if getattr(self, "interaction_prompt_active", False):
                self.reset_interaction_prompt_mode()
            return
        if self.output_ends_with_continuation_prompt(output):
            self.activate_interaction_prompt_mode(
                "mehrzeilige Eingabe fortsetzen oder leere Zeile zum Abschließen senden",
                clear_input=False,
                status_message="Shell wartet auf die Fortsetzung einer mehrzeiligen Eingabe",
            )

    def compact_interactive_prompt_text(self, text, *, max_len=180):
        if hasattr(self.window, "clean_output_text"):
            value = self.window.clean_output_text(str(text or ""))
        else:
            value = str(text or "")
        value = value.replace("\r", "\n")
        value = re.sub(r"\s+", " ", value).strip()
        value = re.sub(r"^(?:PS\s+[^>]+>|[A-Za-z]:[^>]*>|[^@\s:]+@[^:]+:[^#$]*[#$])\s*", "", value)
        if len(value) > int(max_len):
            value = "…" + value[-int(max_len):]
        return value

    def interactive_prompt_patterns(self):
        """Breite Erkennung für sichtbare Rückfragen laufender Prozesse.

        Diese Liste ist bewusst nicht nur auf j/n beschränkt. Sie erkennt
        typische Auswahl-/Bestätigungs-/Fortsetzungsfragen, PowerShell-Confirm,
        Choice-Menüs und Prompts ohne Zeilenumbruch. Zusätzlich kann ShellDeck
        jederzeit in den allgemeinen Prozess-Eingabemodus wechseln, wenn noch
        kein normaler Shell-Prompt zurück ist.
        """
        return [
            re.compile(r"(?:^|\n).{0,260}(?:\[[^\]\r\n]{1,80}\]|\([^()\r\n]{1,80}\))\s*[:?]?\s*$", re.IGNORECASE),
            re.compile(r"(?:^|\n).{0,260}(?:yes/no|y/n|j/n|ja/nein|yes to all|no to all|all/none|a/w/n|abort|retry|ignore|abbrechen|wiederholen|weiter|neu versuchen).{0,160}[:?]\s*$", re.IGNORECASE),
            re.compile(r"(?:^|\n).{0,260}(?:fortfahren|weiter|löschen|loeschen|überschreiben|ueberschreiben|overwrite|delete|remove|continue|proceed|confirm|bestätigen|bestaetigen|abbrechen|retry|ignore|wiederholen|neu versuchen).{0,180}\?\s*$", re.IGNORECASE),
            re.compile(r"(?:^|\n).{0,260}\[[A-Za-zÄÖÜäöü?]\].{0,260}(?:\[[A-Za-zÄÖÜäöü?]\].{0,260}){1,}:\s*$", re.IGNORECASE | re.DOTALL),
            re.compile(r"(?:^|\n).{0,260}(?:press any key|drücken sie eine beliebige taste|beliebige taste|enter drücken|press enter|hit enter).{0,120}$", re.IGNORECASE),
        ]

    def extract_interactive_prompt_from_output(self, text):
        value = str(text or "")
        if not value.strip():
            return ""
        if self.output_contains_password_prompt(value) or self.output_ends_with_shell_prompt(value):
            return ""
        tail = value[-2500:].replace("\r", "\n")
        lines = [line.strip() for line in tail.split("\n") if line.strip()]
        if not lines:
            return ""
        if self.output_ends_with_continuation_prompt(tail):
            return "mehrzeilige Eingabe fortsetzen oder leere Zeile zum Abschließen senden"
        last_line = lines[-1]
        check_text = tail if re.search(r"\[[A-Za-zÄÖÜäöü?]\].*\[[A-Za-zÄÖÜäöü?]\]", tail, re.DOTALL) else last_line
        for pattern in self.interactive_prompt_patterns():
            if pattern.search(check_text):
                return self.compact_interactive_prompt_text(check_text)
        return ""

    def output_contains_interactive_prompt(self, text):
        return bool(self.extract_interactive_prompt_from_output(text))

    def visible_output_waits_for_interaction(self):
        try:
            return self.output_contains_interactive_prompt(self.output_area.toPlainText())
        except Exception:
            return False

    def extract_interactive_prompt_from_command(self, command):
        """Best-effort-Erkennung für Befehle, deren Frage nicht sichtbar wird.

        PowerShell Read-Host über QProcess zeigt die Frage je nach Host nicht
        als normales stdout. Auch choice, set /p und read -p werden hier erfasst,
        damit unten trotzdem ein verständlicher Antwort-Hinweis steht.
        """
        text = str(command or "").strip()
        if not text:
            return ""
        patterns = [
            r"(?is)\bread-host\b\s+(?:-prompt\s+)?(?P<quote>['\"])(?P<prompt>.*?)(?P=quote)",
            r"(?is)\bread-host\b\s+-prompt\s+(?P<prompt>[^;\r\n]+)",
            r"(?is)\bchoice\b.*?\s/(?:m|message)\s+(?P<quote>['\"])(?P<prompt>.*?)(?P=quote)",
            r"(?is)\bset\s+/p\s+[^=\s]+\s*=\s*(?P<prompt>[^\r\n]+)",
            r"(?is)\bread\b.*?\s-p\s+(?P<quote>['\"])(?P<prompt>.*?)(?P=quote)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            prompt = str(match.groupdict().get("prompt", "") or "").strip().strip('"\'')
            if prompt:
                return self.compact_interactive_prompt_text(prompt)
        lowered = text.lower()
        if re.search(r"\b(pause|read-host|choice|set\s+/p|read\b|ssh|sudo|su|passwd)\b", lowered):
            return "laufender Befehl wartet auf Eingabe"
        return ""

    def command_may_request_interactive_input(self, command):
        return bool(self.extract_interactive_prompt_from_command(command))

    def handle_possible_interactive_prompt(self, text):
        if getattr(self, "password_prompt_active", False):
            return
        combined = str(getattr(self, "_interaction_prompt_tail", "") or "") + str(text or "")
        try:
            current_tail = self.output_area.toPlainText()[-2500:]
            combined = current_tail + combined
        except Exception:
            pass
        self._interaction_prompt_tail = combined[-3500:]
        prompt_text = self.extract_interactive_prompt_from_output(combined)
        if not prompt_text:
            return
        self.activate_interaction_prompt_mode(prompt_text, clear_input=True)

    def activate_interaction_prompt_mode(self, prompt_text="", *, clear_input=True, status_message=""):
        if getattr(self, "client_mode_active", False):
            return False
        if getattr(self, "password_prompt_active", False):
            return False
        self.interaction_prompt_active = True
        self._interaction_prompt_text = self.compact_interactive_prompt_text(prompt_text) if prompt_text else ""
        if clear_input:
            self.input_line.clear()
        if self._interaction_prompt_text:
            self.input_line.setPlaceholderText("Antwort/Eingabe an laufenden Prozess senden …")
        else:
            self.input_line.setPlaceholderText("Eingabe wird roh an den laufenden Prozess gesendet …")
        self.execute_button.setText("Eingabe senden" if not self._interaction_prompt_text else "Antwort senden")
        self.execute_button.setEnabled(True)
        self.update_input_prompt_label()
        try:
            self.window.show_status(status_message or "Laufender Prozess wartet möglicherweise auf Eingabe")
        except Exception:
            pass
        return True

    def reset_interaction_prompt_mode(self, status_message=""):
        self.interaction_prompt_active = False
        self._interaction_prompt_tail = ""
        self._interaction_prompt_text = ""
        if not getattr(self, "password_prompt_active", False) and not getattr(self, "client_mode_active", False):
            self.input_line.clear()
            self.input_line.setPlaceholderText("")
            self.execute_button.setText("Befehl ausführen")
            self.execute_button.setEnabled(True)
            self.update_input_prompt_label()
        if status_message:
            try:
                self.window.show_status(status_message)
            except Exception:
                pass

    def refresh_interaction_prompt_state_after_output(self):
        if getattr(self, "password_prompt_active", False):
            self.reset_interaction_prompt_mode()
            return
        self.update_command_completion_state_from_output()
        if getattr(self, "interaction_prompt_active", False):
            try:
                output = self.output_area.toPlainText()
            except Exception:
                output = ""
            prompt_text = self.extract_interactive_prompt_from_output(output)
            if prompt_text:
                self._interaction_prompt_text = prompt_text
                self.update_input_prompt_label()
            elif self.output_ends_with_shell_prompt(output):
                self.reset_interaction_prompt_mode()

    def refresh_process_input_mode_hint(self):
        if getattr(self, "client_mode_active", False) or getattr(self, "password_prompt_active", False):
            return
        if getattr(self, "interaction_prompt_active", False):
            return
        if self.command_appears_to_be_running():
            self.activate_interaction_prompt_mode(
                self.extract_interactive_prompt_from_command(getattr(self, "_last_sent_shell_command", "")) or "laufender Prozess nimmt Eingaben an",
                clear_input=False,
                status_message="Laufender Prozess ist noch aktiv; Eingaben werden direkt dorthin gesendet",
            )

    def send_interactive_input(self, answer):
        if self.process is None or self.process.state() != QProcess.ProcessState.Running:
            self.output_area.append("\nShell ist nicht aktiv; Eingabe wurde nicht gesendet.\n")
            self.reset_interaction_prompt_mode()
            return
        payload = str(answer or "")
        # Leere Eingaben sind wichtig: Sie schließen z.B. PowerShell-Continuation
        # (>>) ab oder bestätigen "Press Enter"-Prompts.
        payload = payload.rstrip("\n") + "\n"
        self.remember_pending_interactive_response_echo(answer)
        self.process.write(payload.encode("utf-8", errors="replace"))
        self.process.waitForBytesWritten(1000)
        self.input_line.clear()
        self._awaiting_command_completion = True
        QTimer.singleShot(250, self.refresh_interaction_prompt_state_after_output)

    def send_client_input(self, text):
        if self.client_mode_kind in {"ollama_prompt", "ollama_api"}:
            self.send_ollama_prompt(text)
            return
        if self.client_mode_kind == "direct_process":
            self.send_direct_client_input(text)
            return

        payload = str(text or "").rstrip("\n")
        if not payload:
            return

        if self.process.state() != QProcess.ProcessState.Running:
            self.output_area.append(
                f"Shell ist nicht aktiv: {self.process.errorString() or 'Prozess wurde beendet.'}"
            )
            self.set_client_mode(False)
            return

        if self.is_client_exit_command(payload):
            self.process.write(payload.encode() + b"\n")
            self.input_line.clear()
            self.set_client_mode(False)
            return

        self.add_command_history(payload)

        self.history_index = -1
        self.current_command = ""
        self.process.write(payload.encode() + b"\n")
        self.input_line.clear()

    def write_shell_command(self, command):
        text = str(command or "").replace("\r\n", "\n").replace("\r", "\n")
        if not text:
            return
        self.update_working_context_from_shell_command(text)

        # Nach jedem normalen POSIX-Shell-Befehl fragt ShellDeck den echten
        # Arbeitsordner nur bei Shell-State-Befehlen direkt ab. Ein pauschaler
        # Probe-Befehl nach jeder Eingabe könnte sonst als Antwort in
        # interaktiven Programmen landen.
        text = self.append_shell_context_probe(text)

        # In PTY/ConPTY PowerShell the shell is started without PSReadLine.
        # That avoids the redraw storm that produced duplicated command
        # fragments. Send the command normally; the pending-echo filter remains
        # as a safety net for already emitted redraw fragments.
        if self.process_uses_pty_engine() and str(self.shell_type or "").lower() in {"powershell", "pwsh"}:
            self.remember_pending_pty_command_echo(text)

        self.update_working_context_from_shell_command(text)
        shell = str(self.shell_type or "").lower()
        is_powershell = shell in {"powershell", "pwsh"}
        is_multiline = "\n" in text
        if not text.endswith("\n"):
            text += "\n"
        # PowerShell-Mehrzeiler mit Backtick/Fortsetzung brauchen über
        # QProcess häufig eine zusätzliche Abschluss-Eingabe. Diese leere Zeile
        # verhindert, dass ShellDeck im ">>"-Prompt stehen bleibt.
        if is_powershell and is_multiline and not text.endswith("\n\n"):
            text += "\n"
        self._last_sent_shell_command = str(command or "")
        self._awaiting_command_completion = True
        self.process.write(text.encode())
        self.process.waitForBytesWritten(1000)
        QTimer.singleShot(300, self.refresh_process_input_mode_hint)

    def execute_command(self):
        command_text = self.input_line.toPlainText().strip()
        if not command_text:
            return

        if self.password_prompt_active or self.visible_output_waits_for_password():
            # Sicherheitsnetz: Wenn kein Popup sichtbar ist oder der Benutzer es
            # geschlossen hat, darf die naechste Eingabe bei einem sichtbaren
            # sudo/ssh-Passwortprompt trotzdem nicht als normaler Shell-Befehl
            # ausgefuehrt und nicht im Verlauf gespeichert werden. Wenn der
            # Prompt inzwischen verschwunden ist, wird die Eingabe verworfen
            # statt als normaler Befehl mit Passwortinhalt zu laufen.
            if self.visible_output_waits_for_password():
                self.activate_password_prompt_mode(open_dialog=False)
                self.send_password_input(command_text)
            else:
                self.reset_password_prompt_mode("Veraltete Passworteingabe ignoriert")
            return

        if self.interaction_prompt_active or self.visible_output_waits_for_interaction() or self.command_appears_to_be_running():
            # Laufender Prozess/Continuation/Confirm: Eingabe roh senden. Keine
            # Historie, kein Vorbefehl und keine Kontext-Probe. So können auch
            # allgemeine Rückfragen, Menüs, Read-Host, a/w/n-Auswahlen oder eine
            # abschließende Leerzeile beantwortet werden.
            prompt = ""
            try:
                prompt = self.extract_interactive_prompt_from_output(self.output_area.toPlainText())
            except Exception:
                prompt = ""
            self.activate_interaction_prompt_mode(prompt, clear_input=False)
            self.send_interactive_input(command_text)
            return

        if self.client_mode_active:
            self.send_client_input(command_text)
            return

        commands = self.command_sequence_from_text(command_text, include_prefix=True)
        if not commands:
            return

        history_entry = command_text
        self.add_command_history(history_entry)
        self.update_restore_command_from_command(history_entry)
        self.history_index = -1
        self.current_command = ""

        for command in commands:
            command = self.translate_cross_platform_command(command)
            ollama_model = self.parse_ollama_run_model(command)
            if ollama_model:
                self.start_ollama_prompt_mode(ollama_model)
                continue
            direct_client = self.parse_direct_client_command(command)
            if direct_client:
                self.start_direct_client_process(direct_client)
                continue
            if command.lower() in ("cls", "clear"):
                self.output_area.clear()
                self.update_input_prompt_label()
            elif self.process.state() != QProcess.ProcessState.Running:
                self.output_area.append(
                    f"Shell ist nicht aktiv: {self.process.errorString() or 'Prozess wurde beendet.'}"
                )
                break
            else:
                self.write_shell_command(command)
                prompt_text = self.extract_interactive_prompt_from_command(command)
                if prompt_text:
                    self.activate_interaction_prompt_mode(prompt_text, clear_input=True)
                client_name = "" if ("\n" in command or "\r" in command) else self.detect_client_mode_name(command)
                if client_name:
                    self.set_client_mode(True, client_name)
        self.input_line.clear()

    def _decode_process_output(self, raw) -> str:
        data = bytes(raw)
        # Linux/macOS-PTYs liefern normalerweise UTF-8. Wenn zuerst cp850
        # versucht wird, wird z.B. "für" als Mojibake dekodiert und lokalisierte
        # Passwort-Prompts werden schlechter erkannt. Unter Windows bleibt die
        # bisherige Codepage-Reihenfolge erhalten.
        if sys.platform == "win32":
            encodings = ("cp850", "mbcs", "cp1252", "utf-8", "latin-1")
        else:
            encodings = ("utf-8", "latin-1", "cp850", "cp1252")
        for encoding in encodings:
            try:
                return data.decode(encoding)
            except (UnicodeDecodeError, LookupError):
                continue
        return data.decode("utf-8", errors="replace")

    def process_uses_pty_engine(self):
        return str(getattr(getattr(self, "process", None), "_shelldeck_engine", "") or "").lower() == "pty"

    def decoded_terminal_output(self, raw):
        text = self._decode_process_output(raw)
        if self.process_uses_pty_engine():
            cleaner = getattr(self.window, "clean_terminal_control_sequences", None)
            if callable(cleaner):
                text = cleaner(text)
            else:
                text = self.window.clean_output_text(text)
            text = self.suppress_pending_pty_command_echo(text)
        text = self.suppress_pending_interactive_response_echo(text)
        return self.consume_shell_context_markers(text)

    def normalize_response_echo_text(self, value):
        return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()

    def remember_pending_interactive_response_echo(self, answer):
        # Viele Shells/Programme echoen die Antwort direkt wieder. Im
        # Antwortmodus unterdrücken wir höchstens die erste unmittelbar
        # folgende Echo-Zeile, damit echte Programmausgaben sichtbar bleiben.
        text = self.normalize_response_echo_text(answer)
        pending = list(getattr(self, "_pending_interactive_response_echoes", []) or [])
        pending.append({"answer": text, "ttl": 4})
        self._pending_interactive_response_echoes = pending[-4:]

    def line_looks_like_interactive_response_echo(self, line, answer):
        raw_line = self.normalize_response_echo_text(line)
        raw_answer = self.normalize_response_echo_text(answer)
        if raw_answer == "":
            return raw_line == ""
        if raw_line != raw_answer:
            return False
        if "\n" in raw_answer or len(raw_answer) > 120:
            return False
        return True

    def suppress_pending_interactive_response_echo(self, text):
        pending = list(getattr(self, "_pending_interactive_response_echoes", []) or [])
        if not pending:
            return text

        kept_lines = []
        removed_index = None
        for line in str(text or "").splitlines(True):
            line_body = line.rstrip("\r\n")
            if removed_index is None:
                for index, item in enumerate(pending):
                    if self.line_looks_like_interactive_response_echo(line_body, item.get("answer", "")):
                        removed_index = index
                        break
                if removed_index is not None:
                    continue
            kept_lines.append(line)

        next_pending = []
        for index, item in enumerate(pending):
            if index == removed_index:
                continue
            ttl = int(item.get("ttl", 0)) - 1
            if ttl > 0:
                item["ttl"] = ttl
                next_pending.append(item)
        self._pending_interactive_response_echoes = next_pending
        return "".join(kept_lines)

    def remember_pending_pty_command_echo(self, command):
        text = str(command or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return
        pending = getattr(self, "_pending_pty_command_echoes", [])
        pending.append({"command": text, "ttl": 8})
        self._pending_pty_command_echoes = pending[-8:]

    def compact_echo_text(self, value):
        text = re.sub(r"\s+", "", str(value or "").lower())
        text = re.sub(r"[^a-z0-9äöüß_./:;\\-]+", "", text)
        collapsed = []
        previous = ""
        for char in text:
            if char == previous and char.isalpha():
                continue
            collapsed.append(char)
            previous = char
        return "".join(collapsed)

    def line_looks_like_pending_pty_echo(self, line, command):
        raw_line = str(line or "").strip()
        raw_command = str(command or "").strip()
        if not raw_line or not raw_command:
            return False

        # A finished PowerShell prompt should remain visible. Only suppress the
        # noisy PSReadLine redraw fragments of the command itself.
        if re.search(r"(?:^|\s)PS\s+[^>]+>\s*$", raw_line):
            return False

        line_key = self.compact_echo_text(raw_line)
        command_key = self.compact_echo_text(raw_command)
        if len(command_key) < 3 or len(line_key) < 3:
            return False

        if command_key.startswith(line_key) or line_key.startswith(command_key):
            return True

        prefix = command_key[: min(18, len(command_key))]
        if len(prefix) >= 6 and line_key.startswith(prefix) and len(line_key) <= max(len(command_key) * 3, 40):
            return True

        # Long PowerShell/PSReadLine redraws can contain several partial copies
        # of the command in one physical output chunk. If the line starts like
        # the command and repeatedly contains its first token, treat it as echo.
        first_token = self.compact_echo_text(raw_command.split(None, 1)[0])
        if first_token and line_key.startswith(first_token) and line_key.count(first_token) >= 2:
            return True

        return False

    def suppress_pending_pty_command_echo(self, text):
        pending = list(getattr(self, "_pending_pty_command_echoes", []) or [])
        if not pending:
            return text

        kept_lines = []
        removed_any = False
        for line in str(text or "").splitlines(True):
            line_body = line.rstrip("\n")
            if any(self.line_looks_like_pending_pty_echo(line_body, item.get("command", "")) for item in pending):
                removed_any = True
                continue
            kept_lines.append(line)

        next_pending = []
        for item in pending:
            ttl = int(item.get("ttl", 0)) - 1
            if ttl > 0 and not removed_any:
                item["ttl"] = ttl
                next_pending.append(item)
        self._pending_pty_command_echoes = next_pending
        return "".join(kept_lines)

    def handle_stdout(self):
        data = self.decoded_terminal_output(self.process.readAllStandardOutput())
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.insertPlainText(data)
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.ensureCursorVisible()
        self.handle_possible_password_prompt(data)
        self.handle_possible_interactive_prompt(data)
        self.refresh_password_prompt_state_after_output()
        self.refresh_interaction_prompt_state_after_output()
        QTimer.singleShot(120, self.update_input_prompt_label)

    def handle_stderr(self):
        data = self.decoded_terminal_output(self.process.readAllStandardError())
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.setTextColor(QColor(self.window.terminal_color("stderr", "#FCA5A5")))
        self.output_area.insertPlainText(data)
        self.output_area.setTextColor(QColor(self.window.terminal_color("stdout", "#FFFFFF")))
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.ensureCursorVisible()
        self.handle_possible_password_prompt(data)
        self.handle_possible_interactive_prompt(data)
        self.refresh_password_prompt_state_after_output()
        self.refresh_interaction_prompt_state_after_output()
        QTimer.singleShot(120, self.update_input_prompt_label)

    def handle_finished(self, exit_code, exit_status):
        self.set_client_mode(False)
        self.output_area.append(f"\nProcess finished with exit code {exit_code}")

    def handle_process_error(self, error):
        self.set_client_mode(False)
        self.output_area.append(f"\nShell konnte nicht gestartet werden: {self.process.errorString()}")

    def set_terminal_font(self, font):
        self.output_area.setFont(font)
        self.input_line.setFont(font)
        if hasattr(self, "input_prompt_label"):
            self.input_prompt_label.setFont(font)

    def apply_theme(self):
        theme = self.window.active_theme()
        background = self.window.normalize_hex_color(theme.get("background"), "#181818")
        foreground = self.window.normalize_hex_color(theme.get("foreground"), "#FFFFFF")
        input_background = self.window.normalize_hex_color(theme.get("input_background"), background)
        accent = self.window.normalize_hex_color(theme.get("accent"), "#339CFF")
        terminal_colors = self.window.terminal_colors()
        stdout_color = self.window.normalize_hex_color(terminal_colors.get("stdout"), foreground)
        input_text_color = self.window.normalize_hex_color(terminal_colors.get("input_text"), foreground)
        selection_color = self.window.normalize_hex_color(terminal_colors.get("selection"), "#2D5F93")
        try:
            background_opacity = max(0, min(100, int(theme.get("background_opacity", 100))))
        except (TypeError, ValueError):
            background_opacity = 100
        try:
            contrast = max(0, min(100, int(theme.get("contrast", 60))))
        except (TypeError, ValueError):
            contrast = 60

        background_rgba = self.window.rgba_color(background, background_opacity)
        input_background_rgba = self.window.rgba_color(input_background, background_opacity)

        border_width = 1 if contrast < 85 else 2
        radius = 8 if bool(theme.get("transparent_sidebar", True)) else 2
        border_color = self.window.readable_border_color(background)
        input_border_color = self.window.readable_border_color(input_background)
        translucent = background_opacity < 100

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, translucent)
        self.setStyleSheet("background: transparent;" if translucent else "")
        self.output_area.setStyleSheet(
            "QTextEdit {"
            f" background-color: {background_rgba};"
            f" color: {stdout_color};"
            f" border: {border_width}px solid {border_color};"
            f" border-radius: {radius}px;"
            " padding: 8px;"
            f" selection-background-color: {selection_color};"
            "}"
            "QTextEdit:focus {"
            f" border: {border_width}px solid {accent};"
            "}"
        )
        self.output_area.setTextColor(QColor(stdout_color))
        self.highlighter.set_terminal_colors(terminal_colors)
        self.input_line.setStyleSheet(
            "QPlainTextEdit {"
            f" background-color: {input_background_rgba};"
            f" color: {input_text_color};"
            f" border: {border_width}px solid {input_border_color};"
            f" border-radius: {radius}px;"
            " padding: 6px;"
            f" selection-background-color: {selection_color};"
            "}"
            "QPlainTextEdit:focus {"
            f" border: {border_width}px solid {accent};"
            "}"
        )
        if hasattr(self, "input_prompt_label"):
            self.input_prompt_label.setStyleSheet(
                "QLineEdit {"
                f" background-color: {input_background_rgba};"
                f" color: {input_text_color};"
                f" border: {border_width}px solid {input_border_color};"
                f" border-radius: {radius}px;"
                " padding: 5px 8px;"
                f" selection-background-color: {selection_color};"
                "}"
            )
        self.execute_button.setStyleSheet(
            "QPushButton {"
            f" background-color: {accent};"
            " color: white;"
            " border: none;"
            " border-radius: 6px;"
            " padding: 7px 12px;"
            "}"
            "QPushButton:hover {"
            " background-color: #4AA8FF;"
            "}"
            "QPushButton:pressed {"
            " background-color: #1E7FCC;"
            "}"
        )


class DetachedTerminalWindow(QMainWindow):
    def __init__(self, owner, title="Entkoppelte Tabs", window_id=""):
        super().__init__(owner)
        self.owner = owner
        self.window_id = str(window_id or "").strip() or owner.next_detached_window_id()
        self._closing_from_owner = False
        self.setWindowTitle(f"{APP_NAME} - {title}")
        self.resize(900, 600)
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tab_widget = owner.create_terminal_tab_widget(detached_window=self)
        layout.addWidget(self.tab_widget)

    def add_tab(self, tab, label=None):
        label = label or getattr(tab, "custom_title", "") or getattr(tab, "title", "Terminal") or "Terminal"
        index = self.tab_widget.addTab(tab, label)
        self.tab_widget.setCurrentIndex(index)
        self.owner.active_tab_widget = self.tab_widget
        self.owner.update_tab_title(tab)
        self.owner.apply_color_scheme()
        self.show()
        self.raise_()
        self.activateWindow()
        return index

    def is_empty(self):
        return self.tab_widget.count() <= 0

    def reattach_all_tabs(self):
        while self.tab_widget.count() > 0:
            tab = self.tab_widget.widget(0)
            label = self.tab_widget.tabText(0)
            self.tab_widget.removeTab(0)
            self.owner.attach_existing_tab_to_main(tab, label=label)

    def closeEvent(self, event):
        if getattr(self, "_closing_from_owner", False):
            event.accept()
            return
        self.reattach_all_tabs()
        self.owner.unregister_detached_window(self)
        self.owner.save_settings()
        event.accept()



class TerminalWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.history = []
        self.default_command = ""
        self.color_scheme_name = "Dunkel"
        self.theme_mode = "dark"
        self.window_opacity = 100
        self.theme_config = self.default_theme_config()
        self.shell_type = self.default_shell_type()
        self.terminal_engine = "qprocess"
        self.max_history_size = 1000
        self.terminal_font = QFont("Courier New", 10)
        self.saved_tabs = []
        self.saved_paths = []
        self.tab_profiles = []
        self.workspaces = []
        self.default_start_directory = ""
        self.selected_ollama_model = ""
        self.ai_features_enabled = False
        self.pre_command_visible = True
        self.pre_command_enabled = False
        self.pre_command_text = ""
        self.pre_command_history = []
        self.detached_windows = []
        self.history_file = Path.home() / ".visual_edit_terminal_history"
        self.settings_file = Path.home() / ".visual_edit_terminal_settings.json"
        workspace_config_base = Path(os.environ.get("APPDATA") or Path.home()) / "ShellDeckTerminal"
        self.workspace_store_file = workspace_config_base / "workspaces.json"
        self.pre_command_store_file = workspace_config_base / "pre_command.json"
        self.terminal_engine_store_file = workspace_config_base / "terminal_engine.json"
        self.theme_store_file = workspace_config_base / "theme.json"
        self.load_history()

        menubar = self.menuBar()
        self.file_menu = menubar.addMenu("&Datei")

        new_tab_action = QAction("Neuer Tab", self)
        new_tab_action.setShortcut("Ctrl+T")
        new_tab_action.triggered.connect(self.new_tab)
        self.file_menu.addAction(new_tab_action)

        self.new_backend_tab_menu = self.file_menu.addMenu("Neuer Tab mit Backend")
        self.new_backend_tab_menu.aboutToShow.connect(self.rebuild_new_backend_tab_menu)

        attach_file_action = QAction("Datei an aktuellen Prompt anhängen", self)
        attach_file_action.triggered.connect(self.attach_file_to_current_prompt)
        self.file_menu.addAction(attach_file_action)

        close_tab_action = QAction("Aktuellen Tab schließen", self)
        close_tab_action.setShortcut("Ctrl+W")
        close_tab_action.triggered.connect(self.close_current_tab)
        self.file_menu.addAction(close_tab_action)

        duplicate_tab_action = QAction("Tab duplizieren", self)
        duplicate_tab_action.setShortcut("Ctrl+D")
        duplicate_tab_action.triggered.connect(self.duplicate_current_tab)
        self.file_menu.addAction(duplicate_tab_action)

        rename_tab_action = QAction("Tab umbenennen", self)
        rename_tab_action.setShortcut("F2")
        rename_tab_action.triggered.connect(self.rename_current_tab)
        self.file_menu.addAction(rename_tab_action)
        self.file_menu.addSeparator()

        exit_action = QAction("&Beenden", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.file_menu.addAction(exit_action)

        self.paths_menu = menubar.addMenu("&Pfade")

        self.profiles_menu = menubar.addMenu("&Profile")

        self.workspaces_menu = menubar.addMenu("&Workspaces")

        self.view_menu = menubar.addMenu("&Ansicht")

        self.pre_command_bar_action = QAction("Vorbefehl-Leiste anzeigen", self)
        self.pre_command_bar_action.setCheckable(True)
        self.pre_command_bar_action.setChecked(True)
        self.pre_command_bar_action.triggered.connect(self.set_pre_command_bar_visible)
        self.view_menu.addAction(self.pre_command_bar_action)
        self.view_menu.addSeparator()

        self.view_single_action = QAction("Einzelansicht", self)
        self.view_single_action.setCheckable(True)
        self.view_single_action.triggered.connect(lambda checked=False: self.set_view_layout_mode("single"))
        self.view_menu.addAction(self.view_single_action)

        self.split_view_action = QAction("2er horizontal: links | rechts", self)
        self.split_view_action.setCheckable(True)
        self.split_view_action.triggered.connect(lambda checked=False: self.set_view_layout_mode("horizontal"))
        self.view_menu.addAction(self.split_view_action)

        self.view_vertical_action = QAction("2er vertikal: oben / unten", self)
        self.view_vertical_action.setCheckable(True)
        self.view_vertical_action.triggered.connect(lambda checked=False: self.set_view_layout_mode("vertical"))
        self.view_menu.addAction(self.view_vertical_action)

        self.view_quad_action = QAction("4er Raster", self)
        self.view_quad_action.setCheckable(True)
        self.view_quad_action.triggered.connect(lambda checked=False: self.set_view_layout_mode("quad"))
        self.view_menu.addAction(self.view_quad_action)

        self.view_menu.addSeparator()
        self.move_view_menu = self.view_menu.addMenu("Aktuellen Tab verschieben nach")
        self.rebuild_move_view_menu()

        self.move_to_other_view_action = QAction("Aktuellen Tab in nächste Ansicht verschieben", self)
        self.move_to_other_view_action.triggered.connect(self.move_current_tab_to_other_view)
        self.view_menu.addAction(self.move_to_other_view_action)

        self.view_menu.addSeparator()
        self.detach_current_tab_action = QAction("Aktuellen Tab entkoppeln", self)
        self.detach_current_tab_action.triggered.connect(self.detach_current_tab)
        self.view_menu.addAction(self.detach_current_tab_action)

        self.reattach_current_tab_action = QAction("Aktuellen Tab wieder ins Hauptfenster koppeln", self)
        self.reattach_current_tab_action.triggered.connect(self.reattach_current_tab)
        self.view_menu.addAction(self.reattach_current_tab_action)

        settings_menu = menubar.addMenu("&Einstellungen")

        font_action = QAction("Schriftart", self)
        font_action.triggered.connect(self.show_font_dialog)
        settings_menu.addAction(font_action)

        color_action = QAction("Farbschema", self)
        color_action.triggered.connect(self.show_color_dialog)
        settings_menu.addAction(color_action)

        theme_action = QAction("Design anpassen", self)
        theme_action.triggered.connect(self.show_theme_dialog)
        settings_menu.addAction(theme_action)

        reset_theme_action = QAction("Design auf Standard zurücksetzen", self)
        reset_theme_action.triggered.connect(self.reset_theme_defaults)
        settings_menu.addAction(reset_theme_action)

        cmd_action = QAction("Standardbefehl", self)
        cmd_action.triggered.connect(self.show_command_dialog)
        settings_menu.addAction(cmd_action)

        history_action = QAction("History-Größe", self)
        history_action.triggered.connect(self.show_history_dialog)
        settings_menu.addAction(history_action)

        shell_action = QAction("Shell-Backend", self)
        shell_action.triggered.connect(self.select_shell)
        settings_menu.addAction(shell_action)

        terminal_engine_action = QAction("Terminal-Engine", self)
        terminal_engine_action.triggered.connect(self.select_terminal_engine)
        settings_menu.addAction(terminal_engine_action)

        settings_menu.addSeparator()

        self.ai_features_action = QAction("KI-Menü / Ollama aktivieren", self)
        self.ai_features_action.setCheckable(True)
        self.ai_features_action.setChecked(False)
        self.ai_features_action.triggered.connect(self.set_ai_features_enabled)
        settings_menu.addAction(self.ai_features_action)

        self.ai_menu = menubar.addMenu("&KI")

        new_ollama_tab_action = QAction("Neuer Ollama-Chat", self)
        new_ollama_tab_action.triggered.connect(self.new_ollama_chat_tab)
        self.ai_menu.addAction(new_ollama_tab_action)

        select_ollama_model_action = QAction("Ollama-Modell wählen", self)
        select_ollama_model_action.triggered.connect(self.select_ollama_model)
        self.ai_menu.addAction(select_ollama_model_action)

        clear_ollama_chat_action = QAction("Ollama-Gespräch löschen", self)
        clear_ollama_chat_action.triggered.connect(self.clear_current_ollama_chat)
        self.ai_menu.addAction(clear_ollama_chat_action)

        clear_ollama_context_action = QAction("Ollama-Kontext löschen", self)
        clear_ollama_context_action.triggered.connect(self.clear_current_ollama_context)
        self.ai_menu.addAction(clear_ollama_context_action)

        system_prompt_action = QAction("Ollama-Systemprompt setzen", self)
        system_prompt_action.triggered.connect(self.set_current_ollama_system_prompt)
        self.ai_menu.addAction(system_prompt_action)

        stop_ollama_action = QAction("Ollama-Antwort stoppen", self)
        stop_ollama_action.triggered.connect(self.stop_current_ollama_response)
        self.ai_menu.addAction(stop_ollama_action)

        save_ollama_markdown_action = QAction("Ollama-Chat als Markdown speichern", self)
        save_ollama_markdown_action.triggered.connect(self.save_current_ollama_chat_markdown)
        self.ai_menu.addAction(save_ollama_markdown_action)

        save_chat_action = QAction("Aktuelle Ausgabe speichern", self)
        save_chat_action.triggered.connect(self.save_current_output)
        self.ai_menu.addAction(save_chat_action)

        help_menu = menubar.addMenu("&Hilfe")

        help_action = QAction("Funktionen und Tastenkürzel", self)
        help_action.setShortcut("F1")
        help_action.triggered.connect(self.show_help_dialog)
        help_menu.addAction(help_action)

        about_action = QAction("Über", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        central_widget = QWidget()
        self.central_widget = central_widget
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        self.pre_command_bar = QWidget(menubar)
        self.pre_command_bar.setObjectName("preCommandCornerWidget")
        pre_command_layout = QHBoxLayout(self.pre_command_bar)
        pre_command_layout.setContentsMargins(8, 0, 8, 0)
        pre_command_layout.setSpacing(6)

        self.terminal_engine_combo = QComboBox(self.pre_command_bar)
        self.terminal_engine_combo.setToolTip(
            "Terminal-Engine für neu gestartete Tabs. "
            "QProcess bleibt Standard; PTY/ConPTY ist experimentell."
        )
        self.terminal_engine_combo.addItem("Standard QProcess", "qprocess")
        self.terminal_engine_combo.addItem("PTY/ConPTY experimentell", "pty")
        self.terminal_engine_combo.setFixedWidth(210)
        self.terminal_engine_combo.currentIndexChanged.connect(self.set_terminal_engine_from_combo)
        pre_command_layout.addWidget(self.terminal_engine_combo)

        self.pre_command_enabled_checkbox = QCheckBox("Vorbefehl aktiv", self.pre_command_bar)
        self.pre_command_enabled_checkbox.setToolTip(
            "Führt den Vorbefehl vor normalen Eingaben aus dem unteren Eingabefeld aus."
        )
        self.pre_command_enabled_checkbox.toggled.connect(self.set_pre_command_enabled)
        pre_command_layout.addWidget(self.pre_command_enabled_checkbox)

        self.pre_command_input = QComboBox(self.pre_command_bar)
        self.pre_command_input.setEditable(True)
        self.pre_command_input.setMinimumWidth(320)
        self.pre_command_input.setFixedWidth(320)
        self.pre_command_input.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.pre_command_input.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.pre_command_input.setToolTip(
            "Mehrere Vorbefehle können mit Semikolon getrennt werden. "
            "Die letzten Vorbefehle bleiben gespeichert."
        )
        if self.pre_command_input.lineEdit() is not None:
            self.pre_command_input.lineEdit().setPlaceholderText("Vorbefehl(e), z.B. cls oder cd ..; dir")
            self.pre_command_input.lineEdit().editingFinished.connect(self.remember_current_pre_command)
        self.pre_command_input.editTextChanged.connect(self.set_pre_command_text)
        self.pre_command_input.currentTextChanged.connect(self.set_pre_command_text)
        pre_command_layout.addWidget(self.pre_command_input, 0)
        menubar.setCornerWidget(self.pre_command_bar, Qt.Corner.TopRightCorner)

        self.view_container = QWidget()
        self.view_grid = QGridLayout(self.view_container)
        self.view_grid.setContentsMargins(0, 0, 0, 0)
        self.view_grid.setSpacing(4)
        self.tab_widget = self.create_terminal_tab_widget()
        self.secondary_tab_widget = self.create_terminal_tab_widget()
        self.tertiary_tab_widget = self.create_terminal_tab_widget()
        self.quaternary_tab_widget = self.create_terminal_tab_widget()
        self.active_tab_widget = self.tab_widget
        self.view_layout_mode = "single"
        self.split_view_enabled = False
        layout.addWidget(self.view_container)

        self.load_settings()
        self.update_terminal_engine_ui()
        self.update_pre_command_ui()
        self.apply_view_layout(move_tabs=False)
        self.update_ai_menu_visibility()
        self.rebuild_saved_paths_menu()
        self.rebuild_profiles_menu()
        self.rebuild_workspaces_menu()
        self.apply_color_scheme()
        self.restore_tabs_from_settings()

        self.shortcut_stop = QShortcut("Ctrl+C", self)
        self.shortcut_stop.activated.connect(self.interrupt_current_command)

        self.shortcut_search = QShortcut("Ctrl+F", self)
        self.shortcut_search.activated.connect(self.search_current_output)

        self.shortcut_find_next = QShortcut("F3", self)
        self.shortcut_find_next.activated.connect(self.find_next_current_output)

        self.shortcut_find_previous = QShortcut("Shift+F3", self)
        self.shortcut_find_previous.activated.connect(self.find_previous_current_output)

        self.shortcut_command_palette = QShortcut("Ctrl+Shift+P", self)
        self.shortcut_command_palette.activated.connect(self.show_command_palette)

    def normalize_color_scheme_name(self, value):
        text = str(value or "Dunkel").strip()
        aliases = {
            "system": "System",
            "dunkel": "Dunkel",
            "dark": "Dunkel",
            "hell": "Hell",
            "light": "Hell",
            "hoher kontrast": "Hoher Kontrast",
            "kontrast": "Hoher Kontrast",
            "high contrast": "Hoher Kontrast",
        }
        return aliases.get(text.lower(), text if text in {"System", "Dunkel", "Hell", "Hoher Kontrast"} else "Dunkel")

    def theme_settings_snapshot(self):
        return {
            "color_scheme_name": self.normalize_color_scheme_name(getattr(self, "color_scheme_name", "Dunkel")),
            "theme_mode": str(getattr(self, "theme_mode", "dark") or "dark").lower().strip(),
        }

    def apply_theme_settings_mapping(self, mapping):
        if not isinstance(mapping, dict):
            return
        if "color_scheme_name" in mapping:
            self.color_scheme_name = self.normalize_color_scheme_name(mapping.get("color_scheme_name"))
        mode = str(mapping.get("theme_mode", "") or "").lower().strip()
        if mode in {"light", "dark", "system"}:
            self.theme_mode = mode
        else:
            scheme = self.normalize_color_scheme_name(getattr(self, "color_scheme_name", "Dunkel"))
            if scheme == "System":
                self.theme_mode = "system"
            elif scheme == "Hell":
                self.theme_mode = "light"
            else:
                self.theme_mode = "dark"

    def load_theme_persistent_settings(self):
        store_file = getattr(self, "theme_store_file", None)
        if store_file is None or not Path(store_file).exists():
            return {}
        try:
            data = json.loads(Path(store_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_theme_persistent_settings(self, settings=None):
        store_file = getattr(self, "theme_store_file", None)
        if store_file is None:
            return False
        payload = settings if isinstance(settings, dict) else self.theme_settings_snapshot()
        try:
            Path(store_file).parent.mkdir(parents=True, exist_ok=True)
            tmp_file = Path(store_file).with_suffix(Path(store_file).suffix + ".tmp")
            tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
            tmp_file.replace(Path(store_file))
            return True
        except OSError:
            return False

    def system_theme_key(self):
        """Return light/dark from the OS setting when possible."""
        try:
            color_scheme = QApplication.styleHints().colorScheme()
            if color_scheme == Qt.ColorScheme.Dark:
                return "dark"
            if color_scheme == Qt.ColorScheme.Light:
                return "light"
        except Exception:
            pass

        if sys.platform == "win32":
            try:
                import winreg
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                ) as key:
                    value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                    return "light" if int(value) else "dark"
            except Exception:
                pass
        else:
            for command in (
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                ["gsettings", "get", "org.gnome.desktop.interface", "gtk-theme"],
            ):
                try:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=1,
                        encoding="utf-8",
                        errors="replace",
                    )
                    value = str(result.stdout or "").strip().lower()
                    if "dark" in value:
                        return "dark"
                    if "light" in value:
                        return "light"
                except Exception:
                    pass

        try:
            palette_color = QApplication.palette().color(QPalette.ColorRole.Window)
            brightness = (
                palette_color.red() * 0.299
                + palette_color.green() * 0.587
                + palette_color.blue() * 0.114
            )
            return "dark" if brightness < 128 else "light"
        except Exception:
            return "dark"

    def normalize_terminal_engine(self, engine):
        value = str(engine or "qprocess").lower().strip()
        return value if value in {"qprocess", "pty"} else "qprocess"

    def terminal_engine_settings_snapshot(self):
        return {"terminal_engine": self.normalize_terminal_engine(getattr(self, "terminal_engine", "qprocess"))}

    def load_terminal_engine_persistent_settings(self):
        store_file = getattr(self, "terminal_engine_store_file", None)
        if store_file is None or not Path(store_file).exists():
            return {}
        try:
            data = json.loads(Path(store_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_terminal_engine_persistent_settings(self, settings=None):
        store_file = getattr(self, "terminal_engine_store_file", None)
        if store_file is None:
            return False
        payload = settings if isinstance(settings, dict) else self.terminal_engine_settings_snapshot()
        try:
            Path(store_file).parent.mkdir(parents=True, exist_ok=True)
            tmp_file = Path(store_file).with_suffix(Path(store_file).suffix + ".tmp")
            tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
            tmp_file.replace(Path(store_file))
            return True
        except OSError:
            return False

    def apply_terminal_engine_settings_mapping(self, mapping):
        if not isinstance(mapping, dict):
            return
        self.terminal_engine = self.normalize_terminal_engine(
            mapping.get("terminal_engine", getattr(self, "terminal_engine", "qprocess"))
        )

    def terminal_engine_combo_value(self):
        combo = getattr(self, "terminal_engine_combo", None)
        if combo is None:
            return self.normalize_terminal_engine(getattr(self, "terminal_engine", "qprocess"))
        try:
            data = combo.currentData()
            if data:
                return self.normalize_terminal_engine(data)
            return self.normalize_terminal_engine(combo.currentText())
        except RuntimeError:
            return self.normalize_terminal_engine(getattr(self, "terminal_engine", "qprocess"))

    def set_terminal_engine(self, engine, *, show_message=True, save=True, apply_to_current_tab=True):
        new_engine = self.normalize_terminal_engine(engine)
        if new_engine == "pty":
            message = PtyTerminalProcess.availability_message()
            if message and show_message:
                self.show_status(f"PTY/ConPTY gewählt, aber noch nicht verfügbar: {message}")
        current_tab = self.current_terminal() if apply_to_current_tab else None
        old_display_engine = self.current_terminal_engine()
        self.terminal_engine = new_engine
        if isinstance(current_tab, TerminalTab):
            current_tab.set_terminal_engine(new_engine, restart=True)
        self.update_terminal_engine_ui()
        if save:
            self.save_terminal_engine_persistent_settings()
            self.save_settings()
        if show_message:
            changed = new_engine != old_display_engine
            suffix = "Der aktuelle Tab wurde mit dieser Engine neu gestartet." if isinstance(current_tab, TerminalTab) else "Die Änderung gilt für neu gestartete Tabs."
            if changed or save:
                self.show_status(f"Terminal-Engine: {self.terminal_engine_label(new_engine)}. {suffix}")

    def set_terminal_engine_from_combo(self, index=0):
        self.set_terminal_engine(self.terminal_engine_combo_value(), show_message=True, save=True)

    def update_terminal_engine_ui(self):
        combo = getattr(self, "terminal_engine_combo", None)
        if combo is None:
            return
        engine = self.current_terminal_engine()
        combo.blockSignals(True)
        for index in range(combo.count()):
            if self.normalize_terminal_engine(combo.itemData(index)) == engine:
                combo.setCurrentIndex(index)
                break
        combo.blockSignals(False)
        combo.setToolTip(
            f"Terminal-Engine des aktuellen Tabs: {self.terminal_engine_label(engine)}. "
            "Eine Änderung startet den aktuellen Tab mit der gewählten Engine neu und wird als Vorgabe gespeichert."
        )

    def normalize_pre_command_text(self, text):
        return str(text or "").strip()

    def current_pre_command_widget_text(self):
        widget = getattr(self, "pre_command_input", None)
        if widget is None:
            return self.normalize_pre_command_text(getattr(self, "pre_command_text", ""))
        try:
            line_edit = widget.lineEdit() if hasattr(widget, "lineEdit") else None
            if line_edit is not None:
                return self.normalize_pre_command_text(line_edit.text())
            if hasattr(widget, "currentText"):
                return self.normalize_pre_command_text(widget.currentText())
            if hasattr(widget, "text"):
                return self.normalize_pre_command_text(widget.text())
        except RuntimeError:
            pass
        return self.normalize_pre_command_text(getattr(self, "pre_command_text", ""))

    def pre_command_settings_snapshot(self):
        return {
            "pre_command_visible": bool(getattr(self, "pre_command_visible", True)),
            "pre_command_enabled": bool(getattr(self, "pre_command_enabled", False)),
            "pre_command_text": self.normalize_pre_command_text(getattr(self, "pre_command_text", "")),
            "pre_command_history": self.normalize_pre_command_history(getattr(self, "pre_command_history", [])),
        }

    def apply_pre_command_settings_mapping(self, values):
        if not isinstance(values, dict):
            return
        if "pre_command_visible" in values:
            self.pre_command_visible = bool(values.get("pre_command_visible"))
        if "pre_command_enabled" in values:
            self.pre_command_enabled = bool(values.get("pre_command_enabled"))
        if "pre_command_text" in values:
            self.pre_command_text = self.normalize_pre_command_text(values.get("pre_command_text", ""))
        if "pre_command_history" in values:
            self.pre_command_history = self.normalize_pre_command_history(values.get("pre_command_history", []))

    def load_pre_command_persistent_settings(self):
        path = getattr(self, "pre_command_store_file", None)
        if path is None or not Path(path).exists():
            return {}
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def save_pre_command_persistent_settings(self, snapshot=None):
        data = snapshot if isinstance(snapshot, dict) else self.pre_command_settings_snapshot()
        path = getattr(self, "pre_command_store_file", None)
        if path is None:
            return False
        try:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            tmp_file = Path(path).with_suffix(Path(path).suffix + ".tmp")
            tmp_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            tmp_file.replace(Path(path))
            return True
        except OSError:
            return False

    def sync_pre_command_state_from_ui(self):
        """Copy the visible Vorbefehl controls into the persistent model.

        The menu action is the source of truth for visibility, because a corner
        widget can report hidden while the main window is closing. The editor's
        lineEdit() is the source of truth for the text, because QComboBox can
        keep an unfinished edit only in its internal editor until focus changes.
        """
        action = getattr(self, "pre_command_bar_action", None)
        bar = getattr(self, "pre_command_bar", None)
        checkbox = getattr(self, "pre_command_enabled_checkbox", None)

        if action is not None:
            try:
                self.pre_command_visible = bool(action.isChecked())
            except RuntimeError:
                pass
        elif bar is not None:
            try:
                self.pre_command_visible = bool(bar.isVisible())
            except RuntimeError:
                pass

        if checkbox is not None:
            try:
                self.pre_command_enabled = bool(checkbox.isChecked())
            except RuntimeError:
                pass

        current_text = self.current_pre_command_widget_text()
        self.pre_command_text = current_text
        if current_text:
            self.pre_command_history = self.normalize_pre_command_history([
                current_text,
                *list(getattr(self, "pre_command_history", [])),
            ])
        else:
            self.pre_command_history = self.normalize_pre_command_history(
                getattr(self, "pre_command_history", [])
            )

    def normalize_pre_command_history(self, values):
        result = []
        if isinstance(values, (list, tuple)):
            candidates = values
        else:
            candidates = []
        current = self.normalize_pre_command_text(getattr(self, "pre_command_text", ""))
        if current:
            candidates = [current, *list(candidates)]
        for value in candidates:
            text = self.normalize_pre_command_text(value)
            if text and text not in result:
                result.append(text)
        return result[:20]

    def remember_pre_command_text(self, text=None):
        normalized = self.current_pre_command_widget_text() if text is None else self.normalize_pre_command_text(text)
        if not normalized:
            return
        self.pre_command_text = normalized
        self.pre_command_history = self.normalize_pre_command_history([
            normalized,
            *list(getattr(self, "pre_command_history", [])),
        ])
        self.update_pre_command_ui()
        self.save_settings()

    def remember_current_pre_command(self):
        self.remember_pre_command_text()

    def active_pre_command_text(self):
        if not bool(getattr(self, "pre_command_visible", True)):
            return ""
        if not bool(getattr(self, "pre_command_enabled", False)):
            return ""
        return self.normalize_pre_command_text(getattr(self, "pre_command_text", ""))

    def set_pre_command_text(self, text):
        normalized = self.normalize_pre_command_text(text)
        if normalized == getattr(self, "pre_command_text", ""):
            return
        self.pre_command_text = normalized
        self.pre_command_history = self.normalize_pre_command_history(getattr(self, "pre_command_history", []))
        self.save_settings()

    def set_pre_command_enabled(self, enabled):
        value = bool(enabled)
        if value == bool(getattr(self, "pre_command_enabled", False)):
            return
        self.pre_command_enabled = value
        self.save_settings()
        if value and not self.active_pre_command_text():
            self.show_status("Vorbefehl ist aktiv, aber noch leer")
        elif value:
            self.show_status("Vorbefehl aktiviert")
        else:
            self.show_status("Vorbefehl deaktiviert")

    def set_pre_command_bar_visible(self, visible):
        self.pre_command_visible = bool(visible)
        self.update_pre_command_ui()
        self.save_settings()
        self.show_status("Vorbefehl-Leiste eingeblendet" if self.pre_command_visible else "Vorbefehl-Leiste ausgeblendet")

    def update_pre_command_ui(self):
        bar = getattr(self, "pre_command_bar", None)
        if bar is not None:
            # Die Engine-Anzeige sitzt in derselben rechten Menüleisten-Gruppe
            # und bleibt immer sichtbar. Die Ansicht-Option blendet nur die
            # Vorbefehl-Bedienelemente aus.
            bar.setVisible(True)
        visible = bool(getattr(self, "pre_command_visible", True))
        action = getattr(self, "pre_command_bar_action", None)
        if action is not None:
            action.blockSignals(True)
            action.setChecked(bool(getattr(self, "pre_command_visible", True)))
            action.blockSignals(False)
        checkbox = getattr(self, "pre_command_enabled_checkbox", None)
        if checkbox is not None:
            checkbox.blockSignals(True)
            checkbox.setChecked(bool(getattr(self, "pre_command_enabled", False)))
            checkbox.setVisible(visible)
            checkbox.blockSignals(False)
        combo = getattr(self, "pre_command_input", None)
        if combo is not None:
            combo.setVisible(visible)
            current_text = self.normalize_pre_command_text(getattr(self, "pre_command_text", ""))
            history = self.normalize_pre_command_history(getattr(self, "pre_command_history", []))
            combo.blockSignals(True)
            combo.clear()
            if history:
                combo.addItems(history)
            combo.setCurrentText(current_text)
            combo.blockSignals(False)

    def create_terminal_tab_widget(self, detached_window=None):
        tab_widget = QTabWidget()
        tab_widget._shelldeck_detached_window = detached_window
        tab_widget.setTabsClosable(True)
        tab_widget.setMovable(True)
        tab_widget.tabCloseRequested.connect(lambda index, w=tab_widget: self.close_tab(index, w))
        tab_widget.currentChanged.connect(lambda index, w=tab_widget: self.current_tab_changed(index, w))
        tab_widget.tabBar().setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tab_widget.tabBar().customContextMenuRequested.connect(
            lambda pos, w=tab_widget: self.show_tab_context_menu(pos, w)
        )
        plus_button = QPushButton("+", tab_widget)
        plus_button.setToolTip("Neuen Tab in dieser Ansicht öffnen")
        plus_button.setFixedSize(28, 24)
        plus_button.clicked.connect(lambda checked=False, w=tab_widget: self.new_tab(target_tab_widget=w))
        tab_widget.setCornerWidget(plus_button, Qt.Corner.TopRightCorner)
        return tab_widget

    def main_terminal_tab_widgets(self):
        widgets = []
        for name in ("tab_widget", "secondary_tab_widget", "tertiary_tab_widget", "quaternary_tab_widget"):
            widget = getattr(self, name, None)
            if widget is not None and widget not in widgets:
                widgets.append(widget)
        return widgets

    def detached_tab_widgets(self):
        widgets = []
        for window in list(getattr(self, "detached_windows", [])):
            widget = getattr(window, "tab_widget", None)
            if widget is not None and widget not in widgets:
                widgets.append(widget)
        return widgets

    def terminal_tab_widgets(self):
        return self.main_terminal_tab_widgets() + self.detached_tab_widgets()

    def is_detached_tab_widget(self, tab_widget):
        return getattr(tab_widget, "_shelldeck_detached_window", None) is not None

    def detached_window_for_tab_widget(self, tab_widget):
        window = getattr(tab_widget, "_shelldeck_detached_window", None)
        return window if window in getattr(self, "detached_windows", []) else None

    def view_pane_widgets(self):
        return {
            "main": self.tab_widget,
            "secondary": self.secondary_tab_widget,
            "tertiary": self.tertiary_tab_widget,
            "quaternary": self.quaternary_tab_widget,
        }

    def all_terminal_tabs(self):
        for tab_widget in self.terminal_tab_widgets():
            for index in range(tab_widget.count()):
                tab = tab_widget.widget(index)
                if isinstance(tab, TerminalTab):
                    yield tab_widget, index, tab

    def total_terminal_tab_count(self):
        return sum(widget.count() for widget in self.terminal_tab_widgets())

    def tab_widget_for_tab(self, tab):
        for tab_widget in self.terminal_tab_widgets():
            index = tab_widget.indexOf(tab)
            if index >= 0:
                return tab_widget, index
        return None, -1

    def set_active_tab_widget(self, tab_widget):
        if tab_widget in self.terminal_tab_widgets():
            self.active_tab_widget = tab_widget

    def view_mode_pane_order(self, mode=None):
        mode = str(mode or getattr(self, "view_layout_mode", "single") or "single")
        if mode == "horizontal":
            return ["left", "right"]
        if mode == "vertical":
            return ["top", "bottom"]
        if mode == "quad":
            return ["top_left", "top_right", "bottom_left", "bottom_right"]
        return ["main"]

    def pane_widget_for_logical_pane(self, pane, mode=None):
        mode = str(mode or getattr(self, "view_layout_mode", "single") or "single")
        pane = str(pane or "main")
        if mode == "horizontal":
            return {"left": self.tab_widget, "right": self.secondary_tab_widget, "main": self.tab_widget}.get(pane, self.tab_widget)
        if mode == "vertical":
            return {"top": self.tab_widget, "bottom": self.secondary_tab_widget, "main": self.tab_widget}.get(pane, self.tab_widget)
        if mode == "quad":
            return {
                "top_left": self.tab_widget,
                "top_right": self.secondary_tab_widget,
                "bottom_left": self.tertiary_tab_widget,
                "bottom_right": self.quaternary_tab_widget,
                "left": self.tab_widget,
                "right": self.secondary_tab_widget,
                "top": self.tab_widget,
                "bottom": self.tertiary_tab_widget,
                "main": self.tab_widget,
            }.get(pane, self.tab_widget)
        return self.tab_widget

    def logical_pane_for_widget(self, tab_widget):
        if self.is_detached_tab_widget(tab_widget):
            return "detached"
        mode = str(getattr(self, "view_layout_mode", "single") or "single")
        if mode == "horizontal":
            if tab_widget is self.secondary_tab_widget:
                return "right"
            return "left"
        if mode == "vertical":
            if tab_widget is self.secondary_tab_widget:
                return "bottom"
            return "top"
        if mode == "quad":
            if tab_widget is self.secondary_tab_widget:
                return "top_right"
            if tab_widget is self.tertiary_tab_widget:
                return "bottom_left"
            if tab_widget is self.quaternary_tab_widget:
                return "bottom_right"
            return "top_left"
        return "main"

    def logical_pane_label(self, pane, mode=None):
        labels = {
            "main": "Hauptansicht",
            "left": "links",
            "right": "rechts",
            "top": "oben",
            "bottom": "unten",
            "top_left": "links oben",
            "top_right": "rechts oben",
            "bottom_left": "links unten",
            "bottom_right": "rechts unten",
            "detached": "entkoppelt",
        }
        return labels.get(str(pane or "main"), str(pane or "main"))

    def layout_mode_for_target_pane(self, pane):
        pane = str(pane or "main")
        if pane in {"left", "right"}:
            return "horizontal"
        if pane in {"top", "bottom"}:
            return "vertical"
        if pane in {"top_left", "top_right", "bottom_left", "bottom_right"}:
            return "quad"
        return "single"

    def clear_view_grid(self):
        while self.view_grid.count():
            item = self.view_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(self.view_container)
                widget.hide()

    def move_all_tabs(self, source, target):
        if source is target:
            return
        while source.count() > 0:
            tab = source.widget(0)
            label = source.tabText(0)
            source.removeTab(0)
            target.addTab(tab, label)
            if isinstance(tab, TerminalTab):
                self.update_tab_title(tab)

    def apply_view_layout(self, move_tabs=True):
        mode = str(getattr(self, "view_layout_mode", "single") or "single")
        if mode not in {"single", "horizontal", "vertical", "quad"}:
            mode = "single"
            self.view_layout_mode = mode

        if move_tabs:
            if mode == "single":
                for widget in (self.secondary_tab_widget, self.tertiary_tab_widget, self.quaternary_tab_widget):
                    self.move_all_tabs(widget, self.tab_widget)
            elif mode in {"horizontal", "vertical"}:
                self.move_all_tabs(self.tertiary_tab_widget, self.tab_widget)
                self.move_all_tabs(self.quaternary_tab_widget, self.secondary_tab_widget)

        self.clear_view_grid()
        self.view_grid.setColumnStretch(0, 0)
        self.view_grid.setColumnStretch(1, 0)
        self.view_grid.setRowStretch(0, 0)
        self.view_grid.setRowStretch(1, 0)
        if mode == "single":
            self.view_grid.addWidget(self.tab_widget, 0, 0, 1, 1)
            visible = [self.tab_widget]
        elif mode == "horizontal":
            self.view_grid.addWidget(self.tab_widget, 0, 0, 1, 1)
            self.view_grid.addWidget(self.secondary_tab_widget, 0, 1, 1, 1)
            self.view_grid.setColumnStretch(0, 1)
            self.view_grid.setColumnStretch(1, 1)
            visible = [self.tab_widget, self.secondary_tab_widget]
        elif mode == "vertical":
            self.view_grid.addWidget(self.tab_widget, 0, 0, 1, 1)
            self.view_grid.addWidget(self.secondary_tab_widget, 1, 0, 1, 1)
            self.view_grid.setRowStretch(0, 1)
            self.view_grid.setRowStretch(1, 1)
            visible = [self.tab_widget, self.secondary_tab_widget]
        else:
            self.view_grid.addWidget(self.tab_widget, 0, 0, 1, 1)
            self.view_grid.addWidget(self.secondary_tab_widget, 0, 1, 1, 1)
            self.view_grid.addWidget(self.tertiary_tab_widget, 1, 0, 1, 1)
            self.view_grid.addWidget(self.quaternary_tab_widget, 1, 1, 1, 1)
            self.view_grid.setColumnStretch(0, 1)
            self.view_grid.setColumnStretch(1, 1)
            self.view_grid.setRowStretch(0, 1)
            self.view_grid.setRowStretch(1, 1)
            visible = [self.tab_widget, self.secondary_tab_widget, self.tertiary_tab_widget, self.quaternary_tab_widget]

        for widget in self.main_terminal_tab_widgets():
            widget.setVisible(widget in visible)
        if self.active_tab_widget not in visible:
            self.active_tab_widget = self.tab_widget
        self.split_view_enabled = mode in {"horizontal", "vertical", "quad"}
        self.update_view_actions()
        self.rebuild_move_view_menu()
        self.apply_color_scheme()
        if mode == "single":
            self.tab_widget.show()
            self.tab_widget.raise_()

    def update_view_actions(self):
        mode = str(getattr(self, "view_layout_mode", "single") or "single")
        action_map = {
            "single": getattr(self, "view_single_action", None),
            "horizontal": getattr(self, "split_view_action", None),
            "vertical": getattr(self, "view_vertical_action", None),
            "quad": getattr(self, "view_quad_action", None),
        }
        for action_mode, action in action_map.items():
            if action is None:
                continue
            action.blockSignals(True)
            action.setChecked(action_mode == mode)
            action.blockSignals(False)

    def set_view_layout_mode(self, mode, move_tabs=True):
        mode = str(mode or "single")
        if mode not in {"single", "horizontal", "vertical", "quad"}:
            mode = "single"
        self.view_layout_mode = mode
        self.apply_view_layout(move_tabs=move_tabs)
        self.save_settings()
        labels = {
            "single": "Einzelansicht aktiv",
            "horizontal": "2er horizontal aktiv",
            "vertical": "2er vertikal aktiv",
            "quad": "4er Raster aktiv",
        }
        self.show_status(labels.get(mode, "Ansicht geändert"))

    def set_split_view_enabled(self, enabled):
        self.set_view_layout_mode("horizontal" if enabled else "single")

    def rebuild_move_view_menu(self):
        menu = getattr(self, "move_view_menu", None)
        if menu is None:
            return
        menu.clear()
        for pane in self.view_mode_pane_order():
            label = self.logical_pane_label(pane)
            action = QAction(label.capitalize(), self)
            action.triggered.connect(lambda checked=False, p=pane: self.move_current_tab_to_pane(p))
            menu.addAction(action)

        menu.addSeparator()
        for label, pane in (
            ("Horizontal rechts", "right"),
            ("Vertikal unten", "bottom"),
            ("Raster: rechts oben", "top_right"),
            ("Raster: links unten", "bottom_left"),
            ("Raster: rechts unten", "bottom_right"),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, p=pane: self.move_current_tab_to_pane(p))
            menu.addAction(action)

    def move_current_tab_to_other_view(self):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        source, index = self.tab_widget_for_tab(tab)
        if source is None or index < 0:
            return
        order = self.view_mode_pane_order()
        current_pane = self.logical_pane_for_widget(source)
        if current_pane not in order or len(order) < 2:
            target_pane = "right"
        else:
            target_pane = order[(order.index(current_pane) + 1) % len(order)]
        self.move_current_tab_to_pane(target_pane)

    def move_current_tab_to_pane(self, pane):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        source, index = self.tab_widget_for_tab(tab)
        if source is None or index < 0:
            return

        target_mode = self.layout_mode_for_target_pane(pane)
        if target_mode != self.view_layout_mode and target_mode != "single":
            self.view_layout_mode = target_mode
            self.apply_view_layout(move_tabs=False)

        target = self.pane_widget_for_logical_pane(pane)
        if target is source:
            self.show_status(f"Tab ist bereits in Ansicht {self.logical_pane_label(self.logical_pane_for_widget(source))}")
            return

        label = source.tabText(index)
        source.removeTab(index)
        new_index = target.addTab(tab, label)
        target.setCurrentIndex(new_index)
        self.active_tab_widget = target
        self.update_tab_title(tab)
        self.cleanup_empty_detached_windows()
        self.save_settings()
        self.show_status(f"Tab nach {self.logical_pane_label(self.logical_pane_for_widget(target))} verschoben")

    def next_detached_window_id(self):
        existing = {str(getattr(window, "window_id", "") or "") for window in getattr(self, "detached_windows", [])}
        index = 1
        while True:
            candidate = f"detached-{index}"
            if candidate not in existing:
                return candidate
            index += 1

    def ensure_detached_window(self, window_id="", title="Entkoppelte Tabs", reuse_existing=True):
        windows = [window for window in getattr(self, "detached_windows", []) if window is not None]
        self.detached_windows = windows
        wanted_id = str(window_id or "").strip()
        if wanted_id:
            for window in self.detached_windows:
                if str(getattr(window, "window_id", "") or "") == wanted_id:
                    window.show()
                    return window
        elif reuse_existing:
            for window in self.detached_windows:
                if not window.is_empty():
                    window.show()
                    return window
        window = DetachedTerminalWindow(self, title=title or "Entkoppelte Tabs", window_id=wanted_id)
        self.detached_windows.append(window)
        self.apply_color_scheme()
        return window

    def detached_widget_for_saved_tab(self, item):
        window_id = str(item.get("detached_window", "") or "").strip() or "detached-1"
        title = str(item.get("detached_title", "") or "Entkoppelte Tabs")
        return self.ensure_detached_window(window_id=window_id, title=title, reuse_existing=False).tab_widget

    def target_widget_for_saved_tab(self, item):
        pane = str(item.get("view_pane", "main") or "main")
        if pane == "detached" or str(item.get("detached_window", "") or "").strip():
            return self.detached_widget_for_saved_tab(item)
        return self.pane_widget_for_logical_pane(pane)

    def unregister_detached_window(self, window):
        if window in getattr(self, "detached_windows", []):
            self.detached_windows.remove(window)
        if getattr(self, "active_tab_widget", None) is getattr(window, "tab_widget", None):
            self.active_tab_widget = self.tab_widget

    def cleanup_empty_detached_windows(self):
        for window in list(getattr(self, "detached_windows", [])):
            if window.is_empty():
                self.unregister_detached_window(window)
                window._closing_from_owner = True
                window.close()

    def attach_existing_tab_to_main(self, tab, label=None, target_tab_widget=None):
        target = target_tab_widget or self.tab_widget
        if target not in self.main_terminal_tab_widgets():
            target = self.tab_widget
        label = label or getattr(tab, "custom_title", "") or getattr(tab, "title", "Terminal") or "Terminal"
        index = target.addTab(tab, label)
        target.setCurrentIndex(index)
        self.active_tab_widget = target
        if isinstance(tab, TerminalTab):
            self.update_tab_title(tab)
        self.apply_color_scheme()
        return index

    def detach_current_tab(self):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        source, index = self.tab_widget_for_tab(tab)
        if source is None or index < 0:
            return
        if self.is_detached_tab_widget(source):
            self.show_status("Tab ist bereits entkoppelt")
            return
        label = source.tabText(index)
        source.removeTab(index)
        window = self.ensure_detached_window()
        window.add_tab(tab, label=label)
        self.active_tab_widget = window.tab_widget
        if self.total_terminal_tab_count() == 0:
            self.new_tab(target_tab_widget=self.tab_widget)
        self.save_settings()
        self.show_status(f"Tab entkoppelt: {label}")

    def reattach_current_tab(self):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        source, index = self.tab_widget_for_tab(tab)
        if source is None or index < 0:
            return
        if not self.is_detached_tab_widget(source):
            self.show_status("Tab ist bereits im Hauptfenster")
            return
        label = source.tabText(index)
        source.removeTab(index)
        self.attach_existing_tab_to_main(tab, label=label)
        self.cleanup_empty_detached_windows()
        self.save_settings()
        self.show_status(f"Tab wieder gekoppelt: {label}")

    def update_ai_menu_visibility(self):
        enabled = bool(getattr(self, "ai_features_enabled", False))
        if hasattr(self, "ai_menu"):
            self.ai_menu.menuAction().setVisible(enabled)
        if hasattr(self, "ai_features_action"):
            self.ai_features_action.blockSignals(True)
            self.ai_features_action.setChecked(enabled)
            self.ai_features_action.blockSignals(False)

    def set_ai_features_enabled(self, enabled):
        self.ai_features_enabled = bool(enabled)
        self.update_ai_menu_visibility()
        self.save_settings()
        if self.ai_features_enabled:
            self.show_status("KI-Menü aktiviert")
        else:
            self.show_status("KI-Menü deaktiviert")

    def ensure_ai_features_enabled(self):
        if bool(getattr(self, "ai_features_enabled", False)):
            return True
        self.show_status("KI/Ollama ist deaktiviert. Aktivieren unter Einstellungen → KI-Menü / Ollama aktivieren.")
        return False

    def new_tab(self, shell_type=None, title=None, start_directory=None, command_history=None, target_tab_widget=None, restore_command="", venv_path="", terminal_engine=None):
        effective_start_directory = start_directory
        if effective_start_directory is None:
            current_tab = self.current_terminal()
            if isinstance(current_tab, TerminalTab):
                effective_start_directory = str(getattr(current_tab, "current_working_directory", "") or "")
            if not effective_start_directory:
                effective_start_directory = self.default_start_directory
        tab = TerminalTab(
            self,
            shell_type=shell_type or self.shell_type,
            custom_title=title,
            start_directory=effective_start_directory,
            command_history=command_history,
            restore_command=restore_command,
            venv_path=venv_path,
            terminal_engine=terminal_engine or self.terminal_engine,
        )
        target = target_tab_widget or getattr(self, "active_tab_widget", None) or self.tab_widget
        if target not in self.terminal_tab_widgets() or (not target.isVisible() and not self.is_detached_tab_widget(target)):
            target = self.tab_widget
        index = target.addTab(tab, tab.title or f"Terminal {self.total_terminal_tab_count() + 1}")
        target.setCurrentIndex(index)
        self.active_tab_widget = target
        self.apply_color_scheme()
        return tab

    def update_tab_title(self, tab):
        tab_widget, index = self.tab_widget_for_tab(tab)
        if tab_widget is None or index < 0:
            return
        base = tab.title or "Terminal"
        existing_same_title = sum(
            1 for _, other_index, other_tab in self.all_terminal_tabs()
            if other_tab is not tab and other_tab.title == base
        )
        title = f"{base} {index + 1}" if existing_same_title and not tab.custom_title else base
        icon = self.shell_backend_icon(tab.shell_type)
        tab_widget.setTabText(index, f"{icon} {title}".strip())
        tab_widget.tabBar().setTabTextColor(index, QColor(self.shell_backend_color(tab.shell_type)))

    def rebuild_saved_paths_menu(self):
        self.paths_menu.clear()

        save_current_action = QAction("Aktuellen Ordner speichern", self)
        save_current_action.triggered.connect(self.save_current_path)
        self.paths_menu.addAction(save_current_action)

        add_manual_action = QAction("Ordnerpfad manuell speichern", self)
        add_manual_action.triggered.connect(self.save_manual_path)
        self.paths_menu.addAction(add_manual_action)

        delete_action = QAction("Gespeicherten Pfad löschen", self)
        delete_action.triggered.connect(self.delete_saved_path)
        delete_action.setEnabled(bool(self.saved_paths))
        self.paths_menu.addAction(delete_action)

        clear_default_action = QAction("Standardordner für neue Tabs zurücksetzen", self)
        clear_default_action.triggered.connect(self.clear_default_start_directory)
        clear_default_action.setEnabled(bool(self.default_start_directory))
        self.paths_menu.addAction(clear_default_action)

        self.paths_menu.addSeparator()

        if self.default_start_directory:
            default_action = QAction(f"Standardordner: {self.default_start_directory}", self)
            default_action.setEnabled(False)
            self.paths_menu.addAction(default_action)
            self.paths_menu.addSeparator()

        if not self.saved_paths:
            empty_action = QAction("Keine gespeicherten Pfade", self)
            empty_action.setEnabled(False)
            self.paths_menu.addAction(empty_action)
            return

        for item in self.saved_paths:
            name = str(item.get("name", "") or item.get("path", ""))
            path = str(item.get("path", "") or "")
            if not path:
                continue

            submenu = self.paths_menu.addMenu(name)
            submenu.setToolTipsVisible(True)
            submenu.setToolTip(path)

            current_action = QAction("Im aktuellen Tab öffnen", self)
            current_action.setToolTip(path)
            current_action.triggered.connect(lambda checked=False, p=path: self.open_saved_path(p))
            submenu.addAction(current_action)

            new_tab_action = QAction("In neuem Tab öffnen", self)
            new_tab_action.setToolTip(path)
            new_tab_action.triggered.connect(lambda checked=False, p=path: self.open_saved_path_in_new_tab(p))
            submenu.addAction(new_tab_action)

            backend_menu = submenu.addMenu("In neuem Tab mit Backend öffnen")
            for backend in self.available_shell_backends():
                shell_id = str(backend.get("id", "") or "")
                label = str(backend.get("label", "") or self.shell_backend_label(shell_id))
                icon = self.shell_backend_icon(shell_id)
                action = QAction(f"{icon} {label}".strip(), self)
                action.setToolTip(path)
                action.triggered.connect(
                    lambda checked=False, p=path, s=shell_id: self.open_saved_path_in_new_tab(p, shell_type=s)
                )
                backend_menu.addAction(action)

            submenu.addSeparator()

            default_action = QAction("Als Standardordner für neue Tabs setzen", self)
            default_action.setToolTip(path)
            default_action.triggered.connect(lambda checked=False, p=path: self.set_default_start_directory(p))
            submenu.addAction(default_action)

    def rebuild_profiles_menu(self):
        if not hasattr(self, "profiles_menu"):
            return

        self.profiles_menu.clear()

        save_action = QAction("Aktuellen Tab als Profil speichern", self)
        save_action.triggered.connect(self.save_current_tab_as_profile)
        self.profiles_menu.addAction(save_action)

        open_action = QAction("Profil in neuem Tab öffnen", self)
        open_action.triggered.connect(self.open_profile_dialog)
        open_action.setEnabled(bool(self.tab_profiles))
        self.profiles_menu.addAction(open_action)

        delete_action = QAction("Profil löschen", self)
        delete_action.triggered.connect(self.delete_profile_dialog)
        delete_action.setEnabled(bool(self.tab_profiles))
        self.profiles_menu.addAction(delete_action)

        self.profiles_menu.addSeparator()

        if not self.tab_profiles:
            empty_action = QAction("Keine Profile gespeichert", self)
            empty_action.setEnabled(False)
            self.profiles_menu.addAction(empty_action)
            return

        for profile in self.tab_profiles:
            normalized = normalize_profile(profile)
            action = QAction(profile_display_label(normalized), self)
            action.triggered.connect(lambda checked=False, p=normalized: self.open_profile_in_new_tab(p))
            self.profiles_menu.addAction(action)

    def choose_profile_save_name(self, default_name):
        profiles = normalize_profiles(self.tab_profiles)
        names = [str(profile.get("name", "") or "").strip() for profile in profiles if str(profile.get("name", "") or "").strip()]
        if names:
            selected, ok = QInputDialog.getItem(
                self,
                "Tab-Profil speichern",
                "Bestehendes Profil ersetzen oder neuen Namen eingeben:",
                names,
                0,
                True,
            )
            if ok and str(selected or "").strip():
                return str(selected).strip()
            return ""

        name, ok = QInputDialog.getText(
            self,
            "Tab-Profil speichern",
            "Profilname:",
            text=str(default_name or "Profil"),
        )
        return str(name or "").strip() if ok else ""

    def save_current_tab_as_profile(self):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            self.show_status("Kein aktiver Terminal-Tab")
            return

        default_name = tab.custom_title or tab.title or self.shell_backend_label(tab.shell_type)
        name = self.choose_profile_save_name(default_name)
        if not name:
            return

        startup_command, ok = QInputDialog.getText(
            self,
            "Optionaler Startbefehl",
            "Startbefehl beim Öffnen dieses Profils (leer lassen für keinen):",
            text="",
        )
        if not ok:
            return

        profile = profile_from_tab(tab, name=name.strip(), startup_command=startup_command.strip())
        self.tab_profiles = [
            item for item in normalize_profiles(self.tab_profiles)
            if str(item.get("name", "")).strip().lower() != profile["name"].strip().lower()
        ]
        self.tab_profiles.append(profile)
        self.rebuild_profiles_menu()
        self.save_settings()
        self.show_status(f"Profil gespeichert: {profile['name']}")

    def profile_choice(self, title):
        profiles = normalize_profiles(self.tab_profiles)
        if not profiles:
            self.show_status("Keine Profile gespeichert")
            return None

        labels = [profile_display_label(profile) for profile in profiles]
        selected, ok = QInputDialog.getItem(
            self,
            title,
            "Profil auswählen:",
            labels,
            0,
            False,
        )
        if not ok or selected not in labels:
            return None
        return profiles[labels.index(selected)]

    def open_profile_dialog(self):
        profile = self.profile_choice("Profil öffnen")
        if profile:
            self.open_profile_in_new_tab(profile)

    def delete_profile_dialog(self):
        profile = self.profile_choice("Profil löschen")
        if not profile:
            return
        name = str(profile.get("name", "") or "").strip().lower()
        self.tab_profiles = [
            item for item in normalize_profiles(self.tab_profiles)
            if str(item.get("name", "") or "").strip().lower() != name
        ]
        self.rebuild_profiles_menu()
        self.save_settings()
        self.show_status(f"Profil gelöscht: {profile.get('name', '')}")

    def open_profile_in_new_tab(self, profile):
        profile = normalize_profile(profile)
        shell_type = profile.get("shell_type") or self.shell_type
        title = profile.get("title") or profile.get("name") or self.shell_backend_label(shell_type)
        working_directory = profile.get("working_directory") or None

        tab = self.new_tab(
            shell_type=shell_type,
            title=title,
            start_directory=working_directory,
            terminal_engine=profile.get("terminal_engine", self.terminal_engine),
        )
        if not isinstance(tab, TerminalTab):
            return

        ollama_model = str(profile.get("ollama_model", "") or "").strip()
        startup_command = str(profile.get("startup_command", "") or "").strip()

        if ollama_model and self.ai_features_enabled:
            tab.start_ollama_prompt_mode(ollama_model)
        elif ollama_model and not self.ai_features_enabled:
            tab.output_area.append("[KI/Ollama ist deaktiviert. Aktivieren unter Einstellungen → KI-Menü / Ollama aktivieren.]\n")
        elif startup_command:
            tab.run_text_command(startup_command)

    def merge_workspaces_by_name(self, *workspace_lists):
        merged = []
        positions = {}
        for workspace_list in workspace_lists:
            for workspace in normalize_workspaces(workspace_list):
                name = str(workspace.get("name", "") or "").strip()
                if not name:
                    continue
                key = name.lower()
                if key in positions:
                    merged[positions[key]] = workspace
                else:
                    positions[key] = len(merged)
                    merged.append(workspace)
        return normalize_workspaces(merged)

    def load_persistent_workspaces(self):
        store_file = getattr(self, "workspace_store_file", None)
        if not store_file or not Path(store_file).exists():
            return []
        try:
            data = json.loads(Path(store_file).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if isinstance(data, dict):
            data = data.get("workspaces", [])
        return normalize_workspaces(data)

    def save_persistent_workspaces(self):
        store_file = getattr(self, "workspace_store_file", None)
        if not store_file:
            return False
        try:
            store_file = Path(store_file)
            store_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "app": APP_NAME,
                "version": APP_VERSION,
                "workspaces": normalize_workspaces(self.workspaces),
            }
            tmp_file = store_file.with_suffix(store_file.suffix + ".tmp")
            tmp_file.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
            tmp_file.replace(store_file)
            return True
        except OSError as exc:
            self.show_status(f"Workspace-Speicherfehler: {exc}")
            return False

    def rebuild_workspaces_menu(self):
        if not hasattr(self, "workspaces_menu"):
            return

        self.workspaces_menu.clear()

        save_action = QAction("Aktuellen Workspace speichern", self)
        save_action.triggered.connect(self.save_current_workspace)
        self.workspaces_menu.addAction(save_action)

        load_action = QAction("Workspace laden", self)
        load_action.triggered.connect(self.load_workspace_dialog)
        load_action.setEnabled(bool(self.workspaces))
        self.workspaces_menu.addAction(load_action)

        delete_action = QAction("Workspace löschen", self)
        delete_action.triggered.connect(self.delete_workspace_dialog)
        delete_action.setEnabled(bool(self.workspaces))
        self.workspaces_menu.addAction(delete_action)

        self.workspaces_menu.addSeparator()

        if not self.workspaces:
            empty_action = QAction("Keine Workspaces gespeichert", self)
            empty_action.setEnabled(False)
            self.workspaces_menu.addAction(empty_action)
            return

        for workspace in normalize_workspaces(self.workspaces):
            action = QAction(workspace_display_label(workspace), self)
            action.triggered.connect(lambda checked=False, w=workspace: self.load_workspace(w))
            self.workspaces_menu.addAction(action)

    def choose_workspace_save_name(self, default_name):
        workspaces = normalize_workspaces(self.workspaces)
        names = [str(workspace.get("name", "") or "").strip() for workspace in workspaces if str(workspace.get("name", "") or "").strip()]
        if names:
            selected, ok = QInputDialog.getItem(
                self,
                "Workspace speichern",
                "Bestehenden Workspace ersetzen oder neuen Namen eingeben:",
                names,
                0,
                True,
            )
            if ok and str(selected or "").strip():
                return str(selected).strip()
            return ""

        name, ok = QInputDialog.getText(
            self,
            "Workspace speichern",
            "Workspace-Name:",
            text=str(default_name or "ShellDeck Workspace"),
        )
        return str(name or "").strip() if ok else ""

    def save_current_workspace(self):
        name = self.choose_workspace_save_name("ShellDeck Workspace")
        if not name:
            return

        workspace = workspace_from_tabs(
            self.collect_tab_settings(),
            name=name.strip(),
            default_start_directory=self.default_start_directory,
            selected_ollama_model=self.selected_ollama_model,
            shell_type=self.shell_type,
            terminal_engine=self.current_terminal_engine(),
            layout_mode=getattr(self, "view_layout_mode", "single"),
        )
        self.workspaces = [
            item for item in normalize_workspaces(self.workspaces)
            if str(item.get("name", "") or "").strip().lower() != workspace["name"].strip().lower()
        ]
        self.workspaces.append(workspace)
        self.rebuild_workspaces_menu()
        settings_ok = self.save_settings()
        store_ok = self.save_persistent_workspaces()
        if settings_ok or store_ok:
            self.show_status(f"Workspace gespeichert: {workspace['name']}")
        else:
            self.show_status(f"Workspace nur im laufenden Menü gespeichert, aber nicht dauerhaft: {workspace['name']}")

    def workspace_choice(self, title):
        workspaces = normalize_workspaces(self.workspaces)
        if not workspaces:
            self.show_status("Keine Workspaces gespeichert")
            return None

        labels = [workspace_display_label(workspace) for workspace in workspaces]
        selected, ok = QInputDialog.getItem(
            self,
            title,
            "Workspace auswählen:",
            labels,
            0,
            False,
        )
        if not ok or selected not in labels:
            return None
        return workspaces[labels.index(selected)]

    def load_workspace_dialog(self):
        workspace = self.workspace_choice("Workspace laden")
        if workspace:
            self.load_workspace(workspace)

    def delete_workspace_dialog(self):
        workspace = self.workspace_choice("Workspace löschen")
        if not workspace:
            return
        name = str(workspace.get("name", "") or "").strip().lower()
        self.workspaces = [
            item for item in normalize_workspaces(self.workspaces)
            if str(item.get("name", "") or "").strip().lower() != name
        ]
        self.rebuild_workspaces_menu()
        self.save_settings()
        self.save_persistent_workspaces()
        self.show_status(f"Workspace gelöscht: {workspace.get('name', '')}")

    def clear_all_tabs_for_workspace_load(self):
        for tab_widget in self.terminal_tab_widgets():
            while tab_widget.count() > 0:
                tab = tab_widget.widget(0)
                if isinstance(tab, TerminalTab):
                    tab.stop_process(fast=True)
                tab_widget.removeTab(0)
                if tab is not None:
                    tab.deleteLater()
        for window in list(getattr(self, "detached_windows", [])):
            window._closing_from_owner = True
            window.close()
        self.detached_windows = []
        self.active_tab_widget = self.tab_widget

    def load_workspace(self, workspace):
        workspace = normalize_workspace(workspace)
        self.default_start_directory = workspace.get("default_start_directory", "")
        self.selected_ollama_model = workspace.get("selected_ollama_model", "")
        shell_type = self.normalize_shell_type(workspace.get("shell_type", ""))
        if shell_type and self.system_shell(shell_type):
            self.shell_type = shell_type
        self.terminal_engine = self.normalize_terminal_engine(workspace.get("terminal_engine", self.terminal_engine))

        layout_mode = str(workspace.get("layout_mode", "single") or "single")
        self.set_view_layout_mode(layout_mode if layout_mode in {"single", "horizontal", "vertical", "quad"} else "single", move_tabs=False)

        self.clear_all_tabs_for_workspace_load()

        restored = False
        for item in workspace.get("tabs", []):
            if not isinstance(item, dict):
                continue
            tab_shell = self.normalize_shell_type(item.get("shell_type", self.shell_type) or self.shell_type)
            if not self.system_shell(tab_shell):
                tab_shell = self.shell_type
            tab = self.new_tab(
                shell_type=tab_shell,
                title=str(item.get("title", "") or ""),
                start_directory=str(item.get("working_directory", "") or ""),
                command_history=item.get("command_history", []),
                restore_command=item.get("restore_command", ""),
                venv_path=item.get("venv_path", ""),
                terminal_engine=item.get("terminal_engine", self.terminal_engine),
                target_tab_widget=self.target_widget_for_saved_tab(item),
            )
            if isinstance(tab, TerminalTab):
                ollama_model = str(item.get("ollama_model", "") or "").strip()
                client_kind = str(item.get("client_mode_kind", "") or item.get("client_mode", "") or "").strip()
                if self.ai_features_enabled and (ollama_model or client_kind == "ollama_api"):
                    tab.start_ollama_prompt_mode(
                        ollama_model or self.selected_ollama_model,
                        system_prompt=str(item.get("ollama_system_prompt", "") or ""),
                    )
                else:
                    tab.schedule_restore_command(item.get("restore_command", ""))
            restored = True

        if not restored:
            self.new_tab()

        self.rebuild_saved_paths_menu()
        self.save_settings()
        current_tab = self.current_terminal()
        if isinstance(current_tab, TerminalTab):
            current_tab.input_line.setFocus()
        self.show_status(f"Workspace geladen: {workspace.get('name', '')}")


    def _normalize_saved_path_item(self, name, path):
        clean_path = str(path or "").strip().strip('"')
        clean_name = str(name or "").strip() or Path(clean_path).name or clean_path
        return {"name": clean_name, "path": clean_path}

    def add_saved_path(self, name, path):
        item = self._normalize_saved_path_item(name, path)
        if not item["path"]:
            return
        self.saved_paths = [entry for entry in self.saved_paths if str(entry.get("path", "")) != item["path"]]
        self.saved_paths.append(item)
        self.rebuild_saved_paths_menu()
        self.save_settings()

    def save_current_path(self):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        current_path = tab.guess_current_directory()
        name, ok = QInputDialog.getText(
            self,
            "Aktuellen Ordner speichern",
            "Name für diesen Ordnerpfad:",
            text=Path(current_path).name or current_path,
        )
        if ok:
            self.add_saved_path(name, current_path)

    def save_manual_path(self):
        path = QFileDialog.getExistingDirectory(self, "Ordnerpfad speichern", str(Path.cwd()))
        if not path:
            text, ok = QInputDialog.getText(self, "Ordnerpfad manuell speichern", "Ordnerpfad:")
            if not ok or not text.strip():
                return
            path = text.strip()
        name, ok = QInputDialog.getText(
            self,
            "Ordnerpfad speichern",
            "Name für diesen Ordnerpfad:",
            text=Path(path).name or path,
        )
        if ok:
            self.add_saved_path(name, path)

    def delete_saved_path(self):
        if not self.saved_paths:
            return
        labels = [f"{item.get('name', item.get('path', ''))} — {item.get('path', '')}" for item in self.saved_paths]
        selected, ok = QInputDialog.getItem(
            self,
            "Gespeicherten Pfad löschen",
            "Pfad auswählen:",
            labels,
            0,
            False,
        )
        if ok and selected in labels:
            index = labels.index(selected)
            self.saved_paths.pop(index)
            self.rebuild_saved_paths_menu()
            self.save_settings()

    def path_for_shell(self, path, shell_type):
        text = str(path or "").strip()
        match = re.match(r"^([A-Za-z]):[\\/](.*)$", text)
        if sys.platform == "win32" and match:
            drive = match.group(1).lower()
            rest = match.group(2).replace("\\", "/")
            lower_shell = str(shell_type or "").lower()
            if lower_shell == "wsl":
                return f"/mnt/{drive}/{rest}"
            if lower_shell in ("git_bash", "bash", "zsh", "fish", "sh"):
                return f"/{drive}/{rest}"
        return text

    def quote_path_for_shell(self, path):
        return '"' + str(path).replace('"', '\"') + '"'

    def cd_command_for_path(self, path, shell_type):
        shell_path = self.path_for_shell(path, shell_type)
        return f"cd {self.quote_path_for_shell(shell_path)}"

    def open_saved_path(self, path):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            tab = self.new_tab()
        tab.current_working_directory = str(path).strip().strip('"') or tab.current_working_directory
        tab.run_text_command(self.cd_command_for_path(path, tab.shell_type))

    def open_saved_path_in_new_tab(self, path, shell_type=None):
        clean_path = str(path or "").strip().strip('"')
        tab = self.new_tab(
            shell_type=shell_type or self.shell_type,
            title=Path(clean_path).name or clean_path or None,
            start_directory=clean_path,
        )
        if isinstance(tab, TerminalTab):
            tab.current_working_directory = clean_path or tab.current_working_directory
            tab.input_line.setFocus()

    def set_default_start_directory(self, path):
        clean_path = str(path or "").strip().strip('"')
        if not clean_path:
            return
        self.default_start_directory = clean_path
        self.rebuild_saved_paths_menu()
        self.save_settings()
        self.statusBar().showMessage(f"Standardordner für neue Tabs gesetzt: {clean_path}")

    def clear_default_start_directory(self):
        self.default_start_directory = ""
        self.rebuild_saved_paths_menu()
        self.save_settings()
        self.statusBar().showMessage("Standardordner für neue Tabs zurückgesetzt")

    def update_current_tab_directory(self):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        directory = tab.refresh_current_working_directory()
        self.statusBar().showMessage(f"Tab-Ordner gespeichert: {directory}")
        self.save_settings()

    def current_terminal(self):
        active = getattr(self, "active_tab_widget", None)
        widget = active.currentWidget() if active is not None else None
        if isinstance(widget, TerminalTab):
            return widget
        widget = self.tab_widget.currentWidget() if hasattr(self, "tab_widget") else None
        return widget if isinstance(widget, TerminalTab) else None

    def close_current_tab(self):
        active = getattr(self, "active_tab_widget", None) or self.tab_widget
        self.close_tab(active.currentIndex(), active)

    def close_tab(self, index, tab_widget=None):
        tab_widget = tab_widget or getattr(self, "active_tab_widget", None) or self.tab_widget
        if index < 0 or index >= tab_widget.count():
            return
        tab = tab_widget.widget(index)
        if isinstance(tab, TerminalTab):
            tab.stop_process(fast=True)
        tab_widget.removeTab(index)
        if tab is not None:
            tab.deleteLater()
        self.cleanup_empty_detached_windows()
        if self.total_terminal_tab_count() == 0:
            self.new_tab(target_tab_widget=self.tab_widget)
        elif tab_widget.count() == 0 and self.active_tab_widget is tab_widget:
            self.active_tab_widget = self.tab_widget

    def show_tab_context_menu(self, pos, tab_widget=None):
        tab_widget = tab_widget or getattr(self, "active_tab_widget", None) or self.tab_widget
        self.active_tab_widget = tab_widget
        menu = QMenu(self)
        new_tab_action = QAction("Neuer Tab", self)
        new_tab_action.triggered.connect(self.new_tab)
        menu.addAction(new_tab_action)

        duplicate_tab_action = QAction("Tab duplizieren", self)
        duplicate_tab_action.triggered.connect(self.duplicate_current_tab)
        menu.addAction(duplicate_tab_action)

        rename_tab_action = QAction("Tab umbenennen", self)
        rename_tab_action.triggered.connect(self.rename_current_tab)
        menu.addAction(rename_tab_action)

        update_directory_action = QAction("Tab-Ordner aktualisieren", self)
        update_directory_action.triggered.connect(self.update_current_tab_directory)
        menu.addAction(update_directory_action)

        move_menu = menu.addMenu("In Ansicht verschieben")
        for pane in self.view_mode_pane_order():
            label = self.logical_pane_label(pane).capitalize()
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, p=pane: self.move_current_tab_to_pane(p))
            move_menu.addAction(action)
        move_menu.addSeparator()
        for label, pane in (
            ("Horizontal rechts", "right"),
            ("Vertikal unten", "bottom"),
            ("Raster: rechts oben", "top_right"),
            ("Raster: links unten", "bottom_left"),
            ("Raster: rechts unten", "bottom_right"),
        ):
            action = QAction(label, self)
            action.triggered.connect(lambda checked=False, p=pane: self.move_current_tab_to_pane(p))
            move_menu.addAction(action)

        move_split_action = QAction("In nächste Ansicht verschieben", self)
        move_split_action.triggered.connect(self.move_current_tab_to_other_view)
        menu.addAction(move_split_action)

        menu.addSeparator()
        if self.is_detached_tab_widget(tab_widget):
            reattach_action = QAction("Tab wieder ins Hauptfenster koppeln", self)
            reattach_action.triggered.connect(self.reattach_current_tab)
            menu.addAction(reattach_action)
        else:
            detach_action = QAction("Tab entkoppeln", self)
            detach_action.triggered.connect(self.detach_current_tab)
            menu.addAction(detach_action)

        close_tab_action = QAction("Aktuellen Tab schließen", self)
        close_tab_action.triggered.connect(self.close_current_tab)
        menu.addAction(close_tab_action)
        menu.exec(tab_widget.tabBar().mapToGlobal(pos))

    def current_tab_changed(self, index, tab_widget=None):
        if tab_widget is not None and index >= 0:
            self.active_tab_widget = tab_widget
        tab = self.current_terminal()
        if tab is not None:
            self.update_terminal_engine_ui()
            engine_label = self.terminal_engine_label_for_tab(tab)
            self.statusBar().showMessage(f"Shell-Backend: {self.shell_backend_label(tab.shell_type)} | Engine: {engine_label}")

    def search_current_output(self):
        tab = self.current_terminal()
        if isinstance(tab, TerminalTab):
            tab.show_output_search_dialog()

    def find_next_current_output(self):
        tab = self.current_terminal()
        if isinstance(tab, TerminalTab):
            tab.find_output_text(backward=False)

    def find_previous_current_output(self):
        tab = self.current_terminal()
        if isinstance(tab, TerminalTab):
            tab.find_output_text(backward=True)

    def clear_current_output(self):
        tab = self.current_terminal()
        if isinstance(tab, TerminalTab):
            tab.output_area.clear()
            self.show_status("Ausgabe geleert")

    def command_palette_entries(self):
        entries = [
            ("Neuer Tab", self.new_tab),
            ("Backend wechseln", self.select_shell),
            ("Ausgabe durchsuchen", self.search_current_output),
            ("Nächster Suchtreffer", self.find_next_current_output),
            ("Vorheriger Suchtreffer", self.find_previous_current_output),
            ("Ausgabe leeren", self.clear_current_output),
            ("Ausgabe speichern", self.save_current_output),
            ("Datei an aktuellen Prompt anhängen", self.attach_file_to_current_prompt),
            ("Design anpassen", self.show_theme_dialog),
            ("Hilfe öffnen", self.show_help_dialog),
            ("Profil: Aktuellen Tab speichern", self.save_current_tab_as_profile),
            ("Profil: Öffnen", self.open_profile_dialog),
            ("Profil: Löschen", self.delete_profile_dialog),
            ("Workspace: Aktuellen Workspace speichern", self.save_current_workspace),
            ("Workspace: Laden", self.load_workspace_dialog),
            ("Workspace: Löschen", self.delete_workspace_dialog),
        ]

        if self.ai_features_enabled:
            entries.extend([
                ("Ollama: Neuer Chat", self.new_ollama_chat_tab),
                ("Ollama: Modell wählen", self.select_ollama_model),
                ("Ollama: Gespräch löschen", self.clear_current_ollama_chat),
                ("Ollama: Kontext löschen", self.clear_current_ollama_context),
                ("Ollama: Systemprompt setzen", self.set_current_ollama_system_prompt),
                ("Ollama: Antwort stoppen", self.stop_current_ollama_response),
                ("Ollama: Chat als Markdown speichern", self.save_current_ollama_chat_markdown),
                ("Ollama: Letzten Codeblock kopieren", self.copy_last_ollama_code_block),
            ])

        for backend in self.available_shell_backends():
            shell_id = str(backend.get("id", "") or "")
            label = str(backend.get("label", "") or self.shell_backend_label(shell_id))
            entries.append((f"Neuer Tab: {label}", lambda s=shell_id: self.new_tab_with_backend(s)))

        for item in self.saved_paths:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or item.get("path", "") or "").strip()
            path = str(item.get("path", "") or "").strip()
            if not path:
                continue
            entries.append((f"Pfad öffnen: {name}", lambda p=path: self.open_saved_path(p)))
            entries.append((f"Pfad in neuem Tab öffnen: {name}", lambda p=path: self.open_saved_path_in_new_tab(p)))

        for profile in normalize_profiles(self.tab_profiles):
            label = profile_display_label(profile)
            entries.append((f"Profil öffnen: {label}", lambda p=profile: self.open_profile_in_new_tab(p)))

        for workspace in normalize_workspaces(self.workspaces):
            label = workspace_display_label(workspace)
            entries.append((f"Workspace laden: {label}", lambda w=workspace: self.load_workspace(w)))

        return entries

    def show_command_palette(self):
        entries = self.command_palette_entries()
        if not entries:
            self.show_status("Keine Aktionen verfügbar")
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("Befehlspalette")
        dialog.resize(620, 460)
        layout = QVBoxLayout(dialog)

        search = QLineEdit(dialog)
        search.setPlaceholderText("Aktion suchen, z. B. Tab, Pfad, Ollama, Suche ...")
        layout.addWidget(search)

        list_widget = QListWidget(dialog)
        layout.addWidget(list_widget)

        def refill():
            query = search.text().strip().lower()
            list_widget.clear()
            for label, callback in entries:
                if query and query not in label.lower():
                    continue
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, callback)
                list_widget.addItem(item)
            if list_widget.count() > 0:
                list_widget.setCurrentRow(0)

        def run_current():
            item = list_widget.currentItem()
            if item is None:
                return
            callback = item.data(Qt.ItemDataRole.UserRole)
            dialog.accept()
            if callable(callback):
                callback()

        search.textChanged.connect(refill)
        search.returnPressed.connect(run_current)
        list_widget.itemActivated.connect(lambda item: run_current())

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel, dialog)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        refill()
        search.setFocus()
        dialog.exec()

    def attach_file_to_current_prompt(self):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            self.show_status("Kein aktiver Terminal-Tab")
            return

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Datei an aktuellen Prompt anhängen",
            tab.refresh_current_working_directory() or str(Path.cwd()),
            "Textdateien (*.txt *.md *.py *.pyw *.json *.csv *.log *.sql *.xml *.html *.css *.js *.ts *.yaml *.yml *.toml *.ini *.bat *.cmd *.ps1 *.sh);;Alle Dateien (*)",
        )
        if not path:
            return

        try:
            file_context = read_text_file_context(path)
        except Exception as exc:
            self.show_status(f"Datei konnte nicht angehängt werden: {exc}")
            return

        current_prompt = tab.input_line.toPlainText()
        combined_prompt = append_file_context_to_prompt(current_prompt, file_context)
        tab.input_line.setPlainText(combined_prompt)
        tab.input_line.moveCursor(QTextCursor.MoveOperation.Start)
        if not str(current_prompt or "").strip():
            tab.input_line.setPlaceholderText("Frage zur angehängten Datei oberhalb des Kontextblocks eingeben …")
        tab.input_line.setFocus()
        self.show_status(f"Datei angehängt: {file_context.get('name', path)}")

    def stop_process(self):
        tab = self.current_terminal()
        if tab is not None:
            tab.stop_process(fast=True)

    def interrupt_current_command(self):
        tab = self.current_terminal()
        if tab is not None:
            tab.interrupt_current_command()

    def execute_command(self):
        tab = self.current_terminal()
        if tab is not None:
            tab.execute_command()

    def restart_shell(self, only_current=False):
        if only_current:
            tab = self.current_terminal()
            if isinstance(tab, TerminalTab):
                tab.restart_shell()
            return
        for _, _, tab in self.all_terminal_tabs():
            tab.restart_shell()

    def select_shell(self):
        options = self.available_shell_backends()
        if not options:
            return
        labels = [item["label"] for item in options]
        ids = [item["id"] for item in options]
        current_tab = self.current_terminal()
        current_shell = current_tab.shell_type if isinstance(current_tab, TerminalTab) else self.shell_type
        current_index = ids.index(current_shell) if current_shell in ids else 0
        selected_label, ok = QInputDialog.getItem(
            self,
            "Shell-Backend auswählen",
            "Shell-Backend für aktuellen Tab wählen:",
            labels,
            current_index,
            False,
        )
        if ok and selected_label:
            selected_index = labels.index(selected_label)
            selected_shell = self.normalize_shell_type(ids[selected_index])
            self.shell_type = selected_shell
            if isinstance(current_tab, TerminalTab):
                current_tab.shell_type = selected_shell
                current_tab.custom_title = ""
                current_tab.restart_shell()
            self.save_settings()

    def rename_current_tab(self):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        text, ok = QInputDialog.getText(
            self,
            "Tab umbenennen",
            "Neuer Tab-Name:",
            text=tab.custom_title or tab.title,
        )
        if ok:
            tab.custom_title = text.strip()
            tab.title = tab.custom_title or self.shell_backend_label(tab.shell_type)
            self.update_tab_title(tab)
            self.save_settings()

    def duplicate_current_tab(self):
        tab = self.current_terminal()
        if isinstance(tab, TerminalTab):
            title = f"{tab.custom_title or self.shell_backend_label(tab.shell_type)} Kopie"
            source_widget, _ = self.tab_widget_for_tab(tab)
            self.new_tab(
                shell_type=tab.shell_type,
                title=title,
                start_directory=tab.refresh_current_working_directory(),
                command_history=list(tab.command_history),
                restore_command=tab.current_restore_command(),
                venv_path=tab.current_venv_path(),
                terminal_engine=tab.actual_terminal_engine(),
                target_tab_widget=source_widget if source_widget is not None else self.active_tab_widget,
            )

    def restore_tabs_from_settings(self):
        restored = False
        for item in getattr(self, "saved_tabs", []):
            if not isinstance(item, dict):
                continue
            shell_type = self.normalize_shell_type(item.get("shell_type", self.shell_type) or self.shell_type)
            if not self.system_shell(shell_type):
                shell_type = self.shell_type
            title = str(item.get("title", "") or "")
            working_directory = str(item.get("working_directory", "") or "")
            tab = self.new_tab(
                shell_type=shell_type,
                title=title,
                start_directory=working_directory,
                command_history=item.get("command_history", []),
                restore_command=item.get("restore_command", ""),
                venv_path=item.get("venv_path", ""),
                terminal_engine=item.get("terminal_engine", self.terminal_engine),
                target_tab_widget=self.target_widget_for_saved_tab(item),
            )
            if isinstance(tab, TerminalTab):
                ollama_model = str(item.get("ollama_model", "") or "").strip()
                client_kind = str(item.get("client_mode_kind", "") or item.get("client_mode", "") or "").strip()
                if self.ai_features_enabled and (ollama_model or client_kind == "ollama_api"):
                    tab.start_ollama_prompt_mode(
                        ollama_model or self.selected_ollama_model,
                        system_prompt=str(item.get("ollama_system_prompt", "") or ""),
                    )
                else:
                    tab.schedule_restore_command(item.get("restore_command", ""))
            restored = True
        if not restored:
            self.new_tab()

    def tab_settings_item(self, tab, tab_widget, detached_window=None):
        item = {
            "shell_type": tab.shell_type,
            "terminal_engine": tab.actual_terminal_engine(),
            "title": tab.custom_title,
            "working_directory": str(getattr(tab, "current_working_directory", "") or tab.refresh_current_working_directory()),
            "command_history": list(tab.command_history)[-self.max_history_size:],
            "restore_command": tab.current_restore_command(),
            "venv_path": tab.current_venv_path(),
            "view_pane": self.logical_pane_for_widget(tab_widget),
        }
        if detached_window is not None:
            item["view_pane"] = "detached"
            item["detached_window"] = str(getattr(detached_window, "window_id", "") or "detached-1")
            item["detached_title"] = str(detached_window.windowTitle() or "Entkoppelte Tabs")
        if tab.client_mode_kind == "ollama_api" and tab.ollama_model:
            item.update({
                "client_mode_kind": "ollama_api",
                "ollama_model": tab.ollama_model,
                "ollama_system_prompt": tab.ollama_system_prompt,
            })
        return item

    def collect_tab_settings(self):
        tabs = []
        if not hasattr(self, "tab_widget"):
            return tabs
        for tab_widget in self.main_terminal_tab_widgets():
            for index in range(tab_widget.count()):
                tab = tab_widget.widget(index)
                if isinstance(tab, TerminalTab):
                    tabs.append(self.tab_settings_item(tab, tab_widget))
        for window in list(getattr(self, "detached_windows", [])):
            tab_widget = getattr(window, "tab_widget", None)
            if tab_widget is None:
                continue
            for index in range(tab_widget.count()):
                tab = tab_widget.widget(index)
                if isinstance(tab, TerminalTab):
                    tabs.append(self.tab_settings_item(tab, tab_widget, detached_window=window))
        return tabs

    def find_git_bash(self):
        candidates = [
            shutil.which("bash.exe"),
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files\Git\usr\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\usr\bin\bash.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        return None

    def _command_version_text(self, executable, args):
        try:
            result = subprocess.run(
                [executable, *args],
                capture_output=True,
                timeout=2,
            )
        except Exception:
            return ""

        raw = result.stdout or result.stderr or b""
        if not raw:
            return ""

        for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "cp850", "cp1252"):
            try:
                text = raw.decode(encoding, errors="replace")
                break
            except Exception:
                text = ""

        text = text.replace("\x00", "").strip()
        if not text:
            return ""

        return text.splitlines()[0].strip()

    def default_shell_type(self):
        """Return the best platform default shell backend for new tabs.

        On Linux, ShellDeck should prefer Bash when it is available. The
        previous Windows-oriented default of ``cmd`` could fall back to sh on
        Linux and then persisted tabs restored ``source .venv/bin/activate``
        in /bin/sh, where ``source`` does not exist.
        """
        if sys.platform != "win32":
            if shutil.which("bash"):
                return "bash"
            if shutil.which("sh"):
                return "sh"
            return "sh"
        if shutil.which("pwsh.exe"):
            return "pwsh"
        if shutil.which("powershell.exe"):
            return "powershell"
        return "cmd"

    def normalize_shell_type(self, shell_type=None):
        text = str(shell_type or "").strip().lower()
        known_shells = {"cmd", "powershell", "pwsh", "git_bash", "wsl", "bash", "zsh", "fish", "sh"}
        if text not in known_shells:
            return self.default_shell_type()
        if sys.platform != "win32":
            if text in {"cmd", "powershell", "pwsh", "git_bash", "wsl"}:
                return self.default_shell_type()
            if text == "sh" and shutil.which("bash"):
                return "bash"
        return text

    def normalize_restore_command_for_shell(self, command, shell_type=None):
        text = str(command or "").strip()
        if not text or sys.platform == "win32":
            return text
        shell = str(shell_type or self.shell_type or "").strip().lower()
        if shell in {"fish"}:
            return text
        # POSIX shells do not all support ``source``. Dot-sourcing works in
        # bash, zsh and /bin/sh, so old saved restore commands remain usable.
        return re.sub(r"^\s*source\s+", ". ", text, count=1)

    def available_shell_backends(self):
        options = []

        def add(shell_id, label, executable=None, args=None):
            executable = executable or self.system_shell(shell_id)
            if not executable:
                return

            # Versionen werden nur noch genutzt, wenn ausdrücklich gewünscht.
            # Für PowerShell/WSL vermeiden wir bewusst Versionsausgaben,
            # weil Windows je nach Umgebung kaputte Kodierungen liefern kann.
            version = ""
            if args is not None:
                version = self._command_version_text(executable, args)

            full_label = f"{label} — {version}" if version else label
            if shell_id not in [item["id"] for item in options]:
                options.append({
                    "id": shell_id,
                    "label": full_label,
                    "executable": executable,
                })

        if sys.platform == "win32":
            if shutil.which("powershell.exe"):
                add("powershell", "PowerShell", "powershell.exe", None)

            if shutil.which("pwsh.exe"):
                add("pwsh", "PowerShell 7", "pwsh.exe", None)

            if shutil.which("cmd.exe"):
                add("cmd", "CMD", "cmd.exe", None)

            git_bash = self.find_git_bash()
            if git_bash:
                add("git_bash", "Git Bash", git_bash, None)

            if shutil.which("wsl.exe"):
                add("wsl", "WSL", "wsl.exe", None)

        else:
            for shell_id, label in (
                ("bash", "Bash"),
                ("zsh", "Z Shell"),
                ("fish", "Fish"),
                ("sh", "sh"),
            ):
                executable = shutil.which(shell_id)
                if executable:
                    add(shell_id, label, executable, None)

        if not options:
            fallback = self.default_shell_type()
            options.append({
                "id": fallback,
                "label": self.shell_backend_label(fallback),
                "executable": self.system_shell(fallback) or fallback,
            })

        return options

    def shell_backend_label(self, shell_name=None) -> str:
        name = str(shell_name or self.shell_type or "Terminal").strip()
        lower = name.lower()
        if lower in ("powershell", "powershell.exe"):
            return "PowerShell"
        if lower in ("pwsh", "pwsh.exe"):
            return "PowerShell 7"
        if lower in ("cmd", "cmd.exe"):
            return "CMD"
        if lower in ("git_bash", "git bash"):
            return "Git Bash"
        if lower in ("bash", "bash.exe"):
            return "Bash"
        if lower in ("zsh",):
            return "Z Shell"
        if lower in ("fish",):
            return "Fish"
        if lower in ("wsl", "wsl.exe"):
            return "WSL"
        if lower in ("sh",):
            return "sh"
        return name or "Terminal"

    def shell_backend_icon(self, shell_type=None) -> str:
        lower = str(shell_type or self.shell_type or "").lower()
        return {
            "powershell": "⚡",
            "pwsh": "⚡",
            "cmd": "▣",
            "git_bash": "🟧",
            "wsl": "🐧",
            "bash": "🐚",
            "zsh": "🐚",
            "fish": "🐟",
            "sh": "🐚",
        }.get(lower, "▸")

    def shell_backend_color(self, shell_type=None) -> str:
        lower = str(shell_type or self.shell_type or "").lower()
        return {
            "powershell": "#7DD3FC",
            "pwsh": "#60A5FA",
            "cmd": "#D1D5DB",
            "git_bash": "#F59E0B",
            "wsl": "#86EFAC",
            "bash": "#34D399",
            "zsh": "#C084FC",
            "fish": "#67E8F9",
            "sh": "#A3A3A3",
        }.get(lower, "#FFFFFF")

    def terminal_engine_label(self, engine=None):
        value = str(engine or getattr(self, "terminal_engine", "qprocess") or "qprocess").lower().strip()
        if value == "pty":
            return "PTY/ConPTY experimentell"
        return "Standard QProcess"

    def terminal_engine_label_for_process(self, process=None):
        engine = str(getattr(process, "_shelldeck_engine", "") or "").lower().strip()
        return self.terminal_engine_label(engine or "qprocess")

    def current_terminal_engine(self):
        tab = self.current_terminal() if hasattr(self, "tab_widget") else None
        if isinstance(tab, TerminalTab):
            return tab.actual_terminal_engine()
        return self.normalize_terminal_engine(getattr(self, "terminal_engine", "qprocess"))

    def terminal_engine_label_for_tab(self, tab=None):
        if isinstance(tab, TerminalTab):
            return self.terminal_engine_label(tab.actual_terminal_engine())
        return self.terminal_engine_label(self.current_terminal_engine())

    def should_use_pty_backend(self, shell_type=None, engine=None):
        if self.normalize_terminal_engine(engine or getattr(self, "terminal_engine", "qprocess")) != "pty":
            return False
        message = PtyTerminalProcess.availability_message()
        if message:
            QTimer.singleShot(0, lambda m=message: self.show_status(f"PTY/ConPTY nicht aktiv: {m}"))
            return False
        return True

    def select_terminal_engine(self):
        options = [
            "Standard QProcess",
            "PTY/ConPTY/Linux-PTY experimentell",
        ]
        current_engine = self.current_terminal_engine()
        current_index = 1 if current_engine == "pty" else 0
        choice, ok = QInputDialog.getItem(
            self,
            "Terminal-Engine",
            "Engine für den aktuellen Tab:",
            options,
            current_index,
            False,
        )
        if not ok:
            return
        new_engine = "pty" if choice.startswith("PTY/") else "qprocess"
        self.set_terminal_engine(new_engine, show_message=True, save=True)

    def system_shell(self, shell_type=None) -> str:
        shell_type = self.normalize_shell_type(shell_type or self.shell_type)
        if sys.platform != "win32":
            if shell_type in ("bash", "zsh", "fish", "sh"):
                return shutil.which(shell_type) or shell_type
            # Unter Linux bevorzugen wir Bash als Standard, weil sie source,
            # History-/Prompt-Verhalten und typische venv-Workflows besser
            # abdeckt als /bin/sh. Die konkrete Login-Shell bleibt nur Fallback.
            return shutil.which("bash") or os.environ.get("SHELL") or shutil.which("sh") or "sh"
        shell_map = {
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "pwsh": "pwsh.exe",
            "wsl": "wsl.exe",
        }
        if shell_type == "git_bash":
            return self.find_git_bash() or "bash.exe"
        executable = shell_map.get(shell_type, "cmd.exe")
        if shutil.which(executable) is not None:
            return executable
        for fallback in ("pwsh.exe", "powershell.exe", "cmd.exe"):
            if shutil.which(fallback) is not None:
                return fallback
        return "cmd.exe"

    def shell_start_args(self, shell_type=None):
        lower = str(shell_type or self.shell_type or "").lower()
        if sys.platform == "win32":
            if lower in {"powershell", "pwsh"}:
                return ["-NoLogo"]
        if lower == "bash":
            return ["--noprofile", "--norc", "-i"]
        return []

    def new_tab_with_backend(self, shell_type):
        self.new_tab(shell_type=shell_type)

    def rebuild_new_backend_tab_menu(self):
        if not hasattr(self, "new_backend_tab_menu"):
            return
        self.new_backend_tab_menu.clear()
        for item in self.available_shell_backends():
            shell_id = str(item.get("id", "") or "")
            label = str(item.get("label", "") or self.shell_backend_label(shell_id))
            icon = self.shell_backend_icon(shell_id)
            action = QAction(f"{icon} {label}".strip(), self)
            action.triggered.connect(lambda checked=False, s=shell_id: self.new_tab_with_backend(s))
            self.new_backend_tab_menu.addAction(action)
        if not self.new_backend_tab_menu.actions():
            action = QAction("Keine Backends gefunden", self)
            action.setEnabled(False)
            self.new_backend_tab_menu.addAction(action)

    def load_history(self):
        if self.history_file.exists():
            try:
                lines = self.history_file.read_text(encoding="utf-8").splitlines()
                lines = [line for line in lines if line.strip()]
                self.history = lines[-self.max_history_size:]
            except Exception:
                self.history = []
        else:
            self.history = []

    def save_history(self):
        try:
            history_to_save = self.history[-self.max_history_size:]
            self.history_file.write_text("\n".join(history_to_save), encoding="utf-8")
        except Exception:
            pass

    def default_theme_config(self):
        return {
            "light": {
                "accent": "#339CFF",
                "background": "#FFFFFF",
                "foreground": "#1A1C1F",
                "input_background": "#F3F3F3",
                "terminal_colors": {
                    "stdout": "#1A1C1F",
                    "stderr": "#B42318",
                    "input_text": "#1A1C1F",
                    "command": "#2563EB",
                    "path": "#15803D",
                    "number": "#7C3AED",
                    "error_word": "#B42318",
                    "selection": "#BBD7FF",
                },
                "background_opacity": 100,
                "contrast": 45,
                "transparent_sidebar": True,
                "ui_font": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                "code_font": "ui-monospace, SFMono-Regular, Consolas, monospace",
            },
            "dark": {
                "accent": "#339CFF",
                "background": "#181818",
                "foreground": "#FFFFFF",
                "input_background": "#202020",
                "terminal_colors": {
                    "stdout": "#FFFFFF",
                    "stderr": "#FCA5A5",
                    "input_text": "#FFFFFF",
                    "command": "#7DD3FC",
                    "path": "#86EFAC",
                    "number": "#C084FC",
                    "error_word": "#FCA5A5",
                    "selection": "#2D5F93",
                },
                "background_opacity": 100,
                "contrast": 60,
                "transparent_sidebar": True,
                "ui_font": "-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif",
                "code_font": "ui-monospace, SFMono-Regular, Consolas, monospace",
            },
        }

    def merge_theme_config(self, loaded_config):
        merged = self.default_theme_config()
        if not isinstance(loaded_config, dict):
            return merged

        for mode in ("light", "dark"):
            values = loaded_config.get(mode)
            if isinstance(values, dict):
                merged[mode].update(values)
                merged[mode]["accent"] = self.normalize_hex_color(merged[mode].get("accent"), merged[mode]["accent"])
                merged[mode]["background"] = self.normalize_hex_color(merged[mode].get("background"), merged[mode]["background"])
                merged[mode]["foreground"] = self.normalize_hex_color(merged[mode].get("foreground"), merged[mode]["foreground"])
                merged[mode]["input_background"] = self.normalize_hex_color(merged[mode].get("input_background"), merged[mode]["input_background"])
                merged[mode]["terminal_colors"] = self.merge_terminal_colors(
                    merged[mode].get("terminal_colors"),
                    self.default_theme_config()[mode].get("terminal_colors", {}),
                )
                try:
                    merged[mode]["background_opacity"] = max(0, min(100, int(merged[mode].get("background_opacity", 100))))
                except (TypeError, ValueError):
                    merged[mode]["background_opacity"] = self.default_theme_config()[mode].get("background_opacity", 100)
                try:
                    merged[mode]["contrast"] = max(0, min(100, int(merged[mode].get("contrast", 50))))
                except (TypeError, ValueError):
                    merged[mode]["contrast"] = self.default_theme_config()[mode]["contrast"]
                merged[mode]["transparent_sidebar"] = bool(merged[mode].get("transparent_sidebar", True))
        return merged

    def normalize_hex_color(self, value, fallback):
        text = str(value or "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
            return text.upper()
        if re.fullmatch(r"[0-9a-fA-F]{6}", text):
            return f"#{text.upper()}"
        return fallback

    def theme_key_from_scheme(self, scheme_name=None):
        name = self.normalize_color_scheme_name(scheme_name or self.color_scheme_name or "Dunkel")
        if name == "Hell":
            return "light"
        if name == "System":
            return self.system_theme_key()
        return "dark"

    def current_theme_key(self):
        if self.theme_mode == "system":
            return self.system_theme_key()
        if self.theme_mode in ("light", "dark"):
            return self.theme_mode
        return self.theme_key_from_scheme()

    def active_theme(self):
        key = self.current_theme_key()
        return self.theme_config.get(key, self.default_theme_config()[key])

    def default_terminal_colors(self):
        return self.default_theme_config()[self.current_theme_key()].get("terminal_colors", {}).copy()

    def merge_terminal_colors(self, loaded_colors, defaults=None):
        merged = dict(defaults or {
            "stdout": "#FFFFFF",
            "stderr": "#FCA5A5",
            "input_text": "#FFFFFF",
            "command": "#7DD3FC",
            "path": "#86EFAC",
            "number": "#C084FC",
            "error_word": "#FCA5A5",
            "selection": "#2D5F93",
        })
        if isinstance(loaded_colors, dict):
            for key in list(merged.keys()):
                merged[key] = self.normalize_hex_color(loaded_colors.get(key), merged[key])
        return merged

    def terminal_colors(self):
        theme = self.active_theme()
        return self.merge_terminal_colors(theme.get("terminal_colors"), self.default_terminal_colors())

    def terminal_color(self, key, fallback):
        return self.normalize_hex_color(self.terminal_colors().get(key), fallback)

    def load_settings(self):
        if not self.settings_file.exists():
            self.apply_theme_settings_mapping(self.load_theme_persistent_settings())
            self.apply_pre_command_settings_mapping(self.load_pre_command_persistent_settings())
            self.workspaces = self.merge_workspaces_by_name(self.workspaces, self.load_persistent_workspaces())
            return

        try:
            settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.apply_theme_settings_mapping(self.load_theme_persistent_settings())
            self.apply_pre_command_settings_mapping(self.load_pre_command_persistent_settings())
            self.workspaces = self.merge_workspaces_by_name(self.workspaces, self.load_persistent_workspaces())
            return

        font_text = str(settings.get("font", "")).strip()
        if font_text:
            font = QFont()
            if font.fromString(font_text):
                self.terminal_font = font

        self._window_geometry_restored = False
        geometry_text = str(settings.get("window_geometry", "") or "").strip()
        if geometry_text:
            try:
                geometry_bytes = QByteArray.fromBase64(geometry_text.encode("ascii"))
                self._window_geometry_restored = bool(self.restoreGeometry(geometry_bytes))
            except Exception:
                self._window_geometry_restored = False

        self.default_command = str(settings.get("default_command", self.default_command or "") or "")
        self.color_scheme_name = self.normalize_color_scheme_name(settings.get("color_scheme_name", self.color_scheme_name or "Dunkel"))
        self.theme_config = self.merge_theme_config(settings.get("theme_config", self.theme_config))

        loaded_theme_mode = str(settings.get("theme_mode", "") or "").lower().strip()
        if loaded_theme_mode in ("light", "dark", "system"):
            self.theme_mode = loaded_theme_mode
        else:
            self.theme_mode = self.theme_key_from_scheme(self.color_scheme_name)
        self.apply_theme_settings_mapping(self.load_theme_persistent_settings())

        try:
            self.window_opacity = max(20, min(100, int(settings.get("window_opacity", self.window_opacity))))
        except (TypeError, ValueError):
            self.window_opacity = 100

        self.migrate_unreadable_theme_settings()

        try:
            self.max_history_size = max(1, int(settings.get("max_history_size", self.max_history_size)))
        except (TypeError, ValueError):
            self.max_history_size = 1000

        self.history = self.history[-self.max_history_size:]

        engine_value = str(settings.get("terminal_engine", self.terminal_engine or "qprocess") or "qprocess").lower().strip()
        self.terminal_engine = engine_value if engine_value in {"qprocess", "pty"} else "qprocess"
        self.apply_terminal_engine_settings_mapping(self.load_terminal_engine_persistent_settings())

        shell_type_val = self.normalize_shell_type(settings.get("shell_type", self.shell_type))
        if self.system_shell(shell_type_val):
            self.shell_type = shell_type_val

        saved_tabs = settings.get("tabs", [])
        self.saved_tabs = saved_tabs if isinstance(saved_tabs, list) else []
        layout_mode = str(settings.get("view_layout_mode", self.view_layout_mode) or "single")
        self.view_layout_mode = layout_mode if layout_mode in {"single", "horizontal", "vertical", "quad"} else "single"

        saved_paths = settings.get("saved_paths", [])
        self.saved_paths = [
            self._normalize_saved_path_item(item.get("name", ""), item.get("path", ""))
            for item in saved_paths
            if isinstance(item, dict) and str(item.get("path", "")).strip()
        ] if isinstance(saved_paths, list) else []

        self.default_start_directory = str(settings.get("default_start_directory", self.default_start_directory or "") or "")
        self.selected_ollama_model = str(settings.get("selected_ollama_model", self.selected_ollama_model or "") or "")
        self.ai_features_enabled = bool(settings.get("ai_features_enabled", False))
        self.apply_pre_command_settings_mapping(settings)
        self.apply_pre_command_settings_mapping(self.load_pre_command_persistent_settings())
        self.tab_profiles = normalize_profiles(settings.get("tab_profiles", self.tab_profiles))
        settings_workspaces = normalize_workspaces(settings.get("workspaces", self.workspaces))
        stored_workspaces = self.load_persistent_workspaces()
        self.workspaces = self.merge_workspaces_by_name(settings_workspaces, stored_workspaces)

    def save_settings(self):
        self.sync_pre_command_state_from_ui()
        pre_command_settings = self.pre_command_settings_snapshot()
        terminal_engine_settings = self.terminal_engine_settings_snapshot()
        theme_settings = self.theme_settings_snapshot()
        self.save_pre_command_persistent_settings(pre_command_settings)
        self.save_terminal_engine_persistent_settings(terminal_engine_settings)
        self.save_theme_persistent_settings(theme_settings)
        settings = {
            "font": self.terminal_font.toString(),
            **theme_settings,
            "theme_config": self.theme_config,
            "window_opacity": self.window_opacity,
            "default_command": self.default_command,
            "max_history_size": self.max_history_size,
            "shell_type": self.shell_type,
            "window_geometry": bytes(self.saveGeometry().toBase64()).decode("ascii"),
            **terminal_engine_settings,
            "tabs": self.collect_tab_settings(),
            "view_layout_mode": getattr(self, "view_layout_mode", "single"),
            "saved_paths": self.saved_paths,
            "default_start_directory": self.default_start_directory,
            "selected_ollama_model": self.selected_ollama_model,
            "ai_features_enabled": self.ai_features_enabled,
            **pre_command_settings,
            "tab_profiles": normalize_profiles(self.tab_profiles),
            "workspaces": normalize_workspaces(self.workspaces),
        }

        try:
            self.settings_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_file = self.settings_file.with_suffix(self.settings_file.suffix + ".tmp")
            tmp_file.write_text(
                json.dumps(settings, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
            tmp_file.replace(self.settings_file)
            return True
        except OSError as exc:
            self.show_status(f"Einstellungen konnten nicht gespeichert werden: {exc}")
            return False

    def migrate_unreadable_theme_settings(self):
        defaults = self.default_theme_config()
        for mode in ("light", "dark"):
            theme = self.theme_config.setdefault(mode, defaults[mode].copy())
            accent = self.normalize_hex_color(theme.get("accent"), defaults[mode]["accent"])
            background = self.normalize_hex_color(theme.get("background"), defaults[mode]["background"])
            input_background = self.normalize_hex_color(theme.get("input_background"), defaults[mode]["input_background"])
            foreground = self.normalize_hex_color(theme.get("foreground"), defaults[mode]["foreground"])
            try:
                contrast = max(0, min(100, int(theme.get("contrast", defaults[mode]["contrast"]))))
            except (TypeError, ValueError):
                contrast = defaults[mode]["contrast"]

            old_high_contrast = (
                mode == "dark"
                and accent == "#FFFF00"
                and background == "#000000"
                and input_background == "#000000"
                and contrast >= 90
            )
            if accent == "#FFFF00":
                theme["accent"] = defaults[mode]["accent"]
            if old_high_contrast:
                theme.update(defaults["dark"])
            elif foreground == "#FFFF00":
                theme["foreground"] = defaults[mode]["foreground"]

    def reset_theme_defaults(self):
        self.theme_config = self.default_theme_config()
        self.theme_mode = "dark"
        self.color_scheme_name = "Dunkel"
        self.window_opacity = 100
        self.apply_color_scheme()
        self.save_settings()

    def readable_border_color(self, background):
        color = QColor(background)
        if not color.isValid():
            return "#3A3A3A"
        brightness = color.red() * 0.299 + color.green() * 0.587 + color.blue() * 0.114
        return "#D0D0D0" if brightness >= 128 else "#3A3A3A"

    def rgba_color(self, hex_color, opacity_percent):
        color = QColor(hex_color)
        if not color.isValid():
            color = QColor("#181818")
        try:
            opacity = max(0, min(100, int(opacity_percent)))
        except (TypeError, ValueError):
            opacity = 100
        return f"rgba({color.red()}, {color.green()}, {color.blue()}, {opacity / 100.0:.2f})"

    def apply_application_palette(self, background, foreground, accent, input_background, background_opacity):
        """Apply the selected ShellDeck theme to Qt's application chrome.

        Unter Linux folgen Menüs, Comboboxen und Dialoge sonst oft weiterhin
        dem hellen Desktop-Theme. Eine zentrale Palette plus globales
        Stylesheet sorgt dafür, dass Dunkel/Hell/Hoher Kontrast überall
        sichtbar wird und nicht nur im Terminal-Ausgabefeld.
        """
        app = QApplication.instance()
        if app is None:
            return

        border = self.readable_border_color(background)
        muted = self.rgba_color(foreground, 70)
        hover = self.rgba_color(accent, 25)
        panel = self.rgba_color(input_background, max(background_opacity, 92))
        base = self.rgba_color(background, max(background_opacity, 96))

        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor(background))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(foreground))
        palette.setColor(QPalette.ColorRole.Base, QColor(input_background))
        palette.setColor(QPalette.ColorRole.AlternateBase, QColor(background))
        palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(input_background))
        palette.setColor(QPalette.ColorRole.ToolTipText, QColor(foreground))
        palette.setColor(QPalette.ColorRole.Text, QColor(foreground))
        palette.setColor(QPalette.ColorRole.Button, QColor(input_background))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(foreground))
        palette.setColor(QPalette.ColorRole.BrightText, QColor("#FFFFFF"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(accent))
        palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#FFFFFF"))
        app.setPalette(palette)

        app.setStyleSheet(
            "QMainWindow, QDialog, QWidget {"
            f" background-color: {base};"
            f" color: {foreground};"
            "}"
            "QMenuBar {"
            f" background-color: {base};"
            f" color: {foreground};"
            " border: 0;"
            " padding: 2px;"
            "}"
            "QMenuBar::item {"
            " padding: 4px 8px;"
            " background: transparent;"
            "}"
            "QMenuBar::item:selected, QMenuBar::item:pressed {"
            f" background-color: {hover};"
            f" color: {foreground};"
            " border-radius: 4px;"
            "}"
            "QMenu {"
            f" background-color: {panel};"
            f" color: {foreground};"
            f" border: 1px solid {border};"
            " padding: 4px;"
            "}"
            "QMenu::item {"
            " padding: 5px 22px 5px 22px;"
            "}"
            "QMenu::item:selected {"
            f" background-color: {accent};"
            " color: #FFFFFF;"
            "}"
            "QMenu::separator {"
            f" background-color: {border};"
            " height: 1px;"
            " margin: 5px 8px;"
            "}"
            "QToolBar {"
            f" background-color: {base};"
            f" color: {foreground};"
            f" border-bottom: 1px solid {border};"
            "}"
            "QLabel, QCheckBox, QRadioButton, QGroupBox {"
            f" color: {foreground};"
            "}"
            "QLineEdit, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit, QListWidget {"
            f" background-color: {panel};"
            f" color: {foreground};"
            f" border: 1px solid {border};"
            " border-radius: 4px;"
            " padding: 3px;"
            f" selection-background-color: {accent};"
            " selection-color: #FFFFFF;"
            "}"
            "QComboBox {"
            f" background-color: {panel};"
            f" color: {foreground};"
            f" border: 1px solid {border};"
            " border-radius: 4px;"
            " padding: 3px 20px 3px 3px;"
            f" selection-background-color: {accent};"
            " selection-color: #FFFFFF;"
            "}"
            "QComboBox QAbstractItemView {"
            f" background-color: {panel};"
            f" color: {foreground};"
            f" border: 1px solid {border};"
            f" selection-background-color: {accent};"
            " selection-color: #FFFFFF;"
            "}"
            "QPushButton {"
            f" background-color: {accent};"
            " color: #FFFFFF;"
            " border: none;"
            " border-radius: 5px;"
            " padding: 5px 10px;"
            "}"
            "QPushButton:hover {"
            f" background-color: {self.rgba_color(accent, 85)};"
            "}"
            "QPushButton:disabled {"
            f" background-color: {border};"
            f" color: {self.rgba_color(foreground, 55)};"
            "}"
            "QTabWidget::pane {"
            f" border: 1px solid {border};"
            "}"
            "QStatusBar {"
            f" background-color: {base};"
            f" color: {foreground};"
            f" border-top: 1px solid {border};"
            "}"
            "QScrollBar:vertical, QScrollBar:horizontal {"
            f" background-color: {base};"
            " width: 12px;"
            " height: 12px;"
            "}"
            "QScrollBar::handle:vertical, QScrollBar::handle:horizontal {"
            f" background-color: {border};"
            " border-radius: 5px;"
            " min-height: 24px;"
            " min-width: 24px;"
            "}"
            "QScrollBar::add-line, QScrollBar::sub-line {"
            " width: 0px; height: 0px;"
            "}"
        )

    def apply_color_scheme(self):
        theme = self.active_theme()
        background = self.normalize_hex_color(theme.get("background"), "#181818")
        foreground = self.normalize_hex_color(theme.get("foreground"), "#FFFFFF")
        input_background = self.normalize_hex_color(theme.get("input_background"), background)
        accent = self.normalize_hex_color(theme.get("accent"), "#339CFF")
        try:
            background_opacity = max(0, min(100, int(theme.get("background_opacity", 100))))
        except (TypeError, ValueError):
            background_opacity = 100
        translucent = background_opacity < 100

        self.apply_application_palette(background, foreground, accent, input_background, background_opacity)

        try:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, translucent)
            self.central_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, translucent)
            self.central_widget.setStyleSheet("background: transparent;" if translucent else "")
        except Exception:
            pass

        tab_style = (
            "QTabWidget::pane {"
            f" border: 1px solid {self.readable_border_color(background)};"
            " border-radius: 6px;"
            "}"
            "QTabBar::tab {"
            f" background-color: {self.rgba_color(background, max(background_opacity, 85))};"
            f" color: {foreground};"
            " padding: 6px 12px;"
            " border-top-left-radius: 6px;"
            " border-top-right-radius: 6px;"
            " margin-right: 2px;"
            "}"
            "QTabBar::tab:selected {"
            f" background-color: {accent};"
            " color: white;"
            "}"
        )
        for tab_widget in self.terminal_tab_widgets():
            tab_widget.setStyleSheet(tab_style)

        for _, _, tab in self.all_terminal_tabs():
            tab.apply_theme()

        try:
            self.setWindowOpacity(max(0.2, min(1.0, self.window_opacity / 100.0)))
        except Exception:
            pass

    def show_font_dialog(self):
        result = QFontDialog.getFont(self.terminal_font, self, "Terminal Schriftart wählen")
        if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[0], bool):
            ok, font = result[0], result[1]
        else:
            font, ok = result
        if ok:
            self.terminal_font = font
            for _, _, tab in self.all_terminal_tabs():
                tab.set_terminal_font(font)
            self.save_settings()

    def show_color_dialog(self):
        schemes = ["System", "Dunkel", "Hell", "Hoher Kontrast"]
        current_scheme = self.normalize_color_scheme_name(self.color_scheme_name)
        current_index = schemes.index(current_scheme) if current_scheme in schemes else 1
        scheme, ok = QInputDialog.getItem(
            self,
            "Farbschema",
            "Farbschema auswählen:",
            schemes,
            current_index,
            False,
        )
        if ok and scheme:
            scheme = self.normalize_color_scheme_name(scheme)
            self.color_scheme_name = scheme
            if scheme == "System":
                self.theme_mode = "system"
            elif scheme == "Hell":
                self.theme_mode = "light"
            elif scheme == "Hoher Kontrast":
                self.theme_mode = "dark"
                self.theme_config["dark"].update({
                    "background": "#101010",
                    "foreground": "#FFFFFF",
                    "input_background": "#181818",
                    "accent": "#339CFF",
                    "contrast": 85,
                })
            else:
                self.theme_mode = "dark"
            self.apply_color_scheme()
            self.save_settings()

    def show_theme_dialog(self):
        original_theme_mode = self.theme_mode
        original_theme_config = json.loads(json.dumps(self.theme_config))
        original_window_opacity = self.window_opacity

        dialog = QDialog(self)
        dialog.setWindowTitle("Design anpassen")
        layout = QFormLayout(dialog)

        mode_combo = QComboBox(dialog)
        mode_combo.addItem("Hell", "light")
        mode_combo.addItem("Dunkel", "dark")
        mode_combo.addItem("System", "system")
        mode_index = mode_combo.findData(self.theme_mode)
        mode_combo.setCurrentIndex(mode_index if mode_index >= 0 else 1)
        layout.addRow("Motiv:", mode_combo)

        preview_label = QLabel(dialog)
        preview_label.setText("Vorschau: Terminal-Design")
        preview_label.setMinimumHeight(34)
        layout.addRow("Vorschau:", preview_label)

        def selected_theme_key():
            value = mode_combo.currentData()
            if value == "light":
                return "light"
            if value == "system":
                return self.current_theme_key()
            return "dark"

        def update_button_style(button, color):
            button.setText(color)
            button.setStyleSheet(
                "QPushButton {"
                f" background-color: {color};"
                f" color: {'#000000' if QColor(color).lightness() > 150 else '#FFFFFF'};"
                " border: 1px solid #666666;"
                " border-radius: 5px;"
                " padding: 5px 10px;"
                "}"
            )

        def make_color_row(label, key):
            button = QPushButton(dialog)

            def choose_color():
                theme_key = selected_theme_key()
                current = QColor(self.theme_config[theme_key].get(key, "#000000"))
                color = QColorDialog.getColor(current, self, label)
                if color.isValid():
                    self.theme_config[theme_key][key] = color.name().upper()
                    refresh_controls_from_theme()
                    self.apply_color_scheme()

            button.clicked.connect(choose_color)
            layout.addRow(f"{label}:", button)
            return button

        accent_button = make_color_row("Akzent", "accent")
        background_button = make_color_row("Hintergrund", "background")
        foreground_button = make_color_row("Vordergrund", "foreground")
        input_button = make_color_row("Eingabefeld", "input_background")

        terminal_color_buttons = {}

        def make_terminal_color_row(label, key):
            button = QPushButton(dialog)

            def choose_color():
                theme_key = selected_theme_key()
                terminal_colors = self.theme_config[theme_key].setdefault(
                    "terminal_colors",
                    self.default_theme_config()[theme_key].get("terminal_colors", {}).copy(),
                )
                current = QColor(terminal_colors.get(key, "#FFFFFF"))
                color = QColorDialog.getColor(current, self, label)
                if color.isValid():
                    terminal_colors[key] = color.name().upper()
                    refresh_controls_from_theme()
                    self.apply_color_scheme()

            button.clicked.connect(choose_color)
            layout.addRow(f"{label}:", button)
            terminal_color_buttons[key] = button
            return button

        make_terminal_color_row("Standardausgabe", "stdout")
        make_terminal_color_row("Fehlerausgabe", "stderr")
        make_terminal_color_row("Eingabetext", "input_text")
        make_terminal_color_row("Befehle", "command")
        make_terminal_color_row("Pfade", "path")
        make_terminal_color_row("Zahlen", "number")
        make_terminal_color_row("Fehler-Wörter", "error_word")
        make_terminal_color_row("Auswahl-Markierung", "selection")

        contrast_row = QWidget(dialog)
        contrast_layout = QHBoxLayout(contrast_row)
        contrast_layout.setContentsMargins(0, 0, 0, 0)
        contrast_slider = QSlider(Qt.Orientation.Horizontal, dialog)
        contrast_slider.setRange(0, 100)
        contrast_slider.setSingleStep(5)
        contrast_slider.setPageStep(5)
        contrast_value = QLabel(dialog)
        contrast_layout.addWidget(contrast_slider)
        contrast_layout.addWidget(contrast_value)
        layout.addRow("Kontrast:", contrast_row)

        background_opacity_row = QWidget(dialog)
        background_opacity_layout = QHBoxLayout(background_opacity_row)
        background_opacity_layout.setContentsMargins(0, 0, 0, 0)
        background_opacity_slider = QSlider(Qt.Orientation.Horizontal, dialog)
        background_opacity_slider.setRange(0, 100)
        background_opacity_slider.setSingleStep(5)
        background_opacity_slider.setPageStep(5)
        background_opacity_slider.setTickInterval(5)
        background_opacity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        background_opacity_value = QLabel(dialog)
        background_opacity_layout.addWidget(background_opacity_slider)
        background_opacity_layout.addWidget(background_opacity_value)
        layout.addRow("Hintergrund-Deckkraft:", background_opacity_row)

        opacity_row = QWidget(dialog)
        opacity_layout = QHBoxLayout(opacity_row)
        opacity_layout.setContentsMargins(0, 0, 0, 0)
        opacity_slider = QSlider(Qt.Orientation.Horizontal, dialog)
        opacity_slider.setRange(20, 100)
        opacity_slider.setSingleStep(5)
        opacity_slider.setPageStep(5)
        opacity_slider.setTickInterval(5)
        opacity_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        opacity_value = QLabel(dialog)
        opacity_layout.addWidget(opacity_slider)
        opacity_layout.addWidget(opacity_value)
        layout.addRow("Fenster-Transparenz:", opacity_row)

        transparent_check = QCheckBox("abgerundete/leichte Oberfläche verwenden", dialog)
        layout.addRow("Transparente Oberfläche:", transparent_check)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            dialog,
        )
        layout.addRow(buttons)

        def refresh_controls_from_theme():
            theme = self.theme_config[selected_theme_key()]
            update_button_style(accent_button, self.normalize_hex_color(theme.get("accent"), "#339CFF"))
            update_button_style(background_button, self.normalize_hex_color(theme.get("background"), "#181818"))
            update_button_style(foreground_button, self.normalize_hex_color(theme.get("foreground"), "#FFFFFF"))
            update_button_style(input_button, self.normalize_hex_color(theme.get("input_background"), "#202020"))
            terminal_colors = self.merge_terminal_colors(
                theme.get("terminal_colors"),
                self.default_theme_config()[selected_theme_key()].get("terminal_colors", {}),
            )
            for key, button in terminal_color_buttons.items():
                update_button_style(button, terminal_colors.get(key, "#FFFFFF"))
            contrast_slider.blockSignals(True)
            background_opacity_slider.blockSignals(True)
            transparent_check.blockSignals(True)
            contrast_slider.setValue(max(0, min(100, int(theme.get("contrast", 60)))))
            background_opacity_slider.setValue(max(0, min(100, int(theme.get("background_opacity", 100)))))
            contrast_value.setText(str(contrast_slider.value()))
            background_opacity_value.setText(f"{background_opacity_slider.value()} %")
            transparent_check.setChecked(bool(theme.get("transparent_sidebar", True)))
            contrast_slider.blockSignals(False)
            background_opacity_slider.blockSignals(False)
            transparent_check.blockSignals(False)
            preview_label.setStyleSheet(
                "QLabel {"
                f" background-color: {self.rgba_color(theme.get('background', '#181818'), theme.get('background_opacity', 100))};"
                f" color: {theme.get('foreground', '#FFFFFF')};"
                f" border: 1px solid {theme.get('accent', '#339CFF')};"
                " border-radius: 6px;"
                " padding: 6px;"
                "}"
            )

        def mode_changed():
            self.theme_mode = str(mode_combo.currentData() or "dark")
            refresh_controls_from_theme()
            self.apply_color_scheme()

        def contrast_changed(value):
            self.theme_config[selected_theme_key()]["contrast"] = int(value)
            contrast_value.setText(str(value))
            self.apply_color_scheme()

        def background_opacity_changed(value):
            snapped = max(0, min(100, int(round(value / 5) * 5)))
            if snapped != value:
                background_opacity_slider.blockSignals(True)
                background_opacity_slider.setValue(snapped)
                background_opacity_slider.blockSignals(False)
            self.theme_config[selected_theme_key()]["background_opacity"] = snapped
            background_opacity_value.setText(f"{snapped} %")
            refresh_controls_from_theme()
            self.apply_color_scheme()

        def opacity_changed(value):
            snapped = max(20, min(100, int(round(value / 5) * 5)))
            if snapped != value:
                opacity_slider.blockSignals(True)
                opacity_slider.setValue(snapped)
                opacity_slider.blockSignals(False)
            self.window_opacity = snapped
            opacity_value.setText(f"{snapped} %")
            self.apply_color_scheme()

        def transparent_changed(checked):
            self.theme_config[selected_theme_key()]["transparent_sidebar"] = bool(checked)
            self.apply_color_scheme()

        mode_combo.currentIndexChanged.connect(mode_changed)
        contrast_slider.valueChanged.connect(contrast_changed)
        background_opacity_slider.valueChanged.connect(background_opacity_changed)
        opacity_slider.valueChanged.connect(opacity_changed)
        transparent_check.toggled.connect(transparent_changed)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        opacity_slider.setValue(self.window_opacity)
        opacity_value.setText(f"{self.window_opacity} %")
        refresh_controls_from_theme()

        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self.theme_mode == "light":
                self.color_scheme_name = "Hell"
            elif self.theme_mode == "dark":
                self.color_scheme_name = "Dunkel"
            self.save_settings()
        else:
            self.theme_mode = original_theme_mode
            self.theme_config = original_theme_config
            self.window_opacity = original_window_opacity
            self.apply_color_scheme()

    def show_command_dialog(self):
        text, ok = QInputDialog.getText(
            self,
            "Standardbefehl",
            "Standardbefehl beim Start eingeben:",
            text=self.default_command,
        )
        if ok:
            self.default_command = text.strip()
            self.save_settings()

    def show_history_dialog(self):
        size, ok = QInputDialog.getInt(
            self,
            "History-Größe",
            "Maximale Anzahl an History-Einträgen:",
            self.max_history_size,
            1,
            10000,
            1,
        )
        if ok:
            self.max_history_size = size
            self.history = self.history[-self.max_history_size:]
            for _, _, tab in self.all_terminal_tabs():
                tab.command_history = tab.command_history[-self.max_history_size:]
            self.save_history()
            self.save_settings()

    def ollama_models(self):
        return list_ollama_models()

    def choose_ollama_model(self):
        if not self.ensure_ai_features_enabled():
            return ""
        models = self.ollama_models()
        if not models:
            model, ok = QInputDialog.getText(
                self,
                "Ollama-Modell",
                "Kein Modell über 'ollama list' gefunden oder Ollama ist nicht im PATH. Modellname manuell eingeben:",
                text=self.selected_ollama_model or "gemma3:1b",
            )
            return model.strip() if ok and model.strip() else ""
        current = self.selected_ollama_model if self.selected_ollama_model in models else models[0]
        index = models.index(current) if current in models else 0
        model, ok = QInputDialog.getItem(
            self,
            "Ollama-Modell wählen",
            "Modell:",
            models,
            index,
            False,
        )
        return str(model or "").strip() if ok else ""

    def select_ollama_model(self):
        model = self.choose_ollama_model()
        if not model:
            return
        self.selected_ollama_model = model
        self.statusBar().showMessage(f"Ollama-Modell gewählt: {model}")
        self.save_settings()

    def new_ollama_chat_tab(self):
        model = self.choose_ollama_model() or self.selected_ollama_model
        if not model:
            return
        self.selected_ollama_model = model
        tab = self.new_tab(title=f"Ollama {model}")
        if isinstance(tab, TerminalTab):
            tab.start_ollama_prompt_mode(model)
            tab.input_line.setFocus()
        self.save_settings()

    def clear_current_ollama_chat(self):
        if not self.ensure_ai_features_enabled():
            return
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        if tab.client_mode_kind == "ollama_api":
            tab.ollama_context = []
            tab.output_area.clear()
            tab.output_area.append(f"[Ollama-API-Modus aktiv: {tab.ollama_model}] Gespräch wurde gelöscht.\n")
            self.show_status("Ollama-Gespräch gelöscht")
        else:
            tab.output_area.clear()
            self.show_status("Ausgabe gelöscht")

    def clear_current_ollama_context(self):
        if not self.ensure_ai_features_enabled():
            return
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab) or tab.client_mode_kind != "ollama_api":
            self.show_status("Kein aktiver Ollama-Tab")
            return
        tab.ollama_context = []
        tab.output_area.append("\n[Ollama-Kontext gelöscht]\n")
        self.show_status("Ollama-Kontext gelöscht")

    def set_current_ollama_system_prompt(self):
        if not self.ensure_ai_features_enabled():
            return
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab) or tab.client_mode_kind != "ollama_api":
            self.show_status("Kein aktiver Ollama-Tab")
            return
        text, ok = QInputDialog.getMultiLineText(
            self,
            "Ollama-Systemprompt",
            "Systemprompt für diesen Ollama-Tab:",
            tab.ollama_system_prompt,
        )
        if not ok:
            return
        tab.ollama_system_prompt = normalize_system_prompt(text)
        tab.ollama_context = []
        note = "gesetzt" if tab.ollama_system_prompt else "geleert"
        tab.output_area.append(f"\n[Ollama-Systemprompt {note}; Kontext zurückgesetzt]\n")
        self.show_status(f"Ollama-Systemprompt {note}")

    def stop_current_ollama_response(self):
        if not self.ensure_ai_features_enabled():
            return
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab) or tab.client_mode_kind != "ollama_api":
            self.show_status("Kein aktiver Ollama-Tab")
            return
        tab.stop_ollama_response()

    def copy_last_ollama_code_block(self):
        if not self.ensure_ai_features_enabled():
            return
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab) or tab.client_mode_kind != "ollama_api":
            self.show_status("Kein aktiver Ollama-Tab")
            return
        tab.copy_last_ollama_code_block()

    def save_current_ollama_chat_markdown(self):
        if not self.ensure_ai_features_enabled():
            return
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab) or tab.client_mode_kind != "ollama_api":
            self.show_status("Kein aktiver Ollama-Tab")
            return
        transcript = self.current_output_text(clean=True)
        if not transcript.strip():
            self.show_status("Kein Ollama-Chat zum Speichern vorhanden")
            return
        safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", tab.ollama_model or "ollama")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Ollama-Chat als Markdown speichern",
            str(Path.cwd() / f"ollama_chat_{safe_model}.md"),
            "Markdown (*.md);;Textdateien (*.txt);;Alle Dateien (*)",
        )
        if not path:
            return
        content = markdown_chat_export(
            app_name=APP_NAME,
            model=tab.ollama_model,
            system_prompt=tab.ollama_system_prompt,
            transcript=transcript,
        )
        try:
            Path(path).write_text(content, encoding="utf-8", newline="\n")
            self.show_status(f"Ollama-Chat gespeichert: {path}")
        except OSError as exc:
            self.show_status(f"Ollama-Chat konnte nicht gespeichert werden: {exc}")

    def show_status(self, message, timeout=5000):
        self.statusBar().showMessage(str(message or ""), timeout)

    def collapse_terminal_redraws(self, text):
        """Reduce PTY/ConPTY carriage-return redraws to visible text.

        PowerShell/PSReadLine redraws the current input line repeatedly via
        carriage return. QTextEdit is not a terminal emulator, so without this
        cleanup every intermediate redraw becomes a new visible line. Keep the
        last redraw state per physical line and apply simple backspace edits.
        """
        value = str(text or "").replace("\r\n", "\n")
        lines = []
        for line in value.split("\n"):
            if "\r" in line:
                line = line.split("\r")[-1]
            if "\b" in line:
                chars = []
                for char in line:
                    if char == "\b":
                        if chars:
                            chars.pop()
                    else:
                        chars.append(char)
                line = "".join(chars)
            lines.append(line)
        return "\n".join(lines)

    def clean_terminal_control_sequences(self, text):
        value = str(text or "")
        # OSC-Sequenzen, z.B. Fenstertitel: ESC ] ... BEL oder ESC ] ... ESC \\
        value = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", value)
        # CSI-Sequenzen, z.B. Farben, Cursorposition, Bildschirm löschen: ESC [ ... final
        value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
        # Einzelne ESC-Sequenzen wie ESC c, ESC 7, ESC 8 usw.
        value = re.sub(r"\x1b[@-Z\\-_]", "", value)
        value = self.collapse_terminal_redraws(value)
        # C1-Steuerzeichen und übrige nicht druckbare Steuerzeichen entfernen,
        # Zeilenumbrüche und Tabs aber erhalten.
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", value)
        return value.replace("\r\n", "\n").replace("\r", "\n")

    def clean_output_text(self, text):
        return self.clean_terminal_control_sequences(text)

    def current_output_text(self, clean=False):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return ""
        text = tab.output_area.toPlainText()
        return self.clean_output_text(text) if clean else text

    def save_current_output(self, forced_format=None):
        tab = self.current_terminal()
        if not isinstance(tab, TerminalTab):
            return
        text = self.current_output_text(clean=True)
        if not text.strip():
            self.show_status("Keine Ausgabe zum Speichern vorhanden")
            return

        forced = str(forced_format or "").lower().strip()
        default_suffix = ".md" if forced != "txt" else ".txt"
        default_name = f"shelldeck_output{default_suffix}"
        if tab.client_mode_kind == "ollama_api" and tab.ollama_model:
            safe_model = re.sub(r"[^A-Za-z0-9_.-]+", "_", tab.ollama_model)
            default_name = f"ollama_{safe_model}{default_suffix}"

        if forced == "md":
            file_filter = "Markdown (*.md);;Textdateien (*.txt);;Alle Dateien (*)"
        elif forced == "txt":
            file_filter = "Textdateien (*.txt);;Markdown (*.md);;Alle Dateien (*)"
        else:
            file_filter = "Markdown (*.md);;Textdateien (*.txt);;Alle Dateien (*)"

        path, _ = QFileDialog.getSaveFileName(
            self,
            "Aktuelle Ausgabe speichern",
            str(Path.cwd() / default_name),
            file_filter,
        )
        if not path:
            return

        try:
            Path(path).write_text(text, encoding="utf-8", newline="\n")
            self.show_status(f"Ausgabe gespeichert: {path}")
        except OSError as exc:
            self.show_status(f"Ausgabe konnte nicht gespeichert werden: {exc}")

    def help_text(self):
        return f"""{APP_NAME} {APP_VERSION}

Übersicht
- ShellDeck Terminal ist eine tabbasierte Terminal-Oberfläche mit mehreren Shell-Backends, optionaler Terminal-Engine-Auswahl, Profilen, Workspaces, Split-/Rasteransichten, gespeicherten Pfaden und optionalem Ollama/KI-Modus.
- Jeder Terminal-Tab besitzt einen eigenen Shell-Prozess, eine eigene Befehlshistorie, einen erkannten Arbeitsordner und optional einen eigenen Client-/Ollama-Modus.
- Einstellungen wie Fenstergröße, Design, Schrift, Farben, Tabs, Workspaces, gespeicherte Pfade, Profile, KI-Menü, Vorbefehl-Leiste und History werden beim Beenden gespeichert und beim nächsten Start wiederhergestellt.
- Die App bleibt bewusst kontrolliert: Befehle werden erst ausgeführt, wenn du Enter, den Button oder „Einfügen + Ausführen“ verwendest.

Grundbedienung
- Gib unten im Eingabefeld einen Befehl ein und starte ihn mit Enter oder dem Button „Befehl ausführen“.
- Mehrere normale Befehle können mit Semikolon getrennt werden, zum Beispiel: cls; dir; git status.
- Ctrl+Enter fügt im unteren Eingabefeld eine neue Zeile ein.
- Pfeil hoch/runter blättert durch die History des aktuellen Tabs und setzt den Cursor ans Ende.
- cls oder clear leert zusätzlich direkt die sichtbare Terminal-Ausgabe.
- Ctrl+C unterbricht den laufenden Shell-Befehl oder beendet/unterbricht den aktiven Client-Modus.

Vorbefehl-Leiste oben rechts
- Die Vorbefehl-Leiste sitzt rechts in der Menüleiste.
- „Vorbefehl aktiv“ bestimmt, ob der Vorbefehl vor normalen Eingaben ausgeführt wird.
- Im Eingabefeld daneben kannst du einen oder mehrere Vorbefehle eintragen; mehrere Vorbefehle werden mit Semikolon getrennt.
- Beispiel: oben cls, unten dir -> zuerst wird cls ausgeführt, danach dir.
- Die Vorbefehl-Leiste wirkt auf normale Befehle aus dem unteren Eingabefeld und auf „Einfügen + Ausführen“.
- Im Client-Modus wird der Vorbefehl bewusst nicht angewendet, damit Python, SQL, Node oder Ollama keine unerwarteten Zusatzzeilen erhalten.
- Sichtbarkeit, Aktiv-Haken, aktueller Vorbefehl und die letzten Vorbefehle werden gespeichert.
- Ansicht → Vorbefehl-Leiste anzeigen blendet die Leiste ein oder aus.

Datei-Menü
- Neuer Tab: öffnet einen neuen Terminal-Tab mit dem aktuell gewählten Standard-Backend.
- Neuer Tab mit Backend: öffnet direkt einen neuen Tab mit CMD, PowerShell, PowerShell 7, Git Bash, WSL, Bash, Zsh, Fish oder sh, sofern erkannt.
- Datei an aktuellen Prompt anhängen: liest eine Textdatei ein und hängt sie als Kontext an den aktuellen Prompt, besonders nützlich für Ollama-Chats.
- Aktuellen Tab schließen: beendet den Shell-Prozess des aktuellen Tabs und schließt den Tab.
- Tab duplizieren: öffnet einen neuen Tab mit gleichem Backend und ähnlichem Titel.
- Tab umbenennen: vergibt einen eigenen Tab-Namen.
- Beenden: speichert Einstellungen und beendet laufende Prozesse möglichst sauber.

Pfade-Menü
- Aktuellen Ordner speichern: speichert den zuletzt erkannten Arbeitsordner des aktuellen Tabs.
- Ordnerpfad manuell speichern: speichert einen gewählten oder eingetippten Ordner unter einem Namen.
- Gespeicherten Pfad löschen: entfernt einen gespeicherten Schnellzugriff.
- Standardordner für neue Tabs zurücksetzen: entfernt den festen Startordner.
- Ein gespeicherter Pfad kann im aktuellen Tab geöffnet, in einem neuen Tab geöffnet oder als Standardordner für neue Tabs gesetzt werden.
- Für WSL und Git Bash werden Windows-Pfade möglichst passend umgewandelt.

Profile-Menü
- Aktuellen Tab als Profil speichern: speichert Backend, Titel, Arbeitsordner und optionalen Startbefehl.
- Profil in neuem Tab öffnen: startet ein gespeichertes Profil als neuen Tab.
- Profil löschen: entfernt gespeicherte Profile.
- Profile eignen sich für wiederkehrende Einzeltabs, zum Beispiel Projekt-Terminal, Python-REPL, Node-Konsole, SQL-Client oder Ollama-Chat.
- Ollama-Profile merken zusätzlich das verwendete Modell.

Workspaces-Menü
- Aktuellen Workspace speichern: speichert die aktuelle Tab-Zusammenstellung.
- Workspace laden: ersetzt die aktuellen Tabs durch den gespeicherten Workspace.
- Workspace löschen: entfernt gespeicherte Workspaces.
- Gespeichert werden Tab-Titel, Shell-Backend, Arbeitsordner, Befehls-History je Tab, Restore-Befehl, venv-Pfad, Layout-Bereich, entkoppelte Tabs, ausgewähltes Ollama-Modell und Standardordner.
- Workspaces sind für komplette Arbeitsumgebungen gedacht, zum Beispiel Visual Edit, Terminal-Projekt und Ollama nebeneinander.

Ansicht-Menü
- Vorbefehl-Leiste anzeigen: blendet das obere Vorbefehl-Feld ein oder aus.
- Einzelansicht: zeigt eine normale Tab-Fläche.
- 2er horizontal: zeigt zwei Bereiche links und rechts.
- 2er vertikal: zeigt zwei Bereiche oben und unten.
- 4er Raster: zeigt vier Bereiche.
- Aktuellen Tab verschieben nach: verschiebt den aktiven Tab gezielt in einen Layout-Bereich.
- Aktuellen Tab in nächste Ansicht verschieben: verschiebt den aktiven Tab zyklisch in den nächsten Bereich.
- Aktuellen Tab entkoppeln: verschiebt den Tab in ein separates Fenster.
- Aktuellen Tab wieder ins Hauptfenster koppeln: holt einen entkoppelten Tab zurück.

Einstellungen-Menü
- Schriftart: setzt die Terminal-Schrift für alle Tabs.
- Farbschema: wechselt zwischen Dunkel, Hell und Hoher Kontrast.
- Design anpassen: bearbeitet Akzent, Hintergrund, Textfarbe, Eingabefeld, Terminal-Farben, Kontrast, Hintergrund-Deckkraft und Fenster-Transparenz.
- Design auf Standard zurücksetzen: stellt die Standardfarben wieder her.
- Standardbefehl: Befehl, der beim Start eines neuen Tabs automatisch ausgeführt wird.
- History-Größe: maximale Anzahl gespeicherter Befehle.
- Shell-Backend: wechselt das Shell-Backend des aktuellen Tabs.
- KI-Menü / Ollama aktivieren: zeigt oder versteckt das KI-Menü.

KI-Menü und Ollama
- Das KI-Menü ist standardmäßig ausblendbar und wird über Einstellungen → KI-Menü / Ollama aktivieren gesteuert.
- Neuer Ollama-Chat: startet einen neuen Ollama-API-Tab mit ausgewähltem Modell.
- Ollama-Modell wählen: liest verfügbare Modelle über ollama list aus und merkt das bevorzugte Modell.
- Ollama-Gespräch löschen: leert Ausgabe und Kontext des aktuellen Ollama-Tabs.
- Ollama-Kontext löschen: setzt nur den Modellkontext zurück, die sichtbare Ausgabe bleibt erhalten.
- Ollama-Systemprompt setzen: legt eine Rollen-/Verhaltensanweisung für den aktuellen Ollama-Tab fest und setzt den Kontext zurück.
- Ollama-Antwort stoppen: bricht eine laufende Ollama-Anfrage ab.
- Ollama-Chat als Markdown speichern: exportiert Verlauf, Modell und Systemprompt als Markdown.
- Aktuelle Ausgabe speichern: speichert die sichtbare Ausgabe des aktuellen Tabs.
- Markdown-Codeblöcke in Ollama-Antworten werden als Codekarten mit Kopieren-Schaltfläche dargestellt.

Interaktiver Client-Modus
- ollama run <modell> startet den stabilen Ollama-API-Prompt-Modus.
- python, py, python3 oder python -i startet einen direkten Python-Client, sofern verfügbar.
- node startet eine Node.js-Konsole.
- sqlite3, psql, mysql, mariadb und sqlcmd werden als SQL-/Datenbank-Clients erkannt.
- Im Client-Modus sendet das untere Eingabefeld rohe Zeilen direkt an den Client.
- Der Button ändert sich zu „An Client senden“ oder passend zum aktiven Client.
- /bye, /exit, exit, quit oder .exit beenden den Client-Modus, je nach Client.
- Semikolon-Aufteilung, cls/clear-Sonderbehandlung und Vorbefehl werden im Client-Modus nicht angewendet.

Kontextmenüs
- Rechtsklick im unteren Eingabefeld: Kopieren, Einfügen, Einfügen + Ausführen, Ausschneiden, Alles auswählen, Datei anhängen, Neuer Tab, Tab duplizieren, Tab umbenennen, Befehlspalette, Tab-Ordner aktualisieren, Client-Modus beenden und aktuellen Tab schließen.
- Einfügen + Ausführen übernimmt den Text aus der Zwischenablage in das Eingabefeld und startet ihn sofort. Ist der Vorbefehl sichtbar und aktiv, läuft er vorher.
- Rechtsklick im Ausgabefeld: Kopieren, Alles kopieren, Kopieren ohne Steuerzeichen, Alles kopieren ohne Steuerzeichen, Ausgabe leeren, Ausgabe speichern, Ausgabe als Markdown/Text speichern, Suchen, nächster/vorheriger Treffer und Tab-Aktionen.
- Im Ollama-Ausgabefeld gibt es zusätzlich Ollama-Antwort stoppen, letzten Codeblock kopieren und Ollama-Chat als Markdown speichern.
- Rechtsklick auf die Tab-Leiste: Neuer Tab, Tab duplizieren, Tab umbenennen, Tab-Ordner aktualisieren, in Ansicht verschieben, in nächste Ansicht verschieben, Tab entkoppeln/wieder koppeln und Tab schließen.

Ausgabe, Suche und Export
- Ctrl+F sucht in der Ausgabe des aktuellen Tabs.
- F3 springt zum nächsten Treffer, Shift+F3 zum vorherigen Treffer.
- Ausgabe kann als Text oder Markdown gespeichert werden.
- Kopieren ohne Steuerzeichen entfernt ANSI-/Terminal-Steuerzeichen aus der kopierten Ausgabe.
- Ausgabe leeren entfernt nur den sichtbaren Inhalt, nicht den laufenden Prozess.

Befehlspalette
- Ctrl+Shift+P öffnet die Befehlspalette.
- Aktionen lassen sich per Suchtext filtern, zum Beispiel Tab, Backend, Pfad, Profil, Workspace, Ollama, Systemprompt, Ausgabe oder Suche.
- Gespeicherte Pfade, Profile und Workspaces erscheinen automatisch als Aktionen.

Backends und Terminal-Engine
- Unterstützt werden je nach System CMD, PowerShell, PowerShell 7, Git Bash, WSL, Bash, Zsh, Fish und sh.
- Nicht installierte Backends werden nicht oder nur eingeschränkt angeboten.
- Das Backend kann pro neuem Tab gewählt werden.
- Einstellungen → Terminal-Engine wählt die interne Ausführungsart für neu gestartete Tabs.
- Standard QProcess bleibt der stabile Standard und verhält sich wie bisher.
- PTY/ConPTY experimentell nutzt unter Windows pywinpty, wenn es installiert ist; fehlt pywinpty, fällt ShellDeck kontrolliert auf QProcess zurück.
- Beim Öffnen gespeicherter Pfade wird der passende cd-Befehl für das jeweilige Backend erzeugt.

Virtuelle Umgebungen und Restore
- ShellDeck versucht Arbeitsordner und virtuelle Python-Umgebungen zu merken.
- Bei Workspaces werden Restore-Befehle und venv-Pfade je Tab gespeichert.
- Beim Laden eines Workspace kann ein erkannter Aktivierungsbefehl erneut ausgeführt werden.
- Die Funktion ist bewusst allgemein gehalten und hängt vom Backend und vom sichtbaren Shell-Prompt ab.

Gespeicherte Daten
- Allgemeine Einstellungen werden über die Anwendungseinstellungen gespeichert.
- Workspaces liegen zusätzlich als JSON-Datei im ShellDeckTerminal-Konfigurationsordner.
- Der Vorbefehl-Zustand wird zusätzlich robust in pre_command.json gespeichert.
- Gespeichert werden unter anderem Fensterzustand, Design, Tabs, Tab-History, Pfade, Profile, Workspaces, KI-Menü-Zustand, Vorbefehl-Sichtbarkeit, Vorbefehl-Aktivierung und Vorbefehl-Historie.

Tastenkürzel
- F1: Hilfe öffnen.
- Ctrl+T: Neuer Tab.
- Ctrl+W: Aktuellen Tab schließen.
- Ctrl+D: Aktuellen Tab duplizieren.
- F2: Aktuellen Tab umbenennen.
- Ctrl+Q: App beenden.
- Ctrl+F: Ausgabe im aktuellen Tab durchsuchen.
- Ctrl+Shift+P: Befehlspalette öffnen.
- F3: nächsten Suchtreffer anzeigen.
- Shift+F3: vorherigen Suchtreffer anzeigen.
- Ctrl+C: laufenden Befehl oder aktiven Client im aktuellen Tab unterbrechen.
- Enter: Befehl ausführen oder Eingabe an aktiven Client senden.
- Ctrl+Enter: neue Zeile im Eingabefeld einfügen.
- Pfeil hoch: vorherigen Befehl aus der History laden, Cursor ans Ende setzen.
- Pfeil runter: nächsten Befehl aus der History laden, Cursor ans Ende setzen.

Modulare Dateien
- src/main.py enthält aktuell die Hauptoberfläche und Terminal-Logik.
- src/shelldeck_profiles.py enthält die Datenlogik für Tab-Profile.
- src/shelldeck_workspaces.py enthält die Datenlogik für Workspaces.
- src/shelldeck_ollama.py enthält Hilfsfunktionen für Ollama.
- src/shelldeck_markdown.py rendert sichere Markdown-/Codeblock-Ausgabe für Ollama-Antworten.
- src/shelldeck_file_context.py liest Textdateien als Prompt-Kontext.

Hinweise
- Standard QProcess ist der stabile Kompatibilitätsmodus. Normale Shell-Befehle funktionieren gut; Programme mit Vollbild-Terminalsteuerung können eingeschränkt sein.
- PTY/ConPTY experimentell ist zum Testen echterer Terminal-Interaktion gedacht und sollte erst nach einem gesicherten Git-Stand genutzt werden.
- Welche Backends, Clients und Ollama-Modelle nutzbar sind, hängt davon ab, was auf dem System installiert ist.
- Unter Linux funktioniert die App grundsätzlich mit PySide6 und verfügbaren Shells wie bash, zsh, fish oder sh.
"""

    def show_help_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Hilfe — {APP_NAME}")
        dialog.resize(760, 620)
        layout = QVBoxLayout(dialog)

        text = QTextEdit(dialog)
        text.setReadOnly(True)
        text.setPlainText(self.help_text())
        layout.addWidget(text)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def show_about_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Über {APP_NAME}")
        dialog.resize(520, 300)
        layout = QVBoxLayout(dialog)

        label = QLabel(
            f"<h2>{APP_NAME}</h2>"
            f"<p><b>Version:</b> {APP_VERSION}</p>"
            "<p>Tabbed Terminal mit Design-Anpassungen, mehreren Shell-Backends, "
            "gespeicherten Ordnerpfaden, Tab-Profilen, Workspaces, Befehlspalette "
            "flexiblen Split-/Raster-Ansichten, optionaler experimenteller PTY/ConPTY-Engine "
            "und verbessertem Ollama-Client-Modus mit Datei-Kontext für Prompts und Chat-artigen Codeblöcken.</p>"
            "<p>Die App stellt die Oberfläche bereit; Befehle werden über das "
            "jeweils ausgewählte Shell-Backend ausgeführt.</p>"
            "<p>Modulare Helferdateien: shelldeck_profiles.py, "
            "shelldeck_workspaces.py, shelldeck_ollama.py, shelldeck_file_context.py und shelldeck_markdown.py.</p>",
            dialog,
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
        buttons.rejected.connect(dialog.reject)
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)
        dialog.exec()

    def closeEvent(self, event):
        self._closing_app = True
        self.save_settings()
        for _, _, tab in self.all_terminal_tabs():
            tab.stop_process(fast=True)
        for window in list(getattr(self, "detached_windows", [])):
            window._closing_from_owner = True
            window.close()
        event.accept()


def main() -> int:
    install_crash_logging()
    app = QApplication(sys.argv)
    try:
        app.setStyle("Fusion")
    except Exception:
        pass
    w = TerminalWindow()
    if not getattr(w, "_window_geometry_restored", False):
        w.resize(800, 600)
        screen = w.screen() or QApplication.primaryScreen()
        if screen:
            frame = w.frameGeometry()
            frame.moveCenter(screen.availableGeometry().center())
            w.move(frame.topLeft())
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
