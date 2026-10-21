# POSIX-PTY: erster Bash-Prompt und Qt-Startgeometrie (Patches 280–282)

## Datengrundlage

Die auf Ubuntu aufgenommene erste ShellDeck-Startdiagnose vom 21.10.2026
enthielt 353 unverkuerzte PTY-Bytes. Das VT-Endmodell zeigte einen sichtbaren
Prompt `((.venv) ) bash-5.3$ ` bei `cursor=(0,0)`. Die Ereignisse zeigen:

- 0 ms: VT-Modell initial 24x80;
- 5 ms: Gitter 2x12; anschliessend `shell_start`;
- 118 ms: Gitter 1x10;
- 119 ms: Gitter 28x32 und schliesslich 58x235.

Die erste Bash-Prompt-Ausgabe wird danach durch CSI-K, CR, CSI-A und weitere
Neuzeichnungen ergaenzt. Der Datenstrom endet mit Rueckschrittzeichen.
Das VT-Modell stellt somit den Cursor entsprechend den empfangenen Bytes dar.
Schnelle SIGWINCH-bedingte Prompt-Neuzeichnungen liessen sich in einer
unabhaengigen Bash-PTY-Sitzung nachstellen; *die letzte Cursorposition ist auf
der Zielplattform Bash 5.3 noch im GUI zu bestaetigen*. Diese Patches sind
keine bestaetigte Heilung des Cursorfehlers.

## Aenderung

Nur der **erste POSIX-PTY-VT-Shellstart** eines Tabs wird verschoben, bis
Terminalgitter und Qt-Layout mindestens 180 ms ohne weitere Aenderung eine
brauchbare Groesse (>=8 Zeilen und >=40 Spalten) melden. Inaktiven Tabs wird
nach 1500 ms ein sicherer Start mit 24x80 Zellen ermoeglicht. Bis eine brauchbare
Qt-Groesse vorliegt, loest ein solches Tab keine Kleinstgroessen-SIGWINCH aus.

Weitere Resize-Events nach dem Shellstart werden wie zuvor weitergereicht.
QProcess, Windows-ConPTY, Vorbefehle und spaetere Shell-Neustarts verwenden
ihre bisherigen Wege. Der automatische ShellDeck-Startbefehl wird bei einem
verzoegerten Start erst nach dem erfolgreichen Prozessstart uebertragen.

Pre-Spawn-Groessenwechsel gelten nicht mehr als angeblich erfolgreiche
PTY-Resizes in den Diagnoseereignissen.

## Tests und GUI-Abnahme

`PYTHONPATH=src python -m pytest -q src/test_shelldeck_first_pty_layout_282.py`

Vor einer Freigabe auf Ubuntu: ShellDeck vollstaendig mit dem vorhandenen
Menuepunkt "ShellDeck neu starten + Startaufzeichnung" starten, nach dem
ersten Prompt OHNE Enter `abc` tippen und pruefen, dass die Zeichen sofort
sichtbar sind und der Cursor hinter dem Prompt und der Eingabe steht.
Nach Stoppen muss die Ereignisliste `shell_start` erst nach der stabilen
Grid-Groesse zeigen; sonst gilt die Korrektur als nicht nachgewiesen.
Auch Eingabe an interaktive Programme, `clear` als Vorbefehl sowie ein Tab-
Wechsel sollten anschliessend getestet werden.
