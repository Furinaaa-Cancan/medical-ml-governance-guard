"""Tests for per-cell notebook parsing fallback (E000 fix).

Verifies that cells which fail ``ast.parse`` (R code, ``%%bash`` magics,
shell commands) are skipped individually instead of aborting the whole
notebook.  Well-formed Python cells continue to be analysed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from mlgg_lint.config import LintConfig
from mlgg_lint.engine import analyze_file
from mlgg_lint.models import Severity
from mlgg_lint.notebook import (
    SkippedCell,
    extract_notebook_source_with_validation,
)

NOTEBOOK_DIR = Path(__file__).parent / "samples" / "notebooks"


# ── Helpers ────────────────────────────────────────────────────────────────


def _make_notebook(cells: List[str], nbformat: int = 4) -> Dict[str, Any]:
    """Build a minimal .ipynb dict from a list of code-cell sources."""
    nb_cells = []
    for src in cells:
        nb_cells.append({
            "cell_type": "code",
            "metadata": {},
            "source": src.splitlines(keepends=True),
            "outputs": [],
            "execution_count": None,
        })
    return {
        "nbformat": nbformat,
        "nbformat_minor": 5,
        "metadata": {},
        "cells": nb_cells,
    }


def _write_nb(path: Path, nb: Dict[str, Any]) -> Path:
    path.write_text(json.dumps(nb), encoding="utf-8")
    return path


# ── Fixture-backed tests ──────────────────────────────────────────────────


def test_mixed_r_python_skips_r_cell_only():
    """First cell is R, others are Python — only the R cell is skipped and
    the Python cells are analysed normally.
    """
    nb_path = NOTEBOOK_DIR / "mixed_r_python.ipynb"
    diags = analyze_file(nb_path, config=LintConfig())

    # Exactly one cell skipped, with R reason.
    skipped = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-cell-skipped"
    ]
    assert len(skipped) == 1, (
        f"Expected 1 skipped-cell INFO; got {len(skipped)}: {[d.message for d in skipped]}"
    )
    assert skipped[0].severity == Severity.INFO
    assert "non_python_r" in skipped[0].message

    # Python cells were actually analysed — at minimum we expect any
    # diagnostic from a real rule to appear.  The fixture's last cell uses
    # accuracy/auc without CI (R009) and does not pass random_state, so
    # something downstream of cell 0 should fire.
    rule_diags = [d for d in diags if d.rule_id != "E000"]
    assert len(rule_diags) >= 1, (
        "Expected at least one rule finding from the Python cells; "
        f"got only: {[d.rule_id for d in diags]}"
    )

    # No notebook-no-python-cells INFO (we DID have Python cells).
    no_python = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-no-python-cells"
    ]
    assert no_python == []


def test_cell_magic_bash_skipped_as_info():
    """A cell whose first line is ``%%bash`` is skipped with reason
    ``cell_magic`` — the remaining Python cell is analysed.
    """
    nb_path = NOTEBOOK_DIR / "cell_magic_bash.ipynb"
    diags = analyze_file(nb_path, config=LintConfig())

    skipped = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-cell-skipped"
    ]
    assert len(skipped) == 1
    assert skipped[0].severity == Severity.INFO
    assert "cell_magic" in skipped[0].message

    # No fatal E000 ERROR should be emitted.
    fatal = [
        d for d in diags
        if d.rule_id == "E000" and d.severity == Severity.ERROR
    ]
    assert fatal == [], f"Unexpected fatal E000: {[d.message for d in fatal]}"


def test_all_r_emits_no_python_cells_info():
    """A notebook whose every cell is R should emit exactly ONE
    ``notebook-no-python-cells`` INFO and per-cell skip records, not a fatal
    E000 ERROR.
    """
    nb_path = NOTEBOOK_DIR / "all_r.ipynb"
    diags = analyze_file(nb_path, config=LintConfig())

    no_python = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-no-python-cells"
    ]
    assert len(no_python) == 1
    assert no_python[0].severity == Severity.INFO

    # No fatal ERROR.
    fatal = [
        d for d in diags
        if d.rule_id == "E000" and d.severity == Severity.ERROR
    ]
    assert fatal == [], f"Unexpected fatal E000: {[d.message for d in fatal]}"

    # Per-cell skip records exist for each R cell.
    skipped = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-cell-skipped"
    ]
    assert len(skipped) >= 3
    for sk in skipped:
        assert sk.severity == Severity.INFO
        assert "non_python_r" in sk.message


# ── Inline tests for edge behaviour ───────────────────────────────────────


def test_nbformat_below_4_preserves_error(tmp_path):
    """Existing behaviour: ``nbformat < 4`` produces a single E000 ERROR."""
    nb = _make_notebook(["x = 1\n"], nbformat=3)
    nb_path = _write_nb(tmp_path / "old.ipynb", nb)
    diags = analyze_file(nb_path, config=LintConfig())
    assert len(diags) == 1
    assert diags[0].rule_id == "E000"
    assert diags[0].severity == Severity.ERROR
    assert diags[0].rule_name == "notebook-parse-error"


def test_unicode_only_string_no_false_skip(tmp_path):
    """A Python cell whose only content is a unicode string literal must
    parse cleanly and NOT be skipped.
    """
    nb = _make_notebook([
        "msg = '日本語テスト —— ünïcödë ✨'\n",
        "from sklearn.model_selection import train_test_split\n"
        "X_train, X_test, y_train, y_test = train_test_split(X, y)\n",
    ])
    nb_path = _write_nb(tmp_path / "unicode.ipynb", nb)
    diags = analyze_file(nb_path, config=LintConfig())

    skipped = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-cell-skipped"
    ]
    assert skipped == [], (
        f"Unicode-only cell should not be skipped; got: {[d.message for d in skipped]}"
    )

    no_python = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-no-python-cells"
    ]
    assert no_python == []


def test_extract_with_validation_returns_skipped_cells(tmp_path):
    """Direct API: function returns ``(virtual_source, mappings, skipped)``
    and skipped cells carry the expected metadata.
    """
    nb = _make_notebook([
        "library(dplyr)\ndf <- read.csv('a.csv')\n",  # R
        "x = 1\ny = 2\n",                              # Python
        "%%bash\ncd /tmp\n",                           # cell magic
    ])
    nb_path = _write_nb(tmp_path / "mix.ipynb", nb)

    source, mappings, skipped = extract_notebook_source_with_validation(nb_path)

    assert "x = 1" in source
    assert len(mappings) == 1
    assert mappings[0].cell_index == 1

    indexes = sorted(s.cell_index for s in skipped)
    assert indexes == [0, 2]

    reasons = {s.cell_index: s.error for s in skipped}
    assert reasons[0] == "non_python_r"
    assert reasons[2] == "cell_magic"

    for sk in skipped:
        assert isinstance(sk, SkippedCell)
        assert 0 < len(sk.first_line_excerpt) <= 60


def test_python_with_line_magic_not_skipped(tmp_path):
    """A Python cell that contains a single-line magic (``%matplotlib``)
    must still be analysed — line magics are stripped, not whole-cell.
    """
    nb = _make_notebook([
        "%matplotlib inline\n"
        "import pandas as pd\n"
        "df = pd.read_csv('a.csv')\n",
    ])
    nb_path = _write_nb(tmp_path / "linemagic.ipynb", nb)
    source, mappings, skipped = extract_notebook_source_with_validation(nb_path)
    assert skipped == []
    assert len(mappings) == 1
    assert "import pandas" in source


def test_syntax_error_cell_skipped_with_reason(tmp_path):
    """A Python cell with genuine syntax errors is skipped individually,
    not fatally — and other cells are still analysed.
    """
    nb = _make_notebook([
        "def broken(\n",                       # syntax error
        "from sklearn.model_selection import train_test_split\n"
        "X_train, X_test, y_train, y_test = train_test_split(X, y)\n",
    ])
    nb_path = _write_nb(tmp_path / "broken.ipynb", nb)
    diags = analyze_file(nb_path, config=LintConfig())

    skipped = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-cell-skipped"
    ]
    assert len(skipped) == 1
    assert skipped[0].severity == Severity.INFO
    assert "syntax_error" in skipped[0].message
    # No fatal ERROR.
    fatal = [d for d in diags if d.severity == Severity.ERROR]
    assert fatal == []


def test_legacy_extract_notebook_source_compat(tmp_path):
    """The legacy ``extract_notebook_source`` API still returns
    ``(virtual_source, mappings)`` — third value is dropped for callers.
    """
    from mlgg_lint.notebook import extract_notebook_source

    nb = _make_notebook(["x = 1\n", "y = 2\n"])
    nb_path = _write_nb(tmp_path / "legacy.ipynb", nb)
    result = extract_notebook_source(nb_path)
    assert isinstance(result, tuple)
    assert len(result) == 2
    source, mappings = result
    assert "x = 1" in source
    assert len(mappings) == 2


def test_severity_threshold_excludes_info(tmp_path):
    """Per-cell INFO diagnostics respect ``severity_threshold='warning'``."""
    nb = _make_notebook([
        "library(dplyr)\ndf <- read.csv('a.csv')\n",
        "x = 1\n",
    ])
    nb_path = _write_nb(tmp_path / "thresh.ipynb", nb)
    diags = analyze_file(nb_path, config=LintConfig(severity_threshold="warning"))
    skipped = [
        d for d in diags
        if d.rule_id == "E000" and d.rule_name == "notebook-cell-skipped"
    ]
    assert skipped == [], (
        "INFO-severity skip records must be filtered out at threshold='warning'"
    )
