"""Benutzerhilfe zur vorhandenen VT-Diagnose; rein beschreibend, keine Aufnahme."""


def vt_diagnostics_help_section() -> str:
    """Text fuer F1 und den eigenen Menuepunkt (eine gemeinsame Quelle)."""
    return """Terminaldiagnose und Aufzeichnungen (echtes PTY/VT-Terminal)
- Die Funktionen sind im Kontextmenue des VT-Gitters verfuegbar. Normal: Rechtsklick; wenn ein Terminalprogramm die Maus selbst verwendet: Umschalt+Rechtsklick. In QProcess gibt es keine VT-Rohdatenaufzeichnung.
- VT-Diagnose: Modell und Ansicht speichern … erstellt eine .txt-Datei mit dem sichtbaren Terminalmodell und der Cursorhistorie sowie ein .png-Bild der Ansicht. Geeignet zum Vergleich von Modell und Darstellung.
- VT-Rohdatenaufzeichnung starten … zeichnet ab der bewussten Aktivierung eingehende PTY-Ausgabebytes und zugehoerige Ereignisse auf. Vor dem zu untersuchenden Befehl oder Programm einschalten; bereits vergangene Ausgaben koennen nicht nachtraeglich aufgezeichnet werden.
- Solange eine Aufnahme bereitsteht, zeigt das VT-Gitter rechts oben ● REC und daneben ■ Stopp. Der Button beendet die Aufnahme und startet den Speichervorgang. Ist die Grenze erreicht, kann dort noch gespeichert werden.
- ShellDeck neu starten + Startaufzeichnung … fragt zuerst nach, beendet die laufende Anwendung samt Shell-Sitzungen und startet ShellDeck neu. Bereits vor dem Start der ausgewaehlten, wiederhergestellten PTY-Shell beginnt die Aufnahme. Nur der Tab, aus dessen Kontextmenue du den Neustart ausgeloest hast, wird automatisch aufgezeichnet.
- Eine Startaufzeichnung wird durch ■ Stopp automatisch in einem privaten Ordner ShellDeck_Startdiagnose_… unter ~/Downloads gespeichert (falls Downloads vorhanden, sonst im Benutzerverzeichnis). Ein normaler manueller Mitschnitt fragt nach einem Speicherort.
- Die Startdiagnose enthaelt *.bin (PTY-Ausgabebytes), *.meta.txt (Groessen und Status), *_Ereignisse.jsonl (Zeit-/Ablaufinformationen), *_Startmodell.txt und *_Endmodell.txt (VT-Zustaende). Manuelle Mitschnitte besitzen je nach Aufzeichnungsart nicht alle diese Dateien.
- Das Limit je Aufnahme betraegt 4 MiB; bei Erreichen endet die Rohdatenaufnahme automatisch, und die Daten koennen noch gespeichert werden. Es ist keine dauerhafte Hintergrundueberwachung.
- Bei Cursor-/Startfehlern zuerst mit Startaufzeichnung neu starten, den Fehler beobachten, nach Bedarf Zeichen ohne Enter eingeben und ueber ■ Stopp sichern. Bei Problemen waehrend eines laufenden Programms hingegen die manuelle Aufnahme vor dem Start dieses Programms einschalten.
- Datenschutz: Rohbytes, Bildschirmbilder und Modelltexte koennen Passwoerter, Befehle, Ausgaben, Pfade oder andere sensible Inhalte enthalten. Vor dem Weitergeben pruefen; nicht automatisch an VisualEdit oder fremde Dienste uebertragen. Die Aufnahme ist standardmaessig ausgeschaltet.
- Eine Diagnose allein behebt den Fehler nicht. Zum Nachweis einer Korrektur denselben Fall nach der Aenderung erneut ausfuehren und die Ergebnisse vergleichen.
"""
