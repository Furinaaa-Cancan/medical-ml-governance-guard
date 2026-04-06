"""Test Phase 5: Model Training — MLGG-M01, M02, M03 compliance."""

import sys
from pathlib import Path

import numpy as np
import pytest
from sklearn.metrics import roc_curve

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
from importlib import import_module

model_mod = import_module("05_modeling.scripts.train_models")


class TestDefineModels:

    def test_minimum_two_families(self):
        """At least LR + RF must always be available."""
        models = model_mod.define_models()
        assert len(models) >= 2
        assert "LR" in models
        assert "RF" in models

    def test_all_models_have_random_state(self):
        """MLGG-R01: Every model must have random_state set."""
        models = model_mod.define_models()
        for name, model in models.items():
            params = model.get_params()
            assert "random_state" in params, f"{name} missing random_state"
            assert params["random_state"] is not None, f"{name} has random_state=None"


class TestSelectThreshold:

    def test_youden_j_returns_valid_threshold(self, split_data):
        """MLGG-M02: Threshold must come from validation set, via Youden's J."""
        from sklearn.linear_model import LogisticRegression
        lr = LogisticRegression(random_state=42, max_iter=5000)
        lr.fit(split_data["X_train"], split_data["y_train"])
        y_prob = lr.predict_proba(split_data["X_valid"])[:, 1]

        threshold = model_mod.select_threshold(split_data["y_valid"], y_prob)
        assert 0.0 < threshold < 1.0

    def test_threshold_not_from_test(self):
        """Structural check: select_threshold takes y_valid, not y_test."""
        import inspect
        sig = inspect.signature(model_mod.select_threshold)
        params = list(sig.parameters.keys())
        assert "y_valid" in params
        assert "y_test" not in params


class TestTrainAndEvaluate:

    def test_returns_all_models(self, split_data):
        models = model_mod.define_models()
        results = model_mod.train_and_evaluate(
            models,
            split_data["X_train"], split_data["y_train"],
            split_data["X_valid"], split_data["y_valid"],
        )
        assert len(results) == len(models)
        assert "auc_valid" in results.columns
        assert "threshold" in results.columns

    def test_no_test_data_in_training(self, split_data):
        """MLGG-M01: train_and_evaluate signature must not accept test data."""
        import inspect
        sig = inspect.signature(model_mod.train_and_evaluate)
        params = list(sig.parameters.keys())
        assert "X_test" not in params
        assert "y_test" not in params
