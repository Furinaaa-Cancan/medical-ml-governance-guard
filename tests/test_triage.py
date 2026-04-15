"""Tests for the triage module."""

import sys
from pathlib import Path

import pytest

# Add orchestration dir to path
_ORCH_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "orchestration")
_CORE_DIR = str(Path(__file__).resolve().parent.parent / "scripts" / "core")
if _ORCH_DIR not in sys.path:
    sys.path.insert(0, _ORCH_DIR)
if _CORE_DIR not in sys.path:
    sys.path.insert(0, _CORE_DIR)

from triage import triage_gates, triage_report, MANDATORY_GATES, _rule_triage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def minimal_project():
    """Project with only train/valid splits and no optional artifacts."""
    normalized = {
        "target_name": "diabetes",
        "claim_tier_target": "publication-grade",
        "primary_metric": "auroc",
        "split_paths": {"train": "train.csv", "valid": "valid.csv"},
    }
    split_paths = {"train": "train.csv", "valid": "valid.csv"}
    return normalized, split_paths


@pytest.fixture
def full_project():
    """Project with all optional artifacts provided."""
    normalized = {
        "target_name": "diabetes",
        "claim_tier_target": "publication-grade",
        "primary_metric": "auroc",
        "split_paths": {"train": "t.csv", "valid": "v.csv", "test": "te.csv"},
        "external_cohort_spec": "ext.json",
        "external_validation_report_file": "ext_report.json",
        "seed_sensitivity_report_file": "seed.json",
        "robustness_report_file": "robust.json",
        "feature_engineering_report_file": "fe.json",
        "model_selection_report_file": "ms.json",
        "prediction_trace_file": "pred.csv",
        "permutation_null_metrics_file": "perm.json",
        "ci_matrix_report_file": "ci.json",
        "model_pool_file": "pool.json",
        "distribution_report_file": "dist.json",
    }
    split_paths = {"train": "t.csv", "valid": "v.csv", "test": "te.csv"}
    return normalized, split_paths


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMandatoryGates:
    """Mandatory gates must never be skipped."""

    def test_mandatory_gates_never_skipped_minimal(self, minimal_project):
        normalized, split_paths = minimal_project
        skip_list = triage_gates(normalized, split_paths, verbose=False)
        for gate in MANDATORY_GATES:
            assert gate not in skip_list, f"Mandatory gate {gate} was skipped"

    def test_mandatory_gates_never_skipped_empty(self):
        skip_list = triage_gates({}, {}, verbose=False)
        for gate in MANDATORY_GATES:
            assert gate not in skip_list, f"Mandatory gate {gate} was skipped"

    def test_mandatory_gate_count(self):
        assert len(MANDATORY_GATES) == 9


class TestRuleTriage:
    """Rule-based triage decisions."""

    def test_no_test_split_skips_gates(self, minimal_project):
        normalized, split_paths = minimal_project
        skip_list = triage_gates(normalized, split_paths, verbose=False)
        expected_skipped = {
            "covariate_shift_gate",
            "imbalance_policy_gate",
            "missingness_policy_gate",
            "robustness_gate",
            "shap_interpretability_gate",
        }
        for gate in expected_skipped:
            assert gate in skip_list, f"{gate} should be skipped without test split"

    def test_no_external_cohort_skips_external_validation(self, minimal_project):
        normalized, split_paths = minimal_project
        skip_list = triage_gates(normalized, split_paths, verbose=False)
        assert "external_validation_gate" in skip_list

    def test_no_prediction_trace_skips_replay(self, minimal_project):
        normalized, split_paths = minimal_project
        skip_list = triage_gates(normalized, split_paths, verbose=False)
        assert "prediction_replay_gate" in skip_list
        assert "calibration_dca_gate" in skip_list

    def test_full_project_skips_nothing(self, full_project):
        normalized, split_paths = full_project
        skip_list = triage_gates(normalized, split_paths, verbose=False)
        assert len(skip_list) == 0

    def test_minimal_project_skip_count(self, minimal_project):
        normalized, split_paths = minimal_project
        skip_list = triage_gates(normalized, split_paths, verbose=False)
        # Should skip a substantial number of gates
        assert len(skip_list) >= 10
        # But not more than half (mandatory + some always-run)
        assert len(skip_list) <= 20


class TestTriageReport:
    """Structured report output."""

    def test_report_structure(self, minimal_project):
        normalized, split_paths = minimal_project
        report = triage_report(normalized, split_paths)
        assert "total_gates" in report
        assert "gates_to_run" in report
        assert "gates_to_skip" in report
        assert "mandatory_gates" in report
        assert "decisions" in report
        assert report["total_gates"] == 33

    def test_report_run_plus_skip_equals_total(self, minimal_project):
        normalized, split_paths = minimal_project
        report = triage_report(normalized, split_paths)
        assert len(report["gates_to_run"]) + len(report["gates_to_skip"]) == report["total_gates"]

    def test_report_decisions_have_reasons(self, minimal_project):
        normalized, split_paths = minimal_project
        report = triage_report(normalized, split_paths)
        for gate_name, decision in report["decisions"].items():
            assert "action" in decision
            assert "reason" in decision
            assert "source" in decision
            assert decision["action"] in ("run", "skip", "uncertain")
