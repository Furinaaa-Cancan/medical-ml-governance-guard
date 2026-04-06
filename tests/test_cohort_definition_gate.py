"""Tests for scripts/cohort_definition_gate.py."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from cohort_definition_gate import (
    _classify_dtype,
    _to_float,
    analyze_cohort,
    _run_checks,
    _write_cohort_summary_csv,
    _write_feature_profile_csv,
)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _make_csv(tmp_path: Path, n=500, seed=42, prevalence=0.15, n_features=5):
    rng = np.random.default_rng(seed)
    data = {"patient_id": range(n), "y": rng.choice([0, 1], n, p=[1 - prevalence, prevalence])}
    for i in range(n_features):
        data[f"feat_{i}"] = rng.standard_normal(n)
    df = pd.DataFrame(data)
    path = tmp_path / "data.csv"
    df.to_csv(path, index=False)
    return path, df


# ─── _to_float ───

class TestToFloat:
    def test_normal(self):
        assert _to_float(3.14) == 3.14

    def test_nan(self):
        assert _to_float(float("nan")) is None

    def test_inf(self):
        assert _to_float(float("inf")) is None


# ─── _classify_dtype ───

class TestClassifyDtype:
    def test_binary(self):
        assert _classify_dtype(pd.Series([0, 1, 0, 1])) == "binary"

    def test_constant(self):
        assert _classify_dtype(pd.Series([5, 5, 5])) == "constant"

    def test_categorical(self):
        assert _classify_dtype(pd.Series([1, 2, 3, 4, 5, 1, 2])) == "categorical"

    def test_numeric(self):
        assert _classify_dtype(pd.Series(np.random.randn(100))) == "numeric"

    def test_id_like(self):
        assert _classify_dtype(pd.Series([f"id_{i}" for i in range(100)])) == "id_or_text"


# ─── analyze_cohort ───

class TestAnalyzeCohort:
    def test_basic(self):
        df = pd.DataFrame({
            "patient_id": range(100),
            "age": np.random.randint(20, 80, 100),
            "gender": np.random.choice([0, 1], 100),
            "y": np.random.choice([0, 1], 100, p=[0.8, 0.2]),
        })
        result = analyze_cohort(df, "y", "patient_id", ["age", "gender"])
        assert result["n_rows"] == 100
        assert result["n_features"] == 2
        assert result["target"]["n_positive"] + result["target"]["n_negative"] == 100
        assert 0 < result["target"]["prevalence"] < 1
        assert result["target"]["epv"] > 0
        assert result["id"]["n_unique"] == 100

    def test_missing_target(self):
        df = pd.DataFrame({"x": [1, 2, 3]})
        result = analyze_cohort(df, "y", "", ["x"])
        assert "error" in result["target"]

    def test_high_missingness(self):
        df = pd.DataFrame({
            "x": [1.0, np.nan, np.nan, np.nan, np.nan],
            "y": [0, 1, 0, 1, 0],
        })
        result = analyze_cohort(df, "y", "", ["x"])
        assert "x" in result["high_missing_features"]

    def test_zero_variance(self):
        df = pd.DataFrame({
            "const": [5, 5, 5, 5],
            "y": [0, 1, 0, 1],
        })
        result = analyze_cohort(df, "y", "", ["const"])
        assert "const" in result["zero_variance_features"]

    def test_longitudinal_detection(self):
        df = pd.DataFrame({
            "patient_id": [1, 1, 2, 2, 3],
            "x": [10, 20, 30, 40, 50],
            "y": [0, 1, 0, 1, 0],
        })
        result = analyze_cohort(df, "y", "patient_id", ["x"])
        assert result["id"]["is_longitudinal"] is True
        assert result["id"]["n_unique"] == 3

    def test_dtype_distribution(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "numeric_col": rng.standard_normal(50),
            "binary_col": rng.choice([0, 1], 50),
            "cat_col": rng.choice([1, 2, 3, 4, 5], 50),
            "y": rng.choice([0, 1], 50),
        })
        result = analyze_cohort(df, "y", "", ["numeric_col", "binary_col", "cat_col"])
        dist = result["dtype_distribution"]
        assert dist.get("numeric", 0) >= 1
        assert dist.get("binary", 0) >= 1
        assert dist.get("categorical", 0) >= 1


# ─── _run_checks ───

class TestRunChecks:
    def _analysis(self, n_rows=500, n_pos=75, n_neg=425, n_features=5, n_dup=0):
        epv = min(n_pos, n_neg) / n_features if n_features > 0 else 0
        return {
            "n_rows": n_rows,
            "n_features": n_features,
            "n_duplicate_rows": n_dup,
            "target": {
                "n_positive": n_pos,
                "n_negative": n_neg,
                "n_missing": 0,
                "n_other": 0,
                "prevalence": n_pos / (n_pos + n_neg),
                "imbalance_ratio": max(n_pos, n_neg) / max(min(n_pos, n_neg), 1),
                "epv": epv,
                "minority_class_count": min(n_pos, n_neg),
            },
            "id": {},
            "high_missing_features": [],
            "zero_variance_features": [],
        }

    def test_pass(self):
        failures, warnings = [], []
        _run_checks(failures, warnings, self._analysis(), 10, 50, 100)
        assert not failures

    def test_too_small(self):
        failures, warnings = [], []
        _run_checks(failures, warnings, self._analysis(n_rows=50), 10, 50, 100)
        assert any(f["code"] == "COHORT_TOO_SMALL" for f in failures)

    def test_few_events(self):
        failures, warnings = [], []
        _run_checks(failures, warnings, self._analysis(n_pos=10, n_neg=490), 10, 50, 100)
        assert any(f["code"] == "COHORT_EVENTS_TOO_FEW" for f in failures)

    def test_epv_critical(self):
        failures, warnings = [], []
        _run_checks(failures, warnings, self._analysis(n_pos=10, n_neg=490, n_features=5), 10, 5, 50)
        # EPV = 10/5 = 2 < 5 → critical
        assert any(f["code"] == "COHORT_EPV_CRITICAL" for f in failures)

    def test_epv_low_warning(self):
        failures, warnings = [], []
        # EPV = 30/5 = 6 → between 5 and 10 → warning
        _run_checks(failures, warnings, self._analysis(n_pos=30, n_neg=470, n_features=5), 10, 5, 50)
        assert any(w["code"] == "COHORT_EPV_LOW" for w in warnings)

    def test_severe_imbalance(self):
        failures, warnings = [], []
        _run_checks(failures, warnings, self._analysis(n_pos=5, n_neg=495, n_features=1), 10, 1, 50)
        assert any(w["code"] == "COHORT_SEVERE_IMBALANCE" for w in warnings)

    def test_duplicate_rows(self):
        failures, warnings = [], []
        _run_checks(failures, warnings, self._analysis(n_dup=10), 10, 50, 100)
        assert any(w["code"] == "COHORT_DUPLICATE_ROWS" for w in warnings)

    def test_missing_target(self):
        failures, warnings = [], []
        analysis = self._analysis()
        analysis["target"] = {"error": "not found"}
        _run_checks(failures, warnings, analysis, 10, 50, 100)
        assert any(f["code"] == "COHORT_TARGET_MISSING" for f in failures)


# ─── CSV writers ───

class TestCSVWriters:
    def test_cohort_summary(self, tmp_path):
        analysis = {
            "n_rows": 500, "n_features": 10, "n_duplicate_rows": 0,
            "target": {"n_positive": 75, "n_negative": 425, "n_missing": 0,
                       "prevalence": 0.15, "imbalance_ratio": 5.67, "epv": 7.5},
            "id": {"n_unique": 500, "is_longitudinal": False},
            "high_missing_features": ["x1"],
            "zero_variance_features": [],
            "dtype_distribution": {"numeric": 8, "binary": 2},
        }
        path = tmp_path / "summary.csv"
        _write_cohort_summary_csv(path, analysis)
        assert path.exists()
        with path.open() as f:
            rows = list(csv.reader(f))
        assert rows[0] == ["Metric", "Value"]
        assert len(rows) > 10

    def test_feature_profile(self, tmp_path):
        profiles = [
            {"feature": "age", "dtype": "float64", "dtype_class": "numeric",
             "n_missing": 0, "pct_missing": 0.0, "n_unique": 60,
             "mean": 55.0, "std": 12.0, "min": 20.0, "max": 80.0},
        ]
        path = tmp_path / "profile.csv"
        _write_feature_profile_csv(path, profiles)
        assert path.exists()
        df = pd.read_csv(path)
        assert len(df) == 1
        assert df.iloc[0]["Feature"] == "age"


# ─── E2E subprocess ───

class TestE2ESubprocess:
    def test_pass(self, tmp_path):
        path, _ = _make_csv(tmp_path, n=500, prevalence=0.15, n_features=5)
        report_path = tmp_path / "report.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "cohort_definition_gate.py"),
             "--data", str(path), "--target-col", "y", "--id-col", "patient_id",
             "--report", str(report_path), "--output-dir", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(report_path.read_text())
        assert report["status"] == "pass"
        assert (tmp_path / "cohort_summary.csv").exists()
        assert (tmp_path / "feature_profile.csv").exists()

    def test_fail_too_few_events(self, tmp_path):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "patient_id": range(100),
            "feat_0": rng.standard_normal(100),
            "y": [1] * 5 + [0] * 95,  # only 5 positive
        })
        path = tmp_path / "data.csv"
        df.to_csv(path, index=False)
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "cohort_definition_gate.py"),
             "--data", str(path), "--target-col", "y",
             "--report", str(report_path), "--output-dir", str(tmp_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 2
        report = json.loads(report_path.read_text())
        assert report["status"] == "fail"

    def test_strict_promotes_warnings(self, tmp_path):
        rng = np.random.default_rng(42)
        n = 200
        df = pd.DataFrame({
            "patient_id": range(n),
            "feat_0": rng.standard_normal(n),
            "y": rng.choice([0, 1], n, p=[0.85, 0.15]),
        })
        # Add high-missing feature
        df["bad_feat"] = np.nan
        df.loc[:5, "bad_feat"] = 1.0
        path = tmp_path / "data.csv"
        df.to_csv(path, index=False)
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "cohort_definition_gate.py"),
             "--data", str(path), "--target-col", "y",
             "--report", str(report_path), "--output-dir", str(tmp_path),
             "--strict"],
            capture_output=True, text=True, timeout=30,
        )
        # high missingness → warning → strict → fail
        assert result.returncode == 2
