"""Test Phase 8: Fairness — MLGG-Q01, Q02 compliance."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
from importlib import import_module

fair_mod = import_module("08_fairness.scripts.fairness")


class TestSubgroupMetrics:

    def test_basic_metrics_returned(self):
        rng = np.random.RandomState(42)
        y_true = rng.binomial(1, 0.3, 300)
        y_prob = rng.uniform(0, 1, 300)
        y_pred = (y_prob > 0.5).astype(int)

        result = fair_mod.subgroup_metrics(y_true, y_prob, y_pred, "TestGroup")
        assert result["group"] == "TestGroup"
        assert result["n"] == 300
        assert "AUROC" in result
        assert "Sensitivity" in result
        assert "FPR" in result
        assert result["reliability"] == "OK"

    def test_bootstrap_ci_present(self):
        """MLGG-Q02: Subgroup metrics must include bootstrap CI."""
        rng = np.random.RandomState(42)
        y_true = rng.binomial(1, 0.3, 300)
        y_prob = rng.uniform(0, 1, 300)
        y_pred = (y_prob > 0.5).astype(int)

        result = fair_mod.subgroup_metrics(y_true, y_prob, y_pred, "TestGroup")
        assert "AUROC_lower" in result, "Missing AUROC CI lower bound"
        assert "AUROC_upper" in result, "Missing AUROC CI upper bound"
        assert result["AUROC_lower"] <= result["AUROC"]
        assert result["AUROC"] <= result["AUROC_upper"]

    def test_small_subgroup_flagged(self):
        """Subgroups with n < 200 must be flagged as unreliable."""
        rng = np.random.RandomState(42)
        y_true = rng.binomial(1, 0.3, 50)
        y_prob = rng.uniform(0, 1, 50)
        y_pred = (y_prob > 0.5).astype(int)

        result = fair_mod.subgroup_metrics(y_true, y_prob, y_pred, "SmallGroup")
        assert "UNRELIABLE" in result.get("reliability", "")

    def test_very_small_subgroup_skipped(self):
        """Subgroups with n < 20 should be skipped."""
        y_true = np.array([0, 1, 0, 1, 0])
        y_prob = np.array([0.1, 0.9, 0.2, 0.8, 0.3])
        y_pred = np.array([0, 1, 0, 1, 0])

        result = fair_mod.subgroup_metrics(y_true, y_prob, y_pred, "TinyGroup")
        assert "too_few_samples" in str(result.get("note", ""))

    def test_single_class_subgroup(self):
        """Subgroup with only one class should skip AUROC but not crash."""
        y_true = np.zeros(50)
        y_prob = np.random.uniform(0, 0.5, 50)
        y_pred = np.zeros(50, dtype=int)

        result = fair_mod.subgroup_metrics(y_true, y_prob, y_pred, "AllNeg")
        assert "AUROC" not in result  # can't compute with one class
        assert result["n"] == 50
