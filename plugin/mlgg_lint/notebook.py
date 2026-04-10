"""Jupyter notebook (.ipynb) support — extract Python source from code cells."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


@dataclass
class CellMapping:
    """Maps virtual-source lines back to a notebook cell."""

    cell_index: int
    cell_start_line: int  # 1-based start in virtual source
    cell_end_line: int  # 1-based end in virtual source (inclusive)


def extract_notebook_source(path: Path) -> Tuple[str, List[CellMapping]]:
    """Read a ``.ipynb`` file and return concatenated code-cell source.

    Returns ``(virtual_source, mappings)`` where *virtual_source* is a single
    Python string with cell-boundary comments and *mappings* lets callers
    translate virtual-source line numbers back to ``(cell_index, cell_line)``.

    Gracefully returns ``("", [])`` for malformed notebooks.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        nb = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ("", [])

    # Validate nbformat >= 4
    nbformat = nb.get("nbformat")
    if not isinstance(nbformat, int) or nbformat < 4:
        return ("", [])

    cells = nb.get("cells")
    if not isinstance(cells, list):
        return ("", [])

    lines: List[str] = []
    mappings: List[CellMapping] = []
    current_line = 1  # 1-based

    for idx, cell in enumerate(cells):
        if not isinstance(cell, dict):
            continue
        if cell.get("cell_type") != "code":
            continue

        source = cell.get("source")
        if isinstance(source, list):
            cell_source = "".join(source)
        elif isinstance(source, str):
            cell_source = source
        else:
            continue

        # Add cell boundary comment
        header = f"# --- cell {idx} ---"
        lines.append(header)
        current_line += 1  # skip the header line

        cell_lines = cell_source.splitlines()
        # Strip IPython-only syntax that causes ast.parse() to fail.
        # Replace with blank lines to preserve line numbers.
        for i, ln in enumerate(cell_lines):
            stripped = ln.strip()
            if (stripped.startswith(("%", "!", "?"))
                    or stripped.endswith("?")
                    or stripped.startswith("get_ipython()")):
                cell_lines[i] = ""
        if not cell_lines:
            continue

        start = current_line
        lines.extend(cell_lines)
        end = current_line + len(cell_lines) - 1
        current_line = end + 1

        mappings.append(CellMapping(
            cell_index=idx,
            cell_start_line=start,
            cell_end_line=end,
        ))

    virtual_source = "\n".join(lines) + "\n" if lines else ""
    return (virtual_source, mappings)


def map_line_to_cell(
    line: int, mappings: List[CellMapping]
) -> Tuple[int, int] | None:
    """Translate a virtual-source line number to ``(cell_index, line_within_cell)``.

    Returns *None* if the line falls outside any cell (e.g. on a boundary
    comment).
    """
    for m in mappings:
        if m.cell_start_line <= line <= m.cell_end_line:
            return (m.cell_index, line - m.cell_start_line + 1)
    return None
