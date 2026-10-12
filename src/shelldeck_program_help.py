"""Strukturierte, rein lokale Programmhilfe fuer ShellDeck.

Die Hilfe liefert Textdaten, keine steuernden Terminaleingaben. Fachlich
konservative Standardtasten; je nach Programmversion, Konfiguration und
Tastaturbelegung koennen Bindings abweichen. Keine Fremdhandbuecher eingebettet.
"""

from dataclasses import dataclass
import unicodedata


@dataclass(frozen=True)
class HelpEntry:
    keys: str
    description: str
    detail: str = ""


@dataclass(frozen=True)
class HelpSection:
    title: str
    entries: tuple[HelpEntry, ...]


def _s(title, *rows):
    return HelpSection(title, tuple(HelpEntry(*row) for row in rows))


def _normalized(value):
    value = unicodedata.normalize("NFKD", str(value).casefold())
    return "".join(c for c in value if not unicodedata.combining(c)).replace("ae", "a").replace("oe", "o").replace("ue", "u")


def filter_help_sections(sections, query):
    """Nicht mutierende Suche in Titeln, Tasten, Beschreibungen und Beispielen.

    Mehrere Woerter werden als UND verknuepft. Treffer im Abschnittstitel
    zeigen den ganzen Abschnitt, andere Treffer nur die relevanten Eintraege.
    """
    terms = _normalized(query).split()
    if not terms:
        return tuple(sections)
    matches = []
    for section in sections:
        heading = _normalized(section.title)
        if all(term in heading for term in terms):
            matches.append(section)
            continue
        entries = tuple(entry for entry in section.entries if all(
            term in _normalized(" ".join((section.title, entry.keys, entry.description, entry.detail)))
            for term in terms
        ))
        if entries:
            matches.append(HelpSection(section.title, entries))
    return tuple(matches)


# Ausschliesslich eigene Kurzbeschreibungen und konservative Default-Bindings.
# Die Eintraege geben Orientierung, nicht eine vollstaendige Programmdokumentation.
PROGRAM_HELP = {
    "vim": (
        _s("Grundlagen und Modi",
           ("Normalmodus", "Navigation und Befehle", "Esc beendet Einfuege-/Auswahlmodi."),
           ("i / a", "Einfuegen vor / nach dem Cursor", "Mit Esc zurueck zum Normalmodus."),
           ("o / O", "Neue Zeile unter / ueber der aktuellen Zeile"),
           ("v / V / Strg+V", "Zeichenweise / zeilenweise / blockweise auswaehlen"),
           (":help BEGRIFF", "Eingebaute Vim-Hilfe oeffnen", "Beispiel: :help visual-block")),
        _s("Navigation",
           ("h j k l / Pfeiltasten", "Cursor bewegen"),
           ("w / b / e", "Zum naechsten / vorigen Wort / Wortende"),
           ("0 / ^ / $", "Zeilenanfang / erstes Zeichen / Zeilenende"),
           ("gg / G / 42G", "Dateianfang / Dateiende / Zeile 42"),
           ("Strg+F / Strg+B", "Seite vor / zurueck")),
        _s("Bearbeiten und Auswahl",
           ("x / dd", "Zeichen / aktuelle Zeile loeschen"),
           ("yy / p / P", "Zeile kopieren / nach / vor Cursor einsetzen"),
           ("u / Strg+R", "Rueckgaengig / Wiederholen"),
           ("d / y", "Auswahl loeschen / kopieren", "Zuvor im visuellen Modus markieren."),
           (".", "Letzte Aenderung wiederholen")),
        _s("Suchen und Ersetzen",
           ("/text / ?text", "Vorwaerts / rueckwaerts suchen", "Mit Enter starten."),
           ("n / N", "Naechster / vorheriger Treffer"),
           (":%s/alt/neu/g", "In allen Zeilen ersetzen"),
           (":%s/alt/neu/gc", "Jede Ersetzung bestaetigen")),
        _s("Dateien, Fenster und Tabs",
           (":e datei", "Weitere Datei oeffnen", "Ungespeicherte Aenderungen koennen den Wechsel blockieren."),
           (":split / :vsplit", "Horizontal / vertikal teilen"),
           ("Strg+W, dann w", "Zum naechsten Fenster wechseln"),
           (":tabnew / gt / gT", "Neuen Vim-Tab oeffnen / zwischen Vim-Tabs wechseln"),
           (":set number", "Zeilennummern anzeigen")),
        _s("Speichern und Beenden",
           ("Esc :w Enter", "Datei speichern"),
           ("Esc :q Enter", "Normal beenden", "Bei ungespeicherten Aenderungen bleibt Vim offen."),
           ("Esc :wq Enter", "Speichern und beenden"),
           ("Esc :q! Enter", "Ohne Speichern beenden", "Verwirft Aenderungen an diesem Puffer."),
           ("Esc :qa Enter", "Alle Vim-Fenster schliessen", "Ungespeicherte Aenderungen verhindern das Beenden.")),
    ),
    "nano": (
        _s("Grundlagen und Navigation",
           ("Pfeiltasten", "Cursor bewegen"),
           ("Strg+A / Strg+E", "Zum Zeilenanfang / -ende"),
           ("Strg+Y / Strg+V", "Seite zurueck / vor"),
           ("Strg+_", "Zu Zeile und Spalte springen")),
        _s("Bearbeiten",
           ("Strg+K", "Zeile oder Markierung ausschneiden"),
           ("Strg+U", "Ausschneidepuffer einsetzen"),
           ("Alt+6", "Zeile oder Markierung kopieren"),
           ("Alt+A", "Markierung beginnen/beenden", "Bindings koennen je nach Nano-Version abweichen."),
           ("Alt+U / Alt+E", "Rueckgaengig / Wiederholen")),
        _s("Suchen und Ersetzen",
           ("Strg+W", "Nach Text suchen"),
           ("Alt+W", "Naechsten Treffer suchen"),
           ("Strg+\\", "Suchen und ersetzen", "Rueckfragen beachten.")),
        _s("Dateien und Hilfe",
           ("Strg+O", "Datei schreiben", "Dateiname mit Enter bestaetigen."),
           ("Strg+R", "Datei in aktuellen Puffer einfuegen"),
           ("Strg+G", "Nano-interne Hilfe"),
           ("Strg+X", "Beenden", "Bei Aenderungen fragt Nano nach dem Speichern.")),
    ),
    "htop": (
        _s("Navigation und Prozesse",
           ("Pfeiltasten / Bild auf, ab", "Prozess auswaehlen und scrollen"),
           ("F3 / /", "Prozess suchen"),
           ("F4", "Prozesse filtern"),
           ("F5", "Baumansicht umschalten"),
           ("Leertaste", "Prozess markieren", "Markierungen betreffen moeglicherweise mehrere Aktionen.")),
        _s("Sortierung und Anzeige",
           ("F6", "Sortierspalte auswaehlen"),
           ("F2", "Einstellungen oeffnen"),
           ("F1 / h", "Interne Hilfe oeffnen")),
        _s("Prozessaktionen",
           ("F9", "Signal-Menue fuer den gewaehlten Prozess", "Achtung: Beenden anderer Prozesse kann Daten verlieren."),
           ("F7 / F8", "Nice-Wert anpassen", "Berechtigungen koennen erforderlich sein."),
           ("q / F10", "Htop verlassen")),
    ),
    "top": (
        _s("Anzeige",
           ("h / ?", "Befehlsuebersicht anzeigen"),
           ("1", "Prozessoren einzeln / gemeinsam anzeigen"),
           ("Leertaste", "Anzeige sofort aktualisieren"),
           ("d", "Aktualisierungsintervall setzen")),
        _s("Sortieren und Filtern",
           ("P / M / T", "Nach CPU / Arbeitsspeicher / Laufzeit sortieren"),
           ("o", "Filterausdruck eingeben", "Verfuegbarkeit abhaengig von der top-Version.")),
        _s("Aktionen und Beenden",
           ("k", "Signal an Prozess senden", "PID und Signal werden abgefragt."),
           ("r", "Nice-Wert eines Prozesses aendern"),
           ("q", "Top beenden")),
    ),
    "less": (
        _s("Blaettern und Navigation",
           ("Leertaste / b", "Eine Seite vor / zurueck"),
           ("Enter / y", "Eine Zeile vor / zurueck"),
           ("g / G", "Dateianfang / Dateiende"),
           ("F", "Auf neue Ausgaben warten", "Mit Strg+C wieder zur Navigation.")),
        _s("Suchen",
           ("/text / ?text", "Vorwaerts / rueckwaerts suchen"),
           ("n / N", "Naechster / vorheriger Treffer"),
           ("&text", "Nur passende Zeilen anzeigen")),
        _s("Hilfe und Beenden",
           ("h", "Less-interne Hilfe"),
           ("q", "Less beenden"),
           ("less -N datei", "Mit Zeilennummern starten", "Shell-Befehl; nicht im laufenden Less eintippen.")),
    ),
    "more": (
        _s("Blaettern und Suche",
           ("Leertaste", "Eine Bildschirmseite weiter"),
           ("Enter", "Eine Zeile weiter"),
           ("/text", "Text suchen", "Mit Enter bestaetigen; Optionen je nach Implementierung."),
           ("b", "Seite zurueck", "Nicht auf allen More-Versionen verfuegbar.")),
        _s("Hilfe und Beenden",
           ("h / ?", "Verfuegbare Tasten anzeigen", "Version und Implementierung beachten."),
           ("q", "More beenden")),
    ),
    "man": (
        _s("Handbuecher oeffnen (Shell)",
           ("man ls", "Handbuch zu ls lesen"),
           ("man 5 passwd", "Bestimmten Handbuchabschnitt waehlen"),
           ("man -k BEGRIFF", "Passende Handbuecher suchen"),
           ("man -f BEFEHL", "Kurzbeschreibungen anzeigen")),
        _s("Navigation im Pager",
           ("Leertaste / b", "Seite vor / zurueck", "Bei Standard-Pager less."),
           ("/text / n / N", "Suche und Treffer wechseln", "Bei Standard-Pager less."),
           ("h", "Pager-Hilfe anzeigen", "Abhaengig von der Pager-Konfiguration."),
           ("q", "Handbuch verlassen")),
    ),
    "watch": (
        _s("Aufruf in der Shell",
           ("watch BEFEHL", "Befehl regelmaessig erneut ausfuehren"),
           ("watch -n 2 BEFEHL", "Aktualisierung alle zwei Sekunden"),
           ("watch -d BEFEHL", "Unterschiede hervorheben"),
           ("watch -t BEFEHL", "Kopfzeile ausblenden"),
           ("watch -g BEFEHL", "Bei geaenderter Ausgabe beenden", "GNU watch; je nach System nicht vorhanden.")),
        _s("Waehren der Ausfuehrung",
           ("Strg+C", "Watch beenden", "Beendet nicht zwangslaeufig jeden vom Befehl gestarteten Hintergrundprozess.")),
    ),
    "btop": (
        _s("Navigation und Anzeige",
           ("Pfeiltasten", "Listen und Auswahl bewegen"),
           ("Esc", "Menue oeffnen oder schliessen", "Abhaengig vom aktuellen Btop-Bildschirm."),
           ("Maus", "Einige Anzeigen und Menues bedienen", "Bei aktivierter Mausunterstuetzung.")),
        _s("Prozesse",
           ("Prozess auswaehlen", "Details und moegliche Aktionen im Prozessfenster", "Tasten und Menues koennen je nach Version variieren."),
           ("Menue: Optionen", "Darstellung, Update-Intervall und Farben konfigurieren")),
        _s("Hilfe und Beenden",
           ("Esc / Menue", "Hilfe oder Optionen im Menue suchen"),
           ("q", "Btop verlassen")),
    ),
    "micro": (
        _s("Bearbeitung und Navigation",
           ("Pfeiltasten", "Cursor bewegen"),
           ("Strg+C / Strg+V", "Kopieren / Einfuegen", "Abhaengig von Clipboard-Einstellungen."),
           ("Strg+Z / Strg+Y", "Rueckgaengig / Wiederholen"),
           ("Strg+A", "Alles markieren")),
        _s("Suchen und Befehle",
           ("Strg+F", "Suchen"),
           ("Strg+E", "Befehlszeile des Editors oeffnen", "Beispiel: help, quit oder open datei."),
           ("Strg+G", "Hilfe oeffnen", "Bindings koennen konfiguriert sein.")),
        _s("Dateien und Beenden",
           ("Strg+S", "Speichern"),
           ("Strg+O", "Datei oeffnen", "Bei Standardbelegung."),
           ("Strg+Q", "Beenden", "Bei ungespeicherten Aenderungen Rueckfrage beachten.")),
    ),
    "mc": (
        _s("Panels und Navigation",
           ("Tab", "Zwischen den Dateipanels wechseln"),
           ("Pfeiltasten / Enter", "Datei oder Verzeichnis auswaehlen / oeffnen"),
           ("Strg+O", "Zwischen Panels und Unter-Shell wechseln", "Wenn die Unter-Shell aktiv ist.")),
        _s("Dateiverwaltung",
           ("F3 / F4", "Datei betrachten / bearbeiten"),
           ("F5 / F6", "Kopieren / Verschieben oder Umbenennen"),
           ("F7", "Verzeichnis erstellen"),
           ("F8", "Dateien loeschen", "Vorher Ziel und Auswahl genau kontrollieren.")),
        _s("Menues und Beenden",
           ("F9", "Menueleiste aktivieren"),
           ("F10", "Midnight Commander beenden")),
    ),
    "tmux": (
        _s("Sitzungen (Shell)",
           ("tmux new -s arbeit", "Benannte Sitzung erstellen"),
           ("tmux ls", "Sitzungen auflisten"),
           ("tmux attach -t arbeit", "Vorhandene Sitzung wieder verbinden"),
           ("tmux kill-session -t arbeit", "Sitzung endgueltig beenden", "Schliesst die darin laufenden Programme!")),
        _s("Standard-Prefix Strg+B",
           ("Strg+B, dann d", "Sitzung trennen", "Die Programme bleiben weiter aktiv."),
           ("Strg+B, dann c", "Neues tmux-Fenster"),
           ("Strg+B, dann n / p", "Naechstes / vorheriges Fenster"),
           ("Strg+B, dann % / \"", "Panel vertikal / horizontal teilen"),
           ("Strg+B, dann Pfeiltaste", "Zwischen Panels wechseln"),
           ("Strg+B, dann ?", "Tmux-Tastenhilfe anzeigen")),
        _s("Sicherheit und Konfiguration",
           ("Prefix geaendert?", "Geaendertes Prefix aus ~/.tmux.conf beachten", "Die ShellDeck-Trennen-Schaltflaeche verwendet das Standard-Prefix."),
           ("Strg+B, dann x", "Ausgewaehltes Panel schliessen", "Kann darin laufende Programme beenden; Rueckfrage beachten.")),
    ),
    "screen": (
        _s("Sitzungen (Shell)",
           ("screen -S arbeit", "Benannte Sitzung starten"),
           ("screen -ls", "Sitzungen auflisten"),
           ("screen -r", "Getrennte Sitzung wieder verbinden"),
           ("screen -S arbeit -X quit", "Sitzung endgueltig beenden", "Schliesst darin laufende Programme!")),
        _s("Standard-Prefix Strg+A",
           ("Strg+A, dann d", "Sitzung trennen", "Programme bleiben aktiv."),
           ("Strg+A, dann c", "Neues Fenster erstellen"),
           ("Strg+A, dann n / p", "Naechstes / vorheriges Fenster"),
           ("Strg+A, dann \"", "Fensterliste anzeigen"),
           ("Strg+A, dann ?", "Interne Hilfe anzeigen")),
        _s("Sicherheit und Konfiguration",
           ("Prefix geaendert?", "Eigene ~/.screenrc beachten", "Die ShellDeck-Trennen-Schaltflaeche nutzt das Standard-Prefix."),
           ("Strg+A, dann k", "Aktuelles Fenster schliessen", "Achtung: darin laufende Programme werden beendet.")),
    ),
}


def help_sections_for(guide):
    """Programmspezifische Hilfe; fuer benutzerdefinierte Guides sichere Text-Fallbacks."""
    if guide is None:
        return ()
    predefined = PROGRAM_HELP.get(guide.name)
    if predefined is not None:
        return predefined
    if getattr(guide, "help_sections", ()):
        return tuple(_s(title, *rows) for title, rows in guide.help_sections)
    # Freie JSON-Texte bleiben Plaintext; der Renderer escaped sie vor HTML.
    lines = tuple(line.strip() for line in guide.help_text.splitlines() if line.strip())
    return (_s("Bedienhinweise", *(("", line) for line in lines)),) if lines else ()
