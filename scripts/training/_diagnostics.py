"""Statistical diagnostics for binary prediction model comparison.

Pure-function module extracted from train_select_evaluate.py — no shared
state, no sklearn estimators, no I/O. Each function takes plain numpy
arrays of (y_true, proba_*) and returns a JSON-serializable dict.

Functions are kept underscore-prefixed (e.g. _delong_test) to preserve
the existing call convention in train_select_evaluate.py and the test
file (tests access them via `tse._delong_test`, where tse is imported
from train_select_evaluate via re-export).

Functions:
    _net_reclassification_improvement: NRI vs reference model (Pencina 2008).
    _integrated_discrimination_improvement: IDI (discrimination slope delta).
    _delong_test: ROC-AUC comparison (DeLong 1988).
    _mcnemar_test: Classifier disagreement test (with Edwards correction).

Citations:
    DeLong et al. (1988) Biometrics 44:837-845.
    Pencina et al. (2008) Stat Med 27:157-172.
"""
from __future__ import annotations

from typing import Any, Dict

import numpy as np


def _net_reclassification_improvement(
    y_true: "np.ndarray",
    proba_new: "np.ndarray",
    proba_ref: "np.ndarray",
    threshold: float = 0.5,
) -> Dict[str, Any]:
    """Compute Net Reclassification Improvement (NRI) vs a reference model.

    Pencina et al. (2008) Statistics in Medicine.
    Category-free (continuous) NRI is also computed.

    Args:
        y_true: Binary ground truth labels.
        proba_new: Predicted probabilities from the new model.
        proba_ref: Predicted probabilities from the reference model.
        threshold: Risk threshold for category-based NRI.

    Returns:
        Dict with NRI_events, NRI_nonevents, NRI_total, and continuous NRI.
    """
    events = y_true == 1
    nonevents = y_true == 0
    # Category-based NRI
    cat_new = (proba_new >= threshold).astype(int)
    cat_ref = (proba_ref >= threshold).astype(int)
    up_events = int(np.sum((cat_new > cat_ref) & events))
    down_events = int(np.sum((cat_new < cat_ref) & events))
    up_nonevents = int(np.sum((cat_new > cat_ref) & nonevents))
    down_nonevents = int(np.sum((cat_new < cat_ref) & nonevents))
    n_events = max(int(np.sum(events)), 1)
    n_nonevents = max(int(np.sum(nonevents)), 1)
    nri_events = (up_events - down_events) / n_events
    nri_nonevents = (down_nonevents - up_nonevents) / n_nonevents
    nri_total = nri_events + nri_nonevents
    # Continuous NRI (category-free)
    diff = proba_new - proba_ref
    cnri_events = float(np.mean(diff[events])) if np.sum(events) > 0 else 0.0
    cnri_nonevents = float(-np.mean(diff[nonevents])) if np.sum(nonevents) > 0 else 0.0
    cnri_total = cnri_events + cnri_nonevents
    return {
        "threshold": float(threshold),
        "nri_events": round(float(nri_events), 4),
        "nri_nonevents": round(float(nri_nonevents), 4),
        "nri_total": round(float(nri_total), 4),
        "continuous_nri_events": round(float(cnri_events), 4),
        "continuous_nri_nonevents": round(float(cnri_nonevents), 4),
        "continuous_nri_total": round(float(cnri_total), 4),
        "reclassification_table": {
            "events_up": up_events,
            "events_down": down_events,
            "nonevents_up": up_nonevents,
            "nonevents_down": down_nonevents,
        },
    }


def _integrated_discrimination_improvement(
    y_true: "np.ndarray",
    proba_new: "np.ndarray",
    proba_ref: "np.ndarray",
) -> Dict[str, Any]:
    """Compute Integrated Discrimination Improvement (IDI).

    Pencina et al. (2008) Statistics in Medicine.
    IDI = (IS_new - IS_ref) where IS = mean(p|events) - mean(p|non-events).
    IDI measures the improvement in discrimination slope between two models.

    Required by top-tier journals (JAMA, Lancet) when comparing prediction models.

    Args:
        y_true: Binary ground truth labels.
        proba_new: Predicted probabilities from the new (candidate) model.
        proba_ref: Predicted probabilities from the reference (baseline) model.

    Returns:
        Dict with IDI, IS_new, IS_ref, and relative IDI.
    """
    events = y_true == 1
    nonevents = y_true == 0
    n_events = int(np.sum(events))
    n_nonevents = int(np.sum(nonevents))

    if n_events < 1 or n_nonevents < 1:
        return {
            "idi": None,
            "is_new": None,
            "is_ref": None,
            "relative_idi": None,
            "note": "insufficient_events_or_nonevents",
        }

    # Discrimination slope (integrated sensitivity - integrated 1-specificity)
    is_new = float(np.mean(proba_new[events]) - np.mean(proba_new[nonevents]))
    is_ref = float(np.mean(proba_ref[events]) - np.mean(proba_ref[nonevents]))
    idi = is_new - is_ref
    relative_idi = idi / is_ref if is_ref != 0 else None

    return {
        "idi": round(float(idi), 6),
        "discrimination_slope_new": round(is_new, 6),
        "discrimination_slope_ref": round(is_ref, 6),
        "relative_idi": round(float(relative_idi), 4) if relative_idi is not None else None,
        "interpretation": (
            "new_model_better" if idi > 0
            else "reference_model_better" if idi < 0
            else "no_difference"
        ),
    }


def _delong_test(
    y_true: "np.ndarray",
    proba_a: "np.ndarray",
    proba_b: "np.ndarray",
) -> Dict[str, Any]:
    """DeLong test for comparing two ROC-AUC values.

    DeLong et al. (1988) — standard for AUC comparison in clinical ML.
    Nature Medicine / Lancet require this when comparing models.

    Args:
        y_true: Binary ground truth labels.
        proba_a: Predicted probabilities from model A (new).
        proba_b: Predicted probabilities from model B (reference).

    Returns:
        Dict with auc_a, auc_b, z_statistic, p_value.
    """
    from scipy import stats as _stats
    pos = np.where(y_true == 1)[0]
    neg = np.where(y_true == 0)[0]
    m = len(pos)
    k = len(neg)
    if m < 2 or k < 2:
        return {"auc_a": None, "auc_b": None, "z_statistic": None, "p_value": None}
    # Structural components (Mann-Whitney U-statistic based, vectorized)
    def _placements(proba: "np.ndarray") -> "np.ndarray":
        scores_pos = proba[pos]
        scores_neg = proba[neg]
        # shape: (m, k) — broadcast comparison
        gt = (scores_pos[:, None] > scores_neg[None, :]).astype(float)
        eq = (scores_pos[:, None] == scores_neg[None, :]).astype(float)
        return np.mean(gt + 0.5 * eq, axis=1)
    def _placements_neg(proba: "np.ndarray") -> "np.ndarray":
        scores_pos = proba[pos]
        scores_neg = proba[neg]
        # shape: (k, m) — broadcast comparison
        lt = (scores_neg[:, None] < scores_pos[None, :]).astype(float)
        eq = (scores_neg[:, None] == scores_pos[None, :]).astype(float)
        return np.mean(lt + 0.5 * eq, axis=1)
    v10_a = _placements(proba_a)
    v10_b = _placements(proba_b)
    v01_a = _placements_neg(proba_a)
    v01_b = _placements_neg(proba_b)
    auc_a = float(np.mean(v10_a))
    auc_b = float(np.mean(v10_b))
    # Covariance matrix of AUC difference
    s10 = np.cov(np.column_stack([v10_a, v10_b]), rowvar=False, ddof=1)
    s01 = np.cov(np.column_stack([v01_a, v01_b]), rowvar=False, ddof=1)
    s = s10 / m + s01 / k
    diff = auc_a - auc_b
    var_diff = float(s[0, 0] + s[1, 1] - 2 * s[0, 1])
    if var_diff <= 0:
        return {"auc_a": round(auc_a, 6), "auc_b": round(auc_b, 6),
                "auc_diff": round(float(diff), 6),
                "z_statistic": None, "p_value": 1.0, "significant_at_005": False}
    z = diff / np.sqrt(var_diff)
    p = float(2 * _stats.norm.sf(abs(z)))
    return {
        "auc_a": round(auc_a, 6),
        "auc_b": round(auc_b, 6),
        "auc_diff": round(float(diff), 6),
        "z_statistic": round(float(z), 4),
        "p_value": round(p, 6),
        "significant_at_005": bool(p < 0.05),
    }


def _mcnemar_test(
    y_true: "np.ndarray",
    pred_a: "np.ndarray",
    pred_b: "np.ndarray",
) -> Dict[str, Any]:
    """McNemar test for comparing two classifiers' disagreements.

    Tests whether the two classifiers make the same types of errors.

    Args:
        y_true: Binary ground truth labels.
        pred_a: Binary predictions from model A (new).
        pred_b: Binary predictions from model B (reference).

    Returns:
        Dict with contingency table, chi2 statistic, p_value.
    """
    from scipy import stats as _stats
    correct_a = (pred_a == y_true).astype(int)
    correct_b = (pred_b == y_true).astype(int)
    # b = A correct, B wrong; c = A wrong, B correct
    b = int(np.sum((correct_a == 1) & (correct_b == 0)))
    c = int(np.sum((correct_a == 0) & (correct_b == 1)))
    if b + c == 0:
        return {"b": b, "c": c, "chi2": 0.0, "p_value": 1.0, "significant_at_005": False}
    # Edwards correction
    chi2 = float((abs(b - c) - 1) ** 2 / (b + c))
    p = float(_stats.chi2.sf(chi2, df=1))
    return {
        "b_a_correct_b_wrong": b,
        "c_a_wrong_b_correct": c,
        "chi2": round(chi2, 4),
        "p_value": round(p, 6),
        "significant_at_005": bool(p < 0.05),
    }
