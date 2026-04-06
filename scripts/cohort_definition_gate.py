#!/usr/bin/env python3
"""
Cohort Definition Gate (Phase 1) — Data understanding and sample adequacy.

Validates the input dataset before any splitting or modeling. Checks:
  - Cohort size and class distribution
  - EPV (Events Per Variable) adequacy — Riley et al. 2019
  - Missing value profile by feature
  - Data type detection (numeric vs categorical vs binary)
  - Cross-sectional vs longitudinal determination
  - Duplicate row and ID checks

Outputs:
  - JSON gate report (envelope v2.0.0)
  - cohort_summary.csv — overview table of dataset characteristics

References:
  - Riley et al. 2019 (BMJ) — Minimum sample size for prediction models
  - Peduzzi et al. 1996 — Events Per Variable rule-of-thumb
  - TRIPOD+AI 2024 Item 4a — Study participants
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

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

GATE_NAME = "cohort_definition_gate"
GATE_VERSION = "1.0.0"

_DEFAULT_EPV_THRESHOLD = 10
_DEFAULT_MIN_POSITIVE = 50
_DEFAULT_MIN_ROWS = 100

# ---------------------------------------------------------------------------
# Remediations
# ---------------------------------------------------------------------------

register_remediations({
    "COHORT_TOO_SMALL":
        "Dataset has fewer rows than the minimum threshold. "
        "Consider merging data sources or relaxing inclusion criteria.",
    "COHORT_EVENTS_TOO_FEW":
        "Positive events are below the minimum threshold. "
        "Binary prediction requires sufficient events for stable estimates.",
    "COHORT_EPV_LOW":
        "Events Per Variable is below 10 (Riley 2019 threshold). "
        "Reduce feature count, collect more data, or use penalized models.",
    "COHORT_EPV_CRITICAL":
        "Events Per Variable is below 5. Model estimates will be unreliable. "
        "Strongly consider reducing dimensionality.",
    "COHORT_HIGH_MISSINGNESS":
        "Features with >50%% missing values detected. "
        "Document missingness mechanism (MCAR/MAR/MNAR) per Madley-Dowd 2019.",
    "COHORT_DUPLICATE_ROWS":
        "Duplicate rows detected. This may indicate data quality issues "
        "or multiple records per patient without proper ID grouping.",
    "COHORT_DUPLICATE_IDS":
        "Duplicate patient IDs detected. If longitudinal, ensure split_data.py "
        "uses --patient-id-col for grouped splitting.",
    "COHORT_NO_VARIANCE":
        "Features with zero variance (constant columns) detected. "
        "Remove these before modeling.",
    "COHORT_TARGET_MISSING":
        "Target column not found in dataset.",
    "COHORT_TARGET_NOT_BINARY":
        "Target column is not binary (0/1). MLGG requires binary classification.",
    "COHORT_RILEY_UNDERPOWERED":
        "Sample size does not meet Riley et al. 2019 minimum. "
        "Reduce candidate parameters, collect more data, or use penalized models. "
        "Ref: Riley RD et al. Stat Med 2019;38:1276-1296.",
    "COHORT_SEVERE_IMBALANCE":
        "Class imbalance ratio exceeds 20:1. Consider stratified sampling "
        "and avoid SMOTE (van den Goorbergh 2022).",
    "COHORT_SURVEY_WEIGHTS_DETECTED":
        "Survey weight column detected. Standard ML models assume simple random "
        "sampling. If data uses complex survey design (NHANES, BRFSS), document "
        "that survey weights are NOT incorporated and report as limitation. "
        "Ref: NHANES analytic guidelines (CDC).",
    "COHORT_SURVEY_WEIGHTS_MISSING":
        "Data appears to be from a survey database (NHANES/BRFSS/NHIS pattern) "
        "but no weight column found. Verify sampling design and document.",
    "COHORT_OUTCOME_DEFINITION_LEAKAGE":
        "Features used to DEFINE the outcome should NOT be used as predictors. "
        "E.g., if diabetes is defined by HbA1c >= 6.5%, then HbA1c cannot be a "
        "predictor — it IS the outcome. Review feature list carefully. "
        "Ref: TRIPOD+AI 2024 Item 6a; MLGG-F01.",
    "COHORT_OUTCOME_DEFINITION_UNDOCUMENTED":
        "No outcome definition specification provided. For clinical prediction, "
        "the outcome must have a precise, reproducible definition. Document: "
        "(1) diagnostic criteria (ICD codes? lab values? self-report? composite?) "
        "(2) disease subtype (e.g., T1D vs T2D) "
        "(3) time window (30-day? 1-year? prevalent?) "
        "(4) ascertainment source (EHR? registry? claims? questionnaire?). "
        "Ref: TRIPOD+AI 2024 Item 6a.",
    "COHORT_OUTCOME_POSSIBLE_COMPOSITE":
        "Target column may use a composite or multi-source definition. "
        "Ensure all components are documented and the definition is clinically "
        "validated. Composite endpoints require sensitivity analysis.",
    "COHORT_EMPTY":
        "Dataset is empty (0 rows). Check data source and file path.",
})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_float(v: Any) -> Optional[float]:
    try:
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def riley_sample_size(
    prevalence: float,
    n_parameters: int,
    r2_cs_adj: float = 0.05,
    max_shrinkage_target: float = 0.90,
    precision_target: float = 0.05,
) -> Dict[str, Any]:
    """Minimum sample size per Riley et al. 2019 (Statistics in Medicine).

    Computes minimum n and E (events) satisfying three criteria:
      C1: Global shrinkage factor >= max_shrinkage_target (default 0.9)
      C2: |R²_apparent - R²_adjusted| <= 0.05
      C3: SE of overall risk estimate <= precision_target / 1.96

    Args:
        prevalence: Event rate (0 < phi < 1).
        n_parameters: Number of candidate predictor parameters p.
        r2_cs_adj: Anticipated Cox-Snell R² (adjusted). Default 0.05 (conservative).
        max_shrinkage_target: Minimum acceptable shrinkage factor.
        precision_target: Maximum CI half-width for overall risk.

    Returns:
        Dict with n_c1, n_c2, n_c3, n_min (maximum of all three), and details.

    References:
        Riley RD et al. Stat Med. 2019;38(7):1276-1296.
        Riley RD et al. BMJ. 2020;368:m441.
    """
    phi = prevalence
    p = max(n_parameters, 1)

    if phi <= 0 or phi >= 1:
        return {
            "error": f"Riley formula undefined for prevalence={phi:.4f}. "
                     "Requires 0 < prevalence < 1 (binary outcome with both classes).",
            "prevalence": round(phi, 4),
            "n_parameters": p,
        }

    # Criterion 1: Shrinkage factor S >= target
    # Approximate: S ≈ 1 - (p / EPP_effective)
    # Rearranging: EPP >= p / (1 - S)
    # n_c1 = p / ((1 - target) * phi)  for events; then n = E / phi
    if phi > 0 and phi < 1:
        # More precise: from Riley 2019 eq. (11)
        # S_approx = max(n * R² - 2) / (n * R²)  where n*R² = LR chi-sq approx
        # Simplified conservative bound:
        epp_c1 = p / (1 - max_shrinkage_target)  # events needed
        n_c1 = int(math.ceil(epp_c1 / phi))
    else:
        n_c1 = 0

    # Criterion 2: Optimism in R² <= 0.05
    # Approximate: optimism ≈ p / n (for logistic regression)
    # So n_c2 >= p / 0.05
    n_c2 = int(math.ceil(p / 0.05))

    # Criterion 3: Precision of overall risk
    # SE(phi_hat) = sqrt(phi * (1-phi) / n) <= precision_target / 1.96
    # n_c3 = phi * (1-phi) / (precision_target / 1.96)^2
    se_target = precision_target / 1.96
    if se_target > 0:
        n_c3 = int(math.ceil(phi * (1 - phi) / (se_target ** 2)))
    else:
        n_c3 = 0

    n_min = max(n_c1, n_c2, n_c3)
    e_min = int(math.ceil(n_min * phi))

    return {
        "n_criterion_1_shrinkage": n_c1,
        "n_criterion_2_optimism": n_c2,
        "n_criterion_3_precision": n_c3,
        "n_minimum": n_min,
        "e_minimum": e_min,
        "epp_minimum": round(e_min / p, 1) if p > 0 else 0,
        "prevalence": round(phi, 4),
        "n_parameters": p,
        "binding_criterion": (
            "C1_shrinkage" if n_c1 >= n_c2 and n_c1 >= n_c3
            else "C2_optimism" if n_c2 >= n_c3
            else "C3_precision"
        ),
    }


def _classify_dtype(series: pd.Series, max_cat_cardinality: int = 20) -> str:
    """Classify a column as numeric, binary, categorical, or id-like."""
    nunique = int(series.nunique(dropna=True))
    if nunique <= 1:
        return "constant"
    if nunique == 2:
        return "binary"
    if nunique <= max_cat_cardinality:
        return "categorical"
    if pd.api.types.is_numeric_dtype(series):
        return "numeric"
    # High-cardinality non-numeric: likely ID or free text
    return "id_or_text"


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze_cohort(
    df: pd.DataFrame,
    target_col: str,
    id_col: str,
    feature_cols: List[str],
) -> Dict[str, Any]:
    """Perform comprehensive cohort analysis."""
    n_rows = len(df)
    n_features = len(feature_cols)

    # Target analysis
    target_info: Dict[str, Any] = {}
    if target_col in df.columns:
        y = pd.to_numeric(df[target_col], errors="coerce")
        n_positive = int((y == 1).sum())
        n_negative = int((y == 0).sum())
        n_missing_target = int(y.isna().sum())
        n_other = n_rows - n_positive - n_negative - n_missing_target
        prevalence = n_positive / (n_positive + n_negative) if (n_positive + n_negative) > 0 else 0.0
        minority = min(n_positive, n_negative)
        majority = max(n_positive, n_negative)
        imbalance_ratio = majority / minority if minority > 0 else float("inf")
        epv = minority / n_features if n_features > 0 else 0.0

        # Riley 2019 sample size calculation
        riley = riley_sample_size(
            prevalence=prevalence,
            n_parameters=n_features,
        ) if prevalence > 0 and n_features > 0 else {}

        target_info = {
            "n_positive": n_positive,
            "n_negative": n_negative,
            "n_missing": n_missing_target,
            "n_other": n_other,
            "prevalence": round(prevalence, 4),
            "imbalance_ratio": round(imbalance_ratio, 2),
            "epv": round(epv, 2),
            "minority_class_count": minority,
            "riley_sample_size": riley,
        }
    else:
        target_info = {"error": f"Target column '{target_col}' not found."}

    # ID analysis
    id_info: Dict[str, Any] = {}
    if id_col and id_col in df.columns:
        n_unique_ids = int(df[id_col].nunique())
        n_duplicate_ids = n_rows - n_unique_ids
        id_info = {
            "n_unique": n_unique_ids,
            "n_duplicate_rows_by_id": n_duplicate_ids,
            "is_longitudinal": n_duplicate_ids > 0,
        }

    # Duplicate rows
    n_duplicate_rows = int(df.duplicated().sum())

    # Feature analysis
    feature_profiles: List[Dict[str, Any]] = []
    high_missing_features: List[str] = []
    zero_variance_features: List[str] = []
    dtype_counts: Dict[str, int] = {}

    for feat in feature_cols:
        if feat not in df.columns:
            continue
        series = df[feat]
        n_missing = int(series.isna().sum())
        pct_missing = round(n_missing / n_rows, 4) if n_rows > 0 else 0.0
        nunique = int(series.nunique(dropna=True))
        dtype_class = _classify_dtype(series)
        dtype_counts[dtype_class] = dtype_counts.get(dtype_class, 0) + 1

        profile = {
            "feature": feat,
            "dtype": str(series.dtype),
            "dtype_class": dtype_class,
            "n_missing": n_missing,
            "pct_missing": pct_missing,
            "n_unique": nunique,
        }

        if pd.api.types.is_numeric_dtype(series) and nunique > 2:
            desc = series.describe()
            profile["mean"] = round(float(desc.get("mean", 0)), 4)
            profile["std"] = round(float(desc.get("std", 0)), 4)
            profile["min"] = round(float(desc.get("min", 0)), 4)
            profile["max"] = round(float(desc.get("max", 0)), 4)

        feature_profiles.append(profile)

        if pct_missing > 0.5:
            high_missing_features.append(feat)
        if nunique <= 1:
            zero_variance_features.append(feat)

    return {
        "n_rows": n_rows,
        "n_features": n_features,
        "n_duplicate_rows": n_duplicate_rows,
        "target": target_info,
        "id": id_info,
        "feature_profiles": feature_profiles,
        "high_missing_features": high_missing_features,
        "zero_variance_features": zero_variance_features,
        "dtype_distribution": dtype_counts,
    }


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------

def _write_cohort_summary_csv(
    path: Path,
    analysis: Dict[str, Any],
) -> None:
    """Write cohort_summary.csv — dataset overview table."""
    target = analysis.get("target", {})
    id_info = analysis.get("id", {})

    rows = [
        ["Metric", "Value"],
        ["Total Rows", str(analysis["n_rows"])],
        ["Total Features", str(analysis["n_features"])],
        ["Duplicate Rows", str(analysis["n_duplicate_rows"])],
        ["Positive Events (y=1)", str(target.get("n_positive", "N/A"))],
        ["Negative Events (y=0)", str(target.get("n_negative", "N/A"))],
        ["Missing Target", str(target.get("n_missing", "N/A"))],
        ["Prevalence", str(target.get("prevalence", "N/A"))],
        ["Imbalance Ratio", str(target.get("imbalance_ratio", "N/A"))],
        ["EPV (Events Per Variable)", str(target.get("epv", "N/A"))],
        ["Unique Patient IDs", str(id_info.get("n_unique", "N/A"))],
        ["Longitudinal (Repeated IDs)", str(id_info.get("is_longitudinal", "N/A"))],
        ["Features >50% Missing", str(len(analysis.get("high_missing_features", [])))],
        ["Zero-Variance Features", str(len(analysis.get("zero_variance_features", [])))],
    ]

    # Dtype distribution
    for dtype_class, count in sorted(analysis.get("dtype_distribution", {}).items()):
        rows.append([f"Features ({dtype_class})", str(count)])

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerows(rows)


def _write_feature_profile_csv(
    path: Path,
    feature_profiles: List[Dict[str, Any]],
) -> None:
    """Write feature_profile.csv — per-feature details."""
    if not feature_profiles:
        return

    header = ["Feature", "DType", "Class", "N_Missing", "Pct_Missing", "N_Unique", "Mean", "Std", "Min", "Max"]
    rows = []
    for fp in feature_profiles:
        rows.append([
            fp["feature"],
            fp["dtype"],
            fp["dtype_class"],
            str(fp["n_missing"]),
            f"{fp['pct_missing']:.4f}",
            str(fp["n_unique"]),
            str(fp.get("mean", "")),
            str(fp.get("std", "")),
            str(fp.get("min", "")),
            str(fp.get("max", "")),
        ])

    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(header)
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# Validation checks
# ---------------------------------------------------------------------------

def _run_checks(
    failures: List[Dict[str, Any]],
    warnings_list: List[Dict[str, Any]],
    analysis: Dict[str, Any],
    epv_threshold: int,
    min_positive: int,
    min_rows: int,
) -> None:
    target = analysis.get("target", {})

    # Target existence
    if "error" in target:
        add_issue(failures, "COHORT_TARGET_MISSING", target["error"], {})
        return

    # Check binary
    if target.get("n_other", 0) > 0:
        add_issue(
            failures, "COHORT_TARGET_NOT_BINARY",
            f"{target['n_other']} rows have target values other than 0/1.",
            {"n_other": target["n_other"]},
        )

    # Sample size
    if analysis["n_rows"] < min_rows:
        add_issue(
            failures, "COHORT_TOO_SMALL",
            f"Dataset has {analysis['n_rows']} rows (minimum: {min_rows}).",
            {"n_rows": analysis["n_rows"], "threshold": min_rows},
        )

    # Positive events
    n_pos = target.get("n_positive", 0)
    if n_pos < min_positive:
        add_issue(
            failures, "COHORT_EVENTS_TOO_FEW",
            f"Only {n_pos} positive events (minimum: {min_positive}).",
            {"n_positive": n_pos, "threshold": min_positive},
        )

    # EPV
    epv = target.get("epv", 0)
    if epv < 5:
        add_issue(
            failures, "COHORT_EPV_CRITICAL",
            f"EPV = {epv:.1f} (< 5). Model estimates will be unreliable.",
            {"epv": epv},
        )
    elif epv < epv_threshold:
        add_issue(
            warnings_list, "COHORT_EPV_LOW",
            f"EPV = {epv:.1f} (< {epv_threshold}). Consider reducing features.",
            {"epv": epv, "threshold": epv_threshold},
        )

    # Riley 2019 sample size adequacy
    riley = target.get("riley_sample_size", {})
    if riley:
        n_min = riley.get("n_minimum", 0)
        if analysis["n_rows"] < n_min:
            add_issue(
                warnings_list, "COHORT_RILEY_UNDERPOWERED",
                f"Sample size {analysis['n_rows']} is below Riley 2019 minimum {n_min} "
                f"(binding criterion: {riley.get('binding_criterion', '?')}). "
                f"C1(shrinkage)={riley.get('n_criterion_1_shrinkage')}, "
                f"C2(optimism)={riley.get('n_criterion_2_optimism')}, "
                f"C3(precision)={riley.get('n_criterion_3_precision')}.",
                {"riley": riley, "actual_n": analysis["n_rows"]},
            )

    # Imbalance
    imbalance = target.get("imbalance_ratio", 1.0)
    if imbalance > 20:
        add_issue(
            warnings_list, "COHORT_SEVERE_IMBALANCE",
            f"Imbalance ratio = {imbalance:.1f}:1.",
            {"imbalance_ratio": imbalance},
        )

    # Duplicate rows
    if analysis["n_duplicate_rows"] > 0:
        add_issue(
            warnings_list, "COHORT_DUPLICATE_ROWS",
            f"{analysis['n_duplicate_rows']} duplicate rows detected.",
            {"n_duplicates": analysis["n_duplicate_rows"]},
        )

    # Duplicate IDs (longitudinal)
    id_info = analysis.get("id", {})
    if id_info.get("n_duplicate_rows_by_id", 0) > 0:
        add_issue(
            warnings_list, "COHORT_DUPLICATE_IDS",
            f"{id_info['n_duplicate_rows_by_id']} rows share IDs with other rows "
            f"(longitudinal data detected).",
            {"n_duplicate_ids": id_info["n_duplicate_rows_by_id"]},
        )

    # High missingness
    high_miss = analysis.get("high_missing_features", [])
    if high_miss:
        add_issue(
            warnings_list, "COHORT_HIGH_MISSINGNESS",
            f"{len(high_miss)} features have >50%% missing: {high_miss[:5]}",
            {"features": high_miss[:10], "count": len(high_miss)},
        )

    # Zero variance
    zv = analysis.get("zero_variance_features", [])
    if zv:
        add_issue(
            warnings_list, "COHORT_NO_VARIANCE",
            f"{len(zv)} zero-variance features: {zv[:5]}",
            {"features": zv[:10], "count": len(zv)},
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Cohort Definition Gate (Phase 1): data understanding and sample adequacy.",
    )

    inp = parser.add_argument_group("Input")
    inp.add_argument("--data", required=True, help="Path to input CSV (full dataset before splitting).")
    inp.add_argument("--target-col", required=True, help="Target column name.")
    inp.add_argument("--id-col", default="", help="Patient/entity ID column name.")
    inp.add_argument(
        "--ignore-cols", default="",
        help="Comma-separated columns to exclude from feature analysis.",
    )

    study = parser.add_argument_group("Study design")
    study.add_argument(
        "--outcome-definition", default="",
        help="JSON file or inline string describing outcome definition "
             "(criteria, subtype, time_window, ascertainment_source).",
    )
    study.add_argument(
        "--definition-cols", default="",
        help="Comma-separated columns used to DEFINE the outcome. "
             "These will be checked for leakage if included as features.",
    )
    study.add_argument(
        "--weight-col", default="",
        help="Survey weight column name (e.g., WTMEC2YR for NHANES). "
             "If provided, flags that standard ML ignores survey design.",
    )
    study.add_argument(
        "--survey-source", default="",
        help="Survey database name (nhanes, brfss, nhis, etc.) for auto-detection.",
    )

    cfg = parser.add_argument_group("Thresholds")
    cfg.add_argument("--epv-threshold", type=int, default=_DEFAULT_EPV_THRESHOLD, help="EPV warning threshold.")
    cfg.add_argument("--min-positive", type=int, default=_DEFAULT_MIN_POSITIVE, help="Minimum positive events.")
    cfg.add_argument("--min-rows", type=int, default=_DEFAULT_MIN_ROWS, help="Minimum dataset rows.")

    out = parser.add_argument_group("Output")
    out.add_argument("--report", help="Path to write JSON gate report.")
    out.add_argument("--output-dir", help="Directory for CSV outputs.")
    out.add_argument("--strict", action="store_true", help="Promote warnings to failures.")

    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()

    failures: List[Dict[str, Any]] = []
    warnings_list: List[Dict[str, Any]] = []

    # Load data
    try:
        data_path = Path(args.data).expanduser().resolve()
        df = pd.read_csv(data_path)
    except Exception as exc:
        add_issue(
            failures, "file_not_found",
            f"Failed to load data: {exc}",
            {"path": str(args.data)},
        )
        return _finish(args, failures, warnings_list, {})

    if len(df) == 0:
        add_issue(
            failures, "COHORT_EMPTY",
            "Dataset is empty (0 rows). Check data source and file path.",
            {"path": str(args.data)},
        )
        return _finish(args, failures, warnings_list, {"n_rows": 0})

    # ── Study design checks ──

    study_design: Dict[str, Any] = {}

    # 1. Survey weight detection
    weight_col = args.weight_col.strip() if args.weight_col else ""
    _KNOWN_WEIGHT_PATTERNS = ["WTMEC", "WTINT", "WTSAF", "SAMPWT", "PERWEIGHT",
                               "FINALWT", "weight", "sampling_weight", "survey_weight"]
    if weight_col and weight_col in df.columns:
        add_issue(
            warnings_list, "COHORT_SURVEY_WEIGHTS_DETECTED",
            f"Survey weight column '{weight_col}' found. Standard ML models do NOT "
            f"incorporate survey weights. Document this as a limitation.",
            {"weight_col": weight_col, "weight_range": [
                round(float(df[weight_col].min()), 2),
                round(float(df[weight_col].max()), 2),
            ]},
        )
        study_design["survey_weight_col"] = weight_col
        study_design["survey_weighted"] = False  # ML does not use weights
    elif not weight_col:
        # Auto-detect weight columns
        detected_weights = [c for c in df.columns
                            if any(p.lower() in c.lower() for p in _KNOWN_WEIGHT_PATTERNS)]
        if detected_weights:
            add_issue(
                warnings_list, "COHORT_SURVEY_WEIGHTS_DETECTED",
                f"Possible survey weight column(s) auto-detected: {detected_weights}. "
                f"If this is survey data, specify --weight-col and document that "
                f"survey design is NOT incorporated in modeling.",
                {"detected_columns": detected_weights},
            )
            study_design["auto_detected_weight_cols"] = detected_weights

    # Survey source auto-detection
    survey_source = args.survey_source.strip().lower() if args.survey_source else ""
    if not survey_source:
        _data_name = Path(args.data).stem.lower()
        for src in ["nhanes", "brfss", "nhis", "meps", "hrs"]:
            if src in _data_name:
                survey_source = src
                break
    if survey_source:
        study_design["survey_source"] = survey_source
        add_issue(
            warnings_list, "COHORT_SURVEY_WEIGHTS_MISSING" if not weight_col else "COHORT_SURVEY_WEIGHTS_DETECTED",
            f"Data appears to be from survey database '{survey_source.upper()}'. "
            f"Complex survey design (stratification, clustering, weights) is NOT "
            f"incorporated in standard ML modeling. This MUST be documented as "
            f"a limitation per STROBE/TRIPOD+AI.",
            {"survey_source": survey_source},
        )

    # 2. Outcome definition check
    outcome_def_provided = bool(args.outcome_definition and args.outcome_definition.strip())
    if not outcome_def_provided:
        add_issue(
            warnings_list, "COHORT_OUTCOME_DEFINITION_UNDOCUMENTED",
            "No outcome definition specification provided via --outcome-definition. "
            "For clinical prediction models, you MUST document: "
            "(1) Diagnostic criteria: ICD codes? Lab values (e.g., HbA1c >= 6.5%)? "
            "Self-report? Physician diagnosis? Composite? "
            "(2) Disease subtype: e.g., Type 1 vs Type 2 diabetes "
            "(3) Time window: 30-day event? 1-year? Prevalent at baseline? "
            "(4) Ascertainment source: EHR? Registry? Claims? Questionnaire? "
            "Provide via --outcome-definition '{\"criteria\":\"...\",\"subtype\":\"...\","
            "\"time_window\":\"...\",\"source\":\"...\"}'",
            {},
        )
    else:
        # Parse outcome definition
        try:
            if args.outcome_definition.strip().startswith("{"):
                outcome_spec = json.loads(args.outcome_definition)
            else:
                outcome_spec_path = Path(args.outcome_definition).expanduser().resolve()
                with outcome_spec_path.open("r", encoding="utf-8") as fh:
                    outcome_spec = json.load(fh)
            study_design["outcome_definition"] = outcome_spec
        except Exception:
            study_design["outcome_definition"] = {"raw": args.outcome_definition}

    # 3. Definition variable leakage check
    definition_cols = [c.strip() for c in args.definition_cols.split(",") if c.strip()]
    if definition_cols:
        study_design["definition_cols"] = definition_cols
        # Definition columns will be auto-excluded from feature set (see ignore_cols below).
        # Confirm this to the user.
        present_def_cols = [c for c in definition_cols if c in df.columns]
        if present_def_cols:
            add_issue(
                warnings_list, "COHORT_OUTCOME_DEFINITION_LEAKAGE",
                f"Definition variable(s) {present_def_cols} declared and will be "
                f"auto-excluded from the predictor set. This prevents the model "
                f"from using the outcome definition as a feature (MLGG-F01).",
                {"excluded_columns": present_def_cols, "action": "auto_excluded"},
            )
    else:
        # Heuristic: warn if common definition variables are present
        _DEF_PATTERNS = ["hba1c", "a1c", "glucose", "fasting_glucose", "fbg",
                         "ogtt", "icd", "diagnosis", "dx_code", "confirmed",
                         "lab_result", "test_result"]
        suspected = [c for c in df.columns
                     if any(p in c.lower() for p in _DEF_PATTERNS)
                     and c != args.target_col]
        if suspected:
            add_issue(
                warnings_list, "COHORT_OUTCOME_DEFINITION_LEAKAGE",
                f"Columns matching common outcome-definition patterns detected: "
                f"{suspected[:8]}. If any of these were used to DEFINE the outcome "
                f"(not just correlated with it), they MUST be excluded. "
                f"Specify --definition-cols to explicitly declare them.",
                {"suspected_columns": suspected[:8]},
            )

    # Determine feature columns
    ignore_cols = set(c.strip() for c in args.ignore_cols.split(",") if c.strip())
    ignore_cols.add(args.target_col)
    if args.id_col:
        ignore_cols.add(args.id_col)
    # Also ignore definition columns if specified
    ignore_cols.update(definition_cols)
    feature_cols = [c for c in df.columns if c not in ignore_cols]

    # Analyze
    analysis = analyze_cohort(df, args.target_col, args.id_col, feature_cols)
    analysis["study_design"] = study_design

    # Validate
    _run_checks(
        failures, warnings_list, analysis,
        epv_threshold=args.epv_threshold,
        min_positive=args.min_positive,
        min_rows=args.min_rows,
    )

    # Write CSVs
    output_dir = Path(args.output_dir) if args.output_dir else (
        Path(args.report).parent if args.report else Path(".")
    )
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    _write_cohort_summary_csv(output_dir / "cohort_summary.csv", analysis)
    _write_feature_profile_csv(output_dir / "feature_profile.csv", analysis.get("feature_profiles", []))

    print(f"  Cohort: {analysis['n_rows']} rows, {analysis['n_features']} features")
    target = analysis.get("target", {})
    if "epv" in target:
        print(f"  Events: {target.get('n_positive', 0)} positive, "
              f"prevalence={target.get('prevalence', 0):.3f}, "
              f"EPV={target['epv']:.1f}")
    print(f"  Tables written to: {output_dir}/")

    # Build summary (strip feature_profiles for JSON brevity)
    summary = {k: v for k, v in analysis.items() if k != "feature_profiles"}
    summary["feature_profile_count"] = len(analysis.get("feature_profiles", []))
    summary["tables_written"] = {
        "cohort_summary": str(output_dir / "cohort_summary.csv"),
        "feature_profile": str(output_dir / "feature_profile.csv"),
    }

    return _finish(args, failures, warnings_list, summary)


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
        input_files={"data": str(getattr(args, "data", ""))},
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
