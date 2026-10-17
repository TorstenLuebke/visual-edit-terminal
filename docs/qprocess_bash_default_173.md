# QProcess-Bash: Standardwahl ab Patch 173

Auf Linux und macOS ist für **neue Einstellungen** die nichtinteraktive
QProcess-Bash (`batch`) voreingestellt. Auf Windows bleibt die klassische
QProcess-Bash (`classic`) voreingestellt; PTY/ConPTY ist davon unabhängig.

**Bereits gespeicherte Entscheidungen bleiben erhalten.** Eine vorhandene
Einstellung `qprocess_bash_mode` mit `classic` oder `batch` wird beim Laden
unverändert übernommen. Die Wahl lässt sich in der GUI bei QProcess weiter
ändern und wird gespeichert. `Bash: kompatibel` bleibt die Rückfalloption.

Die automatische Terminal-Engine-Auswahl (`auto`) wird **nicht** verändert.
Der neue Standard bezieht sich nur auf die Bash-Variante, wenn die QProcess-
Engine verwendet wird. Für Programme mit interaktiver Eingabe bleibt PTY/ConPTY
die passende Engine. Die Bezeichnung „Bash: ohne Jobsteuerung“ ist nach bestandener GUI-
Abnahme freigegeben. Die Auswahl `classic` bleibt jederzeit moeglich.

Bei beschädigten/unbekannten Einträgen wird ein plattformspezifischer Standard
verwendet. Diese Migration überschreibt gültige Benutzerwahlen nicht.
