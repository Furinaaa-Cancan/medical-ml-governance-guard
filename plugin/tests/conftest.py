"""Shared test fixtures."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from mlgg_lint.ast_utils import ImportMap, TaintTracker, build_import_map
from mlgg_lint.engine import _build_taint_tracker, analyze_file
from mlgg_lint.config import LintConfig

SAMPLES_DIR = Path(__file__).parent / "samples"


@pytest.fixture
def samples_dir():
    return SAMPLES_DIR


def parse_sample(name: str) -> tuple[ast.Module, ImportMap, TaintTracker]:
    """Parse a sample file and return (tree, import_map, taint_tracker)."""
    path = SAMPLES_DIR / name
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    im = build_import_map(tree)
    taint = _build_taint_tracker(tree, im)
    return tree, im, taint


def check_sample(name: str, config: LintConfig | None = None) -> list:
    """Run full analysis on a sample file."""
    path = SAMPLES_DIR / name
    return analyze_file(path, config=config or LintConfig())
