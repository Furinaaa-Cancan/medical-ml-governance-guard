#!/usr/bin/env python3
"""
Score a published paper based on its metadata.json against MLGG review criteria.

Unlike audit_external_project.py (which requires code/evidence), this tool
evaluates papers from their *reported methodology* — what authors describe
in the methods section. This is the machine-readable equivalent of a
TRIPOD+AI / PROBAST+AI checklist review.

Produces a 12-dimension score (0–100) based on reporting completeness,
plus TRIPOD+AI item coverage and PROBAST+AI risk-of-bias assessment.

Usage:
  python3 scripts/score_paper_metadata.py \\
      --metadata references/case-studies/nature_medicine/cardiovascular/smith_2023/metadata.json

  # Batch mode
  python3 scripts/score_paper_metadata.py \\
      --batch-dir references/case-studies/ --output references/case-studies/audit_results/batch_scores.json
"""
from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# 12-dimension checks derived from metadata fields
# ---------------------------------------------------------------------------

DIMENSION_CHECKS: Dict[str, Dict[str, Any]] = {
    "data_integrity": {
        "weight": 12,
        "checks": [
            ("split_reported", "dataset.split_strategy", lambda v: v is not None and v != "" and v != "not_reported"),
            ("train_test_sizes", "dataset.train_n", lambda v: v is not None and v > 0),
            ("test_size", "dataset.test_n", lambda v: v is not None and v > 0),
            ("total_n_reported", "dataset.n_patients_total", lambda v: v is not None and v > 0),
            ("prevalence_reported", "dataset.prevalence_pct", lambda v: v is not None),
            ("temporal_split", "dataset.split_strategy", lambda v: v == "temporal"),
        ],
    },
    "leakage_prevention": {
        "weight": 15,
        "checks": [
            ("patient_level_split", "leakage_risk_assessment.patient_level_split_confirmed", lambda v: v is True),
            ("temporal_split_confirmed", "leakage_risk_assessment.temporal_split_confirmed", lambda v: v is True),
            ("preprocess_train_only", "leakage_risk_assessment.preprocessing_fit_on_train_only", lambda v: v is True),
            ("no_test_tuning", "leakage_risk_assessment.tuning_used_test_data", lambda v: v is False),
            ("low_target_leakage", "leakage_risk_assessment.target_leakage_risk", lambda v: v == "low"),
            ("low_post_index_risk", "leakage_risk_assessment.post_index_feature_risk", lambda v: v == "low"),
        ],
    },
    "pipeline_isolation": {
        "weight": 12,
        "checks": [
            ("preprocess_isolated", "leakage_risk_assessment.preprocessing_fit_on_train_only", lambda v: v is True),
            ("tuning_set_valid_only", "model.tuning_set", lambda v: v in ("validation_only", "train_validation")),
            ("missing_data_handled", "dataset.missing_data_strategy", lambda v: v is not None and v != ""),
        ],
    },
    "model_selection_rigor": {
        "weight": 10,
        "checks": [
            ("multiple_candidates", "model.n_candidate_models", lambda v: v is not None and v >= 3),
            ("hyperparameter_tuning", "model.hyperparameter_tuning", lambda v: v is not None and v != ""),
            ("tuning_not_on_test", "model.tuning_set", lambda v: v is not None and v != "" and v != "test_used"),
            ("feature_selection_described", "model.feature_selection_method", lambda v: v is not None and v != ""),
        ],
    },
    "statistical_validity": {
        "weight": 12,
        "checks": [
            ("ci_reported", "performance_metrics.bootstrap_ci_reported", lambda v: v is True),
            ("ci_bounds", "performance_metrics.test_auroc_ci_lower", lambda v: v is not None),
            ("calibration_reported", "performance_metrics.calibration_reported", lambda v: v is True),
            ("dca_reported", "performance_metrics.dca_reported", lambda v: v is True),
            ("brier_reported", "performance_metrics.test_brier_score", lambda v: v is not None),
        ],
    },
    "generalization_evidence": {
        "weight": 10,
        "checks": [
            ("external_validation", "study_design.has_external_validation", lambda v: v is True),
            ("external_auroc", "performance_metrics.external_auroc", lambda v: v is not None),
            ("multicenter", "study_design.is_multicenter", lambda v: v is True),
        ],
    },
    "clinical_completeness": {
        "weight": 7,
        "checks": [
            ("auroc_reported", "performance_metrics.test_auroc", lambda v: v is not None),
            ("sensitivity_reported", "performance_metrics.test_sensitivity", lambda v: v is not None),
            ("specificity_reported", "performance_metrics.test_specificity", lambda v: v is not None),
            ("ppv_npv_reported", "performance_metrics.test_ppv", lambda v: v is not None),
            ("primary_metric_named", "performance_metrics.primary_metric", lambda v: v is not None and v != ""),
        ],
    },
    "reporting_standards": {
        "weight": 7,
        "checks": [
            ("tripod_claimed", "reporting_standards.tripod_ai_claimed", lambda v: v is True),
            ("limitation_section", "reporting_standards.limitation_section", lambda v: v is True),
            ("equator_cited", "reporting_standards.equator_guideline_cited", lambda v: v is not None and v != ""),
        ],
    },
    "reproducibility": {
        "weight": 6,
        "checks": [
            ("code_available", "reporting_standards.code_availability", lambda v: v == "public_github"),
            ("data_available", "reporting_standards.data_availability", lambda v: v in ("public", "on_request")),
        ],
    },
    "security_provenance": {
        "weight": 3,
        "checks": [
            ("code_or_data_shared", "reporting_standards.code_availability", lambda v: v != "not_mentioned" and v is not None),
        ],
    },
    "fairness_equity": {
        "weight": 3,
        "checks": [
            ("multicenter_or_subgroup", "study_design.is_multicenter", lambda v: v is True),
        ],
    },
    "sample_size_adequacy": {
        "weight": 3,
        "checks": [
            ("events_reported", "dataset.n_events_positive", lambda v: v is not None and v >= 100),
            ("epv_adequate", None, None),  # Computed check, see below
        ],
    },
}


def _get_nested(data: Dict, path: str) -> Any:
    """Get a nested value from a dict using dot notation."""
    keys = path.split(".")
    current = data
    for k in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(k)
    return current


def _check_epv(metadata: Dict) -> bool:
    """Check Events Per Variable >= 10."""
    events = metadata.get("dataset", {}).get("n_events_positive")
    features = metadata.get("dataset", {}).get("features_n")
    if events is not None and features is not None and features > 0:
        return events / features >= 10
    return False


_CLAIM_EVIDENCE_PAIRS: tuple[tuple[str, str, str], ...] = (
    # (scoring key, boolean claim field, evidence quote field)
    ("patient_level_split",
     "leakage_risk_assessment.patient_level_split_confirmed",
     "leakage_risk_assessment.patient_level_split_evidence"),
    ("temporal_split_confirmed",
     "leakage_risk_assessment.temporal_split_confirmed",
     "leakage_risk_assessment.temporal_split_evidence"),
    ("preprocess_train_only",
     "leakage_risk_assessment.preprocessing_fit_on_train_only",
     "leakage_risk_assessment.preprocessing_evidence"),
    ("no_test_tuning",
     "leakage_risk_assessment.tuning_used_test_data",
     "leakage_risk_assessment.tuning_evidence"),
)


def _audit_evidence_backing(metadata: Dict[str, Any]) -> List[Dict[str, str]]:
    """P1-4 cross-verification: for each leakage claim, check it has a
    supporting evidence quote. Unsubstantiated positive claims are the
    highest-risk failure mode — extractor may have hallucinated compliance.

    Returns a list of findings with severity + recommendation for the reviewer.
    """
    findings: List[Dict[str, str]] = []
    for key, claim_path, evidence_path in _CLAIM_EVIDENCE_PAIRS:
        claim = _get_nested(metadata, claim_path)
        evidence = _get_nested(metadata, evidence_path) or ""
        evidence_str = str(evidence).strip()
        # Only audit positive compliance claims (True for most, False for tuning_used_test_data).
        is_positive_claim = (
            (key != "no_test_tuning" and claim is True)
            or (key == "no_test_tuning" and claim is False)
        )
        if is_positive_claim and not evidence_str:
            findings.append({
                "claim": key,
                "claim_path": claim_path,
                "severity": "HIGH",
                "message": (
                    f"Positive methodology claim without supporting evidence quote. "
                    f"Extractor marked {claim_path}={claim} but left "
                    f"{evidence_path} empty. Reviewer should downgrade confidence "
                    f"on this dimension until the source text is re-read."
                ),
            })
    return findings


def score_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Score a paper's metadata against MLGG review criteria.

    Returns a structured report with per-dimension scores and overall grade.
    """
    dimensions: Dict[str, Any] = {}
    total_weighted = 0.0
    total_weight = 0

    for dim_id, dim_spec in DIMENSION_CHECKS.items():
        weight = dim_spec["weight"]
        checks = dim_spec["checks"]
        passed: List[str] = []
        failed: List[str] = []

        for check_name, field_path, validator in checks:
            if check_name == "epv_adequate":
                if _check_epv(metadata):
                    passed.append(check_name)
                else:
                    failed.append(check_name)
            elif field_path and validator:
                val = _get_nested(metadata, field_path)
                if validator(val):
                    passed.append(check_name)
                else:
                    failed.append(check_name)

        n_total = len(passed) + len(failed)
        frac = len(passed) / n_total if n_total > 0 else 0.0
        score = round(frac * weight, 2)

        dimensions[dim_id] = {
            "score": score,
            "max": weight,
            "fraction": round(frac, 4),
            "passed": passed,
            "failed": failed,
        }
        total_weighted += score
        total_weight += weight

    total_score = round(total_weighted, 1)

    # Hard floor: if any Tier 1 dimension (D1, D2, D3, D5) scores 0,
    # cap the grade at "Major issues" regardless of total score.
    # Rationale: a paper with zero leakage prevention or zero data integrity
    # cannot be considered "Solid" or "Publication-grade" even if other
    # dimensions are perfect.
    tier1_dims = ["data_integrity", "leakage_prevention", "pipeline_isolation", "statistical_validity"]
    tier1_zero = [d for d in tier1_dims if dimensions.get(d, {}).get("fraction", 0) == 0]
    tier1_cap = bool(tier1_zero)

    grade = (
        "Publication-grade" if total_score >= 90 and not tier1_cap
        else "Solid but gaps remain" if total_score >= 75 and not tier1_cap
        else "Major issues" if total_score >= 60
        else "Not publishable"
    )

    # Leakage risk summary
    risk = metadata.get("leakage_risk_assessment", {})
    leakage_flags = {
        "patient_split": risk.get("patient_level_split_confirmed"),
        "temporal_split": risk.get("temporal_split_confirmed"),
        "preprocess_isolated": risk.get("preprocessing_fit_on_train_only"),
        "test_used_for_tuning": risk.get("tuning_used_test_data"),
        "target_leakage_risk": risk.get("target_leakage_risk"),
    }

    # Flag if scoring relied on unverified LLM-extracted fields
    audit = metadata.get("mlgg_audit", {})
    llm_fields = set(audit.get("_llm_extracted_fields", []))
    validation_warnings = audit.get("_validation_warnings", [])

    # Check which scored dimensions depend on LLM-extracted data
    llm_dependent_dims: list[str] = []
    for dim_name, dim_def in DIMENSION_CHECKS.items():
        for _check_name, field_path, _check_fn in dim_def["checks"]:
            if field_path in llm_fields:
                if dim_name not in llm_dependent_dims:
                    llm_dependent_dims.append(dim_name)

    llm_note = None
    if llm_dependent_dims:
        llm_note = (
            f"Scores for [{', '.join(llm_dependent_dims)}] depend on LLM-extracted data "
            f"(source: {audit.get('_source', 'unknown')}). "
            f"Human verification recommended before publication decisions."
        )

    # P1-4: evidence-backing audit. Flags positive compliance claims that
    # lack a supporting source quote from the PDF — a signal that extractor
    # may have over-claimed and reviewer should look again.
    unsubstantiated = _audit_evidence_backing(metadata)

    result: Dict[str, Any] = {
        "contract_version": "paper_score.v1.1",
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "total_score": total_score,
        "grade": grade,
        "dimensions": dimensions,
        "leakage_flags": leakage_flags,
        "bibliographic": metadata.get("bibliographic", {}),
    }
    if llm_note:
        result["_llm_confidence_note"] = llm_note
    if validation_warnings:
        result["_extraction_validation_warnings"] = validation_warnings
    if unsubstantiated:
        result["unsubstantiated_claims"] = unsubstantiated
        # Flag in leakage_flags so downstream reviewer UIs surface it prominently
        result["leakage_flags"]["_has_unsubstantiated_claims"] = True
    return result


# ---------------------------------------------------------------------------
# Batch scoring
# ---------------------------------------------------------------------------

def find_metadata_files(root: Path) -> List[Path]:
    """Recursively find all metadata.json files under root."""
    return sorted(root.rglob("metadata.json"))


def batch_score(
    metadata_files: List[Path],
) -> Dict[str, Any]:
    """Score multiple papers and produce aggregate statistics."""
    results: List[Dict[str, Any]] = []

    for mf in metadata_files:
        try:
            with mf.open() as f:
                metadata = json.load(f)
            if metadata.get("_template_version"):
                # Skip unfilled templates
                bib = metadata.get("bibliographic", {})
                if not bib.get("title"):
                    continue
            score = score_metadata(metadata)
            score["source_file"] = str(mf)
            results.append(score)
        except Exception as e:
            print(f"  SKIP {mf}: {e}", file=sys.stderr)

    # Aggregate
    if not results:
        return {"papers_scored": 0, "results": []}

    scores = [r["total_score"] for r in results]
    import numpy as np
    scores_arr = np.array(scores)

    # Per-dimension aggregation
    dim_agg: Dict[str, Dict[str, float]] = {}
    for dim_id in DIMENSION_CHECKS:
        dim_scores = [r["dimensions"][dim_id]["fraction"] for r in results]
        dim_agg[dim_id] = {
            "mean_fraction": round(float(np.mean(dim_scores)), 4),
            "std": round(float(np.std(dim_scores)), 4),
            "min": round(float(np.min(dim_scores)), 4),
        }

    # Leakage prevalence
    leakage_counts = {
        "patient_split_confirmed": sum(1 for r in results if r["leakage_flags"].get("patient_split") is True),
        "temporal_split_confirmed": sum(1 for r in results if r["leakage_flags"].get("temporal_split") is True),
        "preprocess_isolated": sum(1 for r in results if r["leakage_flags"].get("preprocess_isolated") is True),
        "test_used_for_tuning": sum(1 for r in results if r["leakage_flags"].get("test_used_for_tuning") is True),
        "high_leakage_risk": sum(1 for r in results if r["leakage_flags"].get("target_leakage_risk") == "high"),
    }

    return {
        "papers_scored": len(results),
        "score_summary": {
            "mean": round(float(scores_arr.mean()), 1),
            "std": round(float(scores_arr.std()), 1),
            "median": round(float(np.median(scores_arr)), 1),
            "min": round(float(scores_arr.min()), 1),
            "max": round(float(scores_arr.max()), 1),
            "publication_grade": sum(1 for s in scores if s >= 90),
            "solid": sum(1 for s in scores if 75 <= s < 90),
            "major_issues": sum(1 for s in scores if 60 <= s < 75),
            "not_publishable": sum(1 for s in scores if s < 60),
        },
        "dimension_aggregation": dim_agg,
        "leakage_prevalence": leakage_counts,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Metadata validation (--validate)
# ---------------------------------------------------------------------------

_RANGE_CHECKS: List[Tuple[str, float, float, str]] = [
    # (field_path, min, max, level)
    ("performance_metrics.test_auroc", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_auroc_ci_lower", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_auroc_ci_upper", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_auprc", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_sensitivity", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_specificity", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_ppv", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_npv", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_f1", 0.0, 1.0, "ERROR"),
    ("performance_metrics.test_brier_score", 0.0, 1.0, "ERROR"),
    ("performance_metrics.external_auroc", 0.0, 1.0, "ERROR"),
    ("dataset.prevalence_pct", 0.0, 100.0, "ERROR"),
]

_ENUM_CHECKS: List[Tuple[str, List[str], str]] = [
    ("dataset.source_type", ["EHR_single_center", "EHR_multicenter", "public_dataset",
                             "registry", "biobank", "claims_data", "mixed"], "WARNING"),
    ("dataset.split_strategy", ["random", "temporal", "site_based", "not_reported"], "WARNING"),
    ("model.tuning_set", ["validation_only", "train_validation", "test_used", "not_reported"], "WARNING"),
    ("leakage_risk_assessment.target_leakage_risk", ["low", "medium", "high", "cannot_assess"], "WARNING"),
    ("reporting_standards.code_availability", ["public_github", "on_request", "not_available", "not_mentioned"], "WARNING"),
    ("reporting_standards.data_availability", ["public", "on_request", "restricted", "not_available", "not_mentioned"], "WARNING"),
]


def validate_metadata(metadata: Dict[str, Any]) -> List[Dict[str, str]]:
    """Validate metadata against consistency rules.

    Returns a list of issues: [{rule_id, level, field, message}].
    """
    issues: List[Dict[str, str]] = []

    def _issue(rule_id: str, level: str, field: str, msg: str) -> None:
        issues.append({"rule_id": rule_id, "level": level, "field": field, "message": msg})

    # ── Required field checks (BUG 8 fix: empty metadata must not pass) ──
    _REQUIRED = [
        ("bibliographic.title", "Paper title is required"),
        ("dataset.n_patients_total", "Total sample size is required"),
        ("dataset.split_strategy", "Split strategy is required"),
        ("performance_metrics.test_auroc", "Test AUROC is required"),
    ]
    for path, msg in _REQUIRED:
        val = _get_nested(metadata, path)
        if val is None or val == "":
            _issue("REQUIRED", "ERROR", path, msg)

    # ── Type checks (BUG 9 fix: string metrics must not pass silently) ──
    _NUMERIC_FIELDS = [
        "performance_metrics.test_auroc", "performance_metrics.test_auroc_ci_lower",
        "performance_metrics.test_auroc_ci_upper", "performance_metrics.external_auroc",
        "dataset.n_patients_total", "dataset.train_n", "dataset.test_n",
        "dataset.n_events_positive", "dataset.features_n", "dataset.prevalence_pct",
    ]
    for path in _NUMERIC_FIELDS:
        val = _get_nested(metadata, path)
        if val is not None and not isinstance(val, (int, float)):
            _issue("TYPE", "ERROR", path, f"{path} must be numeric, got {type(val).__name__}: {val!r}")

    # ── Range checks ──
    for path, lo, hi, level in _RANGE_CHECKS:
        val = _get_nested(metadata, path)
        if val is not None and isinstance(val, (int, float)):
            if not (lo <= val <= hi):
                _issue("RANGE", level, path, f"{path}={val} outside [{lo}, {hi}]")

    # ── Positive integer checks ──
    for path in ("dataset.n_patients_total", "dataset.train_n", "dataset.test_n", "dataset.features_n"):
        val = _get_nested(metadata, path)
        if val is not None and isinstance(val, (int, float)) and val <= 0:
            _issue("RANGE", "ERROR", path, f"{path}={val} must be > 0")

    # ── Enum checks ──
    for path, allowed, level in _ENUM_CHECKS:
        val = _get_nested(metadata, path)
        if val is not None and val != "" and val not in allowed:
            _issue("ENUM", level, path, f"{path}='{val}' not in {allowed}")

    # ── C-001: n_events_positive + n_events_negative ≈ n_patients_total ──
    pos = _get_nested(metadata, "dataset.n_events_positive")
    neg = _get_nested(metadata, "dataset.n_events_negative")
    total = _get_nested(metadata, "dataset.n_patients_total")
    if pos is not None and neg is not None and total is not None and total > 0:
        if abs((pos + neg) - total) / total > 0.01:
            _issue("C-001", "ERROR", "dataset",
                   f"n_events_positive({pos}) + n_events_negative({neg}) = {pos+neg} "
                   f"!= n_patients_total({total})")

    # ── P-001: CI consistency ──
    auroc = _get_nested(metadata, "performance_metrics.test_auroc")
    ci_lo = _get_nested(metadata, "performance_metrics.test_auroc_ci_lower")
    ci_hi = _get_nested(metadata, "performance_metrics.test_auroc_ci_upper")
    if auroc is not None and ci_lo is not None and ci_hi is not None:
        if not (ci_lo <= auroc <= ci_hi):
            _issue("P-001", "ERROR", "performance_metrics",
                   f"AUROC {auroc} not within CI [{ci_lo}, {ci_hi}]")

    # ── P-003: Suspicious AUROC ──
    if auroc is not None and isinstance(auroc, (int, float)) and auroc > 0.99:
        _issue("P-003", "WARNING", "performance_metrics.test_auroc",
               f"AUROC={auroc} > 0.99 — extremely suspicious, possible leakage")

    # ── P-004: High AUROC + low prevalence ──
    prev = _get_nested(metadata, "dataset.prevalence_pct")
    if auroc is not None and isinstance(auroc, (int, float)) and auroc > 0.95 and prev is not None and isinstance(prev, (int, float)) and prev < 5:
        _issue("P-004", "WARNING", "performance_metrics",
               f"AUROC={auroc} > 0.95 with prevalence={prev}% < 5% — suspicious")

    # ── P-005/P-006: External validation consistency ──
    ext_val = _get_nested(metadata, "study_design.has_external_validation")
    ext_auroc = _get_nested(metadata, "performance_metrics.external_auroc")
    if ext_auroc is not None and ext_val is False:
        _issue("P-005", "ERROR", "study_design",
               "external_auroc reported but has_external_validation=false")
    if ext_val is True and ext_auroc is None:
        _issue("P-006", "WARNING", "performance_metrics",
               "has_external_validation=true but external_auroc not reported")

    # ── L-001/L-002: tuning field consistency ──
    tuning_test = _get_nested(metadata, "leakage_risk_assessment.tuning_used_test_data")
    tuning_set = _get_nested(metadata, "model.tuning_set")
    if tuning_test is True and tuning_set is not None and tuning_set != "test_used":
        _issue("L-001", "ERROR", "leakage_risk_assessment",
               f"tuning_used_test_data=true but tuning_set='{tuning_set}'")
    if tuning_set == "test_used" and tuning_test is not True:
        _issue("L-002", "ERROR", "model",
               f"tuning_set='test_used' but tuning_used_test_data={tuning_test}")

    # ── L-004: split strategy vs temporal confirmation ──
    split = _get_nested(metadata, "dataset.split_strategy")
    temporal = _get_nested(metadata, "leakage_risk_assessment.temporal_split_confirmed")
    if split == "random" and temporal is True:
        _issue("L-004", "ERROR", "dataset",
               "split_strategy='random' but temporal_split_confirmed=true — contradictory")

    # ── S-001: multicenter vs source_type ──
    multi = _get_nested(metadata, "study_design.is_multicenter")
    source = _get_nested(metadata, "dataset.source_type")
    if multi is True and source == "EHR_single_center":
        _issue("S-001", "ERROR", "study_design",
               "is_multicenter=true but source_type='EHR_single_center'")

    return issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Score papers from metadata against MLGG review criteria."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--metadata", type=str, help="Path to a single metadata.json.")
    mode.add_argument("--batch-dir", type=str, help="Directory to search for metadata.json files.")

    parser.add_argument("--output", type=str, help="Output JSON path (default: stdout).")
    parser.add_argument("--target-journal", type=str, default="nature_medicine",
                        help="Target journal for context.")
    parser.add_argument("--validate", action="store_true",
                        help="Run validation checks before scoring. Print issues to stderr.")

    args = parser.parse_args()

    if args.metadata:
        path = Path(args.metadata)
        if not path.exists():
            print(f"ERROR: {path} not found.", file=sys.stderr)
            return 2
        with path.open() as f:
            metadata = json.load(f)

        if args.validate:
            issues = validate_metadata(metadata)
            if issues:
                print(f"\n  Validation issues ({len(issues)}):", file=sys.stderr)
                for iss in issues:
                    print(f"    [{iss['level']}] {iss['rule_id']}: {iss['message']}", file=sys.stderr)
                errors = [i for i in issues if i["level"] == "ERROR"]
                if errors:
                    print(f"\n  {len(errors)} ERROR(s) found. Score may be unreliable.\n", file=sys.stderr)
            else:
                print("  Validation: OK (no issues)\n", file=sys.stderr)

        result = score_metadata(metadata)
        if args.validate:
            result["validation_issues"] = issues
        output = result
    else:
        root = Path(args.batch_dir)
        if not root.exists():
            print(f"ERROR: {root} not found.", file=sys.stderr)
            return 2
        files = find_metadata_files(root)
        print(f"Found {len(files)} metadata.json files.", file=sys.stderr)
        output = batch_score(files)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"Output: {out_path}", file=sys.stderr)
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
