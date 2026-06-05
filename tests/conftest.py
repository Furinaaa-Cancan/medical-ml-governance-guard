"""Global test configuration — eliminates per-file sys.path hacks.

This conftest.py sets up the Python path ONCE for all test files,
replacing the 470 sys.path.insert lines scattered across 98 test files.

It also provides shared fixtures used by multiple gate tests.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# numpy / pandas are imported lazily inside the fixtures that need them
# so ci-security (which deliberately installs only pytest to test the
# zero-numpy-dependency code paths) can load this conftest without
# ModuleNotFoundError. Fixtures that use numpy/pandas will still fail
# loudly at call time if those libs are absent.

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
    str(SCRIPTS_DIR / "training"),
    str(SCRIPTS_DIR / "reporting"),
    str(SCRIPTS_DIR / "codebooks"),
    str(SCRIPTS_DIR / "review"),
    str(SCRIPTS_DIR / "diagnostics"),
    str(SCRIPTS_DIR / "orchestration"),
]
for p in _PATHS_TO_ADD:
    if p not in sys.path:
        sys.path.insert(0, p)


# ────────────────────────────────────────────────────────
# pytest-xdist: keep RAG tests on a single worker
# ────────────────────────────────────────────────────────
# scripts/rag/config.py pins the dense-index cache at a fixed path
# (REPO_ROOT/.cache/rag). Under `pytest -n auto`, parallel workers race on
# building/invalidating it and ~30 RAG tests fail. Assigning them all one
# xdist_group makes `--dist loadgroup` run them serially on one worker (same as
# today's serial run, which passes) while the rest of the suite parallelizes.
# No production code change. Inert without pytest-xdist / without --dist loadgroup.
_RAG_CACHE_PREFIXES = ("test_rag", "test_mlgg_rag", "test_harness")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "xdist_group(name): co-locate tests on one xdist worker (keeps RAG tests "
        "that share .cache/rag off parallel workers). Registered so it is a no-op "
        "without pytest-xdist installed.",
    )


def pytest_collection_modifyitems(config, items):
    for item in items:
        name = Path(str(item.fspath)).name
        if any(name.startswith(prefix) for prefix in _RAG_CACHE_PREFIXES):
            item.add_marker(pytest.mark.xdist_group("rag_cache"))


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
    import numpy as np
    import pandas as pd

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
