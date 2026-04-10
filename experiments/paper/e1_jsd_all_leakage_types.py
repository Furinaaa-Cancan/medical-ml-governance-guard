#!/usr/bin/env python3
"""
E1: JSD calibration across ALL 5 leakage types.

For each dataset × seed × leakage_type:
  - Build leaky pipeline (inject one type of leakage)
  - Compute per-feature JSD between train/test
  - Compare to clean baseline

Answers: Which leakage types produce detectable distribution shifts?

Usage:
  python3 experiments/paper/e1_jsd_all_leakage_types.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.model_selection import GroupShuffleSplit, train_test_split
from sklearn.preprocessing import StandardScaler

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "experiments/paper"))
from threshold_calibration import compute_feature_jsd, load_dataset

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
SEEDS = [42, 123, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768]
DATASETS = ["heart", "breast", "pima", "ckd"]

try:
    from imblearn.over_sampling import SMOTE
    HAS_SMOTE = True
except ImportError:
    HAS_SMOTE = False


def inject_leakage(df: pd.DataFrame, target_col: str, pid_col: str,
                   leakage_type: str, seed: int) -> tuple:
    """Inject one leakage type and return (train_df, test_df)."""
    ignore_cols = {target_col, pid_col, "event_time"}
    feature_cols = [c for c in df.columns if c not in ignore_cols]
    numeric_cols = [c for c in feature_cols if df[c].dtype in ("float64", "int64", "float32", "int32")]

    if leakage_type == "clean":
        train_df, test_df = train_test_split(
            df, test_size=0.2, random_state=seed, stratify=df[target_col]
        )
        return train_df, test_df

    elif leakage_type == "L1_preprocessing":
        # Fit scaler on full data, then split
        df_mod = df.copy()
        if numeric_cols:
            scaler = StandardScaler()
            df_mod[numeric_cols] = scaler.fit_transform(df_mod[numeric_cols].fillna(0))
        train_df, test_df = train_test_split(
            df_mod, test_size=0.2, random_state=seed, stratify=df_mod[target_col]
        )
        return train_df, test_df

    elif leakage_type == "L2_resampling":
        # SMOTE on full data before split
        if not HAS_SMOTE or len(numeric_cols) < 2:
            return None, None
        df_mod = df.copy()
        X = df_mod[numeric_cols].fillna(0).values
        y = df_mod[target_col].values
        try:
            smote = SMOTE(random_state=seed)
            X_res, y_res = smote.fit_resample(X, y)
            df_res = pd.DataFrame(X_res, columns=numeric_cols)
            df_res[target_col] = y_res
            for c in df.columns:
                if c not in df_res.columns:
                    df_res[c] = 0
            train_df, test_df = train_test_split(
                df_res, test_size=0.2, random_state=seed, stratify=df_res[target_col]
            )
            return train_df, test_df
        except Exception:
            return None, None

    elif leakage_type == "L3_feature_selection":
        # Feature selection on full data before split
        df_mod = df.copy()
        if len(numeric_cols) < 5:
            return None, None
        X = df_mod[numeric_cols].fillna(0).values
        y = df_mod[target_col].values
        k = min(5, len(numeric_cols))
        selector = SelectKBest(mutual_info_classif, k=k)
        selector.fit(X, y)
        selected = [numeric_cols[i] for i in selector.get_support(indices=True)]
        keep_cols = selected + [c for c in df.columns if c not in numeric_cols]
        df_mod = df_mod[keep_cols]
        train_df, test_df = train_test_split(
            df_mod, test_size=0.2, random_state=seed, stratify=df_mod[target_col]
        )
        return train_df, test_df

    elif leakage_type == "L4_no_grouping":
        # Random row-level split ignoring patient IDs.
        # For single-row-per-patient datasets (UCI, etc.) this is identical
        # to clean — L4 leakage only manifests in longitudinal data where
        # the same patient has multiple rows.
        df_mod = df.copy()
        if pid_col not in df_mod.columns:
            return None, None
        train_df, test_df = train_test_split(
            df_mod, test_size=0.2, random_state=seed, stratify=df_mod[target_col]
        )
        return train_df, test_df

    elif leakage_type == "L5_threshold_on_test":
        # Threshold leakage doesn't change the data split, only the evaluation
        # JSD should be identical to clean
        train_df, test_df = train_test_split(
            df, test_size=0.2, random_state=seed, stratify=df[target_col]
        )
        return train_df, test_df

    return None, None


def main() -> None:
    leakage_types = ["clean", "L1_preprocessing", "L2_resampling",
                     "L3_feature_selection", "L4_no_grouping", "L5_threshold_on_test"]

    results = {}

    for ds_name in DATASETS:
        df, target_col, pid_col = load_dataset(ds_name)
        if df is None:
            print(f"  {ds_name}: not found, skipping")
            continue

        ignore_cols = {target_col, pid_col, "event_time"}
        results[ds_name] = {}

        for ltype in leakage_types:
            jsd_maxes = []
            jsd_means = []
            jsd_medians = []
            n_processed = 0

            for seed in SEEDS:
                train_df, test_df = inject_leakage(df, target_col, pid_col, ltype, seed)
                if train_df is None:
                    continue
                jsds = compute_feature_jsd(train_df, test_df, ignore_cols)
                if not jsds:
                    continue
                vals = sorted(jsds.values(), reverse=True)
                jsd_maxes.append(vals[0])
                jsd_means.append(float(np.mean(vals)))
                jsd_medians.append(float(np.median(vals)))
                n_processed += 1

            if not jsd_maxes:
                results[ds_name][ltype] = {"n": 0, "skipped": True}
                continue

            results[ds_name][ltype] = {
                "n": n_processed,
                "max_jsd": {
                    "mean": round(float(np.mean(jsd_maxes)), 6),
                    "std": round(float(np.std(jsd_maxes)), 6),
                    "min": round(float(np.min(jsd_maxes)), 6),
                    "max": round(float(np.max(jsd_maxes)), 6),
                },
                "mean_jsd": {
                    "mean": round(float(np.mean(jsd_means)), 6),
                    "std": round(float(np.std(jsd_means)), 6),
                },
                "median_jsd": {
                    "mean": round(float(np.mean(jsd_medians)), 6),
                },
            }

        # Print per-dataset summary
        print(f"\n{'='*70}")
        print(f"Dataset: {ds_name}")
        print(f"{'Type':<25} {'N':>3} {'MaxJSD mean':>12} {'MaxJSD max':>12} {'MeanJSD':>12}")
        for ltype in leakage_types:
            r = results[ds_name].get(ltype, {})
            if r.get("skipped"):
                print(f"{ltype:<25} {'skip':>3}")
                continue
            print(f"{ltype:<25} {r['n']:>3} "
                  f"{r['max_jsd']['mean']:>12.4f} {r['max_jsd']['max']:>12.4f} "
                  f"{r['mean_jsd']['mean']:>12.4f}")

    # Discriminability summary
    print(f"\n{'='*70}")
    print("DISCRIMINABILITY: Can JSD distinguish leaky from clean?")
    print(f"{'='*70}")
    for ds_name in results:
        clean = results[ds_name].get("clean", {})
        if not clean or clean.get("skipped"):
            continue
        clean_max = clean["max_jsd"]["mean"]
        for ltype in leakage_types:
            if ltype == "clean":
                continue
            r = results[ds_name].get(ltype, {})
            if not r or r.get("skipped"):
                continue
            leak_max = r["max_jsd"]["mean"]
            delta = leak_max - clean_max
            direction = "↑ HIGHER" if delta > 0.005 else ("↓ LOWER" if delta < -0.005 else "≈ SAME")
            print(f"  {ds_name:>8} | {ltype:<25} | Δ={delta:+.4f} | {direction}")

    out = OUTPUT_DIR / "e1_jsd_all_leakage_types.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
