# ShellDeck – PTY/VT-Diagnose in der Hilfe (284)

Die Benutzerhilfe ist über **Hilfe → Terminaldiagnose und Aufzeichnung …**
und als Abschnitt in **Hilfe → Funktionen und Tastenkürzel (F1)** erreichbar.
Die Beschreibung stammt aus `src/shelldeck_vt_diagnostics_help_283.py` und wird
für beide Ansichten gemeinsam verwendet; die Hilfe führt keine Aktionen aus.

## Einsatz

Die Aufnahme kann interaktive Terminalfehler untersuchen, deren Ursache zwischen
PTY-Ausgabe, Ereignisverarbeitung, Zustandsmodell und Qt-Darstellung liegt.

- **VT-Diagnose: Modell und Ansicht speichern …** liefert eine Momentaufnahme.
- **VT-Rohdatenaufzeichnung starten …** wird vor einer zu prüfenden Handlung
  eingeschaltet; aus der Zeit davor stehen keine Rohbytes zur Verfügung.
- **ShellDeck neu starten + Startaufzeichnung …** zeichnet das gewählte Terminal
  ab dem nächsten Shell-Start auf. Der Nutzer bestätigt den Neustart, der
  bestehende Programme und nicht gespeicherten Shell-Zustand beendet.
- **● REC | ■ Stopp** ist ein Overlay ohne Änderung der VT-Gittergeometrie.
  Stoppen exportiert die Daten; nach dem Limit kann noch gespeichert werden.
- Die automatische Startdiagnose erzeugt private Dateien mit Rohbytes,
  Metadaten, Ereignissen sowie Anfangs- und Endzuständen im Benutzerverzeichnis
  (`Downloads`, sofern vorhanden). Inhalt und Pfade sind vor Weitergabe zu prüfen.

## Bedeutung für VisualEdit

Die Diagnosedateien sind lokale, reproduzierbare **Messdaten**, keine verifizierte
Fehlerursache und kein automatischer Auftrag zur Codeänderung. VisualEdit kann
sie später als externen Befund **nach expliziter Zustimmung** einlesen, sofern
es dafür einen geeigneten Importer mit Validierung gibt. Zeitstempel,
Ereignistypen und Zustandsänderungen sind grundsätzlich unabhängig von der
Programmiersprache der untersuchten Anwendung. Ein Importer oder eine
automatische Anbindung ist in ShellDeck noch **nicht** implementiert.

Die eigentliche Cursor-Korrektur aus 280–282 wurde im Ubuntu-GUI-Praxistest
nach Patch 282 durch sofort sichtbare Eingabe vor Enter bestätigt. Die
Diagnose bleibt auch für andere Start- und Interaktionsprobleme verfügbar.

## Sicherheit und Geltungsbereich

Rohaufzeichnungen können sensible Daten enthalten. Die Aufnahme ist
standardmäßig aus, ausdrücklich durch Nutzeraktion aktiviert und auf 4 MiB
begrenzt. Es findet keine automatische Weitergabe statt. QProcess hat keine
VT-Rohdatenaufnahme. Das Startdiagnose-Verhalten wurde auf Linux/PTY mit Bash
beobachtet; Windows/ConPTY und macOS müssen gegebenenfalls separat geprüft
werden. Die Hilfe ersetzt keine vollständige Testabnahme auf allen Systemen.
