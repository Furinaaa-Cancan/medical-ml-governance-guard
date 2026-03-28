#!/usr/bin/env python3
"""
Build a "Common Practice" leaky pipeline for the deflation experiment.

Given a single CSV dataset, this script builds prediction pipelines with
configurable leakage patterns to measure how much each pattern inflates
performance compared to a fully MLGG-compliant pipeline.

The 5 leakage types are based on the most common anti-patterns detected
by MLGG lint rules (R001-R006, R013) across published medical ML code:

  L1: Preprocessing leakage — fit scaler on full data before split
  L2: Resampling leakage — apply SMOTE on full data before split
  L3: Feature selection leakage — SelectKBest on full data before split
  L4: Patient-level leakage — random split without patient grouping
  L5: Threshold leakage — optimize threshold on test set

Conditions:
  - all_leaky: All 5 leakage patterns active (Condition A)
  - clean: No leakage, MLGG-compliant (Condition B)
  - ablation_L1..L5: All leaky EXCEPT one corrected (5 ablation conditions)

Usage:
  python3 experiments/paper/build_leaky_pipeline.py \\
      --input examples/heart_disease.csv \\
      --target-col y --patient-id-col patient_id --time-col event_time \\
      --condition all_leaky --seed 42 \\
      --output-dir /tmp/paper_heart_leaky_42
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import (
    HistGradientBoostingClassifier,
    RandomForestClassifier,
)
from sklearn.feature_selection import SelectKBest, mutual_info_classif
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

try:
    from imblearn.over_sampling import SMOTE  # type: ignore
except ImportError:
    SMOTE = None  # type: ignore

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONDITIONS = {
    "all_leaky",      # All 5 leakage patterns ON
    "clean",          # All 5 leakage patterns OFF (MLGG-compliant)
    "ablation_L1",    # All leaky EXCEPT L1 corrected
    "ablation_L2",    # All leaky EXCEPT L2 corrected
    "ablation_L3",    # All leaky EXCEPT L3 corrected
    "ablation_L4",    # All leaky EXCEPT L4 corrected
    "ablation_L5",    # All leaky EXCEPT L5 corrected
}

MODEL_CANDIDATES = [
    ("logistic_l2", LogisticRegression, {"C": 1.0, "max_iter": 1000, "solver": "lbfgs"}),
    ("random_forest", RandomForestClassifier, {"n_estimators": 200, "class_weight": "balanced", "n_jobs": -1}),
    ("hist_gb", HistGradientBoostingClassifier, {"max_iter": 200, "class_weight": "balanced"}),
]


# ---------------------------------------------------------------------------
# Leakage pattern implementations
# ---------------------------------------------------------------------------

def _split_data(
    df: pd.DataFrame,
    target_col: str,
    patient_id_col: str,
    seed: int,
    *,
    patient_grouped: bool,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split data into train/valid/test (60/20/20).

    Args:
        patient_grouped: If True, split by patient (no patient in multiple sets).
                         If False, random row-level split (leaky L4 pattern).
    """
    if patient_grouped and patient_id_col in df.columns:
        # Group by patient, then split patient IDs
        patients = df[patient_id_col].unique()
        rng = np.random.default_rng(seed)
        rng.shuffle(patients)
        n = len(patients)
        n_train = int(n * 0.6)
        n_valid = int(n * 0.2)
        train_ids = set(patients[:n_train])
        valid_ids = set(patients[n_train:n_train + n_valid])
        test_ids = set(patients[n_train + n_valid:])
        train = df[df[patient_id_col].isin(train_ids)].copy()
        valid = df[df[patient_id_col].isin(valid_ids)].copy()
        test = df[df[patient_id_col].isin(test_ids)].copy()
    else:
        # Row-level random split (L4 leakage: patients can appear in multiple sets)
        train_valid, test = train_test_split(
            df, test_size=0.2, random_state=seed, stratify=df[target_col]
        )
        train, valid = train_test_split(
            train_valid, test_size=0.25, random_state=seed, stratify=train_valid[target_col]
        )
    return train.reset_index(drop=True), valid.reset_index(drop=True), test.reset_index(drop=True)


def _prepare_features(
    df: pd.DataFrame,
    target_col: str,
    ignore_cols: List[str],
) -> Tuple[pd.DataFrame, pd.Series]:
    """Extract X, y from a DataFrame."""
    drop_cols = [c for c in [target_col] + ignore_cols if c in df.columns]
    X = df.drop(columns=drop_cols)
    # Convert all to numeric
    for col in X.columns:
        X[col] = pd.to_numeric(X[col], errors="coerce")
    y = df[target_col].astype(int)
    return X, y


def run_pipeline(
    df: pd.DataFrame,
    target_col: str,
    patient_id_col: str,
    ignore_cols: List[str],
    seed: int,
    condition: str,
) -> Dict[str, Any]:
    """Run a single experiment pipeline and return metrics.

    Args:
        df: Full dataset.
        target_col: Target column name.
        patient_id_col: Patient ID column name.
        ignore_cols: Columns to exclude from features.
        seed: Random seed.
        condition: One of CONDITIONS.

    Returns:
        Dict with metrics, condition metadata, and timing.
    """
    t0 = time.time()

    # Determine which leakage patterns are active
    if condition == "clean":
        L1 = L2 = L3 = L4 = L5 = False
    elif condition == "all_leaky":
        L1 = L2 = L3 = L4 = L5 = True
    elif condition.startswith("ablation_"):
        # All leaky EXCEPT the specified one
        corrected = condition.split("_")[1]  # e.g. "L1"
        L1 = corrected != "L1"
        L2 = corrected != "L2"
        L3 = corrected != "L3"
        L4 = corrected != "L4"
        L5 = corrected != "L5"
    else:
        raise ValueError(f"Unknown condition: {condition}")

    # ── Step 1: Split ─────────────────────────────────────────────────
    patient_grouped = not L4  # L4 = patient-level leakage (no grouping)
    train, valid, test = _split_data(
        df, target_col, patient_id_col, seed, patient_grouped=patient_grouped
    )

    X_train, y_train = _prepare_features(train, target_col, ignore_cols)
    X_valid, y_valid = _prepare_features(valid, target_col, ignore_cols)
    X_test, y_test = _prepare_features(test, target_col, ignore_cols)

    # ── Step 2: Preprocessing (L1) ───────────────────────────────────
    imputer = SimpleImputer(strategy="median")
    scaler = StandardScaler()

    if L1:
        # LEAKY: fit on ALL data (train+valid+test combined)
        X_all = pd.concat([X_train, X_valid, X_test], ignore_index=True)
        imputer.fit(X_all)
        scaler.fit(imputer.transform(X_all))
    else:
        # CLEAN: fit only on train
        imputer.fit(X_train)
        scaler.fit(imputer.transform(X_train))

    X_train_imp = pd.DataFrame(imputer.transform(X_train), columns=X_train.columns)
    X_valid_imp = pd.DataFrame(imputer.transform(X_valid), columns=X_valid.columns)
    X_test_imp = pd.DataFrame(imputer.transform(X_test), columns=X_test.columns)

    X_train_sc = scaler.transform(X_train_imp)
    X_valid_sc = scaler.transform(X_valid_imp)
    X_test_sc = scaler.transform(X_test_imp)

    # ── Step 3: Resampling (L2) ──────────────────────────────────────
    if L2 and SMOTE is not None:
        # LEAKY: SMOTE on full data before split was the original pattern,
        # but since we already split, simulate by applying SMOTE to
        # train+valid+test combined, then re-split
        X_combined = np.vstack([X_train_sc, X_valid_sc, X_test_sc])
        y_combined = pd.concat([y_train, y_valid, y_test], ignore_index=True)
        try:
            sm = SMOTE(random_state=seed)
            X_resampled, y_resampled = sm.fit_resample(X_combined, y_combined)
            # After SMOTE on full data, re-split (some synthetic samples
            # will land in test — this IS the leakage)
            n_tr = len(X_train_sc)
            n_va = len(X_valid_sc)
            X_train_sc = X_resampled[:n_tr]
            y_train = pd.Series(y_resampled[:n_tr])
            X_valid_sc = X_resampled[n_tr:n_tr + n_va]
            y_valid = pd.Series(y_resampled[n_tr:n_tr + n_va])
            X_test_sc = X_resampled[n_tr + n_va:n_tr + n_va + len(X_test_sc)]
            y_test = pd.Series(y_resampled[n_tr + n_va:n_tr + n_va + len(y_test)])
        except Exception:
            pass  # If SMOTE fails (too few samples), skip
    elif not L2 and SMOTE is not None:
        # CLEAN: SMOTE only on training data
        try:
            sm = SMOTE(random_state=seed)
            X_train_sc, y_train_arr = sm.fit_resample(X_train_sc, y_train)
            y_train = pd.Series(y_train_arr)
        except Exception:
            pass

    # ── Step 4: Feature selection (L3) ───────────────────────────────
    k_features = min(10, X_train_sc.shape[1])
    if L3:
        # LEAKY: select features on ALL data
        X_all_fs = np.vstack([X_train_sc, X_valid_sc, X_test_sc])
        y_all_fs = pd.concat([y_train, y_valid, y_test], ignore_index=True)
        selector = SelectKBest(mutual_info_classif, k=k_features)
        selector.fit(X_all_fs, y_all_fs)
    else:
        # CLEAN: select features on train only
        selector = SelectKBest(mutual_info_classif, k=k_features)
        selector.fit(X_train_sc, y_train)

    X_train_fs = selector.transform(X_train_sc)
    X_valid_fs = selector.transform(X_valid_sc)
    X_test_fs = selector.transform(X_test_sc)

    # ── Step 5: Train models, select best via CV ─────────────────────
    best_model = None
    best_cv_score = -1.0
    best_name = ""
    model_results: List[Dict[str, Any]] = []

    for name, cls, params in MODEL_CANDIDATES:
        model = cls(random_state=seed, **params) if "random_state" in cls().get_params() else cls(**params)
        try:
            cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
            scores = cross_val_score(model, X_train_fs, y_train, cv=cv, scoring="roc_auc", n_jobs=-1)
            mean_cv = float(np.mean(scores))
            model_results.append({"name": name, "cv_auc_mean": round(mean_cv, 4)})
            if mean_cv > best_cv_score:
                best_cv_score = mean_cv
                best_model = model
                best_name = name
        except Exception:
            model_results.append({"name": name, "cv_auc_mean": None, "error": True})

    if best_model is None:
        return {"error": "No model converged", "condition": condition, "seed": seed}

    # Fit on training data
    best_model.fit(X_train_fs, y_train)

    # ── Step 6: Evaluate ─────────────────────────────────────────────
    def _eval(X: np.ndarray, y: pd.Series, split_name: str) -> Dict[str, Any]:
        y_score = best_model.predict_proba(X)[:, 1]
        y_pred = (y_score >= threshold).astype(int)
        try:
            auc_roc = float(roc_auc_score(y, y_score))
        except ValueError:
            auc_roc = float("nan")
        try:
            auc_pr = float(average_precision_score(y, y_score))
        except ValueError:
            auc_pr = float("nan")
        brier = float(brier_score_loss(y, y_score))
        return {
            "split": split_name,
            "auc_roc": round(auc_roc, 4),
            "auc_pr": round(auc_pr, 4),
            "brier": round(brier, 4),
            "n": len(y),
            "prevalence": round(float(y.mean()), 4),
        }

    # ── Step 6a: Threshold selection (L5) ────────────────────────────
    if L5:
        # LEAKY: optimize threshold on TEST set
        y_test_score = best_model.predict_proba(X_test_fs)[:, 1]
        fpr, tpr, thresholds = roc_curve(y_test, y_test_score)
        youden = tpr - fpr
        threshold = float(thresholds[np.argmax(youden)])
    else:
        # CLEAN: optimize threshold on VALIDATION set
        y_valid_score = best_model.predict_proba(X_valid_fs)[:, 1]
        fpr, tpr, thresholds = roc_curve(y_valid, y_valid_score)
        youden = tpr - fpr
        threshold = float(thresholds[np.argmax(youden)])

    metrics_train = _eval(X_train_fs, y_train, "train")
    metrics_valid = _eval(X_valid_fs, y_valid, "valid")
    metrics_test = _eval(X_test_fs, y_test, "test")

    elapsed = round(time.time() - t0, 2)

    return {
        "condition": condition,
        "seed": seed,
        "leakage_flags": {"L1": L1, "L2": L2, "L3": L3, "L4": L4, "L5": L5},
        "selected_model": best_name,
        "cv_auc": round(best_cv_score, 4),
        "threshold": round(threshold, 4),
        "metrics": {
            "train": metrics_train,
            "valid": metrics_valid,
            "test": metrics_test,
        },
        "model_candidates": model_results,
        "n_features_selected": k_features,
        "elapsed_seconds": elapsed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build leaky/clean pipeline for the deflation experiment."
    )
    parser.add_argument("--input", required=True, help="Path to input CSV.")
    parser.add_argument("--target-col", default="y", help="Target column name.")
    parser.add_argument("--patient-id-col", default="patient_id", help="Patient ID column.")
    parser.add_argument("--ignore-cols", default="patient_id,event_time",
                        help="Comma-separated columns to ignore.")
    parser.add_argument("--condition", required=True, choices=sorted(CONDITIONS),
                        help="Experiment condition.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--output-dir", required=True, help="Output directory.")

    args = parser.parse_args()

    df = pd.read_csv(args.input)
    ignore_cols = [c.strip() for c in args.ignore_cols.split(",") if c.strip()]

    result = run_pipeline(
        df=df,
        target_col=args.target_col,
        patient_id_col=args.patient_id_col,
        ignore_cols=ignore_cols,
        seed=args.seed,
        condition=args.condition,
    )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"result_{args.condition}_seed{args.seed}.json"
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    print(f"Result: {out_path}")

    if "error" in result:
        print(f"  ERROR: {result['error']}")
        return 2

    test_auc = result["metrics"]["test"]["auc_roc"]
    print(f"  Condition: {args.condition}")
    print(f"  Model: {result['selected_model']}")
    print(f"  Test AUC: {test_auc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
