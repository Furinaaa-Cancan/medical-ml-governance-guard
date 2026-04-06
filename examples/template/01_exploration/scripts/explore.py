"""
Phase 1: Data Understanding

Checkpoint (MLGG):
  - Sample size adequate per Riley criteria? (MLGG-Z01)
  - Cohort exclusions documented? (MLGG-C01)
  - Prediction time point defined? (MLGG-F05)

Input:  00_database/raw/<dataset>.csv
Output: 01_exploration/results/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import pandas as pd
import numpy as np


def load_data():
    """Load raw data and apply cohort exclusion criteria (MLGG-C01)."""
    raw_path = getattr(cfg, "RAW_DATA", None)
    if raw_path is None or not Path(raw_path).exists():
        # Auto-discover CSV in raw directory
        csvs = sorted(cfg.RAW_DATA_DIR.glob("*.csv"))
        if not csvs:
            raise FileNotFoundError(
                f"No CSV found in {cfg.RAW_DATA_DIR}/. "
                f"Place your data there or set RAW_DATA in config.py."
            )
        raw_path = csvs[0]
        if len(csvs) > 1:
            print(f"WARNING: Multiple CSVs found, using {raw_path.name}")
    df = pd.read_csv(raw_path)
    print(f"Raw data: {len(df)} rows, {df.shape[1]} columns")

    # Apply cohort exclusions
    n_before = len(df)
    for col, values in cfg.EXCLUDE_CONDITIONS.items():
        if col in df.columns:
            df = df[~df[col].isin(values)]
    n_excluded = n_before - len(df)
    if n_excluded > 0:
        print(f"Cohort exclusion: removed {n_excluded} rows ({n_excluded/n_before:.1%})")

    return df


def basic_info(df):
    """Dataset overview: rows, patients, positive rate, features."""
    info = {
        "total_rows": len(df),
        "total_columns": df.shape[1],
    }
    if cfg.PATIENT_ID_COL in df.columns:
        info["unique_patients"] = df[cfg.PATIENT_ID_COL].nunique()
    if cfg.LABEL_COL in df.columns:
        info["positive_rate"] = df[cfg.LABEL_COL].mean()
        info["positive_count"] = int(df[cfg.LABEL_COL].sum())
        info["negative_count"] = int(len(df) - df[cfg.LABEL_COL].sum())
    return pd.DataFrame([info])


def missing_analysis(df):
    """Missing value analysis per column."""
    missing = df.isnull().sum()
    pct = df.isnull().mean()
    result = pd.DataFrame({
        "missing_count": missing,
        "missing_pct": pct,
        "dtype": df.dtypes.astype(str),
    }).sort_values("missing_pct", ascending=False)
    return result


def epv_check(df):
    """Events Per Variable check (MLGG-Z01).

    EPV >= 10 is a simplified heuristic (Peduzzi 1996).
    For rigorous assessment, use Riley 2019/2020 criteria.
    """
    if cfg.LABEL_COL not in df.columns:
        print("WARNING: Label column not found, skipping EPV check")
        return pd.DataFrame()

    n_events = int(df[cfg.LABEL_COL].sum())
    n_non_events = len(df) - n_events
    min_class = min(n_events, n_non_events)

    # Count candidate predictors (excluding ID, time, label)
    exclude = {c for c in [cfg.PATIENT_ID_COL, cfg.TIME_COL, cfg.LABEL_COL] if c}
    n_predictors = len([c for c in df.columns if c not in exclude])

    epv = min_class / max(n_predictors, 1)

    result = {
        "n_events": n_events,
        "n_non_events": n_non_events,
        "n_predictors": n_predictors,
        "EPV": round(epv, 1),
        "EPV_adequate": "Yes" if epv >= 10 else "No (< 10)",
    }
    return pd.DataFrame([result])


def target_distribution(df):
    """Original target variable distribution."""
    if cfg.LABEL_COL not in df.columns:
        return pd.DataFrame()
    return df[cfg.LABEL_COL].value_counts().reset_index()


def main():
    cfg.EXPLORATION_RESULTS.mkdir(parents=True, exist_ok=True)

    df = load_data()

    basic_info(df).to_csv(cfg.EXPLORATION_RESULTS / "basic_info.csv", index=False)
    missing_analysis(df).to_csv(cfg.EXPLORATION_RESULTS / "missing_analysis.csv")
    epv_check(df).to_csv(cfg.EXPLORATION_RESULTS / "epv_check.csv", index=False)
    target_distribution(df).to_csv(cfg.EXPLORATION_RESULTS / "target_distribution.csv", index=False)

    # Numeric summary
    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    if numeric_cols:
        df[numeric_cols].describe().to_csv(cfg.EXPLORATION_RESULTS / "numeric_summary.csv")

    print(f"\nPhase 1 complete. Results in {cfg.EXPLORATION_RESULTS}/")
    print("--- Checkpoint ---")
    print("[ ] Sample size adequate per Riley criteria? (MLGG-Z01)")
    print("[ ] Cohort exclusions documented? (MLGG-C01)")
    print("[ ] Prediction time point defined? (MLGG-F05)")


if __name__ == "__main__":
    main()
