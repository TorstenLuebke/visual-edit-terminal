# QProcess-Batch: unerwartetes Ende der Bash (Patch 162)

Diese Ergänzung gehört zur Dokumentation `docs/qprocess_batch_mode.md`.

## Verhalten beim Prozessabbruch

Bei Bash-Fehlern wie `set -u` mit einer nicht gesetzten Variable kann
die dauerhafte Bash-Sitzung enden, bevor sie ihren Abschlussmarker sendet.
Ein ausbleibender Abschlussmarker allein bedeutet daher nicht, dass der
Befehl noch ausgeführt wird.

Nach dem tatsächlichen Prozessende schließt ShellDeck den laufenden Auftrag
ab und zeigt eine Warnung über den Verlust des Shell-Zustands.

## Verlorener Zustand

Nicht in Dateien gespeicherte Shell-Variablen, Funktionen und sonstiger
Sitzungszustand können verloren sein. ShellDeck darf deshalb keinen
unbemerkten Neustart durchführen und den alten Zustand vortäuschen.

Weitere Eingaben werden nicht mehr an den beendeten Prozess gesendet.
Ein Neustart der Shell muss ausdrücklich ausgelöst werden.

Beim Neustart werden alte Abschlussmarker- und Decoderzustände verworfen.
