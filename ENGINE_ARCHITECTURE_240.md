# ShellDeck – Terminal-Engine-Vergleich (Patchserie 240–242)

**Status: experimenteller, separater Prüfstand; keine Umstellung der produktiven PTY-Engine.**

## Ziel

ShellDeck vergleicht drei Entwicklungswege: (A) bestehendes pyte-Modell verbessern,
(B) eigener Terminalkern, perspektivisch Rust, (C) lizenzgeprüfte externe Engine.
Der Vertrag in `src/shelldeck_engine_contract_240.py` trennt die Datenverarbeitung
vom PySide6-Renderer. Er ist ausdrücklich **noch keine vollständige Schnittstelle**
für Reflow, Mausprotokolle, Zellattribute, Auswahl oder Terminalantworten.

## Prüfstand

Unter Linux im Projektverzeichnis:

```bash
.venv/bin/python src/shelldeck_engine_bench_241.py --json
.venv/bin/python -m pytest -v src/test_shelldeck_engine_arch_242.py
```

Die Benchmarks arbeiten auf einem neuen Zustand je Wiederholung. Erfasst werden
Durchlaufzeit des Feed-Vorgangs samt Snapshot/Transcript und Python-tracemalloc-
Peak. `tracemalloc` misst **nicht** den vollständigen nativen Speicherverbrauch,
und die Ergebnisse sind **keine** allgemeinen CPU-/GUI-/Render-Benchmarks.
Auf verschiedenen Maschinen nur bei identischer Laufzeit, Chunk-Größe und
Datensätzen sinnvoll vergleichbar. Der Prüfstand startet keine Shell und
ändert weder Einstellungen noch produktive Terminaldaten.

Andere Adapter können mit `--adapter package:Klasse` getestet werden. Sie müssen
`TerminalEngineContract` implementieren und die Signatur `(rows, columns)`
unterstützen. Es wird **keine** fremde Engine automatisch installiert oder geladen.

## Verpflichtende Abnahme vor einer Umstellung

- VT-Sequenzen, Cursor, Unicode, Farben, interaktive Anwendungen und Alternate Screen.
- Verlustfreier Reflow bzw. definierte Grenzen bei Resize, stabile Scrollback-Auswahl.
- Windows-ConPTY, Linux/macOS-PTY, GUI-Rendering sowie Nuitka-Distribution.
- Wiederholbare Messung von Ausgabe, Scrollen, CPU und Speicher sowie `seq 1 50000`.
- Konkrete Lizenzprüfung **einschließlich transitiver Abhängigkeiten und Auslieferung**.
- Alte Engine bleibt als Rollback verfügbar, bis die neue alle Abnahmekriterien erfüllt.

**Keine Lizenzfreigabe** für libghostty-vt, wezterm-term oder andere Engines
wird durch diese Patchserie behauptet. Der eigene Kern wird unabhängig entwickelt;
Teilersatz ist nur bei klarer Zustands-Eigentümerschaft zulässig.
