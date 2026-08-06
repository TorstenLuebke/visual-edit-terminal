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
