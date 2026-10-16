"""Bash-Readline mit kurzem und ANSI-farbigem Prompt vergleichen."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from shelldeck_bash_readline_probe_087 import run

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=Path.home() / 'Downloads' / 'ShellDeck_Bash_Readline_088.json')
    args = p.parse_args()
    cases = {name: run(prompt_mode=name) for name in ('plain', 'colored')}
    report = {'profiles': cases, 'passed': all(x['passed'] for x in cases.values())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    for name, case in cases.items():
        bad = [s['step'] for s in case['steps'] if not (s['expected_present'] and s['cursor_at_end'])]
        print(f'{name}: {"OK" if not bad else "Abweichung " + ", ".join(bad)}')
    print('Bericht:', args.output)
    return 0 if report['passed'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
