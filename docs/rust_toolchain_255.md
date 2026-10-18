# Reproduzierbare Rust-Werkzeuge (255)

Die Version 1.99.1 stammt aus dem bestätigten Ubuntu-Test vom 18.10.2026.
Sie gilt nur für `experimental/shelldeck_core/` und wird nicht global gesetzt.
`rustup` kann eine fehlende Toolchain bei Aufruf herunterladen; Installation
nur nach ausdrücklicher Entscheidung. Für Offline-Läufe:

```sh
cd experimental/shelldeck_core
RUSTUP_TOOLCHAIN=1.99.1 cargo test --offline
RUSTUP_TOOLCHAIN=1.99.1 cargo clippy --offline --all-targets -- -D warnings
```

Der Rust-Transport-Prototyp und ShellDeck selbst werden nicht umgestellt.
