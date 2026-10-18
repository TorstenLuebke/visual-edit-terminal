#!/usr/bin/env python3
"""Build independent full ShellDeck standalones with compiled vs source-form pyte.

Does not install or mutate the production app. User tests both GUIs with tool 199.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def make_build(root: Path, output: Path, python: Path, *, jobs: int = 4, timeout: int = 7200) -> int:
    # Keep the venv launcher path: resolving symlinks points to the base
    # interpreter and silently drops the project's site-packages.
    root, output = root.resolve(), output.resolve()
    python = python.expanduser().absolute()
    if root == output or root in output.parents or output == Path('/'):
        raise ValueError('Build-Ausgabe muss ausserhalb des Projekts liegen')
    if not python.is_file() or not (root/'src/main.py').is_file():
        raise ValueError('Interpreter oder src/main.py fehlt')
    if not 1 <= jobs <= 16 or timeout < 60:
        raise ValueError('Ungueltige jobs/timeout')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Zielordner ist nicht leer; vorhandene Builds bleiben unangetastet')
    output.mkdir(parents=True, exist_ok=True)
    locator = subprocess.run([str(python), '-c',
        'import importlib.util,json; s=importlib.util.find_spec("pyte"); print(json.dumps({"origin":s.origin if s else None,"search":list(s.submodule_search_locations or []) if s else []}))'],
        capture_output=True, text=True, check=False)
    if locator.returncode:
        raise ValueError(f'pyte-Pruefung fehlgeschlagen mit {python}: {locator.stderr.strip()}')
    if not locator.stdout.strip():
        raise ValueError(f'Keine pyte-Information von {python} erhalten')
    spec = json.loads(locator.stdout)
    if not spec.get('search'):
        raise ValueError(f'pyte nicht importierbar in der Projektumgebung: {python}')
    pyte_source = Path(spec['search'][0]).resolve()
    results = []
    for variant in ('compiled-pyte', 'source-pyte'):
        target = output / variant
        target.mkdir()
        cmd = [str(python), '-m', 'nuitka', '--standalone', '--follow-imports',
            '--enable-plugin=pyside6', '--lto=no', '--unstripped',
            '--experimental=disable-freelist-all', f'--jobs={jobs}',
            '--noinclude-qt-plugins=qml,quick,webengine,webview,designer',
            f'--output-dir={target}', '--output-filename=ShellDeck']
        if variant == 'compiled-pyte':
            cmd.append('--include-package=pyte')
        else:
            cmd.extend(['--nofollow-import-to=pyte', '--include-package=wcwidth'])
        if (root/'docs').is_dir():
            cmd.append(f'--include-data-dir={root / "docs"}=docs')
        for name in ('AGENTS.md', 'CLAUDE.md', 'README.md', 'requirements.txt', 'version.txt'):
            if (root/name).is_file():
                cmd.append(f'--include-data-files={root/name}={name}')
        cmd.append(str(root/'src/main.py'))
        (target/'build-command.json').write_text(json.dumps(cmd, indent=2)+'\n')
        print('BUILD', variant, flush=True)
        start = time.monotonic()
        with (target/'build.log').open('w', encoding='utf-8') as log:
            try:
                status = subprocess.run(cmd, cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=timeout).returncode
            except subprocess.TimeoutExpired:
                status = 124
            except OSError as exc:
                log.write(f'EXEC FEHLER: {exc}\n')
                status = 127
        dist = target/'main.dist'
        binary = dist/'ShellDeck'
        validation = {'kind': variant, 'compiled_pyte_present': None, 'source_files': 0}
        if status == 0 and variant == 'source-pyte':
            try:
                # Nuitka excludes the package's code. Copy original .py sources only;
                # do not treat source code as Nuitka data files.
                target_package = dist/'pyte'
                if target_package.exists():
                    raise ValueError('Unerwartetes pyte im Build; Isolation nicht nachgewiesen')
                shutil.copytree(pyte_source, target_package,
                    ignore=shutil.ignore_patterns('__pycache__','*.pyc','*.so','*.pyd','*.dll'))
                validation['source_files'] = len(list(target_package.rglob('*.py')))
                # Built-in Nuitka modules appear in the binary, not necessarily as files.
                # Verify source pyte is imported via normal Python source loader at runtime.
                if validation['source_files'] < 5:
                    raise ValueError('Zu wenige pyte-Quelldateien vorhanden')
            except (OSError, ValueError) as exc:
                validation['error'] = str(exc)
                status = 3
        validation['binary_exists'] = binary.is_file() and os.access(binary, os.X_OK)
        (target/'validation.json').write_text(json.dumps(validation, indent=2)+'\n')
        (target/'build.exit').write_text(str(status)+'\n')
        results.append({'variant':variant,'build_exit':status,
            'binary':str(binary) if validation['binary_exists'] else None,
            'duration_seconds':round(time.monotonic()-start,2),'validation':validation})
        (output/'full-build-results.json').write_text(json.dumps(results,indent=2)+'\n')
    return 0 if all(r['build_exit']==0 and r['binary'] for r in results) else 1


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    ap.add_argument('--out',type=Path,default=Path.home()/'Downloads/shelldeck-pyte-201-203')
    ap.add_argument('--python',type=Path,default=Path(__file__).resolve().parents[1]/'.venv/bin/python')
    ap.add_argument('--jobs',type=int,default=4)
    ap.add_argument('--timeout',type=int,default=7200)
    a=ap.parse_args()
    try:
        return make_build(a.root,a.out,a.python,jobs=a.jobs,timeout=a.timeout)
    except (ValueError,OSError,subprocess.SubprocessError) as exc:
        print('FEHLER:',exc,file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
