"""ShellDeck Terminal-Widget.

Dieses Modul kapselt den eigentlichen Terminalbereich von ShellDeck als
wiederverwendbare PySide6-Komponente. Es enthaelt bewusst keine App-Logik
(Menues, Tabs-Verwaltung, Einstellungen, Fenster) - die liegt weiterhin in
main.py.

Einbettung in andere Anwendungen (z.B. Visual Edit):

    from shelldeck_terminal_widget import ShellDeckTerminalWidget

    terminal = ShellDeckTerminalWidget(parent=self)
    layout.addWidget(terminal)

Ohne uebergebenen Host laeuft das Widget mit DefaultTerminalHost
(neutrale Farben/Schrift, plattformabhaengige Standard-Shell). Die
ShellDeck-App uebergibt weiterhin ihr TerminalWindow als Host, wodurch
alle App-Funktionen (Profile, Workspaces, Themes, Statusleiste)
unveraendert funktionieren.
"""

import sys
import re
import os
import json
import time
import shutil
import subprocess
import shlex
import socket
import getpass
import urllib.error
import urllib.request
from pathlib import Path
from shelldeck_ollama import build_generate_payload, extract_generate_response, ollama_api_error_message, normalize_system_prompt
from shelldeck_markdown import extract_code_blocks, ollama_answer_to_html
from PySide6.QtWidgets import (
    QApplication, QTextEdit, QPlainTextEdit, QVBoxLayout, QWidget,
    QPushButton, QDialog, QLabel, QInputDialog, QDialogButtonBox,
    QMenu, QLineEdit, QListWidget, QListWidgetItem, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox
)
from PySide6.QtCore import Qt, QProcess, QEvent, QThread, Signal, QTimer
from PySide6.QtGui import (
    QTextCursor, QTextDocument, QFont, QTextCharFormat, QColor,
    QSyntaxHighlighter, QAction, QTextOption
)

# Terminal-Ausgaben dürfen den Qt-UI-Thread nicht mit einem einzigen
# riesigen QTextEdit-Insert blockieren. Der Drain läuft deshalb
# zeitbudgetiert: Intervall 0 = im nächsten Event-Loop-Durchlauf
# (quasi Echtzeit), und pro Durchlauf wird so viel Text eingefügt,
# wie in das Zeitbudget passt. Dazwischen kann Qt zeichnen und
# Eingaben verarbeiten.
TERMINAL_OUTPUT_DRAIN_INTERVAL_MS = 0
# Etwa eine halbe Frame-Zeit bei 60 Hz: flüssiges Scrollen, keine
# spürbaren Hänger, automatische Anpassung an die reale Einfügegeschwindigkeit.
TERMINAL_OUTPUT_DRAIN_TIME_BUDGET_MS = 8
# Ein Slice pro Edit-Block: groß genug für hohen Durchsatz, klein genug,
# damit die Zeitbudget-Prüfung zwischen den Slices greifen kann.
TERMINAL_OUTPUT_DRAIN_SLICE_CHARS = 65536
TERMINAL_OUTPUT_LARGE_CHUNK_CHARS = 60000
TERMINAL_OUTPUT_MAX_BLOCKS = 25000
TERMINAL_OUTPUT_HARD_WRAP_COLUMN = 12000
TERMINAL_HIGHLIGHT_MAX_DOCUMENT_CHARS = 450000
TERMINAL_HIGHLIGHT_MAX_BLOCKS = 3500
TERMINAL_HIGHLIGHT_MAX_LINE_CHARS = 3000
OLLAMA_HTML_INLINE_RENDER_LIMIT = 180000


def command_targets_shelldeck(command):
    """Erkennt Befehle, die ShellDeck selbst (neu) starten würden.

    Solche Befehle dürfen niemals automatisch ausgeführt werden — weder beim
    App-Start noch beim Tab-/Workspace-Restore noch über Standard- oder
    Profil-Startbefehle. Sonst entsteht eine Endlosschleife aus sich selbst
    startenden Fenstern (z.B. wenn ShellDeck aus einem ShellDeck-Terminal mit
    "python src/main.py" gestartet wurde). Manuelle Eingaben des Benutzers
    bleiben davon unberührt.
    """
    text = str(command or "").strip()
    if not text:
        return False
    if "shelldeck" in text.lower():
        return True
    try:
        app_path = Path(sys.argv[0]).resolve()
    except (OSError, RuntimeError):
        app_path = None
    normalized = text.replace("\\", "/")
    try:
        tokens = shlex.split(normalized, posix=(sys.platform != "win32"))
    except ValueError:
        tokens = normalized.split()
    relative_self = {"main.py", "./main.py", "src/main.py", "./src/main.py"}
    for token in tokens:
        cleaned = str(token).strip("\"'")
        if not cleaned.lower().endswith("main.py"):
            continue
        if cleaned.lower() in relative_self:
            return True
        if app_path is not None:
            try:
                if Path(cleaned).resolve() == app_path:
                    return True
            except (OSError, RuntimeError):
                continue
    return False



class _NullStatusBar:
    """Platzhalter fuer QMainWindow.statusBar() im Standalone-Betrieb."""

    def showMessage(self, *args, **kwargs):
        return None


class DefaultTerminalHost:
    """Standalone-Host fuer ShellDeckTerminalWidget ohne ShellDeck-Hauptfenster.

    In der ShellDeck-App stellt TerminalWindow diese Schnittstelle bereit
    (Farben, Schrift, Shell-Auswahl, Statusmeldungen, App-Aktionen). Dieser
    Host liefert neutrale Standardwerte, damit das Terminal-Widget in anderen
    Anwendungen (z.B. Visual Edit) ohne ShellDeck-Fenster funktioniert.
    Eine einbettende Anwendung kann alternativ ein eigenes Host-Objekt mit
    denselben Methoden uebergeben, um Darstellung und Verhalten anzupassen.
    """

    def __init__(self):
        self.terminal_font = QFont("Courier New", 10)
        self.history = []
        self.max_history_size = 1000
        self.default_command = ""
        self.terminal_engine = "qprocess"
        self.theme_key = "dark"
        self.shell_type = self.default_shell_type()
        self._status_bar = _NullStatusBar()

    # ---- Status und App-Aktionen: im Standalone-Betrieb bewusst neutral ----

    def show_status(self, *args, **kwargs):
        return None

    def statusBar(self):
        return self._status_bar

    def save_settings(self, *args, **kwargs):
        return None

    def save_history(self, *args, **kwargs):
        return None

    def update_tab_title(self, *args, **kwargs):
        return None

    def update_current_tab_directory(self, *args, **kwargs):
        return None

    def new_tab(self, *args, **kwargs):
        return None

    def close_current_tab(self, *args, **kwargs):
        return None

    def duplicate_current_tab(self, *args, **kwargs):
        return None

    def rename_current_tab(self, *args, **kwargs):
        return None

    def show_command_palette(self, *args, **kwargs):
        return None

    def attach_file_to_current_prompt(self, *args, **kwargs):
        return None

    def stop_current_ollama_response(self, *args, **kwargs):
        return None

    def save_current_ollama_chat_markdown(self, *args, **kwargs):
        return None

    def save_current_output(self, *args, **kwargs):
        return None

    def active_pre_command_text(self):
        return ""

    def remember_pre_command_text(self, *args, **kwargs):
        return None

    # ---- Shell-Auswahl (Spiegel der TerminalWindow-Logik) ----

    def default_shell_type(self):
        if sys.platform != "win32":
            if shutil.which("bash"):
                return "bash"
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
        return re.sub(r"^\s*source\s+", ". ", text, count=1)

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

    def system_shell(self, shell_type=None) -> str:
        shell_type = self.normalize_shell_type(shell_type or self.shell_type)
        if sys.platform != "win32":
            if shell_type in ("bash", "zsh", "fish", "sh"):
                return shutil.which(shell_type) or shell_type
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

    def shell_backend_label(self, shell_type=None):
        labels = {
            "cmd": "CMD",
            "powershell": "PowerShell",
            "pwsh": "PowerShell 7",
            "git_bash": "Git Bash",
            "wsl": "WSL",
            "bash": "Bash",
            "zsh": "Zsh",
            "fish": "Fish",
            "sh": "sh",
        }
        key = str(shell_type or "").strip().lower()
        return labels.get(key, key or "Shell")

    # ---- Terminal-Engine ----

    def normalize_terminal_engine(self, engine):
        value = str(engine or "qprocess").lower().strip()
        return value if value in {"qprocess", "pty"} else "qprocess"

    def terminal_engine_label(self, engine=None):
        value = str(engine or getattr(self, "terminal_engine", "qprocess") or "qprocess").lower().strip()
        if value == "pty":
            return "PTY/ConPTY experimentell"
        return "Standard QProcess"

    def terminal_engine_label_for_process(self, process=None):
        engine = str(getattr(process, "_shelldeck_engine", "") or "").lower().strip()
        return self.terminal_engine_label(engine or "qprocess")

    def should_use_pty_backend(self, shell_type=None, engine=None):
        if self.normalize_terminal_engine(engine or getattr(self, "terminal_engine", "qprocess")) != "pty":
            return False
        return not PtyTerminalProcess.availability_message()

    # ---- Ausgabe-Bereinigung ----

    def clean_terminal_control_sequences(self, text):
        value = str(text or "")
        value = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", value)
        value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
        value = re.sub(r"\x1b[@-Z\\-_]", "", value)
        value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]", "", value)
        return value.replace("\r\n", "\n").replace("\r", "\n")

    def clean_output_text(self, text):
        return self.clean_terminal_control_sequences(text)

    # ---- Theme und Farben ----

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
            },
        }

    def current_theme_key(self):
        return "light" if str(getattr(self, "theme_key", "dark")).lower() == "light" else "dark"

    def active_theme(self):
        return self.default_theme_config()[self.current_theme_key()]

    def terminal_colors(self):
        return dict(self.active_theme().get("terminal_colors", {}))

    def terminal_color(self, key, fallback):
        return self.normalize_hex_color(self.terminal_colors().get(key), fallback)

    def normalize_hex_color(self, value, fallback):
        text = str(value or "").strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}", text):
            return text.upper()
        if re.fullmatch(r"[0-9a-fA-F]{6}", text):
            return f"#{text.upper()}"
        return fallback

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

    def set_terminal_colors(self, colors, rehighlight=True):
        self.colors = dict(colors or {})
        self.rebuild_rules()
        if rehighlight:
            self.rehighlight()

    def highlightBlock(self, text):
        if len(text) > TERMINAL_HIGHLIGHT_MAX_LINE_CHARS:
            return
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


class TerminalOutputArea(QTextEdit):
    """Ausgabefeld, dessen append() den Reines-Terminal-Modus respektiert.

    Im Reines-Terminal-Modus ist unten im Dokument ein Prompt samt aktueller
    Eingabe "gepinnt". Meldungen über append() müssen dann vor dem Prompt
    landen, damit sie nicht Teil der Eingabezeile werden.
    """

    def __init__(self, tab):
        super().__init__()
        self._terminal_tab = tab

    def append(self, text):
        getter = getattr(self._terminal_tab, "inline_output_insert_position", None)
        position = getter() if callable(getter) else None
        if position is None:
            super().append(text)
            return
        cursor = QTextCursor(self.document())
        cursor.setPosition(position)
        cursor.insertText(str(text or "") + "\n")


class ShellDeckTerminalWidget(QWidget):
    """Der komplette ShellDeck-Terminalbereich als wiederverwendbares Widget.

    Ohne Argumente laeuft das Widget eigenstaendig mit DefaultTerminalHost.
    Die ShellDeck-App uebergibt ihr TerminalWindow als "window"-Host und
    erhaelt damit exakt das bisherige Verhalten (Tabs, Themes, Profile).
    """

    def __init__(self, window=None, title="Terminal", shell_type=None, custom_title=None, start_directory=None, command_history=None, restore_command="", venv_path="", terminal_engine=None, parent=None):
        if window is None:
            window = DefaultTerminalHost()
        if parent is None and isinstance(window, QWidget):
            parent = window
        super().__init__(parent)
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

        self.output_area = TerminalOutputArea(self)
        self.output_area.setReadOnly(True)
        self.output_area.setUndoRedoEnabled(False)
        self.output_area.setFont(self.window.terminal_font)
        self.output_area.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.output_area.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.output_area.document().setMaximumBlockCount(TERMINAL_OUTPUT_MAX_BLOCKS)
        self.output_area.setTextInteractionFlags(
            self.output_area.textInteractionFlags() | Qt.TextInteractionFlag.LinksAccessibleByMouse
        )
        self.output_area.viewport().installEventFilter(self)
        self.output_area.installEventFilter(self)
        self.output_area.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.output_area.customContextMenuRequested.connect(self.show_terminal_context_menu)
        layout.addWidget(self.output_area)

        self.command_tasks = []
        self.active_command_task = None
        self.command_task_panel_visible = True
        self.command_task_panel_expanded = False
        self.command_task_header = QPushButton()
        self.command_task_header.setCheckable(True)
        self.command_task_header.setChecked(self.command_task_panel_expanded)
        self.command_task_header.setToolTip(
            "Blendet die Tabelle der zuletzt ausgeführten Befehle ein oder aus. "
            "Die Tabelle kann auch über Ansicht → Letzte Befehle anzeigen komplett verborgen werden."
        )
        self.command_task_header.clicked.connect(self.set_command_task_panel_expanded)
        layout.addWidget(self.command_task_header)

        self.command_task_list = QTableWidget(0, 5)
        self.command_task_list.setToolTip(
            "Letzte Befehle als Tabelle. Doppelklick auf eine Zeile führt den Befehl erneut aus. "
            "Rechtsklick öffnet Kopieren-, Löschen-, Eingabe- und sichere Rückgängig-Aktionen."
        )
        self.command_task_list.setHorizontalHeaderLabels(["Status", "Befehl", "Zeit", "Dauer", "Ordner"])
        self.command_task_list.setMaximumHeight(150)
        self.command_task_list.setAlternatingRowColors(True)
        self.command_task_list.setShowGrid(False)
        self.command_task_list.setSortingEnabled(False)
        self.command_task_list.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.command_task_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.command_task_list.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.command_task_list.verticalHeader().setVisible(False)
        header = self.command_task_list.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.command_task_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.command_task_list.customContextMenuRequested.connect(self.show_command_task_context_menu)
        self.command_task_list.cellDoubleClicked.connect(self.rerun_command_task_from_table_cell)
        layout.addWidget(self.command_task_list)
        self.set_command_task_panel_expanded(self.command_task_panel_expanded)

        self.highlighter = TerminalHighlighter(self.output_area.document(), self.window.terminal_colors())
        self._output_queue = []
        self._output_drain_timer = QTimer(self)
        self._output_drain_timer.setInterval(TERMINAL_OUTPUT_DRAIN_INTERVAL_MS)
        self._output_drain_timer.timeout.connect(self.drain_terminal_output_queue)
        self._highlighter_restore_timer = QTimer(self)
        self._highlighter_restore_timer.setSingleShot(True)
        self._highlighter_restore_timer.timeout.connect(self.restore_terminal_highlighter_if_safe)

        # Reines-Terminal-Modus: Eingabe direkt im Ausgabebereich.
        self.pure_terminal_mode = False
        self._inline_prompt_cursor = None
        self._inline_input_cursor = None

        self.input_prompt_label = QLineEdit()
        self.input_prompt_label.setToolTip("Aktueller Eingabe-Prompt mit Shell, Benutzer, Rechner und erkanntem Arbeitsordner.")
        self.input_prompt_label.setReadOnly(True)
        self.input_prompt_label.setFont(self.window.terminal_font)
        self.input_prompt_label.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.input_prompt_label.setCursorPosition(0)
        layout.addWidget(self.input_prompt_label)

        self.input_line = QPlainTextEdit()
        self.input_line.setToolTip(
            "Befehl eingeben und mit Enter oder dem Button ausführen. "
            "Ctrl+Enter fügt eine neue Zeile ein."
        )
        self.input_line.setMaximumHeight(110)
        self.input_line.setFont(self.window.terminal_font)
        self.input_line.installEventFilter(self)
        self.input_line.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.input_line.customContextMenuRequested.connect(self.show_terminal_context_menu)
        layout.addWidget(self.input_line)
        self.update_input_prompt_label()

        self.execute_button = QPushButton("Befehl ausführen")
        self.execute_button.setToolTip("Führt die aktuelle Eingabe im aktiven Terminal-Tab aus.")
        self.execute_button.clicked.connect(self.execute_command)
        layout.addWidget(self.execute_button)

        self.process = self.create_shell_process()
        self.connect_shell_process(self.process)

        self.apply_theme()
        self.start_shell()

        if self.window.default_command and self.process.waitForStarted(2000):
            self.run_startup_command(self.window.default_command)

    def terminal_stdout_color(self):
        return QColor(self.window.terminal_color("stdout", "#FFFFFF"))

    def terminal_stderr_color(self):
        return QColor(self.window.terminal_color("stderr", "#FCA5A5"))

    def terminal_queue_split_index(self, text, limit):
        if len(text) <= limit:
            return len(text)
        newline = text.rfind("\n", 0, limit)
        if newline >= max(1, limit // 2):
            return newline + 1
        return limit

    def wrap_extremely_long_output_lines(self, text):
        """Avoid pathological single QTextDocument blocks.

        QTextEdit and QSyntaxHighlighter become very expensive when one physical
        line is hundreds of thousands of characters long, which can happen with
        escaped JSON/diagnostic blobs containing literal "\\n" sequences.
        Soft wrapping keeps normal text intact; this hard fallback only splits
        extreme single lines so the UI stays responsive.
        """
        value = str(text or "")
        limit = TERMINAL_OUTPUT_HARD_WRAP_COLUMN
        if len(value) <= limit or max((len(line) for line in value.splitlines() or [value]), default=0) <= limit:
            return value

        wrapped = []
        for line in value.splitlines(True):
            line_break = ""
            body = line
            if body.endswith("\n"):
                body = body[:-1]
                line_break = "\n"
            while len(body) > limit:
                wrapped.append(body[:limit])
                wrapped.append("\n")
                body = body[limit:]
            wrapped.append(body)
            wrapped.append(line_break)
        return "".join(wrapped)

    def prepare_terminal_output_for_display(self, text):
        return self.wrap_extremely_long_output_lines(str(text or ""))

    def terminal_document_is_small_enough_for_highlighting(self):
        document = self.output_area.document()
        return (
            document.characterCount() <= TERMINAL_HIGHLIGHT_MAX_DOCUMENT_CHARS
            and document.blockCount() <= TERMINAL_HIGHLIGHT_MAX_BLOCKS
        )

    def suspend_terminal_highlighter_for_bulk_output(self):
        if self.highlighter.document() is not None:
            self.highlighter.setDocument(None)

    def restore_terminal_highlighter_if_safe(self):
        if self._output_queue:
            return
        if self.client_mode_active and self.client_mode_kind == "ollama_api":
            return
        if not self.terminal_document_is_small_enough_for_highlighting():
            self.highlighter.set_terminal_colors(self.window.terminal_colors(), rehighlight=False)
            return
        if self.highlighter.document() is None:
            self.highlighter.setDocument(self.output_area.document())
        self.highlighter.set_terminal_colors(self.window.terminal_colors())

    def queue_terminal_output(self, text, color=None):
        value = self.prepare_terminal_output_for_display(text)
        if not value:
            return
        qcolor = QColor(color) if color is not None else self.terminal_stdout_color()
        if len(value) >= TERMINAL_OUTPUT_LARGE_CHUNK_CHARS or self._output_queue:
            self.suspend_terminal_highlighter_for_bulk_output()
        if self._output_queue and self._output_queue[-1][1] == qcolor:
            # Gleichfarbige Chunks zusammenfassen: QProcess liefert oft viele
            # kleine Häppchen, ein zusammenhängender Text lässt sich in einem
            # Rutsch einfügen.
            self._output_queue[-1][0] += value
        else:
            self._output_queue.append([value, qcolor])
        if not self._output_drain_timer.isActive():
            self._output_drain_timer.start()

    def drain_terminal_output_queue(self):
        if not self._output_queue:
            self._output_drain_timer.stop()
            self._highlighter_restore_timer.start(750)
            return

        pending = sum(len(item[0]) for item in self._output_queue)
        if pending >= TERMINAL_OUTPUT_LARGE_CHUNK_CHARS:
            self.suspend_terminal_highlighter_for_bulk_output()

        deadline = time.perf_counter() + TERMINAL_OUTPUT_DRAIN_TIME_BUDGET_MS / 1000.0
        self.output_area.setUpdatesEnabled(False)
        try:
            while self._output_queue:
                # Eigener Cursor auf dem Dokument statt des Widget-Cursors:
                # vermeidet Cursor-Signale/Auto-Scroll pro Einfügung, und
                # begin/endEditBlock fasst einen ganzen Slice zu einer
                # einzigen Dokumentänderung (= einer Layout-Neuvermessung)
                # zusammen. Nach jedem Slice wird das Zeitbudget geprüft,
                # sodass auch teure Layout-Läufe (z.B. beim Kürzen alter
                # Blöcke) den UI-Thread nie länger als ~ein halbes Frame
                # blockieren.
                budget = TERMINAL_OUTPUT_DRAIN_SLICE_CHARS
                cursor = QTextCursor(self.output_area.document())
                insert_position = self.inline_output_insert_position()
                if insert_position is None:
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                else:
                    # Reines-Terminal-Modus: Ausgabe vor dem gepinnten
                    # Prompt einfügen, die Eingabezeile bleibt unten stehen.
                    cursor.setPosition(insert_position)
                cursor.beginEditBlock()
                try:
                    while self._output_queue and budget > 0:
                        text, color = self._output_queue[0]
                        take = self.terminal_queue_split_index(text, budget)
                        part = text[:take]
                        rest = text[take:]
                        fmt = QTextCharFormat()
                        fmt.setForeground(color)
                        cursor.insertText(part, fmt)
                        budget -= len(part)
                        if rest:
                            self._output_queue[0][0] = rest
                            break
                        self._output_queue.pop(0)
                finally:
                    cursor.endEditBlock()
                if time.perf_counter() >= deadline:
                    break
        finally:
            self.output_area.setUpdatesEnabled(True)

        scrollbar = self.output_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

        if not self._output_queue:
            self.output_area.setTextColor(self.terminal_stdout_color())
            self.output_area.moveCursor(QTextCursor.MoveOperation.End)
            self.output_area.ensureCursorVisible()
            self._output_drain_timer.stop()
            self._highlighter_restore_timer.start(750)
            if self.inline_mode_active():
                # Nach neuer Ausgabe entscheiden, ob der eigene Prompt nötig
                # ist oder der native Shell-Prompt sichtbar geworden ist.
                self.refresh_inline_prompt()

    # ---- Reines-Terminal-Modus: Eingabe direkt im Ausgabebereich ----

    def inline_mode_active(self):
        return bool(getattr(self, "pure_terminal_mode", False))

    def inline_markers_valid(self):
        prompt_cursor = getattr(self, "_inline_prompt_cursor", None)
        input_cursor = getattr(self, "_inline_input_cursor", None)
        return (
            prompt_cursor is not None
            and input_cursor is not None
            and not prompt_cursor.isNull()
            and not input_cursor.isNull()
            and prompt_cursor.position() <= input_cursor.position()
        )

    def inline_output_insert_position(self):
        """Einfügeposition für Ausgaben, oder None für das Dokumentende."""
        if self.inline_mode_active() and self.inline_markers_valid():
            return self._inline_prompt_cursor.position()
        return None

    def inline_prompt_display_text(self):
        if getattr(self, "password_prompt_active", False):
            return "Passwort erwartet: "
        return f"{self.input_prompt_text()} "

    def inline_prompt_context_text(self):
        """Sichtbarer Text vor dem Inline-Prompt inkl. noch nicht gezeichneter Queue."""
        if self.inline_markers_valid():
            cursor = QTextCursor(self.output_area.document())
            cursor.setPosition(0)
            cursor.setPosition(self._inline_prompt_cursor.position(), QTextCursor.MoveMode.KeepAnchor)
            text = cursor.selectedText().replace(chr(0x2029), "\n")
        else:
            try:
                text = self.output_area.toPlainText()
            except Exception:
                text = ""
        try:
            queued = "".join(str(item[0] or "") for item in getattr(self, "_output_queue", []) if item)
        except Exception:
            queued = ""
        return text + queued

    def inline_prompt_should_be_visible(self):
        """Eigenen Prompt nur zeigen, wenn kein echter Shell-Prompt sichtbar ist.

        Im QProcess-Pipe-Modus (und unter PTY/ConPTY) schreiben PowerShell,
        CMD & Co. ihren eigenen Prompt als normale Ausgabe. Endet die Ausgabe
        bereits mit so einem Prompt, würde der zusätzliche ShellDeck-Prompt
        doppelt erscheinen — dann dient der native Prompt als Eingabemarke.
        Die Erkennung ist dieselbe, mit der ShellDeck auch das Befehlsende
        erkennt (output_ends_with_shell_prompt); es wird keine Ausgabe
        entfernt oder verändert.
        """
        if getattr(self, "password_prompt_active", False):
            return True
        return not self.output_ends_with_shell_prompt(self.inline_prompt_context_text())

    def inline_prompt_effective_text(self):
        if self.inline_prompt_should_be_visible():
            return self.inline_prompt_display_text()
        # Unsichtbarer Anker (Zero-Width-Space): Er hält Prompt- und
        # Eingabe-Marker auseinander, während der native Shell-Prompt als
        # sichtbare Eingabemarke dient. Ohne Anker fielen beide Marker auf
        # dieselbe Position und Einfügungen würden sie überholen.
        return chr(0x200B)

    def inline_document_ends_mid_line(self, document, position):
        if position <= 0:
            return False
        return document.characterAt(position - 1) != chr(0x2029)

    def inline_prompt_char_format(self):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(self.window.terminal_color("command", "#7DD3FC")))
        return fmt

    def inline_input_char_format(self):
        fmt = QTextCharFormat()
        fmt.setForeground(self.terminal_stdout_color())
        return fmt

    def arm_inline_prompt(self):
        """Pinnt einen frischen Prompt ans Dokumentende und setzt die Marker."""
        if not self.inline_mode_active():
            return
        document = self.output_area.document()
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.End)
        visible_prompt = self.inline_prompt_should_be_visible()
        prompt_text = self.inline_prompt_effective_text()
        cursor.beginEditBlock()
        try:
            if visible_prompt and self.inline_document_ends_mid_line(document, cursor.position()):
                cursor.insertText("\n")
            prompt_start = cursor.position()
            cursor.insertText(prompt_text, self.inline_prompt_char_format())
        finally:
            cursor.endEditBlock()
        self._inline_prompt_cursor = QTextCursor(document)
        self._inline_prompt_cursor.setPosition(prompt_start)
        self._inline_input_cursor = QTextCursor(document)
        self._inline_input_cursor.setPosition(cursor.position())
        self._inline_input_cursor.setKeepPositionOnInsert(True)
        self.output_area.setCurrentCharFormat(self.inline_input_char_format())
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.ensureCursorVisible()

    def disarm_inline_prompt(self):
        self._inline_prompt_cursor = None
        self._inline_input_cursor = None

    def remove_inline_prompt_from_output(self):
        """Entfernt Prompt samt Eingabe wieder aus dem Dokument (Moduswechsel)."""
        if not self.inline_markers_valid():
            return
        document = self.output_area.document()
        start = self._inline_prompt_cursor.position()
        if start > 0 and document.characterAt(start - 1) == "\u2029":
            start -= 1
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.removeSelectedText()

    def inline_input_text(self):
        if not self.inline_markers_valid():
            return ""
        cursor = QTextCursor(self.output_area.document())
        cursor.setPosition(self._inline_input_cursor.position())
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        return cursor.selectedText().replace("\u2029", "\n")

    def set_inline_input_text(self, text):
        if not self.inline_markers_valid():
            return
        input_start = self._inline_input_cursor.position()
        cursor = QTextCursor(self.output_area.document())
        cursor.setPosition(input_start)
        cursor.movePosition(QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor)
        cursor.insertText(str(text or ""), self.inline_input_char_format())
        self._inline_input_cursor.setPosition(input_start)
        self._inline_input_cursor.setKeepPositionOnInsert(True)
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.ensureCursorVisible()

    def refresh_inline_prompt(self):
        """Hält den gepinnten Prompt aktuell (cwd/venv/Passwortmodus)."""
        if not (self.inline_mode_active() and self.inline_markers_valid()):
            return
        document = self.output_area.document()
        start = self._inline_prompt_cursor.position()
        end = self._inline_input_cursor.position()
        cursor = QTextCursor(document)
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        current = cursor.selectedText().replace(chr(0x2029), "\n")
        new_prompt = self.inline_prompt_effective_text()
        if current == new_prompt:
            return
        cursor.insertText(new_prompt, self.inline_prompt_char_format())
        self._inline_prompt_cursor.setPosition(start)
        self._inline_input_cursor.setPosition(cursor.position())
        self._inline_input_cursor.setKeepPositionOnInsert(True)

    def submit_inline_command(self):
        """Enter im Reines-Terminal-Modus: Eingabe wie gewohnt ausführen.

        Die Eingabe wird in input_line übernommen und durch execute_command()
        geschleust — damit gelten exakt dieselben Regeln wie im klassischen
        Modus (Passwort-/Interaktionsmodus, Client-Modus, Ollama, cls,
        Vorbefehle, Historie).
        """
        if not self.inline_markers_valid():
            self.arm_inline_prompt()
            return
        command_text = self.inline_input_text()
        cursor = QTextCursor(self.output_area.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText("\n")
        self.disarm_inline_prompt()
        self.input_line.setPlainText(command_text)
        self.execute_command()
        self.input_line.clear()
        self.arm_inline_prompt()

    def move_inline_cursor_into_input_region(self):
        cursor = self.output_area.textCursor()
        start = min(cursor.position(), cursor.anchor())
        if not self.inline_markers_valid() or start >= self._inline_input_cursor.position():
            return
        end_cursor = self.output_area.textCursor()
        end_cursor.movePosition(QTextCursor.MoveOperation.End)
        self.output_area.setTextCursor(end_cursor)

    def paste_into_inline_input(self):
        """Fügt die Zwischenablage in die Inline-Eingabe hinter dem Prompt ein."""
        if not (self.inline_mode_active() and self.inline_markers_valid()):
            return
        self.move_inline_cursor_into_input_region()
        clipboard_text = QApplication.clipboard().text()
        if not clipboard_text:
            return
        paste_cursor = self.output_area.textCursor()
        paste_cursor.insertText(clipboard_text, self.inline_input_char_format())
        self.output_area.moveCursor(QTextCursor.MoveOperation.End)
        self.output_area.ensureCursorVisible()

    def inline_selection_in_input_region(self):
        """True, wenn die aktuelle Auswahl vollständig in der Eingabe liegt."""
        if not (self.inline_mode_active() and self.inline_markers_valid()):
            return False
        cursor = self.output_area.textCursor()
        if not cursor.hasSelection():
            return False
        return min(cursor.position(), cursor.anchor()) >= self._inline_input_cursor.position()

    def cut_inline_selection(self):
        """Schneidet markierten Text aus der Inline-Eingabe aus.

        Nur Auswahlen innerhalb der Eingabezeile werden ausgeschnitten; die
        Ausgabe-Historie oberhalb des Prompts bleibt schreibgeschützt.
        """
        if not self.inline_selection_in_input_region():
            return
        cursor = self.output_area.textCursor()
        QApplication.clipboard().setText(cursor.selectedText().replace(chr(0x2029), "\n"))
        cursor.removeSelectedText()

    def handle_inline_terminal_key(self, event):
        """Tastenbehandlung im Reines-Terminal-Modus.

        Rückgabe True = Ereignis verbraucht/blockiert, False = normale
        QTextEdit-Verarbeitung (z.B. Zeicheneingabe am Dokumentende).
        Die Ausgabe-Historie oberhalb des Prompts bleibt schreibgeschützt.
        """
        output_area = self.output_area
        key = event.key()
        modifiers = event.modifiers()
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)

        if not self.inline_markers_valid():
            self.arm_inline_prompt()
            if not self.inline_markers_valid():
                return True

        input_start = self._inline_input_cursor.position()
        cursor = output_area.textCursor()
        selection_start = min(cursor.position(), cursor.anchor())

        if ctrl and key == Qt.Key.Key_C:
            if cursor.hasSelection():
                output_area.copy()
            else:
                self.interrupt_current_command()
            return True
        if ctrl and key == Qt.Key.Key_V:
            self.paste_into_inline_input()
            return True
        if ctrl and key == Qt.Key.Key_X:
            self.cut_inline_selection()
            return True
        if ctrl and key == Qt.Key.Key_L:
            self.clear_terminal_output()
            return True
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.submit_inline_command()
            return True
        if key == Qt.Key.Key_Up and not ctrl:
            self.show_previous_command()
            return True
        if key == Qt.Key.Key_Down and not ctrl:
            self.show_next_command()
            return True
        if key == Qt.Key.Key_Home and not ctrl:
            move_mode = (
                QTextCursor.MoveMode.KeepAnchor
                if modifiers & Qt.KeyboardModifier.ShiftModifier
                else QTextCursor.MoveMode.MoveAnchor
            )
            home_cursor = output_area.textCursor()
            home_cursor.setPosition(input_start, move_mode)
            output_area.setTextCursor(home_cursor)
            return True
        if key == Qt.Key.Key_Backspace:
            if cursor.hasSelection():
                return selection_start < input_start
            return cursor.position() <= input_start
        if key == Qt.Key.Key_Delete:
            return selection_start < input_start
        text = event.text()
        if text and text.isprintable():
            if selection_start < input_start:
                self.move_inline_cursor_into_input_region()
            output_area.setCurrentCharFormat(self.inline_input_char_format())
            return False
        return False

    def clear_terminal_output(self):
        """Ausgabe leeren; im Reines-Terminal-Modus mit frischem Prompt."""
        was_inline = self.inline_mode_active() and self.inline_markers_valid()
        self.disarm_inline_prompt()
        self.output_area.clear()
        if was_inline or self.inline_mode_active():
            self.arm_inline_prompt()

    def set_pure_terminal_mode(self, enabled, focus=True, save=True):
        enabled = bool(enabled)
        if enabled == self.inline_mode_active():
            return
        self.pure_terminal_mode = enabled
        if enabled:
            pending = self.input_line.toPlainText()
            self.input_prompt_label.hide()
            self.input_line.hide()
            self.execute_button.hide()
            self.input_line.setFocusProxy(self.output_area)
            self.output_area.setReadOnly(False)
            self.arm_inline_prompt()
            if pending.strip():
                self.set_inline_input_text(pending)
                self.input_line.clear()
            if focus:
                self.output_area.setFocus()
        else:
            pending = self.inline_input_text()
            self.remove_inline_prompt_from_output()
            self.disarm_inline_prompt()
            self.output_area.setReadOnly(True)
            self.input_line.setFocusProxy(None)
            self.input_prompt_label.show()
            self.input_line.show()
            self.execute_button.show()
            if pending.strip():
                self.input_line.setPlainText(pending)
                self.input_line.moveCursor(QTextCursor.MoveOperation.End)
            if focus:
                self.input_line.setFocus()
        if save:
            try:
                self.window.save_settings()
            except Exception:
                pass

    def toggle_pure_terminal_mode(self):
        self.set_pure_terminal_mode(not self.inline_mode_active())

    def pending_command_text(self):
        if self.inline_mode_active() and self.inline_markers_valid():
            return self.inline_input_text()
        return self.input_line.toPlainText()

    def set_pending_command_text(self, text):
        if self.inline_mode_active() and self.inline_markers_valid():
            self.set_inline_input_text(text)
        else:
            self.input_line.setPlainText(text)
            self.input_line.moveCursor(QTextCursor.MoveOperation.End)

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
        # Im Reines-Terminal-Modus auch den gepinnten Inline-Prompt
        # aktualisieren (cwd/venv/Passwortmodus).
        self.refresh_inline_prompt()

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
            if command_targets_shelldeck(translated):
                self.output_area.append(
                    f"\n[Automatischer Startbefehl übersprungen (zeigt auf ShellDeck selbst): {translated}]\n"
                )
                continue
            if translated.lower() in {"cls", "clear"}:
                self.output_area.clear()
                self._awaiting_command_completion = False
                if getattr(self, "interaction_prompt_active", False):
                    self.reset_interaction_prompt_mode()
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

    def send_return_key(self):
        """Send a plain Return/Enter to the currently running process.

        This is useful for prompts where the process expects an empty answer,
        a confirmation with the default choice, or the final blank line of an
        interactive command. It deliberately bypasses the lower input field and
        the normal command history/task path.
        """
        if self.process and self.process.state() == QProcess.ProcessState.Running:
            self.process.write(b"\n")
            self.process.waitForBytesWritten(1000)
            try:
                self.window.show_status("Return/Enter an laufenden Prozess gesendet")
            except Exception:
                pass

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

            if self.inline_mode_active():
                paste_action = QAction("Einfügen", self)
                paste_action.setToolTip("Zwischenablage in die Eingabe hinter dem Prompt einfügen")
                paste_action.setEnabled(bool(QApplication.clipboard().text()))
                paste_action.triggered.connect(self.paste_into_inline_input)
                menu.addAction(paste_action)

                cut_action = QAction("Ausschneiden", self)
                cut_action.setToolTip("Markierten Text aus der Eingabe ausschneiden (Ausgabe-Historie bleibt geschützt)")
                cut_action.setEnabled(self.inline_selection_in_input_region())
                cut_action.triggered.connect(self.cut_inline_selection)
                menu.addAction(cut_action)

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
            clear_action.triggered.connect(self.clear_terminal_output)
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
        enter_action = signal_menu.addAction("Return/Enter")
        enter_action.setToolTip("Eine leere Return-/Enter-Eingabe an den laufenden Prozess senden")
        enter_action.triggered.connect(self.send_return_key)
        signal_menu.addSeparator()
        sigint_action = signal_menu.addAction("Strg+C (SIGINT)")
        sigint_action.triggered.connect(lambda: self.send_control_character(b"\x03"))
        sigtstp_action = signal_menu.addAction("Strg+Z (SIGTSTP/Pause)")
        sigtstp_action.triggered.connect(lambda: self.send_control_character(b"\x1a"))
        eof_action = signal_menu.addAction("Strg+D (EOF)")
        eof_action.triggered.connect(lambda: self.send_control_character(b"\x04"))
        sigquit_action = signal_menu.addAction("Strg+\\ (SIGQUIT)")
        sigquit_action.triggered.connect(lambda: self.send_control_character(b"\x1c"))

        menu.addSeparator()
        pure_terminal_action = QAction("Reines Terminal (Eingabe in der Ausgabe)", self)
        pure_terminal_action.setCheckable(True)
        pure_terminal_action.setChecked(self.inline_mode_active())
        pure_terminal_action.setToolTip(
            "Eingabezeile ausblenden und Befehle direkt im Ausgabebereich eingeben. "
            "Jederzeit wieder zurückschaltbar (Ctrl+Shift+E)."
        )
        pure_terminal_action.triggered.connect(self.toggle_pure_terminal_mode)
        menu.addAction(pure_terminal_action)

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



    def update_command_task_header_label(self):
        header = getattr(self, "command_task_header", None)
        if header is None:
            return
        expanded = bool(getattr(self, "command_task_panel_expanded", False))
        visible = bool(getattr(self, "command_task_panel_visible", True))
        count = 0
        task_table = getattr(self, "command_task_list", None)
        if task_table is not None:
            count = task_table.rowCount()
        arrow = "▾" if expanded else "▸"
        suffix = f" ({count})" if count else ""
        hidden_suffix = " — ausgeblendet" if not visible else ""
        header.setText(f"{arrow} Letzte Befehle{suffix}{hidden_suffix}")

    def set_command_task_panel_visible(self, visible, *, save=True):
        """Show or hide the complete last-command area for this tab."""
        self.command_task_panel_visible = bool(visible)
        header = getattr(self, "command_task_header", None)
        if header is not None:
            header.setVisible(self.command_task_panel_visible)
        task_table = getattr(self, "command_task_list", None)
        if task_table is not None:
            task_table.setVisible(self.command_task_panel_visible and self.command_task_panel_expanded)
            task_table.setMaximumHeight(150 if (self.command_task_panel_visible and self.command_task_panel_expanded) else 0)
        self.update_command_task_header_label()
        if save:
            try:
                self.window.save_settings()
            except Exception:
                pass

    def toggle_command_task_panel_visible(self):
        self.set_command_task_panel_visible(not bool(getattr(self, "command_task_panel_visible", True)))

    def set_command_task_panel_expanded(self, expanded):
        self.command_task_panel_expanded = bool(expanded)
        if self.command_task_panel_expanded and not bool(getattr(self, "command_task_panel_visible", True)):
            self.command_task_panel_visible = True
        header = getattr(self, "command_task_header", None)
        if header is not None:
            header.setVisible(bool(getattr(self, "command_task_panel_visible", True)))
            if header.isChecked() != self.command_task_panel_expanded:
                header.setChecked(self.command_task_panel_expanded)
        task_table = getattr(self, "command_task_list", None)
        if task_table is not None:
            task_table.setVisible(bool(getattr(self, "command_task_panel_visible", True)) and self.command_task_panel_expanded)
            task_table.setMaximumHeight(150 if (bool(getattr(self, "command_task_panel_visible", True)) and self.command_task_panel_expanded) else 0)
        self.update_command_task_header_label()

    def command_task_time_label(self, value=None):
        timestamp = float(value if value is not None else time.time())
        return time.strftime("%H:%M:%S", time.localtime(timestamp))

    def command_task_datetime_label(self, value=None):
        timestamp = float(value if value is not None else time.time())
        return time.strftime("%d.%m. %H:%M", time.localtime(timestamp))

    def command_task_duration_label(self, task):
        started = float(task.get("started_at") or time.time())
        ended = task.get("ended_at")
        reference = float(ended if ended is not None else time.time())
        duration = max(0.0, reference - started)
        if duration < 10:
            return f"{duration:.1f}s"
        return f"{duration:.0f}s"

    def trim_command_task_text(self, value, limit=4000):
        text = self.window.clean_output_text(str(value or "")) if hasattr(self.window, "clean_output_text") else str(value or "")
        text = text.strip()
        if len(text) <= limit:
            return text
        return text[-limit:].lstrip()

    def command_task_status_icon(self, status):
        text = str(status or "").lower()
        if text == "läuft":
            return "▶"
        if text == "erfolgreich":
            return "✓"
        if text == "fehler":
            return "✗"
        return "?"

    def command_task_command_label(self, task, limit=140):
        command = str(task.get("original_command") or task.get("sent_command") or "").replace("\n", " ⏎ ")
        if len(command) > int(limit):
            command = command[: int(limit) - 1].rstrip() + "…"
        return command

    def command_task_table_values(self, task):
        cwd = self.compact_display_path(task.get("working_directory", ""))
        if task.get("pre_commands"):
            cwd = f"{cwd} | mit Vorbefehl" if cwd else "mit Vorbefehl"
        return [
            self.command_task_status_icon(task.get("status")),
            self.command_task_command_label(task),
            self.command_task_datetime_label(task.get("started_at")),
            self.command_task_duration_label(task),
            cwd,
        ]

    def command_task_row(self, task):
        if not task:
            return -1
        task_table = getattr(self, "command_task_list", None)
        if task_table is None:
            return -1
        item = task.get("item")
        if item is not None:
            try:
                row = item.row()
                if row >= 0 and row < task_table.rowCount():
                    return row
            except RuntimeError:
                pass
        for row in range(task_table.rowCount()):
            for column in range(task_table.columnCount()):
                cell = task_table.item(row, column)
                if cell is not None and cell.data(Qt.ItemDataRole.UserRole) is task:
                    return row
        return -1

    def command_task_tooltip_text(self, task):
        tooltip = [
            f"Status: {task.get('status', 'unbekannt')}",
            f"Originalbefehl: {task.get('original_command', '')}",
            f"Gesendet: {task.get('sent_command', '')}",
            f"Start: {self.command_task_time_label(task.get('started_at'))}",
            f"Arbeitsordner: {task.get('working_directory', '')}",
            f"Shell: {task.get('shell_type', '')}",
            f"Engine: {task.get('terminal_engine', '')}",
        ]
        if task.get("pre_commands"):
            tooltip.append(f"Vorbefehl: {task.get('pre_commands')}")
        if task.get("ended_at"):
            tooltip.append(f"Ende: {self.command_task_time_label(task.get('ended_at'))}")
        if task.get("exit_code") is not None:
            tooltip.append(f"Exit-Code: {task.get('exit_code')}")
        if task.get("stderr"):
            tooltip.append("\nFehler-Ausschnitt:\n" + str(task.get("stderr")))
        elif task.get("stdout"):
            tooltip.append("\nAusgabe-Ausschnitt:\n" + str(task.get("stdout")))
        return "\n".join(tooltip)

    def update_command_task_item(self, task):
        task_table = getattr(self, "command_task_list", None)
        if task_table is None:
            return
        row = self.command_task_row(task)
        if row < 0:
            return
        values = self.command_task_table_values(task)
        tooltip = self.command_task_tooltip_text(task)
        for column, value in enumerate(values):
            item = task_table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                task_table.setItem(row, column, item)
            item.setText(str(value))
            item.setToolTip(tooltip)
            item.setData(Qt.ItemDataRole.UserRole, task)
        task["item"] = task_table.item(row, 0)

    def start_command_task(self, original_command, sent_command, pre_commands=""):
        # Falls ShellDeck ausnahmsweise schon einen laufenden Task hat, wird er
        # bewusst als unbekannt abgeschlossen. So hängt die UI nie dauerhaft auf
        # "läuft", wenn eine Prompt-Erkennung nicht möglich war.
        if self.active_command_task is not None and self.active_command_task.get("status") == "läuft":
            self.finish_active_command_task(status="unbekannt")

        task = {
            "original_command": str(original_command or "").strip(),
            "sent_command": str(sent_command or "").strip(),
            "pre_commands": str(pre_commands or "").strip(),
            "started_at": time.time(),
            "ended_at": None,
            "duration": None,
            "working_directory": str(getattr(self, "current_working_directory", "") or ""),
            "shell_type": str(getattr(self, "shell_type", "") or ""),
            "terminal_engine": str(self.actual_terminal_engine()),
            "exit_code": None,
            "status": "läuft",
            "stdout": "",
            "stderr": "",
            "item": None,
        }
        task_table = self.command_task_list
        task_table.insertRow(0)
        for column in range(task_table.columnCount()):
            item = QTableWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, task)
            task_table.setItem(0, column, item)
        task["item"] = task_table.item(0, 0)
        self.command_tasks.append(task)
        task_table.setCurrentCell(0, 1)
        while task_table.rowCount() > 80:
            old_row = task_table.rowCount() - 1
            old_task = self.command_task_from_table_row(old_row)
            task_table.removeRow(old_row)
            if old_task in self.command_tasks and old_task is not self.active_command_task:
                self.command_tasks.remove(old_task)
        self.update_command_task_header_label()
        self.active_command_task = task
        self.update_command_task_item(task)
        return task

    def append_active_command_task_sent_command(self, sent_command):
        task = self.active_command_task
        if task is None or task.get("status") != "läuft":
            return
        text = str(sent_command or "").strip()
        if not text:
            return
        current = str(task.get("sent_command") or "").strip()
        if not current:
            task["sent_command"] = text
        elif text not in current.split("\n"):
            task["sent_command"] = current + "\n" + text
        self.update_command_task_item(task)

    def append_command_task_output(self, stream_name, text):
        task = self.active_command_task
        if task is None or task.get("status") != "läuft":
            return
        key = "stderr" if stream_name == "stderr" else "stdout"
        task[key] = self.trim_command_task_text(str(task.get(key) or "") + str(text or ""))
        self.update_command_task_item(task)

    def finish_active_command_task(self, status="", exit_code=None):
        task = self.active_command_task
        if task is None:
            return
        if task.get("status") != "läuft":
            return
        stderr = str(task.get("stderr") or "").strip()
        if not status:
            status = "Fehler" if stderr else "erfolgreich"
        task["status"] = status
        task["ended_at"] = time.time()
        task["duration"] = max(0.0, float(task["ended_at"]) - float(task.get("started_at") or task["ended_at"]))
        if exit_code is not None:
            task["exit_code"] = int(exit_code)
            if int(exit_code) != 0:
                task["status"] = "Fehler"
            elif status in {"", "unbekannt"}:
                task["status"] = "erfolgreich"
        self.update_command_task_item(task)
        self.active_command_task = None

    def finish_active_command_task_if_prompt_returned(self):
        task = self.active_command_task
        if task is None or task.get("status") != "läuft":
            return
        if self.output_ends_with_shell_prompt(self.terminal_output_text_for_state_checks()):
            self.finish_active_command_task()

    def command_task_from_item(self, item):
        if item is None:
            return None
        task = item.data(Qt.ItemDataRole.UserRole)
        return task if isinstance(task, dict) else None

    def command_task_from_table_row(self, row):
        task_table = getattr(self, "command_task_list", None)
        if task_table is None or row < 0 or row >= task_table.rowCount():
            return None
        for column in range(task_table.columnCount()):
            task = self.command_task_from_item(task_table.item(row, column))
            if task:
                return task
        return None

    def selected_command_task(self):
        task_table = getattr(self, "command_task_list", None)
        if task_table is None:
            return None
        task = self.command_task_from_item(task_table.currentItem())
        if task:
            return task
        return self.command_task_from_table_row(task_table.currentRow())

    def rerun_command_task_from_table_cell(self, row, column):
        self.rerun_command_task(self.command_task_from_table_row(row))

    def rerun_command_task(self, task=None):
        task = task or self.selected_command_task()
        if not task:
            return
        command = str(task.get("original_command") or task.get("sent_command") or "").strip()
        if not command:
            return
        self.run_text_command(command)

    def load_command_task_into_input(self, task=None):
        task = task or self.selected_command_task()
        if not task:
            return
        command = str(task.get("original_command") or task.get("sent_command") or "").strip()
        if not command:
            return
        self.input_line.setPlainText(command)
        self.input_line.moveCursor(QTextCursor.MoveOperation.End)
        self.input_line.setFocus()

    def command_task_details_text(self, task):
        if not task:
            return ""
        lines = [
            f"Status: {task.get('status', 'unbekannt')}",
            f"Originalbefehl: {task.get('original_command', '')}",
            f"Gesendet: {task.get('sent_command', '')}",
            f"Start: {self.command_task_time_label(task.get('started_at'))}",
            f"Arbeitsordner: {task.get('working_directory', '')}",
            f"Shell: {task.get('shell_type', '')}",
            f"Engine: {task.get('terminal_engine', '')}",
        ]
        if task.get("pre_commands"):
            lines.append(f"Vorbefehl: {task.get('pre_commands')}")
        if task.get("ended_at"):
            lines.append(f"Ende: {self.command_task_time_label(task.get('ended_at'))}")
        if task.get("duration") is not None:
            lines.append(f"Dauer: {self.command_task_duration_label(task)}")
        if task.get("exit_code") is not None:
            lines.append(f"Exit-Code: {task.get('exit_code')}")
        stdout = str(task.get("stdout") or "").strip()
        stderr = str(task.get("stderr") or "").strip()
        if stdout:
            lines.extend(["", "Ausgabe-Ausschnitt:", stdout])
        if stderr:
            lines.extend(["", "Fehler-Ausschnitt:", stderr])
        return "\n".join(lines)

    def all_command_tasks_text(self):
        lines = []
        for task in self.command_tasks:
            lines.append(self.command_task_details_text(task))
        return "\n\n---\n\n".join(line for line in lines if line.strip())

    def delete_command_task(self, task=None):
        task = task or self.selected_command_task()
        if not task:
            return
        row = self.command_task_row(task)
        if row >= 0:
            self.command_task_list.removeRow(row)
        if task in self.command_tasks:
            self.command_tasks.remove(task)
        if self.active_command_task is task:
            self.active_command_task = None
        self.update_command_task_header_label()

    def clear_command_tasks(self):
        self.command_tasks.clear()
        self.active_command_task = None
        self.command_task_list.setRowCount(0)
        self.update_command_task_header_label()


    def shell_split_command_for_undo(self, command):
        text = str(command or "").strip()
        if not text:
            return []
        try:
            return shlex.split(text, posix=(sys.platform != "win32"))
        except ValueError:
            return text.split()

    def mkdir_undo_target_for_task(self, task):
        """Return a Path for simple mkdir/md commands that can be safely offered as undo."""
        if not task:
            return None
        command = str(task.get("original_command") or task.get("sent_command") or "").strip()
        if "\n" in command or "\r" in command or not command:
            return None
        parts = self.shell_split_command_for_undo(command)
        if len(parts) < 2:
            return None
        verb = str(parts[0] or "").lower().strip()
        if verb not in {"mkdir", "md"}:
            return None
        shell_type = str(task.get("shell_type") or getattr(self, "shell_type", "") or "").lower()
        if shell_type == "wsl" and sys.platform == "win32":
            return None
        targets = []
        skip_next = False
        for token in parts[1:]:
            token = str(token or "").strip()
            if not token:
                continue
            if skip_next:
                skip_next = False
                continue
            if token in {"--mode", "-m"}:
                skip_next = True
                continue
            if token.startswith("-"):
                continue
            targets.append(token)
        if len(targets) != 1:
            return None
        target_text = targets[0].strip().strip('"')
        if not target_text:
            return None
        target = Path(os.path.expanduser(target_text))
        if not target.is_absolute():
            cwd = str(task.get("working_directory") or getattr(self, "current_working_directory", "") or "").strip()
            if not cwd:
                return None
            target = Path(cwd) / target
        try:
            return target.resolve()
        except OSError:
            return target

    def can_undo_command_task(self, task):
        target = self.mkdir_undo_target_for_task(task)
        return bool(target and target.exists() and target.is_dir())

    def undo_command_task(self, task=None):
        task = task or self.selected_command_task()
        target = self.mkdir_undo_target_for_task(task)
        if target is None:
            QMessageBox.information(
                self,
                "Kein sicheres Rückgängig möglich",
                "Für diesen Befehl kann ShellDeck keinen sicheren Rückgängig-Schritt ermitteln.",
            )
            return
        if not target.exists() or not target.is_dir():
            QMessageBox.information(
                self,
                "Ordner nicht gefunden",
                f"Der Ordner existiert nicht mehr oder ist kein Ordner:\n{target}",
            )
            return

        try:
            is_empty = not any(target.iterdir())
        except OSError as exc:
            QMessageBox.warning(self, "Ordner kann nicht geprüft werden", f"{target}\n\n{exc}")
            return

        if is_empty:
            question = (
                "Dieser mkdir-Befehl kann rückgängig gemacht werden, indem der leere Ordner gelöscht wird.\n\n"
                f"Ordner:\n{target}\n\nLeeren Ordner löschen?"
            )
            answer = QMessageBox.question(
                self,
                "mkdir rückgängig machen",
                question,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            try:
                target.rmdir()
                self.window.show_status(f"Ordner gelöscht: {target}")
            except OSError as exc:
                QMessageBox.warning(self, "Ordner konnte nicht gelöscht werden", f"{target}\n\n{exc}")
            return

        question = (
            "Der Ordner ist nicht mehr leer. Beim Rückgängig-Machen würden auch alle enthaltenen Dateien "
            "und Unterordner gelöscht.\n\n"
            f"Ordner:\n{target}\n\nWirklich vollständig löschen?"
        )
        answer = QMessageBox.question(
            self,
            "Nicht leeren Ordner löschen?",
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            shutil.rmtree(target)
            self.window.show_status(f"Ordner mit Inhalt gelöscht: {target}")
        except OSError as exc:
            QMessageBox.warning(self, "Ordner konnte nicht gelöscht werden", f"{target}\n\n{exc}")

    def show_command_task_context_menu(self, pos):
        task_table = self.command_task_list
        item = task_table.itemAt(pos)
        if item is not None:
            task_table.setCurrentCell(item.row(), item.column())
        task = self.command_task_from_item(item) or self.command_task_from_table_row(task_table.currentRow())

        menu = QMenu(self)
        menu.setToolTipsVisible(True)

        rerun_action = QAction("Befehl erneut ausführen", self)
        rerun_action.setToolTip("Führt den ausgewählten Befehl erneut im aktiven Terminal aus.")
        rerun_action.setEnabled(bool(task))
        rerun_action.triggered.connect(lambda: self.rerun_command_task(task))
        menu.addAction(rerun_action)

        load_input_action = QAction("Befehl in Eingabe übernehmen", self)
        load_input_action.setToolTip("Übernimmt den Befehl in das Eingabefeld, ohne ihn sofort auszuführen.")
        load_input_action.setEnabled(bool(task))
        load_input_action.triggered.connect(lambda: self.load_command_task_into_input(task))
        menu.addAction(load_input_action)

        undo_action = QAction("Befehl rückgängig machen…", self)
        undo_action.setToolTip(
            "Nur für sicher erkannte einfache Befehle aktiv, z.B. mkdir. "
            "Bei nicht leerem Ordner fragt ShellDeck vor dem Löschen ausdrücklich nach."
        )
        undo_action.setEnabled(bool(task and self.can_undo_command_task(task)))
        undo_action.triggered.connect(lambda: self.undo_command_task(task))
        menu.addAction(undo_action)

        delete_action = QAction("Diesen Befehl löschen", self)
        delete_action.setToolTip("Entfernt nur diesen Eintrag aus der Liste. Der Befehl selbst wird nicht rückgängig gemacht.")
        delete_action.setEnabled(bool(task))
        delete_action.triggered.connect(lambda: self.delete_command_task(task))
        menu.addAction(delete_action)

        clear_action = QAction("Letzte Befehle leeren", self)
        clear_action.setToolTip("Leert die sichtbare Befehlsliste dieses Tabs.")
        clear_action.setEnabled(bool(self.command_tasks))
        clear_action.triggered.connect(self.clear_command_tasks)
        menu.addAction(clear_action)

        menu.addSeparator()

        copy_original_action = QAction("Originalbefehl kopieren", self)
        copy_original_action.setToolTip("Kopiert den ursprünglich eingegebenen Befehl in die Zwischenablage.")
        copy_original_action.setEnabled(bool(task))
        copy_original_action.triggered.connect(lambda: QApplication.clipboard().setText(str(task.get("original_command") or "") if task else ""))
        menu.addAction(copy_original_action)

        copy_sent_action = QAction("Gesendeten Befehl kopieren", self)
        copy_sent_action.setToolTip("Kopiert den tatsächlich an die Shell gesendeten Befehl in die Zwischenablage.")
        copy_sent_action.setEnabled(bool(task))
        copy_sent_action.triggered.connect(lambda: QApplication.clipboard().setText(str(task.get("sent_command") or "") if task else ""))
        menu.addAction(copy_sent_action)

        copy_details_action = QAction("Befehlsdetails kopieren", self)
        copy_details_action.setToolTip("Kopiert Status, Zeiten, Ordner, Shell, Engine und Ausgabeausschnitte dieses Eintrags.")
        copy_details_action.setEnabled(bool(task))
        copy_details_action.triggered.connect(lambda: QApplication.clipboard().setText(self.command_task_details_text(task)))
        menu.addAction(copy_details_action)

        copy_all_action = QAction("Alle Befehlsdetails kopieren", self)
        copy_all_action.setToolTip("Kopiert die Details aller sichtbaren Befehle in die Zwischenablage.")
        copy_all_action.setEnabled(bool(self.command_tasks))
        copy_all_action.triggered.connect(lambda: QApplication.clipboard().setText(self.all_command_tasks_text()))
        menu.addAction(copy_all_action)

        copy_stdout_action = QAction("Ausgabe kopieren", self)
        copy_stdout_action.setToolTip("Kopiert den gespeicherten Ausgabe-Ausschnitt dieses Befehls.")
        copy_stdout_action.setEnabled(bool(task and str(task.get("stdout") or "").strip()))
        copy_stdout_action.triggered.connect(lambda: QApplication.clipboard().setText(str(task.get("stdout") or "") if task else ""))
        menu.addAction(copy_stdout_action)

        copy_stderr_action = QAction("Fehlerausgabe kopieren", self)
        copy_stderr_action.setToolTip("Kopiert den gespeicherten Fehlerausgabe-Ausschnitt dieses Befehls.")
        copy_stderr_action.setEnabled(bool(task and str(task.get("stderr") or "").strip()))
        copy_stderr_action.triggered.connect(lambda: QApplication.clipboard().setText(str(task.get("stderr") or "") if task else ""))
        menu.addAction(copy_stderr_action)

        menu.addSeparator()

        expand_action = QAction("Letzte Befehle ausklappen", self)
        expand_action.setToolTip("Zeigt die Tabelle der letzten Befehle unter der Terminalausgabe an.")
        expand_action.setEnabled(not bool(getattr(self, "command_task_panel_expanded", False)))
        expand_action.triggered.connect(lambda: self.set_command_task_panel_expanded(True))
        menu.addAction(expand_action)

        collapse_action = QAction("Letzte Befehle einklappen", self)
        collapse_action.setToolTip("Klappt die Tabelle ein, lässt die schmale Überschrift aber sichtbar.")
        collapse_action.setEnabled(bool(getattr(self, "command_task_panel_expanded", False)))
        collapse_action.triggered.connect(lambda: self.set_command_task_panel_expanded(False))
        menu.addAction(collapse_action)

        menu.exec(task_table.viewport().mapToGlobal(pos))

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
            output_area is not None
            and source is output_area
            and event.type() == QEvent.Type.KeyPress
            and self.inline_mode_active()
        ):
            if self.handle_inline_terminal_key(event):
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

    def is_safe_restore_command(self, command):
        """Beim Restore werden nur venv-Aktivierungen automatisch ausgeführt.

        Gespeicherte letzte Befehle sind reine Historie/Anzeige. Alles, was
        keine venv-Aktivierung ist — insbesondere Befehle, die auf ShellDeck
        selbst zeigen (z.B. "python src/main.py") — wird beim Start, Tab- oder
        Workspace-Restore niemals automatisch erneut ausgeführt.
        """
        text = str(command or "").strip()
        if not text:
            return False
        if command_targets_shelldeck(text):
            return False
        return bool(self.command_looks_like_venv_activation(text))

    def run_restore_command(self, command=None):
        text = str(command or "").strip() or self.current_restore_command()
        if not text:
            return False
        normalizer = getattr(self.window, "normalize_restore_command_for_shell", None)
        if callable(normalizer):
            text = normalizer(text, self.shell_type)
        if not self.is_safe_restore_command(text):
            self.output_area.append(
                f"\n[Gespeicherter Befehl wird beim Start nicht automatisch ausgeführt: {text}]\n"
            )
            return False
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
            self.current_command = self.pending_command_text()
            self.history_index = len(history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
        self.set_pending_command_text(history[self.history_index])

    def show_next_command(self):
        history = self.tab_history()
        if not history:
            return
        if self.history_index < len(history) - 1:
            self.history_index += 1
            self.set_pending_command_text(history[self.history_index])
        elif self.history_index == len(history) - 1:
            self.history_index = -1
            self.set_pending_command_text(self.current_command)

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
        self.queue_terminal_output(data)

    def handle_client_stderr(self):
        if self.client_process is None:
            return
        data = self._decode_process_output(self.client_process.readAllStandardError())
        self.queue_terminal_output(data, self.terminal_stderr_color())

    def handle_client_finished(self, exit_code, exit_status):
        label = self.client_mode_name or "Client"
        self.queue_terminal_output(f"\n[{label}-Client beendet, Exitcode {exit_code}]\n")
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
            if html and len(html) <= OLLAMA_HTML_INLINE_RENDER_LIMIT and len(text) <= OLLAMA_HTML_INLINE_RENDER_LIMIT:
                cursor = QTextCursor(self.output_area.document())
                insert_position = self.inline_output_insert_position()
                if insert_position is None:
                    cursor.movePosition(QTextCursor.MoveOperation.End)
                else:
                    cursor.setPosition(insert_position)
                cursor.insertHtml(html)
                cursor.insertText("\n")
                self.output_area.moveCursor(QTextCursor.MoveOperation.End)
                self.output_area.ensureCursorVisible()
            else:
                self.queue_terminal_output(f"\nOllama → {text}\n")
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
            self.restore_terminal_highlighter_if_safe()

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

    def terminal_output_text_for_state_checks(self):
        """Return visible output plus queued text that is not painted yet.

        Terminal output is drained asynchronously for UI performance. The shell
        prompt can already be in ``_output_queue`` while ``output_area`` still
        does not contain it. State checks must include that queued text,
        otherwise a finished command can be mistaken for an interactive/running
        process and the next normal command bypasses history, Vorbefehl and
        command translation.
        """
        try:
            output = self.output_area.toPlainText()
        except Exception:
            output = ""
        try:
            queued = "".join(str(item[0] or "") for item in getattr(self, "_output_queue", []) if item)
        except Exception:
            queued = ""
        return output + queued

    def command_appears_to_be_running(self):
        if not getattr(self, "_awaiting_command_completion", False):
            return False
        if getattr(self, "client_mode_active", False) or getattr(self, "password_prompt_active", False):
            return False
        output = self.terminal_output_text_for_state_checks()
        if self.output_ends_with_shell_prompt(output):
            self._awaiting_command_completion = False
            self.finish_active_command_task_if_prompt_returned()
            return False
        if self.output_ends_with_continuation_prompt(output):
            return True
        if self.output_contains_interactive_prompt(output):
            return True
        return True

    def update_command_completion_state_from_output(self):
        output = self.terminal_output_text_for_state_checks()
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
            return self.output_contains_interactive_prompt(self.terminal_output_text_for_state_checks())
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

        prefix_text = ""
        prefix_commands = []
        if not self.client_mode_active:
            prefix_text = self.window.active_pre_command_text()
            if prefix_text:
                self.window.remember_pre_command_text(prefix_text)
                prefix_commands = self.command_sequence_from_text(prefix_text, include_prefix=False)

        user_commands = self.command_sequence_from_text(command_text, include_prefix=False)
        commands_with_origin = [(command, False) for command in prefix_commands] + [(command, True) for command in user_commands]
        if not commands_with_origin:
            return

        history_entry = command_text
        self.add_command_history(history_entry)
        self.update_restore_command_from_command(history_entry)
        self.history_index = -1
        self.current_command = ""

        task_started = False
        for raw_command, is_user_command in commands_with_origin:
            command = self.translate_cross_platform_command(raw_command)
            ollama_model = self.parse_ollama_run_model(command)
            if ollama_model:
                self.start_ollama_prompt_mode(ollama_model)
                continue
            direct_client = self.parse_direct_client_command(command)
            if direct_client:
                self.start_direct_client_process(direct_client)
                continue
            if command.lower() in ("cls", "clear"):
                if is_user_command and not task_started:
                    self.start_command_task(command_text, command, prefix_text)
                    task_started = True
                elif is_user_command:
                    self.append_active_command_task_sent_command(command)
                self.output_area.clear()
                self._awaiting_command_completion = False
                if getattr(self, "interaction_prompt_active", False):
                    self.reset_interaction_prompt_mode()
                if is_user_command:
                    self.finish_active_command_task(status="erfolgreich")
                self.update_input_prompt_label()
            elif self.process.state() != QProcess.ProcessState.Running:
                self.output_area.append(
                    f"Shell ist nicht aktiv: {self.process.errorString() or 'Prozess wurde beendet.'}"
                )
                if is_user_command and task_started:
                    self.finish_active_command_task(status="Fehler")
                break
            else:
                if is_user_command and not task_started:
                    self.start_command_task(command_text, command, prefix_text)
                    task_started = True
                elif is_user_command:
                    self.append_active_command_task_sent_command(command)
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
        self.queue_terminal_output(data)
        self.append_command_task_output("stdout", data)
        self.handle_possible_password_prompt(data)
        self.handle_possible_interactive_prompt(data)
        self.refresh_password_prompt_state_after_output()
        self.refresh_interaction_prompt_state_after_output()
        self.finish_active_command_task_if_prompt_returned()
        QTimer.singleShot(120, self.update_input_prompt_label)

    def handle_stderr(self):
        data = self.decoded_terminal_output(self.process.readAllStandardError())
        self.queue_terminal_output(data, self.terminal_stderr_color())
        self.append_command_task_output("stderr", data)
        self.handle_possible_password_prompt(data)
        self.handle_possible_interactive_prompt(data)
        self.refresh_password_prompt_state_after_output()
        self.refresh_interaction_prompt_state_after_output()
        self.finish_active_command_task_if_prompt_returned()
        QTimer.singleShot(120, self.update_input_prompt_label)

    def handle_finished(self, exit_code, exit_status):
        self.set_client_mode(False)
        self.finish_active_command_task(status=("erfolgreich" if int(exit_code) == 0 else "Fehler"), exit_code=exit_code)
        self.queue_terminal_output(f"\nProcess finished with exit code {exit_code}")

    def handle_process_error(self, error):
        self.set_client_mode(False)
        self.queue_terminal_output(f"\nShell konnte nicht gestartet werden: {self.process.errorString()}")

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
        if self.terminal_document_is_small_enough_for_highlighting():
            self.highlighter.set_terminal_colors(terminal_colors)
        else:
            self.highlighter.set_terminal_colors(terminal_colors, rehighlight=False)
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



    # ---- Stabile oeffentliche API fuer einbettende Anwendungen (z.B. Visual Edit) ----

    def run_command(self, command, cwd=None):
        """Fuehrt einen Shell-Befehl ueber die normale ShellDeck-Pipeline aus.

        Optional wird vorher der Arbeitsordner gewechselt. Der Befehl
        durchlaeuft dieselbe Verarbeitung wie eine manuelle Eingabe
        (Historie, Passwort-/Interaktions-/Client-Modus, cls, Vorbefehle).
        """
        if cwd:
            self.set_working_directory(cwd)
        text = str(command or "").strip()
        if not text:
            return
        if self.inline_mode_active() and self.inline_markers_valid():
            self.set_inline_input_text(text)
            self.submit_inline_command()
            return
        self.input_line.setPlainText(text)
        self.execute_command()

    def append_output(self, text):
        """Zeigt Text als normale Ausgabe an (keine echte Shell-Ausgabe noetig)."""
        self.queue_terminal_output(text)

    def append_error(self, text):
        """Zeigt Text in der Fehlerfarbe (stderr) an."""
        self.queue_terminal_output(text, self.terminal_stderr_color())

    def append_system_message(self, text):
        """Zeigt eine Systemmeldung der einbettenden Anwendung an.

        Systemmeldungen sind keine Shell-Ausgaben; sie werden farblich wie
        Befehle hervorgehoben und immer als eigene Zeile ausgegeben.
        """
        value = str(text or "").rstrip("\n")
        if not value:
            return
        color = QColor(self.window.terminal_color("command", "#7DD3FC"))
        self.queue_terminal_output(f"{value}\n", color)

    def clear_output(self):
        """Leert die Terminalausgabe (im Reines-Terminal-Modus mit frischem Prompt)."""
        self.clear_terminal_output()

    def set_working_directory(self, path):
        """Setzt den Arbeitsordner; bei laufender Shell per cd-Befehl."""
        text = str(path or "").strip()
        if not text:
            return
        try:
            directory = Path(text).expanduser()
            if not directory.is_dir():
                self.append_system_message(f"[Arbeitsordner nicht gefunden: {text}]")
                return
            resolved = str(directory.resolve())
        except OSError:
            self.append_system_message(f"[Arbeitsordner ungueltig: {text}]")
            return
        self.current_working_directory = resolved
        process = getattr(self, "process", None)
        if process is not None and process.state() == QProcess.ProcessState.Running:
            if str(self.shell_type or "").lower() == "cmd":
                self.write_shell_command(f'cd /d "{resolved}"')
            else:
                self.write_shell_command(f'cd "{resolved}"')
        self.update_input_prompt_label()

    def get_working_directory(self):
        """Liefert den aktuell erkannten Arbeitsordner."""
        return str(self.refresh_current_working_directory() or "")

    def stop_current_process(self):
        """Unterbricht den laufenden Befehl/Prozess (wie Ctrl+C)."""
        self.interrupt_current_command()

    def send_text(self, text):
        """Sendet Text roh an den laufenden Prozess (ohne implizites Enter)."""
        payload = str(text or "")
        if not payload:
            return
        process = getattr(self, "process", None)
        if process is None or process.state() != QProcess.ProcessState.Running:
            self.append_system_message("[Shell ist nicht aktiv; Text wurde nicht gesendet.]")
            return
        process.write(payload.encode("utf-8", errors="replace"))
        process.waitForBytesWritten(1000)

    def send_return(self):
        """Sendet ein einzelnes Return/Enter an den laufenden Prozess."""
        self.send_return_key()


# Rueckwaertskompatibler Klassenname: Die ShellDeck-App (Tabs, Profile,
# Workspaces, isinstance-Pruefungen) verwendet weiterhin "TerminalTab".
TerminalTab = ShellDeckTerminalWidget

__all__ = [
    "ShellDeckTerminalWidget",
    "TerminalTab",
    "DefaultTerminalHost",
    "command_targets_shelldeck",
    "TerminalOutputArea",
    "TerminalHighlighter",
    "OllamaApiWorker",
    "PtyTerminalProcess",
    "PtyReaderThread",
    "PosixPtyChild",
]
