"""Tests for encode_categorical_features in train_select_evaluate.py."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from train_select_evaluate import encode_categorical_features, detect_categorical_features


def _make_data():
    """Train/valid/test with binary, categorical, and numeric features."""
    rng = np.random.default_rng(42)
    n = 50
    train = pd.DataFrame({
        "gender": rng.choice([1, 2], n),
        "race": rng.choice([1, 2, 3, 4, 5], n),
        "age": rng.uniform(20, 80, n),  # high cardinality → numeric
        "bmi": rng.uniform(18, 40, n),  # high cardinality → numeric
    })
    valid = pd.DataFrame({
        "gender": rng.choice([1, 2], 20),
        "race": rng.choice([1, 3, 5, 2], 20),
        "age": rng.uniform(20, 80, 20),
        "bmi": rng.uniform(18, 40, 20),
    })
    test = pd.DataFrame({
        "gender": rng.choice([1, 2], 20),
        "race": np.array([4, 1, 6, 3] + list(rng.choice([1, 2, 3, 4, 5], 16))),  # race=6 is OOD
        "age": rng.uniform(20, 80, 20),
        "bmi": rng.uniform(18, 40, 20),
    })
    return train, valid, test


class TestEncodeCategoricalFeatures:
    def test_binary_encoding(self):
        """Binary columns (cardinality=2) should become 0/1."""
        train, valid, test = _make_data()
        cat_report = detect_categorical_features(train, list(train.columns))

        train_enc, valid_enc, test_enc, features = encode_categorical_features(
            train.copy(), valid.copy(), test.copy(), cat_report,
        )
        # gender was binary (1,2) → should be 0/1 in-place
        assert "gender" in features
        assert set(train_enc["gender"].unique()) == {0.0, 1.0}

    def test_categorical_onehot(self):
        """Categorical columns (cardinality 3-15) should be OneHot encoded."""
        train, valid, test = _make_data()
        cat_report = detect_categorical_features(train, list(train.columns))

        train_enc, valid_enc, test_enc, features = encode_categorical_features(
            train.copy(), valid.copy(), test.copy(), cat_report,
        )
        # race had 5 unique values → should be OneHot
        assert "race" not in features  # original column dropped
        race_cols = [c for c in features if c.startswith("race_")]
        assert len(race_cols) == 5  # 5 dummies for 5 train-observed values

    def test_numeric_untouched(self):
        """High-cardinality numeric columns should not be encoded."""
        train, valid, test = _make_data()
        cat_report = detect_categorical_features(train, list(train.columns))

        train_enc, _, _, features = encode_categorical_features(
            train.copy(), valid.copy(), test.copy(), cat_report,
        )
        assert "age" in features
        assert "bmi" in features

    def test_ood_binary_safe(self):
        """OOD values in binary columns should become 0.0, not NaN."""
        train = pd.DataFrame({"x": [0, 1, 0, 1]})
        valid = pd.DataFrame({"x": [0, 1]})
        test = pd.DataFrame({"x": [0, 1, 99]})  # 99 is OOD
        cat_report = detect_categorical_features(train, ["x"])

        _, _, test_enc, _ = encode_categorical_features(
            train.copy(), valid.copy(), test.copy(), cat_report,
        )
        assert not test_enc["x"].isna().any()
        assert test_enc["x"].iloc[2] == 0.5  # OOD → 0.5 (neutral sentinel, not 0.0)
        # OOD indicator column should be created
        assert "x_ood" in test_enc.columns
        assert test_enc["x_ood"].iloc[2] == 1.0  # OOD flagged
        assert test_enc["x_ood"].iloc[0] == 0.0  # non-OOD

    def test_ood_categorical_safe(self):
        """OOD values in OneHot columns should produce all-zero rows, not NaN."""
        train = pd.DataFrame({"cat": [1, 2, 3, 1, 2, 3]})
        valid = pd.DataFrame({"cat": [1, 2]})
        test = pd.DataFrame({"cat": [1, 99]})  # 99 is OOD
        cat_report = detect_categorical_features(train, ["cat"])

        _, _, test_enc, features = encode_categorical_features(
            train.copy(), valid.copy(), test.copy(), cat_report,
        )
        assert not test_enc.isna().any().any()
        # Row with OOD value should be all zeros in cat_ columns
        cat_cols = [c for c in features if c.startswith("cat_")]
        assert all(test_enc.iloc[1][c] == 0.0 for c in cat_cols)
        # Row with known value should have exactly one 1.0
        assert sum(test_enc.iloc[0][c] for c in cat_cols) == 1.0

    def test_empty_report_noop(self):
        """If no categoricals detected, data should pass through unchanged."""
        train = pd.DataFrame({"x": np.random.randn(50)})
        valid = pd.DataFrame({"x": np.random.randn(20)})
        test = pd.DataFrame({"x": np.random.randn(10)})
        cat_report = {"categorical_count": 0, "categorical_features": []}

        train_out, valid_out, test_out, features = encode_categorical_features(
            train.copy(), valid.copy(), test.copy(), cat_report,
        )
        pd.testing.assert_frame_equal(train_out, train)
        assert features == ["x"]

    def test_feature_count_changes(self):
        """Feature count should increase after OneHot encoding."""
        train, valid, test = _make_data()
        original_cols = len(train.columns)
        cat_report = detect_categorical_features(train, list(train.columns))

        _, _, _, features = encode_categorical_features(
            train.copy(), valid.copy(), test.copy(), cat_report,
        )
        # race (5 cats) replaces 1 col with 5 → net +4
        assert len(features) > original_cols

    def test_all_splits_same_columns(self):
        """Train, valid, and test must have identical columns after encoding."""
        train, valid, test = _make_data()
        cat_report = detect_categorical_features(train, list(train.columns))

        train_enc, valid_enc, test_enc, _ = encode_categorical_features(
            train.copy(), valid.copy(), test.copy(), cat_report,
        )
        assert list(train_enc.columns) == list(valid_enc.columns) == list(test_enc.columns)
