# ShellDeck – Paketierung & Systemintegration

Dieser Ordner enthält **einbindbare Integrationsbausteine** für die
Systemintegration. Die eigentlichen Distributionspakete (`.deb`, `.rpm`,
`.run`, `.exe`) werden vom vorhandenen Kompiler/Buildprozess erzeugt; die hier
liegenden Dateien werden dort eingehängt.

## Linux

- `linux/shelldeck` – Starter-Wrapper, der als `/usr/bin/shelldeck` installiert
  wird und alle Argumente (`--working-directory`, `--new-tab`, `-e`/`--execute`)
  unverändert weiterreicht. Wird als `x-terminal-emulator`-Alternative
  registriert. Installationspfade im Wrapper bei Bedarf an den Kompiler-Output
  anpassen.
- `linux/shelldeck.desktop` – Desktop-Datei (`Terminal=false`,
  `Categories=System;TerminalEmulator;`). Nach `/usr/share/applications/`.
- `linux/debian/postinst`, `prerm`, `postrm` – Maintainer-Skripte. Sie
  registrieren ShellDeck als **auswählbare** Terminal-Alternative (Priorität 40)
  und entfernen ausschließlich den ShellDeck-Eintrag wieder. Das Standardterminal
  wird nie ungefragt geändert.

### RPM (.spec-Scriptlets)

Für RPM dieselbe Logik als Scriptlets in die `.spec` übernehmen:

```spec
%post
if command -v update-alternatives >/dev/null 2>&1; then
    [ -x /usr/bin/shelldeck ] && \
        update-alternatives --install /usr/bin/x-terminal-emulator \
            x-terminal-emulator /usr/bin/shelldeck 40 || :
fi

%preun
if [ "$1" = 0 ] && command -v update-alternatives >/dev/null 2>&1; then
    update-alternatives --remove x-terminal-emulator /usr/bin/shelldeck || :
fi
```

### Standardterminal auswählen

Die Registrierung setzt ShellDeck **nicht** als Standard. Auswahl durch den
Nutzer:

```sh
sudo update-alternatives --config x-terminal-emulator
```

Dateimanager verhalten sich bei „Terminal hier öffnen“ unterschiedlich. Nur
Dateimanager, die den Systemstandard über `x-terminal-emulator` starten,
übernehmen die Auswahl automatisch (z. B. Caja unter Ubuntu/MATE über die
`x-terminal-emulator`-Einstellung). Andere verwenden ein fest hinterlegtes
Terminal und müssen separat umgestellt werden.

## Windows

- `windows/shelldeck_explorer_integration.iss` – Inno-Setup-Include. Fügt eine
  optionale Aufgabe „In ShellDeck öffnen“ (Ordner, Ordnerhintergrund, optional
  Laufwerke) hinzu. Nur benutzerbezogen (`HKCU\Software\Classes`), mit
  `uninsdeletekey` für saubere Deinstallation. Einbinden im Hauptskript:

```iss
#include "shelldeck_explorer_integration.iss"
```

Die Explorer-Integration macht ShellDeck **nicht** zum nativen
Windows-Standard-Terminalhost. Die Windows-Konsolendelegierung (ConPTY) ist ein
separates Projekt.

## Zur Laufzeit

Dieselbe Integration ist auch direkt aus ShellDeck heraus über
**Einstellungen → Systemintegration…** verfügbar (installieren/entfernen,
Statusanzeige). Die Logik liegt in `src/shelldeck_system_integration.py`.

## ShellDeck Shell in installierten Paketen

Die Rust-Shell ist eine separate Programmdatei und wird nicht automatisch in
ein Nuitka- oder Setup-Paket aufgenommen. Für jedes Zielsystem muss sie mit
dem passenden Rust-Target gebaut und als zusätzliche Paketdatei mitgeliefert
werden:

- Linux: `rust/shelldeck-shell/target/release/shelldeck-shell`
- Windows: `rust/shelldeck-shell/target/release/shelldeck-shell.exe`

Im Installationspaket muss die Datei unter `bin/shelldeck-shell` bzw.
`bin/shelldeck-shell.exe` relativ zum installierten ShellDeck-Programm landen.
Im Setup- bzw. Kompiler-Pro-Projekt daher die jeweilige Release-Datei als
zusätzliche Datei aufnehmen und in den Unterordner `bin` des Anwendungsordners
installieren. Unter Linux muss das Ausführungsrecht erhalten bleiben. Ein
Linux-Build kann nicht als Windows-Binärdatei verwendet werden; die Datei muss
für jedes Betriebssystem separat gebaut werden.

ShellDeck sucht die Rust-Shell zuerst in den App-Verzeichnissen `bin` und
`resources/bin`, danach im Rust-Quellprojekt und zuletzt im `PATH`. Bei einem
Quellstart genügt `cargo build --release` im Ordner `rust/shelldeck-shell`.
Bei einer installierten Version muss die zusätzliche Programmdatei Bestandteil
des Installationspakets sein. Nach dem Hinzufügen die App neu paketieren und
installieren; anschließend erscheint **ShellDeck Shell** in der Backend-Auswahl.

## Gemeinsame Versionsdatei für Kompiler Pro und ShellDeck

Im Projektstamm liegt **`version.txt`**, genau eine Zeile (z. B. `2.16.0`).
In **Setup konfigurieren → Versionsdatei → Auswählen** diese Datei wählen
und optional die automatische Übernahme der Paketversion einschalten.
Die Versionsanzeige in **Hilfe → Über**, F1 und dem Fenstertitel wird von
ShellDeck aus derselben Datei geladen.

**Nuitka-Standalone:** `version.txt` muss zusätzlich als Datendatei neben
dem erzeugten `ShellDeck`-Programm im `.dist`-Ordner enthalten sein, damit
die installierte Anwendung sie zur Laufzeit findet. Prüfen, ob Kompiler Pro
die ausgewählte Versionsdatei tatsächlich mitliefert. Andernfalls die
Datendatei im Buildprozess ergänzen, beispielsweise mit der Nuitka-Option
`--include-data-files=version.txt=version.txt`.

Version in der Datei vor dem Build festlegen und die Anzeigen im installierten
Programm sowie die Paketversion separat kontrollieren. Keine Anpassungen am
System-Python erforderlich.
