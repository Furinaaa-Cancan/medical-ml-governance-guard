"""
Phase 7: Interpretability

Input:  04_feature_selection/results/selected_data.npz
        outputs/models/*.pkl
Output: 07_interpretability/results/

Note: SHAP background data from TRAINING set, explain on TEST set.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import numpy as np
import pandas as pd
import joblib

try:
    import shap
    HAS_SHAP = True
except ImportError:
    HAS_SHAP = False
    print("WARNING: shap not installed. Install via: pip install shap")


def load_data_and_models():
    data = np.load(cfg.FEATURE_RESULTS / "selected_data.npz")
    with open(cfg.FEATURE_RESULTS / "selected_features.json") as f:
        feature_names = json.load(f)

    models = {}
    for pkl in cfg.OUTPUT_MODELS.glob("*_best.pkl"):
        name = pkl.stem.replace("_best", "")
        if name != "best_model":
            models[name] = joblib.load(pkl)

    return data, models, feature_names


def compute_shap(model, name, X_train, X_test, feature_names):
    """Compute SHAP values. Background: training set subsample."""
    # Subsample background for speed
    rng = np.random.RandomState(cfg.RANDOM_STATE)
    bg_idx = rng.choice(len(X_train), size=min(500, len(X_train)), replace=False)
    background = X_train[bg_idx]

    # Choose explainer based on model type
    model_type = type(model).__name__
    tree_types = {"RandomForestClassifier", "XGBClassifier", "LGBMClassifier",
                  "GradientBoostingClassifier"}

    if model_type in tree_types:
        explainer = shap.TreeExplainer(model, background)
    elif model_type == "LogisticRegression":
        explainer = shap.LinearExplainer(model, background)
    else:
        explainer = shap.KernelExplainer(model.predict_proba, background)

    shap_values = explainer.shap_values(X_test)

    # For binary classification, take positive class (class=1)
    if isinstance(shap_values, list):
        if hasattr(model, "classes_"):
            pos_idx = int(np.where(model.classes_ == 1)[0][0])
        else:
            pos_idx = 1
        shap_values = shap_values[pos_idx]

    # Global importance: mean |SHAP|
    importance = np.abs(shap_values).mean(axis=0)
    importance_df = pd.DataFrame({
        "feature": feature_names,
        "mean_abs_shap": importance,
    }).sort_values("mean_abs_shap", ascending=False)

    return shap_values, importance_df


def main():
    if not HAS_SHAP:
        print("Skipping Phase 7: shap not installed")
        return

    cfg.INTERPRET_RESULTS.mkdir(parents=True, exist_ok=True)

    data, models, feature_names = load_data_and_models()
    X_train, X_test = data["X_train"], data["X_test"]

    all_importance = {}

    for name, model in models.items():
        print(f"\nComputing SHAP for {name}...")
        shap_values, importance_df = compute_shap(
            model, name, X_train, X_test, feature_names
        )

        importance_df.to_csv(
            cfg.INTERPRET_RESULTS / f"{name}_importance.csv", index=False
        )
        np.savez(
            cfg.INTERPRET_RESULTS / f"{name}_shap.npz",
            shap_values=shap_values,
        )

        all_importance[name] = importance_df.set_index("feature")["mean_abs_shap"]
        print(f"  Top 5: {', '.join(importance_df['feature'].head(5).tolist())}")

    # Cross-model comparison: features robust across models
    if len(all_importance) >= 2:
        top_k = 10
        print(f"\nCross-model top-{top_k} comparison:")
        for name, imp in all_importance.items():
            top = set(imp.nlargest(top_k).index)
            print(f"  {name}: {top}")

    print(f"\nPhase 7 complete. Results in {cfg.INTERPRET_RESULTS}/")


if __name__ == "__main__":
    main()
