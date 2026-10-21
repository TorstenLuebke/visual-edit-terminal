# ShellDeck – Vorbefehle und plattformübergreifende Befehle (Patches 265–267)

- Die Vorbefehlsfunktion ist **allgemein**: normale Shell-Befehle werden im
  PTY bei einfachen einzeiligen Anweisungen zusammen mit dem Benutzerbefehl
  als eine Shell-Anweisung gesendet. Damit werden Reihenfolge und Änderungen
  am Shell-Kontext erhalten und Folgebefehle nicht versehentlich als stdin
  eines bereits gestarteten Programms verschickt.
- `cls` unter POSIX wird wie bisher zu `clear` übersetzt. Anders als in
  QProcess wird PTY-`clear` nun an die laufende Shell und deren VT-Emulator
  weitergegeben, statt bloß das Qt-Textfeld zu löschen.
- Unterstützte Shells für die Zusammenfassung: bash, zsh, sh, fish, PowerShell,
  pwsh und cmd. Komplexe Mehrzeiler und ShellDeck-Spezialkommandos nutzen
  weiterhin den bestehenden Pfad. `cls`/`clear` mit Zusatzargumenten wird
  absichtlich nicht pauschal übersetzt.
- Eine vollständige, bidirektionale Übersetzung beliebiger Systembefehle ist
  nicht seriös garantiert: etwa Dateisystem-, Dienst- und Rechtebefehle können
  völlig unterschiedliche Semantik besitzen. Künftige Abbildungen benötigen
  sichere, explizite Regeln und separate Tests pro Plattform.
- **Noch nicht abgedeckt:** Vorbefehle, die selbst interaktiv stdin lesen,
  exotische Shell-Syntax und vollständige Windows-/macOS-Lauftests.

Test: `PYTHONPATH=src .venv/bin/python -m pytest -q src/test_shelldeck_precommands_267.py`
