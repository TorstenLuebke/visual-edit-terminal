#!/usr/bin/env python3
"""Compare ShellDeck/pyte VT screen against Vim's independent +terminal emulator.

Uses project pyte and a locally installed Vim built with +terminal. No changes
are made to the production terminal. Incomplete-frame checkpoints may differ;
review the JSON rather than interpreting every difference as a parser defect.
"""
from __future__ import annotations

import argparse
import re
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ENTER = b"\x1b[?1049h"
EXIT = b"\x1b[?1049l"


def vt_interval(data: bytes) -> tuple[int, int]:
    start = data.find(ENTER)
    if start < 0:
        raise ValueError("Kein Wechsel in Alternate Screen (CSI ?1049h) gefunden")
    stop = data.find(EXIT, start + len(ENTER))
    return start, len(data) if stop < 0 else stop


def start_geometry(path: Path) -> tuple[int, int]:
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "trace_started":
            rows, cols = int(event["rows"]), int(event["cols"])
            if rows <= 0 or cols <= 0:
                raise ValueError("Ungueltige Anfangsgeometrie")
            return rows, cols
    raise ValueError("Ereignis trace_started fehlt")


def checkpoints(raw: bytes, count: int = 5) -> list[int]:
    if count < 1:
        raise ValueError("count muss positiv sein")
    start, stop = vt_interval(raw)
    length = stop - start
    return sorted(set(start + max(1, length * i // (count + 1)) for i in range(1, count + 1)))


def margin_reset_checkpoints(raw: bytes, rows: int, limit: int = 6) -> list[int]:
    """Choose offsets just after restoring full-screen scrolling margins.

    htop updates a restricted scroll area, then usually restores CSI 1;Nr.
    Capture after that complete control sequence instead of dividing the
    stream at arbitrary byte offsets. This is only a *candidate* frame
    boundary: no claim is made that an entire htop refresh has finished.
    """
    if limit < 1:
        raise ValueError("limit muss positiv sein")
    start, stop = vt_interval(raw)
    pattern = re.compile(rb"\x1b\[1;" + str(rows).encode("ascii") + rb"r")
    positions = [match.end() for match in pattern.finditer(raw, start, stop)]
    if len(positions) <= limit:
        return positions
    # Evenly sample all margin resets, retaining first and last.
    selected = [positions[(len(positions) - 1) * i // (limit - 1)]
                for i in range(limit)] if limit > 1 else [positions[0]]
    return sorted(set(selected))


def synthetic_overwrite_trace() -> bytes:
    """Minimal VT fixture: shorter line must not retain a previous suffix."""
    return (ENTER + b"\x1b[1;1H1234 very-very-long-command"
            + b"\x1b[1;1H1234 short\x1b[K")


def vim_quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def vim_supported(binary: str = "vim") -> bool:
    found = shutil.which(binary)
    if not found:
        return False
    result = subprocess.run([found, "--version"], capture_output=True, text=True, check=False)
    return result.returncode == 0 and "+terminal" in result.stdout


def vim_screen(data: bytes, rows: int, cols: int, *, binary: str = "vim") -> list[str]:
    """Render a raw prefix with Vim's terminal emulator in isolated Ex mode."""
    if not vim_supported(binary):
        raise RuntimeError("Vim mit +terminal wird fuer den Referenzvergleich benoetigt")
    with tempfile.TemporaryDirectory(prefix="shelldeck_vim_ref_") as directory:
        root = Path(directory)
        capture = root / "trace.bin"
        script = root / "render.vim"
        output = root / "screen.json"
        capture.write_bytes(data)
        script.write_text("\n".join([
            "set nomore",
            "set noswapfile",
            "let g:term = term_start(['cat', " + vim_quote(str(capture)) + "], "
            "{'term_rows': " + str(rows) + ", 'term_cols': " + str(cols) + ", 'term_finish': 'open'})",
            "let g:attempt = 0",
            "while term_getstatus(g:term) =~# 'running' && g:attempt < 200",
            "  call term_wait(g:term, 100)",
            "  let g:attempt += 1",
            "endwhile",
            "if term_getstatus(g:term) =~# 'running'",
            "  cquit 9",
            "endif",
            "call term_wait(g:term, 100)",
            "let g:lines = []",
            "let g:scrolled = term_getscrolled(g:term)",
            "for g:i in range(1, " + str(rows) + ")",
            "  call add(g:lines, term_getline(g:term, g:scrolled + g:i))",
            "endfor",
            "call writefile([json_encode(g:lines)], " + vim_quote(str(output)) + ")",
            "qa!",
        ]) + "\n", encoding="utf-8")
        completed = subprocess.run([binary, "-Nu", "NONE", "-i", "NONE", "-n", "-es", "-S", str(script)],
                                   stdin=subprocess.DEVNULL, capture_output=True, timeout=60, check=False)
        if completed.returncode or not output.exists():
            raise RuntimeError("Vim-Referenz fehlgeschlagen: " + completed.stderr.decode("utf-8", "replace")[-800:])
        lines = json.loads(output.read_text(encoding="utf-8"))
        if len(lines) != rows:
            raise RuntimeError(f"Vim lieferte {len(lines)} statt {rows} Zeilen")
        return lines


def pyte_screens(raw: bytes, rows: int, cols: int, offsets: list[int]) -> dict[int, list[str]]:
    from shelldeck_vt_screen import VtScreen
    model = VtScreen(rows=rows, cols=cols, enable_history=False)
    previous = 0
    result = {}
    for offset in offsets:
        model.feed(raw[previous:offset])
        result[offset] = list(model.display())
        previous = offset
    return result


def compare(raw: bytes, events: Path, count: int = 5, limit: int = 8, *, binary: str = "vim", checkpoint_mode: str = "margin") -> dict:
    rows, cols = start_geometry(events)
    if checkpoint_mode not in ("margin", "uniform"):
        raise ValueError("Unbekannter checkpoint_mode")
    offsets = (margin_reset_checkpoints(raw, rows, count) if checkpoint_mode == "margin"
               else checkpoints(raw, count))
    if not offsets:
        raise ValueError("Keine geeigneten Prüfstellen gefunden; --mode uniform verwenden")
    pyte = pyte_screens(raw, rows, cols, offsets)
    snapshots = []
    for offset in offsets:
        reference = vim_screen(raw[:offset], rows, cols, binary=binary)
        model = pyte[offset]
        # Vim strips right-hand blank cells; compare rendered characters only.
        differing = [dict(row=index, shell_deck=a.rstrip(), vim=b.rstrip())
                     for index, (a, b) in enumerate(zip(model, reference)) if a.rstrip() != b.rstrip()]
        snapshots.append(dict(byte_offset=offset, different_rows=len(differing), examples=differing[:limit]))
    return {"geometry": {"rows": rows, "cols": cols}, "raw_bytes": len(raw),
            "reference": "Vim +terminal (independent of pyte)",
            "checkpoint_mode": checkpoint_mode,
            "checkpoint_warning": "Auch ein Scrollbereich-Reset beweist keinen vollstaendigen htop-Frame.",
            "snapshots": snapshots}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("raw", type=Path)
    parser.add_argument("events", type=Path)
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--mode", choices=("margin", "uniform"), default="margin",
                        help="Prüfpunkte nach Scrollbereich-Reset oder gleichverteilt")
    parser.add_argument("--out", type=Path, default=Path.home() / "Downloads" / "ShellDeck_VT_Vim_Vergleich_077.json")
    args = parser.parse_args()
    if not vim_supported():
        parser.error("Vim mit +terminal fehlt (pruefen: vim --version)")
    report = compare(args.raw.read_bytes(), args.events, args.count, checkpoint_mode=args.mode)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Bericht: {args.out}")
    for s in report["snapshots"]:
        print(f"Byte {s['byte_offset']}: {s['different_rows']} unterschiedliche Zeilen")
    print("Ein Unterschied beweist noch keinen Fehler in pyte oder Vim.")


if __name__ == "__main__":
    main()
