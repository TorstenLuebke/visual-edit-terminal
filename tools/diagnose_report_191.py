#!/usr/bin/env python3
"""Erstellt eine kompakte Diagnose-Zusammenfassung und ein ZIP nur mit Logs/Metadaten."""
import argparse
import json
from pathlib import Path
import zipfile

EXACT = {"versions.txt", "repeat-results.json", "qt-library-audit.json", "summary.json", "summary.txt"}
SUFFIX = {".log", ".exit"}


def report(root: Path) -> dict:
    cases = {}
    for label in ("model-baseline", "model-freelist", "renderer-baseline", "renderer-freelist"):
        folder = root / label
        case = {}
        for name in ("build.exit", "run.exit"):
            file = folder / name
            try:
                case[name] = int(file.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                case[name] = None
        cases[label] = case
    repeats = []
    try:
        repeats = json.loads((root / "repeat-results.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return {"cases": cases, "repeats": repeats,
            "warning": "Exit-Code 0 bei einem einzelnen Lauf beweist keine dauerhafte Stabilitaet."}


def create_report(root: Path, destination: Path) -> None:
    data = report(root)
    (root / "summary.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rows = ["ShellDeck Nuitka Diagnose", "========================", ""]
    for label, case in data["cases"].items():
        rows.append(f"{label}: build={case['build.exit']} run={case['run.exit']}")
    rows += ["", "Wiederholungen:"]
    for item in data["repeats"]:
        rows.append(f"{item['case']} #{item['attempt']}: {item['status']} (exit={item['exit_code']}, {item['seconds']}s)")
    rows += ["", data["warning"]]
    (root / "summary.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in sorted(root.rglob("*")):
            if file.is_file() and (file.name in EXACT or file.suffix in SUFFIX):
                if file.resolve() != destination.resolve():
                    archive.write(file, file.relative_to(root).as_posix())
    print("Zusammenfassung:", root / "summary.txt")
    print("Diagnose-ZIP:", destination)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--zip", dest="zip_path", type=Path, default=None)
    args = parser.parse_args()
    root = args.directory.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Ordner fehlt: {root}")
    destination = (args.zip_path.expanduser().resolve() if args.zip_path else root.parent / f"{root.name}-nur-protokolle.zip")
    create_report(root, destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
