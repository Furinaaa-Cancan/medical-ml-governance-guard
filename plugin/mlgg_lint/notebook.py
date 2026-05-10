"""Jupyter notebook (.ipynb) support — extract Python source from code cells."""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class CellMapping:
    """Maps virtual-source lines back to a notebook cell."""

    cell_index: int
    cell_start_line: int  # 1-based start in virtual source
    cell_end_line: int  # 1-based end in virtual source (inclusive)


@dataclass
class SkippedCell:
    """A cell excluded from the virtual source.

    Attributes:
        cell_index: 0-based index of the cell in the notebook.
        first_line_excerpt: First non-empty line of the cell, truncated to
            60 characters for display.
        error: Reason the cell was skipped (e.g. ``"non_python_r"``,
            ``"cell_magic"``, ``"non_python_bash"``, ``"syntax_error: <msg>"``).
    """

    cell_index: int
    first_line_excerpt: str
    error: str


# ── Heuristic patterns ─────────────────────────────────────────────────────

# A line that's an R-style assignment (``<-``).  We exclude HTML-comment-like
# tokens and Python's left-arrow comparison patterns by requiring whitespace.
_R_ASSIGN_RE = re.compile(r"(?:^|\s)<-\s*\S")
_R_HINT_RE = re.compile(r"\b(library|function|c|read\.csv)\s*\(")

_BASH_FIRST_LINE_RE = re.compile(
    r"^\s*(?:cd|mkdir)\s+\S",
)
# bash-style "for X in Y; do ..." or "for X in Y\n do ..."
_BASH_FOR_RE = re.compile(
    r"^\s*for\s+\S+\s+in\s+.+\s+do\b",
)


def _first_non_empty_line(text: str) -> str:
    """Return the first non-empty, non-whitespace line, or ``""``."""
    for line in text.splitlines():
        if line.strip():
            return line
    return ""


def _first_non_comment_line(text: str) -> str:
    """Return the first non-comment, non-empty line.  Comments are ``#``-prefixed
    after stripping leading whitespace.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        return line
    return ""


def _looks_like_r(cell_source: str) -> bool:
    """Heuristic: True if the cell contains R-style assignment AND at least
    one R-only construct.

    We require BOTH conditions so that Python code containing comparisons
    (``a < -1``) is not misclassified.  The regex requires the ``<-`` to be
    preceded by whitespace (or start-of-line) and followed by a non-space,
    which excludes ``a < -1`` (space after ``-``) but matches ``x <- 1``.
    """
    if not _R_ASSIGN_RE.search(cell_source):
        return False
    return bool(_R_HINT_RE.search(cell_source))


def _looks_like_bash(cell_source: str) -> bool:
    """Heuristic: True if the first non-comment line looks like a shell
    command (``cd``, ``mkdir``, or ``for X in Y do``).
    """
    line = _first_non_comment_line(cell_source)
    if not line:
        return False
    if _BASH_FIRST_LINE_RE.match(line):
        return True
    if _BASH_FOR_RE.match(line):
        return True
    return False


def _starts_with_cell_magic(cell_source: str) -> bool:
    """True if first non-empty line begins with ``%%`` (cell magic)."""
    line = _first_non_empty_line(cell_source)
    return line.lstrip().startswith("%%")


def _strip_ipython_magics(cell_lines: List[str]) -> List[str]:
    """Return a copy of *cell_lines* with IPython-only line syntax replaced
    by blank lines (preserving line numbers).

    Handles:
    * Line magics: ``%foo``
    * Shell escapes: ``!foo``
    * Help magics: ``foo?`` / ``?foo``
    * ``get_ipython()`` direct calls.
    """
    out = list(cell_lines)
    for i, ln in enumerate(out):
        stripped = ln.strip()
        if (stripped.startswith(("%", "!", "?"))
                or stripped.endswith("?")
                or stripped.startswith("get_ipython()")):
            out[i] = ""
    return out


def _classify_cell(cell_source: str) -> Optional[str]:
    """Return a skip reason if the cell is non-Python, else ``None``.

    Order matters: we check non-Python heuristics before cell-magic so that
    a notebook with ``%%bash`` followed by shell commands gets the
    ``cell_magic`` reason (more specific) and an R cell gets ``non_python_r``.
    """
    # Cell magic on the first non-empty line forces the entire cell to be
    # treated as non-Python (per spec: ``%%bash`` etc.)
    if _starts_with_cell_magic(cell_source):
        return "cell_magic"
    if _looks_like_r(cell_source):
        return "non_python_r"
    if _looks_like_bash(cell_source):
        return "non_python_bash"
    return None


def _excerpt(cell_source: str, max_chars: int = 60) -> str:
    """First non-empty line, truncated to *max_chars* (with ellipsis)."""
    line = _first_non_empty_line(cell_source)
    if len(line) > max_chars:
        return line[: max_chars - 1].rstrip() + "…"
    return line


def _load_notebook_cells(path: Path) -> Optional[list]:
    """Load and validate notebook structure.  Returns the cells list or
    ``None`` for malformed / unsupported notebooks.
    """
    try:
        raw = path.read_text(encoding="utf-8")
        nb = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None

    nbformat = nb.get("nbformat")
    if not isinstance(nbformat, int) or nbformat < 4:
        return None

    cells = nb.get("cells")
    if not isinstance(cells, list):
        return None
    return cells


def extract_notebook_source(path: Path) -> Tuple[str, List[CellMapping]]:
    """Read a ``.ipynb`` file and return concatenated code-cell source.

    Returns ``(virtual_source, mappings)`` where *virtual_source* is a single
    Python string with cell-boundary comments and *mappings* lets callers
    translate virtual-source line numbers back to ``(cell_index, cell_line)``.

    Gracefully returns ``("", [])`` for malformed notebooks.

    .. note:: This function is preserved for backward compatibility.  The
       engine uses :func:`extract_notebook_source_with_validation`, which
       additionally returns information about cells that were skipped.
    """
    source, mappings, _ = extract_notebook_source_with_validation(path)
    return source, mappings


def extract_notebook_source_with_validation(
    path: Path,
) -> Tuple[str, List[CellMapping], List[SkippedCell]]:
    """Read a ``.ipynb`` file with per-cell validation.

    For each code cell:
      1. Skip non-Python cells detected via heuristics
         (``cell_magic`` / ``non_python_r`` / ``non_python_bash``).
      2. Strip IPython-only line syntax (``%foo``, ``!foo``, ``foo?``).
      3. Attempt :func:`ast.parse` on the cleaned cell.  If it fails, the
         cell is excluded from the virtual source and an entry is appended
         to *skipped_cells* with ``error="syntax_error: <message>"``.
      4. Otherwise the cell is concatenated into the virtual source.

    Returns ``(virtual_source, mappings, skipped_cells)``.

    For malformed notebooks (bad JSON, ``nbformat<4``, missing cells), all
    three return values are empty (``("", [], [])``); the engine then
    surfaces a single ``E000 ERROR`` to preserve existing behaviour.
    """
    cells = _load_notebook_cells(path)
    if cells is None:
        return ("", [], [])

    lines: List[str] = []
    mappings: List[CellMapping] = []
    skipped: List[SkippedCell] = []
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

        # Empty cells are silently dropped (no diagnostic value).
        if not cell_source.strip():
            continue

        # Stage 1: non-Python classification (magics, R, bash).
        reason = _classify_cell(cell_source)
        if reason is not None:
            skipped.append(SkippedCell(
                cell_index=idx,
                first_line_excerpt=_excerpt(cell_source),
                error=reason,
            ))
            continue

        # Stage 2: strip IPython line magics, then ast.parse the cleaned cell.
        cell_lines = cell_source.splitlines()
        cell_lines = _strip_ipython_magics(cell_lines)
        cleaned = "\n".join(cell_lines)

        try:
            ast.parse(cleaned, filename=f"<cell {idx}>")
        except SyntaxError as exc:
            skipped.append(SkippedCell(
                cell_index=idx,
                first_line_excerpt=_excerpt(cell_source),
                error=f"syntax_error: {exc.msg}",
            ))
            continue

        # Stage 3: emit cell into virtual source with boundary header.
        header = f"# --- cell {idx} ---"
        lines.append(header)
        current_line += 1  # the header occupies one line

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
    return (virtual_source, mappings, skipped)


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
