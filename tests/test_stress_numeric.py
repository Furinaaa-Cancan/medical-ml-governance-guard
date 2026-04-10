"""
Stress tests for numeric utilities — exhaustive edge cases, boundary values,
and large-scale metric computations.

These tests are designed for overnight CI runs (~1-2 hours).
"""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pytest


from _gate_utils import (
    canonical_metric_token,
    confusion_counts,
    is_finite_number,
    metric_panel,
    normalize_binary,
    safe_ratio,
    to_float,
    to_int,
)


# ────────────────────────────────────────────────────────
# to_float exhaustive
# ────────────────────────────────────────────────────────

class TestToFloatExhaustive:
    @pytest.mark.parametrize("value,expected", [
        (0, 0.0),
        (1, 1.0),
        (-1, -1.0),
        (0.5, 0.5),
        (-0.5, -0.5),
        (1e10, 1e10),
        (1e-10, 1e-10),
        (-1e10, -1e10),
        (2**53, float(2**53)),
    ])
    def test_valid_numeric(self, value: Any, expected: float):
        assert to_float(value) == expected

    @pytest.mark.parametrize("value", [
        float("inf"), float("-inf"), float("nan"),
        True, False, None, [], {}, set(), object(),
        "abc", "", "  ", "inf", "nan", "NaN", "INF",
    ])
    def test_rejected_values(self, value: Any):
        assert to_float(value) is None

    @pytest.mark.parametrize("s,expected", [
        ("0", 0.0),
        ("1.5", 1.5),
        ("-3.14", -3.14),
        ("  42  ", 42.0),
        ("1e5", 1e5),
        (" -0.001 ", -0.001),
    ])
    def test_valid_string(self, s: str, expected: float):
        assert to_float(s) == expected

    @pytest.mark.slow
    def test_many_random_floats(self):
        rng = np.random.default_rng(42)
        for _ in range(100_000):
            val = rng.uniform(-1e6, 1e6)
            result = to_float(val)
            assert result is not None
            assert math.isfinite(result)

    @pytest.mark.slow
    def test_many_random_strings(self):
        rng = np.random.default_rng(42)
        for _ in range(50_000):
            val = str(rng.uniform(-1e6, 1e6))
            result = to_float(val)
            assert result is not None


# ────────────────────────────────────────────────────────
# to_int exhaustive
# ────────────────────────────────────────────────────────

class TestToIntExhaustive:
    @pytest.mark.parametrize("value,expected", [
        (0, 0), (1, 1), (-1, -1), (42, 42),
        (1.0, 1), (0.0, 0), (-3.0, -3),
    ])
    def test_valid(self, value: Any, expected: int):
        assert to_int(value) == expected

    @pytest.mark.parametrize("value", [
        True, False, None, 0.5, -0.1, float("inf"), float("nan"),
        "1", [], {},
    ])
    def test_rejected(self, value: Any):
        assert to_int(value) is None


# ────────────────────────────────────────────────────────
# is_finite_number exhaustive
# ────────────────────────────────────────────────────────

class TestIsFiniteNumberExhaustive:
    @pytest.mark.parametrize("value", [0, 1, -1, 0.0, 1.5, -1e10, 2**53])
    def test_finite(self, value: Any):
        assert is_finite_number(value) is True

    @pytest.mark.parametrize("value", [
        True, False, float("inf"), float("-inf"), float("nan"),
        "1", None, [], {},
    ])
    def test_not_finite(self, value: Any):
        assert is_finite_number(value) is False


# ────────────────────────────────────────────────────────
# safe_ratio exhaustive
# ────────────────────────────────────────────────────────

class TestSafeRatioExhaustive:
    def test_normal(self):
        assert safe_ratio(10, 5) == 2.0

    def test_zero_denominator(self):
        assert safe_ratio(10, 0) == 0.0

    def test_negative_denominator(self):
        assert safe_ratio(10, -1) == 0.0

    def test_zero_numerator(self):
        assert safe_ratio(0, 10) == 0.0

    def test_both_zero(self):
        assert safe_ratio(0, 0) == 0.0

    @pytest.mark.slow
    def test_many_random_ratios(self):
        rng = np.random.default_rng(42)
        for _ in range(100_000):
            num = rng.uniform(-1000, 1000)
            den = rng.uniform(-1000, 1000)
            result = safe_ratio(num, den)
            if den > 0:
                assert result == float(num) / float(den)
            else:
                assert result == 0.0


# ────────────────────────────────────────────────────────
# confusion_counts exhaustive
# ────────────────────────────────────────────────────────

class TestConfusionCountsExhaustive:
    def test_perfect_prediction(self):
        y = np.array([0, 0, 1, 1])
        cm = confusion_counts(y, y)
        assert cm == {"tp": 2, "fp": 0, "tn": 2, "fn": 0}

    def test_worst_prediction(self):
        y_true = np.array([0, 0, 1, 1])
        y_pred = np.array([1, 1, 0, 0])
        cm = confusion_counts(y_true, y_pred)
        assert cm == {"tp": 0, "fp": 2, "tn": 0, "fn": 2}

    def test_all_positive(self):
        y_true = np.array([1, 1, 1])
        y_pred = np.array([1, 1, 1])
        cm = confusion_counts(y_true, y_pred)
        assert cm["tp"] == 3
        assert cm["fp"] == 0

    def test_all_negative(self):
        y_true = np.array([0, 0, 0])
        y_pred = np.array([0, 0, 0])
        cm = confusion_counts(y_true, y_pred)
        assert cm["tn"] == 3

    def test_single_element(self):
        cm = confusion_counts(np.array([1]), np.array([0]))
        assert cm == {"tp": 0, "fp": 0, "tn": 0, "fn": 1}

    def test_counts_sum_to_n(self):
        rng = np.random.default_rng(42)
        for n in [10, 100, 1000]:
            y_true = rng.integers(0, 2, size=n)
            y_pred = rng.integers(0, 2, size=n)
            cm = confusion_counts(y_true, y_pred)
            assert cm["tp"] + cm["fp"] + cm["tn"] + cm["fn"] == n

    @pytest.mark.slow
    def test_large_arrays(self):
        rng = np.random.default_rng(42)
        for _ in range(100):
            n = 100_000
            y_true = rng.integers(0, 2, size=n)
            y_pred = rng.integers(0, 2, size=n)
            cm = confusion_counts(y_true, y_pred)
            assert cm["tp"] + cm["fp"] + cm["tn"] + cm["fn"] == n
            assert all(v >= 0 for v in cm.values())


# ────────────────────────────────────────────────────────
# normalize_binary exhaustive
# ────────────────────────────────────────────────────────

class TestNormalizeBinaryExhaustive:
    def test_valid_binary(self):
        import pandas as pd
        s = pd.Series([0, 1, 1, 0])
        result = normalize_binary(s)
        assert result is not None
        np.testing.assert_array_equal(result, [0, 1, 1, 0])

    def test_float_binary(self):
        import pandas as pd
        s = pd.Series([0.0, 1.0, 1.0, 0.0])
        result = normalize_binary(s)
        assert result is not None

    def test_non_binary_rejected(self):
        import pandas as pd
        s = pd.Series([0, 1, 2, 3])
        assert normalize_binary(s) is None

    def test_nan_rejected(self):
        import pandas as pd
        s = pd.Series([0, 1, float("nan"), 0])
        assert normalize_binary(s) is None

    def test_string_coercion(self):
        import pandas as pd
        s = pd.Series(["0", "1", "1", "0"])
        result = normalize_binary(s)
        assert result is not None

    def test_non_numeric_string_rejected(self):
        import pandas as pd
        s = pd.Series(["yes", "no"])
        assert normalize_binary(s) is None


# ────────────────────────────────────────────────────────
# metric_panel exhaustive
# ────────────────────────────────────────────────────────

class TestMetricPanelExhaustive:
    def _make_data(self, n: int, seed: int = 42):
        rng = np.random.default_rng(seed)
        y_true = rng.integers(0, 2, size=n)
        y_score = rng.uniform(0, 1, size=n)
        y_pred = (y_score >= 0.5).astype(int)
        return y_true, y_score, y_pred

    def test_basic_panel(self):
        y_true, y_score, y_pred = self._make_data(200)
        metrics, cm = metric_panel(y_true, y_score, y_pred, beta=2.0)
        assert set(metrics.keys()) == {
            "accuracy", "precision", "ppv", "npv",
            "sensitivity", "specificity", "f1", "f2_beta",
            "roc_auc", "pr_auc", "brier",
            "lr_positive", "lr_negative", "mcc",
        }
        for k, v in metrics.items():
            assert isinstance(v, float), f"{k} is not float"
            if k not in ("lr_positive", "lr_negative", "mcc"):
                assert 0 <= v <= 1, f"{k}={v} out of [0,1]"

    def test_ppv_equals_precision(self):
        y_true, y_score, y_pred = self._make_data(200)
        metrics, _ = metric_panel(y_true, y_score, y_pred, beta=2.0)
        assert metrics["ppv"] == metrics["precision"]

    def test_perfect_predictions(self):
        y_true = np.array([0, 0, 0, 1, 1, 1])
        y_score = np.array([0.0, 0.1, 0.2, 0.8, 0.9, 1.0])
        y_pred = np.array([0, 0, 0, 1, 1, 1])
        metrics, cm = metric_panel(y_true, y_score, y_pred, beta=2.0)
        assert metrics["accuracy"] == 1.0
        assert metrics["precision"] == 1.0
        assert metrics["sensitivity"] == 1.0
        assert metrics["specificity"] == 1.0
        assert metrics["f1"] == 1.0

    def test_confusion_matrix_consistency(self):
        y_true, y_score, y_pred = self._make_data(500)
        metrics, cm = metric_panel(y_true, y_score, y_pred, beta=2.0)
        total = cm["tp"] + cm["fp"] + cm["tn"] + cm["fn"]
        assert total == 500

    @pytest.mark.slow
    def test_many_random_panels(self):
        """Run metric_panel on 1000 random datasets."""
        for seed in range(1000):
            n = 100 + (seed % 900)
            y_true, y_score, y_pred = self._make_data(n, seed=seed)
            # Ensure at least one of each class
            if y_true.sum() == 0 or y_true.sum() == n:
                y_true[0] = 0
                y_true[1] = 1
            metrics, cm = metric_panel(y_true, y_score, y_pred, beta=2.0)
            for k, v in metrics.items():
                assert math.isfinite(v), f"seed={seed}, {k}={v}"
                if k not in ("lr_positive", "lr_negative", "mcc"):
                    assert 0 <= v <= 1, f"seed={seed}, {k}={v}"

    @pytest.mark.slow
    def test_imbalanced_datasets(self):
        """Test with extreme class imbalance (1:99, 5:95, 10:90)."""
        for minority_frac in [0.01, 0.05, 0.10]:
            for seed in range(100):
                rng = np.random.default_rng(seed)
                n = 1000
                y_true = np.zeros(n, dtype=int)
                n_pos = max(2, int(n * minority_frac))
                y_true[:n_pos] = 1
                rng.shuffle(y_true)
                y_score = rng.uniform(0, 1, size=n)
                y_pred = (y_score >= 0.5).astype(int)
                metrics, cm = metric_panel(y_true, y_score, y_pred, beta=2.0)
                for k, v in metrics.items():
                    assert math.isfinite(v), f"imb={minority_frac}, seed={seed}, {k}={v}"

    @pytest.mark.slow
    def test_varying_beta(self):
        """metric_panel with different beta values."""
        y_true, y_score, y_pred = self._make_data(500)
        for beta in [0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 10.0]:
            metrics, _ = metric_panel(y_true, y_score, y_pred, beta=beta)
            assert 0 <= metrics["f2_beta"] <= 1


# ────────────────────────────────────────────────────────
# canonical_metric_token
# ────────────────────────────────────────────────────────

class TestCanonicalMetricToken:
    @pytest.mark.parametrize("raw,expected", [
        ("ROC-AUC", "rocauc"),
        ("roc_auc", "rocauc"),
        ("PR AUC", "prauc"),
        ("F1-Score", "f1score"),
        ("accuracy", "accuracy"),
        ("Brier Score", "brierscore"),
        ("SENSITIVITY", "sensitivity"),
        ("", ""),
    ])
    def test_normalization(self, raw: str, expected: str):
        assert canonical_metric_token(raw) == expected
