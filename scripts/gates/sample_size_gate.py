#!/usr/bin/env python3
"""
Fail-closed sample size adequacy gate for publication-grade medical prediction.

Validates that the dataset has sufficient sample size relative to the number
of predictors, following Riley et al. (2019, 2025) EPV criteria and
FDA/MHRA/Health Canada Good ML Practice principles.

References:
- Riley et al., BMJ 2019: Minimum sample size for binary prediction models
- Riley et al., Lancet Digital Health 2025: Sample size for AI prediction
- Tsegaye et al., J Clin Epidemiol 2025: ML models in oncology need larger samples
"""
from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from _gate_utils import add_issue, get_gate_elapsed, load_json_from_path as load_json_object, write_json as _write_report
from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    get_remediation,
    print_gate_summary,
    register_remediations,
)


register_remediations({
    "missing_evaluation_report": (
        "Provide --evaluation-report pointing to evaluation_report.json."
    ),
    "invalid_evaluation_report": (
        "Fix JSON syntax in evaluation_report.json."
    ),
    "missing_sample_size_info": (
        "evaluation_report.json must contain 'sample_size_adequacy' or "
        "sufficient metadata (n_train, n_features) for EPV computation."
    ),
    "epv_below_minimum": (
        "Events per variable (EPV) is below the minimum threshold. "
        "Options: 1) Collect more data, 2) Reduce predictors via feature selection, "
        "3) Use penalized regression to reduce effective parameters. "
        "Reference: Riley et al. 2019 recommends EPV >= 10 for binary outcomes."
    ),
    "epv_below_recommended": (
        "EPV is below the recommended level for robust ML models. "
        "Consider increasing sample size or reducing feature count. "
        "Reference: Tsegaye et al. 2025 showed ML models need even larger samples."
    ),
    "total_sample_too_small": (
        "Total sample size is below the minimum for reliable prediction modeling. "
        "At minimum, need 100+ events and 100+ non-events across all splits."
    ),
    "events_too_few": (
        "Too few positive events for reliable model development. "
        "Consider: 1) Broader case definition, 2) Longer observation window, "
        "3) Multi-center data collection."
    ),
    "test_set_events_too_few": (
        "Test set has insufficient events for reliable performance estimation. "
        "Bootstrap CI widths will be unreliable with <50 events in test."
    ),
    "shrinkage_factor_low": (
        "Estimated shrinkage factor is below 0.9, indicating >10% expected "
        "overfitting. Consider: penalized regression, reduced predictor set, "
        "or larger sample. Reference: Riley et al. 2019."
    ),
    "ext_val_events_too_few": (
        "External validation cohort has fewer than 100 events. "
        "Minimum 100 events needed for reliable validation. "
        "Reference: Riley et al. BMJ 2024 Part 3 (LIT-047)."
    ),
    "ext_val_non_events_too_few": (
        "External validation cohort has fewer than 100 non-events. "
        "Minimum 100 non-events needed for reliable validation. "
        "Reference: Riley et al. BMJ 2024 Part 3 (LIT-047)."
    ),
    "ext_val_events_low_for_calibration": (
        "External validation cohort has fewer than 200 events, "
        "which may be insufficient for reliable calibration curves. "
        "Reference: Riley et al. BMJ 2024 Part 3 (LIT-047)."
    ),
    "ext_val_non_events_low_for_calibration": (
        "External validation cohort has fewer than 200 non-events, "
        "which may be insufficient for reliable calibration curves. "
        "Reference: Riley et al. BMJ 2024 Part 3 (LIT-047)."
    ),
    "c_statistic_ci_too_wide": (
        "C-statistic confidence interval width exceeds 0.10, indicating "
        "imprecise discrimination estimation in external validation. "
        "Consider increasing validation sample size. "
        "Reference: Riley et al. BMJ 2024 Part 3 (LIT-047)."
    ),
    "calibration_slope_ci_too_wide": (
        "Calibration slope confidence interval width exceeds 0.30, "
        "indicating imprecise calibration estimation in external validation. "
        "Consider increasing validation sample size. "
        "Reference: Riley et al. BMJ 2024 Part 3 (LIT-047)."
    ),
    "missing_data_inflate_sample": (
        "Consider inflating sample size by 1/(1-missing%) to account for "
        "missing data. Reference: Riley et al. BMJ 2024 (LIT-047)."
    ),
})


DEFAULT_THRESHOLDS: Dict[str, float] = {
    "epv_minimum": 10.0,
    "epv_recommended": 20.0,
    "min_total_events": 100,
    "min_total_non_events": 100,
    "min_test_events": 50,
    "min_train_samples": 200,
    "shrinkage_factor_target": 0.90,
}


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _estimate_shrinkage(n_events: int, n_features: int) -> Optional[float]:
    """Approximate shrinkage factor using Van Houwelingen heuristic.

    S ≈ (E - p) / E where E = events, p = parameters (number of features).

    NOTE: This is the Van Houwelingen (1993) heuristic, NOT the iterative
    Riley et al. (2019) criterion which also accounts for the anticipated
    R-squared (Cox-Snell) and prevalence. The Riley criterion requires
    iterative computation and knowledge of the expected model performance,
    which is unavailable at the sample-size gate stage. The Van Houwelingen
    formula serves as a conservative lower-bound estimate: if S < 0.9 under
    this simpler formula, it will also fail under Riley's stricter criterion.

    Reference: Riley RD et al. BMJ 2019;368:m441 — Criterion (i).
    """
    if n_events <= 0 or n_features <= 0:
        return None
    if n_events <= n_features:
        return 0.0
    return (n_events - n_features) / n_events


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate sample size adequacy for medical prediction model."
    )
    parser.add_argument(
        "--evaluation-report",
        required=True,
        help="Path to evaluation_report.json.",
    )
    parser.add_argument(
        "--report",
        help="Optional output JSON report path.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on warnings.",
    )
    parser.add_argument(
        "--epv-minimum",
        type=float,
        default=None,
        help="Override minimum EPV threshold.",
    )
    parser.add_argument(
        "--min-total-events",
        type=int,
        default=None,
        help="Override minimum total events threshold (default: 100).",
    )
    parser.add_argument(
        "--min-test-events",
        type=int,
        default=None,
        help="Override minimum test events threshold (default: 50).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    info: List[Dict[str, Any]] = []

    thresholds = dict(DEFAULT_THRESHOLDS)
    if args.epv_minimum is not None:
        thresholds["epv_minimum"] = args.epv_minimum
    if args.min_total_events is not None:
        thresholds["min_total_events"] = args.min_total_events
    if args.min_test_events is not None:
        thresholds["min_test_events"] = args.min_test_events

    # Load evaluation report
    eval_path = Path(args.evaluation_report)
    if not eval_path.is_file():
        add_issue(
            failures,
            "missing_evaluation_report",
            f"Evaluation report not found: {eval_path}",
            {"path": str(eval_path)},
        )
        return _finish(args, failures, warnings, info, thresholds, None)

    try:
        eval_report = load_json_object(eval_path)
    except Exception as exc:
        add_issue(
            failures,
            "invalid_evaluation_report",
            f"Cannot parse evaluation report: {exc}",
            {"path": str(eval_path)},
        )
        return _finish(args, failures, warnings, info, thresholds, None)

    # Extract sample size info
    ssa = eval_report.get("sample_size_adequacy", {})
    metadata = eval_report.get("metadata", {})
    split_summary = eval_report.get("split_summary", {})

    # Try to get key numbers
    n_events = _to_float(ssa.get("n_events"))
    n_non_events = _to_float(ssa.get("n_non_events"))
    n_features = _to_float(ssa.get("n_features"))
    n_total = _to_float(ssa.get("n_total"))
    epv = _to_float(ssa.get("events_per_variable"))

    # Fallback extraction from metadata
    if n_features is None:
        n_features = _to_float(metadata.get("n_features"))
    if n_total is None:
        n_total = _to_float(metadata.get("n_train"))

    # Extract test set info
    test_info = split_summary.get("test", {})
    test_events = _to_float(test_info.get("n_positive", test_info.get("positive_count")))

    if n_events is None or n_features is None:
        # Try to compute from split summaries
        train_info = split_summary.get("train", {})
        if train_info:
            n_events = _to_float(train_info.get("n_positive", train_info.get("positive_count")))
            n_non_events = _to_float(train_info.get("n_negative", train_info.get("negative_count")))
            if n_total is None:
                n_total = _to_float(train_info.get("n", train_info.get("total")))

    if n_events is None or n_features is None:
        add_issue(
            failures,
            "missing_sample_size_info",
            "Cannot determine n_events or n_features from evaluation report.",
            {"found_keys": list(ssa.keys()) + list(metadata.keys())},
        )
        return _finish(args, failures, warnings, info, thresholds, eval_report)

    n_events_int = int(n_events)
    n_features_int = int(n_features)

    # Compute EPV if not provided
    if epv is None and n_features_int > 0:
        epv = n_events / n_features
    elif n_features_int == 0:
        epv = None  # No features → EPV undefined; avoid JSON-incompatible Infinity

    # Check EPV
    if epv is not None and epv < thresholds["epv_minimum"]:
        add_issue(
            failures,
            "epv_below_minimum",
            f"EPV = {epv:.1f} is below minimum {thresholds['epv_minimum']:.0f}. "
            f"({n_events_int} events / {n_features_int} features)",
            {
                "epv": epv,
                "n_events": n_events_int,
                "n_features": n_features_int,
                "threshold": thresholds["epv_minimum"],
            },
        )
    elif epv is not None and epv < thresholds["epv_recommended"]:
        add_issue(
            warnings,
            "epv_below_recommended",
            f"EPV = {epv:.1f} is below recommended {thresholds['epv_recommended']:.0f}. "
            f"ML models may need even higher EPV (Tsegaye et al. 2025).",
            {
                "epv": epv,
                "n_events": n_events_int,
                "n_features": n_features_int,
                "threshold": thresholds["epv_recommended"],
            },
        )

    # Check total events
    if n_events < thresholds["min_total_events"]:
        add_issue(
            warnings if n_events >= 50 else failures,
            "events_too_few",
            f"Only {n_events_int} events total (minimum: {int(thresholds['min_total_events'])}).",
            {"n_events": n_events_int, "threshold": thresholds["min_total_events"]},
        )

    # Check non-events (Riley 2019 Criterion 3: minority class >= 100)
    if n_non_events is not None and n_non_events < thresholds["min_total_non_events"]:
        target_list = failures if n_non_events < 50 else warnings
        add_issue(
            target_list,
            "non_events_too_few",
            f"Only {int(n_non_events)} non-events total "
            f"(Riley 2019 Criterion 3: minority class >= {int(thresholds['min_total_non_events'])}).",
            {"n_non_events": int(n_non_events), "threshold": thresholds["min_total_non_events"]},
        )

    # Check test events
    if test_events is not None and test_events < thresholds["min_test_events"]:
        add_issue(
            warnings,
            "test_set_events_too_few",
            f"Test set has {int(test_events)} events (recommend >= {int(thresholds['min_test_events'])}).",
            {"test_events": int(test_events), "threshold": thresholds["min_test_events"]},
        )

    # Shrinkage factor estimate
    shrinkage = _estimate_shrinkage(n_events_int, n_features_int)
    if shrinkage is not None and shrinkage < thresholds["shrinkage_factor_target"]:
        add_issue(
            warnings,
            "shrinkage_factor_low",
            f"Estimated shrinkage factor = {shrinkage:.3f} "
            f"(target >= {thresholds['shrinkage_factor_target']:.2f}).",
            {
                "shrinkage": shrinkage,
                "target": thresholds["shrinkage_factor_target"],
                "n_events": n_events_int,
                "n_features": n_features_int,
            },
        )

    # ── External validation sample size checks (Riley et al. BMJ 2024 Part 3) ──
    ext_val = eval_report.get("external_validation", {})
    ext_cohort = ext_val.get("cohort", {})
    ext_events = _to_float(ext_cohort.get("n_events",
                           ext_cohort.get("n_positive",
                           ext_cohort.get("positive_count"))))
    ext_non_events = _to_float(ext_cohort.get("n_non_events",
                               ext_cohort.get("n_negative",
                               ext_cohort.get("negative_count"))))

    if ext_events is not None and math.isfinite(ext_events):
        if ext_events < 100:
            add_issue(
                failures,
                "ext_val_events_too_few",
                f"External validation cohort has only {int(ext_events)} events "
                f"(minimum 100 required per Riley et al. BMJ 2024 Part 3).",
                {"ext_events": int(ext_events), "threshold": 100},
            )
        elif ext_events < 200:
            add_issue(
                warnings,
                "ext_val_events_low_for_calibration",
                f"External validation cohort has {int(ext_events)} events "
                f"(recommend >= 200 for calibration curves).",
                {"ext_events": int(ext_events), "threshold": 200},
            )

    if ext_non_events is not None and math.isfinite(ext_non_events):
        if ext_non_events < 100:
            add_issue(
                failures,
                "ext_val_non_events_too_few",
                f"External validation cohort has only {int(ext_non_events)} "
                f"non-events (minimum 100 required per Riley et al. BMJ 2024 Part 3).",
                {"ext_non_events": int(ext_non_events), "threshold": 100},
            )
        elif ext_non_events < 200:
            add_issue(
                warnings,
                "ext_val_non_events_low_for_calibration",
                f"External validation cohort has {int(ext_non_events)} non-events "
                f"(recommend >= 200 for calibration curves).",
                {"ext_non_events": int(ext_non_events), "threshold": 200},
            )

    # ── C-statistic CI width check (Riley et al. BMJ 2024 Part 3) ────────────
    ext_metrics = ext_val.get("metrics", {})
    c_stat = ext_metrics.get("c_statistic", ext_metrics.get("roc_auc", {}))
    if isinstance(c_stat, dict):
        c_ci_lower = _to_float(c_stat.get("ci_lower"))
        c_ci_upper = _to_float(c_stat.get("ci_upper"))
        if (c_ci_lower is not None and c_ci_upper is not None
                and math.isfinite(c_ci_lower) and math.isfinite(c_ci_upper)):
            c_ci_width = c_ci_upper - c_ci_lower
            if c_ci_width > 0.10:
                add_issue(
                    warnings,
                    "c_statistic_ci_too_wide",
                    f"C-statistic CI width = {c_ci_width:.3f} exceeds 0.10 "
                    f"(too imprecise per Riley et al. BMJ 2024 Part 3).",
                    {"ci_lower": c_ci_lower, "ci_upper": c_ci_upper,
                     "ci_width": round(c_ci_width, 4), "threshold": 0.10},
                )

    # ── Calibration slope CI width check (Riley et al. BMJ 2024 Part 3) ──────
    cal_slope = ext_metrics.get("calibration_slope", {})
    if isinstance(cal_slope, dict):
        cal_ci_lower = _to_float(cal_slope.get("ci_lower"))
        cal_ci_upper = _to_float(cal_slope.get("ci_upper"))
        if (cal_ci_lower is not None and cal_ci_upper is not None
                and math.isfinite(cal_ci_lower) and math.isfinite(cal_ci_upper)):
            cal_ci_width = cal_ci_upper - cal_ci_lower
            if cal_ci_width > 0.30:
                add_issue(
                    warnings,
                    "calibration_slope_ci_too_wide",
                    f"Calibration slope CI width = {cal_ci_width:.3f} exceeds "
                    f"0.30 (per Riley et al. BMJ 2024 Part 3).",
                    {"ci_lower": cal_ci_lower, "ci_upper": cal_ci_upper,
                     "ci_width": round(cal_ci_width, 4), "threshold": 0.30},
                )

    # ── Missing data inflation reminder (Riley et al. BMJ 2024) ──────────────
    missingness = _to_float(
        ssa.get("missing_pct",
        ssa.get("missingness_pct",
        metadata.get("missing_pct",
        metadata.get("missingness_pct"))))
    )
    if missingness is not None and math.isfinite(missingness) and missingness > 0:
        add_issue(
            info,
            "missing_data_inflate_sample",
            "Consider inflating sample size by 1/(1-missing%) to account "
            "for missing data (Riley et al. BMJ 2024, LIT-047).",
            {"missing_pct": missingness,
             "inflation_factor": round(1.0 / (1.0 - missingness / 100.0), 4)
             if missingness < 100 else None},
        )

    # Summary
    summary = {
        "n_events": n_events_int,
        "n_non_events": int(n_non_events) if n_non_events else None,
        "n_features": n_features_int,
        "n_total": int(n_total) if n_total else None,
        "events_per_variable": round(epv, 2) if epv is not None else None,
        "estimated_shrinkage_factor": (
            round(shrinkage, 4) if shrinkage is not None else None
        ),
        "test_events": int(test_events) if test_events else None,
        "adequacy_verdict": (
            "adequate"
            if (epv is not None and epv >= thresholds["epv_recommended"])
            else "marginal"
            if (epv is not None and epv >= thresholds["epv_minimum"])
            else "insufficient"
        ),
    }

    add_issue(
        info,
        "sample_size_summary",
        f"EPV={epv:.1f}, events={n_events_int}, features={n_features_int}, "
        f"shrinkage={shrinkage:.3f}" if shrinkage and epv is not None else
        f"EPV={'N/A' if epv is None else f'{epv:.1f}'}, events={n_events_int}, features={n_features_int}",
        summary,
    )

    return _finish(args, failures, warnings, info, thresholds, eval_report, summary)


def _finish(
    args: argparse.Namespace,
    failures: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    info: List[Dict[str, Any]],
    thresholds: Dict[str, float],
    eval_report: Optional[Dict[str, Any]],
    summary: Optional[Dict[str, Any]] = None,
) -> int:
    should_fail = bool(failures) or (args.strict and bool(warnings))
    status = "fail" if should_fail else "pass"

    fi = [GateIssue.from_legacy(f, Severity.ERROR) for f in failures]
    wi = [GateIssue.from_legacy(w, Severity.WARNING) for w in warnings]
    for issue in fi + wi:
        if not issue.remediation:
            issue.remediation = get_remediation(issue.code)

    report = build_report_envelope(
        gate_name="sample_size_gate",
        status=status,
        strict_mode=bool(args.strict),
        failures=fi,
        warnings=wi,
        extra={
            "thresholds": thresholds,
            "summary": summary or {},
            "info": info,
        },
    )

    if args.report:
        _write_report(Path(args.report).expanduser().resolve(), report)

    print_gate_summary("sample_size_gate", status, fi, wi, bool(args.strict), get_gate_elapsed())
    return 2 if should_fail else 0


if __name__ == "__main__":
    from _gate_utils import start_gate_timer
    start_gate_timer()
    raise SystemExit(main())
