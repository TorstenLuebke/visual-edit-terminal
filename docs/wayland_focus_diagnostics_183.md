# Qt-Wayland: Fokusdiagnose (optional)

Die Diagnose ist standardmäßig **ausgeschaltet**. ShellDeck verändert dadurch
weder den Fokusablauf noch die Qt-Protokollierung. Sie zeichnet ausschließlich
Zeitstempel sowie **Python-/Qt-Widget-Klassennamen** bei `focusChanged` auf.
Benutzereingaben, Befehle, Widgetnamen und Textinhalte werden nicht erfasst.

Unter Ubuntu ShellDeck testweise so starten:

```bash
cd ~/Programme/visual-edit-terminal
SHELLDECK_FOCUS_TRACE_PATH="$HOME/Downloads/shelldeck_focus.jsonl" .venv/bin/python src/main.py
```

Im Fenster einen Tab öffnen, zwischen zwei Tabs wechseln, in das Eingabefeld
klicken und die Schritte wiederholen, bei denen im Startterminal viele
`qt.qpa.wayland.textinput`-Meldungen erscheinen. Danach die Anwendung beenden.
Die Datei `~/Downloads/shelldeck_focus.jsonl` enthält die Fokuswechsel.

Das Protokoll darf nur bei ausdrücklicher Aktivierung erstellt werden.
Seit Patch 293 werden die wiederholten Warnungen der Kategorie
`qt.qpa.wayland.textinput.warning` beim normalen Start **nur unter Linux/Wayland**
unterdrueckt. Eine explizit aktivierte Fokusdiagnose laesst diese Warnungen
weiterhin sichtbar, um den zeitlichen Zusammenhang zu bewahren.
Eine Korrelation zeitgleicher Ereignisse zeigt, ob ShellDeck oft den Fokus
wechselt; sie beweist allein noch keine Ursache in ShellDeck.

Nach dem Test die Datei bei Bedarf löschen. Start ohne die Umgebungsvariable
schaltet die Aufzeichnung wieder aus.

## Qt-Wayland-Warnungen im Normalbetrieb (Patch 293)

Die Meldungen `QWaylandTextInputv3::enableSurface/disableSurface` mit
`Trying to ... but ... is focused` stammen aus der Qt/Wayland-Texteingabe.
ShellDeck schaltet standardmaessig **nur die Warnstufe dieser Qt-Kategorie** ab.
Andere Qt-Warnungen, kritische Meldungen, Python-Fehler und echte Ausgaben der
Terminalprogramme bleiben erhalten. Die Ursache moeglicher Fokuswechsel wird
hierdurch **nicht** repariert; bei Fehlfunktionen ist eine Diagnose erforderlich.

Um die Warnungen fuer eine Untersuchung wieder einzuschalten:

```bash
SHELLDECK_QT_WAYLAND_TEXTINPUT_LOG=1 .venv/bin/python src/main.py
```

Alternativ bleibt ein vorhandenes `QT_LOGGING_RULES` oder `QT_LOGGING_CONF`
unveraendert und hat Vorrang vor der ShellDeck-Voreinstellung. Filterregeln
werden nur im ShellDeck-Qt-Prozess angewendet, **nicht** als Umgebungsvariable
an gestartete Terminalprogramme vererbt. Andere Betriebssysteme und
Nicht-Wayland-Sitzungen sind von der Aenderung nicht betroffen.
