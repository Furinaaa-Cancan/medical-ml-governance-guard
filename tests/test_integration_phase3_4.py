"""Integration test: Phase 3 → Phase 4 pipeline.

Verifies the full data chain from raw split CSVs through preprocessing
to feature selection, including encoding_groups.json handoff for Group LASSO.
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import json
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config as cfg


@pytest.fixture
def pipeline_dirs(tmp_path, monkeypatch):
    """Set up temporary directories mimicking project structure."""
    split_dir = tmp_path / "02_splitting" / "results"
    preproc_dir = tmp_path / "03_preprocessing" / "results"
    feature_dir = tmp_path / "04_feature_selection" / "results"

    split_dir.mkdir(parents=True)
    preproc_dir.mkdir(parents=True)
    feature_dir.mkdir(parents=True)

    monkeypatch.setattr(cfg, "SPLIT_RESULTS", split_dir)
    monkeypatch.setattr(cfg, "PREPROCESS_RESULTS", preproc_dir)
    monkeypatch.setattr(cfg, "FEATURE_RESULTS", feature_dir)
    monkeypatch.setattr(cfg, "PATIENT_ID_COL", "patient_id")
    monkeypatch.setattr(cfg, "TIME_COL", "event_time")
    monkeypatch.setattr(cfg, "LABEL_COL", "y")
    monkeypatch.setattr(cfg, "ADMISSION_FEATURES", [])
    monkeypatch.setattr(cfg, "DISCHARGE_FEATURES", [])
    monkeypatch.setattr(cfg, "ORDINAL_COLUMNS", {})
    monkeypatch.setattr(cfg, "FEATURE_GROUPS", {})
    monkeypatch.setattr(cfg, "FORBIDDEN_FEATURES", [])
    monkeypatch.setattr(cfg, "COLS_DROP_VALUE_KEEP_INDICATOR", [])
    monkeypatch.setattr(cfg, "COLS_IMPUTE_WITH_INDICATOR", [])
    monkeypatch.setattr(cfg, "COLS_SIMPLE_IMPUTE", [])
    monkeypatch.setattr(cfg, "MAX_ONEHOT_CARDINALITY", 15)
    monkeypatch.setattr(cfg, "MISSING_TIER1_UPPER", 0.05)
    monkeypatch.setattr(cfg, "MISSING_TIER2_UPPER", 0.40)
    monkeypatch.setattr(cfg, "MISSING_TIER3_UPPER", 0.80)

    # Phase 4 config — fast settings for testing
    monkeypatch.setattr(cfg, "NZV_THRESHOLD", 0.99)
    monkeypatch.setattr(cfg, "STABILITY_N_SUBSAMPLES", 10)
    monkeypatch.setattr(cfg, "STABILITY_SUBSAMPLE_RATIO", 0.50)
    monkeypatch.setattr(cfg, "STABILITY_THRESHOLD", 0.3)
    monkeypatch.setattr(cfg, "STABILITY_L1_RATIOS", (0.5, 1.0))
    monkeypatch.setattr(cfg, "STABILITY_CS", (0.1, 1.0))
    monkeypatch.setattr(cfg, "STABILITY_CV_FOLDS", 3)
    monkeypatch.setattr(cfg, "STABILITY_MAX_ITER", 1000)
    monkeypatch.setattr(cfg, "RIDGE_CV_CS", (0.01, 0.1, 1.0, 10.0))
    monkeypatch.setattr(cfg, "RIDGE_FALLBACK_THRESHOLD", 0.005)
    monkeypatch.setattr(cfg, "RANDOM_STATE", 42)

    return {"split": split_dir, "preproc": preproc_dir, "feature": feature_dir}


@pytest.fixture
def synthetic_splits(pipeline_dirs):
    """Create synthetic train/valid/test CSVs with mixed types."""
    rng = np.random.RandomState(42)
    split_dir = pipeline_dirs["split"]

    def make_df(n, seed_offset=0):
        r = np.random.RandomState(42 + seed_offset)
        df = pd.DataFrame({
            "patient_id": np.arange(n),
            "event_time": pd.date_range("2020-01-01", periods=n, freq="D"),
            "age": r.randint(20, 90, n).astype(float),
            "gender": r.choice(["Male", "Female"], n),
            "race": r.choice(["White", "Black", "Asian", "Hispanic"], n),
            "bp_systolic": r.normal(130, 20, n),
            "bp_diastolic": r.normal(80, 12, n),
            "lab_glucose": r.normal(100, 30, n),
            "y": r.binomial(1, 0.20, n),
        })
        # Inject some missingness
        for col in ["bp_systolic", "lab_glucose"]:
            mask = r.random(n) < 0.03  # ~3% → tier1
            df.loc[mask, col] = np.nan
        return df

    train = make_df(300, seed_offset=0)
    valid = make_df(100, seed_offset=1)
    test = make_df(100, seed_offset=2)

    train.to_csv(split_dir / "train.csv", index=False)
    valid.to_csv(split_dir / "valid.csv", index=False)
    test.to_csv(split_dir / "test.csv", index=False)

    return train, valid, test


class TestPhase3to4Pipeline:
    """End-to-end: Phase 3 preprocessing → Phase 4 feature selection."""

    def test_phase3_produces_all_outputs(self, pipeline_dirs, synthetic_splits):
        from importlib import import_module
        preproc_mod = import_module("03_preprocessing.scripts.preprocess")

        preproc_mod.main()

        preproc_dir = pipeline_dirs["preproc"]
        assert (preproc_dir / "processed_data.npz").exists()
        assert (preproc_dir / "feature_names.json").exists()
        assert (preproc_dir / "encoding_groups.json").exists()
        assert (preproc_dir / "column_types.json").exists()
        assert (preproc_dir / "missingness_report.json").exists()

    def test_encoding_groups_match_feature_names(self, pipeline_dirs, synthetic_splits):
        from importlib import import_module
        preproc_mod = import_module("03_preprocessing.scripts.preprocess")
        preproc_mod.main()

        preproc_dir = pipeline_dirs["preproc"]
        with open(preproc_dir / "feature_names.json") as f:
            feature_names = json.load(f)
        with open(preproc_dir / "encoding_groups.json") as f:
            groups = json.load(f)

        # All dummy columns referenced in groups must exist in feature_names
        for group_name, dummy_cols in groups.items():
            for col in dummy_cols:
                assert col in feature_names, (
                    f"encoding_groups references '{col}' but it's not in feature_names"
                )

    def test_no_nan_in_processed_data(self, pipeline_dirs, synthetic_splits):
        from importlib import import_module
        preproc_mod = import_module("03_preprocessing.scripts.preprocess")
        preproc_mod.main()

        data = np.load(pipeline_dirs["preproc"] / "processed_data.npz")
        for key in ["X_train", "X_valid", "X_test"]:
            assert np.isnan(data[key]).sum() == 0, f"NaN found in {key}"

    def test_phase4_reads_phase3_output(self, pipeline_dirs, synthetic_splits):
        """Phase 4 must successfully consume Phase 3 output."""
        from importlib import import_module
        preproc_mod = import_module("03_preprocessing.scripts.preprocess")
        feat_mod = import_module("04_feature_selection.scripts.select_features")

        preproc_mod.main()
        feat_mod.main()

        feature_dir = pipeline_dirs["feature"]
        assert (feature_dir / "selected_data.npz").exists()
        assert (feature_dir / "selected_features.json").exists()
        assert (feature_dir / "selection_report.json").exists()
        assert (feature_dir / "stability_selection.csv").exists()

    def test_selected_features_subset_of_preprocessed(self, pipeline_dirs, synthetic_splits):
        from importlib import import_module
        preproc_mod = import_module("03_preprocessing.scripts.preprocess")
        feat_mod = import_module("04_feature_selection.scripts.select_features")

        preproc_mod.main()
        feat_mod.main()

        with open(pipeline_dirs["preproc"] / "feature_names.json") as f:
            all_features = set(json.load(f))
        with open(pipeline_dirs["feature"] / "selected_features.json") as f:
            selected = set(json.load(f))

        assert selected.issubset(all_features), (
            f"Selected features not subset of preprocessed: {selected - all_features}"
        )

    def test_dimensions_consistent(self, pipeline_dirs, synthetic_splits):
        from importlib import import_module
        preproc_mod = import_module("03_preprocessing.scripts.preprocess")
        feat_mod = import_module("04_feature_selection.scripts.select_features")

        preproc_mod.main()
        feat_mod.main()

        data = np.load(pipeline_dirs["feature"] / "selected_data.npz")
        with open(pipeline_dirs["feature"] / "selected_features.json") as f:
            selected = json.load(f)

        # Feature count must match array width
        assert data["X_train"].shape[1] == len(selected)
        assert data["X_valid"].shape[1] == len(selected)
        assert data["X_test"].shape[1] == len(selected)

        # Row counts must match original splits
        assert data["X_train"].shape[0] == 300
        assert data["X_valid"].shape[0] == 100
        assert data["X_test"].shape[0] == 100

    def test_selection_report_complete(self, pipeline_dirs, synthetic_splits):
        from importlib import import_module
        preproc_mod = import_module("03_preprocessing.scripts.preprocess")
        feat_mod = import_module("04_feature_selection.scripts.select_features")

        preproc_mod.main()
        feat_mod.main()

        with open(pipeline_dirs["feature"] / "selection_report.json") as f:
            report = json.load(f)

        required_keys = [
            "method", "n_input_features", "n_selected_features",
            "ridge_baseline_prauc", "ridge_best_C",
            "stability_config", "expected_false_selections",
            "feature_groups_used", "epv_after_selection", "n_events",
        ]
        for key in required_keys:
            assert key in report, f"Missing key in selection_report: {key}"

    def test_group_lasso_uses_encoding_groups(self, pipeline_dirs, synthetic_splits):
        """Phase 4 must load encoding_groups.json from Phase 3."""
        from importlib import import_module
        preproc_mod = import_module("03_preprocessing.scripts.preprocess")
        feat_mod = import_module("04_feature_selection.scripts.select_features")

        preproc_mod.main()

        # Verify encoding_groups.json has categorical groups
        with open(pipeline_dirs["preproc"] / "encoding_groups.json") as f:
            groups = json.load(f)

        # race and gender should have been detected as categorical/binary
        # race has 4 categories → should be in encoding_groups
        assert len(groups) > 0, "No encoding groups detected from categorical columns"

        # Now run Phase 4 — it should pick up the groups
        feat_mod.main()

        with open(pipeline_dirs["feature"] / "selection_report.json") as f:
            report = json.load(f)
        assert report["feature_groups_used"] > 0
