# Startdiagnose 277–279: ursprünglichen Tab aufzeichnen

Der Neustart mit Rohdatenaufzeichnung wird **nur** aus dem Kontextmenü eines
bereits existierenden PTY/VT-Tabs ausgelöst. Beim Neustart stellt ShellDeck
die Tabs wieder her. Die ursprünglich gewählte Tab-Position wird ausdrücklich
mitgegeben und nur dieses Terminalgitter darf die einmalige Erlaubnis zum
Aufzeichnen beanspruchen. Andere wiederhergestellte Tabs dürfen sie weder
verbrauchen noch anzeigen.

Die Aufzeichnung startet vor dem PTY-Shell-Start, nicht erst beim ersten Menü.
Der ausgewählte Tab wird nach der Wiederherstellung in den Vordergrund geholt.
Im Gitter erscheint rechts oben `● REC | ■ Stopp`; mit Stopp werden Rohbytes,
Ereignisse sowie Anfangs- und Endmodell in einem privaten Downloads-Unterordner
abgelegt. Das Element ist ein Overlay und verändert keine Terminal-Zellgröße.

Ist der Tab nach dem Neustart nicht mehr als VT-Terminal verfügbar, meldet
ShellDeck dies, statt unbemerkt einen anderen Tab aufzuzeichnen. Die Berechtigung
wird aus der Umgebung entfernt; neue Sitzungen sind ohne ausdrückliche
Bestätigung nicht aufgezeichnet. Diagnose-Rohdaten können vertrauliche
Inhalte enthalten und sind vor Weitergabe zu prüfen.

## Tests

`PYTHONPATH=src .venv/bin/python -m pytest -q src/test_shelldeck_vt_startup_capture_276.py src/test_shelldeck_vt_tab_target_279.py`

Der Zusatztest verwendet bei nicht installiertem Qt die unveränderte
Wiederherstellungsmethode über ihr Python-AST und prüft sieben gespeicherte
Tabs, damit ein „erster Tab“ den Aufnahmeauftrag nicht mehr wegnehmen kann.
Ein echter grafischer Starttest mit allen Tabs bleibt erforderlich.

Diese Serie diagnostiziert den Cursorfehler; sie verändert weder die normale
PTY-Verarbeitung noch die Befehls- und Vorbefehlslogik.
