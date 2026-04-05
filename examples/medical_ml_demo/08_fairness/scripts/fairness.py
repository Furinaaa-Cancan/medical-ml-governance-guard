"""
08_fairness/scripts/fairness.py
================================
Phase 8: Fairness & Subgroup Analysis (MLGG-Q01)
- Subgroup performance by race, gender, age
- Equalized odds / demographic parity metrics
- Identify disparities

输出 → 08_fairness/results/
"""

import sys
import os
import json
import warnings
import numpy as np
import pandas as pd
import joblib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import config

from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

warnings.filterwarnings("ignore")


def load_test_with_demographics():
    """加载 test set 原始数据（含人口学特征）+ 预处理后的数据。"""
    # Raw test data for demographics
    test_raw = pd.read_csv(config.TEST_DATA)
    test_raw[config.LABEL_COL] = (test_raw[config.ORIGINAL_TARGET] == config.POSITIVE_CLASS).astype(int)

    # Processed test data for predictions
    feat_dir = os.path.join(config.PROJECT_ROOT, "04_feature_selection", "results")
    data = np.load(os.path.join(feat_dir, "selected_data.npz"))

    # Best model
    model_dir = os.path.join(config.PROJECT_ROOT, "05_modeling", "results")
    with open(os.path.join(model_dir, "best_model_info.json")) as f:
        best_info = json.load(f)
    with open(os.path.join(model_dir, "thresholds.json")) as f:
        thresholds = json.load(f)

    model = joblib.load(os.path.join(config.MODEL_DIR, f"{best_info['model_name']}_best.pkl"))

    return (
        test_raw,
        data["X_test"], data["y_test"],
        model, thresholds[best_info["model_name"]],
        best_info["model_name"],
    )


def subgroup_metrics(y_true, y_prob, threshold):
    """计算子组指标。"""
    if len(np.unique(y_true)) < 2 or len(y_true) < 20:
        return None

    y_pred = (y_prob >= threshold).astype(int)
    tp = ((y_pred == 1) & (y_true == 1)).sum()
    fp = ((y_pred == 1) & (y_true == 0)).sum()
    tn = ((y_pred == 0) & (y_true == 0)).sum()
    fn = ((y_pred == 0) & (y_true == 1)).sum()

    return {
        "n": len(y_true),
        "n_positive": int(y_true.sum()),
        "prevalence": round(y_true.mean(), 4),
        "AUROC": round(roc_auc_score(y_true, y_prob), 4),
        "AUPRC": round(average_precision_score(y_true, y_prob), 4),
        "Sensitivity": round(tp / (tp + fn), 4) if (tp + fn) > 0 else None,
        "Specificity": round(tn / (tn + fp), 4) if (tn + fp) > 0 else None,
        "PPV": round(tp / (tp + fp), 4) if (tp + fp) > 0 else None,
        "FPR": round(fp / (fp + tn), 4) if (fp + tn) > 0 else None,
        "reliable": len(y_true) >= 200,  # MLGG-Q02: flag small subgroups
    }


def analyze_subgroups(test_raw, X_test, y_test, model, threshold, group_col,
                      group_name):
    """按指定列分组分析。"""
    y_prob = model.predict_proba(X_test)[:, 1]

    records = []
    groups = test_raw[group_col].value_counts()

    for group_val in groups.index:
        mask = test_raw[group_col].values == group_val
        if mask.sum() < 20:
            continue

        metrics = subgroup_metrics(y_test[mask], y_prob[mask], threshold)
        if metrics:
            metrics["group"] = str(group_val)
            records.append(metrics)

    df = pd.DataFrame(records)
    if len(df) == 0:
        return df

    # Disparity analysis: max-min difference for each metric
    print(f"\n  {group_name} ({group_col}):")
    print(f"  {'Group':20s} {'N':>6s} {'Prev':>6s} {'AUROC':>7s} {'Sens':>6s} {'Spec':>6s} {'FPR':>6s}  {'':>12s}")
    print(f"  {'-'*72}")
    for _, row in df.iterrows():
        flag = "" if row.get("reliable", True) else "  [small sample]"
        print(f"  {str(row['group']):20s} {row['n']:6d} {row['prevalence']:6.3f} "
              f"{row['AUROC']:7.4f} {row['Sensitivity']:6.4f} {row['Specificity']:6.4f} {row['FPR']:6.4f}{flag}")

    # Disparity summary
    for metric in ["AUROC", "Sensitivity", "FPR"]:
        vals = df[metric].dropna()
        if len(vals) >= 2:
            diff = vals.max() - vals.min()
            flag = "⚠️" if diff > 0.05 else "✅"
            print(f"  {flag} {metric} disparity: {diff:.4f} (max-min)")

    return df


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    print("Loading data...")
    (test_raw, X_test, y_test, model, threshold, model_name) = load_test_with_demographics()
    print(f"  Model: {model_name}, Threshold: {threshold:.4f}")
    print(f"  Test: {len(y_test)} samples")

    print(f"\n{'='*60}")
    print("SUBGROUP ANALYSIS (MLGG-Q01)")
    print(f"{'='*60}")

    # Race
    race_df = analyze_subgroups(test_raw, X_test, y_test, model, threshold,
                                "race", "Race")
    race_df.to_csv(os.path.join(results_dir, "subgroup_race.csv"), index=False)

    # Gender
    gender_df = analyze_subgroups(test_raw, X_test, y_test, model, threshold,
                                  "gender", "Gender")
    gender_df.to_csv(os.path.join(results_dir, "subgroup_gender.csv"), index=False)

    # Age
    age_df = analyze_subgroups(test_raw, X_test, y_test, model, threshold,
                               "age", "Age")
    age_df.to_csv(os.path.join(results_dir, "subgroup_age.csv"), index=False)

    print(f"\n{'='*60}")
    print("PHASE 8 CHECKPOINT")
    print(f"{'='*60}")
    print(f"✅ [MLGG-Q01] Subgroup analysis by race, gender, age completed")
    print(f"✅ Phase 8 results saved to: {results_dir}")


if __name__ == "__main__":
    main()
