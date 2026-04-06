"""Test Phase 2: Data Splitting — MLGG-S01, S02 compliance."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
from importlib import import_module

split_mod = import_module("02_splitting.scripts.split")


class TestPatientOverlapCheck:
    """MLGG-S01: No patient overlap across splits."""

    def test_verify_passes_on_disjoint_splits(self, synthetic_df):
        patients = synthetic_df["patient_id"].unique()
        np.random.seed(42)
        np.random.shuffle(patients)
        n = len(patients)

        train = synthetic_df[synthetic_df["patient_id"].isin(patients[:int(n * 0.6)])]
        valid = synthetic_df[synthetic_df["patient_id"].isin(patients[int(n * 0.6):int(n * 0.8)])]
        test = synthetic_df[synthetic_df["patient_id"].isin(patients[int(n * 0.8):])]

        # Should not raise
        rates = split_mod.verify(train, valid, test)
        assert "train" in rates
        assert "valid" in rates
        assert "test" in rates

    def test_verify_raises_on_overlap(self, synthetic_df):
        """Overlapping patients must raise ValueError, not just assert."""
        train = synthetic_df.iloc[:300]
        valid = synthetic_df.iloc[200:400]  # overlap with train
        test = synthetic_df.iloc[400:]

        with pytest.raises(ValueError, match="CRITICAL.*overlap"):
            split_mod.verify(train, valid, test)


class TestTemporalSplit:
    """MLGG-S02: Temporal ordering."""

    def test_temporal_split_single_class_raises(self, synthetic_df):
        """If a temporal split yields single-class, must raise."""
        # Make all labels 0 for early patients
        df = synthetic_df.copy()
        df = df.sort_values("event_time")
        df["y"] = 0  # all negative
        df.iloc[-5:, df.columns.get_loc("y")] = 1  # only last 5 positive

        # With 60/20/20, train and valid will be all-0
        # _temporal_split should raise
        with pytest.raises(ValueError, match="only one class"):
            split_mod._temporal_split(df)


class TestPatientLevelRates:
    """Positive rates must be computed at patient level, not row level."""

    def test_rates_are_patient_level(self, synthetic_df):
        patients = synthetic_df["patient_id"].unique()
        n = len(patients)
        train = synthetic_df[synthetic_df["patient_id"].isin(patients[:int(n * 0.6)])]
        valid = synthetic_df[synthetic_df["patient_id"].isin(patients[int(n * 0.6):int(n * 0.8)])]
        test = synthetic_df[synthetic_df["patient_id"].isin(patients[int(n * 0.8):])]

        rates = split_mod.verify(train, valid, test)

        # Rate should be patient-level, not row-level
        expected_train_rate = train.groupby("patient_id")["y"].max().mean()
        assert abs(rates["train"] - expected_train_rate) < 1e-10


class TestRandomSplit:
    """_random_patient_split produces disjoint sets."""

    def test_no_patient_overlap(self, synthetic_df):
        train, valid, test = split_mod._random_patient_split(synthetic_df)
        train_ids = set(train["patient_id"])
        valid_ids = set(valid["patient_id"])
        test_ids = set(test["patient_id"])

        assert train_ids.isdisjoint(valid_ids)
        assert train_ids.isdisjoint(test_ids)
        assert valid_ids.isdisjoint(test_ids)

    def test_all_rows_preserved(self, synthetic_df):
        train, valid, test = split_mod._random_patient_split(synthetic_df)
        assert len(train) + len(valid) + len(test) == len(synthetic_df)
