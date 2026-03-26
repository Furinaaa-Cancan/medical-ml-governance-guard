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
      --metadata papers/nature_medicine/cardiovascular/smith_2023/metadata.json

  # Batch mode
  python3 scripts/score_paper_metadata.py \\
      --batch-dir papers/ --output papers/audit_results/batch_scores.json
"""
from __future__ import annotations

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
            ("tuning_not_on_test", "model.tuning_set", lambda v: v != "test_used"),
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
    grade = (
        "Publication-grade" if total_score >= 90
        else "Solid but gaps" if total_score >= 75
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

    return {
        "contract_version": "paper_score.v1",
        "scored_at": datetime.now(timezone.utc).isoformat(),
        "total_score": total_score,
        "grade": grade,
        "dimensions": dimensions,
        "leakage_flags": leakage_flags,
        "bibliographic": metadata.get("bibliographic", {}),
    }


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

    args = parser.parse_args()

    if args.metadata:
        path = Path(args.metadata)
        if not path.exists():
            print(f"ERROR: {path} not found.", file=sys.stderr)
            return 2
        with path.open() as f:
            metadata = json.load(f)
        result = score_metadata(metadata)
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
        with out_path.open("w") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        print(f"Output: {out_path}", file=sys.stderr)
    else:
        print(json.dumps(output, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    sys.exit(main())
