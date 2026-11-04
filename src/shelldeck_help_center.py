"""Offline-Handbuch fuer ShellDeck: sichere Aufbereitung der bestehenden Hilfe.

Qt-frei und damit auch ohne GUI testbar. Der Parser verwendet den F1-Hilfetext
als einzige Inhaltsquelle, um die Dokumentation nicht doppelt pflegen zu muessen.
"""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re
import unicodedata


@dataclass(frozen=True)
class HelpTopic:
    key: str
    title: str
    body: str
    category: str


_CATEGORIES = (
    "Erste Schritte",
    "Terminal und Befehle",
    "Tabs, Projekte und Workspaces",
    "Oberfläche und Einstellungen",
    "KI und Clients",
    "Diagnose und Sicherheit",
    "Referenz",
)


def _category(title: str) -> str:
    name = title.casefold()
    if name.startswith(("übersicht", "grundbedienung")):
        return "Erste Schritte"
    if name.startswith(("schnellbefehle", "vorbefehl", "backends", "echtes terminal", "virtuelle umgebungen")):
        return "Terminal und Befehle"
    if name.startswith(("datei-menü", "pfade-menü", "profile-menü", "workspaces-menü", "gespeicherte daten")):
        return "Tabs, Projekte und Workspaces"
    if name.startswith(("ansicht-menü", "einstellungen-menü", "kontextmenüs", "ausgabe, suche", "befehlspalette")):
        return "Oberfläche und Einstellungen"
    if name.startswith(("ki-menü", "interaktiver client", "ollama", "clients")):
        return "KI und Clients"
    if name.startswith(("terminaldiagnose", "hinweise")):
        return "Diagnose und Sicherheit"
    return "Referenz"


def _slug(title: str) -> str:
    folded = unicodedata.normalize("NFKD", title).casefold()
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")[:64] or "thema"


def topics_from_plain_help(source: str) -> tuple[HelpTopic, ...]:
    """Absatzkapitel der alten Hilfe ohne Informationsverlust gruppieren.

    Der erste alleinstehende Titel (Programmname + Version) ist kein Kapitel.
    Alle eigentlichen Kapitel beginnen auf einer neuen Absatzgruppe.
    """
    blocks = re.split(r"\n\s*\n", str(source or "").strip())
    result: list[HelpTopic] = []
    used: set[str] = set()
    for position, block in enumerate(blocks):
        lines = block.strip().splitlines()
        if not lines:
            continue
        if position == 0 and len(lines) == 1:
            continue  # Titelzeile mit Versionsnummer
        if lines[0].startswith("- ") and result:
            # Ein spaeterer Absatz mit Aufzaehlung gehoert zum letzten Kapitel.
            prev = result[-1]
            result[-1] = HelpTopic(prev.key, prev.title,
                                   prev.body + "\n\n" + block, prev.category)
            continue
        title = lines[0].strip()
        key = _slug(title)
        base = key
        n = 2
        while key in used:
            key = f"{base}-{n}"
            n += 1
        used.add(key)
        result.append(HelpTopic(key, title, "\n".join(lines[1:]).strip(), _category(title)))
    return tuple(result)


def category_order(topics: tuple[HelpTopic, ...]) -> tuple[str, ...]:
    present = {topic.category for topic in topics}
    return tuple(name for name in _CATEGORIES if name in present)


def search_topics(topics: tuple[HelpTopic, ...], query: str) -> tuple[HelpTopic, ...]:
    words = str(query or "").casefold().split()
    if not words:
        return topics
    return tuple(t for t in topics
                 if all(word in f"{t.title} {t.body} {t.category}".casefold()
                        for word in words))


def _shell(body: str, title: str) -> str:
    """Gemeinsames HTML-Grundgeruest (nur QTextBrowser, kein Web/JS)."""
    css = """body {font-family: sans-serif; font-size: 11pt; margin: 18px;}
    h1 {font-size: 21pt; margin-bottom: 6px;} h2 {font-size: 15pt; margin-top: 20px;}
    p {line-height: 1.35;} li {margin-bottom: 8px;} a {color: #218cdc; text-decoration: none;}
    .quiet {color: #8996a0;} .card {margin: 12px 0;} .meta {font-size: 9pt;}
    """
    return (f"<!DOCTYPE html><html><head><meta charset='utf-8'/>"
            f"<title>{escape(title)}</title><style>{css}</style></head>"
            f"<body>{body}</body></html>")


def _inline_html(value: str) -> str:
    """Einfache Inline-Codeformatierung mit konsequenter HTML-Maskierung."""
    fragments = re.split(r"(`[^`]+`)", str(value))
    return "".join(
        "<code>" + escape(part[1:-1]) + "</code>"
        if part.startswith("`") and part.endswith("`") and len(part) >= 3
        else escape(part)
        for part in fragments
    )


def _body_html(body: str) -> str:
    """Abschnitte, nummerierte Anleitungen und Listen lesbar aufbereiten."""
    parts: list[str] = []
    listing: list[str] = []
    kind: str | None = None

    def flush_list() -> None:
        nonlocal kind
        if listing:
            tag = kind or "ul"
            parts.append(f"<{tag}>" + "".join(listing) + f"</{tag}>")
            listing.clear()
        kind = None

    for line in body.splitlines():
        value = line.strip()
        if not value:
            flush_list()
            continue
        if value.startswith("## "):
            flush_list()
            parts.append(f"<h2>{_inline_html(value[3:])}</h2>")
        elif value.startswith("- "):
            if kind not in (None, "ul"):
                flush_list()
            kind = "ul"
            listing.append(f"<li>{_inline_html(value[2:])}</li>")
        elif re.match(r"^\d+\.\s", value):
            if kind not in (None, "ol"):
                flush_list()
            kind = "ol"
            # HTML list numbering stays consistent within a contiguous block.
            listing.append(f"<li>{_inline_html(re.sub(r'^\d+\.\s+', '', value))}</li>")
        else:
            flush_list()
            parts.append(f"<p>{_inline_html(value)}</p>")
    flush_list()
    return "\n".join(parts)


def home_html(topics: tuple[HelpTopic, ...], version_title: str = "ShellDeck") -> str:
    contents = [f"<h1>{escape(version_title)}</h1>",
                "<p>Willkommen in der ShellDeck-Hilfe. Wähle links ein Thema oder "
                "verwende die Suche. Alle Seiten sind offline verfügbar.</p>"]
    for category in category_order(topics):
        contents.append(f"<h2>{escape(category)}</h2><ul>")
        for topic in topics:
            if topic.category == category:
                contents.append(
                    f'<li><a href="help://topic/{escape(topic.key, quote=True)}">'
                    f'{escape(topic.title)}</a></li>'
                )
        contents.append("</ul>")
    return _shell("\n".join(contents), "ShellDeck – Hilfe")


def topic_html(topic: HelpTopic, topics: tuple[HelpTopic, ...]) -> str:
    index = topics.index(topic)
    blocks = ["<p><a href='help://home'>&larr; Zur Themenübersicht</a></p>",
              f"<p class='quiet'>{escape(topic.category)}</p>",
              f"<h1>{escape(topic.title)}</h1>", _body_html(topic.body),
              "<hr/>", "<p class='meta'>"]
    if index:
        previous = topics[index - 1]
        blocks.append(f'<a href="help://topic/{escape(previous.key)}">&larr; Vorheriges Thema</a>')
    if index + 1 < len(topics):
        following = topics[index + 1]
        blocks.append(f' &nbsp; <a href="help://topic/{escape(following.key)}">Nächstes Thema &rarr;</a>')
    blocks.append("</p>")
    return _shell("\n".join(blocks), topic.title)


def results_html(topics: tuple[HelpTopic, ...], query: str) -> str:
    matches = search_topics(topics, query)
    blocks = [f"<h1>Suchergebnisse</h1><p>{len(matches)} Themen zu "
              f"<b>{escape(query)}</b> gefunden.</p>"]
    if not matches:
        blocks.append("<p>Keine Treffer. Versuche einen allgemeineren Suchbegriff.</p>")
    for topic in matches:
        blocks.append(f'<p><a href="help://topic/{escape(topic.key)}">'
                      f'<b>{escape(topic.title)}</b></a><br/>'
                      f'<span class="quiet">{escape(topic.category)}</span></p>')
    blocks.append("<p><a href='help://home'>Zur Themenübersicht</a></p>")
    return _shell("\n".join(blocks), "ShellDeck – Suche")
