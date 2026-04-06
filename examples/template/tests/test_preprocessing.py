"""Test Phase 3: Preprocessing — MLGG-P01, P04, P05, P06 compliance."""

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
        monkeypatch.setattr(cfg, "ADMISSION_FEATURES", ["age", "bp_systolic"])
        monkeypatch.setattr(cfg, "DISCHARGE_FEATURES", [])
        X, y = preproc_mod.separate_xy(synthetic_df)
        assert set(X.columns) == {"age", "bp_systolic"}

    def test_temporal_filter_warns_when_unconfigured(self, synthetic_df, capsys, monkeypatch):
        monkeypatch.setattr(cfg, "ADMISSION_FEATURES", [])
        monkeypatch.setattr(cfg, "DISCHARGE_FEATURES", [])
        X, y = preproc_mod.separate_xy(synthetic_df)
        captured = capsys.readouterr()
        assert "MLGG-F05" in captured.out
        assert "WARNING" in captured.out


class TestClassifyColumns:
    """MLGG-P05: Cardinality + dtype column type detection."""

    def test_binary_detection(self):
        X = pd.DataFrame({"gender": ["M", "F", "M", "F"]})
        col_types = preproc_mod.classify_columns(X)
        assert "gender" in col_types["binary"]

    def test_categorical_detection_string(self):
        """String columns with low cardinality → categorical (OneHot)."""
        X = pd.DataFrame({"race": ["White", "Black", "Asian", "Hispanic"] * 10})
        col_types = preproc_mod.classify_columns(X)
        assert "race" in col_types["categorical"]

    def test_numeric_low_cardinality_stays_numeric(self):
        """Integer count variables must NOT be OneHot encoded.

        num_medications=0..11 has inherent order. OneHot destroys
        "5 > 3" information and wastes degrees of freedom.
        """
        rng = np.random.RandomState(42)
        X = pd.DataFrame({"num_meds": rng.poisson(5, 100)})
        col_types = preproc_mod.classify_columns(X)
        assert "num_meds" in col_types["numeric"]
        assert "num_meds" not in col_types["categorical"]

    def test_numeric_high_cardinality(self):
        rng = np.random.RandomState(42)
        X = pd.DataFrame({"bp": rng.normal(130, 20, 100)})
        col_types = preproc_mod.classify_columns(X)
        assert "bp" in col_types["numeric"]

    def test_constant_detection(self):
        X = pd.DataFrame({"c": [1] * 50})
        col_types = preproc_mod.classify_columns(X)
        assert "c" in col_types["constant"]

    def test_ordinal_from_config(self, monkeypatch):
        monkeypatch.setattr(cfg, "ORDINAL_COLUMNS", {"severity": ["low", "mid", "high"]})
        X = pd.DataFrame({"severity": ["low", "mid", "high", "low"] * 10})
        col_types = preproc_mod.classify_columns(X)
        assert "severity" in col_types["ordinal"]
        assert "severity" not in col_types["categorical"]

    def test_string_low_cardinality_is_categorical(self):
        """String columns with 3-15 unique values → categorical."""
        X = pd.DataFrame({"drug": ["aspirin", "metformin", "insulin"] * 20})
        col_types = preproc_mod.classify_columns(X)
        assert "drug" in col_types["categorical"]
        assert "drug" not in col_types["numeric"]

    def test_integer_coded_nominal_needs_explicit_config(self):
        """Integer codes (admission_type_id=1..5) go numeric by default.

        If they're actually nominal, user must cast to string or
        configure ORDINAL_COLUMNS. This is by design — safe default.
        """
        X = pd.DataFrame({"admission_type_id": [1, 2, 3, 4, 5] * 20})
        col_types = preproc_mod.classify_columns(X)
        assert "admission_type_id" in col_types["numeric"]


class TestMissingnessAnalysis:
    """MLGG-P06: Tiered missingness strategy."""

    def test_tier_assignment(self, monkeypatch):
        monkeypatch.setattr(cfg, "MISSING_TIER1_UPPER", 0.05)
        monkeypatch.setattr(cfg, "MISSING_TIER2_UPPER", 0.40)
        monkeypatch.setattr(cfg, "MISSING_TIER3_UPPER", 0.80)
        monkeypatch.setattr(cfg, "COLS_DROP_VALUE_KEEP_INDICATOR", [])
        monkeypatch.setattr(cfg, "COLS_IMPUTE_WITH_INDICATOR", [])
        monkeypatch.setattr(cfg, "COLS_SIMPLE_IMPUTE", [])

        n = 100
        X = pd.DataFrame({
            "low_miss": np.where(np.arange(n) < 2, np.nan, 1.0),       # 2% → tier1
            "med_miss": np.where(np.arange(n) < 20, np.nan, 1.0),      # 20% → tier2
            "high_miss": np.where(np.arange(n) < 60, np.nan, 1.0),     # 60% → tier3
            "extreme_miss": np.where(np.arange(n) < 90, np.nan, 1.0),  # 90% → tier4
        })
        col_types = {"numeric": list(X.columns), "binary": [], "categorical": [],
                     "ordinal": [], "constant": [], "high_cardinality": []}

        _, tiers = preproc_mod.analyze_missingness(X, col_types)
        assert "low_miss" in tiers["tier1"]
        assert "med_miss" in tiers["tier2"]
        assert "high_miss" in tiers["tier3"]
        assert "extreme_miss" in tiers["tier4"]

    def test_manual_override_takes_priority(self, monkeypatch):
        monkeypatch.setattr(cfg, "COLS_DROP_VALUE_KEEP_INDICATOR", ["forced_t4"])
        monkeypatch.setattr(cfg, "COLS_IMPUTE_WITH_INDICATOR", [])
        monkeypatch.setattr(cfg, "COLS_SIMPLE_IMPUTE", [])
        monkeypatch.setattr(cfg, "MISSING_TIER1_UPPER", 0.05)
        monkeypatch.setattr(cfg, "MISSING_TIER2_UPPER", 0.40)
        monkeypatch.setattr(cfg, "MISSING_TIER3_UPPER", 0.80)

        X = pd.DataFrame({"forced_t4": [1.0] * 100})  # 0% missing but forced tier4
        col_types = {"numeric": ["forced_t4"], "binary": [], "categorical": [],
                     "ordinal": [], "constant": [], "high_cardinality": []}

        _, tiers = preproc_mod.analyze_missingness(X, col_types)
        assert "forced_t4" in tiers["tier4"]


class TestEncodeBinary:

    def test_maps_to_zero_one(self):
        X_tr = pd.DataFrame({"g": ["M", "F", "M", "F"]})
        X_va = pd.DataFrame({"g": ["F", "M"]})
        X_te = pd.DataFrame({"g": ["M", "F"]})
        mappings = preproc_mod.encode_binary(X_tr, X_va, X_te, ["g"])
        assert set(X_tr["g"].unique()) == {0, 1}
        assert set(X_va["g"].unique()) == {0, 1}

    def test_ood_maps_to_zero(self):
        X_tr = pd.DataFrame({"g": ["M", "F", "M", "F"]})
        X_va = pd.DataFrame({"g": ["M"]})
        X_te = pd.DataFrame({"g": [np.nan]})
        preproc_mod.encode_binary(X_tr, X_va, X_te, ["g"])
        assert X_te["g"].iloc[0] == 0.0


class TestEncodeCategorical:

    def test_onehot_creates_correct_dummies(self):
        X_tr = pd.DataFrame({"race": ["W", "B", "A"], "num": [1, 2, 3]})
        X_va = pd.DataFrame({"race": ["W", "B"], "num": [4, 5]})
        X_te = pd.DataFrame({"race": ["A", "W"], "num": [6, 7]})

        X_tr, X_va, X_te, groups = preproc_mod.encode_categorical(
            X_tr, X_va, X_te, ["race"]
        )
        assert "race" in groups
        assert len(groups["race"]) == 3
        assert "race_W" in X_tr.columns
        assert "race" not in X_tr.columns
        assert X_tr.shape[1] == X_va.shape[1] == X_te.shape[1]

    def test_ood_category_gets_all_zeros(self):
        X_tr = pd.DataFrame({"c": ["a", "b"]})
        X_va = pd.DataFrame({"c": ["a"]})
        X_te = pd.DataFrame({"c": ["UNSEEN"]})

        X_tr, X_va, X_te, groups = preproc_mod.encode_categorical(
            X_tr, X_va, X_te, ["c"]
        )
        # Unseen category → all dummy columns are 0
        for col in groups["c"]:
            assert X_te[col].iloc[0] == 0.0

    def test_encoding_groups_structure(self):
        X_tr = pd.DataFrame({"r": ["W", "B", "A", "H"]})
        X_va = pd.DataFrame({"r": ["W"]})
        X_te = pd.DataFrame({"r": ["B"]})

        _, _, _, groups = preproc_mod.encode_categorical(X_tr, X_va, X_te, ["r"])
        assert isinstance(groups, dict)
        assert "r" in groups
        assert all(col.startswith("r_") for col in groups["r"])


class TestImputeTiered:
    """MLGG-P01/P04: All imputation statistics from training set only."""

    def test_tier4_drops_value_keeps_indicator(self):
        X_tr = pd.DataFrame({"a": [np.nan, np.nan, 3.0, np.nan]})
        X_va = pd.DataFrame({"a": [1.0, np.nan]})
        X_te = pd.DataFrame({"a": [np.nan, 2.0]})
        col_types = {"numeric": ["a"], "binary": [], "ordinal": [],
                     "categorical": [], "constant": [], "high_cardinality": []}
        tiers = {"tier1": [], "tier2": [], "tier3": [], "tier4": ["a"]}

        X_tr, X_va, X_te, indicators, _ = preproc_mod.impute_tiered(
            X_tr, X_va, X_te, col_types, tiers
        )
        assert "a" not in X_tr.columns
        assert "a_missing" in X_tr.columns
        assert X_tr["a_missing"].tolist() == [1.0, 1.0, 0.0, 1.0]

    def test_tier2_imputes_and_adds_indicator(self):
        X_tr = pd.DataFrame({"b": [1.0, 2.0, np.nan, 4.0]})
        X_va = pd.DataFrame({"b": [np.nan, 3.0]})
        X_te = pd.DataFrame({"b": [5.0, np.nan]})
        col_types = {"numeric": ["b"], "binary": [], "ordinal": [],
                     "categorical": [], "constant": [], "high_cardinality": []}
        tiers = {"tier1": [], "tier2": ["b"], "tier3": [], "tier4": []}

        X_tr, X_va, X_te, indicators, stats = preproc_mod.impute_tiered(
            X_tr, X_va, X_te, col_types, tiers
        )
        assert "b" in X_tr.columns
        assert "b_missing" in X_tr.columns
        assert not X_tr["b"].isna().any()
        # Imputed with train median (2.0)
        assert X_tr["b"].iloc[2] == 2.0
        # Validation also uses train median
        assert X_va["b"].iloc[0] == 2.0

    def test_tier1_simple_impute_no_indicator(self):
        X_tr = pd.DataFrame({"c": [10.0, 20.0, np.nan, 40.0]})
        X_va = pd.DataFrame({"c": [np.nan]})
        X_te = pd.DataFrame({"c": [50.0]})
        col_types = {"numeric": ["c"], "binary": [], "ordinal": [],
                     "categorical": [], "constant": [], "high_cardinality": []}
        tiers = {"tier1": ["c"], "tier2": [], "tier3": [], "tier4": []}

        X_tr, X_va, X_te, indicators, _ = preproc_mod.impute_tiered(
            X_tr, X_va, X_te, col_types, tiers
        )
        assert "c_missing" not in X_tr.columns
        assert not X_tr["c"].isna().any()

    def test_no_nan_remains(self):
        rng = np.random.RandomState(42)
        vals = rng.randn(100)
        vals[rng.choice(100, 10, replace=False)] = np.nan
        X_tr = pd.DataFrame({"x": vals})
        X_va = pd.DataFrame({"x": [np.nan, 1.0]})
        X_te = pd.DataFrame({"x": [2.0, np.nan]})
        col_types = {"numeric": ["x"], "binary": [], "ordinal": [],
                     "categorical": [], "constant": [], "high_cardinality": []}
        tiers = {"tier1": ["x"], "tier2": [], "tier3": [], "tier4": []}

        X_tr, X_va, X_te, _, _ = preproc_mod.impute_tiered(
            X_tr, X_va, X_te, col_types, tiers
        )
        assert not X_tr["x"].isna().any()
        assert not X_va["x"].isna().any()
        assert not X_te["x"].isna().any()
