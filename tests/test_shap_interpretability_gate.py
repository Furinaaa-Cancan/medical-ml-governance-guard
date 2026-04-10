"""Comprehensive unit tests for scripts/shap_interpretability_gate.py."""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


from shap_interpretability_gate import (
    _aggregate_shap,
    _classify_direction,
    _compute_pdp_ice,
    _compute_rank_correlations,
    _extract_clf_and_transform,
    _run_validation_checks,
    _to_float,
    _write_table_a,
    _write_table_b,
    _write_table_c,
    _write_table_d,
    _write_table_e,
)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


# ────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────

def _write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _make_synthetic_data(tmp_path: Path, n_train=200, n_test=100, n_features=5, seed=42):
    """Create synthetic train/test CSVs and a model pool pickle."""
    rng = np.random.default_rng(seed)

    feature_names = [f"feat_{i}" for i in range(n_features)]

    # Generate data with a real signal
    X_train = rng.standard_normal((n_train, n_features))
    coefs = rng.standard_normal(n_features)
    y_train = (X_train @ coefs + rng.standard_normal(n_train) > 0).astype(int)

    X_test = rng.standard_normal((n_test, n_features))
    y_test = (X_test @ coefs + rng.standard_normal(n_test) > 0).astype(int)

    train_df = pd.DataFrame(X_train, columns=feature_names)
    train_df["y"] = y_train
    train_path = tmp_path / "train.csv"
    train_df.to_csv(train_path, index=False)

    test_df = pd.DataFrame(X_test, columns=feature_names)
    test_df["y"] = y_test
    test_path = tmp_path / "test.csv"
    test_df.to_csv(test_path, index=False)

    return train_path, test_path, feature_names, X_train, y_train


def _make_model_pool(tmp_path: Path, X_train, y_train, feature_names):
    """Train RF + LR models and save as model_pool.pkl."""
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.impute import SimpleImputer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    import joblib

    families = {}

    # RF
    rf_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="mean")),
        ("clf", RandomForestClassifier(n_estimators=20, max_depth=3, random_state=42)),
    ])
    rf_pipe.fit(X_train, y_train)
    families["random_forest_balanced"] = {
        "model_id": "rf_hp0",
        "estimator": rf_pipe,
        "hyperparameters": {"n_estimators": 20, "max_depth": 3},
        "cv_pr_auc_mean": 0.75,
    }

    # LR
    lr_pipe = Pipeline([
        ("imputer", SimpleImputer(strategy="mean")),
        ("clf", LogisticRegression(random_state=42, max_iter=200)),
    ])
    lr_pipe.fit(X_train, y_train)
    families["logistic_l2"] = {
        "model_id": "lr_hp0",
        "estimator": lr_pipe,
        "hyperparameters": {"C": 1.0},
        "cv_pr_auc_mean": 0.72,
    }

    model_pool = {
        "schema_version": 1,
        "families": families,
        "features": feature_names,
        "selected_model_id": "rf_hp0",
    }

    pool_path = tmp_path / "model_pool.pkl"
    joblib.dump(model_pool, pool_path)
    return pool_path


# ────────────────────────────────────────────────────────
# Unit tests: _to_float
# ────────────────────────────────────────────────────────

class TestToFloat:
    def test_normal_float(self):
        assert _to_float(3.14) == 3.14

    def test_int(self):
        assert _to_float(42) == 42.0

    def test_nan(self):
        assert _to_float(float("nan")) is None

    def test_inf(self):
        assert _to_float(float("inf")) is None

    def test_string(self):
        assert _to_float("abc") is None

    def test_none(self):
        assert _to_float(None) is None


# ────────────────────────────────────────────────────────
# Unit tests: _classify_direction
# ────────────────────────────────────────────────────────

class TestClassifyDirection:
    def test_positive(self):
        assert _classify_direction(0.5, [0.3, 0.2, 0.1]) == "positive"

    def test_negative(self):
        assert _classify_direction(-0.5, [-0.3, -0.2, -0.1]) == "negative"

    def test_mixed(self):
        assert _classify_direction(0.1, [0.3, -0.2, 0.1]) == "mixed"

    def test_empty(self):
        assert _classify_direction(0.0, []) == "indeterminate"

    def test_zero_positive(self):
        # All non-negative, ensemble > 0
        assert _classify_direction(0.1, [0.0, 0.3]) == "positive"

    def test_zero_negative(self):
        # All non-positive, ensemble < 0
        assert _classify_direction(-0.1, [0.0, -0.3]) == "negative"


# ────────────────────────────────────────────────────────
# Unit tests: _aggregate_shap
# ────────────────────────────────────────────────────────

class TestAggregateShap:
    def test_basic_aggregation(self):
        """Two models with known SHAP values; verify proportional normalization."""
        features = ["a", "b", "c"]
        # Model 1: a=1.0, b=0.5, c=0.5 → sum=2.0 → proportions: 0.5, 0.25, 0.25
        # Model 2: a=0.2, b=0.6, c=0.2 → sum=1.0 → proportions: 0.2, 0.6, 0.2
        family_results = {
            "model_1": {
                "raw_shap": np.array([
                    [1.0, 0.5, 0.5],
                    [1.0, 0.5, 0.5],
                ]),
            },
            "model_2": {
                "raw_shap": np.array([
                    [0.2, 0.6, 0.2],
                    [0.2, 0.6, 0.2],
                ]),
            },
        }

        agg = _aggregate_shap(family_results, features)

        # Model 1 proportions: [0.5, 0.25, 0.25]
        np.testing.assert_allclose(
            agg["per_model_proportion"]["model_1"],
            [0.5, 0.25, 0.25],
        )
        # Model 2 proportions: [0.2, 0.6, 0.2]
        np.testing.assert_allclose(
            agg["per_model_proportion"]["model_2"],
            [0.2, 0.6, 0.2],
        )
        # Ensemble: average of proportions
        expected = np.array([0.35, 0.425, 0.225])
        np.testing.assert_allclose(agg["ensemble_proportion"], expected)

        # Ranking: b(0.425) > a(0.35) > c(0.225)
        assert list(agg["ranking"][:3]) == [1, 0, 2]

    def test_zero_sum_model(self):
        """A model with all-zero SHAP should produce zero proportions."""
        features = ["a", "b"]
        family_results = {
            "model_1": {"raw_shap": np.array([[0.0, 0.0]])},
        }
        agg = _aggregate_shap(family_results, features)
        np.testing.assert_allclose(agg["per_model_proportion"]["model_1"], [0.0, 0.0])

    def test_signed_mean(self):
        """Verify signed mean is computed correctly."""
        features = ["a", "b"]
        family_results = {
            "m1": {"raw_shap": np.array([[0.5, -0.3], [-0.1, 0.7]])},
        }
        agg = _aggregate_shap(family_results, features)
        # mean signed: a=(0.5-0.1)/2=0.2, b=(-0.3+0.7)/2=0.2
        np.testing.assert_allclose(agg["per_model_signed"]["m1"], [0.2, 0.2])


# ────────────────────────────────────────────────────────
# Unit tests: _compute_rank_correlations
# ────────────────────────────────────────────────────────

class TestRankCorrelations:
    def test_perfect_agreement(self):
        """Identical importance vectors should have tau = 1.0."""
        per_model_abs = {
            "a": np.array([0.5, 0.3, 0.2]),
            "b": np.array([0.5, 0.3, 0.2]),
        }
        corrs = _compute_rank_correlations(per_model_abs)
        assert len(corrs) == 1
        assert corrs[0]["kendall_tau"] == 1.0

    def test_reverse_ranking(self):
        """Opposite rankings should have tau = -1.0."""
        per_model_abs = {
            "a": np.array([0.5, 0.3, 0.1]),
            "b": np.array([0.1, 0.3, 0.5]),
        }
        corrs = _compute_rank_correlations(per_model_abs)
        assert corrs[0]["kendall_tau"] == pytest.approx(-1.0, abs=0.01)

    def test_three_models(self):
        """Three models should produce 3 pairwise comparisons."""
        per_model_abs = {
            "a": np.array([1, 2, 3]),
            "b": np.array([1, 2, 3]),
            "c": np.array([3, 2, 1]),
        }
        corrs = _compute_rank_correlations(per_model_abs)
        assert len(corrs) == 3


# ────────────────────────────────────────────────────────
# Unit tests: validation checks
# ────────────────────────────────────────────────────────

class TestValidationChecks:
    def _make_agg(self, n_features=5):
        """Create a minimal aggregation result."""
        ensemble_prop = np.array([0.3, 0.25, 0.2, 0.15, 0.1])
        return {
            "ensemble_proportion": ensemble_prop,
            "ensemble_signed": np.array([0.1, -0.05, 0.03, -0.02, 0.01]),
            "ranking": np.argsort(-ensemble_prop),
            "per_model_abs": {},
            "per_model_signed": {},
            "per_model_proportion": {},
        }

    def test_single_model_warning(self):
        failures, warnings = [], []
        _run_validation_checks(
            failures, warnings,
            family_results={"only_one": {"raw_shap": np.ones((5, 3))}},
            agg=self._make_agg(3),
            rank_correlations=[],
            feature_names=["a", "b", "c"],
            feature_lineage_spec=None,
            min_rank_correlation=0.5,
            rank_correlation_fail=0.3,
            strict=False,
        )
        codes = [w["code"] for w in warnings]
        assert "SHAP_SINGLE_MODEL" in codes

    def test_all_zeros_failure(self):
        failures, warnings = [], []
        _run_validation_checks(
            failures, warnings,
            family_results={"bad": {"raw_shap": np.zeros((5, 3))}},
            agg=self._make_agg(3),
            rank_correlations=[],
            feature_names=["a", "b", "c"],
            feature_lineage_spec=None,
            min_rank_correlation=0.5,
            rank_correlation_fail=0.3,
            strict=False,
        )
        codes = [f["code"] for f in failures]
        assert "SHAP_ALL_ZEROS" in codes

    def test_nan_failure(self):
        failures, warnings = [], []
        shap_with_nan = np.ones((5, 3))
        shap_with_nan[2, 1] = np.nan
        _run_validation_checks(
            failures, warnings,
            family_results={"bad": {"raw_shap": shap_with_nan}},
            agg=self._make_agg(3),
            rank_correlations=[],
            feature_names=["a", "b", "c"],
            feature_lineage_spec=None,
            min_rank_correlation=0.5,
            rank_correlation_fail=0.3,
            strict=False,
        )
        codes = [f["code"] for f in failures]
        assert "SHAP_NAN_DETECTED" in codes

    def test_extreme_concentration_warning(self):
        failures, warnings = [], []
        agg = self._make_agg()
        agg["ensemble_proportion"] = np.array([0.6, 0.15, 0.1, 0.1, 0.05])
        _run_validation_checks(
            failures, warnings,
            family_results={"m1": {"raw_shap": np.ones((5, 5))}},
            agg=agg,
            rank_correlations=[],
            feature_names=["a", "b", "c", "d", "e"],
            feature_lineage_spec=None,
            min_rank_correlation=0.5,
            rank_correlation_fail=0.3,
            strict=False,
        )
        codes = [w["code"] for w in warnings]
        assert "SHAP_EXTREME_CONCENTRATION" in codes

    def test_rank_disagreement_fail(self):
        failures, warnings = [], []
        _run_validation_checks(
            failures, warnings,
            family_results={
                "m1": {"raw_shap": np.ones((3, 3))},
                "m2": {"raw_shap": np.ones((3, 3))},
            },
            agg=self._make_agg(3),
            rank_correlations=[{"family_a": "m1", "family_b": "m2", "kendall_tau": 0.1, "p_value": 0.5}],
            feature_names=["a", "b", "c"],
            feature_lineage_spec=None,
            min_rank_correlation=0.5,
            rank_correlation_fail=0.3,
            strict=False,
        )
        codes = [f["code"] for f in failures]
        assert "SHAP_RANK_DISAGREEMENT" in codes

    def test_suspicious_feature_warning(self):
        failures, warnings = [], []
        agg = self._make_agg()
        agg["ranking"] = np.array([0, 1, 2, 3, 4])
        lineage = {
            "features": [
                {"name": "a", "temporal_category": "post_outcome"},
            ]
        }
        _run_validation_checks(
            failures, warnings,
            family_results={"m1": {"raw_shap": np.ones((5, 5))}},
            agg=agg,
            rank_correlations=[],
            feature_names=["a", "b", "c", "d", "e"],
            feature_lineage_spec=lineage,
            min_rank_correlation=0.5,
            rank_correlation_fail=0.3,
            strict=False,
        )
        codes = [w["code"] for w in warnings]
        assert "SHAP_SUSPICIOUS_TOP_FEATURE" in codes


# ────────────────────────────────────────────────────────
# Unit tests: CSV table writers
# ────────────────────────────────────────────────────────

class TestTableWriters:
    def test_table_a(self, tmp_path):
        features = ["a", "b", "c"]
        ranking = np.array([1, 0, 2])
        ensemble_prop = np.array([0.3, 0.5, 0.2])
        ensemble_signed = np.array([0.1, -0.2, 0.05])
        per_model_prop = {"m1": np.array([0.4, 0.4, 0.2]), "m2": np.array([0.2, 0.6, 0.2])}
        per_model_signed = {"m1": np.array([0.1, -0.1, 0.05]), "m2": np.array([0.1, -0.3, 0.05])}

        path = tmp_path / "table_a.csv"
        _write_table_a(path, features, ranking, ensemble_prop, ensemble_signed,
                       per_model_prop, per_model_signed, top_n=3)

        assert path.exists()
        with path.open() as f:
            reader = csv.reader(f)
            meta_row = next(reader)  # methodology annotation
            header = next(reader)
            rows = list(reader)

        assert meta_row[0].startswith("# Method:")
        assert header[0] == "Rank"
        assert header[1] == "Feature"
        assert header[2] == "Ensemble_Proportion"
        assert header[3] == "Direction"
        assert len(rows) == 3
        # First row should be feature 'b' (index 1, highest proportion)
        assert rows[0][1] == "b"
        assert rows[0][0] == "1"

    def test_table_c(self, tmp_path):
        rank_corrs = [
            {"family_a": "rf", "family_b": "xgb", "kendall_tau": 0.78, "p_value": 0.0003},
        ]
        per_model_abs = {
            "rf": np.array([0.5, 0.3, 0.2]),
            "xgb": np.array([0.4, 0.35, 0.25]),
        }
        path = tmp_path / "table_c.csv"
        _write_table_c(path, rank_corrs, per_model_abs, top_n=2)

        assert path.exists()
        with path.open() as f:
            reader = csv.reader(f)
            _meta = next(reader)  # skip annotation
            header = next(reader)
            rows = list(reader)

        assert "Kendall_Tau" in header
        assert len(rows) == 1
        assert rows[0][0] == "rf"

    def test_table_d(self, tmp_path):
        cases = [
            {
                "case_index": 0,
                "risk_category": "high_risk",
                "y_true": 1,
                "y_score": 0.92,
                "explaining_model": "rf",
                "top_drivers": [
                    {"feature": "age", "shap_value": 0.15, "abs_shap": 0.15, "direction": "increases risk"},
                    {"feature": "bmi", "shap_value": -0.08, "abs_shap": 0.08, "direction": "decreases risk"},
                    {"feature": "bp", "shap_value": 0.05, "abs_shap": 0.05, "direction": "increases risk"},
                ],
            }
        ]
        path = tmp_path / "table_d.csv"
        _write_table_d(path, cases)

        assert path.exists()
        with path.open() as f:
            reader = csv.reader(f)
            _meta = next(reader)  # skip annotation
            header = next(reader)
            rows = list(reader)

        assert "Driver_1_Feature" in header
        assert len(rows) == 1
        assert rows[0][5] == "age"  # Driver_1_Feature


# ────────────────────────────────────────────────────────
# Unit tests: Pipeline extraction
# ────────────────────────────────────────────────────────

class TestExtractClfAndTransform:
    def test_pipeline_extraction(self):
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler

        pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="mean")),
            ("scaler", StandardScaler()),
            ("clf", LogisticRegression()),
        ])
        X = np.array([[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]])
        y = np.array([0, 1, 0])
        pipe.fit(X, y)

        clf, X_transformed = _extract_clf_and_transform(pipe, X)
        assert type(clf).__name__ == "LogisticRegression"
        # X_transformed should be imputed + scaled
        assert X_transformed.shape == (3, 2)
        # Should be standardized (mean ~0, std ~1)
        assert abs(X_transformed.mean()) < 0.1

    def test_non_pipeline(self):
        from sklearn.linear_model import LogisticRegression

        clf = LogisticRegression()
        X = np.array([[1.0, 2.0]])
        out_clf, out_X = _extract_clf_and_transform(clf, X)
        assert out_clf is clf
        np.testing.assert_array_equal(out_X, X)


# ────────────────────────────────────────────────────────
# Integration tests (require shap)
# ────────────────────────────────────────────────────────

class TestIntegrationSHAP:
    @pytest.fixture(autouse=True)
    def _skip_if_no_shap(self):
        pytest.importorskip("shap")

    def test_e2e_subprocess(self, tmp_path):
        """End-to-end: generate data, train models, run gate via CLI."""
        train_path, test_path, feature_names, X_train, y_train = _make_synthetic_data(tmp_path)
        pool_path = _make_model_pool(tmp_path, X_train, y_train, feature_names)
        report_path = tmp_path / "report.json"

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "gates/shap_interpretability_gate.py"),
                "--model-pool", str(pool_path),
                "--train-data", str(train_path),
                "--test-data", str(test_path),
                "--target-col", "y",
                "--background-samples", "50",
                "--explain-samples", "50",
                "--top-n", "5",
                "--report", str(report_path),
                "--output-dir", str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        assert result.returncode == 0, f"Gate failed:\nstdout: {result.stdout}\nstderr: {result.stderr}"
        assert report_path.exists()

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["gate_name"] == "shap_interpretability_gate"
        assert report["status"] == "pass"
        assert "summary" in report

        summary = report["summary"]
        assert summary["model_count"] == 2
        assert "random_forest_balanced" in summary["families_analyzed"]
        assert "logistic_l2" in summary["families_analyzed"]
        assert len(summary["ensemble_top_features"]) == 5
        assert len(summary["rank_correlations"]) == 1

        # Verify CSV tables
        assert (tmp_path / "shap_table_a_ensemble_importance.csv").exists()
        assert (tmp_path / "shap_table_b_per_model_detail.csv").exists()
        assert (tmp_path / "shap_table_c_rank_agreement.csv").exists()
        assert (tmp_path / "shap_table_d_case_explanations.csv").exists()

        # Verify Table A structure (skip comment row)
        table_a = pd.read_csv(tmp_path / "shap_table_a_ensemble_importance.csv", comment="#")
        assert list(table_a.columns[:4]) == ["Rank", "Feature", "Ensemble_Proportion", "Direction"]
        assert len(table_a) == 5
        # Proportions should sum to less than 1 (only top-N features)
        assert table_a["Ensemble_Proportion"].sum() <= 1.0 + 1e-6

    def test_e2e_strict_mode(self, tmp_path):
        """Strict mode with a single model should produce warning → fail."""
        train_path, test_path, feature_names, X_train, y_train = _make_synthetic_data(tmp_path)

        # Build pool with only ONE family
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import Pipeline
        import joblib

        rf = Pipeline([
            ("imputer", SimpleImputer(strategy="mean")),
            ("clf", RandomForestClassifier(n_estimators=10, random_state=42)),
        ])
        rf.fit(X_train, y_train)

        pool = {
            "schema_version": 1,
            "families": {"rf": {"model_id": "rf0", "estimator": rf, "hyperparameters": {}, "cv_pr_auc_mean": 0.7}},
            "features": feature_names,
            "selected_model_id": "rf0",
        }
        pool_path = tmp_path / "pool.pkl"
        joblib.dump(pool, pool_path)

        report_path = tmp_path / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "gates/shap_interpretability_gate.py"),
                "--model-pool", str(pool_path),
                "--train-data", str(train_path),
                "--test-data", str(test_path),
                "--target-col", "y",
                "--background-samples", "30",
                "--explain-samples", "30",
                "--report", str(report_path),
                "--output-dir", str(tmp_path),
                "--strict",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Single model → SHAP_SINGLE_MODEL warning → strict promotes to fail
        assert result.returncode == 2
        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["status"] == "fail"

    def test_feature_mismatch_fails(self, tmp_path):
        """Mismatched features between pool and data should fail."""
        import joblib

        _, test_path, _, _, _ = _make_synthetic_data(tmp_path)

        # Pool with different feature names
        pool = {
            "schema_version": 1,
            "families": {},
            "features": ["WRONG_col_1", "WRONG_col_2"],
            "selected_model_id": "x",
        }
        pool_path = tmp_path / "pool.pkl"
        joblib.dump(pool, pool_path)

        report_path = tmp_path / "report.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPTS_DIR / "gates/shap_interpretability_gate.py"),
                "--model-pool", str(pool_path),
                "--train-data", str(test_path),
                "--test-data", str(test_path),
                "--target-col", "y",
                "--report", str(report_path),
                "--output-dir", str(tmp_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 2


# ── PDP / ICE computation ──────────────────────────────────────────────

class TestComputePDPICE:
    """Test PDP/ICE computation on simple sklearn models."""

    def _make_simple_model(self):
        """Create a trivially fitted LogisticRegression for testing."""
        from sklearn.linear_model import LogisticRegression
        rng = np.random.default_rng(42)
        X = rng.standard_normal((100, 3))
        y = (X[:, 0] > 0).astype(int)
        model = LogisticRegression(max_iter=200, random_state=42)
        model.fit(X, y)
        return model, X

    def test_pdp_returns_rows(self):
        model, X = self._make_simple_model()
        families = {"lr": {"estimator": model}}
        feature_names = ["f0", "f1", "f2"]
        rows = _compute_pdp_ice(
            families=families,
            X_data=X,
            feature_names=feature_names,
            top_feature_indices=[0, 1],
            grid_points=10,
        )
        assert len(rows) > 0
        assert all(k in rows[0] for k in ("family", "feature", "feature_value", "pd_value"))

    def test_pdp_correct_family_and_features(self):
        model, X = self._make_simple_model()
        families = {"lr": {"estimator": model}}
        feature_names = ["f0", "f1", "f2"]
        rows = _compute_pdp_ice(
            families=families,
            X_data=X,
            feature_names=feature_names,
            top_feature_indices=[0],
            grid_points=5,
        )
        assert all(r["family"] == "lr" for r in rows)
        assert all(r["feature"] == "f0" for r in rows)
        assert len(rows) == 5  # grid_points=5

    def test_pdp_constant_feature_warns(self):
        model, X = self._make_simple_model()
        X[:, 2] = 0.0
        families = {"lr": {"estimator": model}}
        warnings_list = []
        _compute_pdp_ice(
            families=families,
            X_data=X,
            feature_names=["f0", "f1", "f2"],
            top_feature_indices=[2],
            grid_points=10,
            warnings_list=warnings_list,
        )
        codes = [w["code"] for w in warnings_list]
        assert "PDP_FEATURE_CONSTANT" in codes

    def test_pdp_multiple_families(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.ensemble import RandomForestClassifier
        rng = np.random.default_rng(42)
        X = rng.standard_normal((100, 3))
        y = (X[:, 0] > 0).astype(int)
        lr = LogisticRegression(max_iter=200, random_state=42).fit(X, y)
        rf = RandomForestClassifier(n_estimators=5, random_state=42).fit(X, y)
        families = {"lr": {"estimator": lr}, "rf": {"estimator": rf}}
        rows = _compute_pdp_ice(
            families=families,
            X_data=X,
            feature_names=["f0", "f1", "f2"],
            top_feature_indices=[0],
            grid_points=5,
        )
        family_names = {r["family"] for r in rows}
        assert "lr" in family_names
        assert "rf" in family_names

    def test_pdp_disabled_with_empty_indices(self):
        model, X = self._make_simple_model()
        families = {"lr": {"estimator": model}}
        rows = _compute_pdp_ice(
            families=families,
            X_data=X,
            feature_names=["f0", "f1", "f2"],
            top_feature_indices=[],
            grid_points=10,
        )
        assert len(rows) == 0


class TestWriteTableE:
    def test_writes_csv(self, tmp_path):
        rows = [
            {"family": "lr", "feature": "age", "feature_value": 30.0, "pd_value": 0.5},
            {"family": "lr", "feature": "age", "feature_value": 50.0, "pd_value": 0.7},
        ]
        path = tmp_path / "table_e.csv"
        _write_table_e(path, rows)
        assert path.exists()
        with path.open() as fh:
            reader = csv.DictReader(fh)
            data = list(reader)
        assert len(data) == 2
        assert data[0]["family"] == "lr"
        assert data[0]["feature"] == "age"
