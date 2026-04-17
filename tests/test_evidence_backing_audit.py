"""P1-4 regression: score_paper_metadata emits unsubstantiated_claims
findings whenever extractor left an _evidence field empty for a
positive methodology claim.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "review"))

from score_paper_metadata import score_metadata  # type: ignore  # noqa: E402


BASE_METADATA = {
    "bibliographic": {"title": "Test", "year": 2026},
    "dataset": {
        "split_strategy": "temporal",
        "train_n": 1000,
        "test_n": 500,
        "n_patients_total": 2000,
        "prevalence_pct": 0.15,
        "n_events_positive": 300,
        "features_n": 25,
    },
    "model": {"n_candidate_models": 3, "hyperparameter_tuning": "grid_search",
              "tuning_set": "validation_only", "feature_selection_method": "l1"},
    "performance_metrics": {
        "test_auroc": 0.82,
        "bootstrap_ci_reported": True,
        "test_auroc_ci_lower": 0.78,
        "calibration_reported": True,
        "dca_reported": True,
        "test_brier_score": 0.12,
        "test_sensitivity": 0.75,
        "test_specificity": 0.80,
        "test_ppv": 0.70,
        "primary_metric": "AUROC",
    },
    "reporting_standards": {"tripod_ai_claimed": True, "limitation_section": True,
                            "equator_guideline_cited": "TRIPOD+AI",
                            "code_availability": "public_github",
                            "data_availability": "public"},
    "study_design": {"has_external_validation": True, "is_multicenter": True},
}


def _with_leakage(claims: dict, evidence: dict) -> dict:
    md = json.loads(json.dumps(BASE_METADATA))
    md["leakage_risk_assessment"] = {
        "patient_level_split_confirmed": claims.get("patient"),
        "patient_level_split_evidence": evidence.get("patient", ""),
        "temporal_split_confirmed": claims.get("temporal"),
        "temporal_split_evidence": evidence.get("temporal", ""),
        "preprocessing_fit_on_train_only": claims.get("preproc"),
        "preprocessing_evidence": evidence.get("preproc", ""),
        "tuning_used_test_data": claims.get("tuning"),
        "tuning_evidence": evidence.get("tuning", ""),
        "target_leakage_risk": "low",
        "post_index_feature_risk": "low",
    }
    return md


def test_positive_claim_with_evidence_passes_cleanly():
    md = _with_leakage(
        claims={"patient": True, "temporal": True, "preproc": True, "tuning": False},
        evidence={"patient": "We split patients (n=2000) such that all records from one patient were in one split",
                  "temporal": "Training data: 2018-2021; test: 2022",
                  "preproc": "Scalers were fit on the training fold only",
                  "tuning": "Hyperparameters were selected on the validation fold"},
    )
    result = score_metadata(md)
    assert "unsubstantiated_claims" not in result
    assert not result["leakage_flags"].get("_has_unsubstantiated_claims")


def test_positive_claim_without_evidence_flagged():
    md = _with_leakage(
        claims={"patient": True, "temporal": True, "preproc": True, "tuning": False},
        evidence={},  # all empty
    )
    result = score_metadata(md)
    assert "unsubstantiated_claims" in result
    flagged = [c["claim"] for c in result["unsubstantiated_claims"]]
    # All 4 positive-compliance claims should be flagged as unsubstantiated
    assert set(flagged) == {"patient_level_split", "temporal_split_confirmed",
                            "preprocess_train_only", "no_test_tuning"}
    assert result["leakage_flags"]["_has_unsubstantiated_claims"] is True


def test_negative_or_null_claim_not_audited():
    """Null or negative claims (tuning_used_test_data=True, i.e. BAD) are not
    'positive compliance' — extractor can't be expected to quote a confession.
    They should not be flagged as unsubstantiated."""
    md = _with_leakage(
        claims={"patient": None, "temporal": False, "preproc": None, "tuning": True},
        evidence={},
    )
    result = score_metadata(md)
    # No positive claims here, so audit should not flag any
    assert "unsubstantiated_claims" not in result


def test_partial_evidence_catches_only_missing():
    md = _with_leakage(
        claims={"patient": True, "temporal": True, "preproc": True, "tuning": False},
        evidence={"patient": "quoted evidence", "temporal": "", "preproc": "quoted",
                  "tuning": "quoted"},
    )
    result = score_metadata(md)
    flagged = [c["claim"] for c in result.get("unsubstantiated_claims", [])]
    assert flagged == ["temporal_split_confirmed"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
