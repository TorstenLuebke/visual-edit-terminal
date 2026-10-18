#!/usr/bin/env python3
"""Launch a chosen full standalone build for an interactive manual PTY/QProcess test."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def run(build_dir: Path, variant: str, platform: str) -> int:
    results_file = build_dir/'full-build-results.json'
    if not results_file.is_file():
        print(f'FEHLER: Fehlende Buildliste: {results_file}', file=sys.stderr)
        return 2
    records = json.loads(results_file.read_text(encoding='utf-8'))
    record = next((r for r in records if r['variant'] == variant), None)
    if not record or record['build_exit'] != 0 or not record['binary']:
        print(f'FEHLER: Build {variant} ist nicht verwendbar.', file=sys.stderr)
        return 2
    binary = Path(record['binary']).resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK) or build_dir.resolve() not in binary.parents:
        print('FEHLER: Ungueltiger Binarypfad innerhalb des Diagnoseordners.', file=sys.stderr)
        return 2
    folder = build_dir / variant
    index = 1
    while (folder/f'manual-{index:02}.json').exists():
        index += 1
    log = folder / f'manual-{index:02}.log'
    env = dict(os.environ)
    env['QT_QPA_PLATFORM'] = platform
    # Prevent project interpreter or Qt-plugin environment leaking into the standalone app.
    for name in ('PYTHONPATH', 'PYTHONHOME', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        env.pop(name, None)
    start = datetime.now(timezone.utc)
    print(f'Starte {variant} ({platform}). In ShellDeck PTY und QProcess testen.', flush=True)
    print('Vorschlag PTY: seq 1 50000 ; danach weiteren Tab und QProcess pruefen.', flush=True)
    print('Schliesse das Testfenster anschliessend regulaer. Keine Installation erfolgt.', flush=True)
    began = time.monotonic()
    with log.open('w', encoding='utf-8', errors='replace') as handle:
        try:
            completed = subprocess.run([str(binary)], cwd=Path.home(), env=env,
                                       stdout=handle, stderr=subprocess.STDOUT, check=False)
            status = completed.returncode
        except OSError as exc:
            handle.write(f'EXEC FEHLER: {exc}\n')
            status = 127
    info = {'variant': variant, 'platform': platform, 'started_utc': start.isoformat(),
            'duration_seconds': round(time.monotonic()-began, 2), 'returncode': status,
            'manual_steps': 'Interaktive Pruefung durch Benutzer; Status ist kein automatischer PTY-Nachweis.'}
    (folder/f'manual-{index:02}.json').write_text(json.dumps(info, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(f'Beendet: {status}; Protokoll: {log}', flush=True)
    return 0 if status == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('build_dir', type=Path)
    ap.add_argument('--variant', choices=('reference', 'release-no-debug'), required=True)
    ap.add_argument('--platform', choices=('xcb', 'wayland'), default='xcb')
    args = ap.parse_args()
    return run(args.build_dir.resolve(), args.variant, args.platform)


if __name__ == '__main__':
    raise SystemExit(main())
