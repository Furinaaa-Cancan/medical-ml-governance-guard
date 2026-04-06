"""Shared fixtures for all tests."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture
def project_root():
    return PROJECT_ROOT


@pytest.fixture
def synthetic_df():
    """A minimal synthetic medical dataset with known properties."""
    rng = np.random.RandomState(42)
    n = 500
    df = pd.DataFrame({
        "patient_id": np.repeat(np.arange(200), rng.choice([2, 3, 4], size=200))[:n],
        "event_time": pd.date_range("2020-01-01", periods=n, freq="D"),
        "age": rng.randint(20, 90, n),
        "gender": rng.choice(["Male", "Female"], n),
        "race": rng.choice(["White", "Black", "Asian", "Hispanic"], n),
        "bp_systolic": rng.normal(130, 20, n),
        "bp_diastolic": rng.normal(80, 12, n),
        "lab_glucose": rng.normal(100, 30, n),
        "y": rng.binomial(1, 0.15, n),
    })
    return df


@pytest.fixture
def split_data(synthetic_df):
    """Pre-split train/valid/test arrays."""
    rng = np.random.RandomState(42)
    n = len(synthetic_df)
    idx = rng.permutation(n)
    train_end = int(n * 0.6)
    valid_end = int(n * 0.8)

    X_cols = ["age", "bp_systolic", "bp_diastolic", "lab_glucose"]
    X = synthetic_df[X_cols].values.astype(float)
    y = synthetic_df["y"].values.astype(float)

    return {
        "X_train": X[idx[:train_end]], "y_train": y[idx[:train_end]],
        "X_valid": X[idx[train_end:valid_end]], "y_valid": y[idx[train_end:valid_end]],
        "X_test": X[idx[valid_end:]], "y_test": y[idx[valid_end:]],
        "feature_names": X_cols,
    }
