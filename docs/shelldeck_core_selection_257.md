# Experimentelle Auswahl im ShellDeck Core (257)

`LogicalBuffer::selected_text` arbeitet mit stabilen Zeilen-IDs und
Unicode-Skalarwert-Offsets. Der Bereich ist inklusive Start und exklusiv Ende;
zwischen verschiedenen logischen Zeilen wird `\n` eingefügt. Eine entfernte
Zeile macht den Bereich ungültig. Bildschirm-Resize ändert die Auswahl nicht.

Das ist **kein** vollwertiges VT-Textauswahlsystem: Anzeigezellenbreiten,
Soft-Wrap, Rechteckauswahl, Farben und alternativer Bildschirm fehlen noch.
Die laufende ShellDeck-Anwendung bleibt unverändert.
