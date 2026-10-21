# PTY-Startgröße und erster Shell-Prompt (Patches 271–273)

## Beobachtung

Beim Start einer echten ShellDeck-PTY-Bash erscheint der erste Prompt, aber der
Terminalcursor steht auf Spalte 0. Nach Enter wird die nächste Eingabezeile
korrekt dargestellt. Dieses Verhalten wurde bereits vor Patch 268 beobachtet.

## Konkreter Befund

Unter Linux liefert ein frisch mit `os.openpty()` angelegtes PTY zunächst
`TIOCGWINSZ=(0,0)`. Bisher wurde die Bash gestartet und die Qt-/Grid-Größe erst
später mittels `TIOCSWINSZ` und ggf. SIGWINCH gesetzt. Damit konnte Readline
bereits einen Prompt unter ungültigen Größenbedingungen zeichnen.

## Änderung

- Patch 271: Initialgröße vor `posix_spawnp()` auf dem Slave-TTY setzen.
  Der bestehende `pty.fork()`-Fallback erhält die Größe im Kind vor `execvp()`.
- Patch 272: Beim Start des PTY-Prozesses wird die tatsächliche Grid-Größe
  übergeben; `QProcess` bleibt unberührt. Spätere Resize-Meldungen bleiben
  erhalten, u. a. für Window-Manager, Vollbild-Programme und TUI-Anwendungen.
- Patch 273: Integrationstest fragt TIOCGWINSZ als *erste Aktion* im Kind ab.
  Weitere Tests prüfen Größenvalidierung und die Aufrufreihenfolge.

## Wechselwirkungen und Grenzen

- Kein künstliches Verschieben des Modellcursors hinter das vermeintliche
  Prompt-Ende: Das wäre für Escape-Sequenzen, leere Zeilen, TUI-Programme,
  mehrzeilige Prompts und Shells mit anderer Darstellung falsch.
- Kein Eingriff in PTY-Lesepfad, pyte-Verarbeitung, Scrollback, Qt-Painting,
  Bash-Readline-Hooks, Vorbefehle, QProcess oder bestehende Auswahlzustände.
- Die Startgröße darf bei noch nicht finalisierten Qt-Layouts von der späteren
  tatsächlichen Größe abweichen; normale `resizeEvent`-/`SIGWINCH`-Meldungen
  korrigieren sie anschließend. Ein *gültiger* Initialwert verhindert 0x0.
- Der Test belegt die korrigierte Initialisierung, nicht die vollständige
  Behebung des optischen Problems in der echten PySide6-Oberfläche. Diese muss
  auf Ubuntu im PTY-Modus geprüft werden. Windows/ConPTY bleibt unverändert.

## GUI-Abnahme

1. ShellDeck starten, `PTY/ConPTY – interaktiv` auswählen und Tab neu starten.
2. Ohne Enter oder Mausklick prüfen: Der Cursor steht hinter dem ersten Prompt.
3. Mehrmals Enter drücken, lange Eingaben, UTF-8 und `clear`/`cls` testen.
4. Fenster verkleinern/vergrößern und interaktives Programm (z. B. `less`)
   starten/beenden. Cursor muss im jeweiligen Terminalzustand bleiben.
5. Mit aktiviertem und deaktiviertem Vorbefehl wiederholen.

Falls der Fehler fortbesteht, sind die vorhandenen `cursor_diagnostic` und
`_cursor_diagnostic_text`-Messwerte bei Erstausgabe und erstem `grid_resize`
entscheidend. Nicht anhand sichtbarer Prompt-Glyphen künstlich positionieren.
