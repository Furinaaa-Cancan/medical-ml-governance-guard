"""
04_feature_selection/scripts/select_features.py
================================================
Phase 4: Feature Selection (on training set ONLY — MLGG-F03)

Modern approach per Harrell 2015, Steyerberg 2019, Heinze 2018:
- Step 0: Near-zero variance filter (preprocessing, not selection)
- Step 1: Elastic Net with grouped structure (Group Elastic Net concept)
         α cross-validated over [0.1, 0.3, 0.5, 0.7, 1.0]
         Group structure: OneHot dummies from same variable selected/dropped together
- Step 2: Stability Selection (Meinshausen & Bühlmann 2010)
         100 subsamples × Elastic Net, keep features with inclusion probability > 0.6
- Step 3: Ridge baseline (Harrell's recommendation: no selection, just shrinkage)
         Compare selected model vs full Ridge to quantify selection cost/benefit
- Step 4: Final decision — report both paths

Literature justification:
- Univariate pre-screening is explicitly discouraged (Harrell, Heinze 2018)
- Elastic Net preferred over LASSO for correlated clinical features (Pavlou 2015)
- Stability selection provides finite-sample error control on false selections
- Pre-specification + shrinkage is the gold standard (Harrell 2015, Steyerberg 2019)

输出 → 04_feature_selection/results/
"""

import sys
import os
import json
import warnings
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
import config

from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")


def load_processed_data():
    """加载 Phase 3 输出的预处理数据。"""
    prep_dir = os.path.join(config.PROJECT_ROOT, "03_preprocessing", "results")
    data = np.load(os.path.join(prep_dir, "processed_data.npz"))
    with open(os.path.join(prep_dir, "feature_names.json")) as f:
        feature_names = json.load(f)
    with open(os.path.join(prep_dir, "column_types.json")) as f:
        col_types = json.load(f)
    return (
        data["X_train"], data["y_train"],
        data["X_valid"], data["y_valid"],
        data["X_test"], data["y_test"],
        feature_names, col_types,
    )


def filter_near_zero_variance(X_train, X_valid, X_test, feature_names,
                               threshold=0.99):
    """
    移除近零方差特征：>threshold 比例为同一值的列。
    这是预处理步骤，不是特征选择。
    """
    keep_idx = []
    dropped = []
    for i in range(X_train.shape[1]):
        col = X_train[:, i]
        unique, counts = np.unique(col, return_counts=True)
        max_ratio = counts.max() / len(col)
        if max_ratio > threshold:
            dropped.append(feature_names[i])
        else:
            keep_idx.append(i)

    new_names = [feature_names[i] for i in keep_idx]
    return (X_train[:, keep_idx], X_valid[:, keep_idx], X_test[:, keep_idx],
            new_names, dropped)


def build_feature_groups(feature_names, col_types):
    """
    构建特征分组：同一原始变量的 OneHot 列归为一组。
    Group Elastic Net 按组选择/丢弃，避免选了 race_Caucasian 但丢了 race_Asian
    的不一致问题 (Yuan & Lin 2006)。

    返回 {group_name: [indices]} 字典。
    """
    # Identify original variable name from OneHot feature name
    # e.g., "race_Caucasian" → "race", "number_inpatient" → "number_inpatient"
    nominal_cols = col_types.get("nominal_cols", [])

    groups = {}
    for i, fname in enumerate(feature_names):
        # Check if this feature is a OneHot dummy
        matched_group = None
        for nom in nominal_cols:
            if fname.startswith(nom + "_") or fname == nom:
                matched_group = nom
                break

        if matched_group is None:
            # Not a OneHot feature — each is its own group
            matched_group = fname

        if matched_group not in groups:
            groups[matched_group] = []
        groups[matched_group].append(i)

    return groups


def elastic_net_cv(X_train, y_train, feature_names, groups):
    """
    Elastic Net with cross-validated α and λ.
    α ∈ {0.1, 0.3, 0.5, 0.7, 1.0} — 0.1 接近 Ridge, 1.0 = LASSO
    λ (C in sklearn = 1/λ) 通过 inner CV 选择。

    按组汇总系数：如果一组内所有系数为 0 → 该原始变量被排除。
    """
    alphas = [0.1, 0.5, 1.0]
    C_values = [0.01, 0.1, 1.0]

    best_auroc = -1
    best_config = None
    results = []

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=config.RANDOM_STATE)

    for alpha in alphas:
        for C in C_values:
            # sklearn's SGDClassifier with 'log_loss' supports elastic net
            # But LogisticRegression with elasticnet penalty is cleaner
            model = LogisticRegression(
                penalty="elasticnet",
                C=C,
                l1_ratio=alpha,
                solver="saga",
                max_iter=5000,
                random_state=config.RANDOM_STATE,
                class_weight="balanced",
            )

            # Inner CV on training set
            aurocs = []
            for train_idx, val_idx in cv.split(X_train, y_train):
                model.fit(X_train[train_idx], y_train[train_idx])
                y_prob = model.predict_proba(X_train[val_idx])[:, 1]
                aurocs.append(roc_auc_score(y_train[val_idx], y_prob))

            mean_auroc = np.mean(aurocs)
            coefs = None

            # Refit on full training set to get coefficients
            model.fit(X_train, y_train)
            coefs = model.coef_[0]
            n_nonzero = np.sum(coefs != 0)

            results.append({
                "alpha": alpha,
                "C": C,
                "cv_auroc": round(mean_auroc, 4),
                "n_nonzero": n_nonzero,
            })

            if mean_auroc > best_auroc:
                best_auroc = mean_auroc
                best_config = {"alpha": alpha, "C": C, "coefs": coefs,
                               "cv_auroc": mean_auroc}

    # Group-level selection (Bug 5 fix):
    # - Single-feature groups: selected if coef != 0
    # - Multi-feature groups (OneHot): selected if ≥20% of dummies have nonzero coefs
    #   OR if max |coef| > median of all nonzero coefs (strong signal in at least one level)
    all_nonzero = np.abs(best_config["coefs"][best_config["coefs"] != 0])
    median_nonzero = np.median(all_nonzero) if len(all_nonzero) > 0 else 0

    group_selected = {}
    for group_name, indices in groups.items():
        group_coefs = best_config["coefs"][indices]
        n_nonzero = np.sum(group_coefs != 0)
        max_abs_coef = np.max(np.abs(group_coefs))
        proportion_nonzero = n_nonzero / len(indices) if len(indices) > 0 else 0

        if len(indices) == 1:
            selected = group_coefs[0] != 0
        else:
            # Multi-feature group: need meaningful presence
            selected = (proportion_nonzero >= 0.2) or (max_abs_coef > median_nonzero)

        group_selected[group_name] = {
            "selected": bool(selected),
            "n_features": len(indices),
            "n_nonzero": int(n_nonzero),
            "proportion_nonzero": round(float(proportion_nonzero), 3),
            "max_abs_coef": round(float(max_abs_coef), 6),
        }

    return best_config, pd.DataFrame(results), group_selected


def find_stability_regularization(X_train, y_train, target_sparsity=None):
    """
    Find regularization parameters that produce ~sqrt(p) selected features
    per Meinshausen & Bühlmann 2010 recommendation.
    """
    n_features = X_train.shape[1]
    if target_sparsity is None:
        target_sparsity = int(np.sqrt(n_features))

    # Search for C that gives ~sqrt(p) nonzero features at high L1 ratio
    best_C = 0.01
    best_diff = float("inf")
    for C in [0.001, 0.005, 0.01, 0.02, 0.05, 0.1]:
        model = LogisticRegression(
            penalty="elasticnet", C=C, l1_ratio=0.9,
            solver="saga", max_iter=3000,
            random_state=config.RANDOM_STATE,
            class_weight="balanced",
        )
        model.fit(X_train, y_train)
        n_sel = np.sum(model.coef_[0] != 0)
        diff = abs(n_sel - target_sparsity)
        if diff < best_diff:
            best_diff = diff
            best_C = C

    return 0.9, best_C, target_sparsity


def stability_selection(X_train, y_train, feature_names, groups,
                        n_subsamples=50, subsample_ratio=0.5,
                        alpha=None, C=None):
    """
    Stability Selection (Meinshausen & Bühlmann 2010).

    Key implementation details:
    - Regularization calibrated to select ~sqrt(p) features per subsample
      (Meinshausen recommends moderate sparsity, NOT the best-predictive config)
    - Error bound: E[V] ≤ q²/(2π_thr - 1)/p
      where q = average number of features selected per subsample (NOT total ever selected)
    """
    rng = np.random.RandomState(config.RANDOM_STATE)
    n = X_train.shape[0]
    n_features = X_train.shape[1]
    n_sub = int(n * subsample_ratio)

    # Find appropriate regularization for stability selection
    if alpha is None or C is None:
        alpha, C, target = find_stability_regularization(X_train, y_train)
        print(f"    Calibrated regularization: α={alpha}, C={C} (target ~{target} features per run)")

    selection_counts = np.zeros(n_features)
    n_selected_per_run = []

    for b in range(n_subsamples):
        idx = rng.choice(n, size=n_sub, replace=False)
        X_sub, y_sub = X_train[idx], y_train[idx]

        if len(np.unique(y_sub)) < 2:
            continue

        model = LogisticRegression(
            penalty="elasticnet",
            C=C,
            l1_ratio=alpha,
            solver="saga",
            max_iter=3000,
            random_state=config.RANDOM_STATE + b,
            class_weight="balanced",
        )
        model.fit(X_sub, y_sub)
        selected = (model.coef_[0] != 0).astype(int)
        selection_counts += selected
        n_selected_per_run.append(selected.sum())

    n_valid_runs = len(n_selected_per_run)
    selection_prob = selection_counts / n_valid_runs if n_valid_runs > 0 else selection_counts

    # Feature-level results
    feat_stability = pd.DataFrame({
        "feature": feature_names,
        "selection_probability": np.round(selection_prob, 3),
    }).sort_values("selection_probability", ascending=False).reset_index(drop=True)

    # Group-level aggregation
    group_stability = {}
    for group_name, indices in groups.items():
        group_probs = selection_prob[indices]
        max_prob = float(np.max(group_probs))
        mean_prob = float(np.mean(group_probs))
        group_stability[group_name] = {
            "max_selection_prob": round(max_prob, 3),
            "mean_selection_prob": round(mean_prob, 3),
            "stable": max_prob > 0.6,
        }

    # Correct error bound (Bug fix: q = avg features per run, NOT fraction ever selected)
    q = np.mean(n_selected_per_run) if n_selected_per_run else 0
    pi_thr = 0.6
    p = n_features
    expected_false = q**2 / (2 * pi_thr - 1) / p if (2 * pi_thr - 1) > 0 else float("inf")

    print(f"    Avg features selected per run: {q:.1f}")
    print(f"    Meinshausen E[V] bound: {expected_false:.2f}")

    return feat_stability, group_stability, expected_false


def ridge_baseline(X_train, y_train, feature_names):
    """
    Ridge baseline (Harrell's recommendation): no selection, just shrinkage.
    Uses same inner CV as Elastic Net for fair comparison (Bug 3 fix).
    """
    C_values = [0.001, 0.01, 0.1, 1.0, 10.0, 100.0]
    best_auroc = -1
    best_C = None

    cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=config.RANDOM_STATE)

    for C in C_values:
        aurocs = []
        for train_idx, val_idx in cv.split(X_train, y_train):
            model = LogisticRegression(
                penalty="l2", C=C, solver="lbfgs", max_iter=5000,
                random_state=config.RANDOM_STATE, class_weight="balanced",
            )
            model.fit(X_train[train_idx], y_train[train_idx])
            y_prob = model.predict_proba(X_train[val_idx])[:, 1]
            aurocs.append(roc_auc_score(y_train[val_idx], y_prob))

        mean_auroc = np.mean(aurocs)
        if mean_auroc > best_auroc:
            best_auroc = mean_auroc
            best_C = C

    return best_C, best_auroc


def main():
    results_dir = os.path.join(os.path.dirname(__file__), "..", "results")
    os.makedirs(results_dir, exist_ok=True)

    print("Loading processed data...")
    (X_train, y_train, X_valid, y_valid, X_test, y_test,
     feature_names, col_types) = load_processed_data()
    print(f"  Features: {len(feature_names)}, Train samples: {len(y_train)}")

    # Step 0: Near-zero variance filter
    print("\nStep 0: Near-zero variance filter (>99% same value)...")
    X_train, X_valid, X_test, feature_names, dropped_nzv = \
        filter_near_zero_variance(X_train, X_valid, X_test, feature_names)
    print(f"  Dropped {len(dropped_nzv)}: {len(dropped_nzv) + len(feature_names)} → {len(feature_names)}")

    # Build feature groups
    groups = build_feature_groups(feature_names, col_types)
    print(f"  Feature groups (original variables): {len(groups)}")

    # Step 1: Elastic Net CV with grouped structure
    print(f"\nStep 1: Elastic Net CV (α × C grid, 5-fold inner CV)...")
    enet_config, enet_results, group_selected = \
        elastic_net_cv(X_train, y_train, feature_names, groups)
    enet_results.to_csv(os.path.join(results_dir, "elastic_net_cv.csv"), index=False)

    n_groups_selected = sum(1 for v in group_selected.values() if v["selected"])
    n_features_selected = sum(
        v["n_features"] for v in group_selected.values() if v["selected"]
    )
    print(f"  Best: α={enet_config['alpha']}, C={enet_config['C']}, CV AUROC={enet_config['cv_auroc']:.4f}")
    print(f"  Groups selected: {n_groups_selected}/{len(groups)}")
    print(f"  Features selected: {n_features_selected}/{len(feature_names)}")

    print(f"\n  Selected groups (original variables):")
    for g, info in sorted(group_selected.items(), key=lambda x: -x[1]["max_abs_coef"]):
        if info["selected"]:
            print(f"    ✓ {g:40s} ({info['n_features']} features, |coef|_max={info['max_abs_coef']:.4f})")
    print(f"\n  Dropped groups:")
    for g, info in sorted(group_selected.items()):
        if not info["selected"]:
            print(f"    ✗ {g:40s} ({info['n_features']} features)")

    # Step 2: Stability Selection
    print(f"\nStep 2: Stability Selection (50 subsamples × Elastic Net)...")
    print(f"  Calibrating regularization to ~sqrt(p) features per run...")
    feat_stability, group_stability, expected_false = stability_selection(
        X_train, y_train, feature_names, groups,
        n_subsamples=50,
    )
    feat_stability.to_csv(os.path.join(results_dir, "stability_selection.csv"), index=False)

    n_stable_groups = sum(1 for v in group_stability.values() if v["stable"])
    print(f"  Stable groups (max selection prob > 0.6): {n_stable_groups}/{len(groups)}")
    print(f"  Expected false selections (Meinshausen bound): {expected_false:.1f}")

    print(f"\n  Top 15 groups by stability:")
    sorted_groups = sorted(group_stability.items(), key=lambda x: -x[1]["max_selection_prob"])
    for g, info in sorted_groups[:15]:
        bar = "█" * int(info["max_selection_prob"] * 20)
        status = "✓" if info["stable"] else "✗"
        print(f"    {status} {g:40s} prob={info['max_selection_prob']:.3f} {bar}")

    # Step 3: Ridge baseline (no selection) — same inner CV for fair comparison
    print(f"\nStep 3: Ridge baseline (Harrell approach: no selection, all features)...")
    ridge_C, ridge_auroc = ridge_baseline(X_train, y_train, feature_names)
    print(f"  Best Ridge C={ridge_C}, CV AUROC={ridge_auroc:.4f}")

    # Step 4: Compare and decide
    print(f"\n{'='*60}")
    print("COMPARISON: Selection vs No Selection")
    print(f"{'='*60}")

    # Elastic Net: use its CV AUROC (from Step 1) for fair comparison with Ridge CV AUROC
    selected_indices = []
    for g, info in group_selected.items():
        if info["selected"]:
            selected_indices.extend(groups[g])
    selected_indices.sort()
    selected_names = [feature_names[i] for i in selected_indices]

    enet_cv_auroc = enet_config["cv_auroc"]

    print(f"  Ridge (all {len(feature_names)} features):     CV AUROC = {ridge_auroc:.4f}")
    print(f"  Elastic Net ({len(selected_names)} features):  CV AUROC = {enet_cv_auroc:.4f}")
    print(f"  Difference: {enet_cv_auroc - ridge_auroc:+.4f}")

    if enet_cv_auroc >= ridge_auroc - 0.005:
        print(f"\n  → Elastic Net selection retained (no meaningful loss vs Ridge)")
        final_features = selected_names
        final_indices = selected_indices
    else:
        print(f"\n  → Selection causes >0.005 AUROC loss. Using all features (Ridge approach)")
        final_features = feature_names
        final_indices = list(range(len(feature_names)))

    # Save final outputs
    selection_output = {
        "selected_features": final_features,
        "selected_indices": final_indices,
        "n_selected": len(final_features),
        "n_total": len(feature_names),
        "method": "elastic_net_grouped" if len(final_features) < len(feature_names) else "ridge_all",
        "elastic_net_alpha": enet_config["alpha"],
        "elastic_net_C": enet_config["C"],
    }
    with open(os.path.join(results_dir, "selected_features.json"), "w") as f:
        json.dump(selection_output, f, indent=2)

    X_train_sel = X_train[:, final_indices]
    X_valid_sel = X_valid[:, final_indices]
    X_test_sel = X_test[:, final_indices]
    np.savez(
        os.path.join(results_dir, "selected_data.npz"),
        X_train=X_train_sel, y_train=y_train,
        X_valid=X_valid_sel, y_valid=y_valid,
        X_test=X_test_sel, y_test=y_test,
    )

    # Save group-level results (Bug 2 fix: use groups dict for correct membership check)
    final_index_set = set(final_indices)
    group_summary = []
    for g in sorted(groups.keys()):
        enet_sel = group_selected.get(g, {}).get("selected", False)
        stab = group_stability.get(g, {}).get("max_selection_prob", 0)
        # Correct in_final: check if any index of this group is in final_indices
        group_in_final = any(idx in final_index_set for idx in groups[g])
        group_summary.append({
            "group": g,
            "n_features": len(groups[g]),
            "elastic_net_selected": enet_sel,
            "stability_prob": stab,
            "stable": stab > 0.6,
            "in_final": group_in_final,
        })
    pd.DataFrame(group_summary).to_csv(
        os.path.join(results_dir, "group_selection_summary.csv"), index=False)

    # EPV check
    n_events = y_train.sum()
    epv = n_events / len(final_features) if len(final_features) > 0 else 0
    print(f"\n=== EPV Re-check (MLGG-Z01) ===")
    print(f"  Events: {n_events}, Features: {len(final_features)}, EPV: {epv:.1f}")
    print(f"  EPV >= 10? {'✅ YES' if epv >= 10 else '❌ NO'}")

    print(f"\n✅ [MLGG-F03] All feature selection performed on training set only")
    print(f"✅ Elastic Net CV with grouped structure (Zou & Hastie 2005, Yuan & Lin 2006)")
    print(f"✅ Stability Selection with error bound (Meinshausen & Bühlmann 2010)")
    print(f"✅ Ridge baseline comparison (Harrell 2015)")
    print(f"✅ Phase 4 results saved to: {results_dir}")


if __name__ == "__main__":
    main()
