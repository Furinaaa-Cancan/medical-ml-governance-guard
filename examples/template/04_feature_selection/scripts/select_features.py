"""
Phase 4: Feature Selection

Methodology: MLGG Standard (Zou & Hastie 2005, Meinshausen & Buhlmann 2010,
             Yuan & Lin 2006, Harrell 2015, Heinze 2018)

Checkpoint (MLGG):
  - MLGG-F01: No label/outcome variable as feature?
  - MLGG-F02: No post-prediction-timepoint features?
  - MLGG-F03: Feature selection on training set ONLY?
  - MLGG-F04: Univariate pre-screening NOT used? (Heinze 2018)
  - MLGG-F06: Elastic Net + Stability Selection + Group LASSO + Ridge baseline?
  - MLGG-Z01: EPV still >= 10 after selection?

Input:  03_preprocessing/results/processed_data.npz, feature_names.json,
        03_preprocessing/results/encoding_groups.json (optional)
Output: 04_feature_selection/results/selected_data.npz, selected_features.json,
        stability_selection.csv, selection_report.json
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import config as cfg

import json
import math
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression, LogisticRegressionCV
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import average_precision_score


# ─── Safety Checks (MLGG-F01, F02) ───────────────────────────

def check_forbidden_features(feature_names):
    """MLGG-F01/F02: Reject forbidden features before any selection."""
    forbidden = set(cfg.FORBIDDEN_FEATURES)
    if cfg.LABEL_COL:
        forbidden.add(cfg.LABEL_COL)
    found = [f for f in feature_names if f in forbidden]
    if found:
        raise ValueError(
            f"[MLGG-F01/F02] CRITICAL: Forbidden features found in input: {found}. "
            f"These must be removed before feature selection."
        )


# ─── Near-Zero Variance Filter ───────────────────────────────

def filter_near_zero_variance(X, feature_names):
    """Remove features with > NZV_THRESHOLD fraction same value."""
    keep = []
    for i in range(X.shape[1]):
        _, counts = np.unique(X[:, i], return_counts=True)
        if counts.max() / len(X) <= cfg.NZV_THRESHOLD:
            keep.append(i)

    removed = len(feature_names) - len(keep)
    if removed > 0:
        dropped = [feature_names[i] for i in range(len(feature_names)) if i not in keep]
        print(f"Near-zero variance filter: removed {removed} features: {dropped}")
    return keep


# ─── Feature Group Detection ─────────────────────────────────

def load_feature_groups(feature_names):
    """Load or auto-detect feature groups for Group LASSO.

    OneHot dummy columns from the same original variable must be
    selected/dropped together (Yuan & Lin 2006).

    Priority:
      1. cfg.FEATURE_GROUPS (manual override)
      2. encoding_groups.json from Phase 3
      3. Auto-detect from naming convention (prefix_Value)
    """
    # Manual override
    if cfg.FEATURE_GROUPS:
        return cfg.FEATURE_GROUPS

    # Phase 3 encoding metadata
    encoding_path = cfg.PREPROCESS_RESULTS / "encoding_groups.json"
    if encoding_path.exists():
        with open(encoding_path) as f:
            groups = json.load(f)
        print(f"Loaded {len(groups)} feature groups from Phase 3 encoding metadata")
        return groups

    # Auto-detect: group columns sharing a common prefix before last '_'
    groups = {}
    ungrouped = []
    for name in feature_names:
        if "_" in name:
            prefix = name.rsplit("_", 1)[0]
            # Only group if multiple columns share the prefix
            groups.setdefault(prefix, []).append(name)
        else:
            ungrouped.append(name)

    # Filter: only keep groups with 2+ members (actual OneHot groups)
    real_groups = {k: v for k, v in groups.items() if len(v) >= 2}

    if real_groups:
        n_grouped = sum(len(v) for v in real_groups.values())
        print(f"Auto-detected {len(real_groups)} feature groups ({n_grouped} columns)")

    return real_groups


# ─── Stability Selection (Meinshausen & Buhlmann 2010) ───────

def stability_selection(X_train, y_train, feature_names, groups):
    """Elastic Net Stability Selection with stratified subsampling and group LASSO.

    Methodology:
      - n_subsamples iterations, each drawing SUBSAMPLE_RATIO of each class
      - Elastic Net CV with multiple alpha/C values (not pure L1)
      - Group LASSO: feature selected if ANY dummy in group has nonzero coef,
        then ALL dummies in that group are counted as selected
      - False selection bound: E[V] <= q^2 / ((2*pi*threshold - 1) * p)
    """
    n_features = X_train.shape[1]
    selection_counts = np.zeros(n_features)
    effective_runs = 0

    # Stratified indices for subsampling
    pos_idx = np.where(y_train == 1)[0]
    neg_idx = np.where(y_train == 0)[0]
    n_pos_sub = max(int(len(pos_idx) * cfg.STABILITY_SUBSAMPLE_RATIO), 1)
    n_neg_sub = max(int(len(neg_idx) * cfg.STABILITY_SUBSAMPLE_RATIO), 1)

    # Build group membership: feature_index -> group_key
    feat_to_group = {}
    group_to_indices = {}
    for gname, members in groups.items():
        indices = [i for i, f in enumerate(feature_names) if f in members]
        if indices:
            group_to_indices[gname] = indices
            for idx in indices:
                feat_to_group[idx] = gname

    for i in range(cfg.STABILITY_N_SUBSAMPLES):
        rng = np.random.RandomState(cfg.RANDOM_STATE + i)

        # Stratified subsampling (preserve class balance)
        sub_pos = rng.choice(pos_idx, size=n_pos_sub, replace=False)
        sub_neg = rng.choice(neg_idx, size=n_neg_sub, replace=False)
        sub_idx = np.concatenate([sub_pos, sub_neg])
        rng.shuffle(sub_idx)

        scaler = StandardScaler()
        X_sub = scaler.fit_transform(X_train[sub_idx])

        try:
            lr = LogisticRegressionCV(
                penalty="elasticnet",
                solver="saga",
                l1_ratios=cfg.STABILITY_L1_RATIOS,
                Cs=list(cfg.STABILITY_CS),
                cv=min(cfg.STABILITY_CV_FOLDS, n_pos_sub),
                random_state=cfg.RANDOM_STATE + i,
                max_iter=cfg.STABILITY_MAX_ITER,
                scoring="average_precision",
            )
            lr.fit(X_sub, y_train[sub_idx])
        except Exception as e:
            print(f"  Subsample {i}: convergence issue ({e}), skipping")
            continue

        nonzero = np.abs(lr.coef_.ravel()) > 1e-10
        effective_runs += 1

        # Group LASSO: if any member selected, select all members
        for gname, g_indices in group_to_indices.items():
            if any(nonzero[j] for j in g_indices):
                for j in g_indices:
                    nonzero[j] = True

        selection_counts += nonzero.astype(int)

    if effective_runs == 0:
        raise RuntimeError("All stability selection subsamples failed to converge")

    probs = selection_counts / effective_runs
    stable_mask = probs > cfg.STABILITY_THRESHOLD
    stable_idx = np.where(stable_mask)[0]
    stable_names = [feature_names[i] for i in stable_idx]

    # False selection bound (Meinshausen & Buhlmann 2010, Theorem 1)
    q = stable_mask.sum()
    p = n_features
    pi_thresh = cfg.STABILITY_THRESHOLD
    denom = (2 * pi_thresh - 1) * p
    expected_false = (q ** 2) / denom if denom > 0 and pi_thresh > 0.5 else float("inf")

    print(f"Stability Selection: {len(stable_names)}/{n_features} features "
          f"(prob > {cfg.STABILITY_THRESHOLD})")
    print(f"  Effective runs: {effective_runs}/{cfg.STABILITY_N_SUBSAMPLES}")
    print(f"  Expected false selections E[V] <= {expected_false:.2f}")

    stability_df = pd.DataFrame({
        "feature": feature_names,
        "selection_probability": probs,
        "selected": stable_mask,
    }).sort_values("selection_probability", ascending=False)

    return stable_idx, stable_names, stability_df, expected_false


# ─── Ridge Baseline with CV (Harrell 2015) ───────────────────

def ridge_baseline(X_train, y_train, X_valid, y_valid):
    """Ridge baseline: full model with CV-tuned shrinkage (Harrell 2015).

    Uses PR-AUC (not AUROC) for comparison — more informative under
    class imbalance (Saito & Rehmsmeier 2015).
    """
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_valid_s = scaler.transform(X_valid)

    ridge = LogisticRegressionCV(
        penalty="l2",
        Cs=list(cfg.RIDGE_CV_CS),
        cv=5,
        solver="lbfgs",
        scoring="average_precision",
        random_state=cfg.RANDOM_STATE,
        max_iter=5000,
    )
    ridge.fit(X_train_s, y_train)

    y_prob = ridge.predict_proba(X_valid_s)[:, 1]
    ridge_prauc = average_precision_score(y_valid, y_prob)
    best_C = float(ridge.C_[0])
    print(f"Ridge baseline (all {X_train.shape[1]} features, C={best_C:.4f}): "
          f"PR-AUC = {ridge_prauc:.4f}")
    return ridge_prauc, best_C, scaler


# ─── Main ─────────────────────────────────────────────────────

def main():
    cfg.FEATURE_RESULTS.mkdir(parents=True, exist_ok=True)

    # Load Phase 3 output
    data = np.load(cfg.PREPROCESS_RESULTS / "processed_data.npz")
    with open(cfg.PREPROCESS_RESULTS / "feature_names.json") as f:
        feature_names = json.load(f)

    X_train, y_train = data["X_train"], data["y_train"]
    X_valid, y_valid = data["X_valid"], data["y_valid"]
    X_test, y_test = data["X_test"], data["y_test"]

    # MLGG-F01/F02: Reject forbidden features
    check_forbidden_features(feature_names)

    # Step 0: Near-zero variance filter (preprocessing, not selection)
    keep_idx = filter_near_zero_variance(X_train, feature_names)
    X_train = X_train[:, keep_idx]
    X_valid = X_valid[:, keep_idx]
    X_test = X_test[:, keep_idx]
    feature_names = [feature_names[i] for i in keep_idx]

    # Load feature groups for Group LASSO
    groups = load_feature_groups(feature_names)

    # Step 1: Ridge baseline — full model with CV-tuned shrinkage
    ridge_prauc, ridge_C, _ = ridge_baseline(X_train, y_train, X_valid, y_valid)

    # Step 2: Stability Selection (Elastic Net + Group LASSO)
    stable_idx, stable_names, stability_df, expected_false = stability_selection(
        X_train, y_train, feature_names, groups
    )
    stability_df.to_csv(cfg.FEATURE_RESULTS / "stability_selection.csv", index=False)

    # Step 3: Compare selected model vs Ridge baseline on PR-AUC
    use_full_model = False
    selected_prauc = None

    if len(stable_idx) == 0:
        print("WARNING: No features selected by stability selection — "
              "falling back to Ridge full model")
        use_full_model = True
    else:
        scaler_sel = StandardScaler()
        X_tr_sel = scaler_sel.fit_transform(X_train[:, stable_idx])
        X_va_sel = scaler_sel.transform(X_valid[:, stable_idx])

        lr = LogisticRegression(
            C=1.0, solver="lbfgs",
            random_state=cfg.RANDOM_STATE, max_iter=5000,
        )
        lr.fit(X_tr_sel, y_train)
        selected_prauc = average_precision_score(
            y_valid, lr.predict_proba(X_va_sel)[:, 1]
        )
        print(f"Selected model ({len(stable_names)} features): "
              f"PR-AUC = {selected_prauc:.4f}")

        prauc_drop = ridge_prauc - selected_prauc
        if prauc_drop > cfg.RIDGE_FALLBACK_THRESHOLD:
            print(f"WARNING: Selection causes {prauc_drop:.4f} PR-AUC loss vs Ridge "
                  f"(threshold={cfg.RIDGE_FALLBACK_THRESHOLD}). "
                  f"Falling back to full model with shrinkage (Harrell 2015).")
            use_full_model = True

    # Determine final feature set
    if use_full_model:
        final_idx = np.arange(len(feature_names))
        final_names = feature_names
        selection_method = "ridge_full_model"
    else:
        final_idx = stable_idx
        final_names = stable_names
        selection_method = "stability_selection"

    # EPV re-check (MLGG-Z01)
    n_events = int(y_train.sum())
    epv = n_events / max(len(final_names), 1)
    epv_adequate = epv >= 10

    print(f"\nFinal: {len(final_names)} features via {selection_method}")
    print(f"EPV after selection: {epv:.1f} "
          f"{'(adequate)' if epv_adequate else '(INADEQUATE < 10)'}")

    # Save selected data
    np.savez(
        cfg.FEATURE_RESULTS / "selected_data.npz",
        X_train=X_train[:, final_idx], y_train=y_train,
        X_valid=X_valid[:, final_idx], y_valid=y_valid,
        X_test=X_test[:, final_idx], y_test=y_test,
    )
    with open(cfg.FEATURE_RESULTS / "selected_features.json", "w") as f:
        json.dump(final_names, f, indent=2)

    # Save selection report
    report = {
        "method": selection_method,
        "n_input_features": len(feature_names),
        "n_selected_features": len(final_names),
        "selected_features": final_names,
        "ridge_baseline_prauc": ridge_prauc,
        "ridge_best_C": ridge_C,
        "selected_model_prauc": selected_prauc,
        "prauc_drop": (ridge_prauc - selected_prauc) if selected_prauc is not None else None,
        "fallback_threshold": cfg.RIDGE_FALLBACK_THRESHOLD,
        "stability_config": {
            "n_subsamples": cfg.STABILITY_N_SUBSAMPLES,
            "subsample_ratio": cfg.STABILITY_SUBSAMPLE_RATIO,
            "threshold": cfg.STABILITY_THRESHOLD,
            "l1_ratios": list(cfg.STABILITY_L1_RATIOS),
            "Cs": list(cfg.STABILITY_CS),
            "cv_folds": cfg.STABILITY_CV_FOLDS,
        },
        "expected_false_selections": expected_false,
        "feature_groups_used": len(groups),
        "epv_after_selection": epv,
        "epv_adequate": epv_adequate,
        "n_events": n_events,
    }
    with open(cfg.FEATURE_RESULTS / "selection_report.json", "w") as f:
        json.dump(report, f, indent=2)

    # Checkpoint
    print(f"\nPhase 4 complete. Results in {cfg.FEATURE_RESULTS}/")
    print("--- Checkpoint ---")
    print("[x] Forbidden features rejected (MLGG-F01/F02)")
    print("[x] Feature selection on training set only (MLGG-F03)")
    print("[x] Univariate pre-screening NOT used (MLGG-F04, Heinze 2018)")
    print(f"[x] Elastic Net Stability Selection + Group LASSO + Ridge baseline (MLGG-F06)")
    print(f"[{'x' if epv_adequate else ' '}] EPV >= 10 after selection (MLGG-Z01)")
    if expected_false < float("inf"):
        print(f"[i] False selection bound E[V] <= {expected_false:.2f} "
              f"(Meinshausen & Buhlmann 2010)")


if __name__ == "__main__":
    main()
