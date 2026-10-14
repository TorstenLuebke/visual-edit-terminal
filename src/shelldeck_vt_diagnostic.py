"""Opt-in VT model snapshot for comparison with the Qt-rendered image.

No file I/O, logging, tracking or automatic collection in this module.
"""

from __future__ import annotations


def model_snapshot(model) -> str:
    """Return the *visible* model cells with exact column positions.

    Diagnostic may contain confidential terminal data. Never call implicitly.
    """
    rows, cols = model.rows, model.cols
    cursor = model.cursor
    lines = [
        "ShellDeck VT-Diagnose (manuell)",
        f"rows={rows} cols={cols} alternate={model.in_alternate_screen()}",
        f"cursor=({cursor['y']},{cursor['x']}) hidden={cursor['hidden']}",
        "Legend: row indices and exactly cols terminal cells between | markers.",
    ]
    for y in range(rows):
        cells = model.row_cells(y)
        # Delimiters make trailing blanks visible. Keep complete cell layout.
        content = "".join(str(cell.get("char") or " ") for cell in cells)
        lines.append(f"{y:04d}|{content}|")
    return "\n".join(lines) + "\n"
