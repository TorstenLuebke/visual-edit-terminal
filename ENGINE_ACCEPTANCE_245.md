# ShellDeck Engine-Abnahmekriterien

Vergleiche Engines **nur bei identischem Datensatz, Terminalmaß, Chunking,
Aufwärmphase und Wiederholungszahl**. Nutze `--phases` für getrennte
Zeitmessungen und `--trace-memory` separat, weil Tracing Messungen beeinflusst.

Beispiel: `.venv/bin/python src/shelldeck_engine_bench_241.py --phases --json`.

Funktional erforderlich vor Produktivbetrieb: ISO-8859/UTF-8, breite und
kombinierende Unicode-Zeichen, CSI/OSC, Cursor, SGR, Scrollregionen,
Tabulatorstopps, alternativer Bildschirm, 50.000+ Zeilen, stabile Textauswahl,
Kopieren, Suche, Resize/Reflow ohne unbeabsichtigten Datenverlust, IME,
Bash/PowerShell/Zsh und interaktive Programme. Getrennte Windows-ConPTY-
und Linux/macOS-PTY-Integrationstests sind erforderlich.

Eine schnelle Feed-Messung ist **keine** Freigabe: Renderkosten, tatsächliche
CPU/RSS, Fehler bei Resize und Datensicherheit müssen getrennt bestätigt sein.

Die eigenen Rust-Implementierungen werden zuerst isoliert getestet und erst
nach bestandener Abnahme als optionale Engine eingeführt.
