#!/usr/bin/env bash
# Vergleicht unveraenderte Python-Tests mit isolierten Nuitka-Builds.
# Keine Veraenderungen der installierten ShellDeck-Version.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${SHELLDECK_DIAG_OUT:-$HOME/Downloads/shelldeck-nuitka-diagnose-$STAMP}"
mkdir -p "$OUT"
if [[ ! -x "$PY" ]]; then echo "Python fehlt: $PY" >&2; exit 2; fi
if ! "$PY" -m nuitka --version >/dev/null 2>&1; then echo "Nuitka fehlt im Projekt-venv" >&2; exit 2; fi
printf 'Diagnose: %s\n' "$OUT"
# Vorab pruefen, ob beide Skripte in der Quellumgebung starten.
# Ein Import-/Pfadfehler darf keine vier teuren Vergleichsbuilds ausloesen.
for scenario in model renderer; do
  if [[ "$scenario" == model ]]; then ENTRY=diagnose_vt_model_184; else ENTRY=diagnose_vt_renderer_185; fi
  if [[ "$scenario" == renderer ]]; then
    (cd "$ROOT" && QT_QPA_PLATFORM=offscreen "$PY" "tools/$ENTRY.py" --lines 256) > "$OUT/source-$scenario.log" 2>&1
  else
    (cd "$ROOT" && "$PY" "tools/$ENTRY.py" --lines 256) > "$OUT/source-$scenario.log" 2>&1
  fi
  rc=$?
  echo "$rc" > "$OUT/source-$scenario.exit"
  if [[ "$rc" -ne 0 ]]; then
    echo "Quelltest fehlgeschlagen: $OUT/source-$scenario.log" >&2
    tail -n 20 "$OUT/source-$scenario.log" >&2
    exit 3
  fi
done
"$PY" --version > "$OUT/versions.txt" 2>&1
"$PY" -m nuitka --version >> "$OUT/versions.txt" 2>&1
"$PY" -m pip show pyte PySide6 >> "$OUT/versions.txt" 2>&1 || true
# --standalone: lokale Quellen und pyte werden fuer reproduzierbare Vergleiche mitgenommen.
for scenario in model renderer; do
  if [[ "$scenario" == model ]]; then ENTRY=diagnose_vt_model_184; else ENTRY=diagnose_vt_renderer_185; fi
  for variant in baseline freelist; do
    DIR="$OUT/$scenario-$variant"
    mkdir -p "$DIR"
    extra=()
    [[ "$variant" == freelist ]] && extra+=(--experimental=disable-freelist-all)
    echo "BUILD $scenario $variant"
    (cd "$ROOT" && PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}" "$PY" -m nuitka --standalone --lto=no --jobs=4 \
      --include-package=pyte \
      --output-dir="$DIR" --output-filename="$ENTRY" \
      --enable-plugin=pyside6 --include-module=shelldeck_vt_screen       --include-module=shelldeck_terminal_grid       "${extra[@]}" "tools/$ENTRY.py") > "$DIR/build.log" 2>&1
    build_rc=$?
    echo "$build_rc" > "$DIR/build.exit"
    [[ "$build_rc" == 0 ]] || { echo "Build fehlgeschlagen: $DIR/build.log"; continue; }
    BIN="$DIR/$ENTRY.dist/$ENTRY"
    if [[ ! -x "$BIN" ]]; then echo "Binary nicht gefunden: $BIN"; continue; fi
    echo "RUN $scenario $variant"
    if [[ "$scenario" == renderer ]]; then
      QT_QPA_PLATFORM=offscreen timeout --signal=TERM --kill-after=5s 180s "$BIN" --lines 50000 > "$DIR/run.log" 2>&1
    else
      timeout --signal=TERM --kill-after=5s 180s "$BIN" --lines 50000 > "$DIR/run.log" 2>&1
    fi
    echo "$?" > "$DIR/run.exit"
    tail -n 4 "$DIR/run.log" || true
  done
done
echo "Auswertung (Exit-Code 0 = erfolgreich; 139 meist SIGSEGV):"
find "$OUT" -name 'run.exit' -o -name 'build.exit' | sort | while read -r f; do printf '%s: ' "$f"; cat "$f"; done
echo "Protokollordner: $OUT"
