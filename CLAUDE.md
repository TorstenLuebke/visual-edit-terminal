# Hinweise für Claude (ShellDeck-Projekt)

## Arbeitsvereinbarungen mit Torsten

- **Patches immer im Downloads-Ordner speichern:** Jede gelieferte `.patch`-Datei
  zusätzlich nach `C:\Users\luebk\Downloads` kopieren. Falls der Ordner in der
  Session noch nicht verbunden ist, per `request_cowork_directory` Zugriff auf
  `C:\Users\luebk\Downloads` anfordern.
- Lieferungen (ZIP mit Dateien + echter `.patch`-Datei + Prüfanleitung) wie gewohnt
  zusätzlich bereitstellen.

## Projekt-Kurzinfo

- ShellDeck Terminal: PySide6-App. App-Teil in `src/main.py`; der komplette
  Terminalbereich ist als wiederverwendbares Widget in
  `src/shelldeck_terminal_widget.py` (`ShellDeckTerminalWidget`, Alias
  `TerminalTab`) ausgelagert und wird auch von Visual Edit eingebettet.
- `QAction` immer aus `PySide6.QtGui` importieren.
- Syntaxcheck vor Lieferung: `python -m py_compile src/main.py src/shelldeck_terminal_widget.py`
- Smoke-Test: `cd src && python smoke_test_terminal_widget.py` (offscreen:
  `QT_QPA_PLATFORM=offscreen`).
- Vorsicht: Der Sandbox-Sync kappt gewachsene Dateien gelegentlich am alten
  Byte-Limit — Dateien im Mount vor Verwendung auf Vollständigkeit prüfen
  (Dateiende!), niemals abgeschnittene Mount-Kopien zurückschreiben.
