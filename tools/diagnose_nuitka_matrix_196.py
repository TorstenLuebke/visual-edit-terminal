#!/usr/bin/env python3
"""Standalone renderer build matrix; never modifies installed ShellDeck.

Runs one factor at a time relative to the project build settings. Variants
are comparison builds, not automatically endorsed production configurations.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime

VARIANTS = {
    'project-flags': ['--unstripped', '--debug', '--no-debug-immortal-assumptions', '--experimental=disable-freelist-all'],
    'without-immortal-flag': ['--unstripped', '--debug', '--experimental=disable-freelist-all'],
    'without-debug-flag': ['--unstripped', '--no-debug-immortal-assumptions', '--experimental=disable-freelist-all'],
    'normal-freelists': ['--unstripped', '--debug', '--no-debug-immortal-assumptions'],
}


def execute(cmd, log: Path, *, cwd: Path, env: dict, seconds: int) -> int:
    with log.open('w', encoding='utf-8', errors='replace') as handle:
        try:
            result = subprocess.run(cmd, cwd=cwd, env=env, stdout=handle,
                                    stderr=subprocess.STDOUT, timeout=seconds, check=False)
            return result.returncode
        except subprocess.TimeoutExpired:
            handle.write(f'\nTIMEOUT after {seconds}s\n')
            return 124
        except OSError as exc:
            handle.write(f'\nEXEC ERROR: {exc}\n')
            return 127


def run(root: Path, output: Path, variants: list[str], lines: int, repeat: int,
        build_timeout: int) -> int:
    py = root / '.venv/bin/python'
    entry = root / 'tools/diagnose_vt_renderer_185.py'
    if not py.is_file() or not entry.is_file():
        print('Fehler: Projekt-Python oder Renderer-Diagnose fehlt.', file=sys.stderr)
        return 2
    output.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env['PYTHONPATH'] = str(root / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    env['QT_QPA_PLATFORM'] = 'offscreen'
    # A small interpreted test must pass before initiating any expensive build.
    source_rc = execute([str(py), str(entry), '--lines', '256'], output/'source.log',
                        cwd=root, env=env, seconds=35)
    (output/'source.exit').write_text(str(source_rc)+'\n')
    if source_rc:
        print('Quelltest fehlgeschlagen:', output/'source.log', file=sys.stderr)
        return 3
    results=[]
    for variant in variants:
        dest=output/variant
        dest.mkdir(exist_ok=True)
        flags=VARIANTS[variant]
        cmd=[str(py), '-m', 'nuitka', '--standalone', '--lto=no', '--jobs=4',
             '--include-package=pyte', '--enable-plugin=pyside6',
             '--include-module=shelldeck_vt_screen', '--include-module=shelldeck_terminal_grid',
             '--output-dir='+str(dest/'compiled'), '--output-filename=RendererProbe',
             *flags, str(entry)]
        (dest/'command.json').write_text(json.dumps(cmd, indent=2)+'\n')
        print('BUILD',variant,flush=True)
        rc=execute(cmd,dest/'build.log',cwd=root,env=env,seconds=build_timeout)
        (dest/'build.exit').write_text(str(rc)+'\n')
        entry_record={'variant':variant,'flags':flags,'build_exit':rc,'runs':[]}
        binary=dest/'compiled/diagnose_vt_renderer_185.dist/RendererProbe'
        # Nuitka sometimes uses output filename as distribution directory instead.
        other=dest/'compiled/RendererProbe.dist/RendererProbe'
        if not binary.is_file() and other.is_file():
            binary=other
        if rc==0 and binary.is_file():
            for index in range(1,repeat+1):
                print('RUN',variant,index,flush=True)
                run_rc=execute([str(binary),'--lines',str(lines)],
                               dest/f'run-{index:02}.log',cwd=root,env=env,seconds=240)
                (dest/f'run-{index:02}.exit').write_text(str(run_rc)+'\n')
                entry_record['runs'].append(run_rc)
        elif rc==0:
            entry_record['error']='Ausfuehrbare Datei nach Build nicht gefunden'
        results.append(entry_record)
        (output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    print('Ergebnisse:',output/'results.json')
    return 0 if all(r['build_exit']==0 and len(r['runs'])==repeat and all(x==0 for x in r['runs']) for r in results) else 1


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out',type=Path,default=None)
    parser.add_argument('--variants',nargs='+',choices=VARIANTS,default=list(VARIANTS))
    parser.add_argument('--lines',type=int,default=50000)
    parser.add_argument('--repeat',type=int,default=2)
    parser.add_argument('--build-timeout',type=int,default=1800)
    args=parser.parse_args()
    if args.lines<1 or not 1<=args.repeat<=10 or args.build_timeout<30:
        parser.error('--lines > 0, --repeat 1..10, --build-timeout >= 30 erforderlich')
    output=args.out or Path.home()/'Downloads'/('shelldeck-nuitka-matrix-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    raise SystemExit(run(args.root.resolve(),output.resolve(),args.variants,args.lines,args.repeat,args.build_timeout))


if __name__=='__main__':
    main()
