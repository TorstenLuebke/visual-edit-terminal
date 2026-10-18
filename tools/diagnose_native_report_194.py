#!/usr/bin/env python3
"""Erstellt einen kompakten, datensparsamen Bericht aus den GDB-Protokollen."""
import argparse
import json
from pathlib import Path
import re
import zipfile

NAMES = ("renderer-baseline/gdb-native.log", "renderer-freelist/gdb-native.log", "gdb-shelldeck-native.log")
SIGNALS = re.compile(r"Program received signal|SIGSEGV|SIGABRT|Segmentation fault", re.IGNORECASE)
FRAMES = re.compile(r"^#\d+\s+", re.MULTILINE)


def make_report(root: Path, output: Path) -> None:
    records = []
    for rel in NAMES:
        path = root / rel
        if path.is_file():
            data = path.read_text(encoding="utf-8", errors="replace")
            signals = [line.strip()[:240] for line in data.splitlines() if SIGNALS.search(line)]
            frames = FRAMES.findall(data)
            records.append({"file": rel, "bytes": path.stat().st_size,
                            "signals": signals[:12], "native_frames": len(frames)})
        else:
            records.append({"file": rel, "status": "not_recorded"})
    report = {"records": records, "note": "Ein GDB-Backtrace zeigt die Absturzstelle, nicht zwangsläufig die ursprüngliche Ursache."}
    report_file = root / "gdb-summary.json"
    report_file.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for rel in NAMES + ("gdb-summary.json", "gdb-renderer-results.json"):
            file = root / rel
            if file.is_file():
                archive.write(file, rel)
    print("Bericht:", report_file)
    print("ZIP:", output)
    for record in records:
        print(record["file"], "Signale:", len(record.get("signals", [])), "Frames:", record.get("native_frames", 0))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--zip", type=Path, required=True)
    args = parser.parse_args()
    root = args.directory.expanduser().resolve()
    if not root.is_dir():
        parser.error(f"Ordner fehlt: {root}")
    make_report(root, args.zip.expanduser().resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
