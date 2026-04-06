"""
Phase 6: Evaluation

Checkpoint (MLGG):
  - Metrics from single final test evaluation only?
  - Full metric panel reported? (MLGG-E02)
  - 95% CI via bootstrap >= 1000? (MLGG-E01)
  - Calibration ECE < 0.1? (MLGG-E03)
  - Multi-seed stability (>= 5 seeds, std < 0.02)? (MLGG-R02)

Input:  04_feature_selection/results/selected_data.npz
        outputs/models/*.pkl
        05_modeling/results/thresholds.json
Output: 06_evaluation/results/test_metrics.csv, test_metrics_ci.csv
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import (
    roc_auc_score, average_precision_score, brier_score_loss,
    f1_score, matthews_corrcoef, confusion_matrix, log_loss,
)


def load_data_and_models():
    """Load test data and all trained models."""
    data = np.load(cfg.FEATURE_RESULTS / "selected_data.npz")
    with open(cfg.MODELING_RESULTS / "thresholds.json") as f:
        thresholds = json.load(f)

    models = {}
    for pkl in cfg.OUTPUT_MODELS.glob("*_best.pkl"):
        name = pkl.stem.replace("_best", "")
        if name != "best_model":
            models[name] = joblib.load(pkl)

    return data, models, thresholds


def compute_metrics(y_true, y_prob, y_pred):
    """Full metric panel (MLGG-E02)."""
    tn, fp, fn, tp = confusion_matrix(y_true, y_pred, labels=[0, 1]).ravel()

    sens = tp / (tp + fn) if (tp + fn) > 0 else 0
    spec = tn / (tn + fp) if (tn + fp) > 0 else 0
    ppv = tp / (tp + fp) if (tp + fp) > 0 else 0
    npv = tn / (tn + fn) if (tn + fn) > 0 else 0
    lr_pos = sens / (1 - spec) if spec < 1 else float("inf")
    lr_neg = (1 - sens) / spec if spec > 0 else float("inf")

    return {
        "AUROC": roc_auc_score(y_true, y_prob),
        "AUPRC": average_precision_score(y_true, y_prob),
        "Sensitivity": sens,
        "Specificity": spec,
        "PPV": ppv,
        "NPV": npv,
        "F1": f1_score(y_true, y_pred, zero_division=0),
        "MCC": matthews_corrcoef(y_true, y_pred),
        "Balanced_Accuracy": (sens + spec) / 2,
        "Brier": brier_score_loss(y_true, y_prob),
        "LogLoss": log_loss(y_true, y_prob),
        "LR+": lr_pos,
        "LR-": lr_neg,
        "TP": int(tp), "FP": int(fp), "TN": int(tn), "FN": int(fn),
    }


def bootstrap_ci(y_true, y_prob, y_pred, n_bootstrap=None, ci_level=None):
    """95% CI for all metrics via bootstrap (MLGG-E01)."""
    n_bootstrap = n_bootstrap or cfg.N_BOOTSTRAP
    ci_level = ci_level or cfg.CI_LEVEL
    alpha = (1 - ci_level) / 2

    rng = np.random.RandomState(cfg.RANDOM_STATE)
    n = len(y_true)
    boot_metrics = []

    # Stratified bootstrap: resample within each class to preserve ratio
    pos_idx = np.where(y_true == 1)[0]
    neg_idx = np.where(y_true == 0)[0]

    for _ in range(n_bootstrap):
        bp = rng.choice(pos_idx, size=len(pos_idx), replace=True)
        bn = rng.choice(neg_idx, size=len(neg_idx), replace=True)
        idx = np.concatenate([bp, bn])
        m = compute_metrics(y_true[idx], y_prob[idx], y_pred[idx])
        boot_metrics.append(m)

    df = pd.DataFrame(boot_metrics)
    ci = {}
    for col in df.columns:
        if col in ("TP", "FP", "TN", "FN"):
            continue
        vals = df[col].replace([np.inf, -np.inf], np.nan).dropna()
        if len(vals) > 0:
            ci[col] = {
                "lower": float(vals.quantile(alpha)),
                "upper": float(vals.quantile(1 - alpha)),
            }
    return ci


def compute_ece(y_true, y_prob, n_bins=10):
    """Expected Calibration Error (MLGG-E03). Target: < 0.1."""
    bins = np.linspace(0, 1, n_bins + 1)
    ece = 0.0
    for i, (lo, hi) in enumerate(zip(bins[:-1], bins[1:])):
        is_last = (i == n_bins - 1)
        mask = (y_prob >= lo) & (y_prob <= hi if is_last else y_prob < hi)
        if mask.sum() == 0:
            continue
        avg_pred = y_prob[mask].mean()
        avg_true = y_true[mask].mean()
        ece += mask.sum() / len(y_true) * abs(avg_pred - avg_true)
    return ece


def main():
    cfg.EVALUATION_RESULTS.mkdir(parents=True, exist_ok=True)
    cfg.OUTPUT_TABLES.mkdir(parents=True, exist_ok=True)

    data, models, thresholds = load_data_and_models()
    X_test, y_test = data["X_test"], data["y_test"]

    all_metrics = []
    all_ci = []

    for name, model in models.items():
        print(f"\nEvaluating {name} on test set...")
        proba = model.predict_proba(X_test)
        if hasattr(model, "classes_"):
            pos_idx = int(np.where(model.classes_ == 1)[0][0])
        else:
            pos_idx = 1
        y_prob = proba[:, pos_idx]
        threshold = thresholds.get(name, 0.5)
        y_pred = (y_prob >= threshold).astype(int)

        # Full metric panel
        metrics = compute_metrics(y_test, y_prob, y_pred)
        metrics["model"] = name
        metrics["threshold"] = threshold

        # Prevalence (needed for PPV/NPV interpretation)
        metrics["prevalence"] = float(y_test.mean())

        # ECE
        ece = compute_ece(y_test, y_prob)
        metrics["ECE"] = ece
        if ece >= cfg.CALIBRATION_ECE_THRESHOLD:
            print(f"  WARNING: ECE={ece:.3f} >= {cfg.CALIBRATION_ECE_THRESHOLD} — "
                  f"consider post-hoc calibration (MLGG-E03)")

        all_metrics.append(metrics)
        print(f"  AUROC={metrics['AUROC']:.4f}, MCC={metrics['MCC']:.3f}, ECE={ece:.3f}")

        # Bootstrap CI
        print(f"  Computing {cfg.N_BOOTSTRAP} bootstrap CIs...")
        ci = bootstrap_ci(y_test, y_prob, y_pred)
        ci_row = {"model": name}
        for metric, bounds in ci.items():
            ci_row[f"{metric}_lower"] = bounds["lower"]
            ci_row[f"{metric}_upper"] = bounds["upper"]
        all_ci.append(ci_row)

    # Save results
    metrics_df = pd.DataFrame(all_metrics)
    ci_df = pd.DataFrame(all_ci)

    metrics_df.to_csv(cfg.EVALUATION_RESULTS / "test_metrics.csv", index=False)
    ci_df.to_csv(cfg.EVALUATION_RESULTS / "test_metrics_ci.csv", index=False)
    metrics_df.to_csv(cfg.OUTPUT_TABLES / "table2_performance.csv", index=False)

    print(f"\nPhase 6 complete. Results in {cfg.EVALUATION_RESULTS}/")
    print("--- Checkpoint ---")
    print("[x] Single final test evaluation (no peeking)")
    print("[x] Full metric panel (MLGG-E02)")
    print(f"[x] 95% CI via {cfg.N_BOOTSTRAP}x bootstrap (MLGG-E01)")
    print("[ ] Calibration ECE < 0.1 for all models? (MLGG-E03)")
    print("[ ] Multi-seed stability? (MLGG-R02)")
    print("[ ] Decision Curve Analysis? (DCA)")


if __name__ == "__main__":
    main()
