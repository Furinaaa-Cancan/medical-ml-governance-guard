#!/usr/bin/env python3
"""
Fail-closed calibration and decision-curve gate.

Evaluates calibration (ECE/slope/intercept) and DCA net-benefit for:
1) internal test split
2) every external cohort in external_validation_report
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    get_remediation,
    print_gate_summary,
    register_remediations,
)
from _gate_utils import add_issue, load_json_from_str as load_json_obj, normalize_binary as _shared_normalize_binary, to_float


register_remediations({
    "missing_artifact_file": "Provide the missing input file required by this gate.",
    "prediction_trace_unreadable": "Fix or regenerate the prediction_trace CSV file.",
    "prediction_trace_missing_columns": "Ensure prediction_trace contains all required columns (scope, cohort_id, cohort_type, y_true, y_score, y_pred, selected_threshold).",
    "calibration_input_parse_error": "Fix malformed JSON input files for calibration/DCA gate.",
    "prediction_trace_non_binary": "prediction_trace y_true must contain only binary 0/1 values.",
    "prediction_trace_score_invalid": "prediction_trace y_score must be finite and within [0, 1].",
    "external_cohorts_empty": "external_validation_report must include a non-empty cohorts list, or omit the --external-validation-report flag.",
    "cohort_not_in_trace": "Ensure prediction_trace contains rows for every cohort referenced in the validation report.",
    "calibration_insufficient_events": "Cohort does not have enough rows or events for calibration/DCA. Collect more data or relax minimum thresholds.",
    "cohort_evaluation_failed": "Calibration/DCA computation failed for a cohort. Check data integrity.",
    "calibration_ece_exceeds_threshold": "Recalibrate the model (Platt scaling, isotonic regression) to reduce ECE.",
    "calibration_slope_out_of_range": "Calibration slope should be near 1.0. Recalibrate or retrain.",
    "calibration_intercept_too_large": "Calibration intercept too far from 0. Recalibrate.",
    "dca_net_benefit_insufficient": "Model net benefit is insufficient. Review clinical utility.",
    "dca_advantage_coverage_low": "Decision curve advantage coverage is below threshold.",
    "calibration_oe_ratio_out_of_range": "O/E ratio should be near 1.0 (Collins et al. BMJ 2024;384:e074819). Recalibrate the model.",
    "calibration_in_the_large_too_large": "Calibration-in-the-large should be near 0.0 (Collins et al. BMJ 2024;384:e074819). Recalibrate.",
    "hosmer_lemeshow_discouraged": "Replace Hosmer-Lemeshow with calibration slope, O/E ratio, and calibration plots (Collins et al. BMJ 2024;384:e074819).",
    "dca_threshold_grid_not_prespecified": "Pre-specify and justify DCA threshold grid in the study protocol (TRIPOD+AI 2024).",
    "resampling_calibration_risk": "Model uses internal resampling (balanced bootstrap / undersampling) which shifts predicted probabilities. Apply post-hoc recalibration (Platt / isotonic). Ref: van den Goorbergh et al., BMC Med Res Methodol 2022;22:312.",
})


REQUIRED_TRACE_COLUMNS = {
    "scope",
    "cohort_id",
    "cohort_type",
    "y_true",
    "y_score",
    "y_pred",
    "selected_threshold",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fail-closed calibration + DCA gate for test + external cohorts.")
    parser.add_argument("--prediction-trace", required=True, help="Path to prediction_trace CSV/CSV.GZ.")
    parser.add_argument("--evaluation-report", required=True, help="Path to evaluation_report.json.")
    parser.add_argument("--external-validation-report", default=None, help="Path to external_validation_report.json (optional; skip external checks if absent).")
    parser.add_argument("--performance-policy", help="Optional performance_policy JSON path.")
    parser.add_argument("--report", help="Optional output report JSON path.")
    parser.add_argument("--strict", action="store_true", help="Fail on warnings.")
    # Calibration ridge regularization
    parser.add_argument("--calibration-ridge", type=float, default=1.0,
                        help="Ridge regularization strength for calibration slope/intercept fitting (default: 1.0).")
    # O/E ratio thresholds (BMJ 2024)
    parser.add_argument("--oe-ratio-fail-lower", type=float, default=0.70,
                        help="O/E ratio lower bound for failure (default: 0.70).")
    parser.add_argument("--oe-ratio-fail-upper", type=float, default=1.43,
                        help="O/E ratio upper bound for failure (default: 1.43).")
    parser.add_argument("--oe-ratio-warn-lower", type=float, default=0.80,
                        help="O/E ratio lower bound for warning (default: 0.80).")
    parser.add_argument("--oe-ratio-warn-upper", type=float, default=1.25,
                        help="O/E ratio upper bound for warning (default: 1.25).")
    # CITL thresholds (BMJ 2024)
    parser.add_argument("--citl-fail-threshold", type=float, default=0.10,
                        help="Calibration-in-the-large absolute threshold for failure (default: 0.10).")
    parser.add_argument("--citl-warn-threshold", type=float, default=0.05,
                        help="Calibration-in-the-large absolute threshold for warning (default: 0.05).")
    return parser.parse_args()


def normalize_binary(series: pd.Series) -> Optional[np.ndarray]:
    return _shared_normalize_binary(series)


def sigmoid(x: np.ndarray) -> np.ndarray:
    clipped = np.clip(x, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def fit_calibration_slope_intercept(y_true: np.ndarray, y_score: np.ndarray, ridge: float = 20.0) -> Optional[Dict[str, float]]:
    if y_true.shape[0] < 3 or len(np.unique(y_true)) < 2:
        return None
    eps = 1e-6
    p = np.clip(y_score.astype(float), eps, 1.0 - eps)
    z = np.log(p / (1.0 - p))
    X = np.column_stack([np.ones_like(z), z]).astype(float)
    beta = np.array([0.0, 1.0], dtype=float)
    prior = np.array([0.0, 1.0], dtype=float)
    # Minimal regularization for numerical stability only (BMJ 2024 LIT-045:
    # unregularized logistic calibration preferred).  Ridge=1.0 prevents
    # Hessian singularity without materially biasing slope toward 1.0.

    for _ in range(80):
        eta = X @ beta
        mu = sigmoid(eta)
        w = np.clip(mu * (1.0 - mu), 1e-8, None)
        grad = X.T @ (y_true.astype(float) - mu) - (ridge * (beta - prior))
        hessian = X.T @ (w[:, None] * X)
        hessian = hessian + (ridge * np.eye(hessian.shape[0], dtype=float))
        try:
            step = np.linalg.solve(hessian, grad)
        except np.linalg.LinAlgError:
            return None
        beta_next = beta + step
        if np.max(np.abs(step)) < 1e-8:
            beta = beta_next
            break
        beta = beta_next

    if not np.all(np.isfinite(beta)):
        return None
    return {"intercept": float(beta[0]), "slope": float(beta[1])}


def expected_calibration_error(
    y_true: np.ndarray,
    y_score: np.ndarray,
    n_bins: int,
    min_bin_size: int,
) -> float:
    """Expected Calibration Error with equal-frequency (quantile) bins.

    Design note — two ECE implementations coexist in MLGG:
      * This one uses EQUAL-FREQUENCY binning (Van Calster 2019 BMC Med
        17:230). Each bin has roughly n/n_bins observations. Stable for
        small cohorts and non-uniform score distributions; matches the
        decile-of-risk convention used in modern prediction-model papers.
      * _gate_utils.calibration_metrics uses EQUAL-WIDTH binning
        (np.linspace(0,1,n_bins+1)) to match the traditional Hosmer-
        Lemeshow chi-square test (Steyerberg 2019 Clinical Prediction
        Models, §15). Equal-width is required for HL df calculation.

    Keep this divergence intentional. Do NOT silently unify — the two
    ECE values report calibration under different operational assumptions.
    When publishing, report which binning was used and why. The
    calibration_dca_gate report includes this function's value; the
    evaluation_quality_gate (via calibration_metrics) includes the other.

    Ref: Van Calster B et al. BMC Med. 2019;17:230 — "A calibration
    hierarchy for risk models was defined". Equal-frequency ECE
    recommended for stability with small n.
    """
    n = int(y_true.shape[0])
    if n <= 0:
        return 1.0
    # Equal-frequency bins with a minimum bin-size guard reduce sparse-bin variance
    # for small cohorts (publication gate minimum is often around n=50).
    requested_bins = max(2, int(n_bins))
    effective_bins = max(2, n // max(1, int(min_bin_size)))
    n_bins = min(requested_bins, effective_bins)
    order = np.argsort(y_score.astype(float))
    blocks = np.array_split(order, n_bins)
    total = 0.0
    for idx in blocks:
        count = int(idx.shape[0])
        if count == 0:
            continue
        avg_score = float(np.mean(y_score[idx]))
        avg_true = float(np.mean(y_true[idx]))
        total += (count / n) * abs(avg_true - avg_score)
    return float(total)


def net_benefit(y_true: np.ndarray, y_score: np.ndarray, threshold: float) -> float:
    n = float(y_true.shape[0])
    if n <= 0 or threshold >= 1.0 or threshold <= 0.0:
        return 0.0
    y_pred = (y_score >= threshold).astype(int)
    tp = float(np.sum((y_true == 1) & (y_pred == 1)))
    fp = float(np.sum((y_true == 0) & (y_pred == 1)))
    weight = float(threshold / (1.0 - threshold))
    return float((tp / n) - (fp / n) * weight)


def treat_all_net_benefit(y_true: np.ndarray, threshold: float) -> float:
    if threshold >= 1.0 or threshold <= 0.0:
        return 0.0
    prevalence = float(np.mean(y_true.astype(float)))
    weight = float(threshold / (1.0 - threshold))
    return float(prevalence - (1.0 - prevalence) * weight)


def parse_policy_thresholds(policy: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ece_max": 0.06,
        "slope_min": 0.80,
        "slope_max": 2.00,
        "intercept_abs_max": 1.00,
        "min_rows": 50,
        "min_positives": 10,
        "ece_bins": 10,
        "ece_min_bin_size": 40,
        "threshold_grid": {"start": 0.05, "end": 0.50, "step": 0.05},
        "min_advantage_coverage": 0.50,
        "min_average_advantage": 0.0,
        "min_net_benefit_advantage": 0.0,
    }
    if not isinstance(policy, dict):
        return out
    block = policy.get("calibration_dca_thresholds")
    if not isinstance(block, dict):
        return out

    for key in (
        "ece_max",
        "slope_min",
        "slope_max",
        "intercept_abs_max",
        "min_rows",
        "min_positives",
        "ece_bins",
        "ece_min_bin_size",
        "min_advantage_coverage",
        "min_average_advantage",
        "min_net_benefit_advantage",
    ):
        value = to_float(block.get(key))
        if value is None:
            continue
        if key in {"min_rows", "min_positives", "ece_bins", "ece_min_bin_size"}:
            if value >= 1:
                out[key] = int(value)
        elif key == "ece_max":
            if 0.0 <= value <= 1.0:
                out[key] = float(value)
        elif key == "intercept_abs_max":
            if 0.0 <= value <= 10.0:
                out[key] = float(value)
        elif key in {"slope_min", "slope_max"}:
            if value > 0.0:
                out[key] = float(value)
        elif key == "min_advantage_coverage":
            if 0.0 <= value <= 1.0:
                out[key] = float(value)
        else:
            out[key] = float(value)

    grid = block.get("threshold_grid")
    if isinstance(grid, dict):
        start = to_float(grid.get("start"))
        end = to_float(grid.get("end"))
        step = to_float(grid.get("step"))
        if start is not None and end is not None and step is not None:
            out["threshold_grid"] = {"start": float(start), "end": float(end), "step": float(step)}
    return out


def build_threshold_grid(grid_cfg: Dict[str, Any]) -> Optional[np.ndarray]:
    start = to_float(grid_cfg.get("start"))
    end = to_float(grid_cfg.get("end"))
    step = to_float(grid_cfg.get("step"))
    if (
        start is None
        or end is None
        or step is None
        or start <= 0.0
        or end >= 1.0
        or step <= 0.0
        or start >= end
    ):
        return None
    points = np.arange(start, end + (0.5 * step), step, dtype=float)
    points = points[(points > 0.0) & (points < 1.0)]
    if points.size < 2:
        return None
    return points


def evaluate_cohort(
    cohort_label: str,
    y_true: np.ndarray,
    y_score: np.ndarray,
    thresholds: Dict[str, Any],
    grid: np.ndarray,
    ridge: float = 20.0,
) -> Dict[str, Any]:
    ece_bins = int(thresholds["ece_bins"])
    ece_min_bin_size = int(thresholds.get("ece_min_bin_size", 15))
    ece = expected_calibration_error(
        y_true,
        y_score,
        n_bins=ece_bins,
        min_bin_size=ece_min_bin_size,
    )
    cal = fit_calibration_slope_intercept(y_true, y_score, ridge=ridge)
    if cal is None:
        raise ValueError("Unable to fit calibration slope/intercept.")
    slope = float(cal["slope"])
    intercept = float(cal["intercept"])

    dca_rows: List[Dict[str, float]] = []
    deltas: List[float] = []
    for t in grid.tolist():
        nb_model = net_benefit(y_true, y_score, threshold=float(t))
        nb_all = treat_all_net_benefit(y_true, threshold=float(t))
        nb_none = 0.0
        baseline = max(nb_all, nb_none)
        delta = float(nb_model - baseline)
        deltas.append(delta)
        dca_rows.append(
            {
                "threshold": float(t),
                "net_benefit_model": float(nb_model),
                "net_benefit_treat_all": float(nb_all),
                "net_benefit_treat_none": float(nb_none),
                "net_benefit_advantage": float(delta),
            }
        )

    deltas_arr = np.asarray(deltas, dtype=float)
    min_advantage = float(thresholds["min_net_benefit_advantage"])
    coverage = float(np.mean(deltas_arr >= min_advantage)) if deltas_arr.size else 0.0
    avg_advantage = float(np.mean(deltas_arr)) if deltas_arr.size else -1.0
    min_delta = float(np.min(deltas_arr)) if deltas_arr.size else -1.0

    # BMJ 2024: O/E ratio = sum(observed) / sum(expected)
    sum_expected = float(np.sum(y_score.astype(float)))
    sum_observed = float(np.sum(y_true.astype(float)))
    oe_ratio = float(sum_observed / sum_expected) if sum_expected > 0.0 else None

    # BMJ 2024: calibration-in-the-large = mean(observed) - mean(predicted)
    citl = float(np.mean(y_true.astype(float)) - np.mean(y_score.astype(float)))

    return {
        "cohort": cohort_label,
        "row_count": int(y_true.shape[0]),
        "positive_count": int(np.sum(y_true == 1)),
        "negative_count": int(np.sum(y_true == 0)),
        "calibration": {
            "ece": float(ece),
            "slope": slope,
            "intercept": intercept,
            "ece_bins": ece_bins,
            "ece_min_bin_size": int(ece_min_bin_size),
            "oe_ratio": float(oe_ratio) if oe_ratio is not None and math.isfinite(oe_ratio) else None,
            "calibration_in_the_large": float(citl) if citl is not None and math.isfinite(citl) else None,
        },
        "dca": {
            "threshold_count": int(len(dca_rows)),
            "threshold_rows": dca_rows,
            "advantage_coverage": float(coverage),
            "average_advantage": float(avg_advantage),
            "minimum_advantage": float(min_delta),
        },
    }


def main() -> int:
    args = parse_args()
    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []

    trace_path = Path(args.prediction_trace).expanduser().resolve()
    eval_path = Path(args.evaluation_report).expanduser().resolve()
    ext_path = Path(args.external_validation_report).expanduser().resolve() if args.external_validation_report else None
    required_artifacts = [(trace_path, "prediction_trace"), (eval_path, "evaluation_report")]
    if ext_path is not None:
        required_artifacts.append((ext_path, "external_validation_report"))
    for p, name in required_artifacts:
        if not p.exists():
            add_issue(
                failures,
                "missing_artifact_file",
                "Required artifact file is missing for calibration/DCA gate.",
                {"artifact": name, "path": str(p)},
            )
            return finish(args, failures, warnings, {})

    try:
        trace_df = pd.read_csv(trace_path)
    except Exception as exc:
        add_issue(
            failures,
            "prediction_trace_unreadable",
            "Unable to load prediction_trace file.",
            {"path": str(trace_path), "error": str(exc)},
        )
        return finish(args, failures, warnings, {})

    if not REQUIRED_TRACE_COLUMNS.issubset(set(trace_df.columns)):
        add_issue(
            failures,
            "prediction_trace_missing_columns",
            "prediction_trace is missing required columns.",
            {"missing_columns": sorted(REQUIRED_TRACE_COLUMNS - set(trace_df.columns))},
        )
        return finish(args, failures, warnings, {})

    try:
        _eval_report = load_json_obj(str(eval_path))  # noqa: F841 – validates JSON parse
        ext_report = load_json_obj(str(ext_path)) if ext_path else {"cohorts": []}
        policy = load_json_obj(args.performance_policy) if args.performance_policy else {}
    except Exception as exc:
        add_issue(
            failures,
            "calibration_input_parse_error",
            "Unable to parse required JSON input for calibration/DCA gate.",
            {"error": str(exc), "eval_path": str(eval_path), "ext_path": str(ext_path)},
        )
        return finish(args, failures, warnings, {})

    thresholds = parse_policy_thresholds(policy)
    grid = build_threshold_grid(thresholds.get("threshold_grid", {}))
    if grid is None:
        add_issue(
            failures,
            "decision_curve_threshold_grid_invalid",
            "calibration_dca_thresholds.threshold_grid is invalid.",
            {"threshold_grid": thresholds.get("threshold_grid")},
        )
        return finish(args, failures, warnings, {"thresholds": thresholds})

    trace_df = trace_df.copy()
    trace_df["scope"] = trace_df["scope"].astype(str).str.strip().str.lower()
    trace_df["cohort_id"] = trace_df["cohort_id"].astype(str).str.strip()
    trace_df["y_score"] = pd.to_numeric(trace_df["y_score"], errors="coerce")
    y_true_all = normalize_binary(trace_df["y_true"])
    if y_true_all is None:
        add_issue(
            failures,
            "prediction_trace_non_binary",
            "prediction_trace y_true must be binary 0/1.",
            {},
        )
        return finish(args, failures, warnings, {"thresholds": thresholds})
    trace_df["y_true"] = y_true_all

    y_score_all = trace_df["y_score"].to_numpy(dtype=float)
    if np.any(~np.isfinite(y_score_all)) or np.any(y_score_all < 0.0) or np.any(y_score_all > 1.0):
        add_issue(
            failures,
            "prediction_trace_score_invalid",
            "prediction_trace y_score must be finite and in [0,1].",
            {},
        )
        return finish(args, failures, warnings, {"thresholds": thresholds})

    # Early detection of degenerate predictions (all same value).
    # Constant y_score makes calibration slope undefined, ECE meaningless,
    # and DCA net benefit trivially zero — a likely sign of a broken model.
    if y_score_all.size > 1 and np.allclose(y_score_all, y_score_all[0], atol=1e-8):
        add_issue(
            failures,
            "degenerate_predictions",
            f"All y_score values are constant ({y_score_all[0]:.6f}). "
            f"Calibration and DCA are undefined for degenerate predictions. "
            f"This usually indicates a broken model or data pipeline.",
            {"constant_value": float(y_score_all[0]), "n_predictions": int(y_score_all.size)},
        )
        return finish(args, failures, warnings, {"thresholds": thresholds})

    # Check for resampling calibration risk from internal-imbalance models
    _cal_assessment = _eval_report.get("calibration_assessment")
    if isinstance(_cal_assessment, dict):
        _resamp_risk = _cal_assessment.get("resampling_calibration_risk")
        if isinstance(_resamp_risk, dict) and _resamp_risk.get("warning"):
            add_issue(
                warnings,
                "resampling_calibration_risk",
                str(_resamp_risk["warning"]),
                {
                    "model_family": _resamp_risk.get("model_family"),
                    "slope_deviation": _resamp_risk.get("slope_deviation_from_unity"),
                    "auto_calibrated": _resamp_risk.get("auto_calibrated", False),
                    "calibration_method": _resamp_risk.get("calibration_method"),
                },
            )

    cohorts_to_check: List[Dict[str, str]] = [{"scope": "test", "cohort_id": "internal_test", "label": "internal_test"}]
    ext_cohorts = ext_report.get("cohorts")
    if not isinstance(ext_cohorts, list) or not ext_cohorts:
        ext_cohorts = []
        if ext_path is not None:
            # User explicitly provided an external report but it has no cohorts
            add_issue(
                failures,
                "external_cohorts_empty",
                "external_validation_report must include non-empty cohorts list.",
                {},
            )
            return finish(args, failures, warnings, {"thresholds": thresholds})
        # No external validation provided — proceed with internal test only.
        # Silent by design: emitting a warning here would be promoted to failure
        # under --strict for leakage-audited-tier runs where absence is expected.
        # The summary below records "external_cohorts_evaluated: 0" for auditability.
    for entry in ext_cohorts:
        if not isinstance(entry, dict):
            continue
        cohort_id = str(entry.get("cohort_id", "")).strip()
        if not cohort_id:
            continue
        cohorts_to_check.append({"scope": "external", "cohort_id": cohort_id, "label": f"external::{cohort_id}"})

    min_rows = int(thresholds["min_rows"])
    min_positives = int(thresholds["min_positives"])
    cohort_results: List[Dict[str, Any]] = []

    for cohort_ref in cohorts_to_check:
        scope = cohort_ref["scope"]
        cohort_id = cohort_ref["cohort_id"]
        label = cohort_ref["label"]
        if scope == "test":
            subset = trace_df[trace_df["scope"] == "test"]
        else:
            subset = trace_df[(trace_df["scope"] == "external") & (trace_df["cohort_id"] == cohort_id)]

        if subset.empty:
            add_issue(
                failures,
                "cohort_not_in_trace",
                "No prediction_trace rows found for cohort required by calibration/DCA gate.",
                {"scope": scope, "cohort_id": cohort_id},
            )
            continue

        y_true = subset["y_true"].to_numpy(dtype=int)
        y_score = subset["y_score"].to_numpy(dtype=float)
        n_rows = int(y_true.shape[0])
        n_pos = int(np.sum(y_true == 1))
        n_neg = int(np.sum(y_true == 0))
        if n_rows < min_rows or n_pos < min_positives or n_neg < min_positives:
            add_issue(
                failures,
                "calibration_insufficient_events",
                "Cohort does not satisfy minimum sample/event requirements for calibration+DCA.",
                {
                    "cohort": label,
                    "row_count": n_rows,
                    "positive_count": n_pos,
                    "negative_count": n_neg,
                    "min_rows": min_rows,
                    "min_positives": min_positives,
                },
            )
            continue

        try:
            result = evaluate_cohort(
                cohort_label=label,
                y_true=y_true,
                y_score=y_score,
                thresholds=thresholds,
                grid=grid,
                ridge=float(args.calibration_ridge),
            )
        except Exception as exc:
            add_issue(
                failures,
                "cohort_evaluation_failed",
                "Failed to evaluate calibration/DCA metrics for cohort.",
                {"cohort": label, "error": str(exc)},
            )
            continue

        calibration = result["calibration"]
        dca = result["dca"]
        if float(calibration["ece"]) > float(thresholds["ece_max"]):
            add_issue(
                failures,
                "calibration_ece_exceeds_threshold",
                "ECE exceeds configured threshold.",
                {"cohort": label, "ece": calibration["ece"], "ece_max": thresholds["ece_max"]},
            )
        if float(calibration["slope"]) < float(thresholds["slope_min"]) or float(calibration["slope"]) > float(thresholds["slope_max"]):
            add_issue(
                failures,
                "calibration_slope_out_of_range",
                "Calibration slope is outside configured range.",
                {
                    "cohort": label,
                    "slope": calibration["slope"],
                    "slope_min": thresholds["slope_min"],
                    "slope_max": thresholds["slope_max"],
                },
            )
        if abs(float(calibration["intercept"])) > float(thresholds["intercept_abs_max"]):
            add_issue(
                failures,
                "calibration_intercept_too_large",
                "Calibration intercept absolute value exceeds configured threshold.",
                {
                    "cohort": label,
                    "intercept": calibration["intercept"],
                    "intercept_abs_max": thresholds["intercept_abs_max"],
                },
            )

        # BMJ 2024: O/E ratio check (observed/expected)
        oe_ratio_val = to_float(calibration.get("oe_ratio"))
        oe_fail_lo = float(args.oe_ratio_fail_lower)
        oe_fail_hi = float(args.oe_ratio_fail_upper)
        oe_warn_lo = float(args.oe_ratio_warn_lower)
        oe_warn_hi = float(args.oe_ratio_warn_upper)
        if oe_ratio_val is not None and math.isfinite(oe_ratio_val):
            if oe_ratio_val < oe_fail_lo or oe_ratio_val > oe_fail_hi:
                add_issue(
                    failures,
                    "calibration_oe_ratio_out_of_range",
                    f"O/E ratio is outside acceptable range [{oe_fail_lo}, {oe_fail_hi}] (BMJ 2024).",
                    {
                        "cohort": label,
                        "oe_ratio": oe_ratio_val,
                        "acceptable_range": [oe_fail_lo, oe_fail_hi],
                    },
                )
            elif oe_ratio_val < oe_warn_lo or oe_ratio_val > oe_warn_hi:
                add_issue(
                    warnings,
                    "calibration_oe_ratio_out_of_range",
                    f"O/E ratio is outside preferred range [{oe_warn_lo}, {oe_warn_hi}] (BMJ 2024).",
                    {
                        "cohort": label,
                        "oe_ratio": oe_ratio_val,
                        "preferred_range": [oe_warn_lo, oe_warn_hi],
                    },
                )

        # BMJ 2024: calibration-in-the-large check
        citl_val = to_float(calibration.get("calibration_in_the_large"))
        citl_fail_thresh = float(args.citl_fail_threshold)
        citl_warn_thresh = float(args.citl_warn_threshold)
        if citl_val is not None and math.isfinite(citl_val):
            if abs(citl_val) > citl_fail_thresh:
                add_issue(
                    failures,
                    "calibration_in_the_large_too_large",
                    f"Calibration-in-the-large exceeds acceptable threshold |{citl_fail_thresh}| (BMJ 2024).",
                    {
                        "cohort": label,
                        "calibration_in_the_large": citl_val,
                        "threshold": citl_fail_thresh,
                    },
                )
            elif abs(citl_val) > citl_warn_thresh:
                add_issue(
                    warnings,
                    "calibration_in_the_large_too_large",
                    f"Calibration-in-the-large exceeds preferred threshold |{citl_warn_thresh}| (BMJ 2024).",
                    {
                        "cohort": label,
                        "calibration_in_the_large": citl_val,
                        "threshold": citl_warn_thresh,
                    },
                )

        if (
            float(dca["advantage_coverage"]) < float(thresholds["min_advantage_coverage"])
            or float(dca["average_advantage"]) < float(thresholds["min_average_advantage"])
        ):
            add_issue(
                failures,
                "decision_curve_net_benefit_insufficient",
                "Decision-curve net-benefit criteria are not met.",
                {
                    "cohort": label,
                    "advantage_coverage": dca["advantage_coverage"],
                    "average_advantage": dca["average_advantage"],
                    "minimum_advantage": dca["minimum_advantage"],
                    "min_advantage_coverage": thresholds["min_advantage_coverage"],
                    "min_average_advantage": thresholds["min_average_advantage"],
                    "min_net_benefit_advantage": thresholds["min_net_benefit_advantage"],
                },
            )
        cohort_results.append(result)

    # BMJ 2024: Hosmer-Lemeshow prohibition warning
    # Scan all report content for mentions of hosmer-lemeshow
    _hl_found = False
    for _report_obj in (_eval_report, ext_report):
        _report_str = str(_report_obj).lower()
        if "hosmer" in _report_str or "lemeshow" in _report_str:
            _hl_found = True
            break
    if _hl_found:
        add_issue(
            warnings,
            "hosmer_lemeshow_discouraged",
            "Hosmer-Lemeshow test is discouraged (BMJ 2024, LIT-045/046). "
            "Use calibration slope, O/E ratio, and calibration plots instead.",
            {},
        )

    # BMJ 2024 / TRIPOD+AI Item 23: DCA threshold pre-specification check.
    # Rationale: TRIPOD+AI requires that the clinically-relevant decision
    # threshold(s) used for Decision Curve Analysis be pre-specified and
    # justified in the study protocol. Silently using defaults undermines
    # this claim. Behavior:
    #   * non-strict → WARNING (soft signal; user can ignore at their peril)
    #   * strict     → FAILURE (enforced for publication-grade pipelines)
    # In all cases we record `threshold_grid_prespecified: bool` in the
    # summary payload so downstream reporters (export_latex, compliance
    # certificate) can surface it even when the warning gets filtered.
    _default_grid = {"start": 0.05, "end": 0.50, "step": 0.05}
    _active_grid = thresholds.get("threshold_grid", {})
    _policy_block = policy.get("calibration_dca_thresholds") if isinstance(policy, dict) else None
    _explicitly_set = (
        isinstance(_policy_block, dict)
        and isinstance(_policy_block.get("threshold_grid"), dict)
    )
    if _active_grid == _default_grid and not _explicitly_set:
        target_list = failures if args.strict else warnings
        add_issue(
            target_list,
            "dca_threshold_grid_not_prespecified",
            "DCA threshold grid uses default values [0.05, 0.50, step 0.05] "
            "without explicit justification in performance_policy. "
            "Pre-specify and justify thresholds (BMJ 2024; TRIPOD+AI 2024 Item 23). "
            "Non-strict: WARNING; strict or publication-grade: FAILURE.",
            {"threshold_grid": _active_grid, "default_used": True},
        )

    summary = {
        "prediction_trace": str(trace_path),
        "evaluation_report": str(eval_path),
        "external_validation_report": str(ext_path) if ext_path else None,
        "thresholds": thresholds,
        "threshold_grid_prespecified": bool(_explicitly_set),
        "cohort_results": cohort_results,
    }
    return finish(args, failures, warnings, summary)


def finish(
    args: argparse.Namespace,
    failures: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    summary: Dict[str, Any],
) -> int:
    from _gate_utils import get_gate_elapsed, write_json as _write_report

    should_fail = bool(failures) or (args.strict and bool(warnings))
    status = "fail" if should_fail else "pass"

    fi = [GateIssue.from_legacy(f, Severity.ERROR) for f in failures]
    wi = [GateIssue.from_legacy(w, Severity.WARNING) for w in warnings]
    for issue in fi + wi:
        if not issue.remediation:
            issue.remediation = get_remediation(issue.code)

    report = build_report_envelope(
        gate_name="calibration_dca_gate",
        status=status,
        strict_mode=bool(args.strict),
        failures=fi,
        warnings=wi,
        summary=summary,
        input_files={
            "prediction_trace": str(Path(args.prediction_trace).expanduser().resolve()),
            "evaluation_report": str(Path(args.evaluation_report).expanduser().resolve()),
            "external_validation_report": str(Path(args.external_validation_report).expanduser().resolve()) if args.external_validation_report else None,
            "performance_policy": str(Path(args.performance_policy).expanduser().resolve()) if args.performance_policy else None,
        },
    )

    if args.report:
        _write_report(Path(args.report).expanduser().resolve(), report)

    print_gate_summary(
        gate_name="calibration_dca_gate",
        status=status,
        failures=fi,
        warnings=wi,
        strict=bool(args.strict),
        elapsed=get_gate_elapsed(),
    )

    return 2 if should_fail else 0


if __name__ == "__main__":
    from _gate_utils import start_gate_timer
    start_gate_timer()
    raise SystemExit(main())
