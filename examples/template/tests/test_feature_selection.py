"""Test Phase 4: Feature Selection — MLGG-F03, F06, Z01 compliance."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
from importlib import import_module

feat_mod = import_module("04_feature_selection.scripts.select_features")


class TestNearZeroVarianceFilter:

    def test_removes_constant_columns(self):
        """Columns with >99% same value should be removed."""
        X = np.array([
            [1, 0, 5],
            [1, 0, 6],
            [1, 0, 7],
            [1, 1, 8],  # col 0: 75% same, col 1: 75% same, col 2: all different
        ] * 100, dtype=float)
        # With 400 rows, col0 is 75% constant — should keep
        # Make a truly constant column
        X[:, 0] = 1.0  # 100% constant
        names = ["const", "almost_const", "varied"]

        keep = feat_mod.filter_near_zero_variance(X, names, threshold=0.99)
        kept_names = [names[i] for i in keep]
        assert "const" not in kept_names
        assert "varied" in kept_names

    def test_keeps_all_when_no_constant(self):
        rng = np.random.RandomState(42)
        X = rng.randn(200, 5)
        names = [f"f{i}" for i in range(5)]
        keep = feat_mod.filter_near_zero_variance(X, names)
        assert len(keep) == 5


class TestRidgeBaseline:

    def test_returns_valid_auc(self, split_data):
        auc, scaler = feat_mod.ridge_baseline(
            split_data["X_train"], split_data["y_train"],
            split_data["X_valid"], split_data["y_valid"],
        )
        assert 0.0 <= auc <= 1.0
        assert scaler is not None

    def test_ridge_uses_scaler(self, split_data):
        """Ridge baseline must scale data internally."""
        _, scaler = feat_mod.ridge_baseline(
            split_data["X_train"], split_data["y_train"],
            split_data["X_valid"], split_data["y_valid"],
        )
        # Scaler should have been fitted
        assert hasattr(scaler, "mean_")
        assert len(scaler.mean_) == split_data["X_train"].shape[1]


class TestStabilitySelection:

    def test_returns_valid_structure(self, split_data):
        stable_idx, stable_names, stability_df = feat_mod.stability_selection(
            split_data["X_train"], split_data["y_train"],
            split_data["feature_names"],
            n_subsamples=10, threshold=0.3,  # low for speed
        )
        assert len(stable_idx) == len(stable_names)
        assert "feature" in stability_df.columns
        assert "selection_probability" in stability_df.columns
        assert all(0 <= p <= 1 for p in stability_df["selection_probability"])

    def test_selection_on_train_only(self, split_data):
        """Stability selection must not see validation or test data."""
        # This is a structural test — the function signature only takes X_train
        import inspect
        sig = inspect.signature(feat_mod.stability_selection)
        params = list(sig.parameters.keys())
        assert "X_valid" not in params
        assert "X_test" not in params
