"""
Phase 5: Model Training

Checkpoint (MLGG):
  - Test set used for ANY selection or tuning? (MLGG-M01) — must be NO
  - Threshold selected on validation set? (MLGG-M02)
  - >= 3 model families compared? (MLGG-M03)
  - Bootstrap optimism correction computed? (MLGG-E06)

Input:  04_feature_selection/results/selected_data.npz, selected_features.json
Output: 05_modeling/results/best_model_info.json, thresholds.json
        outputs/models/*.pkl
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import numpy as np
import pandas as pd
import joblib
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, roc_curve

# Optional: tree-based boosting models
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


def load_selected():
    """Load selected features from Phase 4."""
    data = np.load(cfg.FEATURE_RESULTS / "selected_data.npz")
    with open(cfg.FEATURE_RESULTS / "selected_features.json") as f:
        feature_names = json.load(f)
    return data, feature_names


def define_models():
    """Define >= 3 model families (MLGG-M03).

    All models use random_state (MLGG-R01).
    """
    models = {
        "LR": LogisticRegression(
            C=1.0, solver="lbfgs",
            class_weight="balanced",
            random_state=cfg.RANDOM_STATE, max_iter=5000,
        ),
        "RF": RandomForestClassifier(
            n_estimators=300, max_depth=8, min_samples_leaf=20,
            class_weight="balanced",
            random_state=cfg.RANDOM_STATE, n_jobs=-1,
        ),
    }

    if HAS_XGB:
        models["XGBoost"] = XGBClassifier(
            n_estimators=200, max_depth=5, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            random_state=cfg.RANDOM_STATE, eval_metric="logloss",
        )

    if HAS_LGBM:
        models["LightGBM"] = LGBMClassifier(
            n_estimators=200, max_depth=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8,
            class_weight="balanced",
            random_state=cfg.RANDOM_STATE, verbose=-1,
        )

    if len(models) < 3:
        print(f"WARNING: Only {len(models)} model families. Install xgboost/lightgbm for MLGG-M03.")

    return models


def select_threshold(y_valid, y_prob_valid):
    """Select threshold via Youden's J on VALIDATION set (MLGG-M02)."""
    fpr, tpr, thresholds = roc_curve(y_valid, y_prob_valid)
    j_scores = tpr - fpr
    best_idx = np.argmax(j_scores)
    return float(thresholds[best_idx])


def train_and_evaluate(models, X_train, y_train, X_valid, y_valid):
    """Train all models, evaluate on VALIDATION set (never test)."""
    results = []

    for name, model in models.items():
        print(f"\nTraining {name}...")
        model.fit(X_train, y_train)

        # Evaluate on validation set (MLGG-M01: never test)
        y_prob_valid = model.predict_proba(X_valid)[:, 1]
        auc_valid = roc_auc_score(y_valid, y_prob_valid)

        # Train AUC for gap diagnostic (MLGG-E04: diagnostic only, not for selection)
        y_prob_train = model.predict_proba(X_train)[:, 1]
        auc_train = roc_auc_score(y_train, y_prob_train)

        # Threshold on validation set (MLGG-M02)
        threshold = select_threshold(y_valid, y_prob_valid)

        results.append({
            "model": name,
            "auc_train": round(auc_train, 4),
            "auc_valid": round(auc_valid, 4),
            "train_valid_gap": round(auc_train - auc_valid, 4),
            "threshold": round(threshold, 4),
        })
        print(f"  Valid AUROC={auc_valid:.4f}, Threshold={threshold:.4f}, "
              f"Gap={auc_train - auc_valid:.4f}")

    return pd.DataFrame(results)


def main():
    cfg.MODELING_RESULTS.mkdir(parents=True, exist_ok=True)
    cfg.OUTPUT_MODELS.mkdir(parents=True, exist_ok=True)

    data, feature_names = load_selected()
    X_train, y_train = data["X_train"], data["y_train"]
    X_valid, y_valid = data["X_valid"], data["y_valid"]

    models = define_models()
    results = train_and_evaluate(models, X_train, y_train, X_valid, y_valid)

    # Select best by VALIDATION performance (MLGG-M04: not by train-test gap)
    best_row = results.loc[results["auc_valid"].idxmax()]
    best_name = best_row["model"]
    print(f"\nBest model: {best_name} (Valid AUROC={best_row['auc_valid']:.4f})")

    # Save all models
    thresholds = {}
    for name, model in models.items():
        joblib.dump(model, cfg.OUTPUT_MODELS / f"{name}_best.pkl")
        row = results[results["model"] == name].iloc[0]
        thresholds[name] = row["threshold"]

    # Save best model info
    best_info = {
        "best_model": best_name,
        "auc_valid": float(best_row["auc_valid"]),
        "threshold": float(best_row["threshold"]),
        "n_models_compared": len(models),
    }
    with open(cfg.MODELING_RESULTS / "best_model_info.json", "w") as f:
        json.dump(best_info, f, indent=2)
    with open(cfg.MODELING_RESULTS / "thresholds.json", "w") as f:
        json.dump(thresholds, f, indent=2)

    results.to_csv(cfg.MODELING_RESULTS / "all_tuning_results.csv", index=False)
    joblib.dump(models[best_name], cfg.OUTPUT_MODELS / "best_model.pkl")

    print(f"\nPhase 5 complete. Results in {cfg.MODELING_RESULTS}/")
    print("--- Checkpoint ---")
    print("[x] Hyperparameter tuning on validation only (MLGG-M01)")
    print("[x] Threshold selected on validation set (MLGG-M02)")
    print(f"[{'x' if len(models) >= 3 else ' '}] >= 3 model families compared (MLGG-M03)")
    print("[x] Model selection by validation performance (MLGG-M04)")
    print("[ ] Bootstrap optimism correction? (MLGG-E06)")


if __name__ == "__main__":
    main()
