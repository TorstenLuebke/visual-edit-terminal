# terminal

Erstellt mit **Visual Edit** am 2026-05-10.

**Sprache:** Python

**Typ:** PySide6 GUI

## Start

Siehe Startdatei in `src/`.

## Kommandozeile

ShellDeck versteht die von Terminal-Emulatoren üblichen Startargumente. Die
Auswertung liegt in `src/shelldeck_cli.py` (Qt-frei und testbar).

Linux:

```
shelldeck --working-directory .
shelldeck --working-directory "/home/torsten/Meine Projekte"
shelldeck --new-tab "/home/torsten/Downloads"
shelldeck -e git status
shelldeck --working-directory /tmp -e pwd
```

Windows:

```
ShellDeck.exe --working-directory "C:\Users\Torsten\Projekte"
ShellDeck.exe --new-tab "C:\Users\Torsten\Downloads"
ShellDeck.exe -e git status
```

- `--working-directory PFAD` – Start mit einem Tab im Ordner. `~`,
  Umgebungsvariablen und relative Pfade werden aufgelöst. Existiert der Ordner
  nicht, startet ShellDeck trotzdem, meldet dies und nutzt das
  Standardverzeichnis.
- `--new-tab PFAD` – öffnet einen Tab im Ordner. Da ShellDeck bewusst keine
  neue Single-Instance-/IPC-Architektur einführt, wird dafür eine neue Instanz
  gestartet.
- `-e` / `--execute BEFEHL` – führt den nachfolgenden Befehl im Terminal aus.
  Alle Folgeargumente gehören zum Befehl (Argumentgrenzen bleiben erhalten).
  Zusammen mit `--working-directory` wird zuerst der Ordner gesetzt.

## Systemintegration

Direkt in der App unter **Einstellungen → Systemintegration…**. Die Logik liegt
UI-frei in `src/shelldeck_system_integration.py`; beim Import werden keine
Systemänderungen ausgelöst, und nichts geschieht automatisch beim Start.

### Linux

ShellDeck kann als **auswählbare** `x-terminal-emulator`-Alternative registriert
werden (Priorität 40). ShellDeck wird dadurch **nicht** automatisch zum
Standard. Das Standardterminal wählt man selbst:

```
sudo update-alternatives --config x-terminal-emulator
```

Die Auswahl ist jederzeit umkehrbar. Dateimanager verhalten sich bei „Terminal
hier öffnen“ unterschiedlich: Nur Dateimanager, die das Terminal über
`x-terminal-emulator` starten (z. B. Caja unter Ubuntu/MATE), übernehmen die
Auswahl automatisch. Andere verwenden ein fest hinterlegtes Terminal.

Für Distributionspakete registrieren die Maintainer-Skripte unter
`packaging/linux/debian/` ShellDeck bei der Installation und entfernen bei der
Deinstallation ausschließlich den ShellDeck-Eintrag. Das bisherige
Standardterminal bleibt unberührt.

### Windows

Der Explorer-Eintrag **„In ShellDeck öffnen“** ist für Ordner, Ordnerhintergrund
und optional Laufwerke verfügbar (benutzerbezogen, `HKCU\Software\Classes`). Er
kann installiert und entfernt werden; unter Windows 11 erscheint er ggf. erst
unter „Weitere Optionen anzeigen“. Das Inno-Setup-Include
`packaging/windows/shelldeck_explorer_integration.iss` bietet die Integration im
Installer als optionale Aufgabe an.

Die Windows-Integration macht ShellDeck **nicht** zum nativen
Windows-Standard-Terminalhost. Die Windows-Konsolendelegierung (ConPTY) ist ein
separates Projekt.

Details zur Paketierung: siehe `packaging/README.md`.

## Echtes Terminal (VT)

ShellDeck kann pro Tab als echtes VT/ANSI-Terminal laufen: Ansicht → „Echtes
Terminal (VT)". Dann werden Vollbild-Programme wie `vim`, `htop`, `less` oder
`nano` korrekt dargestellt. Voraussetzungen sind das optionale Paket `pyte`
(`pip install pyte`) und die PTY-Engine (wird bei Bedarf automatisch aktiviert).

Im echten Terminalmodus rendert ShellDeck ein echtes Zellgitter (Farben,
Cursor, Auswahl/Kopieren mit `Ctrl+Shift+C`, Einfügen mit `Ctrl+Shift+V` oder
Mittelklick, Scrollback per Mausrad) und meldet die Fenstergröße an das PTY.

Die zeilenbasierten Zusatzfunktionen (Befehls-Tabelle, Prompt-Leiste, KI-Prompt)
gehören zum klassischen Modus und bleiben dort vollständig erhalten; „Reines
Terminal" und „Echtes Terminal" schließen sich pro Tab gegenseitig aus. Fehlt
`pyte`, bleibt ShellDeck unverändert bei der klassischen Darstellung. Die
Emulation ist plattformübergreifend (Windows/Linux/macOS), da `pyte` reines
Python ist und die Prozess-Ebene weiterhin PTY (Linux/macOS) bzw.
`pywinpty`/ConPTY (Windows) nutzt.

## Prozessstabilitaet (Etappe 1)

- PTY/ConPTY und QProcess bleiben als getrennte, pro Tab auswählbare Backends
  erhalten. Jede Terminal-Registerkarte verwendet weiterhin ihren eigenen
  Prozess und eigene Ausgabe.
- Die PTY-Ausgabe wird beim Prozessende noch bis zum EOF ausgelesen; der
  angezeigte Exit-Code kommt, soweit das Backend ihn bereitstellt, vom
  Kindprozess.
- Verspaetete Reader-Signale und Restore-Timer aus vorherigen Shell-Sitzungen
  werden beim Wechsel oder Schliessen einer Sitzung ignoriert.
- Automatische Tests: `PYTHONPATH=src python -m pytest -q src/test_shelldeck_pty_lifecycle.py`
  (unter POSIX mit zusaetzlichem echtem PTY-Spawn-Test). Ein GUI- und
  Mehr-Tab-Praxistest bleibt fuer die Zielsysteme erforderlich.

### Sitzungsstatus und asynchrone Timer (Patches 008–009)

- `TerminalTab.get_session_state()` liefert pro Tab einen unveränderlichen
  Snapshot (`phase`, `shell_running`, `command_pending`, `interactive`,
  `engine`, `generation`, `busy`). Die Phasen `stopped`, `starting`, `ready`,
  `running` und `interactive` unterscheiden Shell-Prozess und Shell-Befehl.
  Für QProcess und PTY wird derselbe Zustandsprüfer verwendet. Die Abfrage
  verändert die laufende Shell nicht.
- Verzögerte Eingabe- und Echo-Timer werden nur ausgeführt, wenn Prozess und
  Generation unverändert sind und der Tab noch offen ist. Temporäre Echo-
  und Antwortpuffer werden bei jedem Shell-Neustart gelöscht.
- Regressionstests: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_session_state.py src/test_shelldeck_session_timer_guards.py`.


### Thread-sicherer POSIX-PTY-Start (Patches 013–014)

- Unter Linux startet die PTY-Engine neue Shells mit `os.posix_spawnp`
  statt mit `pty.fork`. Die neue Sitzung bekommt ueber `setsid` und das
  neu geoeffnete PTY-Slave ihre eigene Terminal-Steuerung (Job-Control).
  Damit entfaellt dort die Python-Warnung zum `forkpty()`-Aufruf aus einer
  mehrthreadigen Qt-Anwendung.
- Terminalgroesse, interaktive Eingabe, Exit-Code und die QProcess-Engine
  bleiben unveraendert. Ein Arbeitsverzeichnis wird durch eine kleine
  `sh -c`-Startumhuellung gesetzt; die eigentlichen Argumente werden mit
  `"$@"` unveraendert an das Zielprogramm uebergeben.
- Falls das Betriebssystem `posix_spawn(..., setsid=True)` nicht anbietet,
  bleibt der bisherige `pty.fork`-Start als Kompatibilitaetsweg erhalten.
  Insbesondere auf macOS muss das Verhalten mit der jeweils verwendeten
  System-/Python-Version separat getestet werden.
- Regressionstests (auch ohne Qt): `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_pty_lifecycle.py src/test_shelldeck_pty_spawn.py`.
  Der echte GUI-/Mehr-Tab-Test ist weiterhin Pflicht.

### Verlaessliches Schliessen von Terminal-Tabs (Patch 015)

- Tab-Schliessen, Workspace-Wechsel und App-Ende verwenden jetzt denselben
  idempotenten Sitzungs-Cleanup. Dadurch werden Prozesse gestoppt, offene
  `aboutToQuit`-Verbindungen getrennt und verzoegerte Shell-Timer entwertet.
- Andere laufende Tabs bleiben beim Schliessen einer Registerkarte erhalten.
- Regressionstests: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_tab_cleanup.py`.

### Verzoegerte CLI-Startbefehle (Patch 016)

- Ueber `--execute` angeforderte Befehle laufen erst, wenn die *urspruengliche*
  Shell im Tab tatsaechlich bereit ist. Bei Tab-Schliessen, Shell-Neustart oder
  Engine-Wechsel wird ein noch ausstehender Startbefehl verworfen.
- Scheitert der Shell-Start dauerhaft, wird der Befehl nicht blind nach dem
  Timeout ausgefuehrt, sondern eine Statusmeldung angezeigt. Andere Tabs
  koennen ihre eigenen Startbefehle weiterhin unabhaengig ausfuehren.
- Regressionstests: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_cli_session_fence.py`.

### Verschachtelte virtuelle Umgebungen und Vorbefehle (Patch 017)

- Die Shell-Prompt-Erkennung toleriert mehrere hintereinanderliegende oder
  geklammerte Aktivierungs-Praefixe virtueller Umgebungen (z. B. `((.venv_A))
  ((.venv) ) name@host:~/projekt$`). Nach Rueckkehr dieses Prompts schaltet
  ShellDeck aus dem Antwortmodus wieder auf normale Befehle um, sodass ein
  aktivierter Vorbefehl wie `cls` beim naechsten Befehl wirkt.
- Solange ein Prozess wirklich interaktiv auf Eingaben wartet, werden
  Vorbefehle weiterhin **nicht** vor Antworten ausgefuehrt.
- Regressionstest: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_terminal_controls.py`.

### PTY-Prozessende bei parallelen Sitzungen (Patches 018–019)

- POSIX-PTY-Leser und GUI synchronisieren `waitpid()`, damit ein gleichzeitiger
  Aufruf den echten Exit-Code nicht durch einen zweiten Reap-Versuch ersetzt.
- Bei erzwungener PTY-Beendigung wird nicht nur der Reader gestoppt: Der
  Kindprozess wird nach einer kurzen SIGTERM-Frist bei Bedarf hart beendet
  und sein Ende, soweit das Backend dies anbietet, gesondert abgewartet.
- Der Shutdown-Erfolg haengt auch davon ab, dass der Reader tatsaechlich
  beendet wurde. Bei Backends mit `isalive()` gilt das Reader-Ende nicht
  mehr als Nachweis fuer ein beendetes Kind.
- Regressionen ohne Qt: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_pty_shutdown.py src/test_shelldeck_parallel_pty_shutdown.py`.
  Der Linux-Test startet zwei unabhaengige PTYs, beendet das erste und
  prueft, dass das zweite weiterhin interaktiv antwortet. Die GUI- und
  macOS-/Windows-Praxistests bleiben zusaetzlich erforderlich.

## Etappe 2: Ausgabeleistung und Scrollback (Patches 020–021)

- **Klassische Ansicht / Entwicklerkonsole:** Der vorhandene zeitbudgetierte
  GUI-Drain bleibt bestehen. Ankommende Ausgabestücke werden nun in einer
  FIFO gesammelt und erst beim Zeichnen nach Farben zusammengefasst. Das
  vermeidet wiederholte Verkettungen großer Zeichenketten sowie das lineare
  Entfernen am Listenanfang. Textreihenfolge, Farbgrenzen, Prompt-Erkennung
  und die Ausgabeexport-Funktion bleiben erhalten.
- **Einstellungen → Scrollback-Größe (klassische Ansicht)…:** Legt die
  maximale Anzahl im QTextDocument gespeicherter Textblöcke je Tab fest
  (1.000 bis 100.000, Standard 25.000). Die Einstellung wird gespeichert
  und auf vorhandene, neue, geteilte und entkoppelte Tabs angewandt. Beim
  Verkleinern gehen die ältesten bereits angezeigten Zeilen verloren;
  diese können nicht aus dem Scrollback wiederhergestellt werden.
- **Echter VT-Modus:** Nutzt weiterhin seinen eigenen pyte-History-Speicher
  (derzeit Standard 2.000 Zeilen) und ist von dieser Einstellung noch nicht
  betroffen. Eine gemeinsame konfigurierte Begrenzung beider Darstellungen
  folgt in einem weiteren Entwicklungsschritt.
- Die Warteschlange eingehender Prozessausgabe wird *noch nicht hart*
  speicherbegrenzt. Dafür ist ein gesondertes Backpressure-Konzept nötig,
  das während interaktiver Programme keine wichtigen Bytes verliert.
- Tests: `PYTHONPATH=src python -m pytest -q src/test_shelldeck_output_buffer.py
  src/test_shelldeck_scrollback.py`; die Qt-/GUI-Prüfung erfolgt zusätzlich
  auf den Zielplattformen.

### Ausgabe-Tail fuer Statuspruefungen (Patch 022)

- Die Erkennung von Shell-Prompt, Passwort-/Rueckfragen und Inline-Prompt
  betrachtet nur die letzten maximal 6.000 Zeichen der angezeigten Ausgabe
  samt noch nicht gezeichneter FIFO. Das vermeidet wiederholte Volltextkopien
  bei sehr grossen Logs; die gespeicherte Anzeige und Warteschlange werden
  dabei weder geloescht noch gekuerzt.
- Regressionstests: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_output_tail.py`.

### Fairere GUI-Aktualisierung bei Ausgabefluten (Patch 023)

- Die klassische Ansicht verarbeitet pro Qt-Einfügevorgang maximal 8.192
  Zeichen und gibt dem Event-Loop zwischen Durchlaeufen Zeit fuer andere
  Fenster und Eingaben. Keine Ausgabe wird wegen des Zeitbudgets verworfen.
- Prompt-Anzeige und Tooltips der Befehlsliste werden bei vielen
  `readyRead`-Meldungen gebuendelt, statt fuer jeden Ausgabeblock neue
  Qt-Timer beziehungsweise Tabellendarstellungen anzulegen. Beim
  Befehlsabschluss erfolgt die finale Tabellenaktualisierung sofort.
- Die Warteschlange bleibt vorerst unbegrenzt. Ein echter Speicherschutz
  gegen extrem viel schneller eintreffende Ausgabe benoetigt Backpressure,
  ohne dabei Terminal-/Prompt-Daten zu verlieren.
