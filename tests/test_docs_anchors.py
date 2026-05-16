"""Verify symbolic anchors in docs/RAG_TROUBLESHOOTING.md still resolve.

H18: replaced fragile line numbers with function/constant anchors.
This test grep-checks each cited anchor exists in the target file.
Fails when refactors rename or delete a cited symbol so docs can't
silently rot.
"""
import re
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs/RAG_TROUBLESHOOTING.md"


def test_all_symbolic_anchors_resolve():
    """Every `path/to/file.py::symbol` reference should grep-locate."""
    if not DOC.exists():
        pytest.skip("doc not present")
    text = DOC.read_text()
    # Pattern: `path/to/file.py::symbol_name` (pytest-style)
    pattern = re.compile(r"`([a-zA-Z0-9_/]+\.py)::([a-zA-Z0-9_]+)`")
    anchors = pattern.findall(text)
    assert anchors, "no symbolic anchors found in doc -- H18 fix incomplete?"

    missing = []
    for filepath, symbol in anchors:
        full = REPO_ROOT / filepath
        if not full.exists():
            missing.append((filepath, symbol, "file does not exist"))
            continue
        # Grep for the symbol as a def, class, or top-level assignment.
        # Top-level assignment may carry a type annotation (e.g.
        # `FOO: Final[int] = 3`) or be a bare `FOO = ...`.
        content = full.read_text()
        if not re.search(
            rf"^(def|class|async def)\s+{re.escape(symbol)}\b|"
            rf"^{re.escape(symbol)}\s*[:=]",
            content,
            re.MULTILINE,
        ):
            missing.append((filepath, symbol, "symbol not found in file"))

    assert not missing, (
        f"{len(missing)} doc anchors don't resolve:\n  "
        + "\n  ".join(f"{p}::{s}: {why}" for p, s, why in missing)
    )


def test_no_line_number_references_remain():
    """H18 should have eliminated `file.py:NNN` style references."""
    if not DOC.exists():
        pytest.skip("doc not present")
    text = DOC.read_text()
    # Allow line numbers in shell commands (e.g. `sed -n '1,10p'`) but
    # not in code-reference backticks
    line_num_in_backticks = re.findall(r"`[a-zA-Z0-9_/]+\.py:\d+`", text)
    assert not line_num_in_backticks, (
        f"line-number references survived H18: {line_num_in_backticks[:5]}\n"
        "Replace with `file.py::symbol_name` form."
    )
