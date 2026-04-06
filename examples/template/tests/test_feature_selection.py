"""Test Phase 4: Feature Selection — MLGG-F01, F03, F06, Z01 compliance."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
from importlib import import_module

feat_mod = import_module("04_feature_selection.scripts.select_features")


class TestForbiddenFeatures:
    """MLGG-F01/F02: Label and future-info features must be rejected."""

    def test_rejects_label_column(self, monkeypatch):
        monkeypatch.setattr(cfg, "LABEL_COL", "y")
        monkeypatch.setattr(cfg, "FORBIDDEN_FEATURES", [])
        with pytest.raises(ValueError, match="MLGG-F01"):
            feat_mod.check_forbidden_features(["age", "y", "bp"])

    def test_rejects_configured_forbidden(self, monkeypatch):
        monkeypatch.setattr(cfg, "LABEL_COL", "y")
        monkeypatch.setattr(cfg, "FORBIDDEN_FEATURES", ["future_lab"])
        with pytest.raises(ValueError, match="MLGG-F01"):
            feat_mod.check_forbidden_features(["age", "future_lab", "bp"])

    def test_passes_clean_features(self, monkeypatch):
        monkeypatch.setattr(cfg, "LABEL_COL", "y")
        monkeypatch.setattr(cfg, "FORBIDDEN_FEATURES", [])
        feat_mod.check_forbidden_features(["age", "bp", "glucose"])


class TestNearZeroVarianceFilter:

    def test_removes_constant_columns(self):
        X = np.ones((200, 3))
        X[:, 1] = np.arange(200)  # varied
        X[:, 2] = np.tile([0, 1], 100)  # varied
        names = ["const", "varied", "binary"]
        keep = feat_mod.filter_near_zero_variance(X, names)
        kept_names = [names[i] for i in keep]
        assert "const" not in kept_names
        assert "varied" in kept_names
        assert "binary" in kept_names

    def test_keeps_all_when_no_constant(self):
        rng = np.random.RandomState(42)
        X = rng.randn(200, 5)
        names = [f"f{i}" for i in range(5)]
        keep = feat_mod.filter_near_zero_variance(X, names)
        assert len(keep) == 5


class TestLoadFeatureGroups:

    def test_manual_override(self, monkeypatch):
        monkeypatch.setattr(cfg, "FEATURE_GROUPS", {"race": ["race_W", "race_B"]})
        monkeypatch.setattr(cfg, "PREPROCESS_RESULTS", Path("/nonexistent"))
        groups = feat_mod.load_feature_groups(["race_W", "race_B", "age"])
        assert groups == {"race": ["race_W", "race_B"]}

    def test_loads_from_encoding_groups_json(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cfg, "FEATURE_GROUPS", {})
        monkeypatch.setattr(cfg, "PREPROCESS_RESULTS", tmp_path)

        import json
        groups_data = {"race": ["race_W", "race_B", "race_A"]}
        (tmp_path / "encoding_groups.json").write_text(json.dumps(groups_data))

        groups = feat_mod.load_feature_groups(["race_W", "race_B", "race_A", "age"])
        assert "race" in groups
        assert len(groups["race"]) == 3

    def test_auto_detect_from_naming(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cfg, "FEATURE_GROUPS", {})
        monkeypatch.setattr(cfg, "PREPROCESS_RESULTS", tmp_path)
        # No encoding_groups.json exists

        features = ["race_W", "race_B", "race_A", "age", "bp"]
        groups = feat_mod.load_feature_groups(features)
        assert "race" in groups
        assert set(groups["race"]) == {"race_W", "race_B", "race_A"}


class TestRidgeBaseline:
    """Ridge baseline must use CV-tuned C and PR-AUC."""

    def test_returns_valid_prauc(self, split_data):
        prauc, best_C, scaler = feat_mod.ridge_baseline(
            split_data["X_train"], split_data["y_train"],
            split_data["X_valid"], split_data["y_valid"],
        )
        assert 0.0 <= prauc <= 1.0
        assert best_C > 0
        assert scaler is not None

    def test_ridge_cv_tunes_C(self, split_data):
        """Ridge should not use fixed C=1.0."""
        prauc, best_C, _ = feat_mod.ridge_baseline(
            split_data["X_train"], split_data["y_train"],
            split_data["X_valid"], split_data["y_valid"],
        )
        # best_C should be one of the configured values
        assert best_C in cfg.RIDGE_CV_CS


class TestStabilitySelection:
    """Elastic Net stability selection with group LASSO."""

    def test_returns_valid_structure(self, split_data, monkeypatch):
        monkeypatch.setattr(cfg, "STABILITY_N_SUBSAMPLES", 10)
        monkeypatch.setattr(cfg, "STABILITY_THRESHOLD", 0.3)
        monkeypatch.setattr(cfg, "STABILITY_SUBSAMPLE_RATIO", 0.50)
        monkeypatch.setattr(cfg, "STABILITY_L1_RATIOS", (0.5, 1.0))
        monkeypatch.setattr(cfg, "STABILITY_CS", (0.1, 1.0))
        monkeypatch.setattr(cfg, "STABILITY_CV_FOLDS", 3)
        monkeypatch.setattr(cfg, "STABILITY_MAX_ITER", 1000)

        stable_idx, stable_names, stability_df, ev = feat_mod.stability_selection(
            split_data["X_train"], split_data["y_train"],
            split_data["feature_names"], groups={},
        )
        assert len(stable_idx) == len(stable_names)
        assert "feature" in stability_df.columns
        assert "selection_probability" in stability_df.columns
        assert all(0 <= p <= 1 for p in stability_df["selection_probability"])

    def test_selection_on_train_only(self):
        """Function signature must not accept validation or test data."""
        import inspect
        sig = inspect.signature(feat_mod.stability_selection)
        params = list(sig.parameters.keys())
        assert "X_valid" not in params
        assert "X_test" not in params

    def test_group_lasso_selects_entire_group(self, monkeypatch):
        """If one dummy in a group is selected, all must be selected."""
        monkeypatch.setattr(cfg, "STABILITY_N_SUBSAMPLES", 20)
        monkeypatch.setattr(cfg, "STABILITY_THRESHOLD", 0.1)  # low to ensure selection
        monkeypatch.setattr(cfg, "STABILITY_SUBSAMPLE_RATIO", 0.50)
        monkeypatch.setattr(cfg, "STABILITY_L1_RATIOS", (1.0,))
        monkeypatch.setattr(cfg, "STABILITY_CS", (0.1,))
        monkeypatch.setattr(cfg, "STABILITY_CV_FOLDS", 3)
        monkeypatch.setattr(cfg, "STABILITY_MAX_ITER", 1000)

        rng = np.random.RandomState(42)
        n = 300
        # Create data where race_W is predictive but race_B/race_A are not
        X = np.column_stack([
            rng.randn(n),           # age (numeric)
            rng.binomial(1, 0.5, n),  # race_W (predictive)
            rng.binomial(1, 0.3, n),  # race_B
            rng.binomial(1, 0.2, n),  # race_A
        ])
        y = (X[:, 1] * 0.8 + rng.randn(n) * 0.3 > 0.3).astype(float)
        names = ["age", "race_W", "race_B", "race_A"]
        groups = {"race": ["race_W", "race_B", "race_A"]}

        stable_idx, stable_names, _, _ = feat_mod.stability_selection(
            X, y, names, groups
        )
        # If any race_ is selected, all should be
        race_selected = [n for n in stable_names if n.startswith("race_")]
        if len(race_selected) > 0:
            assert set(race_selected) == {"race_W", "race_B", "race_A"}

    def test_returns_false_selection_bound(self, split_data, monkeypatch):
        monkeypatch.setattr(cfg, "STABILITY_N_SUBSAMPLES", 10)
        monkeypatch.setattr(cfg, "STABILITY_THRESHOLD", 0.6)
        monkeypatch.setattr(cfg, "STABILITY_SUBSAMPLE_RATIO", 0.50)
        monkeypatch.setattr(cfg, "STABILITY_L1_RATIOS", (0.5, 1.0))
        monkeypatch.setattr(cfg, "STABILITY_CS", (0.1, 1.0))
        monkeypatch.setattr(cfg, "STABILITY_CV_FOLDS", 3)
        monkeypatch.setattr(cfg, "STABILITY_MAX_ITER", 1000)

        _, _, _, ev = feat_mod.stability_selection(
            split_data["X_train"], split_data["y_train"],
            split_data["feature_names"], groups={},
        )
        # E[V] should be a number (possibly inf if no features selected)
        assert isinstance(ev, float)
