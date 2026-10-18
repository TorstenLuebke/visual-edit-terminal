#!/usr/bin/env python3
"""Liest Qt/PySide-Bibliotheksherkunft ohne Programmstart und ohne Schreibzugriff auf Builds."""
import argparse
import json
import os
from pathlib import Path
import subprocess


TARGETS = ("libQt6Core.so", "libQt6Gui.so", "libQt6Widgets.so", "libqxcb.so", "libqwayland.so", "libpyside6", "libshiboken6")


def inspect(root: Path) -> dict:
    info = {"directory": str(root), "cases": {}}
    for case in ("model-baseline", "model-freelist", "renderer-baseline", "renderer-freelist"):
        dist = root / case / ("diagnose_vt_renderer_185.dist" if case.startswith("renderer") else "diagnose_vt_model_184.dist")
        entry = dist / ("diagnose_vt_renderer_185" if case.startswith("renderer") else "diagnose_vt_model_184")
        files = []
        if dist.is_dir():
            for path in dist.rglob("*"):
                if path.is_file() and any(token.lower() in path.name.lower() for token in TARGETS):
                    files.append(str(path.relative_to(dist)))
        dependency_lines = []
        if entry.is_file():
            try:
                process = subprocess.run(["ldd", str(entry)], capture_output=True,
                                         text=True, timeout=15, check=False)
                dependency_lines = [line.strip() for line in process.stdout.splitlines()
                                    if "qt" in line.lower() or "pyside" in line.lower() or "shiboken" in line.lower()]
            except (OSError, subprocess.TimeoutExpired) as exc:
                dependency_lines = [f"ldd nicht verfuegbar: {exc}"]
        info["cases"][case] = {"binary_found": entry.is_file(), "bundled_libraries": sorted(files),
                                "ldd_filtered": dependency_lines}
    return info


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    root = args.directory.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Ordner fehlt: {root}")
    report = inspect(root)
    (root / "qt-library-audit.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Qt-Bibliotheksbericht:", root / "qt-library-audit.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
