#!/usr/bin/env python3
"""Run a selected standalone manually and archive compact results for comparison."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import zipfile


def manual(folder: Path, variant: str, platform: str) -> int:
    folder = folder.resolve()
    items = json.loads((folder/'full-build-results.json').read_text(encoding='utf-8'))
    item = next((row for row in items if row['variant'] == variant), None)
    if item is None or item['build_exit'] != 0 or not item['binary']:
        raise ValueError(f'Build nicht erfolgreich: {variant}')
    binary = Path(item['binary']).resolve()
    if not binary.is_file() or folder not in binary.parents:
        raise ValueError('Programmdatei fehlt oder liegt ausserhalb der Diagnose')
    variant_dir = folder / variant
    index = 1
    while (variant_dir/f'manual-{index:02}.json').exists():
        index += 1
    env = os.environ.copy()
    env['QT_QPA_PLATFORM'] = platform
    for key in ('PYTHONPATH','PYTHONHOME','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH'):
        env.pop(key, None)
    log = variant_dir/f'manual-{index:02}.log'
    print(f'Starte {variant}: Bitte PTY mit seq 1 50000 testen und Befund notieren.',flush=True)
    start=time.monotonic()
    with log.open('w',encoding='utf-8',errors='replace') as handle:
        p = subprocess.run([str(binary)], cwd=Path.home(), env=env, stdout=handle, stderr=subprocess.STDOUT, check=False)
    info={'variant':variant,'platform':platform,'exit':p.returncode,
        'duration_s':round(time.monotonic()-start,2),'timestamp':datetime.now(timezone.utc).isoformat(),
        'note':'Exit-Code ersetzt keinen Bedien- und Darstellungstest.'}
    (variant_dir/f'manual-{index:02}.json').write_text(json.dumps(info,indent=2)+'\n')
    print(json.dumps(info,indent=2))
    return 0 if p.returncode==0 else 1


def package(folder: Path, destination: Path) -> None:
    folder=folder.resolve(); destination=destination.resolve()
    items=json.loads((folder/'full-build-results.json').read_text(encoding='utf-8'))
    summary=['ShellDeck pyte-Quellmodulvergleich 201-203',
             'Der Nachweis erfordert Beobachtung der manuellen PTY-Tests.', '']
    for item in items:
        variant=item['variant']; runs=sorted((folder/variant).glob('manual-*.json'))
        summary.append(f'{variant}: build={item["build_exit"]}; binary={bool(item["binary"])}; run_count={len(runs)}')
        for run in runs:
            r=json.loads(run.read_text(encoding='utf-8'))
            summary.append(f'  {run.name}: {r["platform"]}, exit={r["exit"]}, {r["duration_s"]} s')
    (folder/'comparison-summary.txt').write_text('\n'.join(summary)+'\n',encoding='utf-8')
    destination.parent.mkdir(parents=True,exist_ok=True)
    allowed={'full-build-results.json','build-command.json','build.log','build.exit','validation.json','comparison-summary.txt'}
    with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in folder.rglob('*'):
            if path.is_file() and (path.name in allowed or (path.name.startswith('manual-') and path.suffix in ('.json','.log'))):
                z.write(path,arcname=path.relative_to(folder).as_posix())
    print('\n'.join(summary));print('ZIP:',destination)


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='action',required=True)
    m=sub.add_parser('run');m.add_argument('folder',type=Path)
    m.add_argument('--variant',choices=('compiled-pyte','source-pyte'),required=True)
    m.add_argument('--platform',choices=('xcb','wayland'),default='xcb')
    z=sub.add_parser('report');z.add_argument('folder',type=Path)
    z.add_argument('--zip',type=Path,default=Path.home()/'Downloads/ShellDeck_Pyte_201-203_Ergebnisse.zip')
    a=p.parse_args()
    try:
        return manual(a.folder,a.variant,a.platform) if a.action=='run' else (package(a.folder,a.zip) or 0)
    except (OSError,ValueError,KeyError,json.JSONDecodeError) as exc:
        print('FEHLER:',exc,file=sys.stderr)
        return 2

if __name__=='__main__':
    raise SystemExit(main())
