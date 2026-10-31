# ShellDeck Patch 286 – VT-Ausgabe beim Fenster-Resize neu umbrechen

## Fehlerbild
Im klassischen QTextEdit-Modus wird bereits angezeigter Fließtext beim Verkleinern
neu angeordnet. Im echten VT-Modus hatte `VtScreen.resize()` bisher lediglich
`pyte.Screen.resize()` aufgerufen. pyte clippt dabei alle Zellen rechts vom neuen
Gitterrand. Die vorhandene `_shelldeck_resize_tails`-Sicherung konnte Zeichen
nur bei erneutem Vergrößern wiederherstellen, erzeugte aber keine neuen Zeilen.

## Änderung
- Normaler VT-Bildschirm: automatische (weiche) Umbrüche werden von echten
  Zeilenwechseln getrennt, erhaltene Zeichen/Zellattribute werden für die neue
  Spaltenzahl umgebrochen, überzählige Zeilen wandern in die begrenzte History.
- Zurückvergrößern kann weich umgebrochene Zeilen wieder zusammenführen.
- Alternate Screen und benutzerdefinierte Scrollregionen bleiben bei ihrem
  adressierbaren Zellraster; dort würde ein Text-Reflow Vollbildprogramme
  (vim, htop, TUI) beschädigen. Für diese Pfade gilt die frühere Sicherung.
- Bisherige und neue `pyte.Char`-Zellen werden unverändert wiederverwendet.
- Der Umbruch-Metadatenspeicher ist begrenzt; History-Reflow verarbeitet bis
  zu 2000 jüngere alte Verlaufszeilen pro Resize.

## Test

```bash
cd ~/Programme/shelldeck   # gegebenenfalls tatsächlichen Projektordner einsetzen
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q \
  src/test_shelldeck_vt_reflow_286.py \
  src/test_shelldeck_resize_preservation_237.py \
  src/test_shelldeck_vt_screen.py \
  src/test_shelldeck_terminal_grid.py
```

Anschließend in ShellDeck: echtes VT-Terminal aktivieren, einen längeren
Prompt/Pfad und eine lange Ausgabe anzeigen lassen, Fenster mehrfach verkleinern
und wieder vergrößern; zusätzlich Shell-Eingabe, `ls`, `vim` und Scrollback prüfen.

## Einschränkungen
Der Patch ist ein gezielter Fix für normale Terminal-Textausgabe, **kein vollwertiger
VT-Reflow für alle Spezialsequenzen**. Komplexe Programme mit absoluter Cursor-
steuerung, exotischen Zeichenzellen und besonders breite Unicode-Grapheme müssen
in einer echten pyte-/Qt-Umgebung getestet werden. Es wird keine neue Bibliothek
eingeführt.
