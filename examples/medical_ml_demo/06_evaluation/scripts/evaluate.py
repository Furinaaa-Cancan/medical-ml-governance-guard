"""
06_evaluation/scripts/evaluate.py
==================================
Phase 6: Final Evaluation on TEST SET (single use)
- Full metric panel: AUROC, AUPRC, Sensitivity, Specificity, PPV, NPV, F1, Brier (MLGG-E02)
- 95% CI for ALL metrics via bootstrap ≥1000 (MLGG-E01)
- Probability calibration: ECE (MLGG-E03)
- Multi-seed stability: ≥5 seeds, std < 0.02 (MLGG-R02)
- Decision Curve Analysis for clinical utility
- Train-test gap reporting (MLGG-E04, diagnostic only)

输出 → 06_evaluation/results/
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

from sklearn.metrics import (
    roc_auc_score, average_precision_score, brier_score_loss,
    roc_curve, precision_recall_curve,
)
from sklearn.calibration import calibration_curve

warnings.filterwarnings("ignore")


def load_data_and_models():
    """加载测试数据和所有最优模型。"""
    feat_dir = os.path.join(config.PROJECT_ROOT, "04_feature_selection", "results")
    data = np.load(os.path.join(feat_dir, "selected_data.npz"))
    with open(os.path.join(feat_dir, "selected_features.json")) as f:
        feat_info = json.load(f)

    model_dir = os.path.join(config.PROJECT_ROOT, "05_modeling", "results")
    with open(os.path.join(model_dir, "best_model_info.json")) as f:
        best_info = json.load(f)
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
        feat_info["selected_features"],
        models, thresholds, best_info,
    )


def compute_metrics(y_true, y_prob, threshold):
    """计算完整指标面板 (MLGG-E02)。"""
    y_pred = (y_prob >= threshold).astype(int)

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
        "AUROC": roc_auc_score(y_true, y_prob),
        "AUPRC": average_precision_score(y_true, y_prob),
        "Brier": brier_score_loss(y_true, y_prob),
        "Sensitivity": sensitivity,
        "Specificity": specificity,
        "PPV": ppv,
        "NPV": npv,
        "F1": f1,
    }


def bootstrap_ci(y_true, y_prob, threshold, n_boot=1000, ci=0.95,
                  random_state=42):
    """
    Bootstrap 95% CI for all metrics (MLGG-E01).
    """
    rng = np.random.RandomState(random_state)
    n = len(y_true)
    all_metrics = []

    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        y_t = y_true[idx]
        y_p = y_prob[idx]

        if len(np.unique(y_t)) < 2:
            continue

        m = compute_metrics(y_t, y_p, threshold)
        all_metrics.append(m)

    df = pd.DataFrame(all_metrics)
    alpha = (1 - ci) / 2
    result = {}
    for col in df.columns:
        lo = df[col].quantile(alpha)
        hi = df[col].quantile(1 - alpha)
        mean = df[col].mean()
        result[col] = {"mean": mean, "ci_lo": lo, "ci_hi": hi}
    return result


def compute_ece(y_true, y_prob, n_bins=10):
    """
    Expected Calibration Error (MLGG-E03).
    ECE = sum(|fraction_of_positives - mean_predicted_value| * weight)
    """
    fraction_pos, mean_pred = calibration_curve(y_true, y_prob, n_bins=n_bins,
                                                 strategy="uniform")
    # Compute bin weights
    bin_edges = np.linspace(0, 1, n_bins + 1)
    bin_counts = np.histogram(y_prob, bins=bin_edges)[0]
    total = len(y_prob)

    ece = 0.0
    for i in range(len(fraction_pos)):
        weight = bin_counts[i] / total if total > 0 else 0
        ece += abs(fraction_pos[i] - mean_pred[i]) * weight

    return ece, fraction_pos, mean_pred


def decision_curve_analysis(y_true, y_prob, thresholds_range=None):
    """
    Decision Curve Analysis — net benefit across threshold probabilities.
    """
    if thresholds_range is None:
        thresholds_range = np.arange(0.01, 0.50, 0.01)

    n = len(y_true)
    prevalence = y_true.mean()
    records = []

    for pt in thresholds_range:
        y_pred = (y_prob >= pt).astype(int)
        tp = ((y_pred == 1) & (y_true == 1)).sum()
        fp = ((y_pred == 1) & (y_true == 0)).sum()

        net_benefit = (tp / n) - (fp / n) * (pt / (1 - pt))
        treat_all = prevalence - (1 - prevalence) * (pt / (1 - pt))

        records.append({
            "threshold": round(pt, 3),
            "net_benefit_model": round(net_benefit, 6),
            "net_benefit_treat_all": round(treat_all, 6),
            "net_benefit_treat_none": 0.0,
        })

    return pd.DataFrame(records)


def multi_seed_stability(model_class_name, base_params, X_train, y_train,
                         X_test, y_test, seeds=None):
    """
    Multi-seed stability test (MLGG-R02).
    Train with different seeds, check std of test AUROC < 0.02.
    """
    if seeds is None:
        seeds = config.SEED_LIST

    from sklearn.linear_model import LogisticRegression
    from sklearn.ensemble import RandomForestClassifier
    try:
        from xgboost import XGBClassifier
    except ImportError:
        XGBClassifier = None
    try:
        from lightgbm import LGBMClassifier
    except ImportError:
        LGBMClassifier = None

    class_map = {
        "LR": LogisticRegression,
        "RF": RandomForestClassifier,
        "XGBoost": XGBClassifier,
        "LightGBM": LGBMClassifier,
    }
    model_class = class_map.get(model_class_name)
    if model_class is None:
        return None

    aurocs = []
    for seed in seeds:
        params = {**base_params, "random_state": seed}
        model = model_class(**params)
        model.fit(X_train, y_train)
        y_prob = model.predict_proba(X_test)[:, 1]
        aurocs.append(roc_auc_score(y_test, y_prob))

    return {
        "seeds": seeds,
        "aurocs": [round(a, 4) for a in aurocs],
        "mean": round(np.mean(aurocs), 4),
        "std": round(np.std(aurocs), 4),
        "stable": np.std(aurocs) < 0.02,
    }


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    print("Loading data and models...")
    (X_train, y_train, X_valid, y_valid, X_test, y_test,
     feature_names, models, thresholds, best_info) = load_data_and_models()
    print(f"  Test set: {X_test.shape[0]} samples, {y_test.sum()} positive ({y_test.mean():.2%})")

    # ================================================================
    # FULL METRIC PANEL + 95% CI FOR ALL MODELS (MLGG-E01, E02)
    # ================================================================
    print(f"\n{'='*70}")
    print("TEST SET EVALUATION — SINGLE FINAL USE")
    print(f"{'='*70}")

    all_test_results = []
    all_ci_results = []

    for model_name in sorted(models.keys()):
        model = models[model_name]
        threshold = thresholds[model_name]
        y_prob = model.predict_proba(X_test)[:, 1]

        # Point estimates
        metrics = compute_metrics(y_test, y_prob, threshold)

        # Train AUROC for gap diagnostic
        y_prob_train = model.predict_proba(X_train)[:, 1]
        train_auroc = roc_auc_score(y_train, y_prob_train)
        gap = train_auroc - metrics["AUROC"]

        print(f"\n  {model_name} (threshold={threshold:.4f}):")
        for k, v in metrics.items():
            print(f"    {k:15s}: {v:.4f}")
        print(f"    {'Train-Test Gap':15s}: {gap:.4f} (diagnostic)")

        # 95% CI via bootstrap
        print(f"    Computing 95% CI (1000 bootstrap)...", end=" ", flush=True)
        ci = bootstrap_ci(y_test, y_prob, threshold,
                          n_boot=config.N_BOOTSTRAP, random_state=config.RANDOM_STATE)
        print("done")
        for k, v in ci.items():
            print(f"    {k:15s}: {v['mean']:.4f} ({v['ci_lo']:.4f} – {v['ci_hi']:.4f})")

        test_result = {"model": model_name, "threshold": threshold, **metrics,
                       "train_test_gap": round(gap, 4)}
        all_test_results.append(test_result)

        ci_record = {"model": model_name}
        for k, v in ci.items():
            ci_record[f"{k}_mean"] = round(v["mean"], 4)
            ci_record[f"{k}_ci_lo"] = round(v["ci_lo"], 4)
            ci_record[f"{k}_ci_hi"] = round(v["ci_hi"], 4)
        all_ci_results.append(ci_record)

        # Save ROC and PRC data
        fpr, tpr, _ = roc_curve(y_test, y_prob)
        precision, recall, _ = precision_recall_curve(y_test, y_prob)
        np.savez(os.path.join(results_dir, f"{model_name}_curves.npz"),
                 fpr=fpr, tpr=tpr, precision=precision, recall=recall)

    pd.DataFrame(all_test_results).to_csv(
        os.path.join(results_dir, "test_metrics.csv"), index=False)
    pd.DataFrame(all_ci_results).to_csv(
        os.path.join(results_dir, "test_metrics_ci.csv"), index=False)

    # ================================================================
    # CALIBRATION — ECE (MLGG-E03)
    # ================================================================
    print(f"\n{'='*70}")
    print("CALIBRATION (ECE)")
    print(f"{'='*70}")

    cal_records = []
    for model_name in sorted(models.keys()):
        model = models[model_name]
        y_prob = model.predict_proba(X_test)[:, 1]
        ece, frac_pos, mean_pred = compute_ece(y_test, y_prob)
        status = "✅" if ece < 0.1 else "⚠️"
        print(f"  {status} {model_name}: ECE={ece:.4f}")
        cal_records.append({"model": model_name, "ECE": round(ece, 4),
                            "ECE_ok": ece < 0.1})

        np.savez(os.path.join(results_dir, f"{model_name}_calibration.npz"),
                 fraction_positive=frac_pos, mean_predicted=mean_pred)

    pd.DataFrame(cal_records).to_csv(
        os.path.join(results_dir, "calibration_ece.csv"), index=False)

    # ================================================================
    # DECISION CURVE ANALYSIS
    # ================================================================
    print(f"\n{'='*70}")
    print("DECISION CURVE ANALYSIS")
    print(f"{'='*70}")

    overall_best_name = best_info["model_name"]
    best_model = models[overall_best_name]
    y_prob_best = best_model.predict_proba(X_test)[:, 1]
    dca_df = decision_curve_analysis(y_test, y_prob_best)
    dca_df.to_csv(os.path.join(results_dir, "dca.csv"), index=False)

    # Find useful threshold range (where model > treat all and > treat none)
    useful = dca_df[
        (dca_df["net_benefit_model"] > dca_df["net_benefit_treat_all"]) &
        (dca_df["net_benefit_model"] > 0)
    ]
    if len(useful) > 0:
        print(f"  {overall_best_name} provides clinical utility at thresholds: "
              f"{useful['threshold'].min():.2f} – {useful['threshold'].max():.2f}")
    else:
        print(f"  ⚠️  {overall_best_name} does not clearly outperform treat-all/treat-none")

    # ================================================================
    # MULTI-SEED STABILITY (MLGG-R02)
    # ================================================================
    print(f"\n{'='*70}")
    print(f"MULTI-SEED STABILITY (seeds={config.SEED_LIST})")
    print(f"{'='*70}")

    # Load best params from modeling results
    model_results_dir = os.path.join(config.PROJECT_ROOT, "05_modeling", "results")

    stability_records = []
    for model_name in sorted(models.keys()):
        # Reconstruct params from the model object
        params = models[model_name].get_params()
        # Remove non-constructor params that might cause issues
        for key in ["n_jobs"]:
            params.pop(key, None)

        print(f"\n  {model_name} ({len(config.SEED_LIST)} seeds)...", end=" ", flush=True)
        result = multi_seed_stability(
            model_name, params, X_train, y_train, X_test, y_test,
        )
        if result:
            status = "✅" if result["stable"] else "⚠️"
            print(f"done")
            print(f"    AUROCs: {result['aurocs']}")
            print(f"    Mean={result['mean']:.4f}, Std={result['std']:.4f} {status}")
            stability_records.append({
                "model": model_name,
                "mean_auroc": result["mean"],
                "std_auroc": result["std"],
                "stable": result["stable"],
            })
        else:
            print("skipped")

    pd.DataFrame(stability_records).to_csv(
        os.path.join(results_dir, "multi_seed_stability.csv"), index=False)

    # ================================================================
    # TRAIN-TEST GAP (MLGG-E04, diagnostic)
    # ================================================================
    print(f"\n{'='*70}")
    print("TRAIN-TEST GAP (diagnostic, per Steyerberg 2019)")
    print(f"{'='*70}")
    for r in all_test_results:
        print(f"  {r['model']}: gap={r['train_test_gap']:.4f}")

    # ================================================================
    # SUMMARY
    # ================================================================
    print(f"\n{'='*70}")
    print("PHASE 6 CHECKPOINT")
    print(f"{'='*70}")
    print(f"✅ [MLGG-E01] 95% CI computed for all metrics (bootstrap n={config.N_BOOTSTRAP})")
    print(f"✅ [MLGG-E02] Full metric panel: AUROC, AUPRC, Sens, Spec, PPV, NPV, F1, Brier")
    ece_ok = all(r["ECE_ok"] for r in cal_records)
    print(f"{'✅' if ece_ok else '⚠️'}  [MLGG-E03] Calibration ECE < 0.1: {'all pass' if ece_ok else 'some fail'}")
    print(f"✅ [MLGG-E04] Train-test gap reported (diagnostic only)")
    stable_ok = all(r["stable"] for r in stability_records)
    print(f"{'✅' if stable_ok else '⚠️'}  [MLGG-R02] Multi-seed stability std < 0.02: {'all pass' if stable_ok else 'some fail'}")
    print(f"✅ Decision Curve Analysis completed")
    print(f"✅ Single final test evaluation only")

    print(f"\n✅ Phase 6 results saved to: {results_dir}")


if __name__ == "__main__":
    main()
