"""Zentrale ShellDeck-Versionsquelle für Quellstart und gepackte Programme.

``version.txt`` ist die maßgebliche Versionsdatei. Ältere Installationen,
welche nur ``versions.txt`` enthalten, bleiben lesbar. Für Releases muss
``version.txt`` als Datendatei neben dem kompilierten Programm liegen.
"""

from __future__ import annotations

from pathlib import Path
import re
import sys

_FALLBACK_VERSION = "2.16.0"
_VERSION_FORMAT = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z][0-9A-Za-z.+-]*)?")


def version_file_locations() -> tuple[Path, ...]:
    """Sucht zuerst die neue Datei, erst danach den alten Dateinamen.

    Bei Nuitka-Standalone liegt ``sys.executable`` im ``.dist``-Ordner;
    ``__file__`` kann dagegen auf ein Modul im Paket verweisen. Der
    Programmordner hat deshalb bei gebauten Anwendungen Vorrang.
    """
    module_dir = Path(__file__).resolve().parent
    roots: list[Path] = []

    if getattr(sys, "frozen", False) or "__compiled__" in globals():
        roots.append(Path(sys.executable).resolve().parent)
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            roots.append(Path(bundle))

    # Quellstart mit src/main.py, unabhängig vom Arbeitsverzeichnis.
    roots.extend((module_dir.parent, module_dir))
    roots = list(dict.fromkeys(roots))

    # Auch wenn ein alter Dateiname an einem früheren Suchort liegt,
    # gewinnt stets die neue version.txt aus einem späteren Suchort.
    return tuple(root / name for name in ("version.txt", "versions.txt") for root in roots)


def load_version(path: Path | None = None) -> str:
    """Liest eine einzelne SemVer-artige Zeile; fällt sonst sicher zurück."""
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
