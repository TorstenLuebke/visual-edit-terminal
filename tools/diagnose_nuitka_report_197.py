#!/usr/bin/env python3
"""Summarize a Nuitka matrix and create a logs-only ZIP without binaries."""
import argparse
from pathlib import Path
import json
import zipfile


def build_report(folder: Path) -> tuple[str, list[dict]]:
    records_file=folder/'results.json'
    if not records_file.is_file():
        raise FileNotFoundError(f'Keine Ergebnisse gefunden: {records_file}')
    records=json.loads(records_file.read_text(encoding='utf-8'))
    lines=['ShellDeck Nuitka Native-GC Vergleich', f'Diagnoseordner: {folder}',
           'Exit 0: erfolgreich; 139/-11: SIGSEGV; 124: Zeitlimit.',
           'Tests vergleichen isolierten Renderer, nicht die gesamte App.', '']
    for record in records:
        values=record.get('runs',[])
        lines.append(f"{record['variant']}: Build={record['build_exit']}; Laeufe={values}; Flags={' '.join(record['flags'])}")
        if record.get('error'):lines.append('  '+record['error'])
    lines += ['', 'Ein erfolgreicher isolierter Renderer-Test ist keine Freigabe des kompletten ShellDeck.']
    return '\n'.join(lines)+'\n',records


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--zip',dest='zip_path',type=Path)
    args=parser.parse_args()
    folder=args.folder.resolve()
    report,records=build_report(folder)
    (folder/'summary.txt').write_text(report,encoding='utf-8')
    print(report)
    target=args.zip_path or folder.parent/(folder.name+'-logs.zip')
    target=target.resolve()
    target.parent.mkdir(parents=True,exist_ok=True)
    # Explicit allowlist: no compiled binaries, no source trees, no memory dumps.
    allowed={'summary.txt','results.json','configuration.json','source.log','source.exit'}
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as zipfile_out:
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.is_symlink():continue
            if path.name not in allowed and not (path.name.startswith(('run-','build.')) and path.suffix in ('.log','.exit')):
                continue
            zipfile_out.write(path,path.relative_to(folder))
    print('ZIP:',target)


if __name__=='__main__':
    main()
