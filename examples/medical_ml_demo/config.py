"""
Global configuration for Medical ML Demo Project
=================================================
All hardcoded values live here. Scripts import from this file.
"""

import os

# --- Paths ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))

RAW_DATA = os.path.join(PROJECT_ROOT, "00_database", "raw", "diabetic_data.csv")

SPLIT_DIR = os.path.join(PROJECT_ROOT, "02_splitting", "results")
TRAIN_DATA = os.path.join(SPLIT_DIR, "train.csv")
VALID_DATA = os.path.join(SPLIT_DIR, "valid.csv")
TEST_DATA = os.path.join(SPLIT_DIR, "test.csv")

PREP_DIR = os.path.join(PROJECT_ROOT, "03_preprocessing", "results")
PIPELINE_PATH = os.path.join(PREP_DIR, "pipeline.pkl")

MODEL_DIR = os.path.join(PROJECT_ROOT, "outputs", "models")
FIGURE_DIR = os.path.join(PROJECT_ROOT, "outputs", "figures")
TABLE_DIR = os.path.join(PROJECT_ROOT, "outputs", "tables")

# --- Column Definitions ---
ID_COL = "patient_nbr"
ENCOUNTER_COL = "encounter_id"
LABEL_COL = "label"
ORIGINAL_TARGET = "readmitted"
POSITIVE_CLASS = "<30"  # readmitted within 30 days

# Columns to drop (non-predictive)
DROP_COLS = [
    "encounter_id",
    "patient_nbr",
    "readmitted",
]

# --- Cohort Exclusion Criteria ---
# Records to exclude BEFORE any analysis (not in target population)
EXCLUDE_DISCHARGE_DISPOSITION = [
    11,  # Expired (院内死亡) — 无法再入院，readmit=0% (n=1642)
    13,  # Hospice/home (居家临终关怀) — 不属于再入院预测目标
    14,  # Hospice/medical facility (机构临终关怀)
    19,  # Expired at home — 院外死亡
    20,  # Expired (place unknown)
    21,  # Expired (place unknown)
]
EXCLUDE_GENDER = ["Unknown/Invalid"]  # 数据质量问题 (n=3)
EXCLUDE_ADMISSION_TYPE = [4]  # Newborn — 糖尿病数据集中的数据错误 (n=10)

# Near-zero variance columns (to drop)
NEAR_ZERO_VARIANCE_COLS = [
    "examide",                    # 101765 No / 1 Steady
    "citoglipton",                # 101765 No / 1 Steady
    "acetohexamide",              # 101765 No / 1 Steady
    "troglitazone",               # 101763 No / 3 Steady
    "glimepiride-pioglitazone",   # 101765 No / 1 Steady
    "metformin-rosiglitazone",    # 101764 No / 2 Steady
    "metformin-pioglitazone",     # 101765 No / 1 Steady
]

# --- Missingness Strategy (tiered, per Madley-Dowd 2019 / Jakobsen 2017) ---
# Mechanism > proportion. No automatic exclusion by threshold alone.
# See: ml-leakage-guard/references/missingness-policy.example.json v2.0
MISSINGNESS_STRATEGY = {
    # Tier 4 (>80%): drop original value, keep missing indicator
    # Rationale: MNAR in EHR — "not tested" is a clinical decision with predictive value
    "drop_value_keep_indicator": [
        "weight",          # 96.9% missing — MNAR (not weighed = not clinically relevant)
        "max_glu_serum",   # 94.8% missing — MNAR (not tested = glucose not a concern)
        "A1Cresult",       # 83.3% missing — MNAR (not tested = HbA1c not prioritized)
    ],
    # Tier 3 (40-80%): MI + missing indicator + sensitivity analysis
    "impute_with_indicator": [
        "medical_specialty",  # 49.1% missing — MAR/MNAR
    ],
    # Tier 2 (5-40%): MI + missing indicator (>10%)
    "impute_with_indicator_moderate": [
        "payer_code",         # 39.6% missing — MAR
    ],
    # Tier 1 (<5%): simple imputation
    "simple_impute": [
        "race",            # 2.2% missing
        "diag_3",          # 1.4% missing
        "diag_2",          # 0.4% missing
        "diag_1",          # 0.02% missing
    ],
}

# --- Feature Temporal Classification (MLGG-F02) ---
# Features available at ADMISSION (prior to current encounter)
# Includes missing indicators for Tier 4 features that are known at admission
ADMISSION_TIME_FEATURES = [
    "race", "gender", "age",
    "admission_type_id", "admission_source_id",
    "payer_code", "medical_specialty",
    "number_outpatient", "number_emergency", "number_inpatient",
    "diag_1", "diag_2", "diag_3",
    "weight",  # original value dropped (Tier 4), but weight_missing indicator is admission-time
]

# Features available only at/after DISCHARGE
DISCHARGE_TIME_FEATURES = [
    "discharge_disposition_id",
    "time_in_hospital", "num_lab_procedures", "num_procedures",
    "num_medications", "number_diagnoses",
    "max_glu_serum", "A1Cresult",
    "metformin", "repaglinide", "nateglinide", "chlorpropamide",
    "glimepiride", "glipizide", "glyburide", "pioglitazone",
    "rosiglitazone", "acarbose", "miglitol", "insulin",
    "glyburide-metformin",
    "change", "diabetesMed",
]

# --- Random Seeds ---
RANDOM_STATE = 42
SEED_LIST = [42, 123, 456, 789, 1024]  # for multi-seed stability (MLGG-R02)

# --- Split Ratios ---
TRAIN_RATIO = 0.6
VALID_RATIO = 0.2
TEST_RATIO = 0.2

# --- Bootstrap ---
N_BOOTSTRAP = 1000
CI_LEVEL = 0.95
