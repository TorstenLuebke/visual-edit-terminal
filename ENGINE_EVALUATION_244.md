# ShellDeck – Engine-Evaluierung (Stand 2026-10-18)

Status: **Recherche / kein Einbau, keine Lizenzfreigabe**.

## Bevorzugter Kandidat: wezterm-term

- Upstream: https://github.com/wezterm/wezterm/tree/main/term
- Projektangabe: MIT-Lizenz für den Terminal-Crate (Upstream-README).
- Rust-Modell enthält VT-Sequenzverarbeitung, Zellen/Attribute, Scrollback,
  Grafiken und Hyperlinks; **keine GUI und keine PTY-Verwaltung**.
- Integration in ShellDeck erfordert einen separaten nativen Adapter mit einer
  klar versionierten Schnittstelle sowie Build- und Packaging-Tests für Linux,
  Windows 11 und macOS.
- Vor jeglicher Binärauslieferung: genaue Upstream-Revision festlegen,
  Cargo.lock und transitive Lizenzen prüfen, Dateianhänge und native
  Bibliotheken erfassen, Lizenzhinweise mitliefern und Plattform-Builds testen.
- MIT für das Kern-Crate bedeutet **nicht**, dass ungeprüft jede transitive
  Abhängigkeit oder Binärauslieferung freigegeben ist.

## Alternativen

- pyte: bestehende ShellDeck-Referenz, kein Umbau im Prüfstand.
- libghostty-vt: Vergleichsoption, derzeit nicht priorisiert. API und
  konkrete Auslieferungsabhängigkeiten gesondert prüfen.
- ShellDeck Core: langfristig eigener Rust-Kern mit unabhängigem Datenmodell.

## Integrationsregel

Es darf jeweils **nur ein Engine-Kern den aktiven Terminalzustand verwalten**.
Feed, Resize, Snapshot, Eingabe, Scrollback und Auswahl müssen entlang einer
klaren Ownership-Grenze bleiben. Vergleichsadapter dürfen parallel im
Prüfstand laufen, aber niemals dasselbe aktive PTY gleichzeitig steuern.

Quellen: Upstream README https://github.com/wezterm/wezterm/blob/main/term/README.md ;
WezTerm Workspace https://github.com/wezterm/wezterm/blob/main/Cargo.toml .
