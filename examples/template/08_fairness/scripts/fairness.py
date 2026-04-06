"""
Phase 8: Fairness

Checkpoint (MLGG):
  - Subgroup analysis by sex, age, race? (MLGG-Q01)
  - Subgroup metrics include bootstrap CI? (MLGG-Q02)
  - Subgroups with n < 200 flagged as unreliable?

Input:  02_splitting/results/test.csv (demographics)
        04_feature_selection/results/selected_data.npz
        outputs/models/best_model.pkl
        05_modeling/results/thresholds.json
Output: 08_fairness/results/subgroup_*.csv
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import roc_auc_score, recall_score


def load_test_with_demographics():
    """Load test set with demographic columns for fairness analysis."""
    test_raw = pd.read_csv(cfg.SPLIT_RESULTS / "test.csv")
    data = np.load(cfg.FEATURE_RESULTS / "selected_data.npz")
    model = joblib.load(cfg.OUTPUT_MODELS / "best_model.pkl")

    with open(cfg.MODELING_RESULTS / "thresholds.json") as f:
        thresholds = json.load(f)
    with open(cfg.MODELING_RESULTS / "best_model_info.json") as f:
        best_info = json.load(f)

    threshold = thresholds[best_info["best_model"]]

    X_test, y_test = data["X_test"], data["y_test"]
    proba = model.predict_proba(X_test)
    pos_idx = int(np.where(model.classes_ == 1)[0][0]) if hasattr(model, "classes_") else 1
    y_prob = proba[:, pos_idx]
    y_pred = (y_prob >= threshold).astype(int)

    # Align by patient ID to avoid index mismatch
    if len(test_raw) != len(y_test):
        print(f"WARNING: test_raw ({len(test_raw)} rows) != y_test ({len(y_test)} rows). "
              f"Demographics may be misaligned. Using first {len(y_test)} rows.")
        test_raw = test_raw.iloc[:len(y_test)].reset_index(drop=True)

    return test_raw, y_test, y_prob, y_pred


MIN_SUBGROUP_N = 200  # Convention — CI becomes wide below this


def subgroup_metrics(y_true, y_prob, y_pred, group_name):
    """Compute metrics for a subgroup with bootstrap CI (MLGG-Q02)."""
    n = len(y_true)
    if n < 20:
        return {"group": group_name, "n": n, "note": "too_few_samples"}

    result = {"group": group_name, "n": n}
    result["positive_rate"] = round(float(y_true.mean()), 4)

    if len(np.unique(y_true)) == 2:
        auroc = roc_auc_score(y_true, y_prob)
        result["AUROC"] = round(auroc, 4)

        # Bootstrap CI for AUROC (MLGG-Q02)
        rng = np.random.RandomState(cfg.RANDOM_STATE)
        boot_aucs = []
        pos = np.where(y_true == 1)[0]
        neg = np.where(y_true == 0)[0]
        if len(pos) >= 2 and len(neg) >= 2:
            for _ in range(cfg.N_BOOTSTRAP):
                idx = np.concatenate([
                    rng.choice(pos, size=len(pos), replace=True),
                    rng.choice(neg, size=len(neg), replace=True),
                ])
                boot_aucs.append(roc_auc_score(y_true[idx], y_prob[idx]))
        if boot_aucs:
            result["AUROC_lower"] = round(float(np.percentile(boot_aucs, 2.5)), 4)
            result["AUROC_upper"] = round(float(np.percentile(boot_aucs, 97.5)), 4)

    result["Sensitivity"] = round(recall_score(y_true, y_pred, zero_division=0), 4)
    result["FPR"] = round(float(((y_pred == 1) & (y_true == 0)).sum() /
                          max((y_true == 0).sum(), 1)), 4)

    if n < MIN_SUBGROUP_N:
        result["reliability"] = f"UNRELIABLE (n={n} < {MIN_SUBGROUP_N})"
    else:
        result["reliability"] = "OK"

    return result


def analyze_by_column(test_raw, y_test, y_prob, y_pred, col):
    """Run subgroup analysis for a demographic column."""
    if col not in test_raw.columns:
        print(f"  Column '{col}' not found, skipping")
        return pd.DataFrame()

    results = []
    for group_val in test_raw[col].dropna().unique():
        mask = (test_raw[col] == group_val).values[:len(y_test)]
        if mask.sum() == 0:
            continue
        m = subgroup_metrics(
            y_test[mask], y_prob[mask], y_pred[mask],
            group_name=str(group_val),
        )
        results.append(m)

    return pd.DataFrame(results)


def main():
    cfg.FAIRNESS_RESULTS.mkdir(parents=True, exist_ok=True)

    test_raw, y_test, y_prob, y_pred = load_test_with_demographics()

    # TODO: Update these column names for your dataset
    demographic_cols = {
        "race": "race",       # Column name for race/ethnicity
        "gender": "gender",   # Column name for sex/gender
        "age": "age_group",   # Column name for age groups
    }

    for label, col in demographic_cols.items():
        print(f"\nSubgroup analysis: {label} ({col})")
        df = analyze_by_column(test_raw, y_test, y_prob, y_pred, col)
        if not df.empty:
            df.to_csv(cfg.FAIRNESS_RESULTS / f"subgroup_{label}.csv", index=False)
            print(df.to_string(index=False))

    print(f"\nPhase 8 complete. Results in {cfg.FAIRNESS_RESULTS}/")
    print("--- Checkpoint ---")
    print("[ ] Subgroup analysis by sex, age, race? (MLGG-Q01)")
    print("[ ] Subgroup metrics include bootstrap CI? (MLGG-Q02)")
    print("[ ] Disparities discussed with clinical implications?")


if __name__ == "__main__":
    main()
