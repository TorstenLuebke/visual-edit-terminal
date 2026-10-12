"""Durchsuchbarer Hilfedialog fuer ein bereits sicher erkanntes PTY-Programm.

Keine Prozessaktionen, keine Ausfuehrung von Dokumentation. Der Hilfetext wird
vor HTML-Darstellung escaped; Benutzer-Guides bleiben rein deklarativ.
"""

from html import escape

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from shelldeck_program_help import filter_help_sections, help_sections_for


class ProgramHelpDialog(QDialog):
    """Lesende Programmhilfe mit Kategorien und Volltextsuche.

    Die Anzeige erhaelt eine Momentaufnahme des beim Klick erkannten Guides;
    Wechsel in andere Tabs veraendern weder den Dialog noch den PTY-Prozess.
    """

    def __init__(self, guide, parent=None):
        super().__init__(parent)
        self._sections = help_sections_for(guide)
        self._filtered = self._sections
        self.setWindowTitle(f"{guide.label} – Programmhilfe")
        self.resize(940, 620)
        self.setMinimumSize(620, 420)

        layout = QVBoxLayout(self)
        heading = QLabel(f"<h2>{escape(guide.label)} – Programmhilfe</h2>")
        heading.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(heading)
        subtitle = QLabel(
            "Standardbelegung: Funktionen koennen je nach installierter Version, "
            "Konfiguration und Betriebssystem abweichen. "
            "Die Hilfe sendet keine Eingaben an das laufende Programm."
        )
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("Themen, Funktionen oder Tastenkombinationen suchen …")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName("Programmhilfe durchsuchen")
        layout.addWidget(self.search_edit)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.topic_list = QListWidget()
        splitter.addWidget(self.topic_list)
        self.topic_list.setAccessibleName("Hilfethemen")
        self.topic_list.setMinimumWidth(190)
        self.details = QTextBrowser()
        splitter.addWidget(self.details)
        self.details.setOpenExternalLinks(False)
        self.details.setOpenLinks(False)
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Hilfeinhalt")
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([230, 680])
        layout.addWidget(splitter, 1)

        self.counter = QLabel("")
        layout.addWidget(self.counter)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.search_edit.textChanged.connect(self._apply_search)
        self.topic_list.currentRowChanged.connect(self._show_topic)
        self._apply_search("")

    def _apply_search(self, query):
        """Liste + Trefferanzeige aktualisieren, ohne Quellkatalog zu veraendern."""
        selected = self.topic_list.currentItem()
        previous_title = selected.text() if selected else ""
        self._filtered = filter_help_sections(self._sections, query)
        self.topic_list.blockSignals(True)
        self.topic_list.clear()
        self.topic_list.addItems([section.title for section in self._filtered])
        self.topic_list.blockSignals(False)
        total = sum(len(section.entries) for section in self._filtered)
        self.counter.setText(f"{len(self._filtered)} Themen · {total} Einträge")
        if not self._filtered:
            self.details.setHtml("<p>Keine Treffer. Bitte einen anderen Suchbegriff versuchen.</p>")
            return
        titles = [section.title for section in self._filtered]
        index = titles.index(previous_title) if previous_title in titles else 0
        self.topic_list.setCurrentRow(index)
        self._show_topic(index)

    def _show_topic(self, index):
        if not 0 <= index < len(self._filtered):
            return
        section = self._filtered[index]
        parts = [f"<h3>{escape(section.title)}</h3>"]
        for entry in section.entries:
            shortcut = escape(entry.keys)
            body = escape(entry.description)
            if shortcut:
                parts.append(f"<p><b>{shortcut}</b><br/>{body}")
            else:
                parts.append(f"<p>{body}")
            if entry.detail:
                parts.append(f"<br/><small>{escape(entry.detail)}</small>")
            parts.append("</p>")
        self.details.setHtml("".join(parts))
        self.details.moveCursor(QTextCursor.MoveOperation.Start)
