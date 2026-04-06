"""
Phase 2: Data Splitting

Checkpoint (MLGG):
  - No patient overlap across splits? (MLGG-S01)
  - Positive rates consistent across splits?
  - Temporal order respected (if applicable)? (MLGG-S02)

Input:  00_database/raw/<dataset>.csv (or Phase 1 cleaned data)
Output: 02_splitting/results/train.csv, valid.csv, test.csv
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import pandas as pd
import numpy as np
from sklearn.model_selection import GroupShuffleSplit


def load_and_prepare(df=None):
    """Load data with cohort exclusions applied.
    Override df parameter if passing cleaned data from Phase 1.
    """
    if df is None:
        raw_path = getattr(cfg, "RAW_DATA", None)
        if raw_path is None or not Path(raw_path).exists():
            csvs = sorted(cfg.RAW_DATA_DIR.glob("*.csv"))
            if not csvs:
                raise FileNotFoundError(
                    f"No CSV found in {cfg.RAW_DATA_DIR}/. "
                    f"Place your data there or set RAW_DATA in config.py."
                )
            raw_path = csvs[0]
        df = pd.read_csv(raw_path)
        # Apply cohort exclusions
        for col, values in cfg.EXCLUDE_CONDITIONS.items():
            if col in df.columns:
                df = df[~df[col].isin(values)]

    # TODO: Create binary label if not already 0/1
    # Example:
    # df[cfg.LABEL_COL] = (df["original_target"] == "positive_value").astype(int)

    return df


def split_by_patient(df):
    """Split data ensuring no patient appears in multiple sets (MLGG-S01).

    If temporal data is available, use time-based splitting (MLGG-S02).
    Otherwise, use stratified random split by patient.
    """
    has_time = bool(cfg.TIME_COL) and cfg.TIME_COL in df.columns and df[cfg.TIME_COL].notna().any()

    if has_time:
        return _temporal_split(df)
    else:
        return _random_patient_split(df)


def _temporal_split(df):
    """Time-based split: train < valid < test (MLGG-S02)."""
    # Build patient-level timeline (earliest event per patient)
    patient_time = (
        df.groupby(cfg.PATIENT_ID_COL)[cfg.TIME_COL]
        .min()
        .sort_values()
        .reset_index()
    )

    n = len(patient_time)
    train_end = int(n * cfg.TRAIN_RATIO)
    valid_end = int(n * (cfg.TRAIN_RATIO + cfg.VALID_RATIO))

    train_ids = set(patient_time.iloc[:train_end][cfg.PATIENT_ID_COL])
    valid_ids = set(patient_time.iloc[train_end:valid_end][cfg.PATIENT_ID_COL])
    test_ids = set(patient_time.iloc[valid_end:][cfg.PATIENT_ID_COL])

    train = df[df[cfg.PATIENT_ID_COL].isin(train_ids)]
    valid = df[df[cfg.PATIENT_ID_COL].isin(valid_ids)]
    test = df[df[cfg.PATIENT_ID_COL].isin(test_ids)]

    # Verify each split contains both classes
    for name, split_df in [("train", train), ("valid", valid), ("test", test)]:
        if split_df[cfg.LABEL_COL].nunique() < 2:
            raise ValueError(
                f"CRITICAL: Temporal {name} split contains only one class. "
                f"Consider adjusting split boundaries or using random split."
            )

    return train, valid, test


def _random_patient_split(df):
    """Stratified random split by patient ID."""
    # Patient-level label (majority vote or any positive)
    patient_label = df.groupby(cfg.PATIENT_ID_COL)[cfg.LABEL_COL].max()
    unique_patients = patient_label.index.values
    unique_labels = patient_label.values

    # First split: train vs (valid+test)
    gss1 = GroupShuffleSplit(n_splits=1, test_size=1 - cfg.TRAIN_RATIO,
                             random_state=cfg.RANDOM_STATE)
    train_idx, rest_idx = next(gss1.split(unique_patients, unique_labels,
                                          groups=unique_patients))
    train_patients = set(unique_patients[train_idx])
    rest_patients = unique_patients[rest_idx]
    rest_labels = unique_labels[rest_idx]

    # Second split: valid vs test
    relative_test = cfg.TEST_RATIO / (cfg.VALID_RATIO + cfg.TEST_RATIO)
    gss2 = GroupShuffleSplit(n_splits=1, test_size=relative_test,
                             random_state=cfg.RANDOM_STATE)
    valid_idx, test_idx = next(gss2.split(rest_patients, rest_labels,
                                          groups=rest_patients))
    valid_patients = set(rest_patients[valid_idx])
    test_patients = set(rest_patients[test_idx])

    train = df[df[cfg.PATIENT_ID_COL].isin(train_patients)]
    valid = df[df[cfg.PATIENT_ID_COL].isin(valid_patients)]
    test = df[df[cfg.PATIENT_ID_COL].isin(test_patients)]

    return train, valid, test


def verify(train, valid, test):
    """Post-split verification checks."""
    # MLGG-S01: No patient overlap
    train_ids = set(train[cfg.PATIENT_ID_COL])
    valid_ids = set(valid[cfg.PATIENT_ID_COL])
    test_ids = set(test[cfg.PATIENT_ID_COL])

    if not train_ids.isdisjoint(valid_ids):
        raise ValueError("CRITICAL: Patient overlap between train and valid sets!")
    if not train_ids.isdisjoint(test_ids):
        raise ValueError("CRITICAL: Patient overlap between train and test sets!")
    if not valid_ids.isdisjoint(test_ids):
        raise ValueError("CRITICAL: Patient overlap between valid and test sets!")
    print("[MLGG-S01] PASS: No patient overlap across splits")

    # Positive rate consistency — patient-level, not row-level
    splits = {"train": train, "valid": valid, "test": test}
    rates = {}
    for name, df in splits.items():
        patient_rate = df.groupby(cfg.PATIENT_ID_COL)[cfg.LABEL_COL].max().mean()
        rates[name] = patient_rate
        print(f"  {name}: n_rows={len(df)}, n_patients={df[cfg.PATIENT_ID_COL].nunique()}, "
              f"patient_positive_rate={patient_rate:.3f}")

    max_diff = max(rates.values()) - min(rates.values())
    if max_diff > 0.05:
        print(f"  WARNING: Positive rate difference across splits = {max_diff:.3f} (>0.05)")

    return rates


def main():
    cfg.SPLIT_RESULTS.mkdir(parents=True, exist_ok=True)

    df = load_and_prepare()
    train, valid, test = split_by_patient(df)
    rates = verify(train, valid, test)

    # Save splits
    train.to_csv(cfg.SPLIT_RESULTS / "train.csv", index=False)
    valid.to_csv(cfg.SPLIT_RESULTS / "valid.csv", index=False)
    test.to_csv(cfg.SPLIT_RESULTS / "test.csv", index=False)

    # Save stats
    stats = pd.DataFrame([
        {"split": "train", "n_rows": len(train), "n_patients": train[cfg.PATIENT_ID_COL].nunique(),
         "positive_rate": rates["train"]},
        {"split": "valid", "n_rows": len(valid), "n_patients": valid[cfg.PATIENT_ID_COL].nunique(),
         "positive_rate": rates["valid"]},
        {"split": "test", "n_rows": len(test), "n_patients": test[cfg.PATIENT_ID_COL].nunique(),
         "positive_rate": rates["test"]},
    ])
    stats.to_csv(cfg.SPLIT_RESULTS / "split_stats.csv", index=False)

    print(f"\nPhase 2 complete. Results in {cfg.SPLIT_RESULTS}/")
    print("--- Checkpoint ---")
    print("[x] No patient overlap (MLGG-S01)")
    print("[ ] Temporal order respected? (MLGG-S02)")
    print("[ ] Positive rates consistent across splits?")


if __name__ == "__main__":
    main()
