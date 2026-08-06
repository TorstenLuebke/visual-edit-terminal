import csv
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QAbstractTableModel, QDate, QSortFilterProxyModel, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDateEdit, QDialog, QFileDialog, QHBoxLayout,
    QLabel, QLineEdit, QMenu, QPushButton, QTableView, QVBoxLayout,
)


COLUMNS = ("Datum", "Zeit", "Status", "Shell", "Befehl", "Ordner", "Dauer", "Exit-Code")


def command_text(entry):
    return str(entry.get("command") or entry.get("original_command") or entry.get("sent_command") or "").strip()


def entry_timestamp(entry):
    value = entry.get("started_at")
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(str(value or "")).timestamp()
    except (TypeError, ValueError):
        return 0.0


class CommandHistoryModel(QAbstractTableModel):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.entries = []

    def set_entries(self, entries):
        self.beginResetModel()
        self.entries = list(entries or [])
        self.endResetModel()

    def rowCount(self, parent=None):
        return len(self.entries)

    def columnCount(self, parent=None):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self.entries)):
            return None
        entry = self.entries[index.row()]
        timestamp = entry_timestamp(entry)
        dt = datetime.fromtimestamp(timestamp) if timestamp else None
        duration_ms = int(entry.get("duration_ms") or round(float(entry.get("duration") or 0) * 1000))
        exit_code = entry.get("exit_code")
        values = (
            dt.strftime("%d.%m.%Y") if dt else "",
            dt.strftime("%H:%M:%S") if dt else "",
            str(entry.get("status") or ""),
            str(entry.get("shell_type") or ""),
            command_text(entry),
            str(entry.get("working_directory") or ""),
            f"{duration_ms / 1000:.2f} s",
            "" if exit_code is None else str(exit_code),
        )
        if role == Qt.ItemDataRole.DisplayRole:
            return values[index.column()]
        if role == Qt.ItemDataRole.UserRole:
            if index.column() in (0, 1):
                return timestamp
            if index.column() == 6:
                return duration_ms
            if index.column() == 7:
                return -1 if exit_code is None else int(exit_code)
            return values[index.column()].casefold()
        return None


class CommandHistoryProxy(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.search_text = ""
        self.status_text = "alle"
        self.shell_text = "alle"
        self.date_from = QDate.currentDate().addDays(-30)
        self.date_to = QDate.currentDate()
        self.setSortRole(Qt.ItemDataRole.UserRole)

    def filterAcceptsRow(self, source_row, source_parent):
        model = self.sourceModel()
        entry = model.entries[source_row]
        search_space = f"{command_text(entry)} {entry.get('working_directory', '')}".casefold()
        if self.search_text and self.search_text not in search_space:
            return False
        status = str(entry.get("status") or "").casefold()
        if self.status_text != "alle" and status != self.status_text:
            return False
        shell = str(entry.get("shell_type") or "").casefold()
        if self.shell_text != "alle" and shell != self.shell_text:
            return False
        timestamp = entry_timestamp(entry)
        if timestamp:
            day = QDateTime_from_timestamp(timestamp)
            if day < self.date_from or day > self.date_to:
                return False
        return True


def QDateTime_from_timestamp(timestamp):
    dt = datetime.fromtimestamp(timestamp)
    return QDate(dt.year, dt.month, dt.day)


class CommandHistoryDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self.setWindowTitle("Befehlsverlauf durchsuchen")
        self.resize(1100, 650)
        self.setModal(False)

        layout = QVBoxLayout(self)
        filters = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("Befehl oder Ordner durchsuchen")
        self.status = QComboBox(self)
        self.status.addItems(["alle", "erfolgreich", "Fehler", "abgebrochen"])
        self.shell = QComboBox(self)
        self.from_date = QDateEdit(QDate.currentDate().addDays(-30), self)
        self.to_date = QDateEdit(QDate.currentDate(), self)
        for edit in (self.from_date, self.to_date):
            edit.setCalendarPopup(True)
        filters.addWidget(self.search, 1)
        filters.addWidget(QLabel("Status:"))
        filters.addWidget(self.status)
        filters.addWidget(QLabel("Shell:"))
        filters.addWidget(self.shell)
        filters.addWidget(QLabel("Von:"))
        filters.addWidget(self.from_date)
        filters.addWidget(QLabel("Bis:"))
        filters.addWidget(self.to_date)
        layout.addLayout(filters)

        self.model = CommandHistoryModel(self)
        self.proxy = CommandHistoryProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView(self)
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.setSelectionBehavior(QTableView.SelectionBehavior.SelectRows)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        self.table.doubleClicked.connect(self.load_selected)
        layout.addWidget(self.table, 1)

        footer = QHBoxLayout()
        self.count_label = QLabel(self)
        footer.addWidget(self.count_label)
        footer.addStretch(1)
        export_button = QPushButton("Als CSV exportieren", self)
        export_button.clicked.connect(self.export_csv)
        footer.addWidget(export_button)
        layout.addLayout(footer)

        self.search.textChanged.connect(self.update_filter)
        self.status.currentTextChanged.connect(self.update_filter)
        self.shell.currentTextChanged.connect(self.update_filter)
        self.from_date.dateChanged.connect(self.update_filter)
        self.to_date.dateChanged.connect(self.update_filter)
        self.refresh()

    def refresh(self):
        entries = list(getattr(self.owner, "command_history_entries", []))
        self.model.set_entries(entries)
        shells = sorted({str(item.get("shell_type") or "").strip() for item in entries if str(item.get("shell_type") or "").strip()})
        current = self.shell.currentText() or "alle"
        self.shell.blockSignals(True)
        self.shell.clear()
        self.shell.addItem("alle")
        self.shell.addItems(shells)
        self.shell.setCurrentText(current if current in ["alle", *shells] else "alle")
        self.shell.blockSignals(False)
        self.update_filter()

    def update_filter(self):
        self.proxy.search_text = self.search.text().strip().casefold()
        self.proxy.status_text = self.status.currentText().casefold()
        self.proxy.shell_text = self.shell.currentText().casefold()
        self.proxy.date_from = self.from_date.date()
        self.proxy.date_to = self.to_date.date()
        self.proxy.invalidateFilter()
        self.count_label.setText(f"{self.proxy.rowCount()} Einträge")

    def selected_entry(self):
        index = self.table.currentIndex()
        if not index.isValid():
            return None
        source = self.proxy.mapToSource(index)
        return self.model.entries[source.row()]

    def load_selected(self, index=None):
        entry = self.selected_entry()
        tab = self.owner.current_terminal()
        if entry and tab is not None:
            tab.input_line.setPlainText(command_text(entry))
            tab.input_line.setFocus()

    def show_context_menu(self, pos):
        entry = self.selected_entry()
        menu = QMenu(self)
        load_action = QAction("In Eingabe übernehmen", self)
        copy_action = QAction("In Zwischenablage kopieren", self)
        delete_action = QAction("Eintrag löschen", self)
        delete_filtered_action = QAction("Alle gefilterten löschen", self)
        load_action.setEnabled(entry is not None)
        copy_action.setEnabled(entry is not None)
        delete_action.setEnabled(entry is not None)
        load_action.triggered.connect(self.load_selected)
        copy_action.triggered.connect(lambda: QApplication.clipboard().setText(command_text(entry)) if entry else None)
        delete_action.triggered.connect(lambda: self.delete_entries([entry]) if entry else None)
        delete_filtered_action.triggered.connect(self.delete_filtered)
        for action in (load_action, copy_action, delete_action, delete_filtered_action):
            menu.addAction(action)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def delete_entries(self, entries):
        identities = {id(item) for item in entries}
        self.owner.command_history_entries = [item for item in self.owner.command_history_entries if id(item) not in identities]
        self.owner.save_command_history()
        self.owner.refresh_command_history_views()
        self.refresh()

    def delete_filtered(self):
        entries = []
        for row in range(self.proxy.rowCount()):
            source = self.proxy.mapToSource(self.proxy.index(row, 0))
            entries.append(self.model.entries[source.row()])
        self.delete_entries(entries)

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Befehlsverlauf exportieren", "befehlsverlauf.csv", "CSV-Dateien (*.csv)")
        if not path:
            return
        try:
            with Path(path).open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle, delimiter=";")
                writer.writerow(COLUMNS)
                for row in range(self.proxy.rowCount()):
                    source = self.proxy.mapToSource(self.proxy.index(row, 0))
                    entry = self.model.entries[source.row()]
                    writer.writerow([self.model.data(self.model.index(source.row(), column)) for column in range(len(COLUMNS))])
        except OSError as exc:
            self.owner.show_status(f"Befehlsverlauf konnte nicht exportiert werden: {exc}")
