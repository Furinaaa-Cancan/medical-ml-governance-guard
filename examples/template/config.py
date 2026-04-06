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
# Preprocessing (Phase 3)
# ──────────────────────────────────────────────

# Column type detection thresholds (MLGG-P05)
# Cardinality-based: binary (2) / categorical (3-MAX) / numeric (> MAX or float)
MAX_ONEHOT_CARDINALITY = 15   # Categorical upper bound; > this → leave as-is

# Missingness tier thresholds (MLGG-P06, Madley-Dowd 2019)
#   Tier 1 (<5%):   simple impute (median/mode)
#   Tier 2 (5-40%): impute + missingness indicator
#   Tier 3 (40-80%): impute + missingness indicator + sensitivity flag
#   Tier 4 (>80%):  drop original value, keep missingness indicator only
MISSING_TIER1_UPPER = 0.05
MISSING_TIER2_UPPER = 0.40
MISSING_TIER3_UPPER = 0.80

# Manual overrides (take priority over auto-detection)
COLS_DROP_VALUE_KEEP_INDICATOR = []  # Force Tier 4
COLS_IMPUTE_WITH_INDICATOR = []     # Force Tier 2/3
COLS_SIMPLE_IMPUTE = []             # Force Tier 1

# Columns with clinically verified ordinal order → OrdinalEncoder
# Format: {"column_name": ["low", "medium", "high"]}
# DO NOT add here without empirical evidence of monotonic relationship
ORDINAL_COLUMNS = {}

# ──────────────────────────────────────────────
# Feature Selection (Phase 4)
# ──────────────────────────────────────────────
# Near-zero variance pre-filter
NZV_THRESHOLD = 0.99  # Remove features with > this fraction same value

# Stability Selection (Meinshausen & Buhlmann 2010)
STABILITY_N_SUBSAMPLES = 100       # Number of subsamples
STABILITY_SUBSAMPLE_RATIO = 0.50   # Fraction of each class to subsample
STABILITY_THRESHOLD = 0.60         # Selection probability cutoff
STABILITY_L1_RATIOS = (0.1, 0.3, 0.5, 0.7, 1.0)  # Elastic Net α values (Zou & Hastie 2005)
STABILITY_CS = (0.001, 0.01, 0.1, 1.0, 10.0)      # Regularization strengths
STABILITY_CV_FOLDS = 5             # Inner CV folds (StratifiedKFold)
STABILITY_MAX_ITER = 3000          # Solver iteration limit

# Ridge baseline comparison (Harrell 2015)
RIDGE_CV_CS = (0.001, 0.01, 0.1, 1.0, 10.0, 100.0)  # CV-tuned C values
RIDGE_FALLBACK_THRESHOLD = 0.005   # PR-AUC loss vs Ridge → fallback to full model

# Feature groups: OneHot dummies from same original variable must stay/drop together
# (Yuan & Lin 2006, Group LASSO). Auto-detected from Phase 3 encoding metadata.
# Manual override format: {"race": ["race_Asian", "race_Black", ...]}
FEATURE_GROUPS = {}

# Forbidden features (MLGG-F01: label leakage, MLGG-F02: future information)
# Features that must NEVER enter selection. Auto-populated by setup.py.
FORBIDDEN_FEATURES = []

# Legacy alias
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
