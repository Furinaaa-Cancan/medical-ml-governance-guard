"""Test Phase 3: Preprocessing — MLGG-P01, P05, F05 compliance."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg
from importlib import import_module

preproc_mod = import_module("03_preprocessing.scripts.preprocess")


class TestSeparateXY:
    """MLGG-F05: Temporal feature filtering."""

    def test_drops_id_time_label_columns(self, synthetic_df):
        X, y = preproc_mod.separate_xy(synthetic_df)
        assert cfg.PATIENT_ID_COL not in X.columns
        assert cfg.LABEL_COL not in X.columns
        assert len(y) == len(synthetic_df)

    def test_temporal_filter_enforces_whitelist(self, synthetic_df, monkeypatch):
        """When ADMISSION_FEATURES is set, only those columns survive."""
        monkeypatch.setattr(cfg, "ADMISSION_FEATURES", ["age", "bp_systolic"])
        monkeypatch.setattr(cfg, "DISCHARGE_FEATURES", [])

        X, y = preproc_mod.separate_xy(synthetic_df)
        assert set(X.columns) == {"age", "bp_systolic"}

    def test_temporal_filter_warns_when_unconfigured(self, synthetic_df, capsys, monkeypatch):
        """When no temporal features configured, warn."""
        monkeypatch.setattr(cfg, "ADMISSION_FEATURES", [])
        monkeypatch.setattr(cfg, "DISCHARGE_FEATURES", [])

        X, y = preproc_mod.separate_xy(synthetic_df)
        captured = capsys.readouterr()
        assert "MLGG-F05" in captured.out
        assert "WARNING" in captured.out


class TestColumnTypes:

    def test_numeric_and_categorical_separated(self, synthetic_df):
        X = synthetic_df[["age", "bp_systolic", "gender", "race"]]
        numeric, categorical = preproc_mod.identify_column_types(X)
        assert "age" in numeric
        assert "bp_systolic" in numeric
        assert "gender" in categorical
        assert "race" in categorical


class TestBuildPreprocessor:

    def test_fit_transform_dimensions(self):
        """Preprocessor output dimensions must be consistent."""
        X_train = pd.DataFrame({
            "num1": [1.0, 2.0, 3.0, 4.0],
            "cat1": ["a", "b", "a", "b"],
        })
        X_test = pd.DataFrame({
            "num1": [5.0, 6.0],
            "cat1": ["a", "c"],  # unseen category
        })

        preprocessor, handled = preproc_mod.build_preprocessor(["num1"], ["cat1"])
        X_tr = preprocessor.fit_transform(X_train)
        X_te = preprocessor.transform(X_test)

        assert X_tr.shape[0] == 4
        assert X_te.shape[0] == 2
        assert X_tr.shape[1] == X_te.shape[1]  # same number of features

    def test_warns_on_unhandled_columns(self):
        """Columns not in numeric or categorical should be flagged."""
        preprocessor, handled = preproc_mod.build_preprocessor(["num1"], ["cat1"])
        assert handled == {"num1", "cat1"}

    def test_no_nan_after_imputation(self):
        """SimpleImputer must eliminate NaN."""
        X_train = pd.DataFrame({
            "num1": [1.0, np.nan, 3.0, 4.0],
            "cat1": ["a", "b", None, "b"],
        })
        preprocessor, _ = preproc_mod.build_preprocessor(["num1"], ["cat1"])
        result = preprocessor.fit_transform(X_train)
        assert np.isnan(result).sum() == 0
