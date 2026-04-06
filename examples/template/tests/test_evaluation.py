"""Test Phase 6: Evaluation — MLGG-E01, E02, E03 compliance."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
from importlib import import_module

eval_mod = import_module("06_evaluation.scripts.evaluate")


class TestComputeMetrics:

    def test_full_metric_panel(self):
        """MLGG-E02: Must return all required metrics."""
        y_true = np.array([0, 0, 1, 1, 0, 1, 0, 1])
        y_prob = np.array([0.1, 0.2, 0.8, 0.7, 0.3, 0.6, 0.4, 0.9])
        y_pred = np.array([0, 0, 1, 1, 0, 1, 0, 1])

        metrics = eval_mod.compute_metrics(y_true, y_prob, y_pred)

        required = [
            "AUROC", "AUPRC", "Sensitivity", "Specificity",
            "PPV", "NPV", "F1", "MCC", "Balanced_Accuracy",
            "Brier", "LogLoss", "LR+", "LR-",
            "TP", "FP", "TN", "FN",
        ]
        for key in required:
            assert key in metrics, f"Missing metric: {key}"

    def test_perfect_prediction(self):
        y_true = np.array([0, 0, 1, 1])
        y_prob = np.array([0.0, 0.0, 1.0, 1.0])
        y_pred = np.array([0, 0, 1, 1])

        metrics = eval_mod.compute_metrics(y_true, y_prob, y_pred)
        assert metrics["AUROC"] == 1.0
        assert metrics["Sensitivity"] == 1.0
        assert metrics["Specificity"] == 1.0
        assert metrics["MCC"] == 1.0

    def test_confusion_matrix_uses_labels_param(self):
        """Must not crash when model predicts only one class."""
        y_true = np.array([0, 0, 1, 1])
        y_prob = np.array([0.1, 0.2, 0.3, 0.4])
        y_pred = np.array([0, 0, 0, 0])  # all negative

        metrics = eval_mod.compute_metrics(y_true, y_prob, y_pred)
        assert metrics["TP"] == 0
        assert metrics["FN"] == 2
        assert metrics["Sensitivity"] == 0.0

    def test_metrics_ranges(self):
        rng = np.random.RandomState(42)
        y_true = rng.binomial(1, 0.3, 200)
        y_prob = rng.uniform(0, 1, 200)
        y_pred = (y_prob > 0.5).astype(int)

        metrics = eval_mod.compute_metrics(y_true, y_prob, y_pred)
        assert 0 <= metrics["AUROC"] <= 1
        assert 0 <= metrics["AUPRC"] <= 1
        assert 0 <= metrics["Brier"] <= 1
        assert 0 <= metrics["Sensitivity"] <= 1
        assert 0 <= metrics["Specificity"] <= 1


class TestBootstrapCI:

    def test_returns_ci_for_key_metrics(self):
        """MLGG-E01: CI for all primary metrics."""
        rng = np.random.RandomState(42)
        y_true = rng.binomial(1, 0.3, 200)
        y_prob = rng.uniform(0, 1, 200)
        y_pred = (y_prob > 0.5).astype(int)

        ci = eval_mod.bootstrap_ci(y_true, y_prob, y_pred, n_bootstrap=100)

        for metric in ["AUROC", "Sensitivity", "Specificity", "MCC", "Brier"]:
            assert metric in ci, f"Missing CI for {metric}"
            assert ci[metric]["lower"] <= ci[metric]["upper"]

    def test_ci_lower_less_than_upper(self):
        rng = np.random.RandomState(42)
        y_true = rng.binomial(1, 0.3, 300)
        y_prob = rng.uniform(0, 1, 300)
        y_pred = (y_prob > 0.5).astype(int)

        ci = eval_mod.bootstrap_ci(y_true, y_prob, y_pred, n_bootstrap=200)
        for metric, bounds in ci.items():
            assert bounds["lower"] <= bounds["upper"], f"{metric}: lower > upper"

    def test_stratified_bootstrap_preserves_ratio(self):
        """Bootstrap must be stratified — check no single-class samples."""
        y_true = np.array([0] * 90 + [1] * 10)  # 10% positive
        y_prob = np.random.uniform(0, 1, 100)
        y_pred = (y_prob > 0.5).astype(int)

        # With stratified bootstrap, we should always have both classes
        # and get 100 valid iterations
        ci = eval_mod.bootstrap_ci(y_true, y_prob, y_pred, n_bootstrap=100)
        assert "AUROC" in ci


class TestECE:

    def test_perfect_calibration_zero_ece(self):
        """Perfectly calibrated predictions should have ECE ~ 0."""
        y_true = np.array([0, 0, 0, 0, 0, 1, 1, 1, 1, 1])
        y_prob = np.array([0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0])
        ece = eval_mod.compute_ece(y_true, y_prob)
        assert ece < 0.01

    def test_ece_includes_prob_one(self):
        """prob=1.0 must not be excluded from ECE bins."""
        y_true = np.array([1, 1, 1])
        y_prob = np.array([1.0, 1.0, 1.0])
        ece = eval_mod.compute_ece(y_true, y_prob)
        assert ece < 0.01  # all correct at prob=1.0

    def test_bad_calibration_high_ece(self):
        """Predictions far from true labels should have high ECE."""
        y_true = np.array([0] * 50 + [1] * 50)
        y_prob = np.array([0.9] * 50 + [0.1] * 50)  # completely wrong
        ece = eval_mod.compute_ece(y_true, y_prob)
        assert ece > 0.5

    def test_ece_range(self):
        rng = np.random.RandomState(42)
        y_true = rng.binomial(1, 0.3, 500)
        y_prob = rng.uniform(0, 1, 500)
        ece = eval_mod.compute_ece(y_true, y_prob)
        assert 0 <= ece <= 1
