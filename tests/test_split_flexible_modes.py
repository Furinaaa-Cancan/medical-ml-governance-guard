"""Tests for flexible split modes: two-way (no valid) and CV-only (no test)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _make_data(tmp_path, n=500, prevalence=0.2, seed=42):
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({
        "pid": [f"p{i}" for i in range(n)],
        "feat_0": rng.standard_normal(n),
        "feat_1": rng.standard_normal(n),
        "y": rng.choice([0, 1], n, p=[1 - prevalence, prevalence]),
    })
    path = tmp_path / "data.csv"
    df.to_csv(path, index=False)
    return path


class TestTwoWaySplit:
    """valid_ratio=0: train + test only, no validation split."""

    def test_two_way_creates_train_test_only(self, tmp_path):
        data = _make_data(tmp_path)
        out = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "tools/split_data.py"),
             "--input", str(data), "--output-dir", str(out),
             "--patient-id-col", "pid", "--target-col", "y",
             "--strategy", "stratified_grouped",
             "--train-ratio", "0.8", "--valid-ratio", "0.0", "--test-ratio", "0.2"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr[-300:]
        assert (out / "train.csv").exists()
        assert (out / "test.csv").exists()
        assert not (out / "valid.csv").exists()

        train = pd.read_csv(out / "train.csv")
        test = pd.read_csv(out / "test.csv")
        assert len(train) + len(test) == 500
        assert len(train) > len(test)

    def test_two_way_patient_disjoint(self, tmp_path):
        data = _make_data(tmp_path)
        out = tmp_path / "out"
        subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "tools/split_data.py"),
             "--input", str(data), "--output-dir", str(out),
             "--patient-id-col", "pid", "--target-col", "y",
             "--strategy", "stratified_grouped",
             "--train-ratio", "0.8", "--valid-ratio", "0.0", "--test-ratio", "0.2"],
            capture_output=True, text=True, timeout=30,
        )
        train = pd.read_csv(out / "train.csv")
        test = pd.read_csv(out / "test.csv")
        overlap = set(train["pid"]) & set(test["pid"])
        assert len(overlap) == 0, f"Patient overlap: {overlap}"

    def test_two_way_report_json(self, tmp_path):
        data = _make_data(tmp_path)
        out = tmp_path / "out"
        report_path = tmp_path / "report.json"
        subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "tools/split_data.py"),
             "--input", str(data), "--output-dir", str(out),
             "--patient-id-col", "pid", "--target-col", "y",
             "--strategy", "stratified_grouped",
             "--train-ratio", "0.8", "--valid-ratio", "0.0", "--test-ratio", "0.2",
             "--report", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        assert report_path.exists()
        report = json.loads(report_path.read_text())
        assert report["split_mode"] == "two_way"
        assert report["splits"]["valid"] is None
        assert report["splits"]["test"] is not None


class TestCVOnlySplit:
    """valid_ratio=0, test_ratio=0: all data for training."""

    def test_cv_only_creates_train_only(self, tmp_path):
        data = _make_data(tmp_path)
        out = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "tools/split_data.py"),
             "--input", str(data), "--output-dir", str(out),
             "--patient-id-col", "pid", "--target-col", "y",
             "--strategy", "stratified_grouped",
             "--train-ratio", "1.0", "--valid-ratio", "0.0", "--test-ratio", "0.0"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stderr[-300:]
        assert (out / "train.csv").exists()
        assert not (out / "valid.csv").exists()
        assert not (out / "test.csv").exists()

        train = pd.read_csv(out / "train.csv")
        assert len(train) == 500

    def test_cv_only_report_json(self, tmp_path):
        data = _make_data(tmp_path)
        out = tmp_path / "out"
        report_path = tmp_path / "report.json"
        subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "tools/split_data.py"),
             "--input", str(data), "--output-dir", str(out),
             "--patient-id-col", "pid", "--target-col", "y",
             "--strategy", "stratified_grouped",
             "--train-ratio", "1.0", "--valid-ratio", "0.0", "--test-ratio", "0.0",
             "--report", str(report_path)],
            capture_output=True, text=True, timeout=30,
        )
        report = json.loads(report_path.read_text())
        assert report["split_mode"] == "cv_only"
        assert report["splits"]["valid"] is None
        assert report["splits"]["test"] is None


class TestThreeWaySplitUnchanged:
    """Regression: standard three-way split still works."""

    def test_three_way(self, tmp_path):
        data = _make_data(tmp_path)
        out = tmp_path / "out"
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "tools/split_data.py"),
             "--input", str(data), "--output-dir", str(out),
             "--patient-id-col", "pid", "--target-col", "y",
             "--strategy", "stratified_grouped",
             "--train-ratio", "0.6", "--valid-ratio", "0.2", "--test-ratio", "0.2"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert (out / "train.csv").exists()
        assert (out / "valid.csv").exists()
        assert (out / "test.csv").exists()

        train = pd.read_csv(out / "train.csv")
        valid = pd.read_csv(out / "valid.csv")
        test = pd.read_csv(out / "test.csv")
        assert len(train) + len(valid) + len(test) == 500


class TestInvalidRatios:
    """validate_ratios should reject bad inputs."""

    def test_reject_too_small_valid(self, tmp_path):
        """valid_ratio between 0 and 0.05 should be rejected."""
        data = _make_data(tmp_path)
        result = subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "tools/split_data.py"),
             "--input", str(data), "--output-dir", str(tmp_path / "x"),
             "--patient-id-col", "pid", "--target-col", "y",
             "--strategy", "stratified_grouped",
             "--train-ratio", "0.8", "--valid-ratio", "0.03", "--test-ratio", "0.17"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0
        assert "0.05" in result.stderr or "must be" in result.stderr
