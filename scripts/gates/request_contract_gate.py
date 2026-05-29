#!/usr/bin/env python3
"""
Validate structured request contract for medical prediction leakage-safe workflow.
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import hashlib
import json
import math
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    get_remediation,
    print_gate_summary,
    register_remediations,
)
from _gate_utils import _check_json_file_size, add_issue, canonical_metric_token as _shared_canonical_metric_token, is_finite_number as _shared_is_finite_number, resolve_path, to_float, to_int as _shared_to_int


register_remediations({
    "request_file_missing": "Provide --request pointing to a valid request.json file.",
    "request_json_invalid": "request.json contains invalid JSON. Fix syntax errors.",
    "required_field_missing": "A required field is missing from request.json. Add the field.",
    "invalid_claim_tier": "claim_tier_target must be one of: leakage-audited, publication-grade.",
    "split_path_missing": "Declared split path does not exist on disk. Verify file paths.",
    "metric_not_finite": "actual_primary_metric must be a finite number.",
    "invalid_context": "context field must be an object when provided.",
})


REQUIRED_STRING_FIELDS = [
    "study_id",
    "run_id",
    "target_name",
    "prediction_unit",
    "index_time_col",
    "label_col",
    "patient_id_col",
    "primary_metric",
    "phenotype_definition_spec",
    "claim_tier_target",
]

ALLOWED_CLAIM_TIERS = {"leakage-audited", "publication-grade"}

# Rank-ordered claim tiers (monotone by strictness). Used by the
# cross-run anti-downgrade check — once a study_id has been at
# publication-grade, a subsequent run at leakage-audited is refused.
# Lower rank = less strict. Add new tiers here in order.
_CLAIM_TIER_RANK = {
    "leakage-audited": 1,
    "publication-grade": 2,
}


# Files / dirs that mark an MLGG project root. Used to anchor the
# path sandbox tightly instead of trusting the request file's
# parent-of-parent blindly (Codex 2026-04-23 caller-controlled
# sandbox finding).
_PROJECT_ROOT_MARKERS = (
    "SKILL.md",           # MLGG-specific marker
    ".git",               # git root
    "pyproject.toml",     # python project root
    ".mlgg_model_key",    # deployed-project marker
)


# ── Cross-run anti-downgrade state (Codex 2026-04-23 Contract #4) ──
#
# Tracks the highest claim_tier_target ever asserted for each
# study_id, persisted at <project_sandbox>/.mlgg/claim_tier_history.json.
# Refuses any subsequent request that would regress below the
# previously-established tier.
#
# Rationale: a publication-grade run has already asserted (through
# external validation, calibration, etc.) that the cohort definition
# for study_id X meets the high bar. A later run at leakage-audited
# for the same study_id either means the cohort definition changed
# and should be a NEW study_id, or someone is attempting to
# post-hoc weaken the claim. Both warrant explicit refusal.

_DOWNGRADE_STATE_DIR = ".mlgg"
_DOWNGRADE_STATE_FILE = "claim_tier_history.json"
_DOWNGRADE_SCHEMA = "mlgg-claim-tier-history-v1"


def _downgrade_state_path(sandbox: Path) -> Path:
    return sandbox / _DOWNGRADE_STATE_DIR / _DOWNGRADE_STATE_FILE


def _load_downgrade_history(sandbox: Path) -> Dict[str, Any]:
    """Read the per-project claim-tier history file. Returns an
    empty-but-valid history structure if the file is missing OR
    malformed (we don't want a corrupted history file to wedge every
    future run — the new run will rewrite it). Malformed files are
    logged to stderr for visibility.
    """
    path = _downgrade_state_path(sandbox)
    if not path.exists():
        return {"schema": _DOWNGRADE_SCHEMA, "study_ids": {}}
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or "study_ids" not in data:
            raise ValueError("history file missing 'study_ids' object")
        if not isinstance(data["study_ids"], dict):
            raise ValueError("'study_ids' must be an object")
        return data
    except Exception as exc:
        print(
            f"WARN: claim-tier history at {path} malformed "
            f"({exc}); starting fresh. Investigate before the next run.",
            file=sys.stderr,
        )
        return {"schema": _DOWNGRADE_SCHEMA, "study_ids": {}}


def _check_and_update_downgrade(
    sandbox: Path,
    study_id: str,
    run_id: str,
    current_tier: str,
    failures: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Check current claim_tier_target against study_id's historical
    high-water mark. Append a downgrade failure when current < high;
    otherwise update the history file.

    Returns a summary dict for inclusion in the normalized request
    envelope (so callers and downstream gates see what was checked).
    """
    history = _load_downgrade_history(sandbox)
    current_rank = _CLAIM_TIER_RANK.get(current_tier, 0)
    entry = history["study_ids"].get(study_id)
    summary = {
        "history_path": str(_downgrade_state_path(sandbox)),
        "current_tier": current_tier,
        "current_rank": current_rank,
        "previous_tier": entry.get("highest_tier") if entry else None,
        "is_new_study_id": entry is None,
    }
    if entry is not None:
        prior_tier = entry.get("highest_tier", "")
        prior_rank = _CLAIM_TIER_RANK.get(prior_tier, 0)
        if current_rank < prior_rank:
            add_issue(
                failures,
                "publication_grade_downgrade_cross_run",
                "study_id was previously asserted at a stricter claim tier. "
                "Downgrading is refused — either fix this request to match "
                "the previously-asserted tier, or use a new study_id if the "
                "cohort has genuinely changed.",
                {
                    "study_id": study_id,
                    "previous_highest_tier": prior_tier,
                    "previous_run_id": entry.get("last_run_id"),
                    "previous_timestamp": entry.get("last_timestamp"),
                    "current_tier": current_tier,
                    "remediation": (
                        f"Set claim_tier_target >= {prior_tier}, or use a "
                        f"new study_id for a legitimately-different cohort. "
                        f"History: {_downgrade_state_path(sandbox)}"
                    ),
                },
            )
            summary["downgrade_detected"] = True
            return summary

    # No downgrade — update the high-water mark and append to history.
    new_entry = {
        "highest_tier": (
            current_tier if entry is None or current_rank > _CLAIM_TIER_RANK.get(
                entry.get("highest_tier", ""), 0,
            ) else entry["highest_tier"]
        ),
        "first_timestamp": (
            entry["first_timestamp"] if entry else time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(),
            )
        ),
        "last_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "last_run_id": run_id,
        "history": (entry.get("history", []) if entry else []) + [{
            "tier": current_tier,
            "run_id": run_id,
            "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }],
    }
    # Truncate history to last 50 entries to avoid unbounded growth.
    new_entry["history"] = new_entry["history"][-50:]
    history["study_ids"][study_id] = new_entry

    try:
        state_path = _downgrade_state_path(sandbox)
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with state_path.open("w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2, sort_keys=True)
            fh.write("\n")
    except OSError as exc:
        print(
            f"WARN: failed to persist claim-tier history at {state_path}: "
            f"{exc}. Downgrade protection will regress on next run.",
            file=sys.stderr,
        )

    summary["downgrade_detected"] = False
    summary["updated_highest_tier"] = new_entry["highest_tier"]
    return summary


def _detect_project_root(start: Path, max_hops: int = 10) -> Optional[Path]:
    """Ascend from ``start`` looking for a project-root marker.

    Returns the first directory containing any marker in
    ``_PROJECT_ROOT_MARKERS``, or None if nothing is found within
    ``max_hops`` parent directories.

    This is the source of truth for path_sandbox anchoring. If this
    returns None, the caller should fall back to a permissive sandbox
    (request_base.parent) AND emit a warning — that configuration is
    intentionally more risky and operators should see it.
    """
    current = start.resolve()
    for _ in range(max_hops):
        for marker in _PROJECT_ROOT_MARKERS:
            if (current / marker).exists():
                return current
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None
MANDATORY_CLINICAL_METRICS = [
    "accuracy",
    "precision",
    "ppv",
    "npv",
    "sensitivity",
    "specificity",
    "f1",
    "f2_beta",
    "roc_auc",
    "pr_auc",
    "brier",
]

# ---------------------------------------------------------------------------
# Profile-based threshold overrides
# Loaded from references/standards/publication-policy-baselines.json at import time.
# See references/operations/gate-strictness-profiles.md for rationale.
# ---------------------------------------------------------------------------

_POLICY_JSON_PATH = Path(__file__).resolve().parent.parent.parent / "references" / "standards" / "publication-policy-baselines.json"


def _decode_gap_keys(d: Dict[str, Any]) -> Dict[str, Any]:
    """Convert pipe-delimited gap_thresholds_max keys to tuples.

    JSON keys like "train|valid|pr_auc" → Python tuple ("train", "valid", "pr_auc").
    Also converts list-typed allowed_selection_splits/scopes to sets.
    """
    result = {}
    for k, v in d.items():
        if k == "gap_thresholds_max" and isinstance(v, dict):
            result[k] = {tuple(key.split("|")): val for key, val in v.items()}
        elif k in ("allowed_selection_splits", "allowed_selection_scopes") and isinstance(v, list):
            result[k] = set(v)
        elif isinstance(v, dict):
            result[k] = _decode_gap_keys(v)
        else:
            result[k] = v
    return result


def _load_policy_json() -> tuple:
    """Load baselines and profile overrides from JSON. Returns (baselines, overrides)."""
    with open(_POLICY_JSON_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    baselines = _decode_gap_keys(raw["baselines"])
    overrides = {}
    for profile_name, profile_data in raw.get("profile_overrides", {}).items():
        overrides[profile_name] = _decode_gap_keys(profile_data)
    return baselines, overrides


PUBLICATION_POLICY_BASELINES, _PROFILE_OVERRIDES = _load_policy_json()
ALLOWED_PROFILES = set(_PROFILE_OVERRIDES.keys())


def _apply_profile(baselines: Dict[str, Any], profile: str) -> Dict[str, Any]:
    """Deep-merge profile overrides onto a copy of baselines."""
    import copy
    result = copy.deepcopy(baselines)
    overrides = _PROFILE_OVERRIDES.get(profile, {})
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key].update(value)
        else:
            result[key] = value
    return result



# ── parse_args (6 lines) ──────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate structured request JSON for medical prediction workflow.")
    parser.add_argument("--request", required=True, help="Path to request JSON.")
    parser.add_argument("--report", help="Optional output JSON report path.")
    parser.add_argument("--strict", action="store_true", help="Enable strict contract requirements.")
    parser.add_argument(
        "--allow-tier-downgrade",
        action="store_true",
        help=(
            "Explicitly permit this run to use a LOWER claim_tier_target "
            "than the study_id has been at before (reverse of the "
            "Codex-2026-04-23 anti-downgrade check). Use only for "
            "deliberate research-only rollbacks; a publication-grade "
            "result then loses its monotone-strictness guarantee."
        ),
    )
    return parser.parse_args()




def is_finite_number(value: Any) -> bool:
    return _shared_is_finite_number(value)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def must_be_non_empty_str(request: Dict[str, Any], key: str, failures: List[Dict[str, Any]]) -> Optional[str]:
    value = request.get(key)
    if not isinstance(value, str) or not value.strip():
        add_issue(
            failures,
            "invalid_field",
            "Required field must be a non-empty string.",
            {"field": key},
        )
        return None
    return value.strip()



# ── validate_thresholds (112 lines) ──────────────────────────

def validate_thresholds(
    request: Dict[str, Any], failures: List[Dict[str, Any]], warnings: List[Dict[str, Any]], strict: bool
) -> Dict[str, float]:
    thresholds = request.get("thresholds", {})
    if thresholds is None:
        thresholds = {}
    if not isinstance(thresholds, dict):
        add_issue(
            failures,
            "invalid_thresholds",
            "thresholds must be an object.",
            {"actual_type": type(thresholds).__name__},
        )
        return {}

    # ── Profile resolution ──
    profile = thresholds.get("profile", "standard")
    if profile not in ALLOWED_PROFILES:
        add_issue(
            warnings,
            "unknown_profile",
            f"thresholds.profile='{profile}' not recognized. "
            f"Allowed: {sorted(ALLOWED_PROFILES)}. Using 'standard'.",
            {"profile": profile},
        )
        profile = "standard"

    # Store resolved profile for downstream gates
    request["_resolved_profile"] = profile
    request["_resolved_policy"] = _apply_profile(PUBLICATION_POLICY_BASELINES, profile)

    parsed: Dict[str, float] = {}
    for key in ("alpha", "min_delta", "min_baseline_delta", "ci_max_width"):
        if key in thresholds:
            value = thresholds[key]
            if is_finite_number(value):
                parsed[key] = float(value)
            else:
                add_issue(
                    failures,
                    "invalid_threshold_value",
                    "Threshold value must be a finite number.",
                    {"field": key, "actual_type": type(value).__name__},
                )

    if "ci_min_resamples" in thresholds:
        value = thresholds["ci_min_resamples"]
        if isinstance(value, bool):
            value = None
        if isinstance(value, int):
            parsed["ci_min_resamples"] = float(value)
        elif isinstance(value, float) and math.isfinite(value) and float(value).is_integer():
            parsed["ci_min_resamples"] = float(int(value))
        else:
            add_issue(
                failures,
                "invalid_threshold_value",
                "Threshold value must be an integer.",
                {"field": "ci_min_resamples", "actual_type": type(thresholds["ci_min_resamples"]).__name__},
            )

    if "alpha" in parsed and not (0.0 < parsed["alpha"] <= 1.0):
        add_issue(
            failures,
            "invalid_threshold_alpha_range",
            "thresholds.alpha must be within (0, 1].",
            {"alpha": parsed["alpha"]},
        )
    if "min_delta" in parsed and parsed["min_delta"] < 0.0:
        add_issue(
            failures,
            "invalid_threshold_min_delta_range",
            "thresholds.min_delta must be >= 0.",
            {"min_delta": parsed["min_delta"]},
        )
    if "min_baseline_delta" in parsed and parsed["min_baseline_delta"] < 0.0:
        add_issue(
            failures,
            "invalid_threshold_min_baseline_delta_range",
            "thresholds.min_baseline_delta must be >= 0.",
            {"min_baseline_delta": parsed["min_baseline_delta"]},
        )
    if "ci_max_width" in parsed and parsed["ci_max_width"] <= 0.0:
        add_issue(
            failures,
            "invalid_threshold_ci_max_width_range",
            "thresholds.ci_max_width must be > 0.",
            {"ci_max_width": parsed["ci_max_width"]},
        )
    if "ci_min_resamples" in parsed and parsed["ci_min_resamples"] < 1.0:
        add_issue(
            failures,
            "invalid_threshold_ci_min_resamples_range",
            "thresholds.ci_min_resamples must be >= 1.",
            {"ci_min_resamples": parsed["ci_min_resamples"]},
        )

    if strict and "alpha" not in parsed:
        add_issue(
            warnings,
            "missing_threshold_alpha",
            "thresholds.alpha not provided; workflow will use default.",
            {"default": 0.01},
        )
    if strict and "min_delta" not in parsed:
        add_issue(
            warnings,
            "missing_threshold_min_delta",
            "thresholds.min_delta not provided; workflow will use default.",
            {"default": 0.03},
        )
    return parsed


def require_numeric(request: Dict[str, Any], key: str, failures: List[Dict[str, Any]]) -> Optional[float]:
    value = request.get(key)
    if is_finite_number(value):
        return float(value)
    add_issue(
        failures,
        "invalid_numeric_field",
        "Required field must be a finite number.",
        {"field": key, "actual_type": type(value).__name__ if value is not None else None},
    )
    return None


def is_valid_dot_path(path: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*", path))


def canonical_metric_token(value: str) -> str:
    return _shared_canonical_metric_token(value)



def to_int(value: Any) -> Optional[int]:
    return _shared_to_int(value)


def get_gap_pair_block(gap_thresholds: Dict[str, Any], left: str, right: str) -> Optional[Dict[str, Any]]:
    for key in (f"{left}_{right}", f"{left}-{right}", f"{left}{right}"):
        block = gap_thresholds.get(key)
        if isinstance(block, dict):
            return block
    return None



# ── validate_evaluation_report_shape (220 lines) ──────────────────────────

def validate_evaluation_report_shape(
    evaluation_report_path: str,
    failures: List[Dict[str, Any]],
    cross_sectional: bool = False,
    relaxed_profile: bool = False,
) -> None:
    path = Path(evaluation_report_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_evaluation_report",
            "Unable to parse evaluation_report_file JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    split_metrics = payload.get("split_metrics")
    if not isinstance(split_metrics, dict):
        add_issue(
            failures,
            "evaluation_report_missing_split_metrics",
            "evaluation_report_file must include split_metrics with train/valid/test entries.",
            {
                "path": str(path),
                "migration_hint": "Add split_metrics.{train,valid,test}.metrics and confusion_matrix blocks.",
            },
        )
    else:
        for split_name in ("train", "valid", "test"):
            block = split_metrics.get(split_name)
            if not isinstance(block, dict):
                add_issue(
                    failures,
                    "evaluation_report_missing_split_metrics",
                    "Required split missing from evaluation_report split_metrics.",
                    {"path": str(path), "split": split_name},
                )
                continue
            if not isinstance(block.get("metrics"), dict):
                add_issue(
                    failures,
                    "evaluation_report_missing_split_metrics",
                    "split_metrics.<split>.metrics must be an object.",
                    {"path": str(path), "split": split_name},
                )
            if not isinstance(block.get("confusion_matrix"), dict):
                add_issue(
                    failures,
                    "evaluation_report_missing_split_metrics",
                    "split_metrics.<split>.confusion_matrix must be an object.",
                    {"path": str(path), "split": split_name},
                )

    threshold_selection = payload.get("threshold_selection")
    if not isinstance(threshold_selection, dict):
        add_issue(
            failures,
            "evaluation_report_missing_threshold_selection",
            "evaluation_report_file must include threshold_selection metadata.",
            {
                "path": str(path),
                "migration_hint": "Add threshold_selection.selection_split and selected_threshold.",
            },
        )
    else:
        selection_split = threshold_selection.get("selection_split")
        if not isinstance(selection_split, str) or not selection_split.strip():
            add_issue(
                failures,
                "evaluation_report_missing_threshold_selection",
                "threshold_selection.selection_split must be a non-empty string.",
                {"path": str(path)},
            )
        else:
            token = selection_split.strip().lower()
            allowed = {"valid", "cv_inner", "nested_cv"}
            if token not in allowed:
                add_issue(
                    failures,
                    "threshold_selection_split_invalid",
                    "threshold_selection.selection_split must be valid/cv_inner/nested_cv (never train/test).",
                    {"path": str(path), "selection_split": selection_split, "allowed": sorted(allowed)},
                )

    feature_engineering = payload.get("feature_engineering")
    if not isinstance(feature_engineering, dict):
        add_issue(
            failures,
            "evaluation_report_missing_feature_engineering",
            "evaluation_report_file must include feature_engineering block.",
            {
                "path": str(path),
                "migration_hint": "Add feature_engineering.provenance with selected_features and reproducibility evidence.",
            },
        )
    else:
        provenance = feature_engineering.get("provenance")
        if not isinstance(provenance, dict):
            add_issue(
                failures,
                "evaluation_report_missing_feature_engineering",
                "evaluation_report.feature_engineering.provenance must be an object.",
                {"path": str(path)},
            )

    distribution_summary = payload.get("distribution_summary")
    if not isinstance(distribution_summary, dict):
        add_issue(
            failures,
            "evaluation_report_missing_distribution_summary",
            "evaluation_report_file must include distribution_summary object.",
            {
                "path": str(path),
                "migration_hint": "Add distribution_summary with split drift diagnostics summary.",
            },
        )

    ci_matrix_ref = payload.get("ci_matrix_ref")
    if not isinstance(ci_matrix_ref, str) or not ci_matrix_ref.strip():
        add_issue(
            failures,
            "evaluation_report_missing_ci_matrix_ref",
            "evaluation_report_file must include non-empty ci_matrix_ref.",
            {
                "path": str(path),
                "migration_hint": "Add ci_matrix_ref pointing to ci_matrix_report artifact.",
            },
        )

    transport_ci_ref = payload.get("transport_ci_ref")
    if not isinstance(transport_ci_ref, str) or not transport_ci_ref.strip():
        add_issue(
            failures,
            "evaluation_report_missing_transport_ci_ref",
            "evaluation_report_file must include non-empty transport_ci_ref.",
            {
                "path": str(path),
                "migration_hint": "Add transport_ci_ref pointing to transport-drop CI section/report.",
            },
        )

    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        add_issue(
            failures,
            "evaluation_report_missing_metadata",
            "evaluation_report_file must include metadata object.",
            {
                "path": str(path),
                "migration_hint": "Add metadata.imputation and metadata.data_fingerprints for execution-level auditability.",
            },
        )
    else:
        imputation = metadata.get("imputation")
        if not isinstance(imputation, dict):
            add_issue(
                failures,
                "evaluation_report_missing_imputation_metadata",
                "evaluation_report.metadata.imputation must be an object.",
                {
                    "path": str(path),
                    "migration_hint": "Add metadata.imputation.{policy_strategy,executed_strategy,fit_scope,scale_guard}.",
                },
            )
        else:
            for key in ("policy_strategy", "executed_strategy", "fit_scope"):
                raw = imputation.get(key)
                if not isinstance(raw, str) or not raw.strip():
                    add_issue(
                        failures,
                        "evaluation_report_missing_imputation_metadata",
                        "evaluation_report.metadata.imputation field must be a non-empty string.",
                        {"path": str(path), "field": f"metadata.imputation.{key}"},
                    )
            scale_guard = imputation.get("scale_guard")
            if not isinstance(scale_guard, dict):
                add_issue(
                    failures,
                    "evaluation_report_missing_imputation_metadata",
                    "evaluation_report.metadata.imputation.scale_guard must be an object.",
                    {"path": str(path)},
                )

        trace_sha = metadata.get("prediction_trace_sha256")
        if not isinstance(trace_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", trace_sha.strip().lower()):
            add_issue(
                failures,
                "evaluation_report_missing_prediction_trace_hash",
                "evaluation_report.metadata.prediction_trace_sha256 must be 64-char lowercase hex.",
                {
                    "path": str(path),
                    "migration_hint": "Add metadata.prediction_trace_sha256 computed from prediction_trace_file.",
                },
            )

        # External validation checks — required for publication-grade standard
        # profile unless cross-sectional or relaxed profile (small_cohort etc.).
        _ext_issues = failures if (not relaxed_profile) else []  # drop for relaxed
        if not cross_sectional and not relaxed_profile:
            external_sha = metadata.get("external_validation_report_sha256")
            if not isinstance(external_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", external_sha.strip().lower()):
                add_issue(
                    _ext_issues,
                    "evaluation_report_missing_external_validation_hash",
                    "evaluation_report.metadata.external_validation_report_sha256 must be 64-char lowercase hex.",
                    {
                        "path": str(path),
                        "migration_hint": "Add metadata.external_validation_report_sha256 computed from external_validation_report_file.",
                    },
                )

            external_count = metadata.get("external_cohort_count")
            external_count_i = to_int(external_count)
            if external_count_i is None or external_count_i < 2:
                add_issue(
                    _ext_issues,
                    "evaluation_report_external_cohort_count_invalid",
                    "evaluation_report.metadata.external_cohort_count must be integer >= 2 for publication-grade dual external coverage.",
                    {"path": str(path), "external_cohort_count": external_count},
                )



# ── validate_model_selection_report_shape (82 lines) ──────────────────────────

def validate_model_selection_report_shape(
    model_selection_report_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(model_selection_report_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_model_selection_report",
            "Unable to parse model_selection_report_file JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    selection_policy = payload.get("selection_policy")
    if not isinstance(selection_policy, dict):
        add_issue(
            failures,
            "model_selection_missing_policy",
            "model_selection_report_file must include selection_policy object.",
            {"path": str(path)},
        )
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) < 3:
        add_issue(
            failures,
            "model_selection_invalid_candidates",
            "model_selection_report_file must include at least 3 candidate entries.",
            {"path": str(path)},
        )
        candidates = []

    for idx, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            add_issue(
                failures,
                "model_selection_invalid_candidate",
                "Each candidate entry must be an object.",
                {"path": str(path), "index": idx},
            )
            continue
        metrics = candidate.get("selection_metrics")
        metric_block = metrics.get("pr_auc") if isinstance(metrics, dict) else None
        if not isinstance(metric_block, dict):
            add_issue(
                failures,
                "model_selection_invalid_candidate",
                "Candidate must include selection_metrics.pr_auc object.",
                {"path": str(path), "index": idx},
            )
            continue
        n_folds = metric_block.get("n_folds")
        fold_scores = metric_block.get("fold_scores")
        if not isinstance(n_folds, (int, float)) or isinstance(n_folds, bool):
            add_issue(
                failures,
                "model_selection_invalid_candidate",
                "Candidate selection_metrics.pr_auc.n_folds must be numeric.",
                {"path": str(path), "index": idx},
            )
        if not isinstance(fold_scores, list) or not fold_scores:
            add_issue(
                failures,
                "model_selection_invalid_candidate",
                "Candidate selection_metrics.pr_auc.fold_scores must be a non-empty list.",
                {"path": str(path), "index": idx},
            )

    data_fingerprints = payload.get("data_fingerprints")
    if not isinstance(data_fingerprints, dict):
        add_issue(
            failures,
            "model_selection_missing_data_fingerprints",
            "model_selection_report_file must include data_fingerprints.{train,valid,test}.",
            {"path": str(path)},
        )


def validate_seed_sensitivity_report_shape(
    seed_report_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(seed_report_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_seed_sensitivity_report",
            "Unable to parse seed_sensitivity_report_file JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    primary_metric = payload.get("primary_metric")
    if not isinstance(primary_metric, str) or not primary_metric.strip():
        add_issue(
            failures,
            "invalid_seed_sensitivity_report",
            "seed_sensitivity_report_file must include non-empty primary_metric.",
            {"path": str(path)},
        )

    per_seed = payload.get("per_seed_results")
    if not isinstance(per_seed, list) or not per_seed:
        add_issue(
            failures,
            "invalid_seed_sensitivity_report",
            "seed_sensitivity_report_file must include non-empty per_seed_results list.",
            {"path": str(path)},
        )

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        add_issue(
            failures,
            "invalid_seed_sensitivity_report",
            "seed_sensitivity_report_file must include summary object.",
            {"path": str(path)},
        )



# ── validate_robustness_report_shape (62 lines) ──────────────────────────

def validate_robustness_report_shape(
    robustness_report_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(robustness_report_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_robustness_report",
            "Unable to parse robustness_report_file JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    overall = payload.get("overall_test_metrics")
    if not isinstance(overall, dict):
        add_issue(
            failures,
            "invalid_robustness_report",
            "robustness_report_file must include overall_test_metrics object.",
            {"path": str(path)},
        )
    elif not is_finite_number(overall.get("pr_auc")):
        add_issue(
            failures,
            "invalid_robustness_report",
            "robustness_report_file.overall_test_metrics.pr_auc must be finite numeric.",
            {"path": str(path), "value": overall.get("pr_auc")},
        )

    time_slices = payload.get("time_slices")
    # Fail-closed: a self-attested `skipped: true` flag alone must NOT clear the
    # temporal-robustness completeness requirement. The skip is only honored when
    # corroborated by a substantive justification (>= 20 non-whitespace chars).
    # Otherwise a study could self-declare time-slice robustness skipped and dodge
    # the check entirely. The producer (train_select_evaluate.py) emits the
    # corroboration in `time_slices.reason` (e.g. "cross_sectional_no_event_time")
    # for legitimate cross-sectional studies that have no temporal dimension; we
    # accept either `skip_justification` or `reason`.
    _skip_flag = isinstance(time_slices, dict) and bool(time_slices.get("skipped"))
    _justification = None
    if isinstance(time_slices, dict):
        _justification = time_slices.get("skip_justification") or time_slices.get("reason")
    _justified = isinstance(_justification, str) and len(_justification.strip()) >= 20
    _time_skipped = _skip_flag and _justified
    if _skip_flag and not _justified:
        add_issue(
            failures,
            "invalid_robustness_report",
            "robustness_report_file.time_slices.skipped requires a corroborating "
            "time_slices.skip_justification or time_slices.reason (>= 20 chars); a "
            "self-attested skip flag alone cannot suppress the temporal-robustness "
            "completeness requirement.",
            {"path": str(path), "justification": _justification},
        )
    if not _time_skipped and (not isinstance(time_slices, dict) or not isinstance(time_slices.get("slices"), list) or not time_slices.get("slices")):
        add_issue(
            failures,
            "invalid_robustness_report",
            "robustness_report_file must include non-empty time_slices.slices list.",
            {"path": str(path)},
        )

    groups = payload.get("patient_hash_groups")
    if not isinstance(groups, dict) or not isinstance(groups.get("groups"), list) or not groups.get("groups"):
        add_issue(
            failures,
            "invalid_robustness_report",
            "robustness_report_file must include non-empty patient_hash_groups.groups list.",
            {"path": str(path)},
        )

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        add_issue(
            failures,
            "invalid_robustness_report",
            "robustness_report_file must include summary object.",
            {"path": str(path)},
        )


def validate_execution_attestation_shape(
    attestation_spec_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(attestation_spec_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_execution_attestation_spec",
            "Unable to parse execution_attestation_spec JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    required = {
        "training_log",
        "training_config",
        "model_artifact",
        "model_selection_report",
        "robustness_report",
        "seed_sensitivity_report",
        "evaluation_report",
        "prediction_trace",
        "external_validation_report",
    }
    names = payload.get("required_artifact_names")
    if not isinstance(names, list):
        add_issue(
            failures,
            "invalid_execution_attestation_spec",
            "execution_attestation_spec.required_artifact_names must be a list.",
            {"path": str(path)},
        )
        return
    clean = {str(x).strip() for x in names if isinstance(x, str) and str(x).strip()}
    missing = sorted(required - clean)
    if missing:
        add_issue(
            failures,
            "missing_execution_attestation_required_artifact",
            "execution_attestation_spec.required_artifact_names is missing mandatory artifact names.",
            {"path": str(path), "missing_required_artifacts": missing},
        )



# ── validate_external_cohort_spec_shape (102 lines) ──────────────────────────

def validate_external_cohort_spec_shape(
    external_cohort_spec_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(external_cohort_spec_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_external_cohort_spec",
            "Unable to parse external_cohort_spec JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    cohorts = payload.get("cohorts")
    if not isinstance(cohorts, list) or not cohorts:
        add_issue(
            failures,
            "external_cohort_spec_missing_cohorts",
            "external_cohort_spec must include non-empty cohorts list.",
            {
                "path": str(path),
                "migration_hint": "Add cohorts entries with cohort_id/cohort_type/path for external validation.",
            },
        )
        return

    allowed_types = {"cross_period", "cross_institution"}
    observed_types: set[str] = set()
    for idx, entry in enumerate(cohorts):
        if not isinstance(entry, dict):
            add_issue(
                failures,
                "external_cohort_spec_invalid_entry",
                "Each external cohort entry must be an object.",
                {"path": str(path), "index": idx},
            )
            continue
        cohort_id = str(entry.get("cohort_id", "")).strip()
        cohort_type = str(entry.get("cohort_type", "")).strip().lower()
        data_path = entry.get("path")
        if not cohort_id:
            add_issue(
                failures,
                "external_cohort_spec_invalid_entry",
                "external cohort entry must include non-empty cohort_id.",
                {"path": str(path), "index": idx},
            )
        if cohort_type not in allowed_types:
            add_issue(
                failures,
                "external_cohort_spec_invalid_entry",
                "external cohort entry must use supported cohort_type.",
                {"path": str(path), "index": idx, "cohort_type": cohort_type, "allowed": sorted(allowed_types)},
            )
        else:
            observed_types.add(cohort_type)
        if not isinstance(data_path, str) or not data_path.strip():
            add_issue(
                failures,
                "external_cohort_spec_invalid_entry",
                "external cohort entry must include non-empty path.",
                {"path": str(path), "index": idx},
            )
            continue
        # External cohort paths are deliberately not sandbox-restricted:
        # external validation cohorts routinely live outside the project
        # tree (e.g., /shared/cohorts/, another hospital's data mount).
        # The _FORBIDDEN_PATH_PREFIXES denylist inside resolve_path still
        # blocks /etc, /proc, /sys, etc.
        resolved = resolve_path(path.parent, data_path.strip())
        if not resolved.exists() or not resolved.is_file():
            add_issue(
                failures,
                "external_cohort_path_not_found",
                "external cohort path does not exist or is not a file.",
                {"path": str(path), "index": idx, "cohort_path": str(resolved)},
            )

    if not observed_types:
        add_issue(
            failures,
            "external_cohort_spec_missing_supported_type",
            "external_cohort_spec must include at least one supported cohort_type.",
            {"path": str(path), "allowed_any_of": sorted(allowed_types)},
        )
        return

    missing_types = sorted(allowed_types - observed_types)
    if missing_types:
        add_issue(
            failures,
            "external_cohort_spec_missing_supported_type",
            "Publication-grade requires both cross_period and cross_institution cohorts in external_cohort_spec.",
            {
                "path": str(path),
                "observed_types": sorted(observed_types),
                "missing_types": missing_types,
                "required_types": sorted(allowed_types),
            },
        )



# ── validate_external_validation_report_shape (81 lines) ──────────────────────────

def validate_external_validation_report_shape(
    external_validation_report_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(external_validation_report_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_external_validation_report",
            "Unable to parse external_validation_report_file JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    cohorts = payload.get("cohorts")
    if not isinstance(cohorts, list) or not cohorts:
        add_issue(
            failures,
            "external_validation_report_missing_cohorts",
            "external_validation_report must include non-empty cohorts list.",
            {"path": str(path)},
        )
        return

    observed_types: set[str] = set()
    for idx, cohort in enumerate(cohorts):
        if not isinstance(cohort, dict):
            add_issue(
                failures,
                "external_validation_report_invalid_cohort",
                "Each cohort entry in external_validation_report must be an object.",
                {"path": str(path), "index": idx},
            )
            continue
        cohort_id = str(cohort.get("cohort_id", "")).strip()
        cohort_type = str(cohort.get("cohort_type", "")).strip().lower()
        if not cohort_id:
            add_issue(
                failures,
                "external_validation_report_invalid_cohort",
                "external_validation_report cohort entry must include cohort_id.",
                {"path": str(path), "index": idx},
            )
        if cohort_type not in {"cross_period", "cross_institution"}:
            add_issue(
                failures,
                "external_validation_report_invalid_cohort",
                "external_validation_report cohort_type must be cross_period or cross_institution.",
                {"path": str(path), "index": idx, "cohort_type": cohort_type},
            )
        else:
            observed_types.add(cohort_type)
        if not isinstance(cohort.get("metrics"), dict):
            add_issue(
                failures,
                "external_validation_report_invalid_cohort",
                "external_validation_report cohort entry must include metrics object.",
                {"path": str(path), "index": idx},
            )
        if not isinstance(cohort.get("confusion_matrix"), dict):
            add_issue(
                failures,
                "external_validation_report_invalid_cohort",
                "external_validation_report cohort entry must include confusion_matrix object.",
                {"path": str(path), "index": idx},
            )

    missing_types = sorted({"cross_period", "cross_institution"} - observed_types)
    if missing_types:
        add_issue(
            failures,
            "external_validation_report_invalid_cohort",
            "external_validation_report must cover both cross_period and cross_institution cohorts.",
            {"path": str(path), "missing_types": missing_types, "observed_types": sorted(observed_types)},
        )



# ── validate_feature_group_spec_shape (65 lines) ──────────────────────────

def validate_feature_group_spec_shape(
    feature_group_spec_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(feature_group_spec_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "feature_group_spec_missing_or_invalid",
            "Unable to parse feature_group_spec JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    groups = payload.get("groups")
    if not isinstance(groups, dict) or not groups:
        add_issue(
            failures,
            "feature_group_spec_missing_or_invalid",
            "feature_group_spec must include non-empty groups object.",
            {"path": str(path)},
        )
        return
    seen_features: set[str] = set()
    for group_name, features in groups.items():
        if not isinstance(group_name, str) or not group_name.strip():
            add_issue(
                failures,
                "feature_group_spec_missing_or_invalid",
                "feature_group_spec group names must be non-empty strings.",
                {"path": str(path), "group": group_name},
            )
            continue
        # Support timing-aware format: {"timing": "...", "features": [...]}
        if isinstance(features, dict) and "features" in features:
            features = features["features"]
        if not isinstance(features, list) or not features:
            add_issue(
                failures,
                "feature_group_spec_missing_or_invalid",
                "Each feature_group_spec group must map to non-empty feature list.",
                {"path": str(path), "group": group_name},
            )
            continue
        for feature in features:
            if not isinstance(feature, str) or not feature.strip():
                add_issue(
                    failures,
                    "feature_group_spec_missing_or_invalid",
                    "feature_group_spec feature names must be non-empty strings.",
                    {"path": str(path), "group": group_name},
                )
                continue
            feature_name = feature.strip()
            if feature_name in seen_features:
                add_issue(
                    failures,
                    "feature_group_spec_missing_or_invalid",
                    "feature_group_spec must not assign the same feature to multiple groups.",
                    {"path": str(path), "feature": feature_name},
                )
            seen_features.add(feature_name)


def validate_distribution_report_shape(
    distribution_report_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(distribution_report_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "distribution_report_schema_invalid",
            "Unable to parse distribution_report JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    if not isinstance(payload.get("schema_version"), str):
        add_issue(
            failures,
            "distribution_report_schema_invalid",
            "distribution_report must include schema_version string.",
            {"path": str(path)},
        )
    matrix = payload.get("distribution_matrix")
    if not isinstance(matrix, list) or not matrix:
        add_issue(
            failures,
            "distribution_report_schema_invalid",
            "distribution_report must include non-empty distribution_matrix.",
            {"path": str(path)},
        )


def validate_feature_engineering_report_shape(
    feature_engineering_report_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(feature_engineering_report_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "feature_engineering_report_invalid",
            "Unable to parse feature_engineering_report JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    if not isinstance(payload.get("feature_groups"), dict):
        add_issue(
            failures,
            "feature_stability_evidence_missing",
            "feature_engineering_report must include feature_groups object.",
            {"path": str(path)},
        )
    stability = payload.get("stability")
    if not isinstance(stability, dict):
        add_issue(
            failures,
            "feature_stability_evidence_missing",
            "feature_engineering_report must include stability block.",
            {"path": str(path)},
        )
    reproducibility = payload.get("reproducibility")
    if not isinstance(reproducibility, dict):
        add_issue(
            failures,
            "feature_engineering_reproducibility_missing",
            "feature_engineering_report must include reproducibility block.",
            {"path": str(path)},
        )


def validate_ci_matrix_report_shape(
    ci_matrix_report_path: str,
    failures: List[Dict[str, Any]],
) -> None:
    path = Path(ci_matrix_report_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "ci_matrix_input_parse_error",
            "Unable to parse ci_matrix_report JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    split_ci = payload.get("split_metrics_ci")
    if not isinstance(split_ci, dict):
        add_issue(
            failures,
            "ci_matrix_missing_required_metric",
            "ci_matrix_report must include split_metrics_ci object.",
            {"path": str(path)},
        )
    transport_ci = payload.get("transport_drop_ci")
    if not isinstance(transport_ci, dict):
        add_issue(
            failures,
            "transport_ci_invalid",
            "ci_matrix_report must include transport_drop_ci object.",
            {"path": str(path)},
        )


def load_json_object(path: str) -> Optional[Dict[str, Any]]:
    p = Path(path).expanduser().resolve()
    try:
        _check_json_file_size(p)
        with p.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except Exception as exc:
        print(f"[WARN] load_json_object failed for {p}: {exc}", file=sys.stderr)
        return None
    if isinstance(payload, dict):
        return payload
    return None



# ── validate_cross_artifact_alignment (302 lines) ──────────────────────────

def validate_cross_artifact_alignment(
    normalized: Dict[str, Any],
    failures: List[Dict[str, Any]],
    warnings_list: Optional[List[Dict[str, Any]]] = None,
) -> None:
    perf_path = normalized.get("performance_policy_spec")
    eval_path = normalized.get("evaluation_report_file")
    if isinstance(perf_path, str) and perf_path and isinstance(eval_path, str) and eval_path:
        perf_payload = load_json_object(perf_path)
        eval_payload = load_json_object(eval_path)
        if isinstance(perf_payload, dict) and isinstance(eval_payload, dict):
            threshold_policy = perf_payload.get("threshold_policy")
            threshold_selection = eval_payload.get("threshold_selection")
            policy_split = (
                str(threshold_policy.get("selection_split", "")).strip().lower()
                if isinstance(threshold_policy, dict)
                else ""
            )
            eval_split = (
                str(threshold_selection.get("selection_split", "")).strip().lower()
                if isinstance(threshold_selection, dict)
                else ""
            )
            if policy_split and eval_split and policy_split != eval_split:
                add_issue(
                    failures,
                    "threshold_selection_policy_mismatch",
                    "evaluation_report threshold_selection.selection_split must match performance_policy threshold_policy.selection_split.",
                    {"policy_selection_split": policy_split, "evaluation_selection_split": eval_split},
                )

            ci_matrix_ref = eval_payload.get("ci_matrix_ref")
            ci_matrix_path = normalized.get("ci_matrix_report_file")
            if isinstance(ci_matrix_ref, str) and ci_matrix_ref.strip() and isinstance(ci_matrix_path, str) and ci_matrix_path:
                ci_matrix_ref_path = Path(ci_matrix_ref.strip()).expanduser()
                if not ci_matrix_ref_path.is_absolute():
                    ci_matrix_ref_path = (Path(eval_path).expanduser().resolve().parent / ci_matrix_ref_path).resolve()
                else:
                    ci_matrix_ref_path = ci_matrix_ref_path.resolve()
                if ci_matrix_ref_path != Path(ci_matrix_path).expanduser().resolve():
                    add_issue(
                        failures,
                        "ci_matrix_reference_mismatch",
                        "evaluation_report.ci_matrix_ref must match request ci_matrix_report_file.",
                        {
                            "evaluation_ci_matrix_ref": str(ci_matrix_ref_path),
                            "request_ci_matrix_report_file": str(Path(ci_matrix_path).expanduser().resolve()),
                        },
                    )

    model_path = normalized.get("model_selection_report_file")
    tuning_path = normalized.get("tuning_protocol_spec")
    if isinstance(model_path, str) and model_path and isinstance(tuning_path, str) and tuning_path:
        model_payload = load_json_object(model_path)
        tuning_payload = load_json_object(tuning_path)
        if isinstance(model_payload, dict) and isinstance(tuning_payload, dict):
            selection_policy = model_payload.get("selection_policy")
            report_selection_data = (
                str(selection_policy.get("selection_data", "")).strip().lower()
                if isinstance(selection_policy, dict)
                else str(model_payload.get("selection_data", "")).strip().lower()
            )
            tuning_selection_data = str(tuning_payload.get("model_selection_data", "")).strip().lower()
            if report_selection_data and tuning_selection_data and report_selection_data != tuning_selection_data:
                add_issue(
                    failures,
                    "selection_data_spec_mismatch",
                    "model_selection_report selection_data must match tuning_protocol_spec model_selection_data.",
                    {
                        "selection_data_report": report_selection_data,
                        "selection_data_tuning_spec": tuning_selection_data,
                    },
                )

    if isinstance(model_path, str) and model_path and isinstance(eval_path, str) and eval_path:
        model_payload = load_json_object(model_path)
        eval_payload = load_json_object(eval_path)
        required_splits = {"train", "test"}
        split_paths = normalized.get("split_paths")
        if isinstance(split_paths, dict) and isinstance(split_paths.get("valid"), str) and split_paths.get("valid"):
            required_splits.add("valid")
        if isinstance(model_payload, dict) and isinstance(eval_payload, dict):
            selected_model_id = str(model_payload.get("selected_model_id", "")).strip()
            eval_model_id = str(eval_payload.get("model_id", "")).strip()
            if selected_model_id and eval_model_id and selected_model_id != eval_model_id:
                add_issue(
                    failures,
                    "model_id_cross_artifact_mismatch",
                    "evaluation_report.model_id must match model_selection_report.selected_model_id.",
                    {
                        "model_selection_selected_model_id": selected_model_id,
                        "evaluation_model_id": eval_model_id,
                    },
                )

            model_fingerprints = model_payload.get("data_fingerprints")
            eval_metadata = eval_payload.get("metadata")
            eval_fingerprints = (
                eval_metadata.get("data_fingerprints")
                if isinstance(eval_metadata, dict)
                else eval_payload.get("data_fingerprints")
            )
            if isinstance(model_fingerprints, dict) and isinstance(eval_fingerprints, dict):
                for split in sorted(required_splits):
                    model_fp = model_fingerprints.get(split)
                    eval_fp = eval_fingerprints.get(split)
                    if not isinstance(model_fp, dict) or not isinstance(eval_fp, dict):
                        add_issue(
                            failures,
                            "data_fingerprint_missing",
                            "Cross-artifact split fingerprint must exist in both model_selection_report and evaluation_report.",
                            {
                                "split": split,
                                "model_has_split_fingerprint": isinstance(model_fp, dict),
                                "evaluation_has_split_fingerprint": isinstance(eval_fp, dict),
                            },
                        )
                        continue
                    model_sha = str(model_fp.get("sha256", "")).strip().lower()
                    eval_sha = str(eval_fp.get("sha256", "")).strip().lower()
                    if model_sha and eval_sha and model_sha != eval_sha:
                        add_issue(
                            failures,
                            "data_fingerprint_cross_artifact_mismatch",
                            "Split fingerprint sha256 must match between model_selection_report and evaluation_report.",
                            {"split": split, "model_sha256": model_sha, "evaluation_sha256": eval_sha},
                        )
                    model_rows = model_fp.get("row_count")
                    eval_rows = eval_fp.get("row_count")
                    if is_finite_number(model_rows) and is_finite_number(eval_rows):
                        if int(float(model_rows)) != int(float(eval_rows)):
                            add_issue(
                                failures,
                                "data_fingerprint_cross_artifact_mismatch",
                                "Split row_count must match between model_selection_report and evaluation_report.",
                                {
                                    "split": split,
                                    "model_row_count": int(float(model_rows)),
                                    "evaluation_row_count": int(float(eval_rows)),
                                },
                            )

            eval_metadata = eval_payload.get("metadata")
            if isinstance(eval_metadata, dict):
                prediction_trace_path = normalized.get("prediction_trace_file")
                if isinstance(prediction_trace_path, str) and prediction_trace_path:
                    recorded_trace_sha = str(eval_metadata.get("prediction_trace_sha256", "")).strip().lower()
                    actual_trace_sha = ""
                    try:
                        actual_trace_sha = sha256_file(Path(prediction_trace_path).expanduser().resolve()).lower()
                    except Exception as exc:
                        print(f"[WARN] prediction trace hash failed: {exc}", file=sys.stderr)
                        if recorded_trace_sha and re.fullmatch(r"[0-9a-f]{64}", recorded_trace_sha):
                            add_issue(
                                warnings_list if warnings_list is not None else failures,
                                "prediction_trace_hash_unverifiable",
                                f"Cannot verify prediction trace hash: {exc}",
                                {"recorded_sha256": recorded_trace_sha},
                            )
                        actual_trace_sha = ""
                    if (
                        recorded_trace_sha
                        and re.fullmatch(r"[0-9a-f]{64}", recorded_trace_sha)
                        and actual_trace_sha
                        and recorded_trace_sha != actual_trace_sha
                    ):
                        add_issue(
                            failures,
                            "prediction_trace_hash_mismatch",
                            "evaluation_report.metadata.prediction_trace_sha256 must match prediction_trace_file hash.",
                            {
                                "recorded_prediction_trace_sha256": recorded_trace_sha,
                                "actual_prediction_trace_sha256": actual_trace_sha,
                            },
                        )

                external_report_path = normalized.get("external_validation_report_file")
                if isinstance(external_report_path, str) and external_report_path:
                    recorded_external_sha = str(eval_metadata.get("external_validation_report_sha256", "")).strip().lower()
                    actual_external_sha = ""
                    try:
                        actual_external_sha = sha256_file(Path(external_report_path).expanduser().resolve()).lower()
                    except Exception as exc:
                        print(f"[WARN] external report hash failed: {exc}", file=sys.stderr)
                        if recorded_external_sha and re.fullmatch(r"[0-9a-f]{64}", recorded_external_sha):
                            add_issue(
                                warnings_list if warnings_list is not None else failures,
                                "external_report_hash_unverifiable",
                                f"Cannot verify external report hash: {exc}",
                                {"recorded_sha256": recorded_external_sha},
                            )
                        actual_external_sha = ""
                    if (
                        recorded_external_sha
                        and re.fullmatch(r"[0-9a-f]{64}", recorded_external_sha)
                        and actual_external_sha
                        and recorded_external_sha != actual_external_sha
                    ):
                        add_issue(
                            failures,
                            "external_validation_report_hash_mismatch",
                            "evaluation_report.metadata.external_validation_report_sha256 must match external_validation_report_file hash.",
                            {
                                "recorded_external_validation_report_sha256": recorded_external_sha,
                                "actual_external_validation_report_sha256": actual_external_sha,
                            },
                        )

                    ext_payload = load_json_object(external_report_path)
                    if isinstance(ext_payload, dict):
                        cohorts = ext_payload.get("cohorts")
                        cohort_count = len(cohorts) if isinstance(cohorts, list) else 0
                        metadata_count = to_int(eval_metadata.get("external_cohort_count"))
                        if metadata_count is not None and metadata_count != cohort_count:
                            add_issue(
                                failures,
                                "external_cohort_count_mismatch",
                                "evaluation_report.metadata.external_cohort_count must match external_validation_report cohort count.",
                                {
                                    "evaluation_report_external_cohort_count": metadata_count,
                                    "external_validation_report_cohort_count": cohort_count,
                                },
                            )

    seed_path = normalized.get("seed_sensitivity_report_file")
    if isinstance(seed_path, str) and seed_path and isinstance(model_path, str) and model_path:
        seed_payload = load_json_object(seed_path)
        model_payload = load_json_object(model_path)
        if isinstance(seed_payload, dict) and isinstance(model_payload, dict):
            seed_model_id = str(seed_payload.get("model_id", "")).strip()
            selected_model_id = str(model_payload.get("selected_model_id", "")).strip()
            if seed_model_id and selected_model_id and seed_model_id != selected_model_id:
                add_issue(
                    failures,
                    "seed_sensitivity_model_id_mismatch",
                    "seed_sensitivity_report model_id must match model_selection_report selected_model_id.",
                    {"seed_model_id": seed_model_id, "selected_model_id": selected_model_id},
                )
            seed_primary_metric = str(seed_payload.get("primary_metric", "")).strip().lower()
            report_primary_metric = str(model_payload.get("primary_metric", "")).strip().lower()
            if seed_primary_metric and report_primary_metric and seed_primary_metric != report_primary_metric:
                add_issue(
                    failures,
                    "seed_sensitivity_primary_metric_mismatch",
                    "seed_sensitivity_report primary_metric must match model_selection_report primary_metric.",
                    {"seed_primary_metric": seed_primary_metric, "report_primary_metric": report_primary_metric},
                )

    robustness_path = normalized.get("robustness_report_file")
    if isinstance(robustness_path, str) and robustness_path and isinstance(eval_path, str) and eval_path:
        robustness_payload = load_json_object(robustness_path)
        eval_payload = load_json_object(eval_path)
        if isinstance(robustness_payload, dict) and isinstance(eval_payload, dict):
            robust_model_id = str(robustness_payload.get("model_id", "")).strip()
            eval_model_id = str(eval_payload.get("model_id", "")).strip()
            if robust_model_id and eval_model_id and robust_model_id != eval_model_id:
                add_issue(
                    failures,
                    "robustness_model_id_mismatch",
                    "robustness_report model_id must match evaluation_report model_id.",
                    {"robustness_model_id": robust_model_id, "evaluation_model_id": eval_model_id},
                )
            robust_overall = robustness_payload.get("overall_test_metrics")
            eval_metrics = eval_payload.get("metrics")
            robust_pr_auc = robust_overall.get("pr_auc") if isinstance(robust_overall, dict) else None
            eval_pr_auc = eval_metrics.get("pr_auc") if isinstance(eval_metrics, dict) else None
            if is_finite_number(robust_pr_auc) and is_finite_number(eval_pr_auc):
                if abs(float(robust_pr_auc) - float(eval_pr_auc)) > 1e-12:
                    add_issue(
                        failures,
                        "robustness_overall_metric_mismatch",
                        "robustness_report overall_test_metrics.pr_auc must match evaluation_report metrics.pr_auc.",
                        {"robustness_pr_auc": float(robust_pr_auc), "evaluation_pr_auc": float(eval_pr_auc)},
                    )

    if isinstance(tuning_path, str) and tuning_path and isinstance(eval_path, str) and eval_path:
        tuning_payload = load_json_object(tuning_path)
        eval_payload = load_json_object(eval_path)
        if isinstance(tuning_payload, dict) and isinstance(eval_payload, dict):
            final_refit_scope = str(tuning_payload.get("final_model_refit_scope", "")).strip().lower()
            eval_metadata = eval_payload.get("metadata")
            eval_fit_split = (
                str(eval_metadata.get("evaluation_model_fit_split", "")).strip().lower()
                if isinstance(eval_metadata, dict)
                else ""
            )
            expected_fit_scope = {
                "train_only": {"train", "train_only"},
                "train_plus_valid_no_test": {"train_plus_valid", "train_plus_valid_no_test"},
                "outer_train_only": {"outer_train", "outer_train_only"},
            }
            expected = expected_fit_scope.get(final_refit_scope)
            if expected and eval_fit_split and eval_fit_split not in expected:
                add_issue(
                    failures,
                    "final_model_refit_scope_mismatch",
                    "evaluation_report.metadata.evaluation_model_fit_split is inconsistent with tuning_protocol_spec.final_model_refit_scope.",
                    {
                        "final_model_refit_scope": final_refit_scope,
                        "evaluation_model_fit_split": eval_fit_split,
                        "expected_any_of": sorted(expected),
                    },
                )



# ── validate_performance_policy_spec (1145 lines) ──────────────────────────

def validate_performance_policy_spec(
    policy_path: str,
    failures: List[Dict[str, Any]],
    expected_primary_metric: str,
    resolved_baselines: Optional[Dict[str, Any]] = None,
) -> None:
    # Use profile-resolved baselines if provided, else fall back to global defaults.
    # This allows profile=small_cohort/rare_disease to relax clinical floors.
    baselines = resolved_baselines if resolved_baselines else PUBLICATION_POLICY_BASELINES

    path = Path(policy_path).expanduser().resolve()
    try:
        _check_json_file_size(path)
        with path.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if not isinstance(payload, dict):
            raise ValueError("JSON root must be object.")
    except Exception as exc:
        add_issue(
            failures,
            "invalid_performance_policy_spec",
            "Unable to parse performance_policy_spec JSON.",
            {"path": str(path), "error": str(exc)},
        )
        return

    required_keys = [
        "required_metrics",
        "primary_metric",
        "threshold_policy",
        "clinical_floors",
        "clinical_operating_point_v2",
        "gap_thresholds",
        "prediction_replay_thresholds",
        "external_validation_thresholds",
        "calibration_dca_thresholds",
        "distribution_thresholds_v2",
        "feature_engineering_policy",
        "ci_policy",
        "beta",
    ]
    for key in required_keys:
        if key not in payload:
            add_issue(
                failures,
                "missing_performance_policy_field",
                "performance_policy_spec is missing required field.",
                {"path": str(path), "field": key},
            )

    primary_metric = payload.get("primary_metric")
    if not isinstance(primary_metric, str) or not primary_metric.strip():
        add_issue(
            failures,
            "invalid_performance_policy_field",
            "performance_policy_spec.primary_metric must be a non-empty string.",
            {"path": str(path)},
        )
    else:
        if canonical_metric_token(primary_metric) != canonical_metric_token(expected_primary_metric):
            add_issue(
                failures,
                "performance_policy_metric_mismatch",
                "performance_policy_spec.primary_metric must match request primary_metric.",
                {
                    "path": str(path),
                    "policy_primary_metric": primary_metric,
                    "request_primary_metric": expected_primary_metric,
                },
            )

    required_metrics = payload.get("required_metrics")
    if not isinstance(required_metrics, list) or not required_metrics:
        add_issue(
            failures,
            "invalid_performance_policy_field",
            "performance_policy_spec.required_metrics must be a non-empty list.",
            {"path": str(path)},
        )
    else:
        required_metric_tokens = {
            canonical_metric_token(str(x).strip())
            for x in required_metrics
            if isinstance(x, str) and str(x).strip()
        }
        missing_metrics = [
            metric
            for metric in MANDATORY_CLINICAL_METRICS
            if canonical_metric_token(metric) not in required_metric_tokens
        ]
        if missing_metrics:
            add_issue(
                failures,
                "performance_policy_missing_required_metric",
                "performance_policy_spec.required_metrics must include all mandatory clinical metrics.",
                {"path": str(path), "missing_metrics": missing_metrics, "mandatory_metrics": MANDATORY_CLINICAL_METRICS},
            )

    beta = payload.get("beta")
    beta_value = to_float(beta)
    if beta_value is None or beta_value <= 0.0:
        add_issue(
            failures,
            "invalid_performance_policy_field",
            "performance_policy_spec.beta must be finite and > 0.",
            {"path": str(path), "beta": beta},
        )
    elif abs(float(beta_value) - float(baselines["beta"])) > 1e-12:
        add_issue(
            failures,
            "performance_policy_downgrade",
            "Publication-grade policy requires beta fixed to 2.0 for F2 thresholding.",
            {"path": str(path), "beta": float(beta_value), "required_beta": float(baselines["beta"])},
        )

    threshold_policy = payload.get("threshold_policy")
    selection_split_token = ""
    if not isinstance(threshold_policy, dict):
        add_issue(
            failures,
            "invalid_performance_policy_field",
            "performance_policy_spec.threshold_policy must be an object.",
            {"path": str(path)},
        )
    else:
        strategy = str(threshold_policy.get("strategy", "")).strip().lower()
        expected_strategy = str(baselines["threshold_policy_strategy"]).strip().lower()
        if strategy != expected_strategy:
            add_issue(
                failures,
                "performance_policy_downgrade",
                "Publication-grade policy requires threshold_policy.strategy=maximize_fbeta_under_floors.",
                {"path": str(path), "strategy": threshold_policy.get("strategy"), "required": expected_strategy},
            )

        selection_split = threshold_policy.get("selection_split")
        allowed = set(baselines["allowed_selection_splits"])
        if not isinstance(selection_split, str) or selection_split.strip().lower() not in allowed:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "threshold_policy.selection_split must be valid/cv_inner/nested_cv.",
                {"path": str(path), "selection_split": selection_split, "allowed": sorted(allowed)},
            )
        else:
            selection_split_token = selection_split.strip().lower()

        allowed_selection_splits = threshold_policy.get("allowed_selection_splits")
        if allowed_selection_splits is not None:
            if not isinstance(allowed_selection_splits, list) or not allowed_selection_splits:
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "threshold_policy.allowed_selection_splits must be a non-empty list when provided.",
                    {"path": str(path), "allowed_selection_splits": allowed_selection_splits},
                )
            else:
                declared_allowed = {
                    str(x).strip().lower()
                    for x in allowed_selection_splits
                    if isinstance(x, str) and str(x).strip()
                }
                invalid_tokens = sorted(token for token in declared_allowed if token not in allowed)
                if invalid_tokens:
                    add_issue(
                        failures,
                        "performance_policy_downgrade",
                        "threshold_policy.allowed_selection_splits must not include train/test or unknown scopes.",
                        {"path": str(path), "invalid_tokens": invalid_tokens, "allowed": sorted(allowed)},
                    )
                if selection_split_token and selection_split_token not in declared_allowed:
                    add_issue(
                        failures,
                        "invalid_performance_policy_field",
                        "selection_split must be included in allowed_selection_splits.",
                        {
                            "path": str(path),
                            "selection_split": selection_split_token,
                            "allowed_selection_splits": sorted(declared_allowed),
                        },
                    )

    clinical_floors = payload.get("clinical_floors")
    if not isinstance(clinical_floors, dict):
        add_issue(
            failures,
            "invalid_performance_policy_field",
            "performance_policy_spec.clinical_floors must be an object.",
            {"path": str(path)},
        )
    else:
        for key in ("sensitivity_min", "npv_min", "specificity_min", "ppv_min"):
            value = to_float(clinical_floors.get(key))
            if value is None or not (0.0 <= float(value) <= 1.0):
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "clinical floor must be finite within [0,1].",
                    {"path": str(path), "field": key, "value": clinical_floors.get(key)},
                )
                continue
            minimum_floor = float(baselines["clinical_floors_min"][key])
            if value < minimum_floor:
                add_issue(
                    failures,
                    "performance_policy_downgrade",
                    "clinical_floors cannot be relaxed below publication-grade minimum.",
                    {
                        "path": str(path),
                        "field": key,
                        "value": float(value),
                        "required_min": minimum_floor,
                    },
                )

    if isinstance(threshold_policy, dict):
        policy_clinical_floors = threshold_policy.get("clinical_floors")
        if policy_clinical_floors is not None:
            if not isinstance(policy_clinical_floors, dict):
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "threshold_policy.clinical_floors must be an object when provided.",
                    {"path": str(path)},
                )
            else:
                for key in ("sensitivity_min", "npv_min", "specificity_min", "ppv_min"):
                    v_top = to_float(clinical_floors.get(key)) if isinstance(clinical_floors, dict) else None
                    v_policy = to_float(policy_clinical_floors.get(key))
                    if v_policy is None:
                        add_issue(
                            failures,
                            "invalid_performance_policy_field",
                            "threshold_policy.clinical_floors must include finite values for required keys.",
                            {"path": str(path), "field": f"threshold_policy.clinical_floors.{key}"},
                        )
                        continue
                    if v_top is not None and abs(v_top - v_policy) > 1e-12:
                        add_issue(
                            failures,
                            "performance_policy_downgrade",
                            "threshold_policy.clinical_floors must match top-level clinical_floors.",
                            {
                                "path": str(path),
                                "field": key,
                                "top_level": float(v_top),
                                "threshold_policy_value": float(v_policy),
                            },
                        )

    clinical_operating_point_v2 = payload.get("clinical_operating_point_v2")
    if not isinstance(clinical_operating_point_v2, dict):
        add_issue(
            failures,
            "invalid_performance_policy_field",
            "performance_policy_spec.clinical_operating_point_v2 must be an object.",
            {"path": str(path)},
        )
    else:
        floors_block = clinical_operating_point_v2.get("floors")
        if not isinstance(floors_block, dict):
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "clinical_operating_point_v2.floors must be an object.",
                {"path": str(path)},
            )
        else:
            for key in ("sensitivity_min", "npv_min", "specificity_min", "ppv_min"):
                op_value = to_float(floors_block.get(key))
                top_value = to_float(clinical_floors.get(key)) if isinstance(clinical_floors, dict) else None
                if op_value is None or not (0.0 <= op_value <= 1.0):
                    add_issue(
                        failures,
                        "invalid_performance_policy_field",
                        "clinical_operating_point_v2 floor must be finite within [0,1].",
                        {"path": str(path), "field": key, "value": floors_block.get(key)},
                    )
                    continue
                if top_value is not None and abs(op_value - top_value) > 1e-12:
                    add_issue(
                        failures,
                        "performance_policy_downgrade",
                        "clinical_operating_point_v2.floors must match top-level clinical_floors.",
                        {"path": str(path), "field": key, "operating_point": op_value, "clinical_floors": top_value},
                    )

    gap_thresholds = payload.get("gap_thresholds")
    if not isinstance(gap_thresholds, dict):
        add_issue(
            failures,
            "invalid_performance_policy_field",
            "performance_policy_spec.gap_thresholds must be an object.",
            {"path": str(path)},
        )
    else:
        for (left, right, metric), limits in baselines["gap_thresholds_max"].items():
            pair_block = get_gap_pair_block(gap_thresholds, left, right)
            metric_block = pair_block.get(metric) if isinstance(pair_block, dict) else None
            if not isinstance(metric_block, dict):
                add_issue(
                    failures,
                    "performance_policy_missing_threshold_block",
                    "performance_policy_spec.gap_thresholds is missing required pair/metric threshold block.",
                    {"path": str(path), "pair": f"{left}_{right}", "metric": metric},
                )
                continue
            warn_v = to_float(metric_block.get("warn"))
            fail_v = to_float(metric_block.get("fail"))
            if warn_v is None or fail_v is None or warn_v < 0.0 or fail_v < 0.0 or warn_v > fail_v:
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "gap threshold must satisfy finite numeric 0 <= warn <= fail.",
                    {
                        "path": str(path),
                        "pair": f"{left}_{right}",
                        "metric": metric,
                        "warn": metric_block.get("warn"),
                        "fail": metric_block.get("fail"),
                    },
                )
                continue
            if warn_v > float(limits["warn"]) or fail_v > float(limits["fail"]):
                add_issue(
                    failures,
                    "performance_policy_downgrade",
                    "gap_thresholds exceed publication-grade maximum allowed limits.",
                    {
                        "path": str(path),
                        "pair": f"{left}_{right}",
                        "metric": metric,
                        "warn": float(warn_v),
                        "fail": float(fail_v),
                        "max_warn": float(limits["warn"]),
                        "max_fail": float(limits["fail"]),
                    },
                )

    robustness_thresholds = payload.get("robustness_thresholds")
    if not isinstance(robustness_thresholds, dict):
        add_issue(
            failures,
            "performance_policy_missing_threshold_block",
            "performance_policy_spec.robustness_thresholds must be an object.",
            {"path": str(path)},
        )
    else:
        for bucket in ("time_slices", "patient_hash_groups"):
            bucket_block = robustness_thresholds.get(bucket)
            if not isinstance(bucket_block, dict):
                add_issue(
                    failures,
                    "performance_policy_missing_threshold_block",
                    "robustness_thresholds missing required bucket block.",
                    {"path": str(path), "bucket": bucket},
                )
                continue
            for key, max_value in baselines["robustness_thresholds_max"].items():
                raw = to_float(bucket_block.get(key))
                if raw is None or raw < 0.0:
                    add_issue(
                        failures,
                        "invalid_performance_policy_field",
                        "robustness threshold must be finite numeric >= 0.",
                        {"path": str(path), "bucket": bucket, "field": key, "value": bucket_block.get(key)},
                    )
                    continue
                if raw > float(max_value):
                    add_issue(
                        failures,
                        "performance_policy_downgrade",
                        "robustness thresholds cannot be relaxed above publication-grade maxima.",
                        {
                            "path": str(path),
                            "bucket": bucket,
                            "field": key,
                            "value": float(raw),
                            "max_allowed": float(max_value),
                        },
                    )
            warn_drop = to_float(bucket_block.get("pr_auc_drop_warn"))
            fail_drop = to_float(bucket_block.get("pr_auc_drop_fail"))
            warn_range = to_float(bucket_block.get("pr_auc_range_warn"))
            fail_range = to_float(bucket_block.get("pr_auc_range_fail"))
            if (
                warn_drop is not None
                and fail_drop is not None
                and warn_drop > fail_drop
            ) or (
                warn_range is not None
                and fail_range is not None
                and warn_range > fail_range
            ):
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "robustness warn thresholds must be <= fail thresholds.",
                    {"path": str(path), "bucket": bucket},
                )

            for key, min_value in baselines["robustness_thresholds_min"].items():
                raw = to_float(bucket_block.get(key))
                if raw is None or raw < float(min_value):
                    add_issue(
                        failures,
                        "performance_policy_downgrade",
                        "robustness minimum sample/positive guards cannot be reduced below publication baseline.",
                        {
                            "path": str(path),
                            "bucket": bucket,
                            "field": key,
                            "value": bucket_block.get(key),
                            "required_min": float(min_value),
                        },
                    )

    seed_thresholds = payload.get("seed_stability_thresholds")
    if not isinstance(seed_thresholds, dict):
        add_issue(
            failures,
            "performance_policy_missing_threshold_block",
            "performance_policy_spec.seed_stability_thresholds must be an object.",
            {"path": str(path)},
        )
    else:
        for key, max_value in baselines["seed_stability_thresholds_max"].items():
            raw = to_float(seed_thresholds.get(key))
            if raw is None or raw <= 0.0:
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "seed stability threshold must be finite numeric > 0.",
                    {"path": str(path), "field": key, "value": seed_thresholds.get(key)},
                )
                continue
            if raw > float(max_value):
                add_issue(
                    failures,
                    "performance_policy_downgrade",
                    "seed_stability_thresholds cannot be relaxed above publication-grade maxima.",
                    {"path": str(path), "field": key, "value": float(raw), "max_allowed": float(max_value)},
                )

    new_block_downgrade_detected = False

    prediction_replay_thresholds = payload.get("prediction_replay_thresholds")
    if not isinstance(prediction_replay_thresholds, dict):
        add_issue(
            failures,
            "performance_policy_missing_threshold_block",
            "performance_policy_spec.prediction_replay_thresholds must be an object.",
            {"path": str(path)},
        )
    else:
        metric_tol = to_float(prediction_replay_thresholds.get("metric_tolerance"))
        threshold_tol = to_float(prediction_replay_thresholds.get("threshold_tolerance"))
        replay_beta = to_float(prediction_replay_thresholds.get("beta"))
        if metric_tol is None or metric_tol <= 0.0:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "prediction_replay_thresholds.metric_tolerance must be finite > 0.",
                {"path": str(path), "value": prediction_replay_thresholds.get("metric_tolerance")},
            )
        elif metric_tol > float(baselines["prediction_replay_thresholds"]["metric_tolerance_max"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "prediction_replay_thresholds.metric_tolerance cannot be relaxed above publication-grade maximum.",
                {
                    "path": str(path),
                    "value": float(metric_tol),
                    "max_allowed": float(baselines["prediction_replay_thresholds"]["metric_tolerance_max"]),
                },
            )
        if threshold_tol is None or threshold_tol <= 0.0:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "prediction_replay_thresholds.threshold_tolerance must be finite > 0.",
                {"path": str(path), "value": prediction_replay_thresholds.get("threshold_tolerance")},
            )
        elif threshold_tol > float(baselines["prediction_replay_thresholds"]["threshold_tolerance_max"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "prediction_replay_thresholds.threshold_tolerance cannot be relaxed above publication-grade maximum.",
                {
                    "path": str(path),
                    "value": float(threshold_tol),
                    "max_allowed": float(baselines["prediction_replay_thresholds"]["threshold_tolerance_max"]),
                },
            )
        if replay_beta is None or replay_beta <= 0.0:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "prediction_replay_thresholds.beta must be finite > 0.",
                {"path": str(path), "value": prediction_replay_thresholds.get("beta")},
            )
        elif abs(replay_beta - float(baselines["prediction_replay_thresholds"]["beta"])) > 1e-12:
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "prediction_replay_thresholds.beta must stay fixed at 2.0 for publication-grade F2 replay.",
                {
                    "path": str(path),
                    "value": float(replay_beta),
                    "required": float(baselines["prediction_replay_thresholds"]["beta"]),
                },
            )

    external_thresholds = payload.get("external_validation_thresholds")
    if not isinstance(external_thresholds, dict):
        add_issue(
            failures,
            "performance_policy_missing_threshold_block",
            "performance_policy_spec.external_validation_thresholds must be an object.",
            {"path": str(path)},
        )
    else:
        numeric_min_fields = (
            ("min_cohort_count", "min_cohort_count_min"),
            ("min_rows_per_cohort", "min_rows_per_cohort_min"),
            ("min_positive_per_cohort", "min_positive_per_cohort_min"),
        )
        for field, baseline_key in numeric_min_fields:
            value = to_float(external_thresholds.get(field))
            if value is None or value < 1.0:
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "external_validation_thresholds minimum-count field must be finite >= 1.",
                    {"path": str(path), "field": field, "value": external_thresholds.get(field)},
                )
                continue
            if value < float(baselines["external_validation_thresholds"][baseline_key]):
                new_block_downgrade_detected = True
                add_issue(
                    failures,
                    "performance_policy_downgrade",
                    "external_validation_thresholds minimum-count guards cannot be relaxed below publication baseline.",
                    {
                        "path": str(path),
                        "field": field,
                        "value": float(value),
                        "required_min": float(baselines["external_validation_thresholds"][baseline_key]),
                    },
                )

        numeric_max_fields = (
            ("max_pr_auc_drop", "max_pr_auc_drop_max"),
            ("max_f2_beta_drop", "max_f2_beta_drop_max"),
            ("max_brier_increase", "max_brier_increase_max"),
            ("metric_tolerance", "metric_tolerance_max"),
        )
        for field, baseline_key in numeric_max_fields:
            value = to_float(external_thresholds.get(field))
            if value is None or value < 0.0:
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "external_validation_thresholds max/drop field must be finite >= 0.",
                    {"path": str(path), "field": field, "value": external_thresholds.get(field)},
                )
                continue
            if value > float(baselines["external_validation_thresholds"][baseline_key]):
                new_block_downgrade_detected = True
                add_issue(
                    failures,
                    "performance_policy_downgrade",
                    "external_validation_thresholds cannot be relaxed above publication-grade maxima.",
                    {
                        "path": str(path),
                        "field": field,
                        "value": float(value),
                        "max_allowed": float(baselines["external_validation_thresholds"][baseline_key]),
                    },
                )
        ext_beta = to_float(external_thresholds.get("beta"))
        if ext_beta is None or ext_beta <= 0.0:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "external_validation_thresholds.beta must be finite > 0.",
                {"path": str(path), "value": external_thresholds.get("beta")},
            )
        elif abs(ext_beta - float(baselines["external_validation_thresholds"]["beta"])) > 1e-12:
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "external_validation_thresholds.beta must stay fixed at 2.0 for publication-grade F2 transport checks.",
                {
                    "path": str(path),
                    "value": float(ext_beta),
                    "required": float(baselines["external_validation_thresholds"]["beta"]),
                },
            )

        require_cross_period = external_thresholds.get("require_cross_period")
        require_cross_institution = external_thresholds.get("require_cross_institution")
        if require_cross_period is not True:
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "external_validation_thresholds.require_cross_period must be true for publication-grade.",
                {"path": str(path), "value": require_cross_period},
            )
        if require_cross_institution is not True:
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "external_validation_thresholds.require_cross_institution must be true for publication-grade.",
                {"path": str(path), "value": require_cross_institution},
            )

    calibration_dca_thresholds = payload.get("calibration_dca_thresholds")
    if not isinstance(calibration_dca_thresholds, dict):
        add_issue(
            failures,
            "performance_policy_missing_threshold_block",
            "performance_policy_spec.calibration_dca_thresholds must be an object.",
            {"path": str(path)},
        )
    else:
        ece_max = to_float(calibration_dca_thresholds.get("ece_max"))
        slope_min = to_float(calibration_dca_thresholds.get("slope_min"))
        slope_max = to_float(calibration_dca_thresholds.get("slope_max"))
        intercept_abs_max = to_float(calibration_dca_thresholds.get("intercept_abs_max"))
        min_rows = to_float(calibration_dca_thresholds.get("min_rows"))
        min_positives = to_float(calibration_dca_thresholds.get("min_positives"))
        min_coverage = to_float(calibration_dca_thresholds.get("min_advantage_coverage"))
        min_avg_adv = to_float(calibration_dca_thresholds.get("min_average_advantage"))
        min_nb_adv = to_float(calibration_dca_thresholds.get("min_net_benefit_advantage"))

        checks = [
            ("ece_max", ece_max, 0.0, 1.0),
            ("intercept_abs_max", intercept_abs_max, 0.0, 10.0),
            ("min_rows", min_rows, 1.0, None),
            ("min_positives", min_positives, 1.0, None),
            ("min_advantage_coverage", min_coverage, 0.0, 1.0),
        ]
        for field, value, lo, hi in checks:
            if value is None or value < lo or (hi is not None and value > hi):
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "calibration_dca_thresholds field out of allowed numeric range.",
                    {"path": str(path), "field": field, "value": calibration_dca_thresholds.get(field), "min": lo, "max": hi},
                )

        if slope_min is None or slope_max is None or slope_min <= 0.0 or slope_max <= 0.0 or slope_min > slope_max:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "calibration_dca_thresholds must satisfy finite positive slope_min <= slope_max.",
                {
                    "path": str(path),
                    "slope_min": calibration_dca_thresholds.get("slope_min"),
                    "slope_max": calibration_dca_thresholds.get("slope_max"),
                },
            )

        if min_avg_adv is None or min_nb_adv is None:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "calibration_dca_thresholds.min_average_advantage and min_net_benefit_advantage must be finite.",
                {
                    "path": str(path),
                    "min_average_advantage": calibration_dca_thresholds.get("min_average_advantage"),
                    "min_net_benefit_advantage": calibration_dca_thresholds.get("min_net_benefit_advantage"),
                },
            )

        if ece_max is not None and ece_max > float(baselines["calibration_dca_thresholds"]["ece_max_max"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.ece_max cannot be relaxed above publication baseline.",
                {
                    "path": str(path),
                    "value": float(ece_max),
                    "max_allowed": float(baselines["calibration_dca_thresholds"]["ece_max_max"]),
                },
            )
        if slope_min is not None and slope_min < float(baselines["calibration_dca_thresholds"]["slope_min_min"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.slope_min cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": float(slope_min),
                    "required_min": float(baselines["calibration_dca_thresholds"]["slope_min_min"]),
                },
            )
        if slope_max is not None and slope_max > float(baselines["calibration_dca_thresholds"]["slope_max_max"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.slope_max cannot be relaxed above publication baseline.",
                {
                    "path": str(path),
                    "value": float(slope_max),
                    "max_allowed": float(baselines["calibration_dca_thresholds"]["slope_max_max"]),
                },
            )
        if intercept_abs_max is not None and intercept_abs_max > float(baselines["calibration_dca_thresholds"]["intercept_abs_max_max"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.intercept_abs_max cannot be relaxed above publication baseline.",
                {
                    "path": str(path),
                    "value": float(intercept_abs_max),
                    "max_allowed": float(baselines["calibration_dca_thresholds"]["intercept_abs_max_max"]),
                },
            )
        if min_rows is not None and min_rows < float(baselines["calibration_dca_thresholds"]["min_rows_min"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.min_rows cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": float(min_rows),
                    "required_min": float(baselines["calibration_dca_thresholds"]["min_rows_min"]),
                },
            )
        if min_positives is not None and min_positives < float(baselines["calibration_dca_thresholds"]["min_positives_min"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.min_positives cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": float(min_positives),
                    "required_min": float(baselines["calibration_dca_thresholds"]["min_positives_min"]),
                },
            )
        if min_coverage is not None and min_coverage < float(baselines["calibration_dca_thresholds"]["min_advantage_coverage_min"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.min_advantage_coverage cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": float(min_coverage),
                    "required_min": float(baselines["calibration_dca_thresholds"]["min_advantage_coverage_min"]),
                },
            )
        if min_avg_adv is not None and min_avg_adv < float(baselines["calibration_dca_thresholds"]["min_average_advantage_min"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.min_average_advantage cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": float(min_avg_adv),
                    "required_min": float(baselines["calibration_dca_thresholds"]["min_average_advantage_min"]),
                },
            )
        if min_nb_adv is not None and min_nb_adv < float(baselines["calibration_dca_thresholds"]["min_net_benefit_advantage_min"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "calibration_dca_thresholds.min_net_benefit_advantage cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": float(min_nb_adv),
                    "required_min": float(baselines["calibration_dca_thresholds"]["min_net_benefit_advantage_min"]),
                },
            )

        grid = calibration_dca_thresholds.get("threshold_grid")
        if not isinstance(grid, dict):
            add_issue(
                failures,
                "performance_policy_missing_threshold_block",
                "calibration_dca_thresholds.threshold_grid must be an object.",
                {"path": str(path)},
            )
        else:
            start_v = to_float(grid.get("start"))
            end_v = to_float(grid.get("end"))
            step_v = to_float(grid.get("step"))
            if (
                start_v is None
                or end_v is None
                or step_v is None
                or start_v <= 0.0
                or end_v >= 1.0
                or step_v <= 0.0
                or start_v >= end_v
                or step_v > (end_v - start_v)
            ):
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "calibration_dca_thresholds.threshold_grid must satisfy 0 < start < end < 1 and 0 < step <= (end-start).",
                    {
                        "path": str(path),
                        "start": grid.get("start"),
                        "end": grid.get("end"),
                        "step": grid.get("step"),
                    },
                )
            else:
                if start_v > float(baselines["calibration_dca_thresholds"]["threshold_grid_start_max"]):
                    new_block_downgrade_detected = True
                    add_issue(
                        failures,
                        "performance_policy_downgrade",
                        "calibration_dca_thresholds.threshold_grid.start cannot be relaxed above publication baseline.",
                        {
                            "path": str(path),
                            "value": float(start_v),
                            "max_allowed": float(baselines["calibration_dca_thresholds"]["threshold_grid_start_max"]),
                        },
                    )
                if end_v < float(baselines["calibration_dca_thresholds"]["threshold_grid_end_min"]):
                    new_block_downgrade_detected = True
                    add_issue(
                        failures,
                        "performance_policy_downgrade",
                        "calibration_dca_thresholds.threshold_grid.end cannot be relaxed below publication baseline.",
                        {
                            "path": str(path),
                            "value": float(end_v),
                            "required_min": float(baselines["calibration_dca_thresholds"]["threshold_grid_end_min"]),
                        },
                    )
                if step_v > float(baselines["calibration_dca_thresholds"]["threshold_grid_step_max"]):
                    new_block_downgrade_detected = True
                    add_issue(
                        failures,
                        "performance_policy_downgrade",
                        "calibration_dca_thresholds.threshold_grid.step cannot be relaxed above publication baseline.",
                        {
                            "path": str(path),
                            "value": float(step_v),
                            "max_allowed": float(baselines["calibration_dca_thresholds"]["threshold_grid_step_max"]),
                        },
                    )

    distribution_thresholds_v2 = payload.get("distribution_thresholds_v2")
    if not isinstance(distribution_thresholds_v2, dict):
        add_issue(
            failures,
            "performance_policy_missing_threshold_block",
            "performance_policy_spec.distribution_thresholds_v2 must be an object.",
            {"path": str(path)},
        )
    else:
        for field, baseline_key in (
            ("split_classifier_auc_fail", "split_classifier_auc_fail_max"),
            ("split_classifier_auc_warn", "split_classifier_auc_warn_max"),
            ("top_feature_jsd_fail", "top_feature_jsd_fail_max"),
            ("top_feature_jsd_warn", "top_feature_jsd_warn_max"),
            ("high_shift_feature_fraction_fail", "high_shift_feature_fraction_fail_max"),
            ("high_shift_feature_fraction_warn", "high_shift_feature_fraction_warn_max"),
            ("missing_ratio_delta_fail", "missing_ratio_delta_fail_max"),
            ("missing_ratio_delta_warn", "missing_ratio_delta_warn_max"),
            ("prevalence_delta_fail", "prevalence_delta_fail_max"),
            ("prevalence_delta_warn", "prevalence_delta_warn_max"),
        ):
            value = to_float(distribution_thresholds_v2.get(field))
            if value is None or value < 0.0:
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "distribution_thresholds_v2 field must be finite numeric >= 0.",
                    {"path": str(path), "field": field, "value": distribution_thresholds_v2.get(field)},
                )
                continue
            if value > float(baselines["distribution_thresholds_v2"][baseline_key]):
                new_block_downgrade_detected = True
                add_issue(
                    failures,
                    "performance_policy_downgrade",
                    "distribution_thresholds_v2 cannot be relaxed above publication-grade maxima.",
                    {
                        "path": str(path),
                        "field": field,
                        "value": float(value),
                        "max_allowed": float(baselines["distribution_thresholds_v2"][baseline_key]),
                    },
                )

        warn_fail_pairs = (
            ("split_classifier_auc_warn", "split_classifier_auc_fail"),
            ("top_feature_jsd_warn", "top_feature_jsd_fail"),
            ("high_shift_feature_fraction_warn", "high_shift_feature_fraction_fail"),
            ("missing_ratio_delta_warn", "missing_ratio_delta_fail"),
            ("prevalence_delta_warn", "prevalence_delta_fail"),
        )
        for warn_key, fail_key in warn_fail_pairs:
            warn_value = to_float(distribution_thresholds_v2.get(warn_key))
            fail_value = to_float(distribution_thresholds_v2.get(fail_key))
            if warn_value is None or fail_value is None:
                continue
            if warn_value > fail_value:
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "distribution_thresholds_v2 requires warn <= fail for each pair.",
                    {"path": str(path), "warn_field": warn_key, "fail_field": fail_key},
                )

    feature_engineering_policy = payload.get("feature_engineering_policy")
    if not isinstance(feature_engineering_policy, dict):
        add_issue(
            failures,
            "performance_policy_missing_threshold_block",
            "performance_policy_spec.feature_engineering_policy must be an object.",
            {"path": str(path)},
        )
    else:
        for flag in (
            "require_explicit_feature_groups",
            "require_stability_evidence",
            "disallow_valid_test_external_for_selection",
            "require_reproducibility_fields",
        ):
            value = feature_engineering_policy.get(flag)
            if value is not True:
                new_block_downgrade_detected = True
                add_issue(
                    failures,
                    "performance_policy_downgrade",
                    "feature_engineering_policy strict boolean guard must stay enabled for publication-grade.",
                    {"path": str(path), "field": flag, "value": value},
                )

        scopes = feature_engineering_policy.get("allowed_selection_scopes")
        if not isinstance(scopes, list) or not scopes:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "feature_engineering_policy.allowed_selection_scopes must be non-empty list.",
                {"path": str(path), "value": scopes},
            )
        else:
            scope_tokens = {str(x).strip().lower() for x in scopes if isinstance(x, str) and str(x).strip()}
            baseline_scopes = set(baselines["feature_engineering_policy"]["allowed_selection_scopes"])
            invalid_scopes = sorted(token for token in scope_tokens if token not in baseline_scopes)
            if invalid_scopes:
                new_block_downgrade_detected = True
                add_issue(
                    failures,
                    "performance_policy_downgrade",
                    "feature_engineering_policy.allowed_selection_scopes contains unsupported scopes.",
                    {"path": str(path), "invalid_scopes": invalid_scopes, "allowed": sorted(baseline_scopes)},
                )
            if not scope_tokens:
                add_issue(
                    failures,
                    "invalid_performance_policy_field",
                    "feature_engineering_policy.allowed_selection_scopes must contain at least one token.",
                    {"path": str(path)},
                )

        min_feature_freq = to_float(feature_engineering_policy.get("min_feature_selection_frequency"))
        min_group_freq = to_float(feature_engineering_policy.get("min_group_selection_frequency"))
        if min_feature_freq is None or not (0.0 <= min_feature_freq <= 1.0):
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "feature_engineering_policy.min_feature_selection_frequency must be within [0,1].",
                {"path": str(path), "value": feature_engineering_policy.get("min_feature_selection_frequency")},
            )
        elif min_feature_freq < float(baselines["feature_engineering_policy"]["min_feature_selection_frequency"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "feature_engineering_policy.min_feature_selection_frequency cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": float(min_feature_freq),
                    "required_min": float(baselines["feature_engineering_policy"]["min_feature_selection_frequency"]),
                },
            )
        if min_group_freq is None or not (0.0 <= min_group_freq <= 1.0):
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "feature_engineering_policy.min_group_selection_frequency must be within [0,1].",
                {"path": str(path), "value": feature_engineering_policy.get("min_group_selection_frequency")},
            )
        elif min_group_freq < float(baselines["feature_engineering_policy"]["min_group_selection_frequency"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "feature_engineering_policy.min_group_selection_frequency cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": float(min_group_freq),
                    "required_min": float(baselines["feature_engineering_policy"]["min_group_selection_frequency"]),
                },
            )

    ci_policy = payload.get("ci_policy")
    if not isinstance(ci_policy, dict):
        add_issue(
            failures,
            "performance_policy_missing_threshold_block",
            "performance_policy_spec.ci_policy must be an object.",
            {"path": str(path)},
        )
    else:
        n_resamples = to_int(ci_policy.get("n_resamples"))
        max_resamples_supported = to_int(ci_policy.get("max_resamples_supported"))
        max_width = to_float(ci_policy.get("max_width"))
        metric_tolerance = to_float(ci_policy.get("metric_tolerance"))
        transport_required = ci_policy.get("transport_ci_required")

        if n_resamples is None or n_resamples < 100:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "ci_policy.n_resamples must be integer >= 100.",
                {"path": str(path), "value": ci_policy.get("n_resamples")},
            )
        elif n_resamples < int(baselines["ci_policy"]["n_resamples_min"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "ci_policy.n_resamples cannot be relaxed below publication baseline.",
                {
                    "path": str(path),
                    "value": int(n_resamples),
                    "required_min": int(baselines["ci_policy"]["n_resamples_min"]),
                },
            )

        if max_resamples_supported is not None and max_resamples_supported < 100:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "ci_policy.max_resamples_supported must be integer >= 100 when provided.",
                {"path": str(path), "value": ci_policy.get("max_resamples_supported")},
            )
        elif max_resamples_supported is not None and max_resamples_supported > int(
            baselines["ci_policy"]["max_resamples_supported_max"]
        ):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "ci_policy.max_resamples_supported cannot be relaxed above publication baseline.",
                {
                    "path": str(path),
                    "value": int(max_resamples_supported),
                    "max_allowed": int(baselines["ci_policy"]["max_resamples_supported_max"]),
                },
            )

        if n_resamples is not None and max_resamples_supported is not None and n_resamples > max_resamples_supported:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "ci_policy.n_resamples cannot exceed ci_policy.max_resamples_supported.",
                {
                    "path": str(path),
                    "n_resamples": int(n_resamples),
                    "max_resamples_supported": int(max_resamples_supported),
                },
            )

        if max_width is None or max_width <= 0.0:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "ci_policy.max_width must be finite > 0.",
                {"path": str(path), "value": ci_policy.get("max_width")},
            )
        elif max_width > float(baselines["ci_policy"]["max_width_max"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "ci_policy.max_width cannot be relaxed above publication baseline.",
                {
                    "path": str(path),
                    "value": float(max_width),
                    "max_allowed": float(baselines["ci_policy"]["max_width_max"]),
                },
            )

        if metric_tolerance is None or metric_tolerance <= 0.0:
            add_issue(
                failures,
                "invalid_performance_policy_field",
                "ci_policy.metric_tolerance must be finite > 0.",
                {"path": str(path), "value": ci_policy.get("metric_tolerance")},
            )
        elif metric_tolerance > float(baselines["ci_policy"]["metric_tolerance_max"]):
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "ci_policy.metric_tolerance cannot be relaxed above publication baseline.",
                {
                    "path": str(path),
                    "value": float(metric_tolerance),
                    "max_allowed": float(baselines["ci_policy"]["metric_tolerance_max"]),
                },
            )

        if transport_required is not True:
            new_block_downgrade_detected = True
            add_issue(
                failures,
                "performance_policy_downgrade",
                "ci_policy.transport_ci_required must stay enabled for publication-grade.",
                {"path": str(path), "value": transport_required},
            )

    if new_block_downgrade_detected:
        add_issue(
            failures,
            "performance_policy_downgrade_new_blocks",
            "New V3/V4 publication-grade threshold blocks were relaxed beyond allowed baseline.",
            {"path": str(path)},
        )


def validate_optional_path(
    request: Dict[str, Any],
    key: str,
    base: Path,
    failures: List[Dict[str, Any]],
    required: bool,
    normalized: Dict[str, Any],
    warnings: Optional[List[Dict[str, Any]]] = None,
    sandbox: Optional[Path] = None,
) -> None:
    value = request.get(key)
    if value is None:
        if required:
            add_issue(
                failures,
                "missing_required_path",
                "Required path field is missing.",
                {"field": key},
            )
        return

    if not isinstance(value, str) or not value.strip():
        add_issue(
            failures,
            "invalid_path_field",
            "Path field must be a non-empty string.",
            {"field": key},
        )
        return

    # Sandbox defaults to the parent of `base` (i.e., the project root when
    # base is the request.json's directory). This permits the canonical
    # configs/../data, configs/../evidence, configs/../models layout while
    # blocking `../../../home/other-user/secrets.csv` traversals.
    effective_sandbox = sandbox if sandbox is not None else base.parent
    try:
        resolved = resolve_path(base, value.strip(), sandbox=effective_sandbox)
    except ValueError as exc:
        add_issue(
            failures,
            "path_escapes_sandbox",
            f"Path field '{key}' escapes the project sandbox: {exc}",
            {"field": key, "sandbox": str(effective_sandbox)},
        )
        return
    normalized[key] = str(resolved)
    if not resolved.exists():
        # Required paths → failure; optional declared paths → warning only
        target = failures if required else (warnings if warnings is not None else failures)
        add_issue(
            target,
            "path_not_found",
            f"{'Required' if required else 'Optional'} path field points to a missing file.",
            {"field": key, "path": str(resolved), "required": required},
        )
    elif not resolved.is_file():
        add_issue(
            failures,
            "path_not_file",
            "Path field must point to a file.",
            {"field": key, "path": str(resolved)},
        )


def validate_publication_v3_path(
    request: Dict[str, Any],
    key: str,
    base: Path,
    failures: List[Dict[str, Any]],
    normalized: Dict[str, Any],
    migration_hint: str,
    warnings: Optional[List[Dict[str, Any]]] = None,
) -> None:
    if request.get(key) is None:
        add_issue(
            failures,
            "missing_publication_grade_v3_field",
            "Publication-grade request is missing required V3 evidence field.",
            {"field": key, "migration_hint": migration_hint},
        )
        return
    validate_optional_path(
        request=request,
        key=key,
        base=base,
        failures=failures,
        required=False,
        normalized=normalized,
        warnings=warnings,
    )


def validate_publication_v4_path(
    request: Dict[str, Any],
    key: str,
    base: Path,
    failures: List[Dict[str, Any]],
    normalized: Dict[str, Any],
    migration_hint: str,
    warnings: Optional[List[Dict[str, Any]]] = None,
) -> None:
    if request.get(key) is None:
        add_issue(
            failures,
            "missing_publication_grade_v4_field",
            "Publication-grade request is missing required V4 evidence field.",
            {"field": key, "migration_hint": migration_hint},
        )
        return
    validate_optional_path(
        request=request,
        key=key,
        base=base,
        failures=failures,
        required=False,
        normalized=normalized,
        warnings=warnings,
    )



# ── main (466 lines) ──────────────────────────

def main() -> int:
    args = parse_args()

    failures: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    normalized: Dict[str, Any] = {}

    request_path = Path(args.request).expanduser().resolve()
    if not request_path.exists():
        add_issue(
            failures,
            "missing_request_file",
            "Request JSON file not found.",
            {"path": str(request_path)},
        )
        return finish(args, failures, warnings, normalized)

    try:
        _check_json_file_size(request_path)
        with request_path.open("r", encoding="utf-8") as fh:
            request = json.load(fh)
    except Exception as exc:
        add_issue(
            failures,
            "invalid_request_json",
            "Unable to parse request JSON.",
            {"path": str(request_path), "error": str(exc)},
        )
        return finish(args, failures, warnings, normalized)

    if not isinstance(request, dict):
        add_issue(
            failures,
            "invalid_request_json",
            "Request JSON root must be an object.",
            {"path": str(request_path)},
        )
        return finish(args, failures, warnings, normalized)

    request_base = request_path.parent
    # Sandbox for all user-declared paths. Anchor to a project-root
    # marker (SKILL.md / .git / pyproject.toml / .mlgg_model_key)
    # ascending from request_base. Codex 2026-04-23 flagged the old
    # `path_sandbox = request_base.parent` as caller-controlled: a
    # request placed at /tmp/request.json would yield sandbox=/,
    # silently widening every downstream resolve_path() check. The
    # marker-based anchor keeps the sandbox = project root regardless
    # of where the request file is dropped.
    detected_root = _detect_project_root(request_base)
    if detected_root is not None:
        path_sandbox = detected_root
        path_sandbox_source = "project_marker"
    else:
        # Degraded mode: no project marker found. Fall back to the
        # legacy parent-of-parent, but emit a warning so operators see
        # the sandbox is not tightly anchored. Without this warning,
        # running a gate from /tmp/ for a quick test could be confused
        # with a real publication-grade run that lost its anchor.
        path_sandbox = request_base.parent
        path_sandbox_source = "fallback_parent_of_parent"
        add_issue(
            warnings,
            "path_sandbox_unanchored",
            "No project-root marker (SKILL.md / .git / pyproject.toml / "
            ".mlgg_model_key) found ascending from the request file. "
            "path_sandbox fell back to request_base.parent; downstream "
            "path validation is weaker than normal. Place the request "
            "under a project with one of these markers for tight "
            "sandboxing.",
            {"request_base": str(request_base),
             "fallback_sandbox": str(path_sandbox)},
        )
    normalized["path_resolution_base"] = str(request_base)
    normalized["path_resolution_sandbox"] = str(path_sandbox)
    normalized["path_resolution_sandbox_source"] = path_sandbox_source

    for key in REQUIRED_STRING_FIELDS:
        value = must_be_non_empty_str(request, key, failures)
        if value is not None:
            normalized[key] = value

    claim_tier = normalized.get("claim_tier_target")
    if claim_tier and claim_tier not in ALLOWED_CLAIM_TIERS:
        add_issue(
            failures,
            "invalid_claim_tier_target",
            "claim_tier_target must be one of the allowed values.",
            {"allowed": sorted(ALLOWED_CLAIM_TIERS), "actual": claim_tier},
        )

    # Cross-run anti-downgrade (Codex 2026-04-23 Contract #4).
    # Only run when we have a valid claim_tier AND both study_id/run_id
    # — otherwise there's nothing to check yet (earlier failures will
    # already have fired). Also gated on not args.allow_downgrade so CI
    # or a deliberate rollback can override by explicit consent.
    _study_id = normalized.get("study_id")
    _run_id = normalized.get("run_id")
    if (
        claim_tier in ALLOWED_CLAIM_TIERS
        and _study_id
        and _run_id
        and not getattr(args, "allow_tier_downgrade", False)
    ):
        downgrade_summary = _check_and_update_downgrade(
            sandbox=path_sandbox,
            study_id=_study_id,
            run_id=_run_id,
            current_tier=claim_tier,
            failures=failures,
        )
        normalized["claim_tier_history"] = downgrade_summary

    split_paths = request.get("split_paths")
    if not isinstance(split_paths, dict):
        add_issue(
            failures,
            "invalid_split_paths",
            "split_paths must be an object.",
            {},
        )
    else:
        normalized_splits: Dict[str, str] = {}
        for key in ("train", "test"):
            val = split_paths.get(key)
            if not isinstance(val, str) or not val.strip():
                add_issue(
                    failures,
                    "missing_split_path",
                    "Required split path missing.",
                    {"split": key},
                )
                continue
            try:
                resolved = resolve_path(request_base, val.strip(), sandbox=path_sandbox)
            except ValueError as exc:
                add_issue(
                    failures,
                    "path_escapes_sandbox",
                    f"Split path '{key}' escapes the project sandbox: {exc}",
                    {"split": key, "sandbox": str(path_sandbox)},
                )
                continue
            normalized_splits[key] = str(resolved)
            if not resolved.exists():
                add_issue(
                    failures,
                    "split_path_not_found",
                    "Split file path does not exist.",
                    {"split": key, "path": str(resolved)},
                )
            elif not resolved.is_file():
                add_issue(
                    failures,
                    "split_path_not_file",
                    "Split path must point to a file.",
                    {"split": key, "path": str(resolved)},
                )

        valid_val = split_paths.get("valid")
        if valid_val is not None:
            if not isinstance(valid_val, str) or not valid_val.strip():
                add_issue(
                    failures,
                    "invalid_split_path",
                    "valid split path must be a non-empty string when provided.",
                    {},
                )
            else:
                try:
                    resolved = resolve_path(request_base, valid_val.strip(), sandbox=path_sandbox)
                except ValueError as exc:
                    add_issue(
                        failures,
                        "path_escapes_sandbox",
                        f"Valid split path escapes the project sandbox: {exc}",
                        {"sandbox": str(path_sandbox)},
                    )
                    resolved = None
                if resolved is not None:
                    normalized_splits["valid"] = str(resolved)
                    if not resolved.exists():
                        add_issue(
                            failures,
                            "split_path_not_found",
                            "Split file path does not exist.",
                            {"split": "valid", "path": str(resolved)},
                        )
                    elif not resolved.is_file():
                        add_issue(
                            failures,
                            "split_path_not_file",
                            "Split path must point to a file.",
                            {"split": "valid", "path": str(resolved)},
                        )
        elif args.strict:
            add_issue(
                warnings,
                "missing_valid_split",
                "valid split is absent; strict workflows usually require train/valid/test.",
                {},
            )

        seen_paths: Dict[str, str] = {}
        for split_name, split_path in normalized_splits.items():
            prev_split = seen_paths.get(split_path)
            if prev_split is not None:
                add_issue(
                    failures,
                    "duplicate_split_path",
                    "Different splits must not point to the same file path.",
                    {"split_a": prev_split, "split_b": split_name, "path": split_path},
                )
            else:
                seen_paths[split_path] = split_name
        normalized["split_paths"] = normalized_splits

    phenotype_path = normalized.get("phenotype_definition_spec")
    if phenotype_path:
        try:
            resolved = resolve_path(request_base, phenotype_path, sandbox=path_sandbox)
        except ValueError as exc:
            add_issue(
                failures,
                "path_escapes_sandbox",
                f"phenotype_definition_spec escapes the project sandbox: {exc}",
                {"sandbox": str(path_sandbox)},
            )
            resolved = None
        if resolved is not None:
            normalized["phenotype_definition_spec"] = str(resolved)
            if not resolved.exists():
                add_issue(
                    failures,
                    "phenotype_definition_spec_not_found",
                    "phenotype_definition_spec path does not exist.",
                    {"path": str(resolved)},
                )

    # outcome_definition_spec — optional path to a rigorous outcome-definition
    # JSON. Onboarding auto-writes a minimal exploratory_auto_generated stub
    # when the user provides a single CSV without their own definition. Always
    # normalize when present so cohort_definition_gate can consume via
    # --outcome-definition (2026-04-17 dogfood fix).
    # Source from raw request since this field isn't in REQUIRED_STRING_FIELDS.
    _raw_outcome_def = request.get("outcome_definition_spec")
    if isinstance(_raw_outcome_def, str) and _raw_outcome_def.strip():
        normalized["outcome_definition_spec"] = _raw_outcome_def.strip()
    # Also propagate `cross_sectional` boolean flag so run_dag_pipeline can
    # forward --cross-sectional to gates that support it.
    #
    # Strict coercion (Codex review 2026-04-23 critical): the previous
    # `bool(request.get("cross_sectional"))` made every non-empty string
    # truthy — so `"false"` / `"no"` / `"0"` all silently set
    # cross_sectional=True, which suppresses external-validation and
    # robustness requirements downstream. Accept only proper booleans
    # or the literal ASCII-case strings "true"/"false"; anything else
    # (int, list, dict, other strings) becomes a request-validation
    # failure.
    _cs_raw = request.get("cross_sectional")
    if _cs_raw is not None:
        if isinstance(_cs_raw, bool):
            normalized["cross_sectional"] = _cs_raw
        elif isinstance(_cs_raw, str):
            _cs_norm = _cs_raw.strip().lower()
            if _cs_norm in ("true", "yes", "1"):
                normalized["cross_sectional"] = True
            elif _cs_norm in ("false", "no", "0"):
                normalized["cross_sectional"] = False
            else:
                add_issue(
                    failures,
                    "invalid_cross_sectional",
                    "cross_sectional must be a boolean (or 'true'/'false' string); "
                    "non-recognized strings are refused because Python-truthy "
                    "coercion would silently enable publication-grade bypass.",
                    {"actual": _cs_raw},
                )
        else:
            add_issue(
                failures,
                "invalid_cross_sectional",
                "cross_sectional must be a boolean.",
                {"actual_type": type(_cs_raw).__name__},
            )
    _outcome_def_path = normalized.get("outcome_definition_spec")
    if _outcome_def_path:
        try:
            _resolved_od = resolve_path(request_base, _outcome_def_path, sandbox=path_sandbox)
        except ValueError as exc:
            add_issue(
                failures,
                "path_escapes_sandbox",
                f"outcome_definition_spec escapes the project sandbox: {exc}",
                {"sandbox": str(path_sandbox)},
            )
            _resolved_od = None
        if _resolved_od is not None:
            normalized["outcome_definition_spec"] = str(_resolved_od)
            if not _resolved_od.exists():
                # Soft warning for leakage-audited; hard fail only for publication-grade.
                _target_list = failures if normalized.get("claim_tier_target") == "publication-grade" else warnings
                add_issue(
                    _target_list,
                    "outcome_definition_spec_not_found",
                    "outcome_definition_spec path does not exist.",
                    {"path": str(_resolved_od)},
                )

    # Publication-grade requests must include lineage, split/imbalance/tuning protocol specs, and evaluated metric.
    require_lineage = normalized.get("claim_tier_target") == "publication-grade"
    # Resolve profile early so V3/V4 checks can use it.
    # validate_thresholds is called later to set _resolved_policy, but we
    # need the profile name now.  Read directly from thresholds dict.
    _thresholds_raw = request.get("thresholds", {})
    _profile_name = (_thresholds_raw.get("profile", "standard")
                     if isinstance(_thresholds_raw, dict) else "standard")
    # Profiles that relax V3/V4 evidence requirements (external validation,
    # seed sensitivity, feature engineering) to warnings instead of failures.
    # Rationale: small/rare datasets typically lack external cohorts and have
    # high seed variance by nature; forcing these as hard failures blocks the
    # pipeline on data the researcher cannot produce.
    _claim_tier = str(normalized.get("claim_tier_target", "")).strip()
    _relaxed_profile = _profile_name in (
        "small_cohort", "rare_disease", "exploratory",
    ) or _claim_tier == "leakage-audited"

    if require_lineage:
        primary_metric = str(normalized.get("primary_metric", "")).strip()
        if canonical_metric_token(primary_metric) != canonical_metric_token("pr_auc"):
            add_issue(
                failures,
                "unsupported_primary_metric",
                "Publication-grade strict workflow requires primary_metric=pr_auc.",
                {"primary_metric": primary_metric, "expected": "pr_auc"},
            )

    validate_optional_path(
        request=request,
        key="feature_lineage_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="split_protocol_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="imbalance_policy_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="tuning_protocol_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="missingness_policy_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="reporting_bias_checklist_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="execution_attestation_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="performance_policy_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="feature_group_spec",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="model_selection_report_file",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="model_pool_file",
        base=request_base,
        failures=failures,
        required=False,
        normalized=normalized,
        warnings=warnings,
    )

    # Seed sensitivity: required for publication-grade standard profile,
    # downgraded to warning for small_cohort/rare_disease/exploratory
    # (high seed variance is expected with small n).
    validate_optional_path(
        request=request,
        key="seed_sensitivity_report_file",
        base=request_base,
        failures=failures,
        required=require_lineage and not _relaxed_profile,
        normalized=normalized,
        warnings=warnings,
    )

    # Robustness report requires event_time for time-slicing.
    # Cross-sectional data has no time axis → robustness is optional.
    _robustness_required = require_lineage and not bool(request.get("cross_sectional"))
    validate_optional_path(
        request=request,
        key="robustness_report_file",
        base=request_base,
        failures=failures,
        required=_robustness_required,
        normalized=normalized,
        warnings=warnings,
    )

    validate_optional_path(
        request=request,
        key="evaluation_report_file",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    # prediction_trace_file: always normalize when provided, regardless of
    # claim_tier. Downstream calibration_dca_gate / prediction_replay_gate
    # / ci_matrix_gate declare this as a required CLI input in the gate
    # registry (scripts/core/_gate_registry.py), so even `leakage-audited`
    # runs need it normalized or those gates crash at argparse with
    # "the following arguments are required: --prediction-trace".
    # Surfaced by dogfood run on NHANES 15549-row dataset (2026-04-17).
    validate_optional_path(
        request=request,
        key="prediction_trace_file",
        base=request_base,
        failures=failures,
        required=require_lineage,
        normalized=normalized,
        warnings=warnings,
    )

    # ci_matrix_report_file + feature_engineering_report_file:
    # unconditionally normalized because their consumer gates declare
    # --ci-matrix-report / --feature-engineering-report as REQUIRED in
    # argparse (they are artifact paths, not optional references). Without
    # this, leakage-audited tier runs crash at argparse. Content-shape
    # validation for these artifacts remains tier-gated below.
    for _required_artifact_field in (
        "ci_matrix_report_file",
        "feature_engineering_report_file",
    ):
        validate_optional_path(
            request=request,
            key=_required_artifact_field,
            base=request_base,
            failures=failures,
            required=False,
            normalized=normalized,
            warnings=warnings,
        )

    # NOTE: external_validation_report_file / distribution_report_file /
    # feature_engineering_report_file stay tier-gated. Downstream gates
    # (calibration_dca / ci_matrix / distribution_generalization) declare
    # those flags as OPTIONAL in argparse. If onboarding produces a skeletal
    # external_validation_report with cohorts=[] and we forward it, the
    # gate's "external_cohorts_empty" error fires — worse than leaving the
    # flag off entirely (which triggers a soft-skip warning).

    if require_lineage:
        # External validation paths: required for publication-grade standard
        # profile. Skipped entirely for relaxed profiles (small_cohort etc.)
        # and cross-sectional data — external cohorts typically unavailable.
        if not bool(request.get("cross_sectional")) and not _relaxed_profile:
            validate_publication_v3_path(
                request=request,
                key="external_cohort_spec",
                base=request_base,
                failures=failures,
                normalized=normalized,
                migration_hint="Add external_cohort_spec JSON with both cross_period and cross_institution cohorts.",
                warnings=warnings,
            )
            # For publication-grade this field must not only normalize but
            # also satisfy V3 validation (exists, is file) as a hard fail.
            # validate_publication_v3_path adds those extra checks; it also
            # calls validate_optional_path internally so re-adding it is a
            # no-op except for the stricter failure logic.
            validate_publication_v3_path(
                request=request,
                key="external_validation_report_file",
                base=request_base,
                failures=failures,
                normalized=normalized,
                migration_hint="Add external_validation_report_file generated from external cohort replay evaluation.",
                warnings=warnings,
            )
        validate_publication_v4_path(
            request=request,
            key="distribution_report_file",
            base=request_base,
            failures=failures,
            normalized=normalized,
            migration_hint="Add distribution_report_file generated from distribution_generalization analysis.",
            warnings=warnings,
        )
        # Feature engineering report: skipped for relaxed profiles.
        if not _relaxed_profile:
            validate_publication_v4_path(
                request=request,
                key="feature_engineering_report_file",
                base=request_base,
                failures=failures,
                normalized=normalized,
                migration_hint="Add feature_engineering_report_file with grouped selection stability and reproducibility evidence.",
                warnings=warnings,
            )
        validate_publication_v4_path(
            request=request,
            key="ci_matrix_report_file",
            base=request_base,
            failures=failures,
            normalized=normalized,
            migration_hint="Add ci_matrix_report_file with full split/external metric 95% CI matrix and transport-drop CI.",
            warnings=warnings,
        )

    evaluation_report_file = normalized.get("evaluation_report_file")
    _is_cross_sectional = bool(request.get("cross_sectional"))
    if isinstance(evaluation_report_file, str) and evaluation_report_file:
        validate_evaluation_report_shape(evaluation_report_file, failures, cross_sectional=_is_cross_sectional, relaxed_profile=_relaxed_profile)
    external_validation_report_file = normalized.get("external_validation_report_file")
    if isinstance(external_validation_report_file, str) and external_validation_report_file:
        validate_external_validation_report_shape(external_validation_report_file, failures)
    external_cohort_spec = normalized.get("external_cohort_spec")
    if isinstance(external_cohort_spec, str) and external_cohort_spec and not _relaxed_profile:
        validate_external_cohort_spec_shape(external_cohort_spec, failures)
    model_selection_report_file = normalized.get("model_selection_report_file")
    if isinstance(model_selection_report_file, str) and model_selection_report_file:
        validate_model_selection_report_shape(model_selection_report_file, failures)
    seed_sensitivity_report_file = normalized.get("seed_sensitivity_report_file")
    if isinstance(seed_sensitivity_report_file, str) and seed_sensitivity_report_file:
        validate_seed_sensitivity_report_shape(seed_sensitivity_report_file, failures)
    robustness_report_file = normalized.get("robustness_report_file")
    if isinstance(robustness_report_file, str) and robustness_report_file:
        validate_robustness_report_shape(robustness_report_file, failures)
    # Ensure profile-resolved baselines are available before performance policy validation.
    # validate_thresholds sets request["_resolved_policy"] which is needed by
    # validate_performance_policy_spec for profile-aware downgrade checks.
    if "_resolved_policy" not in request:
        validate_thresholds(request, failures, warnings, args.strict)

    performance_policy_spec = normalized.get("performance_policy_spec")
    if isinstance(performance_policy_spec, str) and performance_policy_spec:
        validate_performance_policy_spec(
            performance_policy_spec,
            failures=failures,
            expected_primary_metric=str(normalized.get("primary_metric", "")).strip(),
            resolved_baselines=request.get("_resolved_policy"),
        )
    feature_group_spec = normalized.get("feature_group_spec")
    if isinstance(feature_group_spec, str) and feature_group_spec:
        validate_feature_group_spec_shape(feature_group_spec, failures)
    distribution_report_file = normalized.get("distribution_report_file")
    if isinstance(distribution_report_file, str) and distribution_report_file:
        validate_distribution_report_shape(distribution_report_file, failures)
    # feature_engineering_report_file shape is tier-gated (leakage-audited
    # runs use a skeletal report; the path is normalized above only so the
    # consumer gate's required --feature-engineering-report argparse flag
    # is satisfied).
    feature_engineering_report_file = normalized.get("feature_engineering_report_file")
    if isinstance(feature_engineering_report_file, str) and feature_engineering_report_file and require_lineage:
        validate_feature_engineering_report_shape(feature_engineering_report_file, failures)
    # ci_matrix_report_file shape is still tier-gated (leakage-audited doesn't
    # require the full transport-drop CI matrix; the artifact path is
    # normalized above only so ci_matrix_gate's required --ci-matrix-report
    # argparse flag is satisfied).
    ci_matrix_report_file = normalized.get("ci_matrix_report_file")
    if isinstance(ci_matrix_report_file, str) and ci_matrix_report_file and require_lineage:
        validate_ci_matrix_report_shape(ci_matrix_report_file, failures)
    execution_attestation_spec = normalized.get("execution_attestation_spec")
    if isinstance(execution_attestation_spec, str) and execution_attestation_spec:
        validate_execution_attestation_shape(execution_attestation_spec, failures)
    validate_cross_artifact_alignment(normalized, failures, warnings_list=warnings)

    metric_path = request.get("evaluation_metric_path")
    if metric_path is None:
        if require_lineage:
            add_issue(
                failures,
                "missing_required_field",
                "Publication-grade request requires evaluation_metric_path to pin canonical metric source.",
                {"field": "evaluation_metric_path"},
            )
    elif isinstance(metric_path, str) and metric_path.strip():
        metric_path_clean = metric_path.strip()
        if not is_valid_dot_path(metric_path_clean):
            add_issue(
                failures,
                "invalid_field",
                "evaluation_metric_path must be a dot path using alphanumeric/underscore segments.",
                {"field": "evaluation_metric_path", "value": metric_path_clean},
            )
        else:
            metric_leaf = metric_path_clean.split(".")[-1]
            primary_metric = str(normalized.get("primary_metric", "")).strip()
            if primary_metric and canonical_metric_token(metric_leaf) != canonical_metric_token(primary_metric):
                add_issue(
                    failures,
                    "metric_path_metric_mismatch",
                    "evaluation_metric_path leaf must match primary_metric.",
                    {
                        "primary_metric": primary_metric,
                        "evaluation_metric_path": metric_path_clean,
                        "metric_leaf": metric_leaf,
                    },
                )
            normalized["evaluation_metric_path"] = metric_path_clean
    else:
        add_issue(
            failures,
            "invalid_field",
            "evaluation_metric_path must be a non-empty string when provided.",
            {"field": "evaluation_metric_path"},
        )

    if request.get("actual_primary_metric") is not None:
        actual_metric = request.get("actual_primary_metric")
        if is_finite_number(actual_metric):
            normalized["actual_primary_metric"] = float(actual_metric)
        else:
            add_issue(
                failures,
                "invalid_numeric_field",
                "actual_primary_metric must be a finite number when provided.",
                {"actual_type": type(actual_metric).__name__},
            )
    elif require_lineage:
        require_numeric(request, "actual_primary_metric", failures)

    null_required = normalized.get("claim_tier_target") == "publication-grade"
    validate_optional_path(
        request=request,
        key="permutation_null_metrics_file",
        base=request_base,
        failures=failures,
        required=null_required,
        normalized=normalized,
        warnings=warnings,
    )

    # NOTE: validate_thresholds MUST run before validate_performance_policy_spec
    # because it sets request["_resolved_policy"] used for profile-aware downgrade checks.
    # (Moved here from after performance_policy validation.)
    normalized["thresholds"] = validate_thresholds(request, failures, warnings, args.strict)

    context = request.get("context", {})
    if context is None:
        context = {}
    if not isinstance(context, dict):
        add_issue(
            failures,
            "invalid_context",
            "context must be an object when provided.",
            {"actual_type": type(context).__name__},
        )
    else:
        normalized["context"] = context

    return finish(args, failures, warnings, normalized, request_path=request_path)


def finish(
    args: argparse.Namespace,
    failures: List[Dict[str, Any]],
    warnings: List[Dict[str, Any]],
    normalized_request: Dict[str, Any],
    request_path: Optional[Path] = None,
) -> int:
    from _gate_utils import get_gate_elapsed, write_json as _write_report

    should_fail = bool(failures) or (args.strict and bool(warnings))
    status = "fail" if should_fail else "pass"

    fi = [GateIssue.from_legacy(f, Severity.ERROR) for f in failures]
    wi = [GateIssue.from_legacy(w, Severity.WARNING) for w in warnings]
    for issue in fi + wi:
        if not issue.remediation:
            issue.remediation = get_remediation(issue.code)

    input_files = {}
    if request_path:
        input_files["request"] = str(request_path)

    report = build_report_envelope(
        gate_name="request_contract_gate",
        status=status,
        strict_mode=bool(args.strict),
        failures=fi,
        warnings=wi,
        summary={"request_path": str(request_path) if request_path else None},
        input_files=input_files if input_files else None,
        extra={"normalized_request": normalized_request},
    )

    if args.report:
        # Sandbox the report path to the request's project root — without
        # this constraint, `--report ../sibling_gate/report.json` could
        # overwrite a neighbor gate's attestation (Codex review 2026-04-23
        # overwrite-primitive). When request_path is available (normal
        # case), use its parent.parent as sandbox — same derivation the
        # path validator in main() uses, keeping the two consistent.
        # When request_path is None (very early parse failure), fall back
        # to the legacy behavior but emit a warning.
        try:
            if request_path is not None:
                _req_parent = request_path.parent
                _sandbox = _req_parent.parent
                _report_path = resolve_path(
                    _req_parent, str(args.report), sandbox=_sandbox,
                )
            else:
                _report_path = Path(args.report).expanduser().resolve()
        except ValueError as exc:
            print(
                f"ERROR: --report path escapes request sandbox: {exc}",
                file=sys.stderr,
            )
            return 2
        _write_report(_report_path, report)

    print_gate_summary(
        gate_name="request_contract_gate",
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
