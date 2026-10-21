# ShellDeck: echte PTY-Vorbefehle in der interaktiven Bash (Patches 268–270)

## Fehlerursache

Die echte VT-Gitteransicht verbindet `TerminalGridView.dataReady` direkt mit
`_write_terminal_grid_input`. Die bislang getestete Vorbefehlslogik in
`execute_command` wird dadurch **nicht** aufgerufen. Die vorherigen vier
Tests aus Patch 267 konnten dieses Verhalten nicht erkennen.

## Umsetzung

- Linux/macOS, PTY, Bash: Die isolierte, temporäre Sitzungs-`bashrc` registriert
  einen **Bash-Readline-Accept-Line-Hook**. Nur beim Bestätigen einer nichtleeren
  Zeile am Bash-Prompt wird der aktuell aktivierte Vorbefehl in **derselben Bash**
  vor dem eigentlichen Befehl ausgeführt. Die ursprüngliche Eingabe und ihre
  Shell-Historie werden nicht umgeschrieben.
- Das VT-Gitter schreibt weiterhin **unveränderte** Eingabebytes ins PTY.
  Die Vorbefehlseinstellung wird vorher in eine private Datei der laufenden
  Bash-Sitzung synchronisiert (Dateirechte 0600). Wird der Vorbefehl
  ausgeschaltet, wird die Datei geleert.
- Interaktive Programme mit eigener Eingabe (`vim`, `python`, `read -p`,
  Passwortabfragen) werden nicht durch Qt mit Vorbefehlsbytes beschickt.
- Die klassische ShellDeck-Eingabe bzw. QProcess verarbeitet Vorbefehle wie
  bisher. Bei API-Eingaben in einer aktiven Bash-Gitteransicht verhindert
  ShellDeck eine doppelte explizite Vorbefehlsausführung.
- Im lokalen PTY-Bash-Startskript gibt es auch `cls()` als Aliasfunktion für
  das systemübliche `clear`. `cls` lässt sich somit am Bash-Prompt direkt
  benutzen; der Vorbefehl bleibt **allgemein** und nicht auf `clear` begrenzt.
- Bei abgeschalteter farbiger ShellDeck-Prompt-Option bleibt der Hook aktiv,
  ohne den gewünschten Prompt zu überschreiben.

## Grenzen

- PTY-PowerShell, cmd, zsh, fish und weitere Shells haben **noch keinen**
  gleichwertigen nativen Eingabehaken. Die neue Funktion ist nicht als
  universelle Befehlsübersetzung für Windows/Linux/macOS zu verstehen.
- Bash-Readline-Sondermodi, z. B. `read -e`, können eigene Zeilenbearbeitung
  aktivieren; diese Fälle sind noch nicht vollständig abgesichert.
- Vorbefehle laufen mit denselben Rechten wie die Shell. Interaktive
  Vorbefehle, die selbst Eingaben benötigen, können den Accept-Line-Ablauf
  blockieren und sind nicht für diese Betriebsart geeignet.
- Vorhandene Bash-Sitzungen müssen **neu gestartet** werden, damit sie die
  neue Sitzungs-`bashrc` laden. Die produktive Terminalengine bleibt pyte.

## Tests

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q \
  src/test_shelldeck_prompt_213.py \
  src/test_shelldeck_precommands_267.py \
  src/test_shelldeck_grid_precommands_270.py
```

Der neue Test startet unter Linux/macOS eine **wirkliche interaktive Bash im
PTY**, übergibt mehrere Eingaben, überprüft die Reihenfolge, Umschalten,
`cd`/`export`, `clear`, `cls` und `read -p`. Ein separater Test prüft
im Original-Widget-Quellcode, dass der Gittereingang vor dem PTY-Write
synchronisiert und dass QProcess/andere Shells davon ausgenommen sind.
