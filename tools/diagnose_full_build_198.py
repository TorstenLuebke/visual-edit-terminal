#!/usr/bin/env python3
"""Build two isolated full ShellDeck standalones; never install or modify the live app."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

VARIANTS = {
    'reference': ['--debug', '--no-debug-immortal-assumptions'],
    'release-no-debug': [],
}


def build(root: Path, out: Path, *, jobs: int = 4, timeout: int = 5400) -> int:
    root = root.resolve()
    out = out.resolve()
    if out == root or root in out.parents or out == Path('/'):
        raise ValueError('Ausgabeverzeichnis muss ausserhalb des Projekts liegen')
    py = root / '.venv/bin/python'
    entry = root / 'src/main.py'
    if not py.is_file() or not entry.is_file():
        raise FileNotFoundError('Projekt-Python oder src/main.py fehlt')
    if not 1 <= jobs <= 16 or timeout < 60:
        raise ValueError('jobs muss 1..16 und timeout mindestens 60 sein')
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for name, extra in VARIANTS.items():
        target = out / name
        if target.exists() and any(target.iterdir()):
            raise FileExistsError(f'Build-Verzeichnis nicht leer: {target}')
        target.mkdir(parents=True, exist_ok=True)
        cmd = [str(py), '-m', 'nuitka', '--standalone', '--follow-imports',
               '--enable-plugin=pyside6', '--include-package=pyte', '--lto=no',
               f'--jobs={jobs}', '--unstripped', '--experimental=disable-freelist-all',
               '--noinclude-qt-plugins=qml,quick,webengine,webview,designer',
               f'--output-dir={target}', '--output-filename=ShellDeck', *extra]
        for directory in ('docs',):
            if (root / directory).is_dir():
                cmd.append(f'--include-data-dir={root / directory}={directory}')
        for filename in ('AGENTS.md', 'CLAUDE.md', 'README.md', 'requirements.txt', 'version.txt'):
            if (root / filename).is_file():
                cmd.append(f'--include-data-files={root / filename}={filename}')
        cmd.append(str(entry))
        (target / 'build-command.json').write_text(json.dumps(cmd, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        started = time.monotonic()
        print('BUILD', name, flush=True)
        with (target / 'build.log').open('w', encoding='utf-8', errors='replace') as log:
            try:
                status = subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT,
                                        timeout=timeout, check=False).returncode
            except subprocess.TimeoutExpired:
                status = 124
            except OSError as exc:
                log.write(f'FEHLER: {exc}\n')
                status = 127
        (target / 'build.exit').write_text(str(status)+'\n', encoding='utf-8')
        candidates = [target/'main.dist/ShellDeck', target/'ShellDeck.dist/ShellDeck']
        binary = next((p for p in candidates if p.is_file() and os.access(p, os.X_OK)), None)
        result = {'variant': name, 'build_exit': status, 'duration_seconds': round(time.monotonic()-started, 2),
                  'binary': str(binary) if binary else None, 'flags': extra}
        results.append(result)
        (out / 'full-build-results.json').write_text(json.dumps(results, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    return 0 if all(r['build_exit'] == 0 and r['binary'] for r in results) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--out', type=Path, default=Path.home()/'Downloads'/'shelldeck-full-build-198-200')
    ap.add_argument('--jobs', type=int, default=4)
    ap.add_argument('--timeout', type=int, default=5400)
    a = ap.parse_args()
    try:
        return build(a.root, a.out, jobs=a.jobs, timeout=a.timeout)
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f'FEHLER: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
