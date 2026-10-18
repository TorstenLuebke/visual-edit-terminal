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
Die bekannten Qt-Meldungen werden dabei bewusst **nicht** ausgeblendet.
Eine Korrelation zeitgleicher Ereignisse zeigt, ob ShellDeck oft den Fokus
wechselt; sie beweist allein noch keine Ursache in ShellDeck.

Nach dem Test die Datei bei Bedarf löschen. Start ohne die Umgebungsvariable
schaltet die Aufzeichnung wieder aus.
