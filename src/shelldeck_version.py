"""Einheitliche ShellDeck-Versionsquelle, ohne Qt- oder Plattformabhängigkeiten.

Die Datei ``versions.txt`` liegt im Projektverzeichnis bzw. neben einer
paketierten Anwendung. Ihr Inhalt ist die alleinige wartbare Versionsangabe.
Falls sie bei einer fehlerhaften Installation fehlt, wird der letzte bekannte
Wert verwendet, damit ShellDeck weiter starten kann.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

_FALLBACK_VERSION = "2.16.0"
_VERSION_FORMAT = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]*)?")


def version_file_locations() -> tuple[Path, ...]:
    """Moegliche Ressourcenorte für Source-Start und gepackte Programme."""
    module_dir = Path(__file__).resolve().parent
    candidates = []
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent / "versions.txt")
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            candidates.append(Path(bundle) / "versions.txt")
    # src/main.py kann unabhaengig vom aktuellen Arbeitsverzeichnis starten.
    candidates.extend((module_dir.parent / "versions.txt", module_dir / "versions.txt"))
    return tuple(dict.fromkeys(candidates))


def load_version(path: Path | None = None) -> str:
    """Liest eine einzige SemVer-artige Zeile aus ``versions.txt``."""
    candidates = (Path(path),) if path is not None else version_file_locations()
    for candidate in candidates:
        try:
            value = candidate.read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeError):
            continue
        if _VERSION_FORMAT.fullmatch(value):
            return value
    return _FALLBACK_VERSION


APP_VERSION = load_version()
