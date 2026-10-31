# ShellDeck 2.16.8 – POSIX-PTY: lange Paste-Eingaben (Patches 289–290)

## Ursache

`TerminalGridView.paste_clipboard()` liefert beim Paste einen einzelnen
Byte-Block. `PtyTerminalProcess.write()` leitete den Block unter Linux an
`PosixPtyChild.write()` weiter. Dessen Dateideskriptor ist `O_NONBLOCK`, und
`os.write()` darf daher auch nur **einen Teil** des Blocks akzeptieren oder
`EAGAIN` melden. Der Rueckgabewert wurde im PTY-Prozess nicht vollstaendig
abgearbeitet. Ein fehlendes Ende (`PY`) eines Heredocs laesst Bash auf weitere
Eingaben warten. Das passt zum beobachteten Fehler bei 234 Zeilen.

## Korrektur

* Nur POSIX-PTY: Bytegenaue FIFO-Warteschlange fuer alle Eingaben, keine
  Umkodierung der Benutzereingabe, keine Datenprotokollierung.
* Der Qt-GUI-Thread sendet hoechstens 256 Byte je Timer-Schritt (8 ms);
  er blockiert nicht auf langsame Terminalprogramme.
* Teil-Schreibvorgaenge, `EAGAIN` und `EINTR` bleiben erhalten und werden
  spaeter erneut versucht. Reihenfolge und UTF-8-Bytes bleiben erhalten.
* Maximal 32 MiB Warteschlange (keine unbeschraenkte Speichernutzung).
  Bei Ueberschreitung wird der neue Block komplett abgewiesen und ein
  Schreibfehler gemeldet, nicht stillschweigend abgeschnitten.
* Ctrl+C loescht eine noch laufende grosse Eingabe. Wenn zuvor eine
  Bracketed-Paste-Markierung angefangen wurde, wird sie vor Ctrl+C
  geschlossen, damit Readline das Steuerzeichen verarbeiten kann.
* Beim Start, Ende und Schliessen einer PTY-Sitzung werden alte Daten
  verworfen, damit sie nicht in die naechste Shell gelangen.
* ConPTY-/Windows- und QProcess-Pfade werden nicht veraendert.

Die `write()`-Rueckgabe meldet im POSIX-PTY bei grossen Eingaben die
**zur asynchronen Uebertragung angenommenen** Bytes, nicht die schon vom
Terminalprogramm abgeholten Bytes. Ein Schreibfehler waehrend des Drains
wird ueber `errorOccurred(WriteError)` gemeldet.

## Automatisierte Tests

Im Projektverzeichnis, mit aktivierter Projekt-Python-Umgebung:

```bash
PYTHONPATH=src QT_QPA_PLATFORM=offscreen python3 -m pytest -q \
  src/test_shelldeck_pty_paste_290.py \
  src/test_shelldeck_key_encoding.py \
  src/test_shelldeck_pty_backpressure.py \
  src/test_shelldeck_posix_pty_raw_input_090.py
```

Der neue Test umfasst echte POSIX-PTY-Schreib-/Lesevorgaenge mit 234 Zeilen,
Pastes mit 234/1.000/10.000 Zeilen, kurze Writes, Teil-Writes, EAGAIN,
FIFO-Reihenfolge, Ctrl+C und die Speichergrenze. Fuer den kompletten
GUI-Test wird PySide6 benoetigt; die neuen Tests sind absichtlich ohne
PySide6 lauffaehig.

## Manueller Akzeptanztest auf Ubuntu

1. ShellDeck starten, "PTY/ConPTY – interaktiv" waehlen und eine neue
   Bash-Sitzung oeffnen.
2. Erst kurze Befehle und dann den urspruenglichen Python-Heredoc mit 234
   Zeilen bzw. dem groesseren Base64/LZMA-Block einfuegen.
3. Die letzte `PY`-Zeile muss ankommen und der Befehl nach Enter normal
   enden. Bei deinem Skript muessen beide SHA-256-Pruefungen erfolgreich
   sein und die ZIP im Downloads-Ordner erstellt werden.
4. Noch einen grossen Block einfuegen und waehrend der Uebertragung Ctrl+C
   druecken. Die Shell muss danach weitere Eingaben akzeptieren.
5. QProcess-Modus sowie andere Terminaltabs separat pruefen.

Das automatisierte Ergebnis hier belegt die korrigierte Byte-Uebertragung;
eine GUI-Abnahme in der Benutzerinstallation ist weiterhin erforderlich.
