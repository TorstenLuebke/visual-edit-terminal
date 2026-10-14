# terminal

Erstellt mit **Visual Edit** am 2026-05-10.

**Sprache:** Python

**Typ:** PySide6 GUI

## Start

Siehe Startdatei in `src/`.

### Nuitka-Standalone-Start (Patch 060)

Beim Start aus einer vorhandenen Konsole trennt ShellDeck seine GUI auf
POSIX-Systemen vom steuernden Terminal (Schutz vor SIGTTIN). Im Python-Quelllauf
wird weiterhin der Python-Interpreter gestartet. Bei einem Nuitka-Build kann
`sys.executable` dagegen auf eine nicht vorhandene Datei `python` im `.dist`-
Verzeichnis zeigen. Unter Linux wird in diesem Fall das tatsächlich laufende
Programm über `/proc/self/exe` neu gestartet, ohne es als Python-Skript zu
behandeln. Der normale Desktopstart und andere Tabs bleiben unverändert.

Der Regressionstest ist in `src/test_shelldeck_startup_session.py` enthalten.
Das behebt den fehlenden Relaunch-Pfad; ein davon unabhängiger Segmentation-Fault
im kompilierten Programm muss separat untersucht werden.

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

### Maussteuerung fuer interaktive Programme (Patches 051–056)

Wenn eine Anwendung per DECSET **SGR 1006** und einen Mausmodus **1000**
(Klicks), **1002** (zusaetzlich Ziehen) oder **1003** (alle Bewegungen)
aktiviert, sendet ShellDeck Mausereignisse direkt an **dieses** PTY. Dazu
gehoeren Klicks, Loslassen, Ziehen, Bewegungen und das Mausrad (xterm-SGR,
Zellkoordinaten ab 1). Die einzelnen Terminal-Tabs bleiben unabhaengig.

Ohne explizit ausgehandeltes SGR-Mausprotokoll bleiben das normale Markieren,
Kopieren und der lokale Scrollback unveraendert. **Umschalt + Ziehen** erzwingt
die lokale Auswahl, **Umschalt + Rechtsklick** das Kontextmenue und
**Umschalt + Mausrad** den lokalen Scrollback im normalen Shell-Bildschirm,
auch wenn eine Anwendung Mausereignisse anfordert. **Ausnahme:** Bei einem
aktiven Vollbildprogramm im alternativen Bildschirm bleibt der normale
Shell-Verlauf grundsaetzlich unveraendert; das Mausrad darf ihn dort nicht
verschieben. Mit 1000 ohne 1006 wird absichtlich kein falsches
Mausprotokoll erzeugt. Ueberpruefbar mit Qt-Ereignis-Regressionstests, einem
Qt-freien Protokolltest und einem echten Linux-PTY-Test.

Die Ausbaustufe umfasst **SGR-Mausberichte**, aber noch nicht alle aelteren
Mausprotokolle (X10, UTF-8 1005, urxvt 1015) oder plattformuebergreifende
Funktionstests auf Windows/macOS. Diese Unterschiede werden gesondert
geprueft. Es wurden keine neuen Laufzeitbibliotheken aufgenommen.

Die zeilenbasierten Zusatzfunktionen (Befehls-Tabelle, Prompt-Leiste, KI-Prompt)
gehören zum klassischen Modus und bleiben dort vollständig erhalten; „Reines
Terminal" und „Echtes Terminal" schließen sich pro Tab gegenseitig aus. Fehlt
`pyte`, bleibt ShellDeck unverändert bei der klassischen Darstellung. Die
Emulation ist plattformübergreifend (Windows/Linux/macOS), da `pyte` reines
Python ist und die Prozess-Ebene weiterhin PTY (Linux/macOS) bzw.
`pywinpty`/ConPTY (Windows) nutzt.

### Automatischer VT-Modus in PTY-Tabs (Patches 048–049)

ShellDeck wechselt im **betroffenen Tab** automatisch ins echte VT-Gitter, wenn
im klassischen PTY-Tab direkt `vim`, `nvim`, `nano`, `htop`, `btop`, `micro`, `mc`,
`tmux`, `screen`, `less` oder ein anderes registriertes interaktives Programm
aufgerufen wird. Ein lokal verifizierter Vordergrundjob (z. B. aus einem
Skript) kann den Wechsel ebenfalls ausloesen. Die vorhandene Shell bleibt
aktiv und wird nicht neu gestartet; andere Tabs oder Workspaces aendern sich
nicht. Beim Beenden des Programms bleibt die gewaehlte VT-Ansicht bestehen.

Ein manuell ausgeschalteter VT-Modus wird fuer denselben Vordergrundjob nicht
sofort wieder aktiviert. **QProcess/ConPTY:** Eine sichere Erkennung der
Vordergrund-Prozessgruppe steht nicht fuer alle Backends zur Verfuegung.
Insbesondere wird eine laufende QProcess-Shell **nie** zum automatischen
Moduswechsel beendet oder neu gestartet. Nicht eindeutig erkennbare
Shell-Konstrukte werden nicht als automatischer Direktstart klassifiziert.

## Eigene Hilfen fuer weitere Vollbildprogramme

Neue lokale POSIX-Vordergrundprogramme koennen ohne Aenderungen an der
Terminalsteuerung ueber `~/.config/ShellDeck/program_guides.json` hinzugefuegt
werden (oder `$XDG_CONFIG_HOME/ShellDeck/program_guides.json`).
Die Datei wird beim Start geladen; es werden **keine** Shellbefehle aus dieser
Datei ausgefuehrt. Beispiel fuer ein eigenes lokal installiertes Terminalprogramm:

```json
{
  "programs": [
    {
      "name": "myviewer",
      "label": "Mein Dateibetrachter",
      "help_text": "Beenden: q. Suchen: /.",
      "keys": ["q"],
      "aliases": ["myviewer-cli"],
      "button_label": "Beenden",
      "help_sections": [
        {"title": "Navigation", "entries": [
          {"keys": "Pfeiltasten", "description": "In der Liste navigieren"},
          {"keys": "/", "description": "Suche starten", "detail": "Mit Enter bestaetigen."}
        ]},
        {"title": "Beenden", "entries": [
          {"keys": "q", "description": "Dateibetrachter schliessen"}
        ]}
      ]
    }
  ]
}
```

Zulaessige Tastencodes: sichtbare ASCII-Einzelzeichen, `CTRL+A` bis `CTRL+Z`,
`F1` bis `F12`, `ESC`, `ENTER`, `TAB`, `SPACE`, `BACKSPACE`.
Das Feld `button_label` kann `Beenden` oder `Trennen` sein. `help_sections`
ist optional und definiert 1–12 durchsuchbare Hilfekapitel mit jeweils
1–25 Eintraegen (`keys`, `description`, optional `detail`). Ohne diese Daten
zeigt ShellDeck weiterhin `help_text` an. Texte werden HTML-sicher angezeigt;
die Hilfe fuehrt keine Tasten, Dateien, Weblinks oder Python-Code aus.
Der Konfigurationsparser begrenzt Laengen und verwirft fehlerhafte Eintraege.
Fuer neue Programme
bitte nur eine **bekannte, normale** Tastenkombination verwenden. Die
Anwendung erkennt weiterhin ausschliesslich vertrauenswuerdige lokale
POSIX-Vordergrundprozesse; SSH, Shells und geschuetzte Programmkennungen
koennen nicht durch Konfiguration ueberschrieben werden. Ein ungueltiger
Eintrag wird ignoriert; `USER_GUIDE_ERRORS` liefert die Diagnose.
Bestehende Tabs verwenden die beim Start geladenen Definitionen.
Fuer Windows-ConPTY und Multiplexer-Unterprogramme ist eine eigene sichere
Erkennung erforderlich; der Mechanismus wird dort nicht automatisch aktiviert.

## Kontextbezogene Bedienhilfe fuer Vollbildprogramme

Im **echten VT-Modus** erkennt ShellDeck auf Linux/macOS bekannte lokale
Vordergrundprogramme direkt ueber die aktive PTY-Prozessgruppe. Bei `vim`,
`vi`, `nvim`, `nano`, `htop`, `top`, `less`, `more`, `man`, `watch`,
`btop`, `micro`, `mc`, `tmux` und `screen` erscheint
eine schmale Leiste mit **Beenden** und **Hilfe**. Der Hilfe-Button oeffnet
nun einen grossen, **durchsuchbaren Dialog** mit Themen links und Hinweisen,
Tastenfolgen und Beispielen rechts. Er enthaelt mehrere Kapitel fuer alle 13
integrierten Programme und zeigt bei eigenen Programmen wahlweise die neuen
`help_sections` oder den bisherigen `help_text`. Die Texte sind bewusst
selbst formuliert; tatsaechliche Bindings koennen durch Version, Betriebssystem
oder Benutzerkonfiguration abweichen. Es erfolgt **keine** automatische
Installation, Versionsabfrage oder Prozesssteuerung durch die Hilfe.
Der Button gibt lediglich
das programmspezifische Beenden-Kommando an denselben PTY-Job weiter; er
beendet nicht die Shell und sendet keine systemweiten Kill-Signale.

Bei Vim versucht **Beenden** den normalen Ausstieg (`Esc`, `:q`, Enter).
Ungespeicherte Aenderungen bleiben dadurch geschuetzt. Zusaetzlich stehen
unter **Weitere Aktionen** das Speichern und Beenden (`:wq`) und das
**bestaetigungspflichtige** Verwerfen von Aenderungen (`:q!`) bereit.
Bei `tmux` und `screen` lautet der Button **Trennen** statt Beenden: Er
uebermittelt das jeweilige Standard-Detach-Kuerzel (tmux: Strg+B,d;
screen: Strg+A,d) und beendet keine Sitzung. Bei abweichenden Prefixen
muss die Sitzung manuell getrennt werden. Die Hilfe erkennt keine innerhalb
von Multiplexern oder entfernten SSH-Sitzungen laufenden Programme.
Jeder Tab hat seine eigene Erkennung; normale Tabs bleiben unveraendert.

Nano verwendet `Strg+X` und fragt bei Aenderungen selbst nach. Die Hilfefenster
geben eine kurze Bedienuebersicht; alle gewohnten Tastenkombinationen bleiben
erhalten.

Wenn die Prozessgruppe nicht sicher festgestellt werden kann, bleiben die
Aktionen aus Sicherheitsgruenden ausgeblendet. **ConPTY/Windows** verfuegt
noch nicht ueber die gleiche sichere Vordergrundprozess-Erkennung; eine
plattformgleiche Erweiterung ist vorgesehen, nicht bereits implementiert.

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
- Bei PTY/ConPTY wird der Reader ab Patch 025 per Backpressure gebremst;
  QProcess braucht weiterhin eine eigene Begrenzungsstrategie. Die
  begrenzte Anzeigehistorie ist vom wartenden Ausgabetext getrennt.

### PTY-Rueckstau ohne Byteverlust (Patches 024–025)

- Unter Linux/macOS (POSIX-PTY) und Windows (ConPTY/pywinpty) wartet der
  PTY-Reader nach jedem Signal auf die Uebernahme durch den GUI-Thread. Ein
  blockierter Qt-Eventloop kann damit keine unbegrenzte Zahl noch nicht
  verarbeiteter Reader-Signale aufbauen.
- In der **klassischen Terminalansicht** bremst der Reader ab 1.048.576
  noch nicht angezeigten Zeichen. Er liest erst wieder aus dem PTY, wenn der
  ausstehende Text auf 262.144 Zeichen abgearbeitet wurde. Die Bytes bleiben
  im Terminaldatenstrom und werden nicht stillschweigend geloescht.
- Beim Tab-Schliessen/Prozessabbruch kann der Reader trotz Rueckstau beendet
  werden. Der echte VT-Modus verwendet weiterhin seine separate Darstellung.
- **Geltungsbereich:** Diese Stufe begrenzt den *PTY-Reader-Rueckstau*, nicht
  den gesamten Prozessspeicher. Insbesondere QProcess-Puffer, das sichtbare
  Scrollback und andere Ausgabeverbraucher benoetigen eigene Grenzwerte.
- Regressionen: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_pty_backpressure.py` und anschliessend alle Tests.

### QProcess-Pipe-Ausgabe portionsweise bearbeiten (Patches 026–027)

- Auch der klassische QProcess-Pipe-Modus liest stdout/stderr jetzt in
  Schritten von maximal 32.768 Bytes pro Ereignisdurchlauf. Verbleibende Daten
  holt ein einzelner Qt-Timer nach; separate Kanaele behalten ihre Farben.
- Ab 1.048.576 noch nicht gezeichneten Zeichen setzt ShellDeck das Abholen
  aus dem QProcess-Pipe-Puffer aus. Nach Rueckgang auf 262.144 Zeichen
  wird wieder gelesen. Es werden keine gepufferten Bytes absichtlich verworfen.
- Eine bereits beendete Shell liefert ihre verbleibende stdout-/stderr-Ausgabe
  vor der Abschlussmeldung aus. Unter Linux/macOS bleiben UTF-8-Zeichen
  erhalten, die zwischen zwei Leseschritten geteilt werden.
- **Grenze:** Qt kann die Daten aus Betriebssystem-Pipes intern weiter puffern.
  Dies ist daher eine Begrenzung der GUI-Warteschlange und der Verarbeitung
  pro Ereignis, **keine harte Speicherobergrenze** für den QProcess-Backend.
  Die PTY-Backpressure aus 024–025 bleibt unveraendert.
- Regressionstests: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_qprocess_output_pump.py`; zusaetzlich die GUI und
  die reale Prozessbeendigung mit `QProcess` pruefen.

### Echter VT-Modus: sparsamere Zellzeichnung (Patches 028–029)

- Der VT-Renderer verwendet Schriftvarianten (fett, kursiv, unterstrichen,
  durchgestrichen) wieder, anstatt fuer jedes dargestellte Zeichen ein neues
  Qt-Schriftobjekt zu erzeugen. Explizite ANSI-/Truecolor-Farben werden mit
  einem auf 256 Eintraege begrenzten Cache aufgeloest.
- Nicht benachbarte veraenderte VT-Zeilen werden getrennt zum Neuzeichnen
  angemeldet; reine Cursorbewegungen aktualisieren alte und neue Cursorzeilen.
  Bei grossflaechigen Aenderungen wird weiterhin gebuendelt neu gezeichnet.
- Das begrenzte pyte-Scrollback (derzeit standardmaessig 2.000 Zeilen) bleibt
  von dieser Optimierung unberuehrt. Eine einstellbare VT-Historie und
  umfassendere VT-Lasttests sind spaetere Ausbauschritte.
- Tests: `PYTHONPATH=src QT_QPA_PLATFORM=offscreen python -m pytest -q
  src/test_shelldeck_terminal_grid.py` und anschliessend alle Tests.

### Getrennter Haupt- und Vollbildschirm (Patch 061 ff.)

VT-Programme wie `vim`, `htop`, `nano` und `less` koennen mit DECSET `?47`,
`?1047` oder `?1049` einen **alternativen Bildschirm** aktivieren. ShellDeck
verwendet dafuer jetzt einen eigenen, verlaufsfreien pyte-Screen. Verlassen
sie ihn, wird der bisherige Shell-Bildschirm mitsamt Verlauf wieder sichtbar.
Auch ueber mehrere PTY-Lesebloecke verteilte Steuersequenzen werden von
**einem** fortlaufenden VT-Parser verarbeitet. Die Trennung gilt pro Tab.

Im alternativen Bildschirm veraendert ein nicht ausgehandeltes Mausrad-Ereignis
nicht den lokalen Verlauf. Wurde xterm-Modus **1007** explizit aktiviert, wird
das Rad stattdessen in Auf-/Ab-Cursortasten umgesetzt. Bei aktiviertem
SGR-Mausmodus werden Mausberichte unveraendert an die Anwendung gesendet.

Regressionen: `test_shelldeck_vt_screen.py`,
`test_shelldeck_alternate_router.py`, `test_shelldeck_terminal_grid.py`.

### Zwischenablage im echten VT-Modus

Text mit der Maus markieren und per Rechtsklick kopieren oder einfuegen.
Alternativ `Ctrl+Shift+C` / `Ctrl+Shift+V`, `Ctrl+Insert` / `Shift+Insert`
und unter Linux die mittlere Maustaste nutzen. Das Kontextmenue kann auch
den sichtbaren Bildschirm markieren. `Ctrl+C` und `Ctrl+V` werden weiterhin an
interaktive Anwendungen durchgereicht und duerfen nicht als globale
Zwischenablage-Kuerzel verwendet werden.

### Groessenaenderung im echten VT-Modus

Bei aktivem VT-Modus wird die Terminalgroesse ausschliesslich aus dem
VT-Zellgitter und nicht aus der ausgeblendeten klassischen Textansicht
ermittelt. Nach Groessenaenderungen wird das komplette Gitter neu gezeichnet
und die PTY-Groesse aktualisiert. Vollbildprogramme wie vim/htop muessen
so ihren Zeilenumbruch und ihre Statuszeile erneut anpassen koennen.

### Interaktive Rückfragen und PTY-Größenänderungen (Patches 033–034)

- Identische erneut gesendete Rückfragen aktivieren den Antwortmodus nicht
  erneut. Bereits eingegebene Antworten werden auch bei Ausgabe oder
  Größenänderungen nicht mehr ungefragt gelöscht. Die Prompt-Anzeige wird
  nur bei tatsächlicher Textänderung aktualisiert.
- Größenänderungen der klassischen ShellDeck-Ansicht werden nach 100 ms
  ohne weitere Resize-Ereignisse an das PTY gemeldet. Das reduziert
  SIGWINCH-/Neuzeichnungsstürme beim Ziehen des Fensterrands.
- **Wichtig:** Die klassische Textansicht ist kein VT-Bildschirmemulator.
  `vim`, `htop`, `nano` und ähnliche interaktive Vollbildprogramme müssen
  im Modus Ansicht → Echtes Terminal (VT) mit PTY laufen. Der reine
  QTextEdit-Ausgabebereich kann Cursorbewegungen/Alternate-Screen nicht
  darstellen. Die VT-Ansicht verwendet weiterhin ihre eigenen Größenmeldungen.
- Regressionstests: `src/test_shelldeck_prompt_repeat_guard.py` und
  `src/test_shelldeck_pty_resize_debounce.py`.

### VT-Scrollback-Grenze (Etappe 2, Patches 035–036)

Unter **Einstellungen → Scrollback-Größe (echtes VT-Terminal)…** kann die
Anzahl der VT-Verlaufszeilen pro Tab separat auf **100 bis 20.000** eingestellt
werden (Standard **2.000**). Die Einstellung wird gespeichert und gilt auch
für bereits geöffnete, geteilte und ausgekoppelte VT-Tabs. Ein Tab ohne aktives
VT-Gitter übernimmt den Wert beim Einschalten. Bei kleinerem Grenzwert gehen
nur die ältesten Verlaufszeilen verloren. Der sichtbare Bildschirm, Cursor,
VT-Parser und laufende Terminalprozesse werden dabei nicht zurückgesetzt.
Die klassische Scrollback-Einstellung bleibt unabhängig.

### Versionsangabe (Patches 037 und 059)

Die Datei **`version.txt`** im ShellDeck-Projektverzeichnis enthält die
aktuelle Version (eine Zeile, z. B. `2.16.0`). Sie wird beim Start eingelesen;
**Fenstertitel**, F1-Hilfe, interne Versionsangaben und **Hilfe → Über**
verwenden denselben Wert. Nach einer Änderung ShellDeck neu starten.
Bei Auslieferung von gepackten Anwendungen muss `version.txt` als Ressource
**neben der ausführbaren Datei** (z. B. `ShellDeck.dist/version.txt`) liegen.
Unter Kompiler Pro **Versionsdatei → Auswählen → version.txt** verwenden und
„Version bei jedem Erstellen aus dieser Datei übernehmen“ aktivieren, wenn
auch die Paketversion synchronisiert werden soll. Diese Einstellung allein
garantiert nicht, dass die Datei im Laufzeit-Bundle landet; das ist nach dem
Build gesondert zu prüfen. Ältere Installationen mit ausschließlich
`versions.txt` werden weiterhin gelesen. Fehlen beide Dateien,
startet ShellDeck mit dem im Code hinterlegten Rückfallwert.

### Private VT/ANSI-Farbsequenzen (Patch 038–039)

- Einige pyte-Versionen werfen bei privaten CSI-SGR-Sequenzen wie
  `ESC[?4m` oder `ESC[>4;?m` einen `TypeError` (`private=True`). ShellDeck
  faengt diese Sonderform in seinem eigenen VT-Screen-Adapter ab: Private
  SGR-Codes werden ignoriert, normale Farben/Attribute unveraendert an
  pyte weitergegeben. Die globalen pyte-Klassen bleiben unangetastet.
- Betrifft beide VT-Bildschirmvarianten (mit und ohne History), insbesondere
  Ausgaben von interaktiven Terminalprogrammen. Kein Eingriff in PTY,
  QProcess oder klassische Entwicklerkonsole.
- Regressionen: `PYTHONPATH=src python -m pytest -q
  src/test_shelldeck_vt_private_sgr.py`. Die Stream-Integration wird nur
  bei installiertem pyte getestet.
