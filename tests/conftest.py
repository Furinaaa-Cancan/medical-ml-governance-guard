"""Global test configuration — eliminates per-file sys.path hacks.

This conftest.py sets up the Python path ONCE for all test files,
replacing the 470 sys.path.insert lines scattered across 98 test files.

It also provides shared fixtures used by multiple gate tests.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# ────────────────────────────────────────────────────────
# Path setup (replaces per-file sys.path hacks)
# ────────────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Add all script directories to sys.path so that bare imports
# like `from _gate_framework import ...` work in tests.
# This is the SINGLE place where sys.path is configured for tests.
_PATHS_TO_ADD = [
    str(SCRIPTS_DIR),
    str(SCRIPTS_DIR / "core"),
    str(SCRIPTS_DIR / "gates"),
    str(SCRIPTS_DIR / "tools"),
    str(SCRIPTS_DIR / "orchestration"),
]
for p in _PATHS_TO_ADD:
    if p not in sys.path:
        sys.path.insert(0, p)


# ────────────────────────────────────────────────────────
# Shared fixtures
# ────────────────────────────────────────────────────────

@pytest.fixture()
def project_root() -> Path:
    return PROJECT_ROOT


@pytest.fixture()
def scripts_dir() -> Path:
    return SCRIPTS_DIR


# ── CSV helpers ──────────────────────────────────────────

@pytest.fixture()
def write_csv(tmp_path):
    """Factory fixture: write a CSV and return its path."""
    def _write(filename: str, headers: list, rows: list = None) -> Path:
        path = tmp_path / filename
        lines = [",".join(str(h) for h in headers)]
        if rows:
            for row in rows:
                lines.append(",".join(str(v) for v in row))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path
    return _write


@pytest.fixture()
def write_json_file(tmp_path):
    """Factory fixture: write a JSON file and return its path."""
    def _write(filename: str, data: dict) -> Path:
        path = tmp_path / filename
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path
    return _write


@pytest.fixture()
def make_binary_csv(tmp_path):
    """Factory fixture: create a binary classification CSV with configurable params."""
    def _make(
        n: int = 500,
        n_features: int = 5,
        prevalence: float = 0.15,
        id_col: str = "patient_id",
        target_col: str = "y",
        seed: int = 42,
    ) -> Path:
        rng = np.random.default_rng(seed)
        data = {id_col: range(n)}
        for i in range(n_features):
            data[f"feat_{i}"] = rng.standard_normal(n)
        data[target_col] = rng.choice(
            [0, 1], size=n, p=[1 - prevalence, prevalence]
        )
        df = pd.DataFrame(data)
        path = tmp_path / "data.csv"
        df.to_csv(path, index=False)
        return path
    return _make
