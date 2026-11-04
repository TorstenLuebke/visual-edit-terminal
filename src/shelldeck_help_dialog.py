"""Offline-Dokumentationsbrowser fuer das ShellDeck-F1-Handbuch.

Verwendet ausschliesslich QtWidgets und lokales HTML. Keine QtWebEngine-,
Java-, Netzwerk- oder JavaScript-Abhaengigkeit; niemals Shell-Operationen.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton,
    QSplitter, QTextBrowser, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from shelldeck_help_center import (
    category_order, home_html, results_html, search_topics,
    topic_html, topics_from_plain_help,
)


class ShellDeckHelpDialog(QDialog):
    """Nicht-modales Handbuch als eigenes Fenster, ohne Shell-Eingriffe."""

    def __init__(self, plain_help: str, parent=None):
        super().__init__(parent)
        self._source = str(plain_help or "")
        self._topics = topics_from_plain_help(self._source)
        self._by_key = {topic.key: topic for topic in self._topics}
        self._history = ["home"]
        self._history_position = 0
        self._syncing_index = False
        self._items = {}

        self.setWindowTitle("ShellDeck – Hilfe und Handbuch")
        # Qt.Window bewirkt ein eigenständiges Fenster statt eines modalen Dialogs.
        # Es bleibt im Besitz des Hauptfensters und wird beim Schließen nur verborgen.
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setModal(False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)
        self.resize(1050, 720)
        self.setMinimumSize(650, 420)

        layout = QVBoxLayout(self)
        toolbar = QHBoxLayout()
        self.back_button = QPushButton("← Zurück")
        self.next_button = QPushButton("Vorwärts →")
        self.home_button = QPushButton("⌂ Übersicht")
        self.arrange_button = QPushButton("▥ Nebeneinander")
        self.arrange_button.setToolTip(
            "Terminal und Hilfe auf dem Bildschirm nebeneinander anordnen. "
            "Die Fenstergrößen werden dabei verändert."
        )
        self.arrange_button.setEnabled(parent is not None)
        self.back_button.setToolTip("Zur vorherigen Hilfeseite")
        self.next_button.setToolTip("Zur nächsten Hilfeseite")
        self.home_button.setToolTip("Zur Themenübersicht")
        for button in (self.back_button, self.next_button, self.home_button, self.arrange_button):
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText("In der gesamten Hilfe suchen …")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setAccessibleName("Hilfethemen durchsuchen")
        toolbar.addWidget(self.search_edit, 2)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.index = QTreeWidget(splitter)
        self.index.setHeaderHidden(True)
        self.index.setMinimumWidth(180)
        self.index.setAccessibleName("Inhaltsverzeichnis der Hilfe")
        self.page = QTextBrowser(splitter)
        self.page.setOpenExternalLinks(False)
        self.page.setOpenLinks(False)
        self.page.setReadOnly(True)
        self.page.setAccessibleName("Hilfeseite")
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([270, 780])
        layout.addWidget(splitter, 1)

        self.status = QLabel(self)
        layout.addWidget(self.status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

        self.back_button.clicked.connect(self.go_back)
        self.next_button.clicked.connect(self.go_forward)
        self.home_button.clicked.connect(lambda: self.navigate("home"))
        self.arrange_button.clicked.connect(self.arrange_next_to_terminal)
        self.search_edit.textChanged.connect(self._filter_index)
        self.index.itemActivated.connect(self._index_activated)
        self.index.itemClicked.connect(self._index_activated)
        self.page.anchorClicked.connect(self._link_clicked)

        self._build_index()
        self._render()

    def arrange_next_to_terminal(self) -> bool:
        """Ordnet beide Fenster auf ausdrücklichen Wunsch nebeneinander an.

        Die Shell- und VT-Scrollback-Daten werden nicht verändert. Nur das
        normale Qt-Fensterlayout passt die Terminalbreite an.
        """
        terminal = self.parentWidget()
        if terminal is None or not terminal.isWindow():
            return False
        screen = terminal.screen() or QApplication.primaryScreen()
        if screen is None:
            return False
        area = screen.availableGeometry()
        gap = 8
        min_terminal = max(600, terminal.minimumWidth())
        min_help = max(650, self.minimumWidth())
        if area.width() < min_terminal + min_help + gap:
            QMessageBox.information(
                self, "Fenster nebeneinander",
                "Für zwei Fenster nebeneinander ist dieser Bildschirm zu schmal. "
                "Bitte verschiebe die Hilfe manuell oder nutze einen zweiten Monitor."
            )
            return False

        terminal_width = max(min_terminal, int((area.width() - gap) * 0.55))
        help_width = area.width() - gap - terminal_width
        if help_width < min_help:
            help_width = min_help
            terminal_width = area.width() - gap - help_width

        # showNormal() ist für ein maximiertes Hauptfenster nötig. Wir tun das
        # nur nach Klick auf Nebeneinander, nicht bei jedem F1-Aufruf.
        terminal.showNormal()
        self.showNormal()
        terminal.setGeometry(area.x(), area.y(), terminal_width, area.height())
        self.setGeometry(area.x() + terminal_width + gap, area.y(),
                         help_width, area.height())
        self.raise_()
        return True

    def _build_index(self) -> None:
        self.index.clear()
        self._items.clear()
        start = QTreeWidgetItem(self.index, ["⌂ Startseite"])
        start.setData(0, Qt.ItemDataRole.UserRole, "home")
        self._items["home"] = start
        for category in category_order(self._topics):
            parent = QTreeWidgetItem(self.index, [category])
            parent.setExpanded(True)
            for topic in self._topics:
                if topic.category == category:
                    child = QTreeWidgetItem(parent, [topic.title])
                    child.setData(0, Qt.ItemDataRole.UserRole, topic.key)
                    child.setToolTip(0, topic.title)
                    self._items[topic.key] = child

    def _index_activated(self, item: QTreeWidgetItem, column: int = 0) -> None:
        if self._syncing_index:
            return
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key:
            self.navigate(key)

    def _link_clicked(self, url) -> None:
        # Keine externen Links: nur interne help://topic/<id> oder help://home.
        if url.scheme() != "help":
            return
        if url.host() == "home" and url.path() in ("", "/"):
            self.navigate("home")
        elif url.host() == "topic":
            key = url.path().lstrip("/")
            if key in self._by_key:
                self.navigate(key)

    def navigate(self, key: str) -> None:
        if key != "home" and key not in self._by_key:
            return
        if self._history[self._history_position] == key:
            self._render()
            return
        del self._history[self._history_position + 1:]
        self._history.append(key)
        self._history_position += 1
        self._render()

    def go_back(self) -> None:
        if self._history_position > 0:
            self._history_position -= 1
            self._render()

    def go_forward(self) -> None:
        if self._history_position + 1 < len(self._history):
            self._history_position += 1
            self._render()

    def _filter_index(self, query: str) -> None:
        matches = search_topics(self._topics, query)
        keys = {topic.key for topic in matches}
        for key, item in self._items.items():
            if key != "home":
                item.setHidden(bool(query.strip()) and key not in keys)
        root = self.index.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item is not self._items["home"]:
                item.setHidden(all(item.child(j).isHidden() for j in range(item.childCount())))
        if query.strip():
            self.page.setHtml(results_html(self._topics, query))
            self.status.setText(f"{len(matches)} von {len(self._topics)} Themen gefunden")
        else:
            self._render()

    def _render(self) -> None:
        key = self._history[self._history_position]
        if key == "home":
            title = self._source.splitlines()[0].strip() if self._source else "ShellDeck"
            html = home_html(self._topics, title)
        else:
            html = topic_html(self._by_key[key], self._topics)
        self.page.setHtml(html)
        self.page.verticalScrollBar().setValue(0)
        self.back_button.setEnabled(self._history_position > 0)
        self.next_button.setEnabled(self._history_position + 1 < len(self._history))
        if not self.search_edit.text().strip():
            self.status.setText(f"{len(self._topics)} Hilfethemen · vollständig offline")
        self._syncing_index = True
        try:
            item = self._items.get(key)
            if item is not None and not item.isHidden():
                self.index.setCurrentItem(item)
        finally:
            self._syncing_index = False
