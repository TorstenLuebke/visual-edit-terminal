# QProcess-Bash: Freigabe ab Patch 180

Unter Linux und macOS ist für **neu angelegte Einstellungen** die Bash ohne
Jobsteuerung (`qprocess_bash_mode: batch`) der Standard **innerhalb von QProcess**.
Die automatische Engine-Wahl (`auto`) bevorzugt weiterhin PTY/ConPTY.
Gespeicherte Werte (`batch` oder `classic`) werden beim Upgrade beibehalten.
Die GUI bietet „Bash: kompatibel“ als Rückfalloption an. Windows behält
für neue Profile die klassische QProcess-Bash als Vorgabe.

Die Bezeichnung „Bash: ohne Jobsteuerung“ ist freigegeben, aber sie ist
**kein vollwertiger Ersatz für ein interaktives PTY**: Programme mit
Terminalsteuerung, interaktiver Standardeingabe und Jobsignalen verwenden
PTY/ConPTY. `set -e` kann im Batch-Protokoll abweichend wirken. Bei `set -u`
kann eine fehlerhafte Variablenexpansion die Bash beenden. ShellDeck meldet
dann den Verlust des Sitzungszustands und bietet einen bestätigten Neustart an.

## Abnahme

1. Vollständige Testsuite mit `QT_QPA_PLATFORM=offscreen PYTHONPATH=src .venv/bin/python -m pytest -q` ausführen.
2. Frische Konfiguration sicher über `.venv/bin/python tools/run_fresh_profile.py` starten.
3. QProcess explizit auswählen, den Batch-Standard prüfen und zu `classic` zurückwechseln.
4. PTY/ConPTY unabhängig testen und gespeicherte Benutzerauswahl kontrollieren.

Die isolierte Testkonfiguration verändert reguläre Einstellungen nicht.
