"""
06_evaluation/scripts/calibrate.py
===================================
Post-hoc probability calibration to fix ECE > 0.1.
- Platt scaling (sigmoid) fit on VALIDATION set (not test)
- Isotonic regression as alternative
- Re-evaluate calibrated models on test set
- Save calibrated models

原因：class_weight="balanced" 扭曲了概率输出，需要重新校准。
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

from sklearn.calibration import calibration_curve
from sklearn.linear_model import LogisticRegression as _LR
from sklearn.metrics import roc_auc_score, brier_score_loss

warnings.filterwarnings("ignore")


class _PlattWrapper:
    """Wraps base model + Platt scaling LR for calibrated probabilities."""
    def __init__(self, base_model, platt_lr):
        self.base_model = base_model
        self.platt_lr = platt_lr

    def predict_proba(self, X):
        raw_prob = self.base_model.predict_proba(X)[:, 1].reshape(-1, 1)
        cal_prob = self.platt_lr.predict_proba(raw_prob)
        return cal_prob

    def predict(self, X):
        return self.predict_proba(X).argmax(axis=1)


def load_data_and_models():
    feat_dir = os.path.join(config.PROJECT_ROOT, "04_feature_selection", "results")
    data = np.load(os.path.join(feat_dir, "selected_data.npz"))

    model_dir = os.path.join(config.PROJECT_ROOT, "05_modeling", "results")
    with open(os.path.join(model_dir, "thresholds.json")) as f:
        thresholds = json.load(f)

    models = {}
    for name in thresholds.keys():
        model_path = os.path.join(config.MODEL_DIR, f"{name}_best.pkl")
        if os.path.exists(model_path):
            models[name] = joblib.load(model_path)

    return (
        data["X_train"], data["y_train"],
        data["X_valid"], data["y_valid"],
        data["X_test"], data["y_test"],
        models, thresholds,
    )


def compute_ece(y_true, y_prob, n_bins=10):
    fraction_pos, mean_pred = calibration_curve(y_true, y_prob, n_bins=n_bins,
                                                 strategy="uniform")
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_counts = np.histogram(y_prob, bins=bin_edges)[0]
    total = len(y_prob)

    ece = 0.0
    for i in range(len(fraction_pos)):
        weight = bin_counts[i] / total if total > 0 else 0
        ece += abs(fraction_pos[i] - mean_pred[i]) * weight
    return ece


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")

    print("Loading data and models...")
    (X_train, y_train, X_valid, y_valid, X_test, y_test,
     models, thresholds) = load_data_and_models()

    print(f"\n{'='*70}")
    print("PROBABILITY CALIBRATION (fit on validation set)")
    print(f"{'='*70}")

    calibrated_models = {}
    records = []

    for model_name in sorted(models.keys()):
        model = models[model_name]
        print(f"\n  {model_name}:")

        # Before calibration
        y_prob_before = model.predict_proba(X_test)[:, 1]
        ece_before = compute_ece(y_test, y_prob_before)
        brier_before = brier_score_loss(y_test, y_prob_before)
        auroc_before = roc_auc_score(y_test, y_prob_before)

        # Platt scaling — fit logistic regression on validation set predictions
        # Maps uncalibrated probabilities → calibrated probabilities
        y_prob_valid = model.predict_proba(X_valid)[:, 1].reshape(-1, 1)
        platt = _LR(solver="lbfgs", max_iter=1000)
        platt.fit(y_prob_valid, y_valid)

        # Wrap as a simple calibrated model
        cal_model = _PlattWrapper(model, platt)
        y_prob_after = cal_model.predict_proba(X_test)[:, 1]
        ece_after = compute_ece(y_test, y_prob_after)
        brier_after = brier_score_loss(y_test, y_prob_after)
        auroc_after = roc_auc_score(y_test, y_prob_after)

        print(f"    Before: ECE={ece_before:.4f}, Brier={brier_before:.4f}, AUROC={auroc_before:.4f}")
        print(f"    After:  ECE={ece_after:.4f}, Brier={brier_after:.4f}, AUROC={auroc_after:.4f}")

        status = "✅" if ece_after < 0.1 else "⚠️"
        print(f"    {status} ECE: {ece_before:.4f} → {ece_after:.4f}")

        calibrated_models[model_name] = cal_model
        records.append({
            "model": model_name,
            "ECE_before": round(ece_before, 4),
            "ECE_after": round(ece_after, 4),
            "Brier_before": round(brier_before, 4),
            "Brier_after": round(brier_after, 4),
            "AUROC_before": round(auroc_before, 4),
            "AUROC_after": round(auroc_after, 4),
        })

        # Save Platt LR separately (avoids _PlattWrapper serialization issue)
        joblib.dump(platt, os.path.join(config.MODEL_DIR, f"{model_name}_platt_lr.pkl"))

    pd.DataFrame(records).to_csv(
        os.path.join(results_dir, "calibration_comparison.csv"), index=False)

    # Save calibration curves for plotting
    for model_name, cal_model in calibrated_models.items():
        y_prob = cal_model.predict_proba(X_test)[:, 1]
        frac_pos, mean_pred = calibration_curve(y_test, y_prob, n_bins=10,
                                                 strategy="uniform")
        np.savez(os.path.join(results_dir, f"{model_name}_calibrated_curve.npz"),
                 fraction_positive=frac_pos, mean_predicted=mean_pred)

    print(f"\n✅ Calibrated models saved to: {config.MODEL_DIR}")
    print(f"✅ Results saved to: {results_dir}")


if __name__ == "__main__":
    main()
