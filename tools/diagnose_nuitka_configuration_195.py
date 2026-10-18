#!/usr/bin/env python3
"""Read-only inventory of Nuitka/Python/Qt environment for crash comparisons."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def collect(root: Path) -> dict:
    python = root / '.venv/bin/python'
    if not python.is_file():
        raise FileNotFoundError(f'Projekt-Python fehlt: {python}')
    command = [str(python), '-c',
        'import json,platform,sys,importlib.metadata as m; '
        'print(json.dumps({"python":sys.version,"executable":sys.executable,'
        '"nuitka":m.version("Nuitka"),"pyside6":m.version("PySide6"),'
        '"pyte":m.version("pyte")}))']
    result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=True)
    metadata = json.loads(result.stdout)
    metadata['system'] = platform.platform()
    metadata['root'] = str(root)
    metadata['qt_plugin_env'] = {key: os.environ.get(key, '') for key in
        ('QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH', 'PYTHONPATH', 'LD_LIBRARY_PATH')}
    metadata['note'] = 'Inventar; keine Aussage ueber tatsaechlich geladene Qt-Libraries.'
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    data = collect(args.root.resolve())
    payload = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload + '\n', encoding='utf-8')
    print(payload)


if __name__ == '__main__':
    main()
