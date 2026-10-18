#!/usr/bin/env python3
"""Summarize full build/manual tests into a small ZIP, excluding standalone binaries."""
import argparse
import json
from pathlib import Path
import zipfile


def report(folder: Path, destination: Path) -> None:
    folder = folder.resolve()
    data_path = folder/'full-build-results.json'
    if not data_path.is_file():
        raise FileNotFoundError(data_path)
    builds = json.loads(data_path.read_text(encoding='utf-8'))
    summary = ['ShellDeck – Vollbuild-Vergleich 198–200',
               'Erfolgreicher Build ist kein Nachweis interaktiver Terminal-Stabilitaet.', '']
    for item in builds:
        sub = folder/item['variant']
        manuals = sorted(sub.glob('manual-*.json'))
        summary.append(f"{item['variant']}: build_exit={item['build_exit']}; manual_runs={len(manuals)}")
        for path in manuals:
            r = json.loads(path.read_text(encoding='utf-8'))
            summary.append(f"  {path.name}: platform={r['platform']} exit={r['returncode']} "
                           f"duration={r['duration_seconds']}s")
    summary.append('')
    summary.append('Bitte manuelle Testergebnisse je Engine separat mitteilen; ein Exitcode 0 allein beweist keine Stabilitaet.')
    (folder/'full-build-summary.txt').write_text('\n'.join(summary)+'\n', encoding='utf-8')
    allowed_names = {'full-build-results.json', 'full-build-summary.txt', 'build.log',
                     'build.exit', 'build-command.json'}
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(folder.rglob('*')):
            if not path.is_file():
                continue
            if path.name not in allowed_names and not (path.name.startswith('manual-') and
                                                       path.suffix in ('.json', '.log')):
                continue
            archive.write(path, arcname=str(path.relative_to(folder)))
    print('\n'.join(summary))
    print('ZIP:', destination)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('folder', type=Path)
    ap.add_argument('--zip', type=Path, required=True)
    a = ap.parse_args()
    report(a.folder, a.zip)


if __name__ == '__main__':
    main()
