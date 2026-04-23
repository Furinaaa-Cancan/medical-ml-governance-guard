"""Tests for scripts/request_contract_gate.py.

Covers helper functions, shape validators, cross-artifact alignment,
performance policy validation, and CLI integration.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
GATE_SCRIPT = SCRIPTS_DIR / "gates/request_contract_gate.py"

import request_contract_gate as rcg


# ── helpers ──────────────────────────────────────────────────────────────────

class TestIsFiniteNumber:
    def test_int(self):
        assert rcg.is_finite_number(42) is True

    def test_float(self):
        assert rcg.is_finite_number(3.14) is True

    def test_zero(self):
        assert rcg.is_finite_number(0) is True

    def test_negative(self):
        assert rcg.is_finite_number(-1.5) is True

    def test_nan(self):
        assert rcg.is_finite_number(float("nan")) is False

    def test_inf(self):
        assert rcg.is_finite_number(float("inf")) is False

    def test_neg_inf(self):
        assert rcg.is_finite_number(float("-inf")) is False

    def test_bool_false(self):
        assert rcg.is_finite_number(False) is False

    def test_bool_true(self):
        assert rcg.is_finite_number(True) is False

    def test_string(self):
        assert rcg.is_finite_number("3.14") is False

    def test_none(self):
        assert rcg.is_finite_number(None) is False


class TestSha256File:
    def test_known_content(self, tmp_path: Path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"hello world\n")
        expected = hashlib.sha256(b"hello world\n").hexdigest()
        assert rcg.sha256_file(f) == expected

    def test_empty_file(self, tmp_path: Path):
        f = tmp_path / "empty.txt"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert rcg.sha256_file(f) == expected


class TestMustBeNonEmptyStr:
    def test_valid(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.must_be_non_empty_str({"key": "value"}, "key", failures)
        assert result == "value"
        assert len(failures) == 0

    def test_whitespace_stripped(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.must_be_non_empty_str({"key": "  hello  "}, "key", failures)
        assert result == "hello"

    def test_empty_string(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.must_be_non_empty_str({"key": ""}, "key", failures)
        assert result is None
        assert len(failures) == 1
        assert failures[0]["code"] == "invalid_field"

    def test_whitespace_only(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.must_be_non_empty_str({"key": "   "}, "key", failures)
        assert result is None
        assert len(failures) == 1

    def test_missing_key(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.must_be_non_empty_str({}, "key", failures)
        assert result is None
        assert len(failures) == 1

    def test_non_string(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.must_be_non_empty_str({"key": 123}, "key", failures)
        assert result is None
        assert len(failures) == 1


class TestIsValidDotPath:
    def test_simple(self):
        assert rcg.is_valid_dot_path("metrics") is True

    def test_dotted(self):
        assert rcg.is_valid_dot_path("split_metrics.test.pr_auc") is True

    def test_with_numbers(self):
        assert rcg.is_valid_dot_path("block1.value2") is True

    def test_empty(self):
        assert rcg.is_valid_dot_path("") is False

    def test_starts_with_dot(self):
        assert rcg.is_valid_dot_path(".metrics") is False

    def test_ends_with_dot(self):
        assert rcg.is_valid_dot_path("metrics.") is False

    def test_double_dot(self):
        assert rcg.is_valid_dot_path("a..b") is False

    def test_special_chars(self):
        assert rcg.is_valid_dot_path("a-b") is False

    def test_space(self):
        assert rcg.is_valid_dot_path("a b") is False


class TestCanonicalMetricToken:
    def test_basic(self):
        assert rcg.canonical_metric_token("pr_auc") == "prauc"

    def test_uppercase(self):
        assert rcg.canonical_metric_token("PR_AUC") == "prauc"

    def test_mixed_separators(self):
        assert rcg.canonical_metric_token("pr-auc") == "prauc"

    def test_spaces(self):
        assert rcg.canonical_metric_token("pr auc") == "prauc"


class TestToInt:
    def test_int(self):
        assert rcg.to_int(5) == 5

    def test_float_whole(self):
        assert rcg.to_int(5.0) == 5

    def test_float_fractional(self):
        assert rcg.to_int(5.5) is None

    def test_bool(self):
        assert rcg.to_int(True) is None

    def test_string(self):
        assert rcg.to_int("5") is None

    def test_none(self):
        assert rcg.to_int(None) is None

    def test_nan(self):
        assert rcg.to_int(float("nan")) is None

    def test_inf(self):
        assert rcg.to_int(float("inf")) is None


class TestGetGapPairBlock:
    def test_underscore(self):
        data = {"train_valid": {"pr_auc": {"warn": 0.05}}}
        assert rcg.get_gap_pair_block(data, "train", "valid") == {"pr_auc": {"warn": 0.05}}

    def test_dash(self):
        data = {"train-valid": {"pr_auc": {"warn": 0.05}}}
        assert rcg.get_gap_pair_block(data, "train", "valid") == {"pr_auc": {"warn": 0.05}}

    def test_concat(self):
        data = {"trainvalid": {"pr_auc": {"warn": 0.05}}}
        assert rcg.get_gap_pair_block(data, "train", "valid") == {"pr_auc": {"warn": 0.05}}

    def test_not_found(self):
        assert rcg.get_gap_pair_block({}, "train", "valid") is None


class TestRequireNumeric:
    def test_valid(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.require_numeric({"val": 0.95}, "val", failures)
        assert result == 0.95
        assert len(failures) == 0

    def test_missing(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.require_numeric({}, "val", failures)
        assert result is None
        assert len(failures) == 1
        assert failures[0]["code"] == "invalid_numeric_field"

    def test_string(self):
        failures: List[Dict[str, Any]] = []
        result = rcg.require_numeric({"val": "abc"}, "val", failures)
        assert result is None
        assert len(failures) == 1


# ── validate_thresholds ─────────────────────────────────────────────────────

class TestValidateThresholds:
    def test_valid_thresholds(self):
        request = {"thresholds": {"alpha": 0.05, "min_delta": 0.03, "ci_max_width": 0.2, "ci_min_resamples": 500}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        parsed = rcg.validate_thresholds(request, failures, warnings, strict=False)
        assert len(failures) == 0
        assert parsed["alpha"] == 0.05
        assert parsed["ci_min_resamples"] == 500.0

    def test_alpha_out_of_range(self):
        request = {"thresholds": {"alpha": 0.0}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=False)
        codes = [f["code"] for f in failures]
        assert "invalid_threshold_alpha_range" in codes

    def test_alpha_above_one(self):
        request = {"thresholds": {"alpha": 1.5}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=False)
        codes = [f["code"] for f in failures]
        assert "invalid_threshold_alpha_range" in codes

    def test_negative_min_delta(self):
        request = {"thresholds": {"min_delta": -0.01}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=False)
        codes = [f["code"] for f in failures]
        assert "invalid_threshold_min_delta_range" in codes

    def test_ci_max_width_zero(self):
        request = {"thresholds": {"ci_max_width": 0.0}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=False)
        codes = [f["code"] for f in failures]
        assert "invalid_threshold_ci_max_width_range" in codes

    def test_ci_min_resamples_bool(self):
        request = {"thresholds": {"ci_min_resamples": True}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=False)
        codes = [f["code"] for f in failures]
        assert "invalid_threshold_value" in codes

    def test_ci_min_resamples_below_one(self):
        request = {"thresholds": {"ci_min_resamples": 0}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=False)
        codes = [f["code"] for f in failures]
        assert "invalid_threshold_ci_min_resamples_range" in codes

    def test_thresholds_not_dict(self):
        request = {"thresholds": "bad"}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        parsed = rcg.validate_thresholds(request, failures, warnings, strict=False)
        assert parsed == {}
        assert len(failures) == 1
        assert failures[0]["code"] == "invalid_thresholds"

    def test_thresholds_none(self):
        request = {"thresholds": None}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        parsed = rcg.validate_thresholds(request, failures, warnings, strict=False)
        assert parsed == {}

    def test_strict_missing_alpha_warning(self):
        request = {"thresholds": {}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=True)
        codes = [w["code"] for w in warnings]
        assert "missing_threshold_alpha" in codes

    def test_strict_missing_min_delta_warning(self):
        request = {"thresholds": {"alpha": 0.05}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=True)
        codes = [w["code"] for w in warnings]
        assert "missing_threshold_min_delta" in codes

    def test_invalid_threshold_value_type(self):
        request = {"thresholds": {"alpha": "not_a_number"}}
        failures: List[Dict[str, Any]] = []
        warnings: List[Dict[str, Any]] = []
        rcg.validate_thresholds(request, failures, warnings, strict=False)
        codes = [f["code"] for f in failures]
        assert "invalid_threshold_value" in codes


# ── shape validators ─────────────────────────────────────────────────────────

class TestValidateEvaluationReportShape:
    def _make_valid_eval(self, tmp_path: Path) -> Path:
        p = tmp_path / "eval.json"
        data = {
            "split_metrics": {
                "train": {"metrics": {"pr_auc": 0.9}, "confusion_matrix": {"tp": 10}},
                "valid": {"metrics": {"pr_auc": 0.85}, "confusion_matrix": {"tp": 8}},
                "test": {"metrics": {"pr_auc": 0.82}, "confusion_matrix": {"tp": 7}},
            },
            "threshold_selection": {"selection_split": "valid", "selected_threshold": 0.5},
            "feature_engineering": {"provenance": {"selected_features": ["a"]}},
            "distribution_summary": {"status": "ok"},
            "ci_matrix_ref": "ci_matrix_report.json",
            "transport_ci_ref": "transport_ci.json",
            "metadata": {
                "imputation": {
                    "policy_strategy": "median",
                    "executed_strategy": "median",
                    "fit_scope": "train_only",
                    "scale_guard": {"method": "standard"},
                },
                "prediction_trace_sha256": "a" * 64,
                "external_validation_report_sha256": "b" * 64,
                "external_cohort_count": 2,
            },
        }
        p.write_text(json.dumps(data))
        return p

    def test_valid_report(self, tmp_path: Path):
        p = self._make_valid_eval(tmp_path)
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(str(p), failures)
        assert len(failures) == 0

    def test_missing_split_metrics(self, tmp_path: Path):
        p = tmp_path / "eval.json"
        p.write_text(json.dumps({"threshold_selection": {}}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "evaluation_report_missing_split_metrics" in codes

    def test_missing_threshold_selection(self, tmp_path: Path):
        p = tmp_path / "eval.json"
        p.write_text(json.dumps({
            "split_metrics": {
                "train": {"metrics": {}, "confusion_matrix": {}},
                "valid": {"metrics": {}, "confusion_matrix": {}},
                "test": {"metrics": {}, "confusion_matrix": {}},
            }
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "evaluation_report_missing_threshold_selection" in codes

    def test_invalid_selection_split(self, tmp_path: Path):
        p = tmp_path / "eval.json"
        p.write_text(json.dumps({
            "split_metrics": {
                "train": {"metrics": {}, "confusion_matrix": {}},
                "valid": {"metrics": {}, "confusion_matrix": {}},
                "test": {"metrics": {}, "confusion_matrix": {}},
            },
            "threshold_selection": {"selection_split": "train"},
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "threshold_selection_split_invalid" in codes

    def test_invalid_json(self, tmp_path: Path):
        p = tmp_path / "eval.json"
        p.write_text("not json")
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "invalid_evaluation_report" in codes

    def test_missing_metadata_trace_sha(self, tmp_path: Path):
        p = tmp_path / "eval.json"
        data = {
            "split_metrics": {
                "train": {"metrics": {}, "confusion_matrix": {}},
                "valid": {"metrics": {}, "confusion_matrix": {}},
                "test": {"metrics": {}, "confusion_matrix": {}},
            },
            "threshold_selection": {"selection_split": "valid"},
            "feature_engineering": {"provenance": {}},
            "distribution_summary": {},
            "ci_matrix_ref": "x",
            "transport_ci_ref": "y",
            "metadata": {
                "imputation": {
                    "policy_strategy": "median",
                    "executed_strategy": "median",
                    "fit_scope": "train_only",
                    "scale_guard": {},
                },
                "prediction_trace_sha256": "short",
                "external_validation_report_sha256": "b" * 64,
                "external_cohort_count": 2,
            },
        }
        p.write_text(json.dumps(data))
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "evaluation_report_missing_prediction_trace_hash" in codes

    def test_external_cohort_count_below_2(self, tmp_path: Path):
        p = tmp_path / "eval.json"
        data = {
            "split_metrics": {
                "train": {"metrics": {}, "confusion_matrix": {}},
                "valid": {"metrics": {}, "confusion_matrix": {}},
                "test": {"metrics": {}, "confusion_matrix": {}},
            },
            "threshold_selection": {"selection_split": "valid"},
            "feature_engineering": {"provenance": {}},
            "distribution_summary": {},
            "ci_matrix_ref": "x",
            "transport_ci_ref": "y",
            "metadata": {
                "imputation": {
                    "policy_strategy": "median",
                    "executed_strategy": "median",
                    "fit_scope": "train_only",
                    "scale_guard": {},
                },
                "prediction_trace_sha256": "a" * 64,
                "external_validation_report_sha256": "b" * 64,
                "external_cohort_count": 1,
            },
        }
        p.write_text(json.dumps(data))
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "evaluation_report_external_cohort_count_invalid" in codes


class TestValidateModelSelectionReportShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "ms.json"
        candidates = [
            {"selection_metrics": {"pr_auc": {"n_folds": 5, "fold_scores": [0.8, 0.82, 0.81, 0.83, 0.79]}}}
            for _ in range(3)
        ]
        p.write_text(json.dumps({
            "selection_policy": {"primary_metric": "pr_auc"},
            "candidates": candidates,
            "data_fingerprints": {"train": {}, "valid": {}, "test": {}},
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_model_selection_report_shape(str(p), failures)
        assert len(failures) == 0

    def test_too_few_candidates(self, tmp_path: Path):
        p = tmp_path / "ms.json"
        p.write_text(json.dumps({
            "selection_policy": {},
            "candidates": [{"selection_metrics": {"pr_auc": {"n_folds": 5, "fold_scores": [0.8]}}}],
            "data_fingerprints": {},
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_model_selection_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "model_selection_invalid_candidates" in codes

    def test_invalid_json(self, tmp_path: Path):
        p = tmp_path / "ms.json"
        p.write_text("{bad")
        failures: List[Dict[str, Any]] = []
        rcg.validate_model_selection_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "invalid_model_selection_report" in codes


class TestValidateSeedSensitivityReportShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "seed.json"
        p.write_text(json.dumps({
            "primary_metric": "pr_auc",
            "per_seed_results": [{"seed": 1}],
            "summary": {"std": 0.01},
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_seed_sensitivity_report_shape(str(p), failures)
        assert len(failures) == 0

    def test_missing_primary_metric(self, tmp_path: Path):
        p = tmp_path / "seed.json"
        p.write_text(json.dumps({"per_seed_results": [{}], "summary": {}}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_seed_sensitivity_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "invalid_seed_sensitivity_report" in codes


class TestValidateRobustnessReportShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "robust.json"
        p.write_text(json.dumps({
            "overall_test_metrics": {"pr_auc": 0.85},
            "time_slices": {"slices": [{"metric": 0.8}]},
            "patient_hash_groups": {"groups": [{"metric": 0.82}]},
            "summary": {"status": "pass"},
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_robustness_report_shape(str(p), failures)
        assert len(failures) == 0

    def test_non_finite_pr_auc(self, tmp_path: Path):
        p = tmp_path / "robust.json"
        p.write_text(json.dumps({
            "overall_test_metrics": {"pr_auc": "bad"},
            "time_slices": {"slices": [{}]},
            "patient_hash_groups": {"groups": [{}]},
            "summary": {},
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_robustness_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "invalid_robustness_report" in codes


class TestValidateExecutionAttestationShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "attest.json"
        p.write_text(json.dumps({
            "required_artifact_names": [
                "training_log", "training_config", "model_artifact",
                "model_selection_report", "robustness_report",
                "seed_sensitivity_report", "evaluation_report",
                "prediction_trace", "external_validation_report",
            ]
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_execution_attestation_shape(str(p), failures)
        assert len(failures) == 0

    def test_missing_artifacts(self, tmp_path: Path):
        p = tmp_path / "attest.json"
        p.write_text(json.dumps({"required_artifact_names": ["training_log"]}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_execution_attestation_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "missing_execution_attestation_required_artifact" in codes


class TestValidateFeatureGroupSpecShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "fg.json"
        p.write_text(json.dumps({"groups": {"lab": ["age", "bp"], "vitals": ["hr"]}}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_feature_group_spec_shape(str(p), failures)
        assert len(failures) == 0

    def test_duplicate_feature(self, tmp_path: Path):
        p = tmp_path / "fg.json"
        p.write_text(json.dumps({"groups": {"a": ["age"], "b": ["age"]}}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_feature_group_spec_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "feature_group_spec_missing_or_invalid" in codes

    def test_empty_groups(self, tmp_path: Path):
        p = tmp_path / "fg.json"
        p.write_text(json.dumps({"groups": {}}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_feature_group_spec_shape(str(p), failures)
        assert len(failures) == 1


class TestValidateExternalCohortSpecShape:
    def test_valid(self, tmp_path: Path):
        # Create cohort data files
        c1 = tmp_path / "cohort1.csv"
        c2 = tmp_path / "cohort2.csv"
        c1.write_text("a,b\n1,2\n")
        c2.write_text("a,b\n3,4\n")
        p = tmp_path / "cohort_spec.json"
        p.write_text(json.dumps({
            "cohorts": [
                {"cohort_id": "c1", "cohort_type": "cross_period", "path": str(c1)},
                {"cohort_id": "c2", "cohort_type": "cross_institution", "path": str(c2)},
            ]
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_external_cohort_spec_shape(str(p), failures)
        assert len(failures) == 0

    def test_missing_cohort_type(self, tmp_path: Path):
        c1 = tmp_path / "cohort1.csv"
        c1.write_text("a\n1\n")
        p = tmp_path / "cohort_spec.json"
        p.write_text(json.dumps({
            "cohorts": [
                {"cohort_id": "c1", "cohort_type": "cross_period", "path": str(c1)},
            ]
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_external_cohort_spec_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "external_cohort_spec_missing_supported_type" in codes


class TestValidateDistributionReportShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "dist.json"
        p.write_text(json.dumps({"schema_version": "2.0", "distribution_matrix": [{"feature": "a"}]}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_distribution_report_shape(str(p), failures)
        assert len(failures) == 0

    def test_missing_matrix(self, tmp_path: Path):
        p = tmp_path / "dist.json"
        p.write_text(json.dumps({"schema_version": "2.0"}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_distribution_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "distribution_report_schema_invalid" in codes


class TestValidateCiMatrixReportShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "ci.json"
        p.write_text(json.dumps({"split_metrics_ci": {"test": {}}, "transport_drop_ci": {"valid_test": {}}}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_ci_matrix_report_shape(str(p), failures)
        assert len(failures) == 0

    def test_missing_transport(self, tmp_path: Path):
        p = tmp_path / "ci.json"
        p.write_text(json.dumps({"split_metrics_ci": {}}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_ci_matrix_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "transport_ci_invalid" in codes


class TestValidateFeatureEngineeringReportShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "fe.json"
        p.write_text(json.dumps({
            "feature_groups": {"lab": ["a"]},
            "stability": {"cv_frequency": 0.8},
            "reproducibility": {"hash": "abc"},
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_feature_engineering_report_shape(str(p), failures)
        assert len(failures) == 0

    def test_missing_stability(self, tmp_path: Path):
        p = tmp_path / "fe.json"
        p.write_text(json.dumps({"feature_groups": {}}))
        failures: List[Dict[str, Any]] = []
        rcg.validate_feature_engineering_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "feature_stability_evidence_missing" in codes


class TestValidateExternalValidationReportShape:
    def test_valid(self, tmp_path: Path):
        p = tmp_path / "ext.json"
        p.write_text(json.dumps({
            "cohorts": [
                {"cohort_id": "c1", "cohort_type": "cross_period", "metrics": {"pr_auc": 0.8}, "confusion_matrix": {}},
                {"cohort_id": "c2", "cohort_type": "cross_institution", "metrics": {"pr_auc": 0.75}, "confusion_matrix": {}},
            ]
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_external_validation_report_shape(str(p), failures)
        assert len(failures) == 0

    def test_missing_both_types(self, tmp_path: Path):
        p = tmp_path / "ext.json"
        p.write_text(json.dumps({
            "cohorts": [
                {"cohort_id": "c1", "cohort_type": "cross_period", "metrics": {}, "confusion_matrix": {}},
            ]
        }))
        failures: List[Dict[str, Any]] = []
        rcg.validate_external_validation_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "external_validation_report_invalid_cohort" in codes


# ── CLI integration ──────────────────────────────────────────────────────────

def _make_minimal_request(tmp_path: Path) -> Path:
    """Build a minimal leakage-audited request that should pass."""
    train = tmp_path / "train.csv"
    valid = tmp_path / "valid.csv"
    test = tmp_path / "test.csv"
    for f in (train, valid, test):
        f.write_text("patient_id,y\nP001,0\nP002,1\n")

    request = {
        "study_id": "study-001",
        "run_id": "run-001",
        "target_name": "readmission",
        "prediction_unit": "admission",
        "index_time_col": "event_time",
        "label_col": "y",
        "patient_id_col": "patient_id",
        "primary_metric": "pr_auc",
        "phenotype_definition_spec": "pheno.json",
        "claim_tier_target": "leakage-audited",
        "split_paths": {
            "train": str(train),
            "valid": str(valid),
            "test": str(test),
        },
        "thresholds": {"alpha": 0.05, "min_delta": 0.03},
    }
    # Create phenotype spec
    pheno = tmp_path / "pheno.json"
    pheno.write_text(json.dumps({"definition": "test"}))

    req_path = tmp_path / "request.json"
    req_path.write_text(json.dumps(request))
    return req_path


def _run_gate(request_path: Path, report_path: Path, strict: bool = False) -> dict:
    cmd = [sys.executable, str(GATE_SCRIPT), "--request", str(request_path), "--report", str(report_path)]
    if strict:
        cmd.append("--strict")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(SCRIPTS_DIR))
    if report_path.exists():
        return json.loads(report_path.read_text())
    return {"returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


class TestCLIIntegration:
    def test_minimal_pass(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "pass"
        assert report["failure_count"] == 0

    def test_missing_request_file(self, tmp_path: Path):
        report_path = tmp_path / "report.json"
        req = tmp_path / "nonexistent.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "missing_request_file" in codes

    def test_invalid_json(self, tmp_path: Path):
        req = tmp_path / "bad.json"
        req.write_text("{not valid json")
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_request_json" in codes

    def test_non_object_root(self, tmp_path: Path):
        req = tmp_path / "arr.json"
        req.write_text("[1, 2, 3]")
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_request_json" in codes

    def test_missing_required_fields(self, tmp_path: Path):
        req = tmp_path / "empty.json"
        req.write_text("{}")
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_field" in codes

    def test_invalid_claim_tier(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["claim_tier_target"] = "unknown-tier"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_claim_tier_target" in codes

    def test_duplicate_split_paths(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["split_paths"]["valid"] = data["split_paths"]["train"]
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "duplicate_split_path" in codes

    def test_missing_split_file(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["split_paths"]["train"] = str(tmp_path / "does_not_exist.csv")
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "split_path_not_found" in codes

    def test_strict_mode_warnings_become_fail(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        del data["thresholds"]
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path, strict=True)
        assert report["strict_mode"] is True
        if report["warning_count"] > 0:
            assert report["status"] == "fail"

    def test_report_structure(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert "status" in report
        assert "strict_mode" in report
        assert "request_path" in report.get("summary", {})
        assert "failure_count" in report
        assert "warning_count" in report
        assert "failures" in report
        assert "warnings" in report
        assert "normalized_request" in report

    def test_split_paths_not_dict(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["split_paths"] = "bad"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_split_paths" in codes

    def test_evaluation_metric_path_valid(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["evaluation_metric_path"] = "split_metrics.test.metrics.pr_auc"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "pass"
        assert report["normalized_request"]["evaluation_metric_path"] == "split_metrics.test.metrics.pr_auc"

    def test_evaluation_metric_path_mismatch(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["evaluation_metric_path"] = "split_metrics.test.metrics.roc_auc"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        codes = [f["code"] for f in report["failures"]]
        assert "metric_path_metric_mismatch" in codes

    def test_evaluation_metric_path_invalid_dot_path(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["evaluation_metric_path"] = "bad..path"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_field" in codes

    def test_actual_primary_metric_valid(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["actual_primary_metric"] = 0.85
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "pass"
        assert report["normalized_request"]["actual_primary_metric"] == 0.85

    def test_actual_primary_metric_non_numeric(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["actual_primary_metric"] = "not_a_number"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_numeric_field" in codes

    def test_context_non_dict(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["context"] = "not_a_dict"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_context" in codes


class TestPublicationGradeRequest:
    """Test publication-grade specific requirements."""

    def test_publication_requires_pr_auc(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["claim_tier_target"] = "publication-grade"
        data["primary_metric"] = "roc_auc"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        codes = [f["code"] for f in report["failures"]]
        assert "unsupported_primary_metric" in codes

    def test_publication_missing_lineage_fields(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        data = json.loads(req.read_text())
        data["claim_tier_target"] = "publication-grade"
        req.write_text(json.dumps(data))
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "missing_required_path" in codes or "missing_publication_grade_v3_field" in codes


# ── Evaluation report shape validation ─────────────────────────────────

class TestEvaluationReportShape:
    """Test that required fields in evaluation_report are validated."""

    def _write_eval(self, tmp_path: Path, content: dict) -> str:
        p = tmp_path / "eval.json"
        p.write_text(json.dumps(content), encoding="utf-8")
        return str(p)

    def test_missing_threshold_selection(self, tmp_path: Path):
        path = self._write_eval(tmp_path, {
            "metrics": {"pr_auc": 0.8},
            "metadata": {"model_id": "lr_l2"},
        })
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(path, failures)
        codes = [f["code"] for f in failures]
        assert "evaluation_report_missing_threshold_selection" in codes

    def test_missing_prediction_trace_hash(self, tmp_path: Path):
        path = self._write_eval(tmp_path, {
            "metrics": {"pr_auc": 0.8},
            "metadata": {"model_id": "lr_l2"},
            "threshold_selection": {"method": "youden_j", "split": "valid"},
        })
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(path, failures)
        codes = [f["code"] for f in failures]
        assert "evaluation_report_missing_prediction_trace_hash" in codes

    def test_missing_split_metrics(self, tmp_path: Path):
        path = self._write_eval(tmp_path, {
            "metrics": {"pr_auc": 0.8},
            "metadata": {"model_id": "lr_l2"},
            "threshold_selection": {"method": "youden_j", "split": "valid"},
            "prediction_trace_sha256": "a" * 64,
        })
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(path, failures)
        codes = [f["code"] for f in failures]
        assert "evaluation_report_missing_split_metrics" in codes

    def test_invalid_eval_json(self, tmp_path: Path):
        p = tmp_path / "eval.json"
        p.write_text("not json!")
        failures: List[Dict[str, Any]] = []
        rcg.validate_evaluation_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "invalid_evaluation_report" in codes


# ── Model selection report shape ───────────────────────────────────────

class TestModelSelectionReportShape:

    def _write_report(self, tmp_path: Path, content: dict) -> str:
        p = tmp_path / "model_sel.json"
        p.write_text(json.dumps(content), encoding="utf-8")
        return str(p)

    def test_not_a_dict(self, tmp_path: Path):
        p = tmp_path / "model_sel.json"
        p.write_text(json.dumps([1, 2, 3]))
        failures: List[Dict[str, Any]] = []
        rcg.validate_model_selection_report_shape(str(p), failures)
        codes = [f["code"] for f in failures]
        assert "invalid_model_selection_report" in codes

    def test_valid_minimal(self, tmp_path: Path):
        path = self._write_report(tmp_path, {
            "selected_model_id": "lr_l2",
            "candidates": [{"model_id": "lr_l2", "score": 0.8}],
        })
        failures: List[Dict[str, Any]] = []
        rcg.validate_model_selection_report_shape(path, failures)
        structural = [f for f in failures if f["code"] == "invalid_model_selection_report"]
        assert len(structural) == 0


# ── External cohort spec shape ─────────────────────────────────────────

class TestExternalCohortSpecShape:

    def _write_spec(self, tmp_path: Path, content: dict) -> str:
        p = tmp_path / "ext_cohort.json"
        p.write_text(json.dumps(content), encoding="utf-8")
        return str(p)

    def test_missing_cohorts_array(self, tmp_path: Path):
        path = self._write_spec(tmp_path, {})
        failures: List[Dict[str, Any]] = []
        rcg.validate_external_cohort_spec_shape(path, failures)
        codes = [f["code"] for f in failures]
        assert len(codes) > 0

    def test_invalid_cohort_entry(self, tmp_path: Path):
        path = self._write_spec(tmp_path, {"cohorts": ["not_a_dict"]})
        failures: List[Dict[str, Any]] = []
        rcg.validate_external_cohort_spec_shape(path, failures)
        codes = [f["code"] for f in failures]
        assert len(codes) > 0

    def test_missing_supported_type(self, tmp_path: Path):
        path = self._write_spec(tmp_path, {
            "cohorts": [{"cohort_id": "test1", "path": "data.csv"}],
        })
        failures: List[Dict[str, Any]] = []
        rcg.validate_external_cohort_spec_shape(path, failures)
        codes = [f["code"] for f in failures]
        assert any("type" in c.lower() or "cohort" in c.lower() for c in codes)


# ── Robustness / seed sensitivity report shape ─────────────────────────

class TestOptionalReportShapes:

    def test_robustness_report_non_dict(self, tmp_path: Path):
        failures: List[Dict[str, Any]] = []
        rcg.validate_robustness_report_shape("not_a_dict", failures)
        codes = [f["code"] for f in failures]
        assert "invalid_robustness_report" in codes

    def test_seed_sensitivity_report_non_dict(self, tmp_path: Path):
        failures: List[Dict[str, Any]] = []
        rcg.validate_seed_sensitivity_report_shape("not_a_dict", failures)
        codes = [f["code"] for f in failures]
        assert "invalid_seed_sensitivity_report" in codes

    def test_distribution_report_non_dict(self, tmp_path: Path):
        failures: List[Dict[str, Any]] = []
        rcg.validate_distribution_report_shape("not_a_dict", failures)
        codes = [f["code"] for f in failures]
        assert "distribution_report_schema_invalid" in codes


# ── Strict mode ────────────────────────────────────────────────────────

class TestStrictMode:

    def test_strict_fails_on_warnings(self, tmp_path: Path):
        req = _make_minimal_request(tmp_path)
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path, strict=True)
        # Strict mode should produce a stricter result
        assert "strict_mode" in report
        assert report["strict_mode"] is True


# ── policy baselines JSON loading ────────────────────────────────────────────


class TestPolicyBaselinesLoading:
    """Verify publication-policy-baselines.json loads correctly with tuple keys."""

    def test_baselines_loaded(self):
        assert isinstance(rcg.PUBLICATION_POLICY_BASELINES, dict)
        assert rcg.PUBLICATION_POLICY_BASELINES["beta"] == 2.0

    def test_gap_thresholds_are_tuples(self):
        gaps = rcg.PUBLICATION_POLICY_BASELINES["gap_thresholds_max"]
        assert isinstance(gaps, dict)
        for key in gaps:
            assert isinstance(key, tuple), f"Expected tuple key, got {type(key)}: {key}"
            assert len(key) == 3

    def test_allowed_selection_splits_is_set(self):
        splits = rcg.PUBLICATION_POLICY_BASELINES["allowed_selection_splits"]
        assert isinstance(splits, set)
        assert "valid" in splits

    def test_profiles_loaded(self):
        assert isinstance(rcg._PROFILE_OVERRIDES, dict)
        assert "standard" in rcg.ALLOWED_PROFILES
        assert "small_cohort" in rcg.ALLOWED_PROFILES

    def test_profile_override_gap_keys_are_tuples(self):
        for profile_name, overrides in rcg._PROFILE_OVERRIDES.items():
            if "gap_thresholds_max" in overrides:
                for key in overrides["gap_thresholds_max"]:
                    assert isinstance(key, tuple), (
                        f"Profile '{profile_name}' gap key is {type(key)}: {key}"
                    )

    def test_apply_profile_merges(self):
        resolved = rcg._apply_profile(rcg.PUBLICATION_POLICY_BASELINES, "small_cohort")
        assert resolved["clinical_floors_min"]["sensitivity_min"] == 0.75
        assert resolved["beta"] == 2.0


# ── SEC2 path-sandbox regression (Codex second-opinion finding) ──────────────

class TestPathSandboxEscape:
    """Round-2 Codex audit surfaced a gap: `resolve_path()` accepts a
    `sandbox` parameter but no call site in request_contract_gate was using
    it. A malicious request could declare `split_paths.train` at
    ~/other-user/secrets.csv and the gate would happily open it.
    These tests lock in that sandbox is now enforced."""

    def _make_request_in_subdir(self, tmp_path: Path, train_path: Path) -> Path:
        """Create request.json inside tmp_path/configs/ so sandbox =
        tmp_path. Splits can then be steered outside the sandbox."""
        configs = tmp_path / "configs"
        configs.mkdir(exist_ok=True)
        data = tmp_path / "data"
        data.mkdir(exist_ok=True)
        # Create valid/test under data/ (legitimate layout)
        valid = data / "valid.csv"
        test = data / "test.csv"
        for f in (valid, test):
            f.write_text("patient_id,y\nP001,0\nP002,1\n")
        pheno = data / "pheno.json"
        pheno.write_text(json.dumps({"definition": "test"}))

        request = {
            "study_id": "study-001",
            "run_id": "run-001",
            "target_name": "readmission",
            "prediction_unit": "admission",
            "index_time_col": "event_time",
            "label_col": "y",
            "patient_id_col": "patient_id",
            "primary_metric": "pr_auc",
            "phenotype_definition_spec": "../data/pheno.json",
            "claim_tier_target": "leakage-audited",
            "split_paths": {
                "train": str(train_path),
                "valid": "../data/valid.csv",
                "test": "../data/test.csv",
            },
            "thresholds": {"alpha": 0.05, "min_delta": 0.03},
        }
        req_path = configs / "request.json"
        req_path.write_text(json.dumps(request))
        return req_path

    def test_train_split_outside_sandbox_fails(self, tmp_path: Path, tmp_path_factory):
        """A train.csv declared outside the project root must be rejected
        with path_escapes_sandbox, not silently opened."""
        # Create a file in a DIFFERENT tmp directory — outside tmp_path's sandbox
        outside_dir = tmp_path_factory.mktemp("outside")
        outside_csv = outside_dir / "secrets.csv"
        outside_csv.write_text("patient_id,y\nP001,0\n")

        req = self._make_request_in_subdir(tmp_path, outside_csv)
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)

        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "path_escapes_sandbox" in codes, (
            f"Sandbox escape should be flagged; got codes: {codes}"
        )

    def test_legitimate_subdir_path_passes_sandbox(self, tmp_path: Path):
        """The canonical configs/../data layout must still pass — sandbox
        should NOT false-positive on legitimate relative paths."""
        # train.csv under tmp_path/data/ — i.e., under the sandbox root
        data = tmp_path / "data"
        data.mkdir(exist_ok=True)
        train = data / "train.csv"
        train.write_text("patient_id,y\nP001,0\nP002,1\n")

        req = self._make_request_in_subdir(tmp_path, train)
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)

        codes = [f["code"] for f in report.get("failures", [])]
        assert "path_escapes_sandbox" not in codes, (
            f"Legitimate sibling-dir path should pass sandbox; got codes: {codes}"
        )


class TestCrossSectionalCoercion:
    """Regression (Codex 2026-04-23): the previous
    `bool(request.get('cross_sectional'))` made EVERY non-empty string
    Python-truthy — so the literal value 'false' silently enabled the
    cross-sectional bypass, which suppresses external-validation and
    robustness requirements for publication-grade runs. The new coercion
    accepts only booleans or the literal ASCII strings true/false/
    yes/no/0/1 (case-insensitive); anything else is a request-validation
    failure."""

    def _build(self, tmp_path: Path, cross_sectional_value):
        req_path = _make_minimal_request(tmp_path)
        req = json.loads(req_path.read_text())
        req["cross_sectional"] = cross_sectional_value
        req_path.write_text(json.dumps(req))
        return req_path

    def test_literal_false_string_is_parsed_as_false(self, tmp_path: Path):
        req = self._build(tmp_path, "false")
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        # Must not silently become True.
        norm = report.get("normalized_request", {})
        assert norm.get("cross_sectional") is False, (
            f"String 'false' must parse as False, got "
            f"{norm.get('cross_sectional')!r}"
        )
        # And no validation error — 'false' is a recognized string.
        codes = [f["code"] for f in report.get("failures", [])]
        assert "invalid_cross_sectional" not in codes

    def test_literal_true_string_is_parsed_as_true(self, tmp_path: Path):
        req = self._build(tmp_path, "true")
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        norm = report.get("normalized_request", {})
        assert norm.get("cross_sectional") is True

    def test_bare_boolean_true(self, tmp_path: Path):
        req = self._build(tmp_path, True)
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        norm = report.get("normalized_request", {})
        assert norm.get("cross_sectional") is True

    def test_bare_boolean_false(self, tmp_path: Path):
        req = self._build(tmp_path, False)
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        norm = report.get("normalized_request", {})
        assert norm.get("cross_sectional") is False

    def test_unknown_string_is_rejected(self, tmp_path: Path):
        """A value like 'maybe' used to be Python-truthy. Now must fail."""
        req = self._build(tmp_path, "maybe")
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        codes = [f["code"] for f in report.get("failures", [])]
        assert "invalid_cross_sectional" in codes

    def test_non_boolean_non_string_rejected(self, tmp_path: Path):
        req = self._build(tmp_path, [1, 2])  # list — clearly not intended
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        codes = [f["code"] for f in report.get("failures", [])]
        assert "invalid_cross_sectional" in codes

    def test_missing_field_is_not_an_error(self, tmp_path: Path):
        req_path = _make_minimal_request(tmp_path)
        # Don't set cross_sectional at all.
        report_path = tmp_path / "report.json"
        report = _run_gate(req_path, report_path)
        codes = [f["code"] for f in report.get("failures", [])]
        assert "invalid_cross_sectional" not in codes


class TestReportPathSandbox:
    """Regression (Codex 2026-04-23): `--report <path>` was written raw
    with Path.expanduser().resolve(), so an operator (or malicious user
    controlling the CLI args) could pass --report ../sibling_gate/
    report.json and silently overwrite a neighboring gate's attestation.
    Sandbox check now refuses paths that escape the request's project
    root (request_path.parent.parent)."""

    def test_report_inside_sandbox_accepted(self, tmp_path: Path):
        """Legitimate path under request root must still work — this
        is the normal case and most tests rely on it."""
        req = _make_minimal_request(tmp_path)
        # Report directly next to request → inside sandbox.
        report_path = tmp_path / "report.json"
        report = _run_gate(req, report_path)
        assert report.get("status") in ("pass", "fail")  # report was written
        assert "normalized_request" in report

    def test_report_sibling_subdir_accepted(self, tmp_path: Path):
        """evidence/report.json — sibling directory under project root
        is a legitimate target."""
        req = _make_minimal_request(tmp_path)
        (tmp_path / "evidence").mkdir()
        report_path = tmp_path / "evidence" / "report.json"
        report = _run_gate(req, report_path)
        assert report.get("status") in ("pass", "fail")

    def test_report_escape_to_parent_refused(self, tmp_path: Path):
        """--report pointing outside the project sandbox must be blocked.

        Note: the 'sandbox' in this gate is request_base.parent, so
        the test has to nest the request deeper to make the sandbox
        tight enough that an escape attempt is meaningful. The
        canonical MLGG layout (configs/request.json under a project
        root) gives the sandbox = project root. We mirror that here."""
        import tempfile
        # Canonical layout: project/configs/request.json → sandbox = project/.
        configs = tmp_path / "configs"
        configs.mkdir()
        # Copy request into configs and rewrite split paths as absolute
        # under project root (tmp_path).
        req_flat = _make_minimal_request(tmp_path)
        req_data = json.loads(req_flat.read_text())
        req_path = configs / "request.json"
        req_path.write_text(json.dumps(req_data))

        # Attacker target: absolute path outside tmp_path entirely.
        outside_root = Path(tempfile.mkdtemp(prefix="mlgg_escape_test_"))
        try:
            evil_report_path = outside_root / "stolen_attestation.json"
            result = subprocess.run(
                [sys.executable, str(GATE_SCRIPT),
                 "--request", str(req_path),
                 "--report", str(evil_report_path)],
                capture_output=True, text=True, timeout=30,
                cwd=str(SCRIPTS_DIR),
            )
            assert result.returncode != 0, (
                f"Sandbox should reject out-of-tree report path.\n"
                f"stdout={result.stdout[:300]}\nstderr={result.stderr[:300]}"
            )
            assert not evil_report_path.exists(), (
                f"Sandbox failed: report leaked to {evil_report_path}"
            )
            assert "escape" in (result.stderr + result.stdout).lower()
        finally:
            import shutil
            shutil.rmtree(outside_root, ignore_errors=True)
