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


from cohort_definition_gate import (
    _classify_dtype,
    _find_columns_for_var,
    _to_float,
    analyze_cohort,
    _run_checks,
    validate_codebook,
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
            [sys.executable, str(SCRIPTS_DIR / "gates/cohort_definition_gate.py"),
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
            [sys.executable, str(SCRIPTS_DIR / "gates/cohort_definition_gate.py"),
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
            [sys.executable, str(SCRIPTS_DIR / "gates/cohort_definition_gate.py"),
             "--data", str(path), "--target-col", "y",
             "--report", str(report_path), "--output-dir", str(tmp_path),
             "--strict"],
            capture_output=True, text=True, timeout=30,
        )
        # high missingness → warning → strict → fail
        assert result.returncode == 2


# ────────────────────────────────────────────────────────
# Codebook validation tests
# ────────────────────────────────────────────────────────

CODEBOOK_REGISTRY = Path(__file__).resolve().parent.parent / "references" / "codebooks" / "dataset-codebook-registry.json"


class TestCodebookValidation:
    """Verify codebook validation catches NHANES-specific issues."""

    @pytest.fixture()
    def codebook_path(self) -> Path:
        if not CODEBOOK_REGISTRY.exists():
            pytest.skip("Codebook registry not found")
        return CODEBOOK_REGISTRY

    def test_race_as_numeric_fails(self, codebook_path: Path):
        """Nominal race_ethnicity stored as float → CODEBOOK_ENCODING_MISMATCH failure."""
        df = pd.DataFrame({
            "patient_id": [1, 2, 3],
            "race_ethnicity": [1.0, 3.0, 4.0],  # numeric = wrong
            "age": [50, 60, 70],
            "y": [0, 1, 0],
        })
        failures, warnings = [], []
        validate_codebook(df, str(codebook_path), "nhanes_2017_2020", "y", failures, warnings)
        fail_codes = [f["code"] for f in failures]
        assert "CODEBOOK_ENCODING_MISMATCH" in fail_codes

    def test_race_as_string_passes(self, codebook_path: Path):
        """Nominal race_ethnicity stored as string → no encoding failure."""
        df = pd.DataFrame({
            "patient_id": [1, 2, 3],
            "race_ethnicity": ["nh_white", "nh_black", "nh_asian"],
            "age": [50, 60, 70],
            "y": [0, 1, 0],
        })
        failures, warnings = [], []
        validate_codebook(df, str(codebook_path), "nhanes_2017_2020", "y", failures, warnings)
        fail_codes = [f["code"] for f in failures]
        assert "CODEBOOK_ENCODING_MISMATCH" not in fail_codes

    def test_gated_missingness_detected(self, codebook_path: Path):
        """bp_medication with high NaN rate → CODEBOOK_GATED_MISSINGNESS warning."""
        n = 100
        df = pd.DataFrame({
            "patient_id": range(n),
            "bp_medication": [np.nan] * 66 + [1.0] * 20 + [0.0] * 14,
            "age": np.random.default_rng(42).integers(18, 80, n),
            "y": [0] * 80 + [1] * 20,
        })
        failures, warnings = [], []
        validate_codebook(df, str(codebook_path), "nhanes_2017_2020", "y", failures, warnings)
        warn_codes = [w["code"] for w in warnings]
        assert "CODEBOOK_GATED_MISSINGNESS" in warn_codes
        # Check it mentions BPQ050A
        gated_warns = [w for w in warnings if w["code"] == "CODEBOOK_GATED_MISSINGNESS"]
        assert any("BPQ050A" in w.get("details", {}).get("var_code", "") for w in gated_warns)

    def test_age_top_coding_detected(self, codebook_path: Path):
        """Age with many values at 80 → CODEBOOK_TOP_CODED warning."""
        ages = [80.0] * 15 + list(range(18, 80))
        df = pd.DataFrame({
            "patient_id": range(len(ages)),
            "age": ages,
            "y": [0] * (len(ages) - 5) + [1] * 5,
        })
        failures, warnings = [], []
        validate_codebook(df, str(codebook_path), "nhanes_2017_2020", "y", failures, warnings)
        warn_codes = [w["code"] for w in warnings]
        assert "CODEBOOK_TOP_CODED" in warn_codes

    def test_reverse_causation_flagged(self, codebook_path: Path):
        """CHD and stroke features → CODEBOOK_REVERSE_CAUSATION warning."""
        df = pd.DataFrame({
            "patient_id": [1, 2, 3],
            "coronary_heart_disease": [0.0, 1.0, 0.0],
            "stroke": [0.0, 0.0, 1.0],
            "age": [50, 60, 70],
            "y": [0, 1, 0],
        })
        failures, warnings = [], []
        validate_codebook(df, str(codebook_path), "nhanes_2017_2020", "y", failures, warnings)
        warn_codes = [w["code"] for w in warnings]
        assert warn_codes.count("CODEBOOK_REVERSE_CAUSATION") >= 2

    def test_definition_variable_in_features_fails(self, codebook_path: Path):
        """HbA1c as feature when predicting diabetes → must_exclude failure."""
        df = pd.DataFrame({
            "patient_id": [1, 2, 3],
            "hba1c": [5.5, 7.0, 6.0],
            "age": [50, 60, 70],
            "y": [0, 1, 0],
        })
        failures, warnings = [], []
        validate_codebook(df, str(codebook_path), "nhanes_2017_2020", "y", failures, warnings)
        fail_codes = [f["code"] for f in failures]
        assert "CODEBOOK_VARIABLE_MISLABEL" in fail_codes
        # Should mention must_exclude
        mislabel_fails = [f for f in failures if f["code"] == "CODEBOOK_VARIABLE_MISLABEL"]
        assert any("must be excluded" in f.get("message", "") for f in mislabel_fails)

    def test_clean_nhanes_no_failures(self, codebook_path: Path):
        """Clean NHANES features (post-fix) should produce zero failures."""
        df = pd.DataFrame({
            "patient_id": [1, 2, 3],
            "age": [50, 60, 70],
            "gender": [0.0, 1.0, 0.0],
            "race_ethnicity": ["nh_white", "nh_black", "nh_asian"],
            "bmi": [25.0, 30.0, 22.0],
            "sbp_mean": [120.0, 140.0, 110.0],
            "ever_smoked": [0.0, 1.0, 0.0],
            "bp_medication": [0.0, 1.0, 0.0],
            "coronary_heart_disease": [0.0, 1.0, 0.0],
            "stroke": [0.0, 0.0, 0.0],
            "y": [0, 1, 0],
        })
        failures, warnings = [], []
        validate_codebook(df, str(codebook_path), "nhanes_2017_2020", "y", failures, warnings)
        assert len(failures) == 0, f"Unexpected failures: {failures}"
        # Warnings are OK (top-coding, reverse causation are warnings not failures)

    def test_cli_codebook_flag(self, tmp_path: Path, codebook_path: Path):
        """E2E: --codebook flag works in subprocess."""
        n = 200
        rng = np.random.default_rng(42)
        df = pd.DataFrame({
            "patient_id": range(n),
            "age": rng.integers(18, 80, n).astype(float),
            "race_ethnicity": rng.choice([1.0, 3.0, 4.0], n),  # numeric = should flag
            "y": rng.choice([0, 1], n, p=[0.85, 0.15]),
        })
        data_path = tmp_path / "nhanes_test.csv"
        df.to_csv(data_path, index=False)
        report_path = tmp_path / "report.json"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "gates/cohort_definition_gate.py"),
             "--data", str(data_path), "--target-col", "y",
             "--codebook", str(codebook_path),
             "--codebook-dataset", "nhanes_2017_2020",
             "--report", str(report_path), "--output-dir", str(tmp_path),
             "--strict"],
            capture_output=True, text=True, timeout=30,
        )
        # strict + encoding mismatch (failure) → exit 2
        assert result.returncode == 2, f"Expected failure.\nstdout:\n{result.stdout}"
        report = json.loads(report_path.read_text())
        all_codes = [f["code"] for f in report["failures"]]
        assert "CODEBOOK_ENCODING_MISMATCH" in all_codes

    def test_unknown_dataset_key_skipped(self, codebook_path: Path):
        """Unknown dataset key → validation returns not_found, no crash."""
        df = pd.DataFrame({"x": [1, 2], "y": [0, 1]})
        failures, warnings = [], []
        result = validate_codebook(df, str(codebook_path), "nonexistent_ds", "y", failures, warnings)
        assert result.get("status") == "not_found"
        assert len(failures) == 0

    def test_missing_codebook_file(self, tmp_path: Path):
        """Non-existent codebook path → warning, no crash."""
        df = pd.DataFrame({"x": [1, 2], "y": [0, 1]})
        failures, warnings = [], []
        validate_codebook(df, str(tmp_path / "nope.json"), "nhanes", "y", failures, warnings)
        assert len(failures) == 0
        assert len(warnings) == 1


# ─── P1: cohort_spec cascade + Table 1 + index_date ───

from cohort_definition_gate import (
    _load_cohort_spec,
    _validate_cohort_cascade,
    _validate_index_date,
    _generate_table_one,
)


class TestLoadCohortSpec:
    def test_empty(self):
        assert _load_cohort_spec("") is None
        assert _load_cohort_spec("   ") is None

    def test_inline_json(self):
        spec = _load_cohort_spec('{"final_cohort_size": 100}')
        assert spec == {"final_cohort_size": 100}

    def test_file_path(self, tmp_path: Path):
        p = tmp_path / "spec.json"
        p.write_text('{"inclusion_criteria": [{"step": "a", "n_initial": 10}]}')
        spec = _load_cohort_spec(str(p))
        assert spec["inclusion_criteria"][0]["step"] == "a"


class TestValidateCohortCascade:
    def test_undocumented_leakage_audited_is_warn(self):
        failures, warnings = [], []
        result = _validate_cohort_cascade(None, 100, failures, warnings,
                                          claim_tier="leakage-audited")
        assert result["declared"] is False
        assert len(failures) == 0
        assert len(warnings) == 1
        assert warnings[0]["code"] == "COHORT_CASCADE_UNDOCUMENTED"

    def test_undocumented_publication_grade_is_fail(self):
        failures, warnings = [], []
        _validate_cohort_cascade(None, 100, failures, warnings,
                                 claim_tier="publication-grade")
        assert len(failures) == 1
        assert failures[0]["code"] == "COHORT_CASCADE_UNDOCUMENTED"

    def test_monotonicity_violation_fails(self):
        spec = {"inclusion_criteria": [
            {"step": "registry", "n_initial": 1000},
            {"step": "age>=18", "n_after": 800},
            {"step": "added back somehow", "n_after": 900},  # BUG
        ]}
        failures, warnings = [], []
        _validate_cohort_cascade(spec, 900, failures, warnings,
                                 claim_tier="leakage-audited")
        mono = [f for f in failures if f["code"] == "COHORT_CASCADE_MONOTONICITY"]
        assert len(mono) >= 1

    def test_valid_cascade_no_failure(self):
        spec = {
            "inclusion_criteria": [
                {"step": "registry", "n_initial": 1000},
                {"step": "age>=18", "n_after": 800},
                {"step": "1y history", "n_after": 600},
            ],
            "final_cohort_size": 600,
        }
        failures, warnings = [], []
        result = _validate_cohort_cascade(spec, 600, failures, warnings,
                                          claim_tier="publication-grade")
        assert result["declared"] is True
        assert result["n_inclusion_steps"] == 3
        cascade_failures = [f for f in failures
                            if f["code"].startswith("COHORT_CASCADE")]
        assert len(cascade_failures) == 0

    def test_size_mismatch_fails(self):
        spec = {"final_cohort_size": 1000}
        failures, warnings = [], []
        _validate_cohort_cascade(spec, 500, failures, warnings,
                                 claim_tier="leakage-audited")
        mismatch = [f for f in failures if f["code"] == "COHORT_CASCADE_MISMATCH"]
        assert len(mismatch) == 1

    def test_size_within_tolerance_passes(self):
        spec = {"final_cohort_size": 1000}
        failures, warnings = [], []
        _validate_cohort_cascade(spec, 1005, failures, warnings,
                                 claim_tier="leakage-audited")
        mismatch = [f for f in failures if f["code"] == "COHORT_CASCADE_MISMATCH"]
        assert len(mismatch) == 0


class TestValidateIndexDate:
    def test_no_spec_returns_empty(self):
        failures = []
        result = _validate_index_date(None, ["a", "b"], failures)
        assert result == {}
        assert len(failures) == 0

    def test_declared_and_present(self):
        failures = []
        spec = {"index_date_col": "index_dt"}
        result = _validate_index_date(spec, ["index_dt", "age"], failures)
        assert result == {"index_date_col": "index_dt", "present": True}
        assert len(failures) == 0

    def test_declared_missing_fails(self):
        failures = []
        spec = {"index_date_col": "missing_col"}
        _validate_index_date(spec, ["age", "sex"], failures)
        assert len(failures) == 1
        assert failures[0]["code"] == "COHORT_INDEX_DATE_MISSING"


class TestGenerateTableOne:
    def test_emits_csv_with_groups(self, tmp_path: Path):
        df = pd.DataFrame({
            "age": [25, 35, 45, 55, 65, 75],
            "sex": [0, 1, 0, 1, 0, 1],
            "race": ["white", "black", "asian", "white", "black", "asian"],
            "y": [0, 0, 0, 1, 1, 1],
        })
        path = tmp_path / "t1.csv"
        result = _generate_table_one(df, "y", ["age", "sex", "race"], path)
        assert result["status"] == "written"
        assert result["n_features"] == 3
        assert result["n_outcome_positive"] == 3
        assert result["n_outcome_negative"] == 3
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "age" in text and "sex" in text and "race" in text
        assert "continuous" in text and "binary" in text and "categorical" in text

    def test_missing_target_is_skipped(self, tmp_path: Path):
        df = pd.DataFrame({"x": [1, 2, 3]})
        result = _generate_table_one(df, "nope", ["x"], tmp_path / "t1.csv")
        assert result["status"] == "skipped"
