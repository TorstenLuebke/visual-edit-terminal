# ShellDeck VT-Startdiagnose (Patches 274–276)

## Hintergrund

Eine manuell im Kontextmenü gestartete PTY-Aufzeichnung erfasst den
**ersten Prompt nach dem Start** nicht. Das Fehlerbild kann sich später
beim ersten Enter bereits verändert haben. Der diagnostische Neustart
schaltet die Aufzeichnung daher beim Erzeugen der **ersten** neuen
`TerminalGridView` an, **bevor** `start_shell()` die Bash startet.

## Bedienung

1. Im echten PTY-Terminal **Shift + Rechtsklick** öffnen.
2. Ganz unten **„ShellDeck neu starten + Startaufzeichnung …“** wählen.
3. Sicherheits- und Datenschutzbestätigung lesen und bestätigen.
4. Die gesamte Anwendung startet neu; im ersten neuen echten Terminal
   erscheint rechts oben die schwebende Anzeige **● REC  [■ Stopp]**.
5. Den sichtbaren Startfehler beobachten, ggf. `abc` eingeben (ohne Enter).
6. **■ Stopp** klicken; der Dateisatz wird automatisch im neu erstellten
   privaten Ordner `~/Downloads/ShellDeck_Startdiagnose_…/` gespeichert
   (ersatzweise direkt im Home-Verzeichnis). Anschließend erscheint der
   Speicherort. Der Kontextmenüpunkt „Aufzeichnung beenden …“ funktioniert
   weiterhin. Falls die 4-MiB-Grenze erreicht wurde, bleibt **Speichern**
   verfügbar, ohne weiter aufzuzeichnen.

Es werden binäre PTY-Ausgaben (`*.bin`), zeitliche Ereignisse (`*.jsonl`),
Start- und Endmodell (`*.txt`) und Metadaten (`*.meta.txt`) gesichert.
Die Eingabewerte selbst werden nicht als gesonderte Tastaturprotokolle
aufgezeichnet. Allerdings **können die PTY-Ausgaben Geheimnisse enthalten**,
zum Beispiel eingegebene Befehle, Daten aus Dateien oder Ausgaben von Tools.
Die Dateien vor dem Weitergeben kontrollieren. Der Ordner ist privat
(0700), die Dateien sind privat (0600). Es wird nichts automatisch versendet.

Die Anzeige liegt **über** dem Qt-Gitter und wird nicht in dessen Layout
aufgenommen. Damit verändert sie weder Zeilenzahl noch PTY-Fenstergröße.

## Sicherheits- und Gültigkeitsgrenzen

- Die Startdiagnose ist standardmäßig aus und erfordert eine ausdrückliche
  Zustimmung zum Neustart der gesamten Anwendung. Bestehende Shell-Zustände
  gehen dadurch verloren; laufende Jobs werden beendet.
- Die opt-in Umgebungsvariable wird vor dem Start der ersten VT-Shell
  verbraucht und nicht an Kind-Shells vererbt. Nur das **erste** neue
  VT-Gitter zeichnet auf; keine globale Überwachung anderer Tabs.
- Der neue Prozess wartet bis zum Ende des alten, damit dieser seine
  Workspace-Einstellungen speichern kann.
- Beim Abbruch des Dateidialogs einer **manuellen** VT-Aufnahme bleiben die
  Daten zum späteren Speichern im Speicher. Bei der Startdiagnose entfällt
  der Dateidialog, denn der vorab erstellte private Zielordner steht fest.
- Nach Beenden oder Erreichen des 4-MiB-Limits ist die Aufnahme gestoppt,
  und der Nutzer kann die Daten speichern. Ohne Stoppen werden die
  Rohdaten nicht automatisch auf die Festplatte geschrieben.
- Diese Patches korrigieren **nicht** den Prompt-/Readline-/Cursorfehler.
  Sie ermöglichen erst einen belastbaren Nachweis ab dessen Entstehung.
