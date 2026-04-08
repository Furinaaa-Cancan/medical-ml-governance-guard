"""
07_interpretability/scripts/interpret.py
=========================================
Phase 7: Model Interpretability
- SHAP values (TreeExplainer for XGBoost/LightGBM/RF, LinearExplainer for LR)
- Global feature importance (mean |SHAP|)
- Cross-model SHAP consistency (Spearman rank correlation)
- Individual case explanations (highest/lowest risk)

SHAP 基于训练集计算（不泄漏测试集信息）。
注：PDP/ICE 图建议用 sklearn.inspection.PartialDependenceDisplay 手动生成。

输出 → 07_interpretability/results/
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

warnings.filterwarnings("ignore")

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False


def load_data_and_model():
    feat_dir = os.path.join(config.PROJECT_ROOT, "04_feature_selection", "results")
    data = np.load(os.path.join(feat_dir, "selected_data.npz"))
    with open(os.path.join(feat_dir, "selected_features.json")) as f:
        feat_info = json.load(f)

    model_dir = os.path.join(config.PROJECT_ROOT, "05_modeling", "results")
    with open(os.path.join(model_dir, "best_model_info.json")) as f:
        best_info = json.load(f)

    models = {}
    for name in ["LR", "RF", "XGBoost", "LightGBM"]:
        path = os.path.join(config.MODEL_DIR, f"{name}_best.pkl")
        if os.path.exists(path):
            models[name] = joblib.load(path)

    return (
        data["X_train"], data["y_train"],
        data["X_test"], data["y_test"],
        feat_info["selected_features"],
        models, best_info["model_name"],
    )


def compute_shap_values(model, model_name, X_train, X_test, feature_names):
    """
    计算 SHAP values。
    TreeExplainer 用于树模型，LinearExplainer 用于 LR。
    使用训练集的子样本作为 background。
    """
    # Subsample background for speed
    n_bg = min(500, X_train.shape[0])
    rng = np.random.RandomState(config.RANDOM_STATE)
    bg_idx = rng.choice(X_train.shape[0], size=n_bg, replace=False)
    X_bg = X_train[bg_idx]

    # Subsample test for SHAP (full test too slow for some explainers)
    n_explain = min(2000, X_test.shape[0])
    explain_idx = rng.choice(X_test.shape[0], size=n_explain, replace=False)
    X_explain = X_test[explain_idx]

    if model_name in ["XGBoost", "LightGBM", "RF"]:
        explainer = shap.TreeExplainer(model, X_bg)
        shap_values = explainer.shap_values(X_explain)
        # For binary classification, TreeExplainer may return list [neg, pos]
        if isinstance(shap_values, list):
            shap_values = shap_values[1]
        # Or 3D array (n_samples, n_features, n_classes)
        if shap_values.ndim == 3:
            shap_values = shap_values[:, :, 1]
    else:
        # LR — use LinearExplainer
        explainer = shap.LinearExplainer(model, X_bg)
        shap_values = explainer.shap_values(X_explain)

    return shap_values, X_explain, explain_idx


def global_importance(shap_values, feature_names):
    """Mean |SHAP| — global feature importance ranking."""
    mean_abs = np.mean(np.abs(shap_values), axis=0)
    importance = pd.DataFrame({
        "feature": feature_names,
        "mean_abs_shap": mean_abs,
    }).sort_values("mean_abs_shap", ascending=False).reset_index(drop=True)
    importance["rank"] = range(1, len(importance) + 1)
    return importance


def individual_explanations(shap_values, X_explain, y_test, explain_idx,
                            feature_names, model, n_cases=5):
    """
    选取最高和最低风险案例，输出 SHAP 解释。
    """
    y_prob = model.predict_proba(X_explain)[:, 1]

    # Highest risk
    high_idx = np.argsort(y_prob)[-n_cases:][::-1]
    # Lowest risk
    low_idx = np.argsort(y_prob)[:n_cases]

    cases = []
    for label, indices in [("high_risk", high_idx), ("low_risk", low_idx)]:
        for i in indices:
            top_features = np.argsort(np.abs(shap_values[i]))[-5:][::-1]
            explanation = []
            for fi in top_features:
                explanation.append({
                    "feature": feature_names[fi],
                    "value": round(float(X_explain[i, fi]), 4),
                    "shap_value": round(float(shap_values[i, fi]), 4),
                    "direction": "increases risk" if shap_values[i, fi] > 0 else "decreases risk",
                })
            cases.append({
                "category": label,
                "predicted_prob": round(float(y_prob[i]), 4),
                "actual_label": int(y_test[explain_idx[i]]),
                "top_5_drivers": explanation,
            })
    return cases


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    if not HAS_SHAP:
        print("❌ SHAP not installed. Run: pip install shap")
        return

    print("Loading data and models...")
    (X_train, y_train, X_test, y_test,
     feature_names, models, best_model_name) = load_data_and_model()

    print(f"  Best model: {best_model_name}")
    print(f"  Features: {len(feature_names)}")

    # Compute SHAP for all models
    all_importance = {}  # {model_name: importance_df} for cross-model consistency
    for model_name in sorted(models.keys()):
        model = models[model_name]
        print(f"\n{'='*60}")
        print(f"SHAP: {model_name}")
        print(f"{'='*60}")

        print("  Computing SHAP values...", end=" ", flush=True)
        shap_values, X_explain, explain_idx = compute_shap_values(
            model, model_name, X_train, X_test, feature_names
        )
        print(f"done (shape={shap_values.shape})")

        # Save raw SHAP values
        np.savez(os.path.join(results_dir, f"{model_name}_shap.npz"),
                 shap_values=shap_values, X_explain=X_explain,
                 explain_idx=explain_idx)

        # Global importance
        importance = global_importance(shap_values, feature_names)
        importance.to_csv(os.path.join(results_dir, f"{model_name}_importance.csv"),
                          index=False)
        all_importance[model_name] = importance

        print(f"\n  Top 10 features (mean |SHAP|):")
        for _, row in importance.head(10).iterrows():
            bar = "█" * int(row["mean_abs_shap"] * 100)
            print(f"    {row['rank']:2d}. {row['feature']:35s} {row['mean_abs_shap']:.4f} {bar}")

        # Individual explanations (best model only)
        if model_name == best_model_name:
            print(f"\n  Individual case explanations:")
            cases = individual_explanations(
                shap_values, X_explain, y_test, explain_idx,
                feature_names, model,
            )
            with open(os.path.join(results_dir, "individual_cases.json"), "w") as f:
                json.dump(cases, f, indent=2)

            for case in cases[:3]:  # Show top 3 high risk
                print(f"\n    [{case['category']}] P={case['predicted_prob']:.3f}, actual={case['actual_label']}")
                for d in case["top_5_drivers"][:3]:
                    print(f"      {d['feature']}: SHAP={d['shap_value']:+.4f} ({d['direction']})")

    # Cross-model SHAP consistency (Spearman rank correlation)
    if len(all_importance) >= 2:
        from scipy.stats import spearmanr
        print(f"\n{'='*60}")
        print("Cross-Model SHAP Consistency")
        print(f"{'='*60}")
        model_names = sorted(all_importance.keys())
        consistency_rows = []
        for i, m1 in enumerate(model_names):
            for m2 in model_names[i+1:]:
                imp1 = all_importance[m1].set_index("feature")["mean_abs_shap"]
                imp2 = all_importance[m2].set_index("feature")["mean_abs_shap"]
                common = imp1.index.intersection(imp2.index)
                if len(common) >= 5:
                    rho, pval = spearmanr(imp1[common].values, imp2[common].values)
                    print(f"  {m1} vs {m2}: Spearman ρ = {rho:.4f} (p = {pval:.2e})")
                    consistency_rows.append({
                        "model_1": m1, "model_2": m2,
                        "spearman_rho": round(rho, 4), "p_value": round(pval, 6),
                        "n_features": len(common),
                    })
        if consistency_rows:
            pd.DataFrame(consistency_rows).to_csv(
                os.path.join(results_dir, "shap_cross_model_consistency.csv"),
                index=False)
            mean_rho = np.mean([r["spearman_rho"] for r in consistency_rows])
            print(f"\n  Mean Spearman ρ: {mean_rho:.4f}", end="")
            print("  ✅" if mean_rho >= 0.5 else "  ⚠️ Low consistency")

    print(f"\n✅ Phase 7 results saved to: {results_dir}")


if __name__ == "__main__":
    main()
