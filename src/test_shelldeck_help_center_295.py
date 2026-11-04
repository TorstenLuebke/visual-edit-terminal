"""Offline-Tests fuer Inhaltsverzeichnis, Suche, HTML-Sicherheit und PTY-Texte."""
from __future__ import annotations

import ast
from pathlib import Path
from html import escape

from shelldeck_help_center import (
    home_html, results_html, search_topics, topic_html, topics_from_plain_help,
)
from shelldeck_vt_diagnostics_help_283 import vt_diagnostics_help_section

MAIN = Path(__file__).with_name("main.py")


def _help_text():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "TerminalWindow")
    node = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == "help_text")
    ns = {"APP_NAME": "ShellDeck Terminal", "APP_VERSION": "2.16.10",
          "vt_diagnostics_help_section": vt_diagnostics_help_section}
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
                 str(MAIN), "exec"), ns)
    return ns["help_text"](None)


def test_all_existing_help_subjects_are_navigable_and_searchable():
    text = _help_text()
    topics = topics_from_plain_help(text)
    assert len(topics) >= 24
    assert len({t.key for t in topics}) == len(topics)
    for term in ("Schnellbefehle", "Vorbefehl", "Terminaldiagnose", "Tastenkürzel",
                 "Kommandozeile", "Workspaces", "Ollama", "Echtes Terminal"):
        assert any(term.casefold() in t.title.casefold() for t in topics), term
        assert search_topics(topics, term), term
    # Der Diagnoseabschnitt stammt unveraendert aus seiner bestehenden Quelle.
    diagnostics = next(t for t in topics if t.title.startswith("Terminaldiagnose"))
    assert "4 MiB" in diagnostics.body
    assert "● REC" in diagnostics.body
    assert "■ Stopp" in diagnostics.body


def test_correct_engine_recommendation_without_obsolete_blanket_warning():
    text = _help_text()
    assert "Automatisch – empfohlen:" in text
    assert "PTY/ConPTY – interaktiv:" in text
    assert "QProcess – kompatibel:" in text
    assert "PTY/ConPTY experimentell ist zum Testen" not in text
    assert "sollte erst nach einem gesicherten Git-Stand" not in text
    assert "Vollbild-Terminalprogramme sind hier eingeschraenkt" in text
    assert "pywinpty" in text


def test_documented_content_is_not_lost_when_rendered_to_html():
    text = _help_text()
    topics = topics_from_plain_help(text)
    joined = "\n".join(topic.body for topic in topics)
    for line in text.splitlines()[2:]:
        if line.startswith("- "):
            assert line in joined, line
    home = home_html(topics, "ShellDeck Terminal <2.16.10>")
    assert "&lt;2.16.10&gt;" in home
    for topic in topics:
        assert f"help://topic/{topic.key}" in home
        article = topic_html(topic, topics)
        assert "help://home" in article
        assert escape(topic.title) in article


def test_html_escaping_and_search_links_are_safe():
    text = "ShellDeck 1\n\nUebersicht\n- <script>alert('bad')</script>"
    topics = topics_from_plain_help(text)
    assert "<script>" not in topic_html(topics[0], topics)
    assert "&lt;script&gt;" in topic_html(topics[0], topics)
    matches = results_html(topics, "<script>")
    assert "<script>" not in matches
    assert "&lt;script&gt;" in matches
    assert "1 Themen" in matches
    assert len(search_topics(topics, "ueber falsch")) == 0  # alle Suchworte muessen passen


def test_new_f1_dialog_is_read_only_and_diagnostic_help_remains_separate():
    text = MAIN.read_text(encoding="utf-8")
    assert "from shelldeck_help_dialog import ShellDeckHelpDialog" in text
    assert "self._help_window = ShellDeckHelpDialog(self.help_text(), self)" in text
    assert "vt_diagnostics_help_section()" in text
    gui = Path(__file__).with_name("shelldeck_help_dialog.py").read_text(encoding="utf-8")
    assert "QTextBrowser" in gui and "QTreeWidget" in gui and "QLineEdit" in gui
    assert "setOpenExternalLinks(False)" in gui
    assert "setReadOnly(True)" in gui
    assert "anchorClicked.connect" in gui
    assert "go_back" in gui and "go_forward" in gui
    assert "subprocess" not in gui


def test_graphical_dialog_controls_if_pyside_available(monkeypatch):
    import pytest
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    from shelldeck_help_dialog import ShellDeckHelpDialog
    app = QApplication.instance() or QApplication([])
    dialog = ShellDeckHelpDialog(_help_text())
    assert dialog.index.topLevelItemCount() >= 5
    assert dialog._history == ["home"]
    topic = next(t for t in dialog._topics if "Schnellbefehle" in t.title)
    dialog.navigate(topic.key)
    assert dialog.back_button.isEnabled()
    dialog.go_back()
    assert dialog._history[dialog._history_position] == "home"
    dialog.go_forward()
    assert dialog._history[dialog._history_position] == topic.key
    dialog.search_edit.setText("readline")
    assert dialog.page.toPlainText().find("Suchergebnisse") >= 0
    dialog.search_edit.clear()
    assert topic.title in dialog.page.toPlainText()
    dialog.close()


def test_practical_ollama_and_client_guides_are_indexed_and_show_steps():
    topics = topics_from_plain_help(_help_text())
    expected = {
        "Ollama – erster Chat (Schritt für Schritt)",
        "Ollama – Modelle, Kontext und Systemprompt",
        "Ollama – Dateien und Code im Chat",
        "Ollama – häufige Fehler und Lösungen",
        "Clients – Python, Node.js und Datenbanken",
        "Clients – typische Stolperfallen",
    }
    assert expected <= {t.title for t in topics}
    assert all(t.category == "KI und Clients" for t in topics if t.title in expected)
    howto = next(t for t in topics if t.title.startswith("Ollama – erster Chat"))
    html = topic_html(howto, topics)
    assert "<ol>" in html and "<h2>Vorbereitung</h2>" in html
    assert "<code>ollama list</code>" in html
    assert "<code>ollama pull gemma3:1b</code>" in html
    assert "KI → Neuer Ollama-Chat" in html
    assert len(search_topics(topics, "API 11434")) >= 1
    assert len(search_topics(topics, "Client sqlite3")) >= 1
    assert len(search_topics(topics, "Kontext Systemprompt")) >= 1


def test_ollama_chat_keeps_visible_classic_input_even_with_global_vt_default():
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == "TerminalWindow")
    def method(name):
        return next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == name)
    chat_text = ast.unparse(method("new_ollama_chat_tab"))
    profile_text = ast.unparse(method("open_profile_in_new_tab"))
    assert "terminal_engine=" in chat_text and "qprocess" in chat_text
    assert "qprocess" in profile_text and "ollama_model and self.ai_features_enabled" in profile_text


def test_html_help_renders_inline_code_without_injecting_markup():
    topics = topics_from_plain_help(
        "ShellDeck 1\n\nOllama\n## Schritte\n1. Gib `ollama list` ein.\n"
        "2. Gib `<script>alert(1)</script>` nicht ungeprüft ein.\n"
        "- <b>Passwort</b> nicht anhängen."
    )
    html = topic_html(topics[0], topics)
    assert "<h2>Schritte</h2>" in html
    assert "<ol>" in html and "</ol>" in html
    assert "<code>ollama list</code>" in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<b>Passwort</b>" not in html
