"""
Phase 4: Feature Selection

Checkpoint (MLGG):
  - Feature selection on training set ONLY? (MLGG-F03)
  - EPV still >= 10 after selection? (MLGG-Z01)
  - Ridge baseline compared? (MLGG-F06)
  - Univariate pre-screening NOT used? (Heinze 2018, Harrell 2015)

Input:  03_preprocessing/results/processed_data.npz, feature_names.json
Output: 04_feature_selection/results/selected_data.npz, selected_features.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score


def load_processed():
    """Load preprocessed data from Phase 3."""
    data = np.load(cfg.PREPROCESS_RESULTS / "processed_data.npz")
    with open(cfg.PREPROCESS_RESULTS / "feature_names.json") as f:
        feature_names = json.load(f)
    return data, feature_names


def filter_near_zero_variance(X, feature_names, threshold=0.99):
    """Remove features with >99% same value (preprocessing, not selection)."""
    keep = []
    for i, name in enumerate(feature_names):
        vals, counts = np.unique(X[:, i], return_counts=True)
        max_pct = counts.max() / len(X)
        if max_pct <= threshold:
            keep.append(i)

    removed = len(feature_names) - len(keep)
    if removed > 0:
        print(f"Near-zero variance filter: removed {removed} features")
    return keep


def stability_selection(X_train, y_train, feature_names, n_subsamples=100, threshold=0.6):
    """Stability Selection (Meinshausen & Buhlmann 2010).

    Run L1-penalized logistic regression on random 50% subsamples,
    keep features with selection probability > threshold.

    Uses LogisticRegressionCV (classification) not ElasticNetCV (regression).
    Features are scaled internally to prevent penalty bias.
    """
    n_features = X_train.shape[1]
    selection_counts = np.zeros(n_features)
    n_samples = X_train.shape[0]

    for i in range(n_subsamples):
        rng = np.random.RandomState(cfg.RANDOM_STATE + i)
        idx = rng.choice(n_samples, size=n_samples // 2, replace=False)

        # Scale subsample to prevent penalty bias (Qwen/Claude cross-check)
        scaler = StandardScaler()
        X_sub = scaler.fit_transform(X_train[idx])

        lr = LogisticRegressionCV(
            solver="saga",
            l1_ratios=(1.0,),
            Cs=10,
            cv=3,
            random_state=cfg.RANDOM_STATE + i,
            max_iter=3000,
        )
        lr.fit(X_sub, y_train[idx])
        selection_counts += (lr.coef_.ravel() != 0).astype(int)

    probs = selection_counts / n_subsamples
    stable_idx = np.where(probs > threshold)[0]
    stable_names = [feature_names[i] for i in stable_idx]

    print(f"Stability Selection: {len(stable_names)} features with prob > {threshold}")

    # Save stability results
    stability_df = pd.DataFrame({
        "feature": feature_names,
        "selection_probability": probs,
        "selected": probs > threshold,
    }).sort_values("selection_probability", ascending=False)

    return stable_idx, stable_names, stability_df


def ridge_baseline(X_train, y_train, X_valid, y_valid):
    """Ridge baseline: full model with shrinkage, no selection (Harrell 2015).

    If feature selection causes >0.005 AUROC loss vs Ridge baseline,
    prefer full model with shrinkage.
    """
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_valid_s = scaler.transform(X_valid)

    ridge = LogisticRegression(
        C=1.0, solver="lbfgs",
        random_state=cfg.RANDOM_STATE, max_iter=5000,
    )
    ridge.fit(X_train_s, y_train)
    ridge_auc = roc_auc_score(y_valid, ridge.predict_proba(X_valid_s)[:, 1])
    print(f"Ridge baseline (all features): AUROC = {ridge_auc:.4f}")
    return ridge_auc, scaler


def main():
    cfg.FEATURE_RESULTS.mkdir(parents=True, exist_ok=True)

    data, feature_names = load_processed()
    X_train, y_train = data["X_train"], data["y_train"]
    X_valid, y_valid = data["X_valid"], data["y_valid"]
    X_test, y_test = data["X_test"], data["y_test"]

    # Step 0: Near-zero variance filter
    keep_idx = filter_near_zero_variance(X_train, feature_names)
    X_train = X_train[:, keep_idx]
    X_valid = X_valid[:, keep_idx]
    X_test = X_test[:, keep_idx]
    feature_names = [feature_names[i] for i in keep_idx]

    # Step 1: Ridge baseline (no selection)
    ridge_auc, _ = ridge_baseline(X_train, y_train, X_valid, y_valid)

    # Step 2: Stability Selection
    stable_idx, stable_names, stability_df = stability_selection(
        X_train, y_train, feature_names
    )
    stability_df.to_csv(cfg.FEATURE_RESULTS / "stability_selection.csv", index=False)

    # Step 3: Compare selected vs Ridge
    if len(stable_idx) > 0:
        scaler_sel = StandardScaler()
        X_tr_sel = scaler_sel.fit_transform(X_train[:, stable_idx])
        X_va_sel = scaler_sel.transform(X_valid[:, stable_idx])

        lr = LogisticRegression(C=1.0, solver="lbfgs",
                                random_state=cfg.RANDOM_STATE, max_iter=5000)
        lr.fit(X_tr_sel, y_train)
        selected_auc = roc_auc_score(y_valid, lr.predict_proba(X_va_sel)[:, 1])
        print(f"Selected model: AUROC = {selected_auc:.4f}")

        auc_drop = ridge_auc - selected_auc
        if auc_drop > 0.005:
            print(f"WARNING: Selection causes {auc_drop:.4f} AUROC loss vs Ridge. "
                  f"Consider using full model with shrinkage.")
    else:
        print("WARNING: No features selected by stability selection")
        stable_idx = np.arange(len(feature_names))
        stable_names = feature_names

    # EPV re-check
    n_events = int(y_train.sum())
    epv = n_events / max(len(stable_names), 1)
    print(f"EPV after selection: {epv:.1f} {'(adequate)' if epv >= 10 else '(INADEQUATE < 10)'}")

    # Save selected data
    np.savez(
        cfg.FEATURE_RESULTS / "selected_data.npz",
        X_train=X_train[:, stable_idx], y_train=y_train,
        X_valid=X_valid[:, stable_idx], y_valid=y_valid,
        X_test=X_test[:, stable_idx], y_test=y_test,
    )
    with open(cfg.FEATURE_RESULTS / "selected_features.json", "w") as f:
        json.dump(stable_names, f, indent=2)

    print(f"\nPhase 4 complete. Results in {cfg.FEATURE_RESULTS}/")
    print("--- Checkpoint ---")
    print("[x] Feature selection on training set only (MLGG-F03)")
    print(f"[{'x' if epv >= 10 else ' '}] EPV >= 10 after selection (MLGG-Z01)")
    print("[x] Ridge baseline compared (MLGG-F06)")
    print("[x] Univariate pre-screening NOT used (Heinze 2018)")


if __name__ == "__main__":
    main()
