import sys
import re
import json
import os
import traceback
import faulthandler
import shutil
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget, 
    QPlainTextEdit, QFontDialog, QColorDialog, QInputDialog)
from PySide6.QtCore import Qt, QProcess, QEvent
from PySide6.QtGui import QTextCursor, QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QAction, QShortcut


LOG_FILE = Path.home() / "TerminalApp.log"
_LOG_HANDLE = None


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
    def __init__(self, parent=None):
        super().__init__(parent)
        self.highlighting_rules = []
        
        # Error patterns
        error_format = QTextCharFormat()
        error_format.setForeground(QColor("#ff6b6b"))
        self.highlighting_rules.append((re.compile(r'error', re.IGNORECASE), error_format))
        
        # Command patterns
        command_format = QTextCharFormat()
        command_format.setForeground(QColor("#7dd3fc"))
        self.highlighting_rules.append((re.compile(r'\b(cd|ls|pwd|mkdir|rm|cp|mv|grep|find|cat|echo|exit)\b'), command_format))
        
        # Path patterns
        path_format = QTextCharFormat()
        path_format.setForeground(QColor("#86efac"))
        self.highlighting_rules.append((re.compile(r'[\w\-\_/\.]+[/\\]'), path_format))
        
        # Number patterns
        number_format = QTextCharFormat()
        number_format.setForeground(QColor("#c084fc"))
        self.highlighting_rules.append((re.compile(r'\b\d+\b'), number_format))
    
    def highlightBlock(self, text):
        for pattern, format in self.highlighting_rules:
            for match in pattern.finditer(text):
                start = match.start()
                length = match.end() - start
                self.setFormat(start, length, format)
class TerminalWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Terminal Emulator')
        self.history = []
        self.history_index = -1
        self.current_command = ""
        self.default_command = ""
        self.color_scheme_name = "Dunkel"
        self.shell_type = "cmd"
        self.max_history_size = 1000
        self.history_file = Path.home() / ".visual_edit_terminal_history"
        self.settings_file = Path.home() / ".visual_edit_terminal_settings.json"
        self.load_history()
        
        # Create central widget and layout
        # Create menu bar
        menubar = self.menuBar()
        file_menu = menubar.addMenu("&Datei")
        
        # Add exit action
        exit_action = QAction("&Beenden", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # Add settings menu
        settings_menu = menubar.addMenu("&Einstellungen")
        
        # Add font settings action
        font_action = QAction("Schriftart", self)
        font_action.triggered.connect(self.show_font_dialog)
        settings_menu.addAction(font_action)
        
        # Add color scheme action
        color_action = QAction("Farbschema", self)
        color_action.triggered.connect(self.show_color_dialog)
        settings_menu.addAction(color_action)
        
        # Add default command action
        cmd_action = QAction("Standardbefehl", self)
        cmd_action.triggered.connect(self.show_command_dialog)
        settings_menu.addAction(cmd_action)
        
        # Add history size action
        history_action = QAction("History-Größe", self)
        history_action.triggered.connect(self.show_history_dialog)
        settings_menu.addAction(history_action)

        # Add shell selection action
        shell_action = QAction("Shell", self)
        shell_action.triggered.connect(self.select_shell)
        settings_menu.addAction(shell_action)
        
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        
        # Create output text area
        self.output_area = QTextEdit()
        self.output_area.setReadOnly(True)
        self.output_area.setFont(QFont("Courier New", 10))
        
        # Add syntax highlighter
        self.highlighter = TerminalHighlighter(self.output_area.document())
        layout.addWidget(self.output_area)
        
        # Create input line
        self.input_line = QPlainTextEdit()
        self.input_line.setMaximumHeight(110)
        self.input_line.installEventFilter(self)
        layout.addWidget(self.input_line)

        # Apply persisted settings only after the widgets they touch exist.
        self.load_settings()
        self.apply_color_scheme()
        
        # Start with system shell
        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.handle_finished)
        self.process.errorOccurred.connect(self.handle_process_error)

        self.start_shell()
        # Connect Ctrl+C shortcut to stop_process
        self.shortcut_stop = QShortcut("Ctrl+C", self)
        self.shortcut_stop.activated.connect(self.stop_process)

        if self.default_command and self.process.waitForStarted(2000):
            self.process.write(self.default_command.encode() + b"\n")

    def stop_process(self):
        if self.process and self.process.state() == QProcess.Running:
            self.process.terminate()
            if not self.process.waitForFinished(3000):
                self.process.kill()
                self.process.waitForFinished(1000)
    def select_shell(self):
        shells = ["cmd", "powershell"]
        if shutil.which("pwsh.exe") is not None:
            shells.append("pwsh")
        current_index = shells.index(self.shell_type) if self.shell_type in shells else 0
        selected, ok = QInputDialog.getItem(
            self,
            "Shell auswahl",
            "Shell waehlen:",
            shells,
            current_index,
            False,
        )
        if ok and selected:
            self.shell_type = selected
            self.restart_shell()
            self.save_settings()

    def start_shell(self):
        shell_path = self.system_shell()
        if not shutil.which(shell_path) and sys.platform == "win32":
            for fallback in ["cmd.exe", "powershell.exe"]:
                if shutil.which(fallback):
                    shell_path = fallback
                    break
        self.process.start(shell_path)

    def restart_shell(self):
        if hasattr(self, "process") and self.process.state() == QProcess.Running:
            self.stop_process()
            while self.process.state() != QProcess.NotRunning:
                self.process.waitForFinished(500)
            self.output_area.clear()
        self.start_shell()

    def system_shell(self) -> str:
        if sys.platform != "win32":
            return os.environ.get("SHELL") or "bash"
        shell_map = {
            "cmd": "cmd.exe",
            "powershell": "powershell.exe",
            "pwsh": "pwsh.exe",
        }
        executable = shell_map.get(self.shell_type, "cmd.exe")
        if shutil.which(executable) is not None:
            return executable
        # Fallback chain
        for fallback in ("powershell.exe", "cmd.exe"):
            if shutil.which(fallback) is not None:
                return fallback
        return "cmd.exe"
    def load_history(self):
        if self.history_file.exists():
            try:
                lines = self.history_file.read_text(encoding='utf-8').splitlines()
                # Remove empty lines
                lines = [line for line in lines if line.strip()]
                # Keep only the last max_history_size entries
                self.history = lines[-self.max_history_size:]
            except Exception:
                self.history = []
        else:
            self.history = []

    def save_history(self):
        try:
            # Limit to max_history_size entries
            history_to_save = self.history[-self.max_history_size:]
            self.history_file.write_text('\n'.join(history_to_save), encoding='utf-8')
        except Exception:
            pass

    def load_settings(self):
        if not self.settings_file.exists():
            return

        try:
            settings = json.loads(self.settings_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return

        font_text = str(settings.get("font", "")).strip()
        if font_text and hasattr(self, "output_area") and hasattr(self, "input_line"):
            font = QFont()
            if font.fromString(font_text):
                self.output_area.setFont(font)
                self.input_line.setFont(font)

        self.default_command = str(settings.get("default_command", self.default_command or "") or "")
        self.color_scheme_name = str(settings.get("color_scheme_name", self.color_scheme_name or "Dunkel") or "Dunkel")

        try:
            self.max_history_size = max(1, int(settings.get("max_history_size", self.max_history_size)))
        except (TypeError, ValueError):
            self.max_history_size = 1000

        self.history = self.history[-self.max_history_size:]

        shell_type_val = str(settings.get("shell_type", self.shell_type or "cmd") or "cmd")
        if shell_type_val in ("cmd", "powershell"):
            self.shell_type = shell_type_val
        elif shell_type_val == "pwsh" and shutil.which("pwsh.exe") is not None:
            self.shell_type = "pwsh"

    def save_settings(self):
        settings = {
            "font": self.output_area.font().toString(),
            "color_scheme_name": self.color_scheme_name,
            "default_command": self.default_command,
            "max_history_size": self.max_history_size,
            "shell_type": self.shell_type,
        }

        try:
            self.settings_file.write_text(
                json.dumps(settings, ensure_ascii=False, indent=4),
                encoding="utf-8",
            )
        except OSError:
            pass

    def apply_color_scheme(self):
        schemes = {
            "Dunkel": {
                "output_bg": "#1e1e1e",
                "output_fg": "#d4d4d4",
                "input_bg": "#252526",
                "input_fg": "#ffffff",
            },
            "Hell": {
                "output_bg": "#ffffff",
                "output_fg": "#202020",
                "input_bg": "#f3f3f3",
                "input_fg": "#202020",
            },
            "Hoher Kontrast": {
                "output_bg": "#000000",
                "output_fg": "#ffffff",
                "input_bg": "#000000",
                "input_fg": "#ffff00",
            },
        }
        scheme = schemes.get(self.color_scheme_name, schemes["Dunkel"])
        self.output_area.setStyleSheet(
            f"QTextEdit {{ background-color: {scheme['output_bg']}; color: {scheme['output_fg']}; }}"
        )
        self.output_area.setTextColor(QColor(scheme["output_fg"]))
        self.input_line.setStyleSheet(
            f"QPlainTextEdit {{ background-color: {scheme['input_bg']}; color: {scheme['input_fg']}; }}"
        )
    def eventFilter(self, source, event):
        if source is self.input_line and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not (event.modifiers() & Qt.ControlModifier):
                self.execute_command()
                return True
            if event.key() in (Qt.Key_Return, Qt.Key_Enter) and event.modifiers() & Qt.ControlModifier:
                self.input_line.insertPlainText('\n')
                return True
            if event.key() == Qt.Key_Up:
                self.show_previous_command()
                return True
            elif event.key() == Qt.Key_Down:
                self.show_next_command()
                return True
        return super().eventFilter(source, event)
    
    def show_previous_command(self):
        if not self.history:
            return
        
        if self.history_index == -1:
            self.current_command = self.input_line.toPlainText()
            self.history_index = len(self.history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
            
        self.input_line.setPlainText(self.history[self.history_index])
    
    def show_next_command(self):
        if not self.history:
            return
            
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.input_line.setPlainText(self.history[self.history_index])
        elif self.history_index == len(self.history) - 1:
            self.history_index = -1
            self.input_line.setPlainText(self.current_command)
    
    
    def show_font_dialog(self):
        current_font = self.output_area.font()
        result = QFontDialog.getFont(current_font, self, "Terminal Schriftart wählen")
        if isinstance(result, tuple) and len(result) >= 2 and isinstance(result[0], bool):
            ok, font = result[0], result[1]
        else:
            font, ok = result
        if ok:
            self.output_area.setFont(font)
            self.input_line.setFont(font)
            self.save_settings()

    def show_color_dialog(self):
        schemes = ["Dunkel", "Hell", "Hoher Kontrast"]
        current_index = schemes.index(self.color_scheme_name) if self.color_scheme_name in schemes else 0
        scheme, ok = QInputDialog.getItem(
            self,
            "Farbschema",
            "Farbschema auswählen:",
            schemes,
            current_index,
            False,
        )
        if ok and scheme:
            self.color_scheme_name = scheme
            self.apply_color_scheme()
            self.save_settings()

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
        size, ok = QInputDialog.getInt(self, "History-Größe", "Maximale Anzahl an History-Einträgen:",
                                     self.max_history_size, 1, 10000, 1)
        if ok:
            self.max_history_size = size
            self.history = self.history[-self.max_history_size:]
            self.save_history()
            self.save_settings()

    def execute_command(self):
        command_text = self.input_line.toPlainText().strip()
        commands = [line.strip() for line in command_text.splitlines() if line.strip()]
        if not commands:
            return

        # Add each command to history if not duplicate of previous command
        for cmd in commands:
            # A valid command is non-empty, not only whitespace, and not identical to the previous entry
            if cmd.strip() and (not self.history or self.history[-1] != cmd):
                self.history.append(cmd)
        self.save_history()
        self.history_index = -1
        self.current_command = ""
        
        # Process each non-empty line without displaying in output
        for command in commands:
            if command.lower() in ("cls", "clear"):
                self.output_area.clear()
            elif self.process.state() != QProcess.Running:
                self.output_area.append(
                    f"Shell ist nicht aktiv: {self.process.errorString() or 'Prozess wurde beendet.'}"
                )
                break
            else:
                self.process.write(command.encode() + b"\n")
        self.input_line.clear()
        
    def _decode_process_output(self, raw) -> str:
        data = bytes(raw)
        for encoding in ("cp850", "mbcs", "cp1252", "utf-8", "latin-1"):
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")
    def handle_stdout(self):
        data = self._decode_process_output(self.process.readAllStandardOutput())
        self.output_area.moveCursor(QTextCursor.End)
        self.output_area.insertPlainText(data)
        self.output_area.moveCursor(QTextCursor.End)
        self.output_area.ensureCursorVisible()    
    def handle_stderr(self):
        data = self._decode_process_output(self.process.readAllStandardError())
        self.output_area.moveCursor(QTextCursor.End)
        self.output_area.setTextColor(Qt.red)
        self.output_area.insertPlainText(data)
        self.output_area.setTextColor(QColor("#d4d4d4"))
        self.output_area.moveCursor(QTextCursor.End)
        self.output_area.ensureCursorVisible()    
    def handle_finished(self, exit_code, exit_status):
        self.output_area.append(f"\nProcess finished with exit code {exit_code}")

    def handle_process_error(self, error):
        self.output_area.append(f"\nShell konnte nicht gestartet werden: {self.process.errorString()}")
        
    def closeEvent(self, event):
        self.save_settings()
        if self.process.state() == QProcess.Running:
            self.process.terminate()
            if not self.process.waitForFinished(2000):
                self.process.kill()
                self.process.waitForFinished(1000)
        event.accept()


def main() -> int:
    install_crash_logging()
    app = QApplication(sys.argv)
    w = TerminalWindow()
    w.resize(800, 600)
    screen = w.screen() or QApplication.primaryScreen()
    if screen:
        frame = w.frameGeometry()
        frame.moveCenter(screen.availableGeometry().center())
        w.move(frame.topLeft())
    w.show()
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
