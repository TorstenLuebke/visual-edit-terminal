# ShellDeck – Patch 294: Schnellbefehle im aktiven Terminal

## Bedienung

- Ein Schnellbefehl wird standardmäßig **in der aktuell ausgewählten Terminal-Sitzung** ausgeführt, nicht in einem automatisch angelegten Tab.
- In der individuellen Button-Konfiguration kann **„Befehl in neuem Terminal-Tab ausführen“** weiterhin freiwillig aktiviert werden.
- Die Checkboxen **„Vor jeder Ausführung nachfragen“** und **„Aktivierten Vorbefehl anwenden“** bleiben unabhängig davon einstellbar.
- Die bisherige generelle Warnung, dass VT-Befehle nur in neuen Tabs ausgeführt werden sollen, und der Menüpunkt **„Sicherheitshinweis wieder anzeigen“** unter **Ansicht → Schnellbefehle** entfallen.

## Shell-Ausführung und Schutz

- **Linux/macOS – Bash im echten PTY/VT-Modus:** Eine ShellDeck-interne, nur temporär für den jeweiligen Tab erzeugte Bash-Readline-Tastenbindung übernimmt den gespeicherten Befehl in die aktuelle **leere** Eingabezeile. Erst nach einer passenden Bestätigung der Shell wird die Readline-Zeile regulär abgeschickt. Dadurch wirken `cd`, `source`, `export` in derselben Bash und Befehle erscheinen im normalen Bash-Verlauf. Es wird **keine zweite Shell** gestartet. Mit aktiviertem Vorbefehl wird dieser vor dem eigentlichen Befehl ausgeführt – so wie beim manuellen Enter-Hook.
- Bereits begonnene Eingaben werden vom Readline-Hook **nicht überschrieben und nicht abgeschickt**. Während eines Vordergrundprogramms oder bei nicht erkennbar leerem Prompt verweigert ShellDeck die direkte Übergabe.
- **Windows – CMD/PowerShell, macOS – zsh und andere erkannte POSIX-Shells:** Bei zuverlässig erkanntem **leeren** Prompt werden die Befehle als normale Tastatureingabe über das vorhandene PTY/ConPTY übertragen. Da hier kein Bash-Readline-Handshake zur Verfügung steht, ist die Erkennung konservativ; bei unklarem Prompt wird **kein** Befehl übertragen. Ein neuer Tab wird **nicht** automatisch geöffnet.
- **Klassische Terminaleingabe / QProcess:** Verwendet unverändert die bestehende Befehlsverarbeitung.
- Die Sicherheitseigenschaft für Fremdprogramme mit ungewöhnlichen Prompts sowie die GUI-Bedienbarkeit unter Windows/macOS müssen auf den Zielsystemen separat geprüft werden.

## Technische Details

- Bash-Request und -ACK liegen in einem privaten TemporaryDirectory mit Dateiberechtigung `0600`; Dateinamen `grid_quick_command` und `grid_quick_ack`.
- Kein `eval` für den Schnellbefehl, keine Änderung am ShellDeck-Terminalpuffer, an VT-Reflow oder Resize-Logik.
- Altes Feld `vt_warning_enabled` wird für Kompatibilität zu bestehenden Einstellungsdateien weiterhin akzeptiert, hat aber keine Menüwirkung mehr.

## Gezielt testen

```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q \
  src/test_shelldeck_quick_command_same_tab_294.py \
  src/test_shelldeck_quick_commands.py \
  src/test_shelldeck_quick_shortcuts_292.py \
  src/test_shelldeck_vt_reflow_286.py \
  src/test_shelldeck_vt_resize_stability_289.py
```

Unter Ubuntu interaktiv in einem leeren Bash-PTY-Tab `pwd`, `cd ..`, `source .venv/bin/activate` (im passenden Projektverzeichnis) und `history` über Buttons testen. Besonders wichtig: ein unbestätigter, von Hand begonnener Befehl darf durch einen Button nicht verschwinden oder abgeschickt werden. Danach Windows (CMD und PowerShell), macOS (zsh/Bash) und die bekannten Resize-/Scrollback-Fälle testen.
