import sys
import re
import json
import os
import traceback
import faulthandler
import shutil
from pathlib import Path
from PySide6.QtWidgets import (QApplication, QMainWindow, QTextEdit, QVBoxLayout, QWidget,
    QPlainTextEdit, QFontDialog, QColorDialog, QInputDialog, QPushButton,
    QDialog, QFormLayout, QHBoxLayout, QLabel, QComboBox, QSlider,
    QDialogButtonBox, QCheckBox)
from PySide6.QtCore import Qt, QProcess, QEvent
from PySide6.QtGui import QTextCursor, QFont, QTextCharFormat, QColor, QSyntaxHighlighter, QAction, QShortcut, QPalette


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
        self.theme_mode = "dark"
        self.window_opacity = 100
        self.theme_config = self.default_theme_config()
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

        # Add detailed theme settings action
        theme_action = QAction("Design anpassen", self)
        theme_action.triggered.connect(self.show_theme_dialog)
        settings_menu.addAction(theme_action)

        reset_theme_action = QAction("Design auf Standard zurücksetzen", self)
        reset_theme_action.triggered.connect(self.reset_theme_defaults)
        settings_menu.addAction(reset_theme_action)
        
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
        self.central_widget = central_widget
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
        # Create execution button
        self.execute_button = QPushButton("Befehl ausführen")
        self.execute_button.clicked.connect(self.execute_command)
        layout.addWidget(self.execute_button)

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
        self.shortcut_stop.activated.connect(self.interrupt_current_command)

        if self.default_command and self.process.waitForStarted(2000):
            self.process.write(self.default_command.encode() + b"\n")

    def stop_process(self):
        if self.process and self.process.state() == QProcess.Running:
            self.process.terminate()
            if not self.process.waitForFinished(3000):
                self.process.kill()
                self.process.waitForFinished(1000)
    def interrupt_current_command(self):
        if self.process and self.process.state() == QProcess.Running:
            self.process.write(b"\x03")
            self.process.waitForBytesWritten(1000)
        else:
            self.output_area.append("Kein laufender Prozess zum Unterbrechen.")
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
        self.display_shell_status(shell_path)

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
    def display_shell_status(self, shell_path=None):
        shell_label = str(shell_path or self.system_shell() or "unknown")
        shell_name = shell_label.replace("\\", "/").rsplit("/", 1)[-1]
        if shell_name.lower().endswith(".exe"):
            shell_name = shell_name[:-4]
        message = f"Shell: {shell_name}"
        try:
            self.statusBar().showMessage(message)
        except Exception:
            if hasattr(self, "output_area"):
                self.output_area.append(message)
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

    def default_theme_config(self):
        return {
            "light": {
                "accent": "#339CFF",
                "background": "#FFFFFF",
                "foreground": "#1A1C1F",
                "input_background": "#F3F3F3",
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
                merged[mode]["accent"] = self.normalize_hex_color(
                    merged[mode].get("accent"), merged[mode]["accent"]
                )
                merged[mode]["background"] = self.normalize_hex_color(
                    merged[mode].get("background"), merged[mode]["background"]
                )
                merged[mode]["foreground"] = self.normalize_hex_color(
                    merged[mode].get("foreground"), merged[mode]["foreground"]
                )
                merged[mode]["input_background"] = self.normalize_hex_color(
                    merged[mode].get("input_background"), merged[mode]["input_background"]
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
        name = str(scheme_name or self.color_scheme_name or "Dunkel").strip().lower()
        if name == "hell":
            return "light"
        return "dark"

    def current_theme_key(self):
        if self.theme_mode == "system":
            try:
                palette_color = QApplication.palette().color(QPalette.ColorRole.Window)
                brightness = (
                    palette_color.red() * 0.299
                    + palette_color.green() * 0.587
                    + palette_color.blue() * 0.114
                )
                return "dark" if brightness < 128 else "light"
            except Exception:
                return self.theme_key_from_scheme()
        if self.theme_mode in ("light", "dark"):
            return self.theme_mode
        return self.theme_key_from_scheme()

    def active_theme(self):
        key = self.current_theme_key()
        return self.theme_config.get(key, self.default_theme_config()[key])

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
        self.theme_config = self.merge_theme_config(settings.get("theme_config", self.theme_config))

        loaded_theme_mode = str(settings.get("theme_mode", "") or "").lower().strip()
        if loaded_theme_mode in ("light", "dark", "system"):
            self.theme_mode = loaded_theme_mode
        else:
            self.theme_mode = self.theme_key_from_scheme(self.color_scheme_name)

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

        shell_type_val = str(settings.get("shell_type", self.shell_type or "cmd") or "cmd")
        if shell_type_val in ("cmd", "powershell"):
            self.shell_type = shell_type_val
        elif shell_type_val == "pwsh" and shutil.which("pwsh.exe") is not None:
            self.shell_type = "pwsh"

    def save_settings(self):
        settings = {
            "font": self.output_area.font().toString(),
            "color_scheme_name": self.color_scheme_name,
            "theme_mode": self.theme_mode,
            "theme_config": self.theme_config,
            "window_opacity": self.window_opacity,
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

    def migrate_unreadable_theme_settings(self):
        defaults = self.default_theme_config()
        for mode in ("light", "dark"):
            theme = self.theme_config.setdefault(mode, defaults[mode].copy())
            accent = self.normalize_hex_color(theme.get("accent"), defaults[mode]["accent"])
            background = self.normalize_hex_color(theme.get("background"), defaults[mode]["background"])
            input_background = self.normalize_hex_color(
                theme.get("input_background"), defaults[mode]["input_background"]
            )
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
        try:
            contrast = max(0, min(100, int(theme.get("contrast", 60))))
        except (TypeError, ValueError):
            contrast = 60

        background_rgba = self.rgba_color(background, background_opacity)
        input_background_rgba = self.rgba_color(input_background, background_opacity)

        border_width = 1 if contrast < 85 else 2
        radius = 8 if bool(theme.get("transparent_sidebar", True)) else 2
        border_color = self.readable_border_color(background)
        input_border_color = self.readable_border_color(input_background)

        self.output_area.setStyleSheet(
            "QTextEdit {"
            f" background-color: {background_rgba};"
            f" color: {foreground};"
            f" border: {border_width}px solid {border_color};"
            f" border-radius: {radius}px;"
            " padding: 8px;"
            " selection-background-color: #2D5F93;"
            "}"
            "QTextEdit:focus {"
            f" border: {border_width}px solid {accent};"
            "}"
        )
        self.output_area.setTextColor(QColor(foreground))
        self.input_line.setStyleSheet(
            "QPlainTextEdit {"
            f" background-color: {input_background_rgba};"
            f" color: {foreground};"
            f" border: {border_width}px solid {input_border_color};"
            f" border-radius: {radius}px;"
            " padding: 6px;"
            " selection-background-color: #2D5F93;"
            "}"
            "QPlainTextEdit:focus {"
            f" border: {border_width}px solid {accent};"
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
        try:
            translucent = background_opacity < 100
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, translucent)
            if hasattr(self, "central_widget"):
                self.central_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, translucent)
                self.central_widget.setStyleSheet("background: transparent;" if translucent else "")
        except Exception:
            pass
        try:
            self.setWindowOpacity(max(0.2, min(1.0, self.window_opacity / 100.0)))
        except Exception:
            pass
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
            if scheme == "Hell":
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

        contrast_row = QWidget(dialog)
        contrast_layout = QHBoxLayout(contrast_row)
        contrast_layout.setContentsMargins(0, 0, 0, 0)
        contrast_slider = QSlider(Qt.Horizontal, dialog)
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
        background_opacity_slider = QSlider(Qt.Horizontal, dialog)
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
        opacity_slider = QSlider(Qt.Horizontal, dialog)
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

        if dialog.exec() == QDialog.Accepted:
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
        size, ok = QInputDialog.getInt(self, "History-Größe", "Maximale Anzahl an History-Einträgen:",
                                     self.max_history_size, 1, 10000, 1)
        if ok:
            self.max_history_size = size
            self.history = self.history[-self.max_history_size:]
            self.save_history()
            self.save_settings()

    def execute_command(self):
        command_text = self.input_line.toPlainText().strip()
        commands = [
            cmd.strip()
            for line in command_text.splitlines()
            for cmd in line.split(';')
            if cmd.strip()
        ]
        if not commands:
            return

        # Add original input block to history so grouped commands can be recalled together
        history_entry = command_text
        if history_entry and (not self.history or self.history[-1] != history_entry):
            self.history.append(history_entry)
        self.save_history()
        self.history_index = -1
        self.current_command = ""

        # Process each non-empty command without displaying in output
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
        self.output_area.setTextColor(QColor(self.active_theme().get("foreground", "#d4d4d4")))
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
