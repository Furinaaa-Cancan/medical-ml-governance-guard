"""Tests for split_protocol_gate.py cross-sectional data support."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _make_splits(tmp_path: Path, n_train=200, n_test=100, seed=42, add_time_col=False):
    """Create train/test CSVs with or without a time column."""
    rng = np.random.default_rng(seed)

    def _make_df(n, id_offset=0, year="2024"):
        d = {
            "patient_id": [f"p{i + id_offset}" for i in range(n)],
            "feat_0": rng.standard_normal(n),
            "y": rng.choice([0, 1], n, p=[0.85, 0.15]),
        }
        if add_time_col:
            # Train gets earlier dates, test gets later dates
            d["event_time"] = [f"{year}-{(i % 12) + 1:02d}-01" for i in range(n)]
        return pd.DataFrame(d)

    train_df = _make_df(n_train, id_offset=0, year="2023")
    test_df = _make_df(n_test, id_offset=n_train, year="2025")

    train_path = tmp_path / "train.csv"
    test_path = tmp_path / "test.csv"
    train_df.to_csv(train_path, index=False)
    test_df.to_csv(test_path, index=False)
    return train_path, test_path


def _make_protocol_spec(tmp_path: Path, cross_sectional=False):
    """Create a minimal split protocol spec."""
    spec = {
        "split_strategy": "stratified_grouped" if cross_sectional else "grouped_temporal",
        "split_reference": "test_protocol",
        "id_col": "patient_id",
        "index_time_col": "" if cross_sectional else "event_time",
        "frozen_before_modeling": True,
        "requires_group_disjoint": True,
        "requires_temporal_order": not cross_sectional,
        "allow_patient_overlap": False,
        "allow_time_overlap": False,
        "split_seed_locked": True,
    }
    return _write_json(tmp_path / "protocol_spec.json", spec)


class TestCrossSectionalMode:
    """Post-add53c5 semantics (2026-04):
    - **Implicit** cross-sectional (no `--time-col` AND no `--cross-sectional`) → WARN,
      prompting the user to either supply --cross-sectional or document the
      limitation per TRIPOD+AI S03.
    - **Explicit** `--cross-sectional` → treated as user acknowledgement; no warning.
    - Implicit + `--strict` → warning promotes to failure (exit 2).
    """

    def test_cross_sectional_implicit_warns(self, tmp_path):
        """No time column AND no --cross-sectional flag → warning emitted
        to prompt user to either acknowledge or add temporal data."""
        train_path, test_path = _make_splits(tmp_path, add_time_col=False)
        spec_path = _make_protocol_spec(tmp_path, cross_sectional=True)
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "gates/split_protocol_gate.py"),
             "--protocol-spec", str(spec_path),
             "--train", str(train_path),
             "--test", str(test_path),
             "--id-col", "patient_id",
             # No --cross-sectional — implicit path.
             "--report", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Failed: {result.stdout}\n{result.stderr}"
        report = json.loads(report_path.read_text())
        assert report["status"] == "pass"
        warning_codes = [w["code"] for w in report.get("warnings", [])]
        assert "cross_sectional_data" in warning_codes

    def test_cross_sectional_explicit_flag_suppresses_warning(self, tmp_path):
        """--cross-sectional flag set → user has explicitly acknowledged;
        the cross_sectional_data warning is suppressed (add53c5)."""
        train_path, test_path = _make_splits(tmp_path, add_time_col=False)
        spec_path = _make_protocol_spec(tmp_path, cross_sectional=True)
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "gates/split_protocol_gate.py"),
             "--protocol-spec", str(spec_path),
             "--train", str(train_path),
             "--test", str(test_path),
             "--id-col", "patient_id",
             "--cross-sectional",
             "--report", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Failed: {result.stdout}\n{result.stderr}"
        report = json.loads(report_path.read_text())
        assert report["status"] == "pass"
        warning_codes = [w["code"] for w in report.get("warnings", [])]
        assert "cross_sectional_data" not in warning_codes, (
            f"Explicit --cross-sectional should suppress the warning; got {warning_codes}"
        )

    def test_cross_sectional_implicit_strict_fails(self, tmp_path):
        """Implicit cross-sectional + --strict → warning promotes to failure."""
        train_path, test_path = _make_splits(tmp_path, add_time_col=False)
        spec_path = _make_protocol_spec(tmp_path, cross_sectional=True)
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "gates/split_protocol_gate.py"),
             "--protocol-spec", str(spec_path),
             "--train", str(train_path),
             "--test", str(test_path),
             "--id-col", "patient_id",
             # No --cross-sectional → implicit → warning emitted → strict promotes.
             "--strict",
             "--report", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 2  # cross_sectional warning → strict → fail

    def test_temporal_with_time_col_passes(self, tmp_path):
        """Longitudinal data with time column should still pass normally."""
        train_path, test_path = _make_splits(tmp_path, add_time_col=True)
        spec_path = _make_protocol_spec(tmp_path, cross_sectional=False)
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "gates/split_protocol_gate.py"),
             "--protocol-spec", str(spec_path),
             "--train", str(train_path),
             "--test", str(test_path),
             "--id-col", "patient_id",
             "--time-col", "event_time",
             "--report", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Failed: {result.stdout}\n{result.stderr}"

    def test_empty_time_col_implies_cross_sectional(self, tmp_path):
        """Omitting --time-col should auto-enable cross-sectional mode."""
        train_path, test_path = _make_splits(tmp_path, add_time_col=False)
        spec_path = _make_protocol_spec(tmp_path, cross_sectional=True)
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "gates/split_protocol_gate.py"),
             "--protocol-spec", str(spec_path),
             "--train", str(train_path),
             "--test", str(test_path),
             "--id-col", "patient_id",
             # No --time-col, no --cross-sectional: should auto-detect
             "--report", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, f"Failed: {result.stdout}\n{result.stderr}"
        report = json.loads(report_path.read_text())
        warning_codes = [w["code"] for w in report.get("warnings", [])]
        assert "cross_sectional_data" in warning_codes
