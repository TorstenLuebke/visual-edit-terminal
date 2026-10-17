# QProcess-Bash: experimenteller Batch-Modus

Stand nach Patch 129. Dieser Modus wird **nicht** automatisch aktiviert.

Start unter Linux: `SHELLDECK_QPROCESS_BASH_BATCH=1 .venv/bin/python src/main.py`.

Die nichtinteraktive Bash bleibt zwischen Befehlen bestehen (`cd`, `export`, `source`).
Befehle laufen mit `/dev/null` als Standardeingabe, damit Programme nicht
versehentlich Protokollbefehle aus der QProcess-Leitung lesen. Programme, die
Eingaben benötigen (z. B. Editoren oder `sudo` mit Eingabeaufforderung),
müssen im PTY/ConPTY-Modus ausgeführt werden.

Der Befehl ist erst abgeschlossen, wenn der gültige Abschlussmarker empfangen
wurde. Vorherige weitere Befehle werden nicht in die laufende Bash gesendet.
Bei unerwartetem Ende der Bash wird der wartende Zustand freigegeben.

**Einschränkungen:** Der Batch-Modus ist weiterhin experimentell. Seine
Kompatibilität mit allen GUI-Befehlsfolgen ist noch nicht bestätigt. Der
klassische QProcess-Modus bleibt ohne gesetzte Umgebungsvariable verfügbar.
Die PTY/ConPTY-Engine wurde nicht verändert.

## Stand nach Patch 137

Die experimentelle QProcess-Bash wird weiterhin nur mit
`SHELLDECK_QPROCESS_BASH_BATCH=1` aktiviert. Ein abgeschlossener Auftrag
wird durch den internen RS/US-gerahmten Abschlussmarker quittiert.
Der Marker muss vor der Terminal-Textbereinigung entfernt werden; ohne
aktiven Marker-Decoder verwendet ShellDeck weiter die normale Ausgabeverarbeitung.

Im Batch-Modus werden weitere Eingaben, einschließlich leerer Eingaben,
während eines laufenden Auftrags nicht zur Bash transportiert.
Abgewiesene Befehle dürfen weder den angezeigten Arbeitsordner noch den
aktuellen Auftragsstatus verändern. Für echte stdin-Interaktion ist weiterhin
die PTY/ConPTY-Engine erforderlich.

Die Freigabe als Standard bleibt vom erfolgreichen GUI-Praxistest abhängig.

## GUI-Auswahl (Patch 139–144)

Neben der Engine-Auswahl kann unter Linux für einen **QProcess-Bash-Tab**
zwischen „Bash: kompatibel“ und „Bash: ohne Jobsteuerung (Test)“ gewählt werden.
Der Wechsel startet diesen Tab neu und ist bei einem laufenden Befehl gesperrt.
Die Auswahl wird als `qprocess_bash_mode` in den ShellDeck-Einstellungen
persistiert. Die konservative Variante ist bei neuen Installationen Standard.
PTY/ConPTY und andere Shelltypen bleiben unverändert. Der Batch-Modus
unterstützt keine interaktive Standardeingabe. Ohne GUI-Einstellung bleibt der
frühere Umgebungsvariablen-Teststart für ältere Aufrufer verfügbar.

## Pipelines und Shell-Fehleroptionen

Pipelines werden als ein Bash-Auftrag ausgefuehrt. Bash-Optionen wie
`set -o pipefail` bleiben in der dauerhaften Sitzung erhalten. Das
Abschlussprotokoll gibt den Bash-Exit-Code der Pipeline zurueck.

**Bekannte Grenze:** Bei `set -u` kann ein nicht gesetzter Variablenname
die nichtinteraktive Bash sofort beenden, ohne einen Abschlussmarker zu
liefern. Dieser Fall ist ein Shell-Abbruch und keine erfolgreiche
Befehlsbeendigung. ShellDeck muss den beendeten QProcess erkennen und
darf den Auftrag nicht als erfolgreich markieren.

Der Batch-Modus ist weiterhin nicht fuer Programme geeignet, die
interaktive Eingaben von stdin benoetigen. Dafuer PTY/ConPTY verwenden.
