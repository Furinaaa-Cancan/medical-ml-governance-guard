#!/usr/bin/env python3
"""
Threshold calibration study for covariate_shift_gate JSD thresholds.

For each dataset × seed, creates a clean train/test split and computes
per-feature JSD. This gives the empirical null distribution of JSD values
under correct splitting (no leakage). We then determine:
  1. What JSD values are "normal" for clean splits?
  2. What false positive rate does each threshold produce?
  3. Do leaky splits produce detectably higher JSD?

Usage:
  python3 experiments/paper/threshold_calibration.py
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "examples"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# --------------------------------------------------------------------------
# JSD computation (replicate covariate_shift_gate logic)
# --------------------------------------------------------------------------

MISSING_TOKENS = {"", "na", "nan", "null", "none", "n/a", "?"}
JSD_PSEUDO_COUNT = 0.5


def _is_numeric(series: pd.Series, threshold: float = 0.98) -> bool:
    non_missing = series.dropna().astype(str)
    non_missing = non_missing[~non_missing.str.strip().str.lower().isin(MISSING_TOKENS)]
    if len(non_missing) == 0:
        return False
    n_numeric = 0
    for v in non_missing:
        try:
            float(v)
            n_numeric += 1
        except (ValueError, TypeError):
            pass
    return n_numeric / len(non_missing) >= threshold


def _jsd(counts_a: np.ndarray, counts_b: np.ndarray) -> float:
    """Jensen-Shannon divergence with Laplace smoothing."""
    n_bins = len(counts_a)
    pa = (counts_a + JSD_PSEUDO_COUNT) / (counts_a.sum() + JSD_PSEUDO_COUNT * n_bins)
    pb = (counts_b + JSD_PSEUDO_COUNT) / (counts_b.sum() + JSD_PSEUDO_COUNT * n_bins)
    m = 0.5 * (pa + pb)
    kl_am = np.sum(pa * np.log(pa / m))
    kl_bm = np.sum(pb * np.log(pb / m))
    return float(0.5 * (kl_am + kl_bm))


def compute_feature_jsd(
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    ignore_cols: set,
    n_bins: int = 20,
    n_buckets: int = 64,
) -> Dict[str, float]:
    """Compute JSD per feature between train and test."""
    results = {}
    feature_cols = [c for c in train_df.columns if c not in ignore_cols]

    for col in feature_cols:
        train_vals = train_df[col].astype(str).str.strip().str.lower()
        test_vals = test_df[col].astype(str).str.strip().str.lower()

        # Remove missing
        train_clean = train_vals[~train_vals.isin(MISSING_TOKENS)]
        test_clean = test_vals[~test_vals.isin(MISSING_TOKENS)]

        if len(train_clean) < 5 or len(test_clean) < 5:
            continue

        if _is_numeric(train_df[col]):
            # Numeric: bin into n_bins
            try:
                all_vals = pd.to_numeric(
                    pd.concat([train_clean, test_clean]), errors="coerce"
                ).dropna()
                if len(all_vals) < 10:
                    continue
                bin_edges = np.linspace(all_vals.min(), all_vals.max(), n_bins + 1)
                train_num = pd.to_numeric(train_clean, errors="coerce").dropna()
                test_num = pd.to_numeric(test_clean, errors="coerce").dropna()
                counts_a = np.histogram(train_num, bins=bin_edges)[0].astype(float)
                counts_b = np.histogram(test_num, bins=bin_edges)[0].astype(float)
            except Exception:
                continue
        else:
            # Categorical: hash into buckets
            train_hashes = train_clean.apply(lambda x: hash(x) % n_buckets)
            test_hashes = test_clean.apply(lambda x: hash(x) % n_buckets)
            counts_a = np.bincount(train_hashes, minlength=n_buckets).astype(float)
            counts_b = np.bincount(test_hashes, minlength=n_buckets).astype(float)

        jsd = _jsd(counts_a, counts_b)
        results[col] = round(jsd, 6)

    return results


# --------------------------------------------------------------------------
# Dataset loading
# --------------------------------------------------------------------------

def load_dataset(name: str) -> Tuple[pd.DataFrame, str, str]:
    """Load dataset, return (df, target_col, patient_id_col)."""
    data_dir = REPO_ROOT / "examples"
    files = {
        "heart": "heart_disease.csv",
        "breast": "breast_cancer.csv",
        "pima": "pima_diabetes.csv",
        "framingham": "framingham_heart.csv",
        "diabetes130": "diabetes_130_readmission.csv",
        "ckd": "chronic_kidney_disease.csv",
    }
    path = data_dir / files[name]
    if not path.exists():
        return None, "y", "patient_id"
    df = pd.read_csv(path)
    return df, "y", "patient_id"


# --------------------------------------------------------------------------
# Main calibration
# --------------------------------------------------------------------------

SEEDS = [42, 123, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768]
DATASETS = ["heart", "breast", "pima", "framingham", "ckd"]  # skip diabetes130 (too large for quick run)
CURRENT_THRESHOLDS = {
    "high_shift_jsd": 0.12,
    "max_top_feature_jsd": 0.35,
    "max_mean_top10_jsd": 0.18,
    "max_high_shift_fraction": 0.30,
}


def run_calibration() -> Dict[str, Any]:
    results = {"clean": {}, "summary": {}}

    all_jsds_clean = []  # all per-feature JSD values across clean splits
    all_top1_clean = []  # max JSD per split
    all_top10_mean_clean = []  # mean of top-10 JSD per split
    all_high_frac_clean = []  # fraction of features with JSD > threshold

    for ds_name in DATASETS:
        df, target_col, pid_col = load_dataset(ds_name)
        if df is None:
            print(f"  {ds_name}: data not found, skipping")
            continue

        ignore_cols = {target_col, pid_col, "event_time"}
        results["clean"][ds_name] = {"seeds": {}}

        for seed in SEEDS:
            # Clean random split (no leakage)
            train_df, test_df = train_test_split(df, test_size=0.2, random_state=seed,
                                                  stratify=df[target_col])

            jsds = compute_feature_jsd(train_df, test_df, ignore_cols)

            if not jsds:
                continue

            jsd_vals = sorted(jsds.values(), reverse=True)
            top1 = jsd_vals[0]
            top10_mean = float(np.mean(jsd_vals[:10])) if len(jsd_vals) >= 10 else float(np.mean(jsd_vals))
            high_frac = sum(1 for v in jsd_vals if v > CURRENT_THRESHOLDS["high_shift_jsd"]) / len(jsd_vals)

            all_jsds_clean.extend(jsd_vals)
            all_top1_clean.append(top1)
            all_top10_mean_clean.append(top10_mean)
            all_high_frac_clean.append(high_frac)

            results["clean"][ds_name]["seeds"][str(seed)] = {
                "n_features": len(jsds),
                "max_jsd": round(top1, 6),
                "mean_top10_jsd": round(top10_mean, 6),
                "high_shift_fraction": round(high_frac, 4),
                "median_jsd": round(float(np.median(jsd_vals)), 6),
                "mean_jsd": round(float(np.mean(jsd_vals)), 6),
            }

        print(f"  {ds_name}: {len(results['clean'][ds_name]['seeds'])} seeds processed")

    # Compute null distribution statistics
    all_jsds_clean = np.array(all_jsds_clean)
    all_top1_clean = np.array(all_top1_clean)
    all_top10_mean_clean = np.array(all_top10_mean_clean)
    all_high_frac_clean = np.array(all_high_frac_clean)

    results["null_distribution"] = {
        "per_feature_jsd": {
            "n": len(all_jsds_clean),
            "mean": round(float(np.mean(all_jsds_clean)), 6),
            "std": round(float(np.std(all_jsds_clean)), 6),
            "median": round(float(np.median(all_jsds_clean)), 6),
            "p95": round(float(np.percentile(all_jsds_clean, 95)), 6),
            "p99": round(float(np.percentile(all_jsds_clean, 99)), 6),
            "max": round(float(np.max(all_jsds_clean)), 6),
        },
        "max_jsd_per_split": {
            "n": len(all_top1_clean),
            "mean": round(float(np.mean(all_top1_clean)), 6),
            "std": round(float(np.std(all_top1_clean)), 6),
            "p95": round(float(np.percentile(all_top1_clean, 95)), 6),
            "p99": round(float(np.percentile(all_top1_clean, 99)), 6),
            "max": round(float(np.max(all_top1_clean)), 6),
        },
        "mean_top10_per_split": {
            "n": len(all_top10_mean_clean),
            "mean": round(float(np.mean(all_top10_mean_clean)), 6),
            "std": round(float(np.std(all_top10_mean_clean)), 6),
            "p95": round(float(np.percentile(all_top10_mean_clean, 95)), 6),
            "p99": round(float(np.percentile(all_top10_mean_clean, 99)), 6),
            "max": round(float(np.max(all_top10_mean_clean)), 6),
        },
        "high_shift_fraction_per_split": {
            "n": len(all_high_frac_clean),
            "mean": round(float(np.mean(all_high_frac_clean)), 6),
            "std": round(float(np.std(all_high_frac_clean)), 6),
            "p95": round(float(np.percentile(all_high_frac_clean, 95)), 6),
            "p99": round(float(np.percentile(all_high_frac_clean, 99)), 6),
            "max": round(float(np.max(all_high_frac_clean)), 6),
        },
    }

    # False positive rates at current thresholds
    fpr_top1 = float(np.mean(all_top1_clean > CURRENT_THRESHOLDS["max_top_feature_jsd"]))
    fpr_top10 = float(np.mean(all_top10_mean_clean > CURRENT_THRESHOLDS["max_mean_top10_jsd"]))
    fpr_frac = float(np.mean(all_high_frac_clean > CURRENT_THRESHOLDS["max_high_shift_fraction"]))
    fpr_any_feature = float(np.mean(all_jsds_clean > CURRENT_THRESHOLDS["high_shift_jsd"]))

    results["false_positive_rates_at_current_thresholds"] = {
        "max_top_feature_jsd_0.35": {"fpr": round(fpr_top1, 4), "n": len(all_top1_clean)},
        "max_mean_top10_jsd_0.18": {"fpr": round(fpr_top10, 4), "n": len(all_top10_mean_clean)},
        "max_high_shift_fraction_0.30": {"fpr": round(fpr_frac, 4), "n": len(all_high_frac_clean)},
        "per_feature_jsd_0.12": {"fpr": round(fpr_any_feature, 4), "n": len(all_jsds_clean)},
    }

    # Suggested thresholds at various FPR levels
    for target_fpr in [0.01, 0.05, 0.10]:
        pct = (1 - target_fpr) * 100
        results[f"suggested_threshold_fpr_{int(target_fpr*100)}pct"] = {
            "max_top_feature_jsd": round(float(np.percentile(all_top1_clean, pct)), 4),
            "max_mean_top10_jsd": round(float(np.percentile(all_top10_mean_clean, pct)), 4),
            "max_high_shift_fraction": round(float(np.percentile(all_high_frac_clean, pct)), 4),
            "per_feature_jsd": round(float(np.percentile(all_jsds_clean, pct)), 4),
        }

    return results


def main() -> None:
    print("Threshold Calibration Study")
    print("=" * 60)
    print("Computing JSD null distribution from clean splits...\n")

    results = run_calibration()

    # Print summary
    null = results["null_distribution"]
    print(f"\n{'='*60}")
    print("NULL DISTRIBUTION (clean splits, no leakage)")
    print(f"{'='*60}")
    print(f"Per-feature JSD: mean={null['per_feature_jsd']['mean']:.4f}, "
          f"p95={null['per_feature_jsd']['p95']:.4f}, "
          f"p99={null['per_feature_jsd']['p99']:.4f}")
    print(f"Max JSD per split: mean={null['max_jsd_per_split']['mean']:.4f}, "
          f"p95={null['max_jsd_per_split']['p95']:.4f}, "
          f"p99={null['max_jsd_per_split']['p99']:.4f}")
    print(f"Mean top-10 JSD: mean={null['mean_top10_per_split']['mean']:.4f}, "
          f"p95={null['mean_top10_per_split']['p95']:.4f}, "
          f"p99={null['mean_top10_per_split']['p99']:.4f}")

    fpr = results["false_positive_rates_at_current_thresholds"]
    print(f"\nFALSE POSITIVE RATES AT CURRENT THRESHOLDS")
    print(f"  max_top_feature_jsd=0.35:    FPR = {fpr['max_top_feature_jsd_0.35']['fpr']:.1%}")
    print(f"  max_mean_top10_jsd=0.18:     FPR = {fpr['max_mean_top10_jsd_0.18']['fpr']:.1%}")
    print(f"  max_high_shift_fraction=0.30: FPR = {fpr['max_high_shift_fraction_0.30']['fpr']:.1%}")
    print(f"  per_feature_jsd=0.12:         FPR = {fpr['per_feature_jsd_0.12']['fpr']:.1%}")

    for target in ["01", "05", "10"]:
        key = f"suggested_threshold_fpr_{target}pct"
        if key in results:
            s = results[key]
            print(f"\n  Suggested thresholds at FPR={target}%:")
            for k, v in s.items():
                print(f"    {k}: {v}")

    out_path = OUTPUT_DIR / "threshold_calibration.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved: {out_path}")


if __name__ == "__main__":
    main()
