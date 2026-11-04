"""Schnellbefehle-Seitenleiste: Qt-Oberfläche ohne Änderungen am Terminalrenderer."""
from __future__ import annotations

from time import monotonic

from PySide6.QtCore import Qt, QEvent, QTimer, Signal, QSize
from PySide6.QtGui import QCursor, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QDialog,
    QDialogButtonBox, QDockWidget, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QTextEdit, QVBoxLayout, QWidget, QKeySequenceEdit,
)

from shelldeck_quick_commands import normalized_command, resolved_command


class QuickCommandDialog(QDialog):
    def __init__(self, command: dict, shell_type: str, parent=None, shortcut_validator=None):
        super().__init__(parent)
        self._shortcut_validator = shortcut_validator
        self._accepted_shortcut = ""
        self.setWindowTitle("Schnellbefehl bearbeiten")
        self.resize(620, 460)
        form = QFormLayout(self)
        self.name = QLineEdit(self)
        self.name.setText(command.get("name", ""))
        form.addRow("Buttonname:", self.name)
        self.number_label = QCheckBox("Automatische Nummer statt Namen anzeigen", self)
        self.number_label.setChecked(bool(command.get("number_label", False)))
        form.addRow("Beschriftung:", self.number_label)
        self.command = QTextEdit(self)
        self.command.setAcceptRichText(False)
        self.command.setPlainText(resolved_command(command, shell_type))
        self._original_command = self.command.toPlainText()
        form.addRow("Shell-Befehl:", self.command)
        info = QLabel("Mehrzeilige Befehle sind erlaubt. Variablen werden erst in der Ziel-Shell ausgewertet.\n"
                      "Eine Änderung des Befehls ersetzt die automatische Linux-/Windows-/macOS-Vorlage.", self)
        info.setWordWrap(True)
        form.addRow(info)
        self.confirm = QCheckBox("Vor jeder Ausführung nachfragen", self)
        self.confirm.setChecked(bool(command.get("confirm", False)))
        form.addRow("Bestätigung:", self.confirm)
        self.use_precommand = QCheckBox("Aktivierten Vorbefehl anwenden", self)
        self.use_precommand.setChecked(bool(command.get("use_precommand", False)))
        form.addRow("Vorbefehl:", self.use_precommand)
        self.new_tab = QCheckBox("Befehl in neuem Terminal-Tab ausführen", self)
        self.new_tab.setChecked(bool(command.get("new_tab", False)))
        form.addRow("Ziel:", self.new_tab)
        shortcut_row = QWidget(self)
        shortcut_layout = QHBoxLayout(shortcut_row)
        shortcut_layout.setContentsMargins(0, 0, 0, 0)
        self.shortcut = QKeySequenceEdit(shortcut_row)
        self.shortcut.setKeySequence(QKeySequence(str(command.get("shortcut", "") or "")))
        self.shortcut.setToolTip("Tastenkombination direkt drücken; keine Texteingabe erforderlich")
        self.shortcut.setAccessibleName("Tastenkombination aufzeichnen")
        shortcut_layout.addWidget(self.shortcut, 1)
        self.clear_shortcut = QPushButton("Löschen", shortcut_row)
        self.clear_shortcut.setToolTip("Tastenkombination entfernen")
        self.clear_shortcut.clicked.connect(self.shortcut.clear)
        shortcut_layout.addWidget(self.clear_shortcut)
        form.addRow("Tastenkombination:", shortcut_row)
        shortcut_info = QLabel(
            "Tasten direkt drücken. Doppelte ShellDeck-Kürzel und bekannte systemweite "
            "Belegungen werden abgewiesen. Fremde Desktop-Kürzel lassen sich nicht "
            "auf jedem System vollständig ermitteln.", self)
        shortcut_info.setWordWrap(True)
        form.addRow(shortcut_info)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel, self
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def accept(self):
        sequence = self.shortcut.keySequence()
        if sequence.count() > 1:
            QMessageBox.warning(self, "Tastenkombination", "Bitte nur eine einzelne Tastenkombination eingeben.")
            self.shortcut.setFocus()
            return
        key = sequence.toString(QKeySequence.SequenceFormat.PortableText).strip()
        if key and self._shortcut_validator is not None:
            message = self._shortcut_validator(key)
            if message:
                QMessageBox.warning(self, "Tastenkombination nicht verfügbar", message)
                self.shortcut.setFocus()
                return
        self._accepted_shortcut = key
        super().accept()

    def result_command(self, original: dict) -> dict:
        item = dict(original)
        value = self.command.toPlainText().strip()
        item.update(name=self.name.text().strip(), confirm=self.confirm.isChecked(),
                    use_precommand=self.use_precommand.isChecked(),
                    new_tab=self.new_tab.isChecked(), shortcut=self._accepted_shortcut,
                    number_label=self.number_label.isChecked())
        if value != self._original_command:
            item["command"] = value
            item.pop("variants", None)
        return normalized_command(item)


class QuickCommandsDock(QDockWidget):
    """Schmale Kante im Auto-Hide-Modus; ein QDockWidget ändert nur das Layout.

    Weder QTextDocument noch TerminalGridView/PTY werden hier berührt. Qt darf
    die Terminalfläche verkleinern; deren bestehende Resize/Reflow-Pfade bleiben
    verantwortlich für den vollständigen Erhalt der Terminalausgabe.
    """
    changed = Signal()
    commandRequested = Signal(str)
    commandsReordered = Signal(list)

    def __init__(self, parent=None):
        super().__init__("Schnellbefehle", parent)
        self.setObjectName("ShellDeckQuickCommandsDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea | Qt.DockWidgetArea.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.NoDockWidgetFeatures)
        # Native Dock-Titel reservieren oft 150+ px Mindestbreite. Der eigene
        # Header sitzt im Panel, so kann die angedockte Auto-Hide-Kante schmal sein.
        self._empty_title_bar = QWidget(self)
        self._empty_title_bar.setFixedHeight(0)
        self.setTitleBarWidget(self._empty_title_bar)
        self._pinned = True
        self._compact = False
        self._expanded = True
        self._commands = []
        self._shell_type = "bash"
        self._ignore_reorder = False
        self._last_requested = ("", -1.0)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(450)
        self._hide_timer.timeout.connect(self.collapse_if_unfocused)

        self.container = QWidget(self)
        self.setWidget(self.container)
        self.outer = QHBoxLayout(self.container)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.outer.setSpacing(0)
        self.handle = QPushButton("❯", self.container)
        self.handle.setToolTip("Schnellbefehle öffnen (F8)")
        self.handle.setFixedWidth(27)
        self.handle.clicked.connect(self.expand)
        self.outer.addWidget(self.handle)

        self.panel = QWidget(self.container)
        self.panel_layout = QVBoxLayout(self.panel)
        self.panel_layout.setContentsMargins(3, 2, 3, 3)
        self.panel_layout.setSpacing(2)
        header = QHBoxLayout()
        self.title = QLabel("Schnellbefehle", self.panel)
        header.addWidget(self.title, 1)
        self.pin = QPushButton("📌", self.panel)
        self.pin.setFixedSize(27, 22)
        self.pin.setToolTip("Anheften / automatisch ausblenden")
        self.pin.clicked.connect(self.toggle_pin)
        header.addWidget(self.pin)
        self.panel_layout.addLayout(header)

        self.buttons = QListWidget(self.panel)
        self.buttons.setObjectName("QuickCommandsButtonList")
        self.buttons.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.buttons.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.buttons.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.buttons.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.buttons.setStyleSheet(
            "QListWidget::item { border: 1px solid palette(mid); border-radius: 3px; "
            "padding: 1px 3px; margin: 1px; }"
            "QListWidget::item:hover { background: palette(midlight); }"
            "QListWidget::item:selected { background: palette(highlight); "
            "color: palette(highlighted-text); }"
        )
        self.buttons.setSpacing(0)
        self.buttons.itemClicked.connect(self.request_selected)
        self.buttons.itemActivated.connect(self.request_selected)
        self.buttons.customContextMenuRequested.connect(self.context_menu)
        self.buttons.model().rowsMoved.connect(self.reordered)
        self.panel_layout.addWidget(self.buttons, 1)

        bottom = QHBoxLayout()
        self.add_button = QPushButton("+", self.panel)
        self.add_button.setToolTip("Neuen Schnellbefehl hinzufügen")
        self.add_button.clicked.connect(self.add_requested)
        self.add_button.setFixedHeight(23)
        bottom.addWidget(self.add_button)
        self.remove_button = QPushButton("−", self.panel)
        self.remove_button.setToolTip("Ausgewählten Schnellbefehl entfernen")
        self.remove_button.setFixedHeight(23)
        self.remove_button.clicked.connect(self.remove_requested)
        bottom.addWidget(self.remove_button)
        self.panel_layout.addLayout(bottom)
        self.outer.addWidget(self.panel)
        for part in (self, self.container, self.handle, self.panel, self.buttons):
            part.installEventFilter(self)
        QApplication.instance().focusChanged.connect(self._focus_changed)
        self.set_pinned(True, emit=False)

    def populate(self, commands: list[dict], shell_type: str):
        self._commands = list(commands)
        self._shell_type = str(shell_type or "bash")
        self._ignore_reorder = True
        selected = self.selected_id()
        self.buttons.clear()
        for n, item in enumerate(commands, 1):
            label = str(n) if item.get("number_label") else (item.get("name") or str(n))
            button = QListWidgetItem(label)
            button.setData(Qt.ItemDataRole.UserRole, item.get("id"))
            command = resolved_command(item, self._shell_type)
            button.setToolTip(command or "(Kein Befehl)")
            button.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            button.setSizeHint(QSize(42, 23 if self._compact else 25))
            self.buttons.addItem(button)
        for i in range(self.buttons.count()):
            if self.buttons.item(i).data(Qt.ItemDataRole.UserRole) == selected:
                self.buttons.setCurrentRow(i)
                break
        self._ignore_reorder = False

    def selected_id(self):
        item = self.buttons.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def request_selected(self, item):
        command_id = str(item.data(Qt.ItemDataRole.UserRole)) if item else ""
        if command_id:
            # Click + DoubleClick/Activated duerfen denselben Befehl nicht
            # unmittelbar zweimal ausfuehren (z.B. Backup-Erstellung).
            previous_id, previous_time = self._last_requested
            now = monotonic()
            if previous_id == command_id and now - previous_time < 0.4:
                return
            self._last_requested = (command_id, now)
            self.commandRequested.emit(command_id)
            # Nach dem Klick liegt der Fokus noch auf der Liste. Sonst wird
            # im Auto-Hide-Modus nie ein Fokusverlust erkannt.
            QTimer.singleShot(0, self.parent().focus_active_terminal)

    def reordered(self, *_):
        if not self._ignore_reorder:
            self.commandsReordered.emit([
                str(self.buttons.item(i).data(Qt.ItemDataRole.UserRole))
                for i in range(self.buttons.count())
            ])

    def context_menu(self, point):
        item = self.buttons.itemAt(point)
        if item is None:
            return
        self.buttons.setCurrentItem(item)
        menu = QMenu(self)
        run = menu.addAction("Ausführen")
        edit = menu.addAction("Bearbeiten…")
        duplicate = menu.addAction("Duplizieren")
        remove = menu.addAction("Entfernen…")
        self._hide_timer.stop()
        action = menu.exec(self.buttons.mapToGlobal(point))
        if action is run:
            self.request_selected(item)
        elif action is edit:
            self.parent().edit_quick_command(self.selected_id())
        elif action is duplicate:
            self.parent().duplicate_quick_command(self.selected_id())
        elif action is remove:
            self.remove_requested()
        self.schedule_collapse()

    def add_requested(self):
        self._hide_timer.stop()
        self.parent().add_quick_command()
        self.schedule_collapse()

    def remove_requested(self):
        self._hide_timer.stop()
        self.parent().remove_quick_command(self.selected_id())
        self.schedule_collapse()

    def toggle_pin(self):
        self.set_pinned(not self._pinned)
        if not self._pinned:
            # Ein QPushButton behaelt nach dem Klick den Tastaturfokus.
            # Ohne diese Rueckgabe ans Terminal klappt die Leiste beim
            # anschliessenden Mausverlassen niemals automatisch ein.
            QTimer.singleShot(0, self.parent().focus_active_terminal)

    def set_pinned(self, pinned: bool, *, emit=True):
        self._pinned = bool(pinned)
        self.pin.setText("📌" if self._pinned else "○")
        self.pin.setToolTip("Automatisches Ausblenden aktivieren" if self._pinned
                            else "Leiste dauerhaft anheften")
        if self._pinned:
            self.expand()
        else:
            self.schedule_collapse()
        if emit:
            self.changed.emit()

    def set_compact(self, compact: bool):
        self._compact = bool(compact)
        self._apply_width()
        # Eine Dichteänderung muss auch bestehende Einträge aktualisieren.
        for index in range(self.buttons.count()):
            self.buttons.item(index).setSizeHint(QSize(42, 23 if self._compact else 25))

    def _apply_width(self):
        width = (94 if self._compact else 150) if self._expanded else 27
        self.panel.setVisible(self._expanded)
        self.handle.setVisible(not self._expanded)
        self.title.setVisible(not self._compact)
        self.setFixedWidth(width)
        self.setMinimumHeight(24)

    def expand(self):
        self._hide_timer.stop()
        if not self.isVisible():
            self.show()
        self._expanded = True
        self._apply_width()
        self.changed.emit()

    def collapse(self):
        if self._pinned:
            return
        self._expanded = False
        self._apply_width()
        self.changed.emit()

    def collapse_if_unfocused(self):
        if self._pinned or not self._expanded or not self.isVisible():
            return
        at_mouse = QApplication.widgetAt(QCursor.pos())
        in_dock = at_mouse is not None and (at_mouse is self or self.isAncestorOf(at_mouse))
        active_focus = QApplication.focusWidget()
        in_focus = active_focus is not None and (active_focus is self or self.isAncestorOf(active_focus))
        if not in_dock and not in_focus and QApplication.activeModalWidget() is None and QApplication.activePopupWidget() is None:
            self.collapse()

    def schedule_collapse(self):
        if not self._pinned and self._expanded:
            self._hide_timer.start()

    def _focus_changed(self, *_):
        self.schedule_collapse()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Enter, QEvent.Type.HoverEnter):
            self._hide_timer.stop()
            if watched is self.handle and not self._expanded:
                self.expand()
        elif event.type() in (QEvent.Type.Leave, QEvent.Type.HoverLeave):
            self.schedule_collapse()
        return super().eventFilter(watched, event)
