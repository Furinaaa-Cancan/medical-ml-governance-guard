"""
05_modeling/scripts/train_models.py
====================================
Phase 5: Model Training
- Compare ≥3 model families (MLGG-M03): LR, RF, XGBoost, LightGBM
- Hyperparameter tuning on validation set — NEVER test set (MLGG-M01)
- Threshold selection on validation set via Youden's J (MLGG-M02)
- Set random_state everywhere (MLGG-R01)
- NO test set usage in this phase

输出 → 05_modeling/results/
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

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.metrics import (
    roc_auc_score, average_precision_score, brier_score_loss,
    roc_curve, precision_recall_curve,
    classification_report,
)

warnings.filterwarnings("ignore")

# Try importing optional models
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


def load_selected_data():
    """加载 Phase 4 筛选后的数据。"""
    feat_dir = os.path.join(config.PROJECT_ROOT, "04_feature_selection", "results")
    data = np.load(os.path.join(feat_dir, "selected_data.npz"))
    with open(os.path.join(feat_dir, "selected_features.json")) as f:
        feat_info = json.load(f)
    return (
        data["X_train"], data["y_train"],
        data["X_valid"], data["y_valid"],
        data["X_test"], data["y_test"],
        feat_info["selected_features"],
    )


def define_model_configs():
    """
    定义模型族和超参搜索空间。
    每个模型多组超参，在 validation set 上选最优。
    偏向更强正则化的配置以控制过拟合。
    """
    models = {}

    # 1. Logistic Regression (baseline)
    models["LR"] = [
        {"C": 0.001, "penalty": "l2", "solver": "lbfgs", "max_iter": 5000,
         "class_weight": "balanced", "random_state": config.RANDOM_STATE},
        {"C": 0.01, "penalty": "l2", "solver": "lbfgs", "max_iter": 5000,
         "class_weight": "balanced", "random_state": config.RANDOM_STATE},
        {"C": 0.1, "penalty": "l2", "solver": "lbfgs", "max_iter": 5000,
         "class_weight": "balanced", "random_state": config.RANDOM_STATE},
        {"C": 1.0, "penalty": "l2", "solver": "lbfgs", "max_iter": 5000,
         "class_weight": "balanced", "random_state": config.RANDOM_STATE},
    ]

    # 2. Random Forest — 限制深度和叶节点，防止过拟合
    models["RF"] = [
        {"n_estimators": 300, "max_depth": 4, "min_samples_leaf": 50,
         "max_features": "sqrt", "class_weight": "balanced",
         "random_state": config.RANDOM_STATE, "n_jobs": -1},
        {"n_estimators": 300, "max_depth": 5, "min_samples_leaf": 30,
         "max_features": "sqrt", "class_weight": "balanced",
         "random_state": config.RANDOM_STATE, "n_jobs": -1},
        {"n_estimators": 500, "max_depth": 6, "min_samples_leaf": 30,
         "max_features": "sqrt", "class_weight": "balanced",
         "random_state": config.RANDOM_STATE, "n_jobs": -1},
        {"n_estimators": 500, "max_depth": 6, "min_samples_leaf": 50,
         "max_features": 0.5, "class_weight": "balanced",
         "random_state": config.RANDOM_STATE, "n_jobs": -1},
    ]

    # 3. XGBoost — 更强正则化 (higher reg_alpha/lambda, lower lr, shallower)
    if HAS_XGB:
        models["XGBoost"] = [
            {"n_estimators": 200, "max_depth": 3, "learning_rate": 0.05,
             "subsample": 0.7, "colsample_bytree": 0.7,
             "reg_alpha": 0.5, "reg_lambda": 2.0, "min_child_weight": 10,
             "random_state": config.RANDOM_STATE, "eval_metric": "logloss",
             "use_label_encoder": False},
            {"n_estimators": 300, "max_depth": 3, "learning_rate": 0.03,
             "subsample": 0.7, "colsample_bytree": 0.7,
             "reg_alpha": 1.0, "reg_lambda": 3.0, "min_child_weight": 20,
             "random_state": config.RANDOM_STATE, "eval_metric": "logloss",
             "use_label_encoder": False},
            {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05,
             "subsample": 0.7, "colsample_bytree": 0.7,
             "reg_alpha": 0.5, "reg_lambda": 2.0, "min_child_weight": 10,
             "random_state": config.RANDOM_STATE, "eval_metric": "logloss",
             "use_label_encoder": False},
            {"n_estimators": 500, "max_depth": 4, "learning_rate": 0.02,
             "subsample": 0.6, "colsample_bytree": 0.6,
             "reg_alpha": 1.0, "reg_lambda": 5.0, "min_child_weight": 30,
             "random_state": config.RANDOM_STATE, "eval_metric": "logloss",
             "use_label_encoder": False},
        ]

    # 4. LightGBM — 更强正则化
    if HAS_LGBM:
        models["LightGBM"] = [
            {"n_estimators": 200, "max_depth": 3, "learning_rate": 0.05,
             "subsample": 0.7, "colsample_bytree": 0.7,
             "reg_alpha": 0.5, "reg_lambda": 2.0, "min_child_samples": 50,
             "class_weight": "balanced", "random_state": config.RANDOM_STATE,
             "verbose": -1},
            {"n_estimators": 300, "max_depth": 3, "learning_rate": 0.03,
             "subsample": 0.7, "colsample_bytree": 0.7,
             "reg_alpha": 1.0, "reg_lambda": 3.0, "min_child_samples": 80,
             "class_weight": "balanced", "random_state": config.RANDOM_STATE,
             "verbose": -1},
            {"n_estimators": 300, "max_depth": 4, "learning_rate": 0.05,
             "subsample": 0.7, "colsample_bytree": 0.7,
             "reg_alpha": 0.5, "reg_lambda": 2.0, "min_child_samples": 50,
             "class_weight": "balanced", "random_state": config.RANDOM_STATE,
             "verbose": -1},
            {"n_estimators": 500, "max_depth": 4, "learning_rate": 0.02,
             "subsample": 0.6, "colsample_bytree": 0.6,
             "reg_alpha": 1.0, "reg_lambda": 5.0, "min_child_samples": 100,
             "class_weight": "balanced", "random_state": config.RANDOM_STATE,
             "verbose": -1},
        ]

    return models


def get_model_class(name):
    """根据名称返回模型类。"""
    mapping = {
        "LR": LogisticRegression,
        "RF": RandomForestClassifier,
        "XGBoost": XGBClassifier if HAS_XGB else None,
        "LightGBM": LGBMClassifier if HAS_LGBM else None,
    }
    return mapping.get(name)


def compute_scale_pos_weight(y_train):
    """计算正负类比例，用于 XGBoost。"""
    n_neg = (y_train == 0).sum()
    n_pos = (y_train == 1).sum()
    return n_neg / n_pos if n_pos > 0 else 1.0


def find_optimal_threshold(y_true, y_prob):
    """
    在 validation set 上用 Youden's J statistic 选最优阈值 (MLGG-M02)。
    J = sensitivity + specificity - 1
    """
    fpr, tpr, thresholds = roc_curve(y_true, y_prob)
    j_scores = tpr - fpr
    best_idx = np.argmax(j_scores)
    return thresholds[best_idx], j_scores[best_idx]


def evaluate_on_validation(y_true, y_prob, threshold):
    """在 validation set 上计算指标（用于模型选择，非最终评估）。"""
    y_pred = (y_prob >= threshold).astype(int)
    auroc = roc_auc_score(y_true, y_prob)
    auprc = average_precision_score(y_true, y_prob)
    brier = brier_score_loss(y_true, y_prob)

    tp = ((y_pred == 1) & (y_true == 1)).sum()
    fp = ((y_pred == 1) & (y_true == 0)).sum()
    tn = ((y_pred == 0) & (y_true == 0)).sum()
    fn = ((y_pred == 0) & (y_true == 1)).sum()

    sensitivity = tp / (tp + fn) if (tp + fn) > 0 else 0
    specificity = tn / (tn + fp) if (tn + fp) > 0 else 0
    ppv = tp / (tp + fp) if (tp + fp) > 0 else 0
    npv = tn / (tn + fn) if (tn + fn) > 0 else 0
    f1 = 2 * tp / (2 * tp + fp + fn) if (2 * tp + fp + fn) > 0 else 0

    return {
        "AUROC": round(auroc, 4),
        "AUPRC": round(auprc, 4),
        "Brier": round(brier, 4),
        "Sensitivity": round(sensitivity, 4),
        "Specificity": round(specificity, 4),
        "PPV": round(ppv, 4),
        "NPV": round(npv, 4),
        "F1": round(f1, 4),
        "threshold": round(threshold, 4),
    }


def bootstrap_optimism(model_class, params, X_train, y_train, n_boot=100,
                       random_state=42):
    """
    Bootstrap optimism correction (Steyerberg 2019, Harrell 2015).
    1. Fit model on full training set → apparent AUROC
    2. For each bootstrap resample:
       a. Fit model on bootstrap sample → apparent_boot
       b. Evaluate on original training set → test_boot
       c. optimism_i = apparent_boot - test_boot
    3. corrected_AUROC = apparent - mean(optimism)

    Returns (optimism_estimate, corrected_auroc, apparent_auroc).
    """
    rng = np.random.RandomState(random_state)
    n = len(y_train)

    # Apparent performance
    model_full = model_class(**params)
    model_full.fit(X_train, y_train)
    apparent = roc_auc_score(y_train, model_full.predict_proba(X_train)[:, 1])

    optimisms = []
    for b in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        X_boot, y_boot = X_train[idx], y_train[idx]

        # Skip if only one class in bootstrap sample
        if len(np.unique(y_boot)) < 2:
            continue

        model_boot = model_class(**params)
        model_boot.fit(X_boot, y_boot)

        apparent_boot = roc_auc_score(y_boot, model_boot.predict_proba(X_boot)[:, 1])
        test_boot = roc_auc_score(y_train, model_boot.predict_proba(X_train)[:, 1])
        optimisms.append(apparent_boot - test_boot)

    optimism = np.mean(optimisms) if optimisms else 0.0
    corrected = apparent - optimism
    return optimism, corrected, apparent


def train_and_select(model_configs, X_train, y_train, X_valid, y_valid):
    """
    训练所有模型配置，选择逻辑：
    - 主标准：validation AUROC（无偏估计，Yang et al. KDD 2023）
    - gap 仅作为诊断信号记录，不参与选择（Steyerberg 2019, Harrell 2015）
    - 对每个模型族的最优配置做 bootstrap optimism correction 作为内部验证
    """
    scale_pos_weight = compute_scale_pos_weight(y_train)
    all_results = []
    best_models = {}

    for model_name, param_list in model_configs.items():
        model_class = get_model_class(model_name)
        if model_class is None:
            print(f"  Skipping {model_name} (not installed)")
            continue

        print(f"\n  Training {model_name} ({len(param_list)} configs)...")
        candidates = []

        for i, params in enumerate(param_list):
            if model_name == "XGBoost":
                params = {**params, "scale_pos_weight": scale_pos_weight}

            model = model_class(**params)
            model.fit(X_train, y_train)

            y_prob_valid = model.predict_proba(X_valid)[:, 1]
            threshold, j_stat = find_optimal_threshold(y_valid, y_prob_valid)
            metrics = evaluate_on_validation(y_valid, y_prob_valid, threshold)

            # Train AUROC for diagnostic gap
            y_prob_train = model.predict_proba(X_train)[:, 1]
            train_auroc = roc_auc_score(y_train, y_prob_train)
            gap = train_auroc - metrics["AUROC"]

            result = {
                "model": model_name,
                "config_id": i,
                "params": str(params),
                "train_AUROC": round(train_auroc, 4),
                **metrics,
                "train_valid_gap": round(gap, 4),
            }
            all_results.append(result)

            candidate = {
                "model": model,
                "params": params,
                "threshold": threshold,
                "metrics": metrics,
                "config_id": i,
                "gap": gap,
                "train_auroc": train_auroc,
            }
            candidates.append(candidate)

            print(f"    config {i}: valid_AUROC={metrics['AUROC']:.4f} (train={train_auroc:.4f}, gap={gap:.4f})")

        # Select by validation AUROC — the unbiased estimate
        best = max(candidates, key=lambda c: c["metrics"]["AUROC"])
        print(f"    → Selected config {best['config_id']} (best validation AUROC={best['metrics']['AUROC']:.4f})")
        best_models[model_name] = best

    return all_results, best_models


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    print("Loading selected features data...")
    X_train, y_train, X_valid, y_valid, X_test, y_test, feature_names = load_selected_data()
    print(f"  Train: {X_train.shape}, Valid: {X_valid.shape}, Test: {X_test.shape}")
    print(f"  Features: {len(feature_names)}")
    print(f"  Available models: LR, RF" +
          (", XGBoost" if HAS_XGB else "") +
          (", LightGBM" if HAS_LGBM else ""))

    # Define and train models
    model_configs = define_model_configs()
    print(f"\n{'='*60}")
    print("TRAINING (tuning on validation set — MLGG-M01)")
    print(f"{'='*60}")

    all_results, best_models = train_and_select(
        model_configs, X_train, y_train, X_valid, y_valid
    )

    # Save all results
    results_df = pd.DataFrame(all_results)
    results_df.to_csv(os.path.join(results_dir, "all_tuning_results.csv"), index=False)

    # Summary of best per family
    print(f"\n{'='*60}")
    print("BEST MODEL PER FAMILY (validation set)")
    print(f"{'='*60}")

    summary_records = []
    for model_name, info in sorted(best_models.items(), key=lambda x: -x[1]["metrics"]["AUROC"]):
        m = info["metrics"]
        print(f"\n  {model_name} (config {info['config_id']}):")
        print(f"    AUROC={m['AUROC']:.4f}  AUPRC={m['AUPRC']:.4f}  Brier={m['Brier']:.4f}")
        print(f"    Sens={m['Sensitivity']:.4f}  Spec={m['Specificity']:.4f}  PPV={m['PPV']:.4f}  NPV={m['NPV']:.4f}  F1={m['F1']:.4f}")
        print(f"    Threshold={m['threshold']:.4f} (Youden's J)")

        summary_records.append({
            "model": model_name,
            "config_id": info["config_id"],
            **m,
        })

    summary_df = pd.DataFrame(summary_records)
    summary_df.to_csv(os.path.join(results_dir, "best_per_family.csv"), index=False)

    # Select overall best model
    overall_best_name = max(best_models, key=lambda x: best_models[x]["metrics"]["AUROC"])
    overall_best = best_models[overall_best_name]

    print(f"\n{'='*60}")
    print(f"OVERALL BEST: {overall_best_name}")
    print(f"{'='*60}")

    # Save best model, threshold, and validation predictions
    joblib.dump(overall_best["model"], os.path.join(config.MODEL_DIR, "best_model.pkl"))

    best_info = {
        "model_name": overall_best_name,
        "config_id": overall_best["config_id"],
        "threshold": overall_best["threshold"],
        "params": str(overall_best["params"]),
        "validation_metrics": overall_best["metrics"],
    }
    with open(os.path.join(results_dir, "best_model_info.json"), "w") as f:
        json.dump(best_info, f, indent=2)

    # Save all best models (for ensemble or comparison in Phase 6)
    for name, info in best_models.items():
        joblib.dump(info["model"], os.path.join(config.MODEL_DIR, f"{name}_best.pkl"))

    thresholds = {name: info["threshold"] for name, info in best_models.items()}
    with open(os.path.join(results_dir, "thresholds.json"), "w") as f:
        json.dump(thresholds, f, indent=2)

    # Bootstrap optimism correction for each best model
    # Steyerberg 2019 Ch.17, Harrell 2015: recommended internal validation
    print(f"\n{'='*60}")
    print("BOOTSTRAP OPTIMISM CORRECTION (100 resamples)")
    print(f"{'='*60}")

    scale_pos_weight = compute_scale_pos_weight(y_train)
    bootstrap_records = []
    for name, info in sorted(best_models.items(), key=lambda x: -x[1]["metrics"]["AUROC"]):
        model_class = get_model_class(name)
        params = info["params"]
        if name == "XGBoost":
            params = {**params, "scale_pos_weight": scale_pos_weight}

        print(f"\n  {name}...", end=" ", flush=True)
        optimism, corrected, apparent = bootstrap_optimism(
            model_class, params, X_train, y_train,
            n_boot=100, random_state=config.RANDOM_STATE,
        )
        valid_auroc = info["metrics"]["AUROC"]
        print(f"done")
        print(f"    Apparent (train):                {apparent:.4f}")
        print(f"    Optimism estimate:               {optimism:.4f}")
        print(f"    Corrected (apparent - optimism): {corrected:.4f}")
        print(f"    Validation AUROC:                {valid_auroc:.4f}")
        print(f"    |Corrected - Valid|:             {abs(corrected - valid_auroc):.4f}")

        bootstrap_records.append({
            "model": name,
            "apparent_auroc": round(apparent, 4),
            "optimism": round(optimism, 4),
            "corrected_auroc": round(corrected, 4),
            "validation_auroc": round(valid_auroc, 4),
            "corrected_valid_diff": round(abs(corrected - valid_auroc), 4),
        })

    bootstrap_df = pd.DataFrame(bootstrap_records)
    bootstrap_df.to_csv(os.path.join(results_dir, "bootstrap_optimism.csv"), index=False)

    # Verification
    print(f"\n{'='*60}")
    print("VERIFICATION")
    print(f"{'='*60}")
    print(f"✅ [MLGG-M01] Hyperparameter tuning on validation set only — test set not touched")
    print(f"✅ [MLGG-M02] Threshold selected on validation set (Youden's J)")
    print(f"✅ [MLGG-M03] Compared {len(best_models)} model families")
    print(f"✅ [MLGG-R01] random_state={config.RANDOM_STATE} set for all models")
    print(f"✅ Model selection by validation AUROC (Yang et al. KDD 2023)")
    print(f"✅ Bootstrap optimism correction completed (Steyerberg 2019, Harrell 2015)")

    # Gap diagnostic (for reporting only — not a selection criterion)
    print(f"\n  Train-valid gap diagnostic (reporting only, not selection criterion):")
    for name, info in best_models.items():
        print(f"    {name}: gap={info['gap']:.4f}")

    print(f"\n✅ Phase 5 results saved to: {results_dir}")
    print(f"✅ Models saved to: {config.MODEL_DIR}")


if __name__ == "__main__":
    main()
