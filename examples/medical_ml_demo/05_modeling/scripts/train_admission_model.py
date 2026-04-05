"""
05_modeling/scripts/train_admission_model.py
=============================================
Model A: Admission-time model (MLGG-F02 compliant)
Uses ONLY features available at the time of admission.
Compares with Model B (discharge-time, full features) to quantify
the contribution of discharge-time information.

This directly addresses TRIPOD+AI Item 4b: prediction time point.
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

from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss, roc_curve
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier

warnings.filterwarnings("ignore")

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False

try:
    from lightgbm import LGBMClassifier
    HAS_LGBM = True
except ImportError:
    HAS_LGBM = False


def load_data():
    """加载预处理后的数据，并识别 admission-time 特征的索引。"""
    feat_dir = os.path.join(config.PROJECT_ROOT, "04_feature_selection", "results")
    data = np.load(os.path.join(feat_dir, "selected_data.npz"))
    with open(os.path.join(feat_dir, "selected_features.json")) as f:
        feat_info = json.load(f)

    feature_names = feat_info["selected_features"]

    # Identify admission-time feature indices using group mapping from Phase 4
    # This avoids fragile startswith() matching
    group_map_path = os.path.join(feat_dir, "group_selection_summary.csv")
    admission_set = set(config.ADMISSION_TIME_FEATURES)
    # Also include missing indicators for admission-time features
    for f in config.ADMISSION_TIME_FEATURES:
        admission_set.add(f + "_missing")

    admission_indices = []
    admission_names = []
    for i, name in enumerate(feature_names):
        # Determine which original variable this feature belongs to
        # by matching against known admission feature names/prefixes
        matched = False
        for adm_feat in admission_set:
            # Exact match (e.g., "age", "number_inpatient", "weight_missing")
            if name == adm_feat:
                matched = True
                break
            # OneHot prefix match with underscore boundary
            # e.g., "diag_1_circulatory" matches "diag_1" + "_"
            if name.startswith(adm_feat + "_"):
                matched = True
                break
        if matched:
            admission_indices.append(i)
            admission_names.append(name)

    return (
        data["X_train"], data["y_train"],
        data["X_valid"], data["y_valid"],
        data["X_test"], data["y_test"],
        feature_names,
        admission_indices, admission_names,
    )


def find_optimal_threshold(y_true, y_prob):
    fpr, tpr, thresholds = roc_curve(y_true, y_prob)
    j_scores = tpr - fpr
    best_idx = np.argmax(j_scores)
    return thresholds[best_idx]


def train_and_evaluate(X_train, y_train, X_valid, y_valid, X_test, y_test, label):
    """Train best config per family, evaluate on test."""
    scale_pos_weight = (y_train == 0).sum() / max((y_train == 1).sum(), 1)

    models_configs = {
        "LR": LogisticRegression(C=0.01, penalty="l2", solver="lbfgs", max_iter=5000,
                                  class_weight="balanced", random_state=config.RANDOM_STATE),
        "RF": RandomForestClassifier(n_estimators=500, max_depth=6, min_samples_leaf=50,
                                      max_features=0.5, class_weight="balanced",
                                      random_state=config.RANDOM_STATE, n_jobs=-1),
    }
    if HAS_XGB:
        models_configs["XGBoost"] = XGBClassifier(
            n_estimators=500, max_depth=4, learning_rate=0.02,
            subsample=0.6, colsample_bytree=0.6,
            reg_alpha=1.0, reg_lambda=5.0, min_child_weight=30,
            scale_pos_weight=scale_pos_weight,
            random_state=config.RANDOM_STATE, eval_metric="logloss",
            use_label_encoder=False)
    if HAS_LGBM:
        models_configs["LightGBM"] = LGBMClassifier(
            n_estimators=300, max_depth=3, learning_rate=0.03,
            subsample=0.7, colsample_bytree=0.7,
            reg_alpha=1.0, reg_lambda=3.0, min_child_samples=80,
            class_weight="balanced", random_state=config.RANDOM_STATE,
            verbose=-1)

    results = []
    for name, model in models_configs.items():
        model.fit(X_train, y_train)
        y_prob_valid = model.predict_proba(X_valid)[:, 1]
        y_prob_test = model.predict_proba(X_test)[:, 1]
        threshold = find_optimal_threshold(y_valid, y_prob_valid)

        valid_auroc = roc_auc_score(y_valid, y_prob_valid)
        test_auroc = roc_auc_score(y_test, y_prob_test)
        test_auprc = average_precision_score(y_test, y_prob_test)

        results.append({
            "scenario": label,
            "model": name,
            "valid_AUROC": round(valid_auroc, 4),
            "test_AUROC": round(test_auroc, 4),
            "test_AUPRC": round(test_auprc, 4),
            "threshold": round(threshold, 4),
        })

    return pd.DataFrame(results)


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")

    print("Loading data...")
    (X_train, y_train, X_valid, y_valid, X_test, y_test,
     all_features, adm_idx, adm_names) = load_data()

    print(f"  All features: {len(all_features)}")
    print(f"  Admission-time features: {len(adm_idx)}")
    print(f"  Discharge-time features: {len(all_features) - len(adm_idx)}")

    # Model A: Admission-time only
    print(f"\n{'='*60}")
    print(f"MODEL A: Admission-time features only ({len(adm_idx)} features)")
    print(f"{'='*60}")
    X_tr_a = X_train[:, adm_idx]
    X_va_a = X_valid[:, adm_idx]
    X_te_a = X_test[:, adm_idx]
    results_a = train_and_evaluate(X_tr_a, y_train, X_va_a, y_valid, X_te_a, y_test,
                                    "admission_time")
    for _, r in results_a.iterrows():
        print(f"  {r['model']:10s}: valid={r['valid_AUROC']:.4f}, test={r['test_AUROC']:.4f}, AUPRC={r['test_AUPRC']:.4f}")

    # Model B: All features (discharge-time)
    print(f"\n{'='*60}")
    print(f"MODEL B: All features incl. discharge-time ({len(all_features)} features)")
    print(f"{'='*60}")
    results_b = train_and_evaluate(X_train, y_train, X_valid, y_valid, X_test, y_test,
                                    "discharge_time")
    for _, r in results_b.iterrows():
        print(f"  {r['model']:10s}: valid={r['valid_AUROC']:.4f}, test={r['test_AUROC']:.4f}, AUPRC={r['test_AUPRC']:.4f}")

    # Comparison
    print(f"\n{'='*60}")
    print("COMPARISON: Model A vs Model B")
    print(f"{'='*60}")
    all_results = pd.concat([results_a, results_b], ignore_index=True)
    all_results.to_csv(os.path.join(results_dir, "admission_vs_discharge.csv"), index=False)

    for model_name in results_a["model"].unique():
        a = results_a[results_a["model"] == model_name]["test_AUROC"].values[0]
        b = results_b[results_b["model"] == model_name]["test_AUROC"].values[0]
        diff = b - a
        print(f"  {model_name:10s}: A={a:.4f}, B={b:.4f}, diff={diff:+.4f}")

    print(f"\n  Interpretation:")
    mean_a = results_a["test_AUROC"].mean()
    mean_b = results_b["test_AUROC"].mean()
    print(f"    Mean AUROC admission-only:   {mean_a:.4f}")
    print(f"    Mean AUROC with discharge:   {mean_b:.4f}")
    print(f"    Marginal gain from discharge info: {mean_b - mean_a:+.4f}")

    # Save admission feature list
    with open(os.path.join(results_dir, "admission_features.json"), "w") as f:
        json.dump({"admission_features": adm_names, "n_features": len(adm_names)}, f, indent=2)

    print(f"\n✅ Results saved to: {results_dir}")


if __name__ == "__main__":
    main()
