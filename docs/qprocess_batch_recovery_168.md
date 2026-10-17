# QProcess-Bash: Wiederanlauf nach Prozessabbruch

Im Modus „Bash: ohne Jobsteuerung“ kann eine nicht gesetzte Variable bei aktiviertem `set -u` den Bash-Prozess beenden. ShellDeck markiert den Verlust der Sitzung; der vorherige Zustand aus exportierten Variablen, Funktionen oder Optionen kann nicht vollständig wiederhergestellt werden.

Über das **Kontextmenü im Terminal** kann die Aktion **„Beendete Bash neu starten…“** aufgerufen werden. Der Neustart erfolgt nur nach ausdrücklicher Bestätigung und nur bei tatsächlich beendetem Prozess. Dabei startet eine neue Bash-Sitzung im bisherigen Tab. ShellDeck verwirft alte Abschlussmarker/Decoder beim Neustart. Es findet kein automatischer Neustart statt.

Der vorherige Arbeitsordner kann vom Tab weiterhin bekannt sein. Dies ist **keine** Wiederherstellung aller früheren Shell-Zustände. Interaktive Eingaben erfordern weiterhin PTY/ConPTY.
