"""Tests for _gate_utils analysis tools: VIF, nonlinearity, MNAR, drift, model card, imputation, subgroup DCA, baseline, ablation, resources."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


from _gate_utils import (
    baseline_comparisons,
    calibration_metrics,
    check_nonlinearity,
    compute_nri_idi,
    compute_resource_report,
    compute_vif,
    feature_ablation,
    generate_model_card,
    imputation_sensitivity,
    learning_curve_data,
    mnar_sensitivity_analysis,
    robustness_stress_test,
    subgroup_dca,
    temporal_drift_analysis,
)


# ─── VIF ───

class TestComputeVIF:
    def test_independent_features(self):
        rng = np.random.default_rng(42)
        X = rng.standard_normal((200, 3))
        r = compute_vif(X, ["a", "b", "c"])
        assert all(v["flag"] == "ok" for v in r["vif_table"])
        assert r["max_vif"] < 2.0

    def test_collinear_features(self):
        rng = np.random.default_rng(42)
        x1 = rng.standard_normal(200)
        X = np.column_stack([x1, x1 + rng.normal(0, 0.05, 200), rng.standard_normal(200)])
        r = compute_vif(X, ["x1", "x1_copy", "x3"])
        assert len(r["critical_features"]) >= 1
        assert r["max_vif"] > 10

    def test_too_few_samples(self):
        X = np.random.randn(3, 10)
        r = compute_vif(X)
        assert "error" in r


# ─── Nonlinearity ───

class TestCheckNonlinearity:
    def test_linear_relationship(self):
        rng = np.random.default_rng(42)
        x = rng.standard_normal(500)
        y = (x > 0).astype(int)
        results = check_nonlinearity(x.reshape(-1, 1), y, ["x_linear"])
        assert not results[0].get("nonlinear", True)

    def test_quadratic_relationship(self):
        rng = np.random.default_rng(42)
        x = rng.standard_normal(500)
        logit = x ** 2 - 1
        y = (rng.random(500) < 1 / (1 + np.exp(-logit))).astype(int)
        results = check_nonlinearity(x.reshape(-1, 1), y, ["x_quad"])
        assert results[0].get("nonlinear") is True

    def test_constant_feature_skipped(self):
        x = np.ones((100, 1))
        y = np.random.choice([0, 1], 100)
        results = check_nonlinearity(x, y, ["const"])
        assert results[0].get("note") == "constant feature"

    def test_low_cardinality_skipped(self):
        x = np.random.choice([1, 2, 3], 100).reshape(-1, 1)
        y = np.random.choice([0, 1], 100)
        results = check_nonlinearity(x, y, ["cat"])
        assert "skip" in results[0].get("note", "")


# ─── MNAR Sensitivity ───

class TestMNARSensitivity:
    def test_basic(self):
        rng = np.random.default_rng(42)
        from sklearn.linear_model import LogisticRegression
        X = rng.standard_normal((200, 3))
        y = (X[:, 0] > 0).astype(int)
        mask = rng.random((200, 3)) < 0.1
        X[mask] = 0.0
        lr = LogisticRegression(max_iter=200)
        lr.fit(X[:150], y[:150])

        r = mnar_sensitivity_analysis(lr, X[:150], y[:150], X[150:], y[150:],
                                      mask[:150], mask[150:], deltas=[-0.2, 0, 0.2])
        assert r["baseline_score"] is not None
        assert len(r["delta_results"]) == 3

    def test_delta_zero_is_baseline(self):
        rng = np.random.default_rng(42)
        from sklearn.linear_model import LogisticRegression
        X = rng.standard_normal((200, 2))
        y = (X[:, 0] > 0).astype(int)
        mask = np.zeros((200, 2), dtype=bool)
        lr = LogisticRegression(max_iter=200).fit(X[:150], y[:150])

        r = mnar_sensitivity_analysis(lr, X[:150], y[:150], X[150:], y[150:],
                                      mask[:150], mask[150:], deltas=[0.0])
        assert r["baseline_score"] is not None


# ─── Temporal Drift ───

class TestTemporalDrift:
    def test_no_drift(self):
        rng = np.random.default_rng(42)
        n = 500
        y = rng.choice([0, 1], n, p=[0.7, 0.3])
        y_score = np.clip(y * 0.6 + rng.normal(0.3, 0.1, n), 0.01, 0.99)
        times = np.arange(n, dtype=float)
        r = temporal_drift_analysis(y, y_score, times, n_windows=5)
        assert r["n_windows"] == 5
        assert isinstance(r["drift_detected"], bool)

    def test_with_drift(self):
        rng = np.random.default_rng(42)
        n = 500
        y = rng.choice([0, 1], n, p=[0.7, 0.3])
        # Simulate drift: predictions become worse over time
        y_score = np.clip(0.3 + 0.002 * np.arange(n) + rng.normal(0, 0.05, n), 0.01, 0.99)
        times = np.arange(n, dtype=float)
        r = temporal_drift_analysis(y, y_score, times, n_windows=5)
        assert len(r["per_window"]) == 5
        assert len(r["cusum_values"]) >= 3


# ─── Model Card ───

class TestGenerateModelCard:
    def test_basic(self):
        card = generate_model_card(
            "Test Model", "LR",
            {"summary": {"metrics": {"auroc": 0.75, "mcc": 0.3}}},
        )
        assert "# Model Card: Test Model" in card
        assert "## Performance" in card
        assert "## Limitations" in card
        assert "## Ethical Considerations" in card

    def test_with_cohort_report(self):
        card = generate_model_card(
            "Model", "RF",
            {"summary": {"metrics": {"auroc": 0.8}}},
            cohort_report={"summary": {"n_rows": 1000, "n_features": 20,
                           "target": {"n_positive": 150, "prevalence": 0.15, "epv": 7.5}}},
        )
        assert "1000" in card
        assert "## Training Data" in card


# ─── Imputation Sensitivity ───

class TestImputationSensitivity:
    def test_basic(self):
        rng = np.random.default_rng(42)
        from sklearn.linear_model import LogisticRegression
        X = rng.standard_normal((200, 3))
        X[rng.random((200, 3)) < 0.1] = np.nan
        y = rng.choice([0, 1], 200)
        r = imputation_sensitivity(X, y, LogisticRegression(max_iter=200), ["a", "b", "c"])
        methods = [m["method"] for m in r["methods"]]
        assert "median" in methods
        assert "mean" in methods
        assert r["roc_auc_spread"] is not None

    def test_no_missing(self):
        rng = np.random.default_rng(42)
        from sklearn.linear_model import LogisticRegression
        X = rng.standard_normal((200, 3))
        y = rng.choice([0, 1], 200)
        r = imputation_sensitivity(X, y, LogisticRegression(max_iter=200), ["a", "b", "c"])
        assert r["missing_fraction"] == 0.0


# ─── Subgroup DCA ───

class TestSubgroupDCA:
    def test_basic(self):
        rng = np.random.default_rng(42)
        n = 300
        y = rng.choice([0, 1], n, p=[0.7, 0.3])
        y_score = np.clip(y * 0.5 + rng.normal(0.3, 0.15, n), 0.01, 0.99)
        groups = rng.choice(["A", "B"], n)
        r = subgroup_dca(y, y_score, groups)
        assert "A" in r["group_curves"]
        assert "B" in r["group_curves"]
        assert r["equity_gap"] is not None

    def test_small_group_skipped(self):
        rng = np.random.default_rng(42)
        n = 100
        y = rng.choice([0, 1], n)
        y_score = rng.random(n)
        groups = np.array(["A"] * 90 + ["tiny"] * 10)
        r = subgroup_dca(y, y_score, groups)
        assert r["group_curves"].get("tiny") == []  # n=10 < 20, skipped

    def test_single_group(self):
        rng = np.random.default_rng(42)
        n = 100
        y = rng.choice([0, 1], n)
        y_score = rng.random(n)
        groups = np.array(["only"] * n)
        r = subgroup_dca(y, y_score, groups)
        assert r["equity_gap"] is None  # only 1 group


# ─── Calibration metrics edge cases ───

class TestCalibrationEdgeCases:
    def test_constant_y_score(self):
        y = np.array([0, 1, 0, 1])
        y_score = np.array([0.5, 0.5, 0.5, 0.5])
        r = calibration_metrics(y, y_score)
        assert "error" in r

    def test_single_class(self):
        y = np.array([0, 0, 0, 0])
        y_score = np.array([0.1, 0.2, 0.3, 0.4])
        r = calibration_metrics(y, y_score)
        assert "error" in r


# ─── NRI edge cases ───

class TestNRIEdgeCases:
    def test_no_events(self):
        y = np.array([0, 0, 0, 0])
        r = compute_nri_idi(y, np.random.rand(4), np.random.rand(4))
        assert r["categorical_nri"] is None
        assert "error" in r

    def test_normal(self):
        rng = np.random.default_rng(42)
        y = rng.choice([0, 1], 200)
        p_old = rng.random(200) * 0.5
        p_new = rng.random(200) * 0.5 + 0.1
        r = compute_nri_idi(y, p_old, p_new)
        assert r["categorical_nri"] is not None
        assert isinstance(r["idi"], float)


# ─── Learning curve edge cases ───

class TestLearningCurveEdgeCases:
    def test_basic(self):
        from sklearn.linear_model import LogisticRegression
        rng = np.random.default_rng(42)
        X = rng.standard_normal((200, 3))
        y = (X[:, 0] > 0).astype(int)
        lr = LogisticRegression(max_iter=200).fit(X[:150], y[:150])
        results = learning_curve_data(lr, X[:150], y[:150], X[150:], y[150:],
                                      fractions=[0.3, 0.7, 1.0])
        assert len(results) >= 2
        assert all("test_score" in r for r in results)


# ─── Baseline Comparisons (NC 4D) ───

class TestBaselineComparisons:
    def test_better_than_random(self):
        rng = np.random.default_rng(42)
        n = 200
        y = rng.choice([0, 1], n, p=[0.7, 0.3])
        y_score = np.clip(y * 0.6 + rng.normal(0.3, 0.1, n), 0.01, 0.99)
        y_pred = (y_score > 0.5).astype(int)
        r = baseline_comparisons(y, y_score, y_pred)
        assert r["model"]["roc_auc"] > 0.5
        assert r["improvement_over_baseline"]["roc_auc_over_random"] > 0
        assert r["improvement_over_baseline"]["brier_skill_score"] > 0

    def test_prevalence_baseline(self):
        rng = np.random.default_rng(42)
        n = 100
        y = rng.choice([0, 1], n, p=[0.8, 0.2])
        y_score = np.full(n, 0.2)  # predict prevalence for everyone
        y_pred = np.zeros(n, dtype=int)
        r = baseline_comparisons(y, y_score, y_pred)
        assert r["prevalence_baseline"]["roc_auc"] == 0.5
        assert r["all_positive"]["sensitivity"] == 1.0
        assert r["all_negative"]["specificity"] == 1.0


# ─── Feature Ablation (NC 4F) ───

class TestFeatureAblation:
    def test_basic(self):
        from sklearn.ensemble import RandomForestClassifier
        rng = np.random.default_rng(42)
        X = rng.standard_normal((200, 5))
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        rf = RandomForestClassifier(n_estimators=20, random_state=42)
        results = feature_ablation(rf, X[:150], y[:150], X[150:], y[150:],
                                   ["f0", "f1", "f2", "f3", "f4"], top_n=3)
        assert len(results) == 3
        assert all("delta" in r for r in results)
        # Top features should have positive importance
        assert results[0]["permutation_importance"] > 0

    def test_empty_on_failure(self):
        # Bad estimator that can't predict
        from sklearn.linear_model import LogisticRegression
        results = feature_ablation(
            LogisticRegression(), np.array([[1]]), np.array([0]),
            np.array([[1]]), np.array([0]), ["x"], top_n=1,
        )
        assert results == []


# ─── Compute Resource Report (NC 5A/5B) ───

class TestComputeResourceReport:
    def test_basic(self):
        import time
        t0 = time.time()
        time.sleep(0.01)
        t1 = time.time()
        r = compute_resource_report(t0, t1, "TestModel", 1000, 50)
        assert r["wall_time_seconds"] >= 0
        assert r["n_train_samples"] == 1000
        assert r["n_features"] == 50
        assert "cpu_count" in r["hardware"]
        assert r["hardware"]["cpu_count"] > 0
        assert "m" in r["wall_time_human"]


# ─── Robustness Stress Test ───

class TestRobustnessStressTest:
    def test_basic(self):
        from sklearn.ensemble import RandomForestClassifier
        rng = np.random.default_rng(42)
        X = rng.standard_normal((300, 5))
        y = (X[:, 0] + X[:, 1] > 0).astype(int)
        rf = RandomForestClassifier(n_estimators=20, random_state=42).fit(X[:200], y[:200])
        r = robustness_stress_test(rf, X[:200], y[:200], X[200:], y[200:])
        assert r["baseline"] > 0.5
        assert len(r["perturbations"]) == 4
        assert r["verdict"] in ("robust", "sensitive")
        assert isinstance(r["max_relative_drop_pct"], float)

    def test_training_data_immutable(self):
        from sklearn.linear_model import LogisticRegression
        rng = np.random.default_rng(42)
        X = rng.standard_normal((200, 3))
        y = (X[:, 0] > 0).astype(int)
        X_train = X[:150].copy()
        original = X_train.copy()
        lr = LogisticRegression(max_iter=200).fit(X_train, y[:150])
        robustness_stress_test(lr, X_train, y[:150], X[150:], y[150:])
        np.testing.assert_array_equal(X_train, original)

    def test_perfect_model_robust(self):
        from sklearn.ensemble import RandomForestClassifier
        rng = np.random.default_rng(42)
        X = np.vstack([rng.normal(-5, 0.1, (100, 3)), rng.normal(5, 0.1, (100, 3))])
        y = np.array([0]*100 + [1]*100)
        rf = RandomForestClassifier(n_estimators=10, random_state=42).fit(X[:150], y[:150])
        r = robustness_stress_test(rf, X[:150], y[:150], X[150:], y[150:])
        assert r["max_relative_drop_pct"] < 10  # perfect sep → robust

    def test_estimator_unchanged(self):
        from sklearn.ensemble import RandomForestClassifier
        rng = np.random.default_rng(42)
        X = rng.standard_normal((200, 3))
        y = (X[:, 0] > 0).astype(int)
        rf = RandomForestClassifier(n_estimators=10, random_state=42).fit(X[:150], y[:150])
        pred_before = rf.predict_proba(X[150:]).copy()
        robustness_stress_test(rf, X[:150], y[:150], X[150:], y[150:])
        pred_after = rf.predict_proba(X[150:])
        np.testing.assert_array_equal(pred_before, pred_after)
