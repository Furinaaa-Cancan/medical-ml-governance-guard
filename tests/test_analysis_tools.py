"""Tests for _gate_utils analysis tools: VIF, nonlinearity, MNAR, drift, model card, imputation, subgroup DCA, baseline, ablation, resources."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest


from _gate_utils import (
    baseline_comparisons,
    bonferroni_adjusted_threshold,
    bootstrap_optimism_correction,
    calibration_bin_ci,
    calibration_metrics,
    check_nonlinearity,
    compute_nri_idi,
    compute_resource_report,
    compute_vif,
    export_model_coefficients,
    fdr_bh_correction,
    feature_ablation,
    generate_model_card,
    imputation_sensitivity,
    learning_curve_data,
    mnar_sensitivity_analysis,
    robustness_stress_test,
    rubins_rules_combine,
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

    def test_calibration_intercept_is_citl_not_joint(self):
        """Regression test for 2026-04-19: `calibration_intercept` must
        be Van Calster 2019 calibration-in-the-large (offset fit with
        slope=1), not the joint-fit α. The two diverge when the
        underlying miscalibration affects the SLOPE (over-/under-
        confidence) rather than just the level.

        Setup: low-prevalence task (logit_true ~ N(-1.5, 1), prev ≈ 0.15).
        Biased predictor doubles the logit — `logit(p_biased) = 2·logit_true`
        — so predictions are too extreme in both directions.
          Joint fit should recover β ≈ 0.5 and α ≈ 0 (inverts the scale).
          CITL must compensate with slope fixed at 1, so α ≠ 0.
        """
        rng = np.random.default_rng(7)
        n = 4000
        logit_true = rng.standard_normal(n) - 1.5  # skewed-negative logit
        p_true = 1.0 / (1.0 + np.exp(-logit_true))
        y = (rng.uniform(0, 1, n) < p_true).astype(int)
        # Over-confident predictor (slope = 2 in logit space).
        p_biased = 1.0 / (1.0 + np.exp(-2.0 * logit_true))

        r = calibration_metrics(y, p_biased, n_bins=10)
        assert "error" not in r
        assert "calibration_intercept" in r
        assert "calibration_intercept_joint" in r
        citl = r["calibration_intercept"]
        joint = r["calibration_intercept_joint"]
        slope = r["calibration_slope"]
        # Slope should be ≈ 0.5 (inverting the 2x over-confidence).
        assert 0.3 < slope < 0.7, f"Expected joint slope ≈ 0.5, got {slope}"
        # Joint-fit α near 0 (symmetric miscalibration + best β).
        assert abs(joint) < 0.3, f"Expected joint α ≈ 0, got {joint}"
        # CITL has to absorb the mis-scale with intercept alone → nontrivial.
        assert citl > 0.8, (
            f"Expected CITL α substantially > 0 on over-confident predictor; "
            f"got citl={citl}, joint={joint}"
        )
        assert abs(citl - joint) > 0.5, (
            f"CITL and joint-fit intercept should differ materially when "
            f"slope ≠ 1; got citl={citl}, joint={joint}, slope={slope}"
        )

    def test_hl_df_tracks_populated_bins(self):
        """Regression test for 2026-04-19: Hosmer-Lemeshow df must
        reflect bins that ACTUALLY contributed to the chi-sq sum, not
        the nominal n_bins. If predictions cluster in a few bins, empty
        bins are silently skipped above and df must drop accordingly —
        otherwise the p-value is inflated and calibration looks better
        than it is."""
        rng = np.random.default_rng(0)
        n = 500
        # Predictions clustered in [0.0, 0.3] — bins 0-2 populated, 3-9 empty.
        y_score = rng.uniform(0.0, 0.3, n)
        # Well-calibrated labels around these scores.
        y_true = (rng.uniform(0, 1, n) < y_score).astype(int)
        r = calibration_metrics(y_true, y_score, n_bins=10)
        assert "error" not in r
        populated = sum(1 for b in r["bin_data"] if b["n"] > 0)
        assert populated < 10, (
            "Test setup precondition: need some empty bins in [0.3, 1.0]"
        )
        # df should equal populated-2 (or 1 for tiny cases), NOT nominal 8.
        assert r["hosmer_lemeshow_df"] == max(populated - 2, 1), (
            f"HL df drifted from populated bins. populated={populated}, "
            f"reported_df={r['hosmer_lemeshow_df']}, expected={max(populated-2, 1)}"
        )
        assert r["hosmer_lemeshow_df"] < 8, (
            "df must be less than n_bins-2 when some bins are empty"
        )


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
        # Stratified split: ensure both classes in train and test
        rf = RandomForestClassifier(n_estimators=10, random_state=42).fit(X[:160:2], y[:160:2])
        X_test = np.vstack([X[1:160:2], X[160:]])
        y_test = np.concatenate([y[1:160:2], y[160:]])
        r = robustness_stress_test(rf, X[:160:2], y[:160:2], X_test, y_test)
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

    def test_feature_zeroing_enters_verdict(self):
        """Regression test for 2026-04-19 fix: feature_zeroing must be
        surfaced as `relative_drop_pct` so it counts toward the robust/
        sensitive verdict. Before the fix, a model that collapsed when
        its top feature was zeroed could still be certified as robust
        because the verdict loop only inspected relative_drop_pct, which
        feature_zeroing never emitted."""
        from sklearn.linear_model import LogisticRegression
        rng = np.random.default_rng(0)
        # Single-feature-dominant model: LR with one predictive feature
        # and four pure-noise features. Zeroing out the top variance
        # feature (the predictive one) should collapse performance.
        n = 400
        x_signal = rng.standard_normal(n) * 10  # high variance → top-ranked
        noise = rng.standard_normal((n, 4)) * 0.01
        X = np.column_stack([x_signal, noise])
        y = (x_signal > 0).astype(int)
        lr = LogisticRegression(max_iter=300).fit(X[:300], y[:300])
        r = robustness_stress_test(
            lr, X[:300], y[:300], X[300:], y[300:],
            top_n_features=1,
        )
        # feature_zeroing perturbation must expose relative_drop_pct
        fz = next(p for p in r["perturbations"] if "feature_zeroing" in p["type"])
        assert fz.get("relative_drop_pct") is not None, (
            "feature_zeroing must emit relative_drop_pct for verdict aggregation"
        )
        assert fz["relative_drop_pct"] > 0, fz
        # And the verdict must acknowledge it — zeroing the only predictive
        # feature should never certify the model as robust.
        assert r["max_relative_drop_pct"] >= fz["relative_drop_pct"], (
            "max_relative_drop_pct must include feature_zeroing's drop; "
            f"got max={r['max_relative_drop_pct']} vs fz={fz['relative_drop_pct']}"
        )
        assert not r["robust"], (
            f"Collapsing under feature zeroing must flip robust=False; "
            f"got verdict={r['verdict']}, perturbations={r['perturbations']}"
        )


# ─── FDR BH Correction ───

class TestFdrBhCorrection:
    def test_all_significant(self):
        pvals = [0.001, 0.002, 0.003, 0.004]
        r = fdr_bh_correction(pvals, alpha=0.05)
        assert r["n_tests"] == 4
        assert r["n_rejected"] == 4
        assert all(r["rejected"])
        # Adjusted p-values should be >= raw p-values
        for raw, adj in zip(r["pvalues_raw"], r["pvalues_adjusted"]):
            assert adj >= raw

    def test_none_significant(self):
        pvals = [0.5, 0.6, 0.7, 0.8]
        r = fdr_bh_correction(pvals, alpha=0.05)
        assert r["n_rejected"] == 0
        assert not any(r["rejected"])

    def test_mixed(self):
        pvals = [0.001, 0.04, 0.5, 0.9]
        r = fdr_bh_correction(pvals, alpha=0.05)
        assert r["n_rejected"] >= 1
        # First p-value should be rejected
        assert r["rejected"][0] is True

    def test_empty(self):
        r = fdr_bh_correction([], alpha=0.05)
        assert r["n_tests"] == 0
        assert r["n_rejected"] == 0

    def test_single(self):
        r = fdr_bh_correction([0.03], alpha=0.05)
        assert r["n_rejected"] == 1
        assert r["pvalues_adjusted"][0] == pytest.approx(0.03, abs=1e-9)

    def test_nan_and_inf_treated_as_nonsignificant(self):
        r = fdr_bh_correction([0.001, float("nan"), float("inf")])
        assert r["n_tests"] == 3
        # nan/inf become 1.0 → not rejected
        assert r["rejected"][0] is True
        assert r["rejected"][1] is False
        assert r["rejected"][2] is False

    def test_monotonicity(self):
        """Adjusted p-values should be monotonically non-decreasing when sorted by raw p-value."""
        pvals = [0.01, 0.03, 0.05, 0.10, 0.20]
        r = fdr_bh_correction(pvals)
        # Sort by raw p-value and check adjusted are non-decreasing
        pairs = sorted(zip(r["pvalues_raw"], r["pvalues_adjusted"]))
        adjusted_sorted = [adj for _, adj in pairs]
        for i in range(len(adjusted_sorted) - 1):
            assert adjusted_sorted[i] <= adjusted_sorted[i + 1] + 1e-12


# ─── Bonferroni Adjusted Threshold ───

class TestBonferroniAdjustedThreshold:
    def test_basic(self):
        assert bonferroni_adjusted_threshold(0.05, 10) == pytest.approx(0.005)

    def test_single_comparison(self):
        assert bonferroni_adjusted_threshold(0.05, 1) == 0.05

    def test_zero_comparisons(self):
        # n<=1 returns original threshold
        assert bonferroni_adjusted_threshold(0.05, 0) == 0.05


# ─── Bootstrap Optimism Correction ───

class TestBootstrapOptimismCorrection:
    def test_basic(self):
        from sklearn.linear_model import LogisticRegression
        rng = np.random.default_rng(42)
        X = rng.standard_normal((200, 3))
        y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(int)
        r = bootstrap_optimism_correction(
            LogisticRegression(max_iter=500), X, y,
            n_bootstrap=50, metric="roc_auc", seed=42,
        )
        assert "error" not in r
        assert r["apparent"] > 0.5
        assert r["mean_optimism"] >= -0.05  # typically positive, allow small negative from bootstrap noise
        assert r["corrected"] <= r["apparent"] + 0.05  # corrected ≈ apparent - optimism
        assert r["metric"] == "roc_auc"
        assert r["n_valid_bootstrap"] >= 10
        assert r["shrinkage_factor"] is not None
        assert 0 < r["shrinkage_factor"] <= 1.0

    def test_pr_auc_metric(self):
        from sklearn.linear_model import LogisticRegression
        rng = np.random.default_rng(42)
        X = rng.standard_normal((200, 3))
        y = (X[:, 0] > 0).astype(int)
        r = bootstrap_optimism_correction(
            LogisticRegression(max_iter=500), X, y,
            n_bootstrap=50, metric="pr_auc", seed=42,
        )
        assert "error" not in r
        assert r["metric"] == "pr_auc"

    def test_too_few_samples(self):
        from sklearn.linear_model import LogisticRegression
        X = np.array([[1], [2]])
        y = np.array([0, 1])
        r = bootstrap_optimism_correction(
            LogisticRegression(), X, y, n_bootstrap=5,
        )
        assert "error" in r


# ─── Export Model Coefficients ───

class TestExportModelCoefficients:
    def test_logistic_regression(self):
        from sklearn.linear_model import LogisticRegression
        rng = np.random.default_rng(42)
        X = rng.standard_normal((100, 3))
        y = (X[:, 0] > 0).astype(int)
        lr = LogisticRegression(max_iter=200).fit(X, y)
        r = export_model_coefficients(lr, ["a", "b", "c"])
        assert r is not None
        assert len(r) == 3
        assert r[0]["rank"] == 1
        assert "coefficient" in r[0]
        assert "abs_coefficient" in r[0]
        # Ranks are 1-based and ordered by abs coefficient descending
        assert r[0]["abs_coefficient"] >= r[1]["abs_coefficient"]

    def test_random_forest(self):
        from sklearn.ensemble import RandomForestClassifier
        rng = np.random.default_rng(42)
        X = rng.standard_normal((100, 3))
        y = (X[:, 0] > 0).astype(int)
        rf = RandomForestClassifier(n_estimators=10, random_state=42).fit(X, y)
        r = export_model_coefficients(rf, ["a", "b", "c"])
        assert r is not None
        assert len(r) == 3
        assert "importance" in r[0]

    def test_pipeline(self):
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        rng = np.random.default_rng(42)
        X = rng.standard_normal((100, 2))
        y = (X[:, 0] > 0).astype(int)
        pipe = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(max_iter=200))])
        pipe.fit(X, y)
        r = export_model_coefficients(pipe, ["a", "b"])
        assert r is not None
        assert len(r) == 2

    def test_unsupported_estimator(self):
        from sklearn.neighbors import KNeighborsClassifier
        knn = KNeighborsClassifier().fit([[0], [1]], [0, 1])
        r = export_model_coefficients(knn, ["x"])
        assert r is None

    def test_mismatched_features(self):
        from sklearn.linear_model import LogisticRegression
        lr = LogisticRegression(max_iter=200).fit([[0, 1], [1, 0]], [0, 1])
        r = export_model_coefficients(lr, ["only_one"])
        assert r is None


# ─── Calibration Bin CI ───

class TestCalibrationBinCI:
    def test_basic(self):
        rng = np.random.default_rng(42)
        n = 500
        y_score = rng.random(n)
        y_true = (rng.random(n) < y_score).astype(int)
        bins = calibration_bin_ci(y_true, y_score, n_bins=5, n_bootstrap=200, seed=42)
        assert len(bins) == 5
        for b in bins:
            assert "bin" in b
            assert "mean_predicted" in b
            assert "fraction_positive" in b
            if b["n"] >= 2:
                assert b["ci_lower"] is not None
                assert b["ci_upper"] is not None
                assert b["ci_lower"] <= b["fraction_positive"] <= b["ci_upper"]

    def test_sparse_bins(self):
        """Bins with <2 samples should have None CI."""
        y_true = np.array([0, 1])
        y_score = np.array([0.05, 0.95])
        bins = calibration_bin_ci(y_true, y_score, n_bins=10, n_bootstrap=50)
        # Most bins will be empty or have 1 sample
        empty_bins = [b for b in bins if b["n"] < 2]
        for b in empty_bins:
            assert b["ci_lower"] is None
            assert b["ci_upper"] is None


# ─── Rubin's Rules ───

class TestRubinsRulesCombine:
    def test_basic_with_variances(self):
        estimates = [0.75, 0.78, 0.73, 0.76, 0.77]
        variances = [0.01, 0.012, 0.011, 0.009, 0.01]
        r = rubins_rules_combine(estimates, variances)
        assert r["n_imputations"] == 5
        assert r["pooled_estimate"] == pytest.approx(np.mean(estimates), abs=1e-4)
        assert r["between_variance"] > 0
        assert r["within_variance"] is not None
        assert r["total_variance"] > r["between_variance"]
        assert r["total_se"] > 0
        assert r["degrees_of_freedom"] > 0

    def test_without_variances(self):
        estimates = [0.80, 0.82, 0.79]
        r = rubins_rules_combine(estimates)
        assert r["n_imputations"] == 3
        assert r["within_variance"] is None
        assert r["total_variance"] > 0
        assert r["degrees_of_freedom"] == 2  # m-1

    def test_single_imputation_error(self):
        r = rubins_rules_combine([0.75])
        assert "error" in r
        assert r["pooled_estimate"] == pytest.approx(0.75)

    def test_identical_estimates(self):
        r = rubins_rules_combine([0.80, 0.80, 0.80])
        assert r["between_variance"] == pytest.approx(0.0, abs=1e-10)
        assert r["pooled_estimate"] == pytest.approx(0.80, abs=1e-6)
