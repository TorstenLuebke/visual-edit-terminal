# ShellDeck – Patch 291: Frei belegbare Schnellbefehlsleiste

## Funktion

- **Ansicht → Schnellbefehle** ist der zentrale Menüeintrag. Dort liegen Leiste anzeigen, Ein-/Ausklappen (F8), Anheften, Position → Links/Rechts, Schmale Buttons, Buttons verwalten und Sicherheitshinweis wieder anzeigen.
- **Stecknadel**: dauerhaft sichtbar oder beim Verlassen der Leiste/Fokuswechsel einklappen. Eine schmale Kante bleibt erreichbar.
- **+ / −** fügt Befehlsbuttons hinzu bzw. entfernt den ausgewählten Button (mit Rückfrage). **Rechtsklick**: Bearbeiten, Duplizieren, Löschen.
- **Ziehen** ändert die Buttonreihenfolge. Kurze Namen oder automatische Nummerierung; kompakter oder breiter Modus. Die Schalter sind flacher (23–25 px statt 36 px); die Leiste im schmalen Modus nur 94 px breit.
- Standardmäßig zehn Vorlagen, die je nach Ziel-Tab-Shell für Linux/Bash, macOS, Windows-CMD oder Windows-PowerShell aufgelöst werden. Veränderte Vorlagen bleiben bei Plattformwechseln bewusst benutzerspezifisch.
- Jeder Button hat **unabhängige** Haken für Ausführungsbestätigung und Vorbefehl, optionalen eigenen Shortcut und Ausführung im neuen Tab.
- Speicherung unter `~/ShellDeckTerminal/quick_commands.json` (Linux/macOS) bzw. `%APPDATA%/ShellDeckTerminal/quick_commands.json` (Windows); bestehende Änderungen bleiben erhalten, gelöschte Buttons erscheinen nicht wieder.
- In der Befehlspalette (`Strg+Umschalt+P`) sind gespeicherte Schnellbefehle ebenfalls aufrufbar.

## Terminaltextschutz

Die Schnellbefehlsleiste verändert ausschließlich Qt-Dock-Geometrie. Terminalausgaben werden nicht gelöscht, rekonstruiert oder per `clear()` zurückgesetzt. Die bisherigen VT-Reflow-Korrekturen, insbesondere Patch 286 und 289, bleiben unverändert.

Schnellbefehle dürfen weder laufenden Clients noch Passwort- oder Antwortdialogen als Eingabe geschickt werden. Ein bereits begonnener Befehl im klassischen Eingabefeld bleibt unangetastet. Im echten VT-Grid kann eine unbestätigte, bereits getippte Readline-Eingabe nicht immer sicher erkannt werden. Deshalb bietet ShellDeck für einen Schnellbefehl im aktuell benutzten VT-Grid explizit **einen neuen Tab** an. Damit sind die bestehenden Eingaben und die laufende Anwendung im ursprünglichen Tab geschützt. Ein als „neuer Tab“ konfigurierter Button öffnet diesen ohne die Zusatzabfrage. Die Schutzabfrage hat eine Option **„Nicht mehr fragen (immer neuen Tab verwenden)“**. Die erneute Anzeige wird über **Ansicht → Schnellbefehle → Sicherheitshinweis wieder anzeigen** eingeschaltet. Die Unterdrückung der Abfrage **hebt den Schutz niemals auf**: Es wird weiterhin immer ein neuer Tab angelegt.

Ein Schnellbefehl wird nicht automatisch beim Start der Anwendung ausgeführt.

## Prüfungen (Linux / Windows / macOS)

```bash
cd ~/Programme/shelldeck # gegebenenfalls tatsächliches Verzeichnis
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  src/test_shelldeck_quick_commands.py \
  src/test_shelldeck_quick_commands_gui.py \
  src/test_shelldeck_vt_reflow_286.py \
  src/test_shelldeck_vt_resize_stability_289.py
```

**Manuelle Abnahme auf Linux und Windows, anschließend macOS:**

1. ShellDeck normal starten. Die zehn Buttons überprüfen; mit `+` den VisualEdit-ZIP-Befehl erstellen, danach umbenennen, Tooltip kontrollieren, an andere Stelle ziehen, `−` und Kontextmenü testen.
2. Vorbefehl deaktivieren, Schnellbefehl testen. Danach Vorbefehl aktivieren und den **pro Button** vorhandenen Haken jeweils aus- und einschalten. Bestätigung unabhängig davon testen.
3. In einem normalen Terminal Tab `pwd` und eine sehr lange Ausgabe erzeugen. **Originaltext/Scrollback markieren bzw. sichtbar prüfen.** Leiste links/rechts, kompakt/breit, Stecknadel aus/an, 40 Mal öffnen/einklappen und Fenster stark verkleinern/vergrößern. Text muss danach vollständig vorhanden sein.
4. Im echten VT-Terminal die gleiche Resize- und History-Prüfung durchführen, außerdem Vollbildprogramm `vim`/`nano`/`htop` starten und Leiste umschalten. Nach Rückkehr muss der ursprüngliche Shell-Verlauf erhalten sein.
5. Befehl im Eingabefeld nur **vorschreiben**, Schnellbefehl drücken: Er darf nicht überschrieben oder abgesendet werden. Bei laufendem Programm/Passwortfrage: Ausführung muss abgewiesen werden.
6. Mit aktivem VT-Grid im aktuellen Tab Schnellbefehl drücken: Der Dialog muss neuen Tab anbieten. Erst nach ausdrücklicher Zustimmung öffnet sich der neue Tab; die ursprüngliche Sitzung bleibt unverändert.
7. Windows CMD und PowerShell separat überprüfen (Beispiel: `dir` vs. `Get-ChildItem -Force`). Linux Bash und (falls installiert) zsh und macOS zsh separat prüfen. Keine Linux-Befehle in CMD/PowerShell-Vorlagen verwenden.
8. ShellDeck beenden und erneut starten. Position, Stecknadel, Breite, eigene Buttons, ihre Reihenfolge, Optionen und Tastenkürzel müssen erhalten bleiben.

**Wichtig:** In der hier verfügbaren Erstellungsumgebung fehlten PySide6 und pyte. Deshalb ersetzen die bestandenen Qt-freien Tests keine interaktive GUI-Abnahme auf den drei Zielplattformen.

## Änderungen in Patch 292

- Alle Menüpunkte der Schnellbefehle unter **Ansicht → Schnellbefehle** zusammengefasst; kein verstreuter Eintrag mehr unter „Einstellungen“.
- Deutlich flachere Buttons und schmalere angedockte Leiste; umschaltbarer schmaler Modus.
- Der VT-Sicherheitshinweis ist optional ausblendbar, jederzeit im Menü wieder aktivierbar und schützt bei Unterdrückung weiterhin die Eingaben.
- Tastenkombinationen per Tastendruck aufnehmen, vor dem Speichern auf doppelte/ bekannte reservierte Belegungen prüfen; beim Duplizieren kein zweites Kürzel zuweisen.
- Unveränderte Terminal-Resize-/Reflow-Implementierung; Textverlust muss weiterhin manuell auf Linux/Windows und anschließend macOS geprüft werden.
