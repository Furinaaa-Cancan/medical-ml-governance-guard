"""Test config.py integrity."""

import importlib
from pathlib import Path


def test_config_importable(project_root):
    """config.py must import without error."""
    import config as cfg
    assert hasattr(cfg, "PROJECT_ROOT")


def test_config_required_attributes(project_root):
    """All required attributes exist with correct types."""
    import config as cfg

    # Path attributes
    for attr in [
        "PROJECT_ROOT", "RAW_DATA_DIR", "EXPLORATION_RESULTS", "SPLIT_RESULTS",
        "PREPROCESS_RESULTS", "FEATURE_RESULTS", "MODELING_RESULTS",
        "EVALUATION_RESULTS", "INTERPRET_RESULTS", "FAIRNESS_RESULTS",
        "REPORTING_RESULTS", "OUTPUT_FIGURES", "OUTPUT_TABLES", "OUTPUT_MODELS",
    ]:
        assert hasattr(cfg, attr), f"Missing: {attr}"
        assert isinstance(getattr(cfg, attr), Path), f"{attr} must be a Path"

    # Column definitions
    for attr in ["PATIENT_ID_COL", "TIME_COL", "LABEL_COL"]:
        assert hasattr(cfg, attr), f"Missing: {attr}"
        assert isinstance(getattr(cfg, attr), str), f"{attr} must be str"

    # Numeric config
    assert isinstance(cfg.RANDOM_STATE, int)
    assert isinstance(cfg.TRAIN_RATIO, float)
    assert isinstance(cfg.VALID_RATIO, float)
    assert isinstance(cfg.TEST_RATIO, float)
    assert isinstance(cfg.N_BOOTSTRAP, int)
    assert isinstance(cfg.CI_LEVEL, float)


def test_config_split_ratios_sum_to_one(project_root):
    """Train + Valid + Test must equal 1.0."""
    import config as cfg
    total = cfg.TRAIN_RATIO + cfg.VALID_RATIO + cfg.TEST_RATIO
    assert abs(total - 1.0) < 0.01, f"Split ratios sum to {total}, expected 1.0"


def test_config_seed_list(project_root):
    """SEED_LIST must have >= 5 entries for MLGG-R02."""
    import config as cfg
    assert hasattr(cfg, "SEED_LIST")
    assert len(cfg.SEED_LIST) >= 5, "MLGG-R02 requires >= 5 seeds"
    assert len(set(cfg.SEED_LIST)) == len(cfg.SEED_LIST), "Seeds must be unique"
