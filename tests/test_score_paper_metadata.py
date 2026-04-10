"""Tests for score_paper_metadata.py — scoring logic, validation, and tier1 cap."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from score_paper_metadata import score_metadata, validate_metadata, _check_epv


# ---------------------------------------------------------------------------
# Scoring basics
# ---------------------------------------------------------------------------


def test_empty_metadata_scores_low():
    result = score_metadata({})
    assert result["total_score"] < 10
    assert result["grade"] == "Not publishable"


def test_perfect_metadata_scores_high():
    m = {
        "dataset": {
            "split_strategy": "temporal", "train_n": 5000, "test_n": 1000,
            "n_patients_total": 6000, "prevalence_pct": 15,
            "missing_data_strategy": "imputation", "n_events_positive": 900, "features_n": 20,
        },
        "leakage_risk_assessment": {
            "patient_level_split_confirmed": True, "temporal_split_confirmed": True,
            "preprocessing_fit_on_train_only": True, "tuning_used_test_data": False,
            "target_leakage_risk": "low", "post_index_feature_risk": "low",
        },
        "model": {
            "n_candidate_models": 5, "hyperparameter_tuning": "grid",
            "tuning_set": "validation_only", "feature_selection_method": "RFECV",
        },
        "performance_metrics": {
            "test_auroc": 0.85, "bootstrap_ci_reported": True,
            "test_auroc_ci_lower": 0.83, "calibration_reported": True,
            "dca_reported": True, "test_brier_score": 0.12,
            "test_sensitivity": 0.8, "test_specificity": 0.85,
            "test_ppv": 0.7, "primary_metric": "auroc",
            "external_auroc": 0.82,
        },
        "study_design": {"has_external_validation": True, "is_multicenter": True},
        "reporting_standards": {
            "tripod_ai_claimed": True, "limitation_section": True,
            "equator_guideline_cited": "TRIPOD+AI",
            "code_availability": "public_github", "data_availability": "public",
        },
    }
    result = score_metadata(m)
    assert result["total_score"] >= 90
    assert result["grade"] == "Publication-grade"


def test_score_has_12_dimensions():
    result = score_metadata({})
    assert len(result["dimensions"]) == 12


def test_weights_sum_to_100():
    result = score_metadata({})
    total_weight = sum(d["max"] for d in result["dimensions"].values())
    assert total_weight == 100


# ---------------------------------------------------------------------------
# Tier 1 hard floor cap
# ---------------------------------------------------------------------------


def test_tier1_cap_d2_zero():
    """D2 = 0 should cap grade at 'Major issues' even if total >= 75."""
    m = {
        "dataset": {
            "split_strategy": "temporal", "train_n": 5000, "test_n": 1000,
            "n_patients_total": 6000, "prevalence_pct": 15,
            "missing_data_strategy": "imputation", "n_events_positive": 900, "features_n": 20,
        },
        "leakage_risk_assessment": {
            "patient_level_split_confirmed": False, "temporal_split_confirmed": False,
            "preprocessing_fit_on_train_only": False, "tuning_used_test_data": True,
            "target_leakage_risk": "high", "post_index_feature_risk": "high",
        },
        "model": {
            "n_candidate_models": 5, "hyperparameter_tuning": "grid",
            "tuning_set": "validation_only", "feature_selection_method": "RFECV",
        },
        "performance_metrics": {
            "test_auroc": 0.85, "bootstrap_ci_reported": True,
            "test_auroc_ci_lower": 0.83, "calibration_reported": True,
            "dca_reported": True, "test_brier_score": 0.12,
            "test_sensitivity": 0.8, "test_specificity": 0.85,
            "test_ppv": 0.7, "primary_metric": "auroc",
            "external_auroc": 0.82,
        },
        "study_design": {"has_external_validation": True, "is_multicenter": True},
        "reporting_standards": {
            "tripod_ai_claimed": True, "limitation_section": True,
            "equator_guideline_cited": "TRIPOD+AI",
            "code_availability": "public_github", "data_availability": "public",
        },
    }
    result = score_metadata(m)
    assert result["dimensions"]["leakage_prevention"]["fraction"] == 0.0
    assert result["total_score"] >= 60
    assert result["grade"] == "Major issues", f"Expected 'Major issues' due to D2=0 cap, got '{result['grade']}'"


def test_tier1_cap_not_triggered_when_d2_nonzero():
    """If D2 > 0, no cap should apply."""
    m = {
        "leakage_risk_assessment": {
            "patient_level_split_confirmed": True,
            "preprocessing_fit_on_train_only": True,
        },
    }
    result = score_metadata(m)
    d2_frac = result["dimensions"]["leakage_prevention"]["fraction"]
    assert d2_frac > 0, "D2 should be non-zero with some checks passing"


# ---------------------------------------------------------------------------
# EPV check
# ---------------------------------------------------------------------------


def test_epv_adequate():
    assert _check_epv({"dataset": {"n_events_positive": 200, "features_n": 10}}) is True


def test_epv_inadequate():
    assert _check_epv({"dataset": {"n_events_positive": 5, "features_n": 10}}) is False


def test_epv_missing_data():
    assert _check_epv({"dataset": {}}) is False
    assert _check_epv({}) is False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_validate_empty_metadata_has_errors():
    issues = validate_metadata({})
    errors = [i for i in issues if i["level"] == "ERROR"]
    assert len(errors) >= 4, "Empty metadata should have at least 4 REQUIRED errors"


def test_validate_string_auroc():
    issues = validate_metadata({"performance_metrics": {"test_auroc": "0.95"}})
    type_issues = [i for i in issues if i["rule_id"] == "TYPE"]
    assert len(type_issues) >= 1


def test_validate_auroc_out_of_range():
    issues = validate_metadata({"performance_metrics": {"test_auroc": 1.5}})
    range_issues = [i for i in issues if i["rule_id"] == "RANGE"]
    assert len(range_issues) >= 1


def test_validate_ci_inconsistency():
    issues = validate_metadata({
        "performance_metrics": {
            "test_auroc": 0.90,
            "test_auroc_ci_lower": 0.92,
            "test_auroc_ci_upper": 0.95,
        }
    })
    p001 = [i for i in issues if i["rule_id"] == "P-001"]
    assert len(p001) >= 1, "AUROC below CI lower bound should trigger P-001"


def test_validate_tuning_contradiction():
    issues = validate_metadata({
        "leakage_risk_assessment": {"tuning_used_test_data": True},
        "model": {"tuning_set": "validation_only"},
    })
    l001 = [i for i in issues if i["rule_id"] == "L-001"]
    assert len(l001) >= 1


def test_validate_split_contradiction():
    issues = validate_metadata({
        "dataset": {"split_strategy": "random"},
        "leakage_risk_assessment": {"temporal_split_confirmed": True},
    })
    l004 = [i for i in issues if i["rule_id"] == "L-004"]
    assert len(l004) >= 1


def test_validate_suspicious_auroc():
    issues = validate_metadata({
        "performance_metrics": {"test_auroc": 0.999},
        "bibliographic": {"title": "test"},
        "dataset": {"n_patients_total": 100, "split_strategy": "random"},
    })
    p003 = [i for i in issues if i["rule_id"] == "P-003"]
    assert len(p003) >= 1


def test_validate_clean_metadata_no_errors():
    m = {
        "bibliographic": {"title": "Test Paper"},
        "dataset": {
            "split_strategy": "temporal", "n_patients_total": 5000,
            "train_n": 3500, "test_n": 1000,
        },
        "performance_metrics": {
            "test_auroc": 0.85,
            "test_auroc_ci_lower": 0.82,
            "test_auroc_ci_upper": 0.88,
        },
    }
    issues = validate_metadata(m)
    errors = [i for i in issues if i["level"] == "ERROR"]
    assert len(errors) == 0, f"Clean metadata should have no ERRORs, got: {errors}"


# ---------------------------------------------------------------------------
# Grade labels
# ---------------------------------------------------------------------------


def test_grade_labels_match_audit_shared():
    """Grade labels in score_metadata must match _audit_shared.score_interpretation."""
    from _audit_shared import score_interpretation

    for target, expected in [(95, "Publication-grade"), (80, "Solid but gaps remain"),
                              (65, "Major issues"), (40, "Not publishable")]:
        label = score_interpretation(target)[0]
        assert label == expected, f"At score {target}: expected '{expected}', got '{label}'"
