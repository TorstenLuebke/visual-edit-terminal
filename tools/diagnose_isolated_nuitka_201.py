#!/usr/bin/env python3
"""Create an independent build environment without changing ShellDeck's .venv.

This script installs only already-used project dependencies in a new venv.
Network access for pip is explicit (--allow-index); otherwise --wheelhouse is required.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import venv


def prepare(root: Path, folder: Path, version: str, wheelhouse: Path | None, allow_index: bool) -> int:
    root, folder = root.resolve(), folder.resolve()
    if folder == root or root in folder.parents or folder == Path('/'):
        raise ValueError('Build-Umgebung muss ausserhalb des Quellprojekts liegen')
    if not allow_index and not wheelhouse:
        raise ValueError('Offline-Modus: --wheelhouse angeben oder --allow-index explizit freigeben')
    if wheelhouse and not wheelhouse.is_dir():
        raise ValueError('Wheelhouse nicht gefunden')
    if (folder / 'pyvenv.cfg').exists():
        raise ValueError('Zielumgebung existiert bereits; bestehende Umgebung bleibt unveraendert')
    folder.parent.mkdir(parents=True, exist_ok=True)
    venv.EnvBuilder(with_pip=True, system_site_packages=False).create(folder)
    py = folder / 'bin/python'
    original = root / '.venv/bin/python'
    if not original.is_file():
        raise ValueError('Projekt-Python fehlt')
    def package_version(pkg: str) -> str:
        script = ('from importlib.metadata import version; print(version(' + repr(pkg) + '))')
        return subprocess.check_output([str(original), '-c', script], text=True).strip()
    packages = [f'nuitka=={version}', f'PySide6=={package_version("PySide6")}',
                f'pyte=={package_version("pyte")}', f'wcwidth=={package_version("wcwidth")}']
    cmd = [str(py), '-m', 'pip', 'install', '--disable-pip-version-check']
    if not allow_index:
        cmd += ['--no-index']
    if wheelhouse:
        cmd += ['--find-links', str(wheelhouse.resolve())]
    cmd += packages
    log = folder.parent / (folder.name + '-install.log')
    with log.open('w', encoding='utf-8') as f:
        status = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, check=False).returncode
    versions = {}
    if status == 0:
        script = 'import nuitka,pyte,PySide6,wcwidth; from importlib.metadata import version; print("|".join(version(p) for p in ("nuitka","pyte","PySide6","wcwidth")))'
        p = subprocess.run([str(py), '-c', script], capture_output=True, text=True)
        if p.returncode != 0:
            status = p.returncode
            versions['import_error'] = p.stderr
        else:
            versions = dict(zip(('nuitka','pyte','pyside6','wcwidth'), p.stdout.strip().split('|')))
    meta = {'python': str(py), 'requirements': packages, 'install_status': status,
            'versions': versions, 'wheelhouse': str(wheelhouse) if wheelhouse else None,
            'allow_index': allow_index}
    (folder.parent / (folder.name + '-environment.json')).write_text(json.dumps(meta, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(meta, indent=2))
    return 0 if status == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--out', type=Path, default=Path.home()/'Downloads/shelldeck-nuitka-431-env')
    ap.add_argument('--version', default='4.3.1')
    ap.add_argument('--wheelhouse', type=Path)
    ap.add_argument('--allow-index', action='store_true', help='Ausdrueckliche Freigabe fuer Paketdownloads')
    a = ap.parse_args()
    try:
        return prepare(a.root, a.out, a.version, a.wheelhouse, a.allow_index)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('FEHLER:', exc, file=sys.stderr)
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
