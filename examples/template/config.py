"""
config.py — Global Configuration (Single Source of Truth)

All hardcoded values live here. Phase scripts import this file.
DO NOT scatter magic numbers, column names, or paths across scripts.

Usage:
    from config import *
    # or
    import config as cfg
"""

from pathlib import Path

# ──────────────────────────────────────────────
# Paths
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent

RAW_DATA_DIR = PROJECT_ROOT / "00_database" / "raw"
EXPLORATION_RESULTS = PROJECT_ROOT / "01_exploration" / "results"
SPLIT_RESULTS = PROJECT_ROOT / "02_splitting" / "results"
PREPROCESS_RESULTS = PROJECT_ROOT / "03_preprocessing" / "results"
FEATURE_RESULTS = PROJECT_ROOT / "04_feature_selection" / "results"
MODELING_RESULTS = PROJECT_ROOT / "05_modeling" / "results"
EVALUATION_RESULTS = PROJECT_ROOT / "06_evaluation" / "results"
INTERPRET_RESULTS = PROJECT_ROOT / "07_interpretability" / "results"
FAIRNESS_RESULTS = PROJECT_ROOT / "08_fairness" / "results"
REPORTING_RESULTS = PROJECT_ROOT / "09_reporting" / "results"

OUTPUT_FIGURES = PROJECT_ROOT / "outputs" / "figures"
OUTPUT_TABLES = PROJECT_ROOT / "outputs" / "tables"
OUTPUT_MODELS = PROJECT_ROOT / "outputs" / "models"

# Raw data file (update after placing your CSV in 00_database/raw/)
# RAW_DATA = RAW_DATA_DIR / "your_data.csv"

# ──────────────────────────────────────────────
# Column Definitions (MUST customize per dataset)
# ──────────────────────────────────────────────
PATIENT_ID_COL = "patient_id"       # Unique patient identifier
TIME_COL = "event_time"             # Timestamp for temporal ordering (if available)
LABEL_COL = "y"                     # Binary label column (0/1)

# Original target column name and positive class value (before binarization)
# ORIGINAL_TARGET = "readmitted"
# POSITIVE_CLASS = "<30"

# ──────────────────────────────────────────────
# Cohort Exclusion Criteria (MLGG-C01)
# ──────────────────────────────────────────────
# Define records where the outcome is structurally impossible.
# Example for readmission prediction:
# EXCLUDE_CONDITIONS = {
#     "discharge_disposition_id": [11, 13, 14, 19, 20, 21],  # expired / hospice
#     "gender": ["Unknown/Invalid"],
# }
EXCLUDE_CONDITIONS = {}

# ──────────────────────────────────────────────
# Feature Temporal Classification (MLGG-F05)
# ──────────────────────────────────────────────
# Features available at the prediction time point.
# All other features are considered post-prediction and MUST NOT be used.
# ADMISSION_FEATURES = ["age", "gender", "race", "admission_type_id", ...]
# DISCHARGE_FEATURES = ADMISSION_FEATURES + ["num_procedures", "num_medications", ...]
ADMISSION_FEATURES = []
DISCHARGE_FEATURES = []

# ──────────────────────────────────────────────
# Missingness Strategy (MLGG-P06)
# ──────────────────────────────────────────────
# Tiered by mechanism and proportion:
#   <5%: simple impute (median/mode)
#   5-40%: multiple imputation
#   40-80%: MI + indicator + sensitivity analysis
#   >80%: clinical review per feature
COLS_DROP_VALUE_KEEP_INDICATOR = []  # High missing, keep as indicator
COLS_IMPUTE_WITH_INDICATOR = []     # Medium missing, impute + indicator
COLS_SIMPLE_IMPUTE = []             # Low missing, simple impute

# ──────────────────────────────────────────────
# Near-Zero Variance Columns (Phase 4 pre-filter)
# ──────────────────────────────────────────────
# Columns with >99% same value — drop before feature selection.
NEAR_ZERO_VARIANCE_COLS = []

# ──────────────────────────────────────────────
# Reproducibility
# ──────────────────────────────────────────────
RANDOM_STATE = 42
SEED_LIST = [42, 123, 456, 789, 1024]  # For multi-seed stability (MLGG-R02)

# ──────────────────────────────────────────────
# Split Ratios
# ──────────────────────────────────────────────
TRAIN_RATIO = 0.60
VALID_RATIO = 0.20
TEST_RATIO = 0.20

# ──────────────────────────────────────────────
# Evaluation
# ──────────────────────────────────────────────
N_BOOTSTRAP = 1000       # Bootstrap resamples for CI (MLGG-E01)
CI_LEVEL = 0.95          # Confidence level
CALIBRATION_ECE_THRESHOLD = 0.1  # MLGG-E03
