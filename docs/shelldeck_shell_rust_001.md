# ShellDeck Rust Shell — Grundgerüst (Patch 295)

## Ziel dieses Schritts

Der erste Shell-Kern liegt als eigenständiges Cargo-Projekt unter
`rust/shelldeck-shell`. Er ist von Qt und der ShellDeck-Oberfläche unabhängig.
Die Bibliothek definiert `ShellEngine` und das Host-Interface `ShellHost`; eine
kleine CLI dient als erster Host. ShellDeck selbst bleibt in diesem Schritt
unverändert.

## Befehle aus Patch 295

- `cd`, `pwd`, `help`, `history`, `clear` und `exit`
- Start installierter Programme ohne zwischengeschaltete System-Shell
- Einfache Argumente mit einfachen oder doppelten Anführungszeichen
- Keine externen Cargo-Abhängigkeiten

## Erweiterungen aus Patch 296

- `echo [-n] TEXT...`
- `set NAME=WERT` und `unset NAME`; `$NAME` und `${NAME}` werden expandiert,
  interne Variablen werden gestarteten Programmen als Umgebungswerte übergeben
- `cd -` wechselt zum vorherigen Verzeichnis; `history -c` leert die Sitzungshistorie
- `ls`/`dir` (`-a`), UTF-8-`cat` und `mkdir` (`-p`)
- Dateisystem- und Prozesszugriffe bleiben hinter `ShellHost`, damit andere Hosts
  dieselbe Rust-Bibliothek mit eigenen Ausgabekanälen und Prozessadaptern nutzen
  können

## Erweiterungen aus Patch 297

- Pipes mit `|`; mehrere externe Programme laufen direkt über Betriebssystem-Pipes
- Eingabe mit `<`, Ausgabe mit `>` oder `>>`, Fehlerausgabe externer Programme mit
  `2>` oder `2>>`
- Pipefähige eingebaute Befehle: `echo`, `pwd`, `help`, `history`, `set` ohne
  Zuweisung, `ls`/`dir` und `cat`; `cat` kann Pipe-Eingabe übernehmen
- Zustandsändernde Befehle wie `cd`, `set NAME=WERT`, `unset` und `exit` werden
  innerhalb einer Pipe abgewiesen, damit der Shell-Zustand eindeutig bleibt
- Eingabeumleitung gilt für die erste Stufe, Ausgabeumleitung für die letzte
  Stufe; Fehlerumleitungen gelten für die jeweilige externe Programmstufe
- Der `ShellHost` stellt dafür bytebasierte Dateioperationen und eine
  Prozess-Pipeline-Schnittstelle bereit

## Erweiterungen aus Patch 298

- `source DATEI` und `. DATEI` führen ein UTF-8-Skript im aktuellen
  `ShellEngine` aus; Variablen und Verzeichniswechsel bleiben bestehen
- Verschachtelte `source`-Aufrufe sind bis zu 32 Ebenen möglich
- Leerzeilen und vollständige Kommentarzeilen, die mit `#` beginnen, werden
  übersprungen; bei einem Fehler stoppt das Skript mit Datei- und Zeilenangabe
- Skriptzeilen nutzen denselben Parser, dieselben Befehle, Pipes und Umleitungen
  wie interaktive Eingaben
- Kontrollfluss (`if`, Schleifen), Skriptargumente und Funktionen folgen später

## Erweiterungen aus Patch 299

- Externe Programme und rein externe Pipes können mit `&` im Hintergrund
  gestartet werden
- `jobs` zeigt laufende und abgeschlossene, noch nicht abgerufene Jobs
- `wait [JOB_ID]` wartet auf einen Job oder auf alle aktuellen Jobs; erfolgreich
  abgewartete Einträge werden aus der Jobliste entfernt
- Die Jobverwaltung liegt beim `ShellHost`; Hosts ohne Job-Unterstützung behalten
  durch Standardmethoden ihre Kompatibilität und melden die Funktion als nicht
  unterstützt
- Hintergrundprozesse erhalten standardmäßig keine interaktive Eingabe; Ausgabe
  wird geerbt, sofern sie nicht umgeleitet ist
- Interaktive Terminalsteuerung, Vordergrundübernahme, Stoppen/Fortsetzen,
  Signale und vollständige PTY/ConPTY-Jobkontrolle folgen später

## Erweiterungen aus Patch 300

- `;` führt mehrere Befehle oder Pipes nacheinander aus; ein einzelnes `;` am
  Ende der Zeile ist zulässig
- Shell-Zustand wie Verzeichnis und Variablen bleibt zwischen Teilbefehlen
  erhalten
- Ein externer Befehl mit Exitcode ungleich null verhindert den nächsten
  Teilbefehl nicht; `exit` beendet die Folge sofort
- Die gesamte Zeile wird vor der Ausführung geparst, damit Syntaxfehler in einem
  späteren Teilbefehl keine vorherigen Befehle ausführen
- Kontrollstrukturen (`if`, Schleifen), `&&` und `||` bleiben späteren Schritten
  vorbehalten

## Erweiterungen aus Patch 301

- `&&` führt den nächsten Befehl nur aus, wenn der letzte ausgeführte Befehl
  Status 0 geliefert hat
- `||` führt den nächsten Befehl nur bei einem Status ungleich 0 aus
- Übersprungene Befehle ändern den gespeicherten Status nicht; dadurch verhalten
  sich gemischte Folgen wie `false && echo nein || echo ja` linksassoziativ
- `;` setzt die Bedingung zurück und führt den nächsten Befehl immer aus
- Die gesamte Zeile einschließlich aller Bedingungen wird vor der Ausführung
  geparst; `exit` beendet die Folge weiterhin sofort
- `if`, Schleifen, `2>&1` und interaktive Jobsteuerung bleiben offen

## Erweiterungen aus Patch 302

- `true` und `false` liefern plattformübergreifend die Statuswerte 0 und 1
- `exit [STATUS]` akzeptiert Statuswerte von 0 bis 255; ohne Argument wird der
  Status des zuletzt ausgeführten Befehls verwendet
- Die eigenständige CLI gibt den gewählten Status als Prozess-Exitcode zurück
- `true` und `false` sind auch als Pipeline-Stufen verwendbar

## Noch offen

Persistente History, Autovervollständigung und der PTY/ConPTY-Prozessadapter
folgen in späteren Schritten. Externe Programme
innerhalb eines zusammenhängenden Pipeline-Abschnitts werden über OS-Pipes
verbunden. Beim Übergang zwischen externen Programmen und eingebauten Befehlen
wird der Zwischenstrom im Speicher gehalten. Variablen expandieren in unquoted
und doppelten Anführungszeichen; einfache Anführungszeichen unterdrücken die
Expansion. Shell-Variablen werden an gestartete Programme weitergegeben.
`ls -a` behandelt Namen mit führendem Punkt portabel als verborgen.

Das Modul ist noch keine Ablösung der bestehenden Shell und noch nicht mit
ShellDecks Oberfläche verbunden. Interaktive Programme wie Vim benötigen dort
den späteren PTY/ConPTY-Adapter.

## In VisualEdit bauen

1. Rust mit Cargo auf dem Entwicklungsrechner installieren.
2. In VisualEdit den Ordner `rust/shelldeck-shell` als Projekt öffnen; dort
   liegt die `Cargo.toml`.
3. Im VisualEdit-Terminal in diesem Ordner `cargo check` ausführen.
4. Für die ausführbare Datei `cargo build` ausführen. Sie liegt anschließend
   unter `target/debug/shelldeck-shell` (Windows: `shelldeck-shell.exe`).
5. Zum Start `cargo run` verwenden.

VisualEdit erkennt `.rs`-Dateien und Cargo-Projekte. Der vorhandene Cargo-
Prüfadapter verwendet `cargo check` und `cargo test`; `cargo build` wird für
die Erzeugung der ausführbaren Datei im integrierten Terminal gestartet. Die
jeweilige Rust-/Cargo-Installation muss für VisualEdit im `PATH` verfügbar
sein.

## Prüfstatus

Patch 302 baut auf Patch 301 auf. Die Patch-Anwendung und das ZIP wurden geprüft.
In dieser Umgebung sind `rustc` und `cargo` nicht installiert; deshalb war kein
Kompilieren möglich. Es wurden keine Tests hinzugefügt oder ausgeführt.

## Korrektur in Patch 303

Der vom Nutzer ausgeführte cargo check meldete, dass die CLI last_child
veränderbar binden muss, weil Child::wait() eine mutable Referenz benötigt.
Die Bindung wurde korrigiert. Außerdem wurde der unbenutzte OsStr-Import
entfernt. Patch 303 baut auf Patch 302 auf. Nach dem Einspielen cargo check
erneut ausführen. Anschließend bestätigte der Nutzer einen sauberen cargo check
ohne Fehler und Warnungen.

## Erweiterung in Patch 304

- Skripte unterstützen jetzt verschachtelte `if BEFEHL; then`-Blöcke mit
  optionalem `else` und abschließendem `fi`.
- Der Zweig wird anhand des Status des Bedingungsbefehls gewählt: Status 0 gilt
  als erfolgreich, jeder andere Status als nicht erfolgreich.
- Die `then`-Angabe muss auf derselben Zeile wie `if` stehen. Ein fehlendes
  `fi`, ein überzähliges `else` oder ein `else`/`fi` ohne `if` wird mit
  Dateiname und Zeilennummer gemeldet.
- Die Steuerwörter gelten vorerst nur innerhalb von `source`-Skripten. Schleifen,
  `elif`, Skriptargumente und Funktionen bleiben spätere Schritte.

Patch 304 baut auf Patch 303 auf. `cargo` war in der Erstellungsumgebung nicht
verfügbar. Der Nutzer bestätigte anschließend, dass `cargo check` für Patch 304
ohne Fehler und Warnungen durchlief. Es wurden keine Tests hinzugefügt oder
ausgeführt.

## Erweiterung in Patch 305

- `elif BEFEHL; then` kann zwischen `if` und `else` beliebig oft vorkommen.
- Bedingungen werden der Reihe nach geprüft; nach dem ersten Status 0 werden
  weitere `elif`-Befehle übersprungen.
- `elif` nach `else` und `elif` ohne passendes `if` werden mit Dateiname und
  Zeilennummer gemeldet.
- Die `then`-Angabe muss weiterhin auf derselben Zeile wie `if` oder `elif`
  stehen. Schleifen, Skriptargumente und Funktionen folgen später.

Patch 305 baut auf Patch 304 auf. Beim anschließenden `cargo check` meldete der
Compiler E0106 an `script_condition`: Der Rückgabewert war nicht eindeutig an
seinen Eingabeparameter gebunden. Patch 306 verknüpft die Rückgabe explizit mit
der Lebensdauer von `command`. Der Korrekturpatch wurde hier nicht kompiliert;
es wurden keine Tests hinzugefügt oder ausgeführt.

## Korrektur in Patch 306

Die Signatur von `script_condition` bindet den zurückgegebenen Textausschnitt
jetzt an die Eingabe `command`. `keyword` wird nur zum Suchen des Präfixes
verwendet und bestimmt nicht die Lebensdauer der Rückgabe. Patch 306 baut auf
Patch 305 auf. Der Nutzer bestätigte anschließend einen erfolgreichen
`cargo check` ohne Fehler.

## Erweiterung in Patch 307

- `source DATEI [ARGUMENT ...]` übergibt Skriptargumente.
- Innerhalb des Skripts stehen `$1` bis `$9`, `${10}` und höhere Indizes sowie
  `$#` für die Anzahl der übergebenen Argumente bereit.
- Ein verschachteltes `source` erhält eigene Argumente und stellt nach der
  Rückkehr die Argumente des aufrufenden Skripts wieder her.
- Erweiterte Werte werden in das aktuelle Wort eingesetzt. Eine Wertzeichenfolge
  mit Leerzeichen wird nicht in mehrere Argumente zerlegt.

Patch 307 baut auf Patch 306 auf. Der Nutzer bestätigte anschließend einen
erfolgreichen `cargo check` ohne Fehler. Es wurden keine Tests hinzugefügt oder
ausgeführt.

## Erweiterung in Patch 308

- `shift [ANZAHL]` entfernt führende Skriptargumente; ohne Anzahl wird eines
  entfernt, mit `shift 0` keines.
- Wird eine größere Anzahl als die verfügbare Argumentliste angefordert, meldet
  die Shell den Fehler über stderr, liefert Status 1 und lässt die Liste
  unverändert. Das Skript kann den Status mit `||` oder `if` behandeln.
- Die Argumentliste eines aufrufenden Skripts wird nach einem verschachtelten
  `source` weiterhin wiederhergestellt.

Patch 308 baut auf Patch 307 auf. Der Nutzer bestätigte anschließend einen
erfolgreichen `cargo check` ohne Fehler. Es wurden keine Tests hinzugefügt oder
ausgeführt.

## Erweiterung in Patch 309

- `for NAME in WERTE...; do` führt den Skriptblock bis zur alleinstehenden
  Zeile `done` für jeden Wert aus. Die Werteliste wird vor Beginn einmal
  ausgewertet; der Schleifenname bleibt nach dem Ende auf dem letzten Wert.
- Schleifen dürfen bis zu 64 Ebenen verschachtelt werden. Eine leere Liste führt
  den Block nicht aus. `while`, `break` und `continue` sind noch nicht enthalten.
- Die Schleife funktioniert nur in `source`-Skripten. Der `for`-Kopf muss die
  Form `for NAME in WERTE...; do` haben; Quoting und Variablenexpansion nutzen
  den bestehenden Shell-Parser.

Patch 309 baut auf Patch 308 auf. `cargo` war in der Erstellungsumgebung nicht
verfügbar; der Patch wurde deshalb nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Korrektur der Patchbasis für Patch 309

Der Ersatz-Diff wurde gegen den bereitgestellten ShellDeck-Quellstand erstellt,
der Patch 308 entspricht. Die zuerst gelieferte Diff-Datei enthielt versehentlich
Änderungen aus Patch 308 und wurde deshalb vom PatchZipEinspieler als Konflikt
erkannt. Dieser angepasste Patch enthält nur die Schleifenerweiterung aus
Patch 309.

## Erweiterung in Patch 310

- `break` beendet die innerste aktive `for`-Schleife; `continue` beginnt deren
  nächste Iteration. Beide Befehle erwarten keine Argumente und funktionieren
  auch in `if`-Blöcken sowie aus einem verschachtelt eingebundenen `source`-Skript.
- Außerhalb einer laufenden `for`-Schleife oder mit Argumenten melden die Befehle
  einen Skriptfehler mit Dateiname und Zeilennummer. `while`-Schleifen sind nicht
  Teil dieses Patches.

Patch 310 baut auf Patch 309 auf. Der Nutzer bestätigte für Patch 309 nach dem
Einspielen einen erfolgreichen `cargo check`. `cargo` ist in der Erstellungsumgebung
nicht verfügbar; Patch 310 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 311

- `while BEFEHL; do` prüft den Befehl vor jedem Schleifendurchlauf. Bei einem
  Status ungleich 0 endet die Schleife. `break` und `continue` steuern die
  innerste aktive Schleife, also auch eine `while`-Schleife.
- `for`- und `while`-Blöcke lassen sich ineinander verschachteln und gemeinsam
  bis zu 64 Ebenen tief verwenden. Ein fehlendes `done` wird mit Dateiname und
  Zeilennummer des geöffneten Blocks gemeldet.

Patch 311 baut auf Patch 310 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 311 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Korrektur in Patch 312

`cargo check` meldete für Patch 311 eine Zuweisung an `last_result`, die vor dem
Überschreiben nicht verwendet wurde. Patch 312 entfernt diese Initialisierung;
der Schleifenstatus wird weiterhin nach der Ausführung der `while`-Schleife
gesetzt. Der Nutzer bestätigte, dass Patch 311 kompiliert, aber diese Warnung
ausgibt. Patch 312 wurde hier nicht kompiliert.

## Erweiterung in Patch 313

- Die eingebauten Befehle `test` und `[ AUSDRUCK ]` liefern Status 0 für wahr
  und 1 für falsch. Unterstützt werden nichtleere Zeichenketten, `-n`, `-z`,
  Zeichenkettenvergleiche `=`/`==` und `!=` sowie Ganzzahlvergleiche `-eq`, `-ne`,
  `-lt`, `-le`, `-gt` und `-ge` mit vorangestelltem `!` zur Negation.
- Ganzzahlen müssen in den Bereich eines vorzeichenbehafteten 64-Bit-Werts passen.
  Die Kurzform `[` erfordert das abschließende Token `]`. Dateiprüfungen sowie
  zusammengesetzte Testoperatoren `-a` und `-o` sind nicht enthalten; dafür kann
  die Shell-Verkettung `&&` und `||` verwendet werden.
- Beide Befehle sind plattformunabhängige Shell-Built-ins und können in Pipes
  verwendet werden. Ungültige Ausdrücke und ungültige Ganzzahlen werden als
  Parsefehler gemeldet.

Patch 313 baut auf Patch 312 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 313 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 314

- `test` und `[ ... ]` unterstützen jetzt mehrere Ausdrücke mit `-a` (UND) und
  `-o` (ODER). `-a` bindet stärker als `-o`; vorangestelltes `!` negiert den
  folgenden atomaren Ausdruck.
- Gruppierungsklammern und Dateiprüfungen bleiben außerhalb des Umfangs. Für
  gruppierte Kommandobedingungen stehen `&&` und `||` zur Verfügung.

Patch 314 baut auf Patch 313 auf. Die Datei `lib.rs` wurde in der
Erstellungsumgebung nicht kompiliert. Es wurden keine Tests hinzugefügt oder
ausgeführt.

## Erweiterung in Patch 315

- `printf FORMAT [WERT ...]` schreibt formatierte Ausgabe ohne automatischen
  Zeilenumbruch. Unterstützt werden `%s`, `%d`, `%i`, `%u`, `%x`, `%X`, `%o`,
  `%c` und `%%` sowie die Format-Escapes `\\n`, `\\r`, `\\t` und `\\\\`.
- Wenn nach einem Durchlauf weitere Werte übrig sind, wird das Format erneut
  ausgewertet. Formatbreite, Genauigkeit und Flags gehören nicht zum Umfang.
  Ungültige Konvertierungen und ungültige Zahlen werden als Parsefehler gemeldet.

Patch 315 baut auf Patch 314 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 315 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Vorbereitung in Patch 316

- `ShellHost` erhält die optionale Methode `path_kind`, die `File`, `Directory`,
  `Other` oder `None` für einen nicht vorhandenen Pfad zurückgibt. Die Methode
  hat eine Standardimplementierung mit `Unsupported`, damit bestehende Hosts
  nicht sofort angepasst werden müssen.
- Der CLI-Host verwendet `std::fs::metadata`; Fehler außer `NotFound` werden
  weitergereicht. Die Shell-Built-ins verwenden die neue Schnittstelle im
  folgenden Patch.

Patch 316 baut auf Patch 315 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 316 wurde hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 317

- `test -e PFAD` prüft, ob ein Pfad vorhanden ist; `-f` erkennt reguläre Dateien
  und `-d` Verzeichnisse. Relative Pfade werden gegen das aktuelle Arbeits-
  verzeichnis aufgelöst; `~` wird wie bei anderen Dateibefehlen expandiert.
- Der CLI-Host nutzt `std::fs::metadata`. Bestehende Hosts funktionieren weiter,
  melden die Dateioperatoren aber als nicht unterstützt, solange sie
  `ShellHost::path_kind` nicht implementieren. Andere Metadatenfehler werden
  angezeigt statt als „nicht vorhanden“ verschluckt.

Patch 317 baut auf Patch 316 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 317 wurde hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 318

- `$((AUSDRUCK))` wertet einen vorzeichenbehafteten 64-Bit-Ganzzahlausdruck aus
  und setzt das Ergebnis in das aktuelle Argument ein. Unterstützt werden
  Variablen, Klammern, unäres `+`/`-` sowie `+`, `-`, `*`, `/` und `%` mit
  üblicher Rechenpriorität. Variablen aus Shell-Variablen und Umgebung werden
  gelesen; nicht gesetzte oder leere Werte gelten als 0.
- Nichtnumerische Werte, Division/Modulo durch null, Überläufe, fehlerhafte
  Ausdrücke und Verschachtelungen über 64 Ebenen werden als Parsefehler gemeldet.
  Die Expansion führt selbst keine Variablenzuweisung aus.

Patch 318 baut auf Patch 317 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 318 wurde hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 319

- `let NAME=AUSDRUCK [NAME=AUSDRUCK ...]` wertet die Ausdrücke nacheinander aus
  und speichert jedes Ergebnis als Shell-Variable. Spätere Zuweisungen sehen
  frühere Änderungen desselben Aufrufs.
- Der Rückgabestatus ist 0, wenn der letzte Ausdruck ungleich 0 ist, andernfalls
  1. Das lässt sich mit `if`, `&&` und `||` auswerten. `let` verändert den
  Shell-Zustand und ist deshalb nicht als Pipe-Stufe verfügbar.

Patch 319 baut auf Patch 318 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 319 wurde hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 320

- `return [STATUS]` beendet das aktuell ausgeführte `source`-Skript vorzeitig.
  Der Status kann zwischen 0 und 255 liegen; ohne Angabe wird der Status des
  vorherigen Befehls zurückgegeben.
- Ein verschachteltes `source` hat seinen eigenen Rücksprungpunkt. `return`
  darin beendet nur das innere Skript und setzt das aufrufende Skript fort.
  `return` außerhalb eines Skripts wird als Fehler gemeldet.

Patch 320 baut auf Patch 319 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 320 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 321

- Sourced Skripte können mehrzeilige Funktionen mit `NAME() {` und einer
  alleinstehenden schließenden `}` definieren. Definitionen bleiben im
  `ShellEngine` verfügbar und lassen sich interaktiv oder aus anderen Skripten
  mit Argumenten aufrufen.
- Während eines Funktionsaufrufs bezeichnen `$1` bis `${10}` und `$#` die
  Funktionsargumente. Nach der Rückkehr werden die Argumente des Aufrufers
  wiederhergestellt. `return [STATUS]` beendet die aktuelle Funktion; ohne
  Status wird der letzte Befehlsstatus zurückgegeben. Funktionen teilen sich
  Variablen und Arbeitsverzeichnis mit ihrem Aufrufer.
- Funktionsnamen dürfen keine eingebauten oder reservierten Befehle ersetzen.
  Funktionsaufrufe können nicht als Pipe- oder Hintergrundstufe laufen und die
  Aufrufzeile kann nicht umgeleitet werden. Lokale Variablen und einzeilige
  Funktionsdefinitionen sind nicht enthalten.

Patch 321 baut auf Patch 320 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 321 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 322

- `local NAME[=WERT] ...` legt Variablen im aktuellen Shell-Funktionsaufruf an.
  Vorherige Werte werden während des Aufrufs verdeckt und danach wiederhergestellt;
  Variablen, die vorher nicht gesetzt waren, werden nach der Rückkehr entfernt.
- Wiederholte lokale Deklarationen innerhalb derselben Funktion behalten den
  ursprünglichen Wert für die spätere Wiederherstellung. Verschachtelte
  Funktionen erhalten eigene lokale Bereiche. Außerhalb einer Funktion ist
  `local` ein Fehler.

Patch 322 baut auf Patch 321 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 322 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 323

- `read [NAME ...]` liest eine UTF-8-Zeile über den Shell-Host. Ohne Namen wird
  `REPLY` gesetzt. Bei mehreren Namen werden durch Leerraum getrennte Felder
  zugewiesen; die letzte Variable erhält die übrigen Felder, verbunden mit
  einfachen Leerzeichen. Backslashes bleiben unverändert.
- EOF liefert Status 1 und lässt Variablen unverändert. Mit `< DATEI` wird die
  erste UTF-8-Zeile der Eingabedatei gelesen. Pipes mit `read` sind noch nicht
  unterstützt.
- `ShellHost::read_input_line` erhält eine Standardimplementierung mit
  `Unsupported`, damit bestehende Hosts weiterhin kompilieren. Der CLI-Host liest
  eine Zeile von der Konsole.

Patch 323 baut auf Patch 322 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 323 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 324

- `$?` und `${?}` expandieren zu dem Status, den der letzte ausgeführte Befehl
  vor dem Einlesen der aktuellen Befehlszeile zurückgegeben hat. Damit kann ein
  Skript den Status auf einer folgenden Zeile ausgeben oder weiterverarbeiten.
- Die Expansion erfolgt wie die übrigen Variablenexpansionen beim Parsen der
  ganzen Eingabezeile. Ein Status, der erst durch einen früheren Befehl derselben
  Zeile entsteht, steht deshalb innerhalb dieser Zeile noch nicht bereit.

Patch 324 baut auf Patch 323 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 324 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 325

- Sourced Skripte können `case WERT in`-Blöcke mit `MUSTER)`-Kopfzeilen,
  alleinstehenden `;;`-Abschlüssen und einem alleinstehenden `esac` ausführen.
  Mehrere Alternativen lassen sich mit `|` angeben. Der erste Treffer wird
  ausgeführt; `*` dient als Catch-all.
- Muster unterstützen `*` für beliebig viele Zeichen und `?` für genau ein
  Unicode-Zeichen. Zeichenklassen, Fall-through und Inline-Zweige sind nicht
  enthalten; Anführungszeichen machen Wildcard-Zeichen noch nicht wörtlich.
  Fehlende `esac`- oder `;;`-Abschlüsse werden als Skriptfehler gemeldet.

Patch 325 baut auf Patch 324 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 325 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 326

- `${NAME-WERT}` fügt `WERT` ein, wenn die Variable nicht gesetzt ist.
  `${NAME:-WERT}` verwendet den Standardwert zusätzlich bei einer leeren
  Variable. Das gilt auch für Positionsparameter und Umgebungsvariablen.
- Der Standardwert wird wörtlich eingefügt; weitere Variablenexpansion darin
  findet nicht statt. Zuweisungsformen wie `${NAME:=WERT}` sind nicht enthalten.

Patch 326 baut auf Patch 325 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 326 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 327

- `${NAME+WERT}` fügt `WERT` ein, wenn die Variable gesetzt ist;
  `${NAME:+WERT}` verlangt zusätzlich einen nichtleeren Wert. Andernfalls
  expandieren beide Formen zu einer leeren Zeichenkette.
- Der Alternativtext wird wörtlich übernommen und nicht weiter expandiert.
  Damit deckt die Shell nun die einfachen `-`, `:-`, `+` und `:+` Formen ab;
  Zuweisungs- und Fehlermeldungsoperatoren bleiben offen.

Patch 327 baut auf Patch 326 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 327 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 328

- `${NAME?MELDUNG}` bricht die Auswertung der aktuellen Eingabezeile mit der
  Meldung ab, wenn `NAME` nicht gesetzt ist. Eine leere Meldung erzeugt einen
  Standardhinweis. Der Meldungstext wird wörtlich übernommen; Expansionen darin
  werden nicht ausgeführt.
- Fehler bei Variablenexpansionen werden wie Parsefehler zurückgegeben und
  verhindern, dass ein Teil der betroffenen Zeile ausgeführt wird.

Patch 328 baut auf Patch 327 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 328 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 329

- `${NAME:?MELDUNG}` behandelt zusätzlich einen gesetzten, aber leeren Wert als
  fehlend. Bei nichtleerer Meldung wird sie wörtlich ausgegeben; andernfalls
  nennt der Standardhinweis die Variable und weist auf den leeren Wert hin.
- Die Prüfung funktioniert ebenso für Positions- und Umgebungsvariablen.

Patch 329 baut auf Patch 328 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 329 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 330

- `${#NAME}` liefert die Anzahl der Unicode-Zeichen des Variablenwertes; eine
  nicht gesetzte Variable hat die Länge null. `${#}` bleibt die Anzahl der
  Skriptargumente.

Patch 330 baut auf Patch 329 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 330 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 331

- `${NAME#MUSTER}` und `${NAME##MUSTER}` entfernen das kürzeste beziehungsweise
  längste passende Präfix. `${NAME%MUSTER}` und `${NAME%%MUSTER}` entfernen das
  kürzeste beziehungsweise längste passende Suffix.
- Die Muster folgen den vorhandenen `case`-Regeln: `*` steht für beliebig viele
  Unicode-Zeichen, `?` für genau ein Unicode-Zeichen. Andere Glob-Syntax wie
  Zeichenklassen ist nicht enthalten.

Patch 331 baut auf Patch 330 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 331 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 332

- Ein unquotiertes `~` am Wortanfang wird zum vom Host bereitgestellten
  Home-Verzeichnis. `~/PFAD` und `~\PFAD` übernehmen den Rest des Pfades.
- `~BENUTZER` wird nicht aufgelöst. Wenn der Host kein Home-Verzeichnis liefert,
  bleibt die Tilde unverändert. Innerhalb von Anführungszeichen wird nicht
  expandiert.

Patch 332 baut auf Patch 331 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 332 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 333

- Ein unquotiertes `~+` am Wortanfang wird zum aktuellen Arbeitsverzeichnis des
  Hosts. `~+/PFAD` übernimmt den Pfadrest; `~+NAME` bleibt unverändert.
- Die Erweiterung benötigt keine neue Host-Schnittstelle und bleibt innerhalb
  von Anführungszeichen deaktiviert.

Patch 333 baut auf Patch 332 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 333 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 334

- Ein unquotiertes `~-` am Wortanfang wird zum vorherigen Arbeitsverzeichnis;
  `~-/PFAD` übernimmt den Pfadrest. Ohne vorherigen Verzeichniswechsel bleibt
  die Tilde unverändert.
- Die Shell reicht den bisherigen Verzeichniskontext auch an die Expansionen in
  Skriptkopfzeilen und `case`-Mustern weiter.

Patch 334 baut auf Patch 333 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 334 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 335

- `cd -` wechselt zum vorherigen Verzeichnis und schreibt nach erfolgreichem
  Wechsel den Zielpfad nach stdout.

Patch 335 baut auf Patch 334 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 335 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 336

- `pushd PFAD` wechselt in das Verzeichnis und legt das vorherige Verzeichnis
  auf einem internen Stack ab. `pushd` ohne Argument tauscht mit dem letzten
  Stackeintrag oder, wenn der Stack leer ist, mit dem vorherigen Verzeichnis.
- Nach erfolgreichem Wechsel gibt `pushd` das neue Verzeichnis nach stdout aus.

Patch 336 baut auf Patch 335 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 336 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 337

- `popd` wechselt zum obersten gespeicherten Verzeichnis und entfernt es danach
  vom Stack. Der Zielpfad wird nach stdout geschrieben; ein leerer Stack wird
  mit einer klaren Fehlermeldung abgewiesen.

Patch 337 baut auf Patch 336 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 337 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 338

- `dirs` zeigt zuerst das aktuelle Verzeichnis und danach gespeicherte
  Verzeichnisse vom jüngsten zum ältesten Stackeintrag.
- Der Befehl ist zustandsfrei und kann als Stufe einer Pipe verwendet werden.

Patch 338 baut auf Patch 337 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 338 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 339

- `dirs -p` schreibt jeden Verzeichniseintrag in eine eigene Zeile.
- `dirs -c` leert den Stack, ohne das aktuelle Verzeichnis zu ändern. Die
  mutierende Form ist deshalb nicht als Pipeline-Stufe zugelassen.

Patch 339 baut auf Patch 338 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 339 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 340

- `dirs -v` nummeriert das aktuelle Verzeichnis als Eintrag `0` und die
  gespeicherten Verzeichnisse anschließend vom jüngsten zum ältesten.
- Die Anzeige ist zustandsfrei und bleibt als Pipeline-Stufe zugelassen.

Patch 340 baut auf Patch 339 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 340 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 341

- `pushd +N` rotiert den Verzeichnisstack, sodass Eintrag `N` aus `dirs -v` zum
  aktuellen Verzeichnis wird.
- `popd +N` entfernt den angegebenen Eintrag. `popd +0` wechselt zum nächsten
  Stackeintrag; `popd` ohne Index behält das bisherige Wechsel-und-Entfernen-
  Verhalten für den obersten gespeicherten Eintrag.

Patch 341 baut auf Patch 340 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 341 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 342

- Nach einem erfolgreichen `cd` erhält `OLDPWD` das verlassene und `PWD` das
  anschließend tatsächlich aktuelle Verzeichnis. Beide Shell-Variablen stehen
  in Expansionen und als Umgebungsüberschreibungen für gestartete Programme
  bereit.
- Fehlgeschlagene Verzeichniswechsel ändern diese Variablen nicht.

Patch 342 baut auf Patch 341 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 342 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 343

- Erfolgreiche Verzeichniswechsel über `pushd` und `popd` aktualisieren nun
  ebenfalls `PWD` und `OLDPWD` mit dem tatsächlich aktuellen Verzeichnis.
- Reine Stackänderungen wie `popd +N` bei `N > 0` lassen die Variablen
  unverändert, weil das aktuelle Verzeichnis dabei nicht wechselt.

Patch 343 baut auf Patch 342 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 343 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 344

- `cd -- PFAD` behandelt das folgende Argument als Verzeichnispfad. So lassen
  sich auch Verzeichnisnamen angeben, die mit `-` beginnen oder genau `-`
  lauten, ohne dass sie als Option oder als Wechsel zum vorherigen Verzeichnis
  interpretiert werden.
- `cd --` kehrt wie ein `cd` ohne Argument zum Home-Verzeichnis zurück.

Patch 344 baut auf Patch 343 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 344 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 345

- `pushd -- PFAD` behandelt das folgende Argument als Verzeichnispfad. Damit
  können beispielsweise Verzeichnisse mit einem Namen wie `+2` geöffnet
  werden, ohne `+2` als Stackindex auszuwerten.
- `pushd --` verhält sich wie `pushd` ohne Argument und tauscht mit dem
  gespeicherten Verzeichnis.

Patch 345 baut auf Patch 344 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 345 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 346

- `ShellHost` erhält eine optionale Methode für den Start interaktiver
  Vordergrundprogramme. Ein Host kann darüber sein Terminal für Programme wie
  Vim bereitstellen.
- Bestehende Hosts müssen die Methode nicht implementieren; standardmäßig wird
  weiterhin der bisherige Pipeline-Start verwendet.

Patch 346 baut auf Patch 345 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 346 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.

## Erweiterung in Patch 347

- Ein einzelnes externes Vordergrundprogramm ohne Umleitungen wird nun über den
  interaktiven Host-Hook gestartet.
- Pipes, Hintergrundjobs und umgeleitete Befehle bleiben beim bisherigen
  Pipeline-Start. Gibt der Host für den Hook `None` zurück, greift ebenfalls der
  normale Pipeline-Start.

Patch 347 baut auf Patch 346 auf. `cargo` ist in der Erstellungsumgebung nicht
verfügbar; Patch 347 wurde daher hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.


## ShellDeck-GUI-Backend (Patch 348)

Die Rust-CLI kann in ShellDeck als ausdrücklich wählbares Backend erscheinen,
wenn eine bereits gebaute ausführbare Datei gefunden wird. Die Suche umfasst
das Rust-Projektverzeichnis unter `target/release` und `target/debug` sowie
gebündelte `bin`-Verzeichnisse. Cargo wird dabei nicht automatisch gestartet.
Fehlt die Datei, zeigt ShellDeck einen Hinweis und fällt für diesen Backendtyp
nicht unbemerkt auf eine andere Shell zurück.

Zum Erzeugen der Release-Datei im Ordner `rust/shelldeck-shell`
`cargo build --release` ausführen und ShellDeck anschließend neu starten.
`cargo check` erzeugt keine ausführbare Datei. Die bisherige Standardshell bleibt
unverändert; System-Shells bleiben als auswählbarer Kompatibilitätsmodus erhalten.

Diese erste GUI-Anbindung startet die Rust-CLI im vorhandenen PTY/ConPTY-Weg.
Sie bestätigt noch keine vollständige Roh-Tastatureingabe für Vollbildprogramme
wie Vim. Dafür müssen der interaktive Rust-Host-Hook und die Eingabepipeline der
GUI separat verbunden werden.


## Terminal-Rueckkanal fuer ShellDeck (Patch 349)

- Die Rust-Shells `PATH >`-Prompt wird als fertiger Shell-Prompt erkannt.
- Nach `cd`, `pushd` und `popd` liest ShellDeck `PWD` und `VIRTUAL_ENV` über
  einen unsichtbaren `printf`-Kontextmarker aus; das gilt auch unter Windows.
- `cls` wird in der ShellDeck-Shell auf `clear` abgebildet.

Damit werden Statusanzeige und Arbeitsordner-Prompt mit der Rust-Shell
synchronisiert. Vollbild-Tastatureingabe für Vim bleibt davon unberührt und ist
noch nicht Teil dieser Anbindung.


## Erweiterung in Patch 350

- Der eigenständige CLI-Host implementiert nun `run_interactive_program`.
  Einzelne Vordergrundprogramme ohne Umleitungen erben Ein- und Ausgabekanäle,
  erhalten das aktuelle Arbeitsverzeichnis sowie Shell-Variablen und liefern
  ihren Exitstatus an die Shell zurück.
- Bei umgeleiteter Fehlerausgabe greift vorsorglich der normale Pipeline-Pfad.
- In ShellDeck kann der bestehende PTY/ConPTY-Kanal so bis zum Kindprogramm
  weitergereicht werden. Die tatsächliche Tastaturbedienung hängt weiterhin vom
  jeweiligen Terminal-Host ab.

Patch 350 baut auf Patch 349 auf. `cargo` war in der Erstellungsumgebung nicht
verfügbar; der Patch wurde hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.


## Erweiterung in Patch 351

- Die CLI-Eingabeschleife liest Befehle nun über `ShellHost::read_input_line`,
  denselben Host-Zugriff, den auch das eingebaute `read` verwendet.
- Shell-Befehle und das eingebaute `read` verwenden damit denselben
  Host-Eingabepunkt. Eine spätere Eingabeanpassung kann so zentral am Host
  erfolgen.

Patch 351 baut auf Patch 350 auf. `cargo` war in der Erstellungsumgebung nicht
verfügbar; der Patch wurde hier nicht kompiliert. Es wurden keine Tests
hinzugefügt oder ausgeführt.


## Erweiterung in Patch 352

- Der eigenständige CLI-Host verwendet Rustyline für die interaktive Eingabe.
  Pfeiltasten, Cursorbewegung, Löschen und eine Sitzungshistorie werden dadurch
  direkt in der Shell-Eingabezeile verarbeitet.
- Vor dem Start eines Vordergrundprogramms stellt Rustyline den vorherigen
  Terminalmodus wieder her. Bei nicht-interaktiver Standardeingabe bleibt das
  zeilenweise Lesen über stdin erhalten.
- Das wiederverwendbare `ShellHost`-Modul bleibt frei von dieser CLI-spezifischen
  Eingabebibliothek.

Patch 352 ergänzt Rustyline als Abhängigkeit des CLI-Binaries.


## Erweiterung in Patch 355

- Reedline ersetzt Rustyline als interaktiven Zeileneditor. In der ShellDeck-
  VT-Ansicht kann ein Linksklick den Eingabecursor in der aktuellen Befehlszeile
  versetzen. Die Mauserfassung bleibt auf den aktiven Eingabemodus begrenzt.
- Rechtsklick und Mittelklick behalten die ShellDeck-Bedienung: Kontextmenü
  beziehungsweise Einfügen der Primärauswahl.
- Die Rust-Shell-Eingabeaufforderung wird grün dargestellt.
- Der VT-Renderer unterstützt ANSI-16-Farben, 256-Farben und Truecolor bereits;
  ein SGR-Farbbefehl wie `printf` kann die Ausgabe sichtbar prüfen. Vim zeigt
  auf seiner Startseite normalerweise keine syntaxgefärbte Datei an.

Patch 355 benötigt Rust 1.95 oder neuer. Nach dem Einspielen `cargo check` und
`cargo build --release` im Ordner `rust/shelldeck-shell` ausführen. Cargo
aktualisiert dabei `Cargo.lock` für Reedline 0.52.1.
Reedline steht unter MIT-Lizenz; bei Auslieferung des Rust-CLI-Binaries ist
der entsprechende Drittanbieterhinweis in ShellDecks Lizenzübersicht aufzunehmen.
