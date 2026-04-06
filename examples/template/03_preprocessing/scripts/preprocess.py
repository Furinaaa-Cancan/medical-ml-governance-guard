"""
Phase 3: Preprocessing

Checkpoint (MLGG):
  - All fit() on training set ONLY? (MLGG-P01)
  - SMOTE on training set ONLY (if used)? (MLGG-P02)
  - No global cleaning before split? (MLGG-P03)
  - Encoding matches variable semantics? (MLGG-P05)
  - Missingness strategy: mechanism over proportion? (MLGG-P06)

Input:  02_splitting/results/train.csv, valid.csv, test.csv
Output: 03_preprocessing/results/processed_data.npz, feature_names.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import pandas as pd
import numpy as np
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
import joblib


def load_splits():
    """Load train/valid/test from Phase 2."""
    train = pd.read_csv(cfg.SPLIT_RESULTS / "train.csv")
    valid = pd.read_csv(cfg.SPLIT_RESULTS / "valid.csv")
    test = pd.read_csv(cfg.SPLIT_RESULTS / "test.csv")
    return train, valid, test


def separate_xy(df):
    """Separate features and label. Drop ID and time columns.

    MLGG-F05: If temporal feature lists are configured, enforce whitelist.
    """
    drop_cols = [cfg.PATIENT_ID_COL, cfg.TIME_COL, cfg.LABEL_COL]
    drop_cols = [c for c in drop_cols if c and c in df.columns]
    X = df.drop(columns=drop_cols)
    y = df[cfg.LABEL_COL].values

    # Temporal feature filtering (MLGG-F05)
    allowed = cfg.ADMISSION_FEATURES or cfg.DISCHARGE_FEATURES
    if allowed:
        available = [c for c in allowed if c in X.columns]
        dropped = set(X.columns) - set(available)
        if dropped:
            print(f"[MLGG-F05] Temporal filter: dropped {len(dropped)} post-prediction features")
        X = X[available]
    elif X.shape[1] > 0:
        print("[MLGG-F05] WARNING: No temporal feature list configured in config.py. "
              "All features are assumed available at prediction time.")

    return X, y


def identify_column_types(X):
    """Classify columns as numeric or categorical.

    MLGG-P05: Encoding MUST match variable semantics.
    - Nominal variables -> OneHotEncoder
    - Ordinal variables -> OrdinalEncoder only with verified monotonic order
    - Binary variables -> passthrough (0/1)
    """
    numeric_cols = X.select_dtypes(include=[np.number]).columns.tolist()
    categorical_cols = X.select_dtypes(include=["object", "category"]).columns.tolist()

    # TODO: Review each categorical column — is it nominal or ordinal?
    # Nominal (no inherent order): race, gender, drug_name → OneHotEncoder
    # Ordinal (verified monotonic):  → OrdinalEncoder (rare, must verify)
    # DO NOT assume ordinal without empirical evidence

    return numeric_cols, categorical_cols


def build_preprocessor(numeric_cols, categorical_cols):
    """Build sklearn Pipeline. All fit() happens on train only (MLGG-P01).

    MLGG-P04: Imputer statistics from training set only.
    MLGG-P06: Missingness tiered strategy.
    """
    transformers = []

    if numeric_cols:
        numeric_pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("scaler", StandardScaler()),
        ])
        transformers.append(("num", numeric_pipe, numeric_cols))

    if categorical_cols:
        cat_pipe = Pipeline([
            ("imputer", SimpleImputer(strategy="most_frequent")),
            ("encoder", OneHotEncoder(handle_unknown="ignore", sparse_output=False)),
        ])
        transformers.append(("cat", cat_pipe, categorical_cols))

    preprocessor = ColumnTransformer(transformers, remainder="drop")

    # Warn about dropped columns (remainder="drop")
    all_handled = set(numeric_cols + categorical_cols)
    return preprocessor, all_handled


def main():
    cfg.PREPROCESS_RESULTS.mkdir(parents=True, exist_ok=True)

    train, valid, test = load_splits()
    X_train, y_train = separate_xy(train)
    X_valid, y_valid = separate_xy(valid)
    X_test, y_test = separate_xy(test)

    numeric_cols, categorical_cols = identify_column_types(X_train)
    print(f"Numeric features: {len(numeric_cols)}")
    print(f"Categorical features: {len(categorical_cols)}")

    # Build and fit on TRAIN ONLY (MLGG-P01)
    preprocessor, handled_cols = build_preprocessor(numeric_cols, categorical_cols)

    # Check for silently dropped columns
    unhandled = set(X_train.columns) - handled_cols
    if unhandled:
        print(f"WARNING: {len(unhandled)} columns not handled by preprocessor "
              f"(will be dropped): {sorted(unhandled)[:10]}")

    X_train_proc = preprocessor.fit_transform(X_train)  # fit on train
    X_valid_proc = preprocessor.transform(X_valid)       # transform only
    X_test_proc = preprocessor.transform(X_test)         # transform only
    print(f"[MLGG-P01] Preprocessor fitted on training set only")

    # Get feature names after transformation
    feature_names = preprocessor.get_feature_names_out().tolist()
    print(f"Total features after preprocessing: {len(feature_names)}")

    # Verify no NaN remaining
    for name, arr in [("train", X_train_proc), ("valid", X_valid_proc), ("test", X_test_proc)]:
        n_nan = np.isnan(arr).sum()
        if n_nan > 0:
            raise ValueError(f"CRITICAL: {n_nan} NaN values in {name} after preprocessing")

    # Save
    np.savez(
        cfg.PREPROCESS_RESULTS / "processed_data.npz",
        X_train=X_train_proc, y_train=y_train,
        X_valid=X_valid_proc, y_valid=y_valid,
        X_test=X_test_proc, y_test=y_test,
    )
    with open(cfg.PREPROCESS_RESULTS / "feature_names.json", "w") as f:
        json.dump(feature_names, f, indent=2)
    with open(cfg.PREPROCESS_RESULTS / "column_types.json", "w") as f:
        json.dump({"numeric": numeric_cols, "categorical": categorical_cols}, f, indent=2)

    joblib.dump(preprocessor, cfg.PREPROCESS_RESULTS / "preprocessor.pkl")

    print(f"\nPhase 3 complete. Results in {cfg.PREPROCESS_RESULTS}/")
    print("--- Checkpoint ---")
    print("[x] fit() on training set only (MLGG-P01)")
    print("[ ] Encoding matches variable semantics? (MLGG-P05)")
    print("[ ] Missingness strategy documented? (MLGG-P06)")


if __name__ == "__main__":
    main()
