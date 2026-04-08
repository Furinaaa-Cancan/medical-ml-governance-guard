#!/usr/bin/env python3
"""
SHAP Interpretability Gate — Multi-model feature importance with ensemble aggregation.

Computes SHAP values across multiple model families (RF, XGBoost, CatBoost,
LightGBM, etc.), applies proportional normalization per model, then averages
to produce a robust ensemble feature importance ranking.

Outputs:
  - JSON gate report (envelope v2.0.0) with full importance tables
  - 4 publication-grade CSV tables:
      Table A: Ensemble Feature Importance (main table)
      Table B: Per-Model Detailed SHAP
      Table C: Cross-Model Rank Agreement
      Table D: Individual Case Explanations

References:
  - Lundberg & Lee, "A Unified Approach to Interpreting Model Predictions"
    (NeurIPS 2017)
  - Lundberg et al., "From Local Explanations to Global Understanding with
    Explainable AI for Trees" (Nature Machine Intelligence, 2020)
  - PMC11513550, "Practical guide to SHAP analysis" (2024) — proportional
    normalization methodology
  - arxiv 2505.24612, "Multi-criteria Rank-based Aggregation for XAI" (2025)
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import csv
import json
import math
import sys
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    print_gate_summary,
    register_remediations,
)
from _gate_utils import add_issue, start_gate_timer, get_gate_elapsed, write_json

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GATE_NAME = "shap_interpretability_gate"
GATE_VERSION = "1.0.0"

_TREE_CLASS_FRAGMENTS = (
    "RandomForest", "ExtraTrees", "XGB", "LGBM", "LGBClassifier",
    "CatBoost", "HistGradientBoosting", "DecisionTree",
    "GradientBoosting", "AdaBoost",
)
_LINEAR_CLASS_FRAGMENTS = ("LogisticRegression",)

_DEFAULT_BACKGROUND_SAMPLES = 200
_DEFAULT_EXPLAIN_SAMPLES = 500
_DEFAULT_TOP_N = 20
_DEFAULT_MIN_RANK_CORRELATION = 0.5
_DEFAULT_RANK_CORRELATION_FAIL = 0.3
_KERNEL_EXPLAINER_MAX_SAMPLES = 100
_KERNEL_EXPLAINER_TIMEOUT_PER_MODEL = 300  # seconds

# ---------------------------------------------------------------------------
# Remediations
# ---------------------------------------------------------------------------

register_remediations({
    "SHAP_IMPORT_FAILED":
        "Install the shap package: pip install 'shap>=0.42'. "
        "It is listed as an optional dependency in pyproject.toml.",
    "SHAP_POOL_LOAD_FAILED":
        "Verify the model pool file exists and was produced by "
        "train_select_evaluate.py --model-pool-out.",
    "SHAP_POOL_SCHEMA_INVALID":
        "Model pool must have schema_version=1 with keys: "
        "families, features, selected_model_id.",
    "SHAP_FEATURE_MISMATCH":
        "Features in model pool do not match columns in the data file. "
        "Ensure train/test CSVs match the pipeline that produced model_pool.pkl.",
    "SHAP_ALL_ZEROS":
        "SHAP values are all zeros for a model. This usually means the model "
        "is trivial (predicts a constant). Check model training.",
    "SHAP_NAN_DETECTED":
        "NaN in SHAP values indicates a computation failure. "
        "Try reducing --explain-samples or check for data quality issues.",
    "SHAP_SINGLE_MODEL":
        "Model pool contains only 1 family. Ensemble averaging is degenerate. "
        "Add more model families to the training pool for robust importance.",
    "SHAP_RANK_DISAGREEMENT":
        "Models disagree on feature importance ranking (low Kendall tau). "
        "This may indicate that importance is model-dependent rather than "
        "data-driven. Investigate feature interactions.",
    "SHAP_EXTREME_CONCENTRATION":
        "A single feature dominates >50%% of total importance. "
        "Investigate whether this is a leaky feature or legitimate signal.",
    "SHAP_SUSPICIOUS_TOP_FEATURE":
        "A top-ranked feature matches a known post-outcome or temporal pattern "
        "from the feature lineage spec. Review for potential data leakage.",
    "SHAP_COMPUTATION_FAILED":
        "SHAP computation failed for a model family. Check model compatibility "
        "and data integrity.",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(v: Any) -> Optional[float]:
    """Safe float conversion with isfinite guard."""
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _classify_direction(
    ensemble_signed: float,
    per_model_signed: List[float],
) -> str:
    """Classify feature direction as positive / negative / mixed.

    positive: ensemble_signed > 0 AND all per-model values >= 0
    negative: ensemble_signed < 0 AND all per-model values <= 0
    mixed: models disagree on direction
    """
    if not per_model_signed:
        return "indeterminate"
    all_non_negative = all(v >= 0 for v in per_model_signed)
    all_non_positive = all(v <= 0 for v in per_model_signed)
    if ensemble_signed > 0 and all_non_negative:
        return "positive"
    elif ensemble_signed < 0 and all_non_positive:
        return "negative"
    else:
        return "mixed"


def _pick_explainer(clf: Any, background: "np.ndarray") -> Any:
    """Select the appropriate SHAP explainer for a classifier.

    TreeExplainer for tree-based models, LinearExplainer for linear models,
    KernelExplainer as fallback for everything else.
    """
    import shap

    name = type(clf).__name__
    if any(t in name for t in _TREE_CLASS_FRAGMENTS):
        try:
            return shap.TreeExplainer(clf)
        except Exception:
            # CatBoost and some tree models have known TreeExplainer
            # compatibility issues; fall back to KernelExplainer
            return shap.KernelExplainer(
                lambda x: clf.predict_proba(x)[:, 1],
                background,
            )
    elif any(t in name for t in _LINEAR_CLASS_FRAGMENTS):
        return shap.LinearExplainer(clf, background)
    else:
        return shap.KernelExplainer(
            lambda x: clf.predict_proba(x)[:, 1],
            background,
        )


def _extract_clf_and_transform(
    estimator: Any,
    X: "np.ndarray",
) -> Tuple[Any, "np.ndarray"]:
    """Extract the classifier from a Pipeline and transform data through
    all preceding steps (imputer, scaler, etc.).

    If estimator is not a Pipeline, return it directly with untransformed data.
    """
    from sklearn.pipeline import Pipeline

    if isinstance(estimator, Pipeline):
        steps = list(estimator.named_steps.keys())
        clf_key = steps[-1]
        clf = estimator.named_steps[clf_key]
        if len(steps) > 1:
            # Transform through all steps except the last (classifier)
            from sklearn.pipeline import Pipeline as Pipe
            pre_pipe = Pipe([(k, estimator.named_steps[k]) for k in steps[:-1]])
            X_transformed = pre_pipe.transform(X)
        else:
            X_transformed = X
        return clf, X_transformed
    else:
        return estimator, X


def _compute_shap_for_family(
    family: str,
    estimator: Any,
    X_background: "np.ndarray",
    X_explain: "np.ndarray",
    feature_names: List[str],
    seed: int = 42,
) -> Optional[Dict[str, Any]]:
    """Compute SHAP values for a single model family.

    Returns dict with raw_shap (n_explain x n_features), or None on failure.
    """
    import shap

    clf, bg_transformed = _extract_clf_and_transform(estimator, X_background)
    _, ex_transformed = _extract_clf_and_transform(estimator, X_explain)

    # For KernelExplainer, limit samples
    name = type(clf).__name__
    is_kernel = not (
        any(t in name for t in _TREE_CLASS_FRAGMENTS)
        or any(t in name for t in _LINEAR_CLASS_FRAGMENTS)
    )
    if is_kernel and ex_transformed.shape[0] > _KERNEL_EXPLAINER_MAX_SAMPLES:
        rng = np.random.default_rng(seed)
        idx = rng.choice(
            ex_transformed.shape[0],
            _KERNEL_EXPLAINER_MAX_SAMPLES,
            replace=False,
        )
        ex_transformed = ex_transformed[idx]

    explainer = _pick_explainer(clf, bg_transformed)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        shap_values = explainer.shap_values(ex_transformed)

    # Handle binary classification: shap_values may be a list [class_0, class_1]
    if isinstance(shap_values, list):
        shap_values = shap_values[1]  # positive class

    shap_values = np.asarray(shap_values, dtype=np.float64)

    # Handle 3D output (some explainers return (n_samples, n_features, n_classes))
    if shap_values.ndim == 3:
        shap_values = shap_values[:, :, 1]

    expected_value = None
    if hasattr(explainer, "expected_value"):
        ev = explainer.expected_value
        if isinstance(ev, (list, np.ndarray)):
            expected_value = _to_float(ev[1] if len(ev) > 1 else ev[0])
        else:
            expected_value = _to_float(ev)

    return {
        "raw_shap": shap_values,  # (n_explain, n_features)
        "expected_value": expected_value,
        "n_explained": shap_values.shape[0],
        "explainer_type": type(explainer).__name__,
    }


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def _aggregate_shap(
    family_results: Dict[str, Dict[str, Any]],
    feature_names: List[str],
) -> Dict[str, Any]:
    """Aggregate SHAP values across model families.

    Dual-track:
      1. Per-model mean(|SHAP|) → L1-normalize to proportions → average
      2. Per-model mean(SHAP) → average for directional information
    """
    n_features = len(feature_names)

    per_model_abs: Dict[str, np.ndarray] = {}
    per_model_signed: Dict[str, np.ndarray] = {}
    per_model_proportion: Dict[str, np.ndarray] = {}

    for family, result in family_results.items():
        raw = result["raw_shap"]  # (n_samples, n_features)
        abs_mean = np.mean(np.abs(raw), axis=0)  # (n_features,)
        signed_mean = np.mean(raw, axis=0)

        per_model_abs[family] = abs_mean
        per_model_signed[family] = signed_mean

        # L1-normalize: convert to proportions (sum=1)
        total = abs_mean.sum()
        if total > 0:
            per_model_proportion[family] = abs_mean / total
        else:
            per_model_proportion[family] = np.zeros(n_features)

    # Ensemble: equal-weight average of proportions
    prop_matrix = np.stack(list(per_model_proportion.values()))  # (n_models, n_features)
    ensemble_proportion = np.mean(prop_matrix, axis=0)

    # Ensemble signed: average of raw signed means
    signed_matrix = np.stack(list(per_model_signed.values()))
    ensemble_signed = np.mean(signed_matrix, axis=0)

    # Rank by ensemble proportion (descending)
    ranking = np.argsort(-ensemble_proportion)

    return {
        "per_model_abs": per_model_abs,
        "per_model_signed": per_model_signed,
        "per_model_proportion": per_model_proportion,
        "ensemble_proportion": ensemble_proportion,
        "ensemble_signed": ensemble_signed,
        "ranking": ranking,
    }


def _compute_rank_correlations(
    per_model_abs: Dict[str, np.ndarray],
) -> List[Dict[str, Any]]:
    """Compute pairwise Kendall tau rank correlations between model families."""
    from scipy.stats import kendalltau

    families = sorted(per_model_abs.keys())
    correlations: List[Dict[str, Any]] = []

    for i in range(len(families)):
        for j in range(i + 1, len(families)):
            tau, p = kendalltau(
                per_model_abs[families[i]],
                per_model_abs[families[j]],
            )
            correlations.append({
                "family_a": families[i],
                "family_b": families[j],
                "kendall_tau": round(float(tau), 4),
                "p_value": float(p),
            })

    return correlations


# ---------------------------------------------------------------------------
# Individual case explanations
# ---------------------------------------------------------------------------

def _build_case_explanations(
    family_results: Dict[str, Dict[str, Any]],
    selected_model_id: str,
    feature_names: List[str],
    y_true: "np.ndarray",
    y_score: "np.ndarray",
    top_k: int = 5,
    top_features_per_case: int = 5,
) -> List[Dict[str, Any]]:
    """Build individual case explanations using the selected (best) model.

    Selects top-K highest risk + top-K lowest risk cases from the test set,
    reports their top contributing features with SHAP values.
    """
    # Find the family containing the selected model
    selected_family = None
    for family, result in family_results.items():
        if result.get("model_id") == selected_model_id:
            selected_family = family
            break

    # Fallback: use first available family
    if selected_family is None:
        selected_family = next(iter(family_results))

    raw_shap = family_results[selected_family]["raw_shap"]
    n_samples = raw_shap.shape[0]

    # Ensure arrays match
    n_usable = min(n_samples, len(y_true), len(y_score))

    # Top-K highest risk
    high_risk_idx = np.argsort(-y_score[:n_usable])[:top_k]
    # Top-K lowest risk
    low_risk_idx = np.argsort(y_score[:n_usable])[:top_k]

    cases: List[Dict[str, Any]] = []

    for label, indices in [("high_risk", high_risk_idx), ("low_risk", low_risk_idx)]:
        for idx in indices:
            sample_shap = raw_shap[idx]
            # Top contributing features by |SHAP|
            top_feat_idx = np.argsort(-np.abs(sample_shap))[:top_features_per_case]
            drivers = []
            for fi in top_feat_idx:
                drivers.append({
                    "feature": feature_names[fi],
                    "shap_value": round(float(sample_shap[fi]), 6),
                    "abs_shap": round(float(abs(sample_shap[fi])), 6),
                    "direction": "increases risk" if sample_shap[fi] > 0 else "decreases risk",
                })
            cases.append({
                "case_index": int(idx),
                "risk_category": label,
                "y_true": int(y_true[idx]),
                "y_score": round(float(y_score[idx]), 4),
                "explaining_model": selected_family,
                "top_drivers": drivers,
            })

    return cases


# ---------------------------------------------------------------------------
# CSV Table Writers
# ---------------------------------------------------------------------------

def _write_table_a(
    path: Path,
    feature_names: List[str],
    ranking: np.ndarray,
    ensemble_proportion: np.ndarray,
    ensemble_signed: np.ndarray,
    per_model_proportion: Dict[str, np.ndarray],
    per_model_signed: Dict[str, np.ndarray],
    top_n: int,
) -> None:
    """Table A: Ensemble Feature Importance — main publication table."""
    families = sorted(per_model_proportion.keys())
    header = [
        "Rank",
        "Feature",
        "Ensemble_Proportion",
        "Direction",
    ]
    for f in families:
        header.append(f"{f}_Proportion")

    # Methodology annotation row
    meta_row = [
        "# Method: L1-normalized mean|SHAP| per model, equal-weight averaged across "
        f"{len(families)} families ({', '.join(families)}). "
        "Direction: positive/negative/mixed based on cross-model sign agreement. "
        "Ref: Lundberg & Lee 2017; PMC11513550 proportional normalization."
    ]

    rows = []
    for rank_pos, feat_idx in enumerate(ranking[:top_n], start=1):
        feat = feature_names[feat_idx]
        ens_prop = ensemble_proportion[feat_idx]
        ens_sign = ensemble_signed[feat_idx]

        per_model_sign_vals = [per_model_signed[f][feat_idx] for f in families]
        direction = _classify_direction(ens_sign, per_model_sign_vals)

        row = [
            str(rank_pos),
            feat,
            f"{ens_prop:.4f}",
            direction,
        ]
        for f in families:
            row.append(f"{per_model_proportion[f][feat_idx]:.4f}")

        rows.append(row)

    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write(meta_row[0] + "\n")
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _write_table_b(
    path: Path,
    feature_names: List[str],
    ranking: np.ndarray,
    per_model_abs: Dict[str, np.ndarray],
    per_model_proportion: Dict[str, np.ndarray],
    per_model_signed: Dict[str, np.ndarray],
) -> None:
    """Table B: Per-Model Detailed SHAP — supplementary table for reviewers."""
    families = sorted(per_model_abs.keys())
    header = ["Feature"]
    for f in families:
        header.extend([
            f"{f}_MeanAbsSHAP",
            f"{f}_Proportion",
            f"{f}_MeanSignedSHAP",
            f"{f}_Rank",
        ])

    # Compute per-model ranks
    per_model_rank: Dict[str, np.ndarray] = {}
    for f in families:
        order = np.argsort(-per_model_abs[f])
        ranks = np.empty_like(order)
        ranks[order] = np.arange(1, len(order) + 1)
        per_model_rank[f] = ranks

    rows = []
    for feat_idx in ranking:
        feat = feature_names[feat_idx]
        row = [feat]
        for f in families:
            row.extend([
                f"{per_model_abs[f][feat_idx]:.6f}",
                f"{per_model_proportion[f][feat_idx]:.4f}",
                f"{per_model_signed[f][feat_idx]:.6f}",
                str(int(per_model_rank[f][feat_idx])),
            ])
        rows.append(row)

    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write("# Per-model SHAP detail: raw mean|SHAP|, L1-normalized proportion, "
                 "signed mean SHAP, and within-model rank for all features.\n")
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _write_table_c(
    path: Path,
    rank_correlations: List[Dict[str, Any]],
    per_model_abs: Dict[str, np.ndarray],
    top_n: int = 10,
) -> None:
    """Table C: Cross-Model Rank Agreement — methodological evidence."""
    families = sorted(per_model_abs.keys())

    # Compute top-N overlap counts
    per_model_top_n: Dict[str, set] = {}
    for f in families:
        top_idx = set(np.argsort(-per_model_abs[f])[:top_n].tolist())
        per_model_top_n[f] = top_idx

    header = [
        "Model_A",
        "Model_B",
        "Kendall_Tau",
        "P_Value",
        f"Top{top_n}_Overlap_Count",
        f"Top{top_n}_Jaccard",
    ]
    rows = []
    for rc in rank_correlations:
        fa, fb = rc["family_a"], rc["family_b"]
        overlap = len(per_model_top_n.get(fa, set()) & per_model_top_n.get(fb, set()))
        union = len(per_model_top_n.get(fa, set()) | per_model_top_n.get(fb, set()))
        jaccard = overlap / union if union > 0 else 0.0

        p_val = rc["p_value"]
        p_str = f"{p_val:.2e}" if p_val < 0.001 else f"{p_val:.4f}"

        rows.append([
            fa,
            fb,
            f"{rc['kendall_tau']:.4f}",
            p_str,
            str(overlap),
            f"{jaccard:.4f}",
        ])

    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write("# Cross-model rank agreement: Kendall tau and Top-N Jaccard overlap. "
                 "tau > 0.7 = strong, 0.5-0.7 = moderate, < 0.5 = weak.\n")
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


def _write_table_d(
    path: Path,
    cases: List[Dict[str, Any]],
) -> None:
    """Table D: Individual Case Explanations — clinical narrative."""
    header = [
        "Case_Index",
        "Risk_Category",
        "Y_True",
        "Predicted_Risk_Score",
        "Explaining_Model",
        "Driver_1_Feature", "Driver_1_SHAP", "Driver_1_Direction",
        "Driver_2_Feature", "Driver_2_SHAP", "Driver_2_Direction",
        "Driver_3_Feature", "Driver_3_SHAP", "Driver_3_Direction",
    ]
    rows = []
    for case in cases:
        row = [
            str(case["case_index"]),
            case["risk_category"],
            str(case["y_true"]),
            f"{case['y_score']:.4f}",
            case["explaining_model"],
        ]
        drivers = case.get("top_drivers", [])
        for i in range(3):
            if i < len(drivers):
                d = drivers[i]
                row.extend([
                    d["feature"],
                    f"{d['shap_value']:.6f}",
                    d["direction"],
                ])
            else:
                row.extend(["", "", ""])
        rows.append(row)

    with path.open("w", newline="", encoding="utf-8") as fh:
        fh.write("# Individual case explanations: top-K highest/lowest risk cases "
                 "with top-3 SHAP drivers. Model = pipeline-selected best.\n")
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def _run_validation_checks(
    failures: List[Dict[str, Any]],
    warnings_list: List[Dict[str, Any]],
    family_results: Dict[str, Dict[str, Any]],
    agg: Dict[str, Any],
    rank_correlations: List[Dict[str, Any]],
    feature_names: List[str],
    feature_lineage_spec: Optional[Dict[str, Any]],
    min_rank_correlation: float,
    rank_correlation_fail: float,
    strict: bool,
) -> None:
    """Run all validation checks, populating failures and warnings."""

    # Check: single model
    if len(family_results) == 1:
        add_issue(
            warnings_list, "SHAP_SINGLE_MODEL",
            "Model pool contains only 1 family; ensemble averaging is degenerate.",
            {"family_count": 1},
        )

    # Check: all zeros per model
    for family, result in family_results.items():
        raw = result["raw_shap"]
        if np.allclose(raw, 0.0):
            add_issue(
                failures, "SHAP_ALL_ZEROS",
                f"Model '{family}' produced all-zero SHAP values.",
                {"family": family},
            )

    # Check: NaN detected
    for family, result in family_results.items():
        raw = result["raw_shap"]
        nan_count = int(np.isnan(raw).sum())
        if nan_count > 0:
            add_issue(
                failures, "SHAP_NAN_DETECTED",
                f"Model '{family}' has {nan_count} NaN values in SHAP output.",
                {"family": family, "nan_count": nan_count},
            )

    # Check: rank disagreement
    if rank_correlations:
        taus = [rc["kendall_tau"] for rc in rank_correlations]
        # Guard against NaN (identical rankings produce tau=NaN in scipy)
        finite_taus = [t for t in taus if np.isfinite(t)]
        if len(finite_taus) < len(taus):
            add_issue(
                warnings_list, "SHAP_RANK_IDENTICAL",
                f"{len(taus) - len(finite_taus)} model pair(s) produced identical "
                f"or degenerate importance rankings (Kendall tau = NaN).",
                {"nan_count": len(taus) - len(finite_taus)},
            )
        mean_tau = float(np.mean(finite_taus)) if finite_taus else 0.0
        if mean_tau < rank_correlation_fail:
            add_issue(
                failures, "SHAP_RANK_DISAGREEMENT",
                f"Mean Kendall tau = {mean_tau:.3f} < {rank_correlation_fail} "
                f"(fail threshold). Models strongly disagree on feature importance.",
                {"mean_kendall_tau": mean_tau, "threshold": rank_correlation_fail},
            )
        elif mean_tau < min_rank_correlation:
            add_issue(
                warnings_list, "SHAP_RANK_DISAGREEMENT",
                f"Mean Kendall tau = {mean_tau:.3f} < {min_rank_correlation} "
                f"(warn threshold). Models moderately disagree on feature importance.",
                {"mean_kendall_tau": mean_tau, "threshold": min_rank_correlation},
            )

    # Check: extreme concentration
    ensemble_prop = agg["ensemble_proportion"]
    max_prop = float(ensemble_prop.max()) if len(ensemble_prop) > 0 else 0.0
    if max_prop > 0.5:
        max_idx = int(np.argmax(ensemble_prop))
        add_issue(
            warnings_list, "SHAP_EXTREME_CONCENTRATION",
            f"Feature '{feature_names[max_idx]}' accounts for "
            f"{max_prop:.1%} of total ensemble importance.",
            {"feature": feature_names[max_idx], "proportion": max_prop},
        )

    # Check: suspicious top features (from feature lineage spec)
    if feature_lineage_spec:
        post_outcome_features = set()
        for entry in feature_lineage_spec.get("features", []):
            if entry.get("temporal_category") in ("post_outcome", "post-outcome"):
                post_outcome_features.add(entry.get("name", ""))
            if entry.get("leakage_risk", "").lower() in ("high", "critical"):
                post_outcome_features.add(entry.get("name", ""))

        if post_outcome_features:
            ranking = agg["ranking"]
            for rank_pos in range(min(5, len(ranking))):
                feat = feature_names[ranking[rank_pos]]
                if feat in post_outcome_features:
                    add_issue(
                        warnings_list, "SHAP_SUSPICIOUS_TOP_FEATURE",
                        f"Top-{rank_pos + 1} feature '{feat}' is flagged as "
                        f"post-outcome in feature lineage spec.",
                        {"feature": feat, "rank": rank_pos + 1},
                    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="SHAP Interpretability Gate: multi-model feature importance.",
    )

    inp = parser.add_argument_group("Input files")
    inp.add_argument(
        "--model-pool", required=True,
        help="Path to model_pool.pkl (produced by train_select_evaluate.py --model-pool-out).",
    )
    inp.add_argument(
        "--train-data", required=True,
        help="Training data CSV (for SHAP background). Must contain feature columns.",
    )
    inp.add_argument(
        "--test-data", required=True,
        help="Test data CSV (for SHAP explanations). Must contain feature + target columns.",
    )
    inp.add_argument("--target-col", required=True, help="Target column name.")
    inp.add_argument(
        "--prediction-trace",
        help="Optional prediction_trace.csv(.gz) for aligning y_score with test data.",
    )
    inp.add_argument(
        "--feature-lineage-spec",
        help="Optional feature lineage JSON for suspicious-feature detection.",
    )

    cfg = parser.add_argument_group("SHAP configuration")
    cfg.add_argument(
        "--background-samples", type=int, default=_DEFAULT_BACKGROUND_SAMPLES,
        help=f"Number of training samples for SHAP background (default {_DEFAULT_BACKGROUND_SAMPLES}).",
    )
    cfg.add_argument(
        "--explain-samples", type=int, default=_DEFAULT_EXPLAIN_SAMPLES,
        help=f"Max test samples to explain (default {_DEFAULT_EXPLAIN_SAMPLES}).",
    )
    cfg.add_argument(
        "--top-n", type=int, default=_DEFAULT_TOP_N,
        help=f"Number of top features in Table A (default {_DEFAULT_TOP_N}).",
    )
    cfg.add_argument(
        "--case-top-k", type=int, default=5,
        help="Number of highest/lowest risk cases in Table D (default 5).",
    )
    cfg.add_argument(
        "--min-rank-correlation", type=float, default=_DEFAULT_MIN_RANK_CORRELATION,
        help=f"Warn if mean Kendall tau < this (default {_DEFAULT_MIN_RANK_CORRELATION}).",
    )
    cfg.add_argument(
        "--rank-correlation-fail", type=float, default=_DEFAULT_RANK_CORRELATION_FAIL,
        help=f"Fail if mean Kendall tau < this (default {_DEFAULT_RANK_CORRELATION_FAIL}).",
    )

    pdp = parser.add_argument_group("PDP/ICE (complementary to SHAP)")
    pdp.add_argument(
        "--pdp-top-k", type=int, default=5,
        help="Number of top SHAP features for PDP/ICE computation (default 5). Set 0 to disable.",
    )
    pdp.add_argument(
        "--pdp-grid-points", type=int, default=20,
        help="Number of grid points per feature for PDP (default 20).",
    )

    misc = parser.add_argument_group("Reproducibility")
    misc.add_argument(
        "--random-seed", type=int, default=42,
        help="Random seed for background/explain subsampling (default 42). "
             "Set to match pipeline seed for full reproducibility.",
    )

    out = parser.add_argument_group("Output")
    out.add_argument("--report", help="Path to write JSON gate report.")
    out.add_argument("--output-dir", help="Directory for CSV tables (default: same as --report parent).")
    out.add_argument("--strict", action="store_true", help="Promote warnings to failures.")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# PDP / ICE computation (complementary to SHAP)
# ---------------------------------------------------------------------------

def _compute_pdp_ice(
    families: Dict[str, Dict[str, Any]],
    X_data: "np.ndarray",
    feature_names: List[str],
    top_feature_indices: List[int],
    grid_points: int = 20,
    warnings_list: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Compute Partial Dependence for top features across all model families.

    Uses sklearn.inspection.partial_dependence (kind='average') for PDP
    and (kind='individual') for ICE summary statistics.

    Returns list of dicts, one per (feature, family) pair, suitable for CSV.
    """
    import numpy as _np

    try:
        from sklearn.inspection import partial_dependence
    except ImportError:
        if warnings_list is not None:
            add_issue(
                warnings_list,
                "PDP_SKLEARN_MISSING",
                "sklearn.inspection not available; PDP/ICE skipped.",
                {},
            )
        return []

    rows: List[Dict[str, Any]] = []

    for family_name, family_info in sorted(families.items()):
        estimator = family_info.get("estimator")
        if estimator is None:
            continue

        for feat_idx in top_feature_indices:
            feat_name = feature_names[feat_idx]

            # Check feature has variance
            feat_vals = X_data[:, feat_idx]
            if _np.std(feat_vals) < 1e-12:
                if warnings_list is not None:
                    add_issue(
                        warnings_list,
                        "PDP_FEATURE_CONSTANT",
                        f"Feature '{feat_name}' has near-zero variance; PDP is degenerate.",
                        {"feature": feat_name, "family": family_name},
                    )
                continue

            try:
                pd_result = partial_dependence(
                    estimator, X_data, [feat_idx],
                    grid_resolution=grid_points,
                    kind="average",
                )
                grid_vals = pd_result["grid_values"][0]
                pd_vals = pd_result["average"][0]

                for gi in range(len(grid_vals)):
                    rows.append({
                        "family": family_name,
                        "feature": feat_name,
                        "feature_value": round(float(grid_vals[gi]), 6),
                        "pd_value": round(float(pd_vals[gi]), 6),
                    })

            except Exception as exc:
                if warnings_list is not None:
                    add_issue(
                        warnings_list,
                        "PDP_COMPUTATION_FAILED",
                        f"PDP failed for '{feat_name}' in '{family_name}': {exc}",
                        {"feature": feat_name, "family": family_name, "error": str(exc)},
                    )

    return rows


def _write_table_e(path: Path, pdp_rows: List[Dict[str, Any]]) -> None:
    """Write Table E: PDP marginal effects."""
    import csv as _csv

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = _csv.DictWriter(fh, fieldnames=["family", "feature", "feature_value", "pd_value"])
        writer.writeheader()
        for row in pdp_rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    failures: List[Dict[str, Any]] = []
    warnings_list: List[Dict[str, Any]] = []

    # --- Check shap import ---
    try:
        import shap  # noqa: F401
    except ImportError:
        add_issue(
            failures, "SHAP_IMPORT_FAILED",
            "The 'shap' package is not installed.",
            {"install_cmd": "pip install 'shap>=0.42'"},
        )
        return _finish(args, failures, warnings_list, {})

    # --- Load model pool ---
    try:
        import joblib
        pool_path = Path(args.model_pool).expanduser().resolve()
        model_pool = joblib.load(pool_path)
    except Exception as exc:
        add_issue(
            failures, "SHAP_POOL_LOAD_FAILED",
            f"Failed to load model pool: {exc}",
            {"path": str(args.model_pool), "error": str(exc)},
        )
        return _finish(args, failures, warnings_list, {})

    # Validate pool schema
    required_keys = {"schema_version", "families", "features"}
    if not required_keys.issubset(set(model_pool.keys())):
        add_issue(
            failures, "SHAP_POOL_SCHEMA_INVALID",
            f"Model pool missing keys: {required_keys - set(model_pool.keys())}",
            {"present_keys": list(model_pool.keys())},
        )
        return _finish(args, failures, warnings_list, {})

    feature_names: List[str] = list(model_pool["features"])
    families: Dict[str, Any] = model_pool["families"]
    selected_model_id = model_pool.get("selected_model_id", "")
    n_features = len(feature_names)

    if not families:
        add_issue(
            failures, "SHAP_POOL_SCHEMA_INVALID",
            "Model pool has no families.",
            {},
        )
        return _finish(args, failures, warnings_list, {})

    # --- Load data ---
    import pandas as pd

    try:
        train_df = pd.read_csv(Path(args.train_data).expanduser().resolve())
    except Exception as exc:
        add_issue(
            failures, "file_not_found",
            f"Failed to load training data: {exc}",
            {"path": str(args.train_data)},
        )
        return _finish(args, failures, warnings_list, {})

    try:
        test_df = pd.read_csv(Path(args.test_data).expanduser().resolve())
    except Exception as exc:
        add_issue(
            failures, "file_not_found",
            f"Failed to load test data: {exc}",
            {"path": str(args.test_data)},
        )
        return _finish(args, failures, warnings_list, {})

    # Validate feature columns exist
    missing_train = set(feature_names) - set(train_df.columns)
    missing_test = set(feature_names) - set(test_df.columns)
    if missing_train or missing_test:
        add_issue(
            failures, "SHAP_FEATURE_MISMATCH",
            "Features in model pool not found in data.",
            {
                "missing_in_train": sorted(missing_train)[:10],
                "missing_in_test": sorted(missing_test)[:10],
            },
        )
        return _finish(args, failures, warnings_list, {})

    # Extract feature matrices
    X_train_full = train_df[feature_names].values.astype(np.float64)
    X_test_full = test_df[feature_names].values.astype(np.float64)

    # Subsample background (seed from CLI for pipeline reproducibility)
    rng = np.random.default_rng(args.random_seed)
    bg_n = min(args.background_samples, X_train_full.shape[0])
    bg_idx = rng.choice(X_train_full.shape[0], bg_n, replace=False)
    X_background = X_train_full[bg_idx]

    # Subsample explain set
    ex_n = min(args.explain_samples, X_test_full.shape[0])
    if ex_n < X_test_full.shape[0]:
        ex_idx = rng.choice(X_test_full.shape[0], ex_n, replace=False)
    else:
        ex_idx = np.arange(X_test_full.shape[0])
    X_explain = X_test_full[ex_idx]

    # Extract y_true and y_score for case explanations
    target_col = args.target_col
    if target_col in test_df.columns:
        y_true = test_df[target_col].values[ex_idx]
    else:
        y_true = np.full(ex_n, -1)

    # Try to get y_score from prediction trace or from models
    y_score = None
    if args.prediction_trace:
        try:
            trace_path = Path(args.prediction_trace).expanduser().resolve()
            trace_df = pd.read_csv(trace_path)
            test_trace = trace_df[trace_df["scope"] == "test"]
            if "y_score" in test_trace.columns and len(test_trace) >= ex_n:
                y_score = test_trace["y_score"].values[:X_test_full.shape[0]][ex_idx]
        except Exception as exc:
            print(f"[WARN] prediction trace load: {exc}", file=sys.stderr)

    # --- Compute SHAP per family ---
    family_results: Dict[str, Dict[str, Any]] = {}

    for family_name, family_info in families.items():
        estimator = family_info["estimator"]
        model_id = family_info.get("model_id", family_name)

        try:
            result = _compute_shap_for_family(
                family=family_name,
                estimator=estimator,
                X_background=X_background,
                X_explain=X_explain,
                feature_names=feature_names,
                seed=args.random_seed,
            )
            if result is not None:
                result["model_id"] = model_id
                family_results[family_name] = result
                print(f"  SHAP computed: {family_name} ({result['explainer_type']}, "
                      f"n={result['n_explained']})")
        except Exception as exc:
            add_issue(
                warnings_list, "SHAP_COMPUTATION_FAILED",
                f"SHAP computation failed for '{family_name}': {exc}",
                {"family": family_name, "error": str(exc)},
            )

    if not family_results:
        add_issue(
            failures, "SHAP_COMPUTATION_FAILED",
            "SHAP computation failed for ALL model families.",
            {},
        )
        return _finish(args, failures, warnings_list, {})

    # --- Aggregate ---
    agg = _aggregate_shap(family_results, feature_names)

    # --- Rank correlations (with FDR-BH correction) ---
    rank_correlations = []
    if len(family_results) >= 2:
        rank_correlations = _compute_rank_correlations(agg["per_model_abs"])
        # Apply FDR-BH correction when multiple pairwise comparisons exist
        if len(rank_correlations) >= 2:
            from _gate_utils import fdr_bh_correction
            raw_pvals = [rc["p_value"] for rc in rank_correlations]
            fdr_result = fdr_bh_correction(raw_pvals, alpha=0.05)
            for idx, rc in enumerate(rank_correlations):
                rc["p_value_adjusted"] = round(fdr_result["pvalues_adjusted"][idx], 6)
                rc["significant_after_fdr"] = fdr_result["rejected"][idx]

    # --- PDP / ICE computation (complementary to SHAP) ---
    pdp_rows: List[Dict[str, Any]] = []
    pdp_top_k = getattr(args, "pdp_top_k", 5)
    if pdp_top_k > 0 and len(agg["ranking"]) > 0:
        top_feat_indices = list(agg["ranking"][:pdp_top_k])
        pdp_rows = _compute_pdp_ice(
            families=families,
            X_data=X_explain,
            feature_names=feature_names,
            top_feature_indices=top_feat_indices,
            grid_points=getattr(args, "pdp_grid_points", 20),
            warnings_list=warnings_list,
        )

    # --- y_score fallback: use selected model to predict ---
    if y_score is None:
        # Use first available family's estimator to predict
        first_family = next(iter(families))
        est = families[first_family]["estimator"]
        try:
            from sklearn.pipeline import Pipeline
            if isinstance(est, Pipeline):
                y_score = est.predict_proba(X_explain)[:, 1]
            else:
                y_score = est.predict_proba(X_explain)[:, 1]
        except Exception:
            y_score = np.full(ex_n, 0.5)

    # --- Individual case explanations ---
    cases = _build_case_explanations(
        family_results=family_results,
        selected_model_id=selected_model_id,
        feature_names=feature_names,
        y_true=y_true,
        y_score=y_score,
        top_k=args.case_top_k,
    )

    # --- Feature lineage spec ---
    feature_lineage_spec = None
    if args.feature_lineage_spec:
        try:
            fl_path = Path(args.feature_lineage_spec).expanduser().resolve()
            with fl_path.open("r", encoding="utf-8") as fh:
                feature_lineage_spec = json.load(fh)
        except Exception as exc:
            print(f"[WARN] feature lineage spec load: {exc}", file=sys.stderr)

    # --- Validation checks ---
    _run_validation_checks(
        failures=failures,
        warnings_list=warnings_list,
        family_results=family_results,
        agg=agg,
        rank_correlations=rank_correlations,
        feature_names=feature_names,
        feature_lineage_spec=feature_lineage_spec,
        min_rank_correlation=args.min_rank_correlation,
        rank_correlation_fail=args.rank_correlation_fail,
        strict=args.strict,
    )

    # --- Write CSV tables ---
    output_dir = Path(args.output_dir) if args.output_dir else (
        Path(args.report).parent if args.report else Path(".")
    )
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_table_a(
        path=output_dir / "shap_table_a_ensemble_importance.csv",
        feature_names=feature_names,
        ranking=agg["ranking"],
        ensemble_proportion=agg["ensemble_proportion"],
        ensemble_signed=agg["ensemble_signed"],
        per_model_proportion=agg["per_model_proportion"],
        per_model_signed=agg["per_model_signed"],
        top_n=args.top_n,
    )

    _write_table_b(
        path=output_dir / "shap_table_b_per_model_detail.csv",
        feature_names=feature_names,
        ranking=agg["ranking"],
        per_model_abs=agg["per_model_abs"],
        per_model_proportion=agg["per_model_proportion"],
        per_model_signed=agg["per_model_signed"],
    )

    if rank_correlations:
        _write_table_c(
            path=output_dir / "shap_table_c_rank_agreement.csv",
            rank_correlations=rank_correlations,
            per_model_abs=agg["per_model_abs"],
            top_n=min(10, n_features),
        )

    if cases:
        _write_table_d(
            path=output_dir / "shap_table_d_case_explanations.csv",
            cases=cases,
        )

    if pdp_rows:
        _write_table_e(
            path=output_dir / "pdp_table_e_marginal_effects.csv",
            pdp_rows=pdp_rows,
        )

    print(f"  Tables written to: {output_dir}/")

    # --- Build summary ---
    ranking = agg["ranking"]
    families_analyzed = sorted(family_results.keys())
    mean_tau = (
        float(np.mean([rc["kendall_tau"] for rc in rank_correlations]))
        if rank_correlations else None
    )

    ensemble_top = []
    for rank_pos, feat_idx in enumerate(ranking[:args.top_n], start=1):
        per_model_sign_vals = [
            agg["per_model_signed"][f][feat_idx] for f in families_analyzed
        ]
        direction = _classify_direction(
            agg["ensemble_signed"][feat_idx],
            per_model_sign_vals,
        )
        ensemble_top.append({
            "rank": rank_pos,
            "feature": feature_names[feat_idx],
            "ensemble_proportion": round(float(agg["ensemble_proportion"][feat_idx]), 6),
            "ensemble_signed_mean": round(float(agg["ensemble_signed"][feat_idx]), 6),
            "direction": direction,
        })

    per_model_summary = {}
    for f in families_analyzed:
        f_ranking = np.argsort(-agg["per_model_abs"][f])
        top_feats = []
        for i in range(min(args.top_n, n_features)):
            fi = f_ranking[i]
            top_feats.append({
                "rank": i + 1,
                "feature": feature_names[fi],
                "mean_abs_shap": round(float(agg["per_model_abs"][f][fi]), 6),
                "proportion": round(float(agg["per_model_proportion"][f][fi]), 6),
                "mean_signed_shap": round(float(agg["per_model_signed"][f][fi]), 6),
            })
        per_model_summary[f] = {
            "model_id": family_results[f].get("model_id", f),
            "explainer_type": family_results[f].get("explainer_type", "unknown"),
            "n_explained": family_results[f].get("n_explained", 0),
            "top_features": top_feats,
        }

    summary = {
        "model_count": len(family_results),
        "families_analyzed": families_analyzed,
        "feature_count": n_features,
        "test_samples_explained": int(X_explain.shape[0]),
        "background_samples_used": int(X_background.shape[0]),
        "mean_kendall_tau": round(mean_tau, 4) if mean_tau is not None else None,
        "ensemble_top_features": ensemble_top,
        "per_model_importance": per_model_summary,
        "rank_correlations": rank_correlations,
        "individual_cases_count": len(cases),
        "tables_written": {
            "table_a": str(output_dir / "shap_table_a_ensemble_importance.csv"),
            "table_b": str(output_dir / "shap_table_b_per_model_detail.csv"),
            "table_c": str(output_dir / "shap_table_c_rank_agreement.csv") if rank_correlations else None,
            "table_d": str(output_dir / "shap_table_d_case_explanations.csv") if cases else None,
            "table_e_pdp": str(output_dir / "pdp_table_e_marginal_effects.csv") if pdp_rows else None,
        },
        "pdp_ice": {
            "enabled": pdp_top_k > 0,
            "top_k_features": pdp_top_k,
            "grid_points": getattr(args, "pdp_grid_points", 20),
            "n_pdp_rows": len(pdp_rows),
        },
    }

    return _finish(args, failures, warnings_list, summary)


# ---------------------------------------------------------------------------
# Finish
# ---------------------------------------------------------------------------

def _finish(
    args: argparse.Namespace,
    failures: List[Dict[str, Any]],
    warnings_list: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> int:
    should_fail = bool(failures) or (args.strict and bool(warnings_list))
    status = "fail" if should_fail else "pass"

    fi = [GateIssue.from_legacy(f, Severity.ERROR) for f in failures]
    wi = [GateIssue.from_legacy(w, Severity.WARNING) for w in warnings_list]

    report = build_report_envelope(
        gate_name=GATE_NAME,
        status=status,
        strict_mode=bool(args.strict),
        failures=fi,
        warnings=wi,
        summary=summary,
        input_files={
            "model_pool": str(getattr(args, "model_pool", "")),
            "train_data": str(getattr(args, "train_data", "")),
            "test_data": str(getattr(args, "test_data", "")),
        },
        gate_version=GATE_VERSION,
    )

    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(report_path, report)

    print_gate_summary(
        gate_name=GATE_NAME,
        status=status,
        failures=fi,
        warnings=wi,
        strict=bool(args.strict),
        elapsed=get_gate_elapsed(),
    )

    return 2 if should_fail else 0


if __name__ == "__main__":
    start_gate_timer()
    raise SystemExit(main())
