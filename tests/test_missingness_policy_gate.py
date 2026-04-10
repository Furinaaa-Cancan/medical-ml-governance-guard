"""Comprehensive unit tests for scripts/missingness_policy_gate.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from missingness_policy_gate import (
    is_missing,
    parse_ignore_cols,
    read_missing_stats,
    require_bool,
    require_number,
    require_str,
    require_str_list,
    validate_ratio_field,
)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"


# ────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────

def _write_csv(path: Path, headers: list, rows: list) -> Path:
    lines = [",".join(headers)]
    for row in rows:
        lines.append(",".join(str(v) for v in row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _good_policy():
    return {
        "strategy": "simple",
        "imputer_fit_scope": "train_only",
        "add_missing_indicators": False,
        "complete_case_analysis": False,
        "forbid_test_usage": True,
        "test_used_for_fit": False,
        "valid_used_for_fit": False,
        "use_target_in_imputation": False,
        "max_feature_missing_ratio": 0.6,
        "min_non_missing_per_feature": 2,
        "indicator_required_above_ratio": 0.9,
        "missingness_drift_tolerance": 0.2,
    }


def _make_setup(tmp_path, policy=None, train_data=None, test_data=None, valid_data=None):
    if policy is None:
        policy = _good_policy()
    headers = ["patient_id", "y", "age", "bp"]
    if train_data is None:
        train_data = [["P1", "0", "30", "120"], ["P2", "1", "40", "130"],
                      ["P3", "0", "50", "115"], ["P4", "1", "60", "110"],
                      ["P5", "0", "35", "125"], ["P6", "1", "45", "135"],
                      ["P7", "0", "55", "105"], ["P8", "1", "65", "140"]]
    if test_data is None:
        test_data = [["P5", "0", "35", "125"], ["P6", "1", "45", "135"]]

    spec_path = _write_json(tmp_path / "policy.json", policy)
    train_path = _write_csv(tmp_path / "train.csv", headers, train_data)
    test_path = _write_csv(tmp_path / "test.csv", headers, test_data)
    paths = {"spec": spec_path, "train": train_path, "test": test_path}
    if valid_data is not None:
        paths["valid"] = _write_csv(tmp_path / "valid.csv", headers, valid_data)
    return paths


# ────────────────────────────────────────────────────────
# is_missing
# ────────────────────────────────────────────────────────

class TestIsMissing:
    def test_empty(self):
        assert is_missing("") is True

    def test_na(self):
        assert is_missing("NA") is True
        assert is_missing("na") is True

    def test_nan(self):
        assert is_missing("NaN") is True
        assert is_missing("nan") is True

    def test_null(self):
        assert is_missing("null") is True
        assert is_missing("NULL") is True

    def test_none_str(self):
        assert is_missing("None") is True
        assert is_missing("none") is True

    def test_n_a(self):
        assert is_missing("N/A") is True

    def test_question(self):
        assert is_missing("?") is True

    def test_normal_value(self):
        assert is_missing("42") is False
        assert is_missing("hello") is False

    def test_whitespace_around(self):
        assert is_missing("  NA  ") is True
        assert is_missing("  42  ") is False


# ────────────────────────────────────────────────────────
# parse_ignore_cols
# ────────────────────────────────────────────────────────

class TestParseIgnoreCols:
    def test_normal(self):
        result = parse_ignore_cols("patient_id,event_time", "y")
        assert result == {"patient_id", "event_time", "y"}

    def test_empty(self):
        result = parse_ignore_cols("", "y")
        assert result == {"y"}

    def test_whitespace(self):
        result = parse_ignore_cols(" a , b ", "y")
        assert "a" in result and "b" in result


# ────────────────────────────────────────────────────────
# read_missing_stats
# ────────────────────────────────────────────────────────

class TestReadMissingStats:
    def test_normal(self, tmp_path: Path):
        p = _write_csv(tmp_path / "d.csv", ["y", "a"], [["0", "1"], ["1", ""], ["0", "NA"]])
        stats = read_missing_stats(str(p), "train", "y")
        assert stats["row_count"] == 3
        assert stats["missing_by_col"]["a"] == 2  # "" and "NA"
        assert stats["missing_by_col"]["y"] == 0
        assert stats["target_missing_count"] == 0

    def test_target_missing(self, tmp_path: Path):
        p = _write_csv(tmp_path / "d.csv", ["y", "a"], [["", "1"], ["1", "2"]])
        stats = read_missing_stats(str(p), "train", "y")
        assert stats["target_missing_count"] == 1

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            read_missing_stats("/nonexistent.csv", "train", "y")

    def test_missing_target_col(self, tmp_path: Path):
        p = _write_csv(tmp_path / "d.csv", ["a", "b"], [["1", "2"]])
        with pytest.raises(ValueError, match="missing target_col"):
            read_missing_stats(str(p), "train", "y")


# ────────────────────────────────────────────────────────
# require_str / require_bool / require_number / require_str_list
# ────────────────────────────────────────────────────────

class TestRequireStr:
    def test_normal(self):
        f = []
        assert require_str({"k": "val"}, "k", f) == "val"

    def test_missing(self):
        f = []
        assert require_str({}, "k", f) is None
        assert len(f) == 1


class TestRequireBool:
    def test_true(self):
        f = []
        assert require_bool({"k": True}, "k", f) is True

    def test_missing_default(self):
        f = []
        assert require_bool({}, "k", f, default=False) is False
        assert f == []

    def test_not_bool(self):
        f = []
        assert require_bool({"k": "yes"}, "k", f) is None
        assert len(f) == 1


class TestRequireNumber:
    def test_normal(self):
        f = []
        assert require_number({"k": 5.0}, "k", f) == 5.0

    def test_bool_rejected(self):
        f = []
        require_number({"k": True}, "k", f, default=0.0)
        assert len(f) == 1

    def test_inf_rejected(self):
        f = []
        result = require_number({"k": float("inf")}, "k", f, default=0.0)
        assert result == 0.0
        assert len(f) == 1


class TestRequireStrList:
    def test_normal(self):
        f = []
        assert require_str_list({"k": ["a", "b"]}, "k", f) == ["a", "b"]

    def test_missing_default(self):
        f = []
        assert require_str_list({}, "k", f, default=["x"]) == ["x"]

    def test_not_list(self):
        f = []
        assert require_str_list({"k": "not_list"}, "k", f) == []
        assert len(f) == 1

    def test_empty_string_item(self):
        f = []
        require_str_list({"k": ["a", ""]}, "k", f)
        assert len(f) == 1


# ────────────────────────────────────────────────────────
# validate_ratio_field
# ────────────────────────────────────────────────────────

class TestValidateRatioField:
    def test_in_range(self):
        f = []
        validate_ratio_field("k", 0.5, f)
        assert f == []

    def test_out_of_range(self):
        f = []
        validate_ratio_field("k", 1.5, f)
        assert len(f) == 1

    def test_none(self):
        f = []
        validate_ratio_field("k", None, f)
        assert f == []


# ────────────────────────────────────────────────────────
# CLI tests
# ────────────────────────────────────────────────────────

class TestCLI:
    def _run(self, tmp_path, setup, extra_args=None):
        cmd = [
            sys.executable, str(SCRIPTS_DIR / "gates/missingness_policy_gate.py"),
            "--policy-spec", str(setup["spec"]),
            "--train", str(setup["train"]),
            "--test", str(setup["test"]),
            "--report", str(tmp_path / "report.json"),
            "--ignore-cols", "patient_id",
        ]
        if "valid" in setup:
            cmd.extend(["--valid", str(setup["valid"])])
        if extra_args:
            cmd.extend(extra_args)
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30)

    def test_pass(self, tmp_path: Path):
        setup = _make_setup(tmp_path)
        result = self._run(tmp_path, setup)
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        report = json.loads((tmp_path / "report.json").read_text())
        assert report["status"] == "pass"

    def test_missing_policy_spec(self, tmp_path: Path):
        train_path = _write_csv(tmp_path / "train.csv", ["y", "a"], [["0", "1"]])
        test_path = _write_csv(tmp_path / "test.csv", ["y", "a"], [["1", "2"]])
        setup = {"spec": tmp_path / "nonexistent.json", "train": train_path, "test": test_path}
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "missing_policy_spec" in codes

    def test_invalid_policy_json(self, tmp_path: Path):
        spec_path = tmp_path / "bad.json"
        spec_path.write_text("{bad", encoding="utf-8")
        train_path = _write_csv(tmp_path / "train.csv", ["y", "a"], [["0", "1"]])
        test_path = _write_csv(tmp_path / "test.csv", ["y", "a"], [["1", "2"]])
        setup = {"spec": spec_path, "train": train_path, "test": test_path}
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_policy_spec" in codes

    def test_invalid_strategy(self, tmp_path: Path):
        policy = _good_policy()
        policy["strategy"] = "unknown_method"
        setup = _make_setup(tmp_path, policy=policy)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "unsupported_missingness_strategy" in codes

    def test_invalid_imputer_fit_scope(self, tmp_path: Path):
        policy = _good_policy()
        policy["imputer_fit_scope"] = "all_splits"
        setup = _make_setup(tmp_path, policy=policy)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_imputer_fit_scope" in codes

    def test_target_used_in_imputation(self, tmp_path: Path):
        policy = _good_policy()
        policy["use_target_in_imputation"] = True
        setup = _make_setup(tmp_path, policy=policy)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "target_used_in_imputation" in codes

    def test_test_used_for_fit(self, tmp_path: Path):
        policy = _good_policy()
        policy["test_used_for_fit"] = True
        setup = _make_setup(tmp_path, policy=policy)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "test_used_for_imputer_fit" in codes

    def test_forbid_test_false(self, tmp_path: Path):
        policy = _good_policy()
        policy["forbid_test_usage"] = False
        setup = _make_setup(tmp_path, policy=policy)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "test_usage_not_forbidden" in codes

    def test_target_missing_values(self, tmp_path: Path):
        setup = _make_setup(
            tmp_path,
            train_data=[["P1", "", "30", "120"], ["P2", "1", "40", "130"]],
        )
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "target_missing_values" in codes

    def test_feature_missingness_too_high(self, tmp_path: Path):
        policy = _good_policy()
        policy["max_feature_missing_ratio"] = 0.3
        # 3 out of 4 bp values missing = 75% > 30%
        setup = _make_setup(
            tmp_path, policy=policy,
            train_data=[["P1", "0", "30", ""], ["P2", "1", "40", ""],
                        ["P3", "0", "50", ""], ["P4", "1", "60", "110"]],
        )
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "feature_missingness_too_high" in codes

    def test_missingness_unhandled(self, tmp_path: Path):
        policy = _good_policy()
        policy["strategy"] = "none"
        setup = _make_setup(
            tmp_path, policy=policy,
            train_data=[["P1", "0", "30", ""], ["P2", "1", "40", "130"]],
        )
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "missingness_unhandled" in codes

    def test_none_with_complete_case_pass(self, tmp_path: Path):
        policy = _good_policy()
        policy["strategy"] = "none"
        policy["complete_case_analysis"] = True
        setup = _make_setup(
            tmp_path, policy=policy,
            train_data=[["P1", "0", "30", ""], ["P2", "1", "40", "130"]],
        )
        self._run(tmp_path, setup)
        # complete_case_analysis=True bypasses missingness_unhandled
        report = json.loads((tmp_path / "report.json").read_text())
        fail_codes = [f["code"] for f in report["failures"]]
        assert "missingness_unhandled" not in fail_codes

    def test_simple_with_indicator_requires_flag(self, tmp_path: Path):
        policy = _good_policy()
        policy["strategy"] = "simple_with_indicator"
        policy["add_missing_indicators"] = False
        setup = _make_setup(tmp_path, policy=policy)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "indicator_flag_required" in codes

    def test_valid_used_for_fit_warning(self, tmp_path: Path):
        policy = _good_policy()
        policy["valid_used_for_fit"] = True
        setup = _make_setup(tmp_path, policy=policy)
        self._run(tmp_path, setup)
        report = json.loads((tmp_path / "report.json").read_text())
        warn_codes = [w["code"] for w in report["warnings"]]
        assert "valid_used_for_imputer_fit" in warn_codes

    def test_report_structure(self, tmp_path: Path):
        setup = _make_setup(tmp_path)
        self._run(tmp_path, setup)
        report = json.loads((tmp_path / "report.json").read_text())
        assert "status" in report
        assert "strict_mode" in report
        assert "strategy" in report["summary"]
        assert "policy_spec" in report.get("input_files", {})
        assert "failure_count" in report
        assert "warning_count" in report
        assert "summary" in report
        assert "splits" in report["summary"]
        assert "ignored_columns" in report["summary"]

    def test_mice_row_scale_exceeded(self, tmp_path: Path):
        policy = _good_policy()
        policy["strategy"] = "mice"
        policy["mice_max_rows"] = 2  # Very low threshold
        setup = _make_setup(tmp_path, policy=policy)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "mice_row_scale_exceeded" in codes

    def test_mice_with_scale_guard_missing_evidence(self, tmp_path: Path):
        policy = _good_policy()
        policy["strategy"] = "mice_with_scale_guard"
        # No scale_guard_evidence
        setup = _make_setup(tmp_path, policy=policy)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "mice_scale_guard_violation" in codes

    # ── Mechanism assessment enforcement ──────────────────────────

    def _make_missing_setup(self, tmp_path, policy=None, miss_ratio=0.25):
        """Create train/test with controlled missingness ratio on 'bp' column."""
        if policy is None:
            policy = _good_policy()
        headers = ["patient_id", "y", "age", "bp"]
        n = 20
        n_miss = max(1, int(n * miss_ratio))
        train_data = []
        for i in range(n):
            bp = "" if i < n_miss else str(120 + i)
            train_data.append([f"P{i}", str(i % 2), str(30 + i), bp])
        test_data = [["T1", "0", "35", "125"], ["T2", "1", "45", "135"]]
        return _make_setup(tmp_path, policy=policy, train_data=train_data, test_data=test_data)

    def test_mechanism_assessment_required_above_5pct(self, tmp_path: Path):
        """miss >5% without mechanism_assessment → failure."""
        policy = _good_policy()
        # No mechanism_assessment key
        setup = self._make_missing_setup(tmp_path, policy=policy, miss_ratio=0.10)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "mechanism_assessment_required" in codes

    def test_mechanism_assessment_not_required_below_5pct(self, tmp_path: Path):
        """miss <5% → no mechanism_assessment needed."""
        policy = _good_policy()
        setup = self._make_missing_setup(tmp_path, policy=policy, miss_ratio=0.0)
        result = self._run(tmp_path, setup)
        assert result.returncode == 0

    def test_mechanism_assessment_valid_passes(self, tmp_path: Path):
        """Valid mechanism_assessment with >5% miss → pass."""
        policy = _good_policy()
        policy["mechanism_assessment"] = {
            "method": "Little's MCAR test + logistic regression for MAR",
            "conclusion": "mar",
        }
        setup = self._make_missing_setup(tmp_path, policy=policy, miss_ratio=0.10)
        result = self._run(tmp_path, setup)
        assert result.returncode == 0

    def test_mechanism_assessment_missing_method(self, tmp_path: Path):
        """mechanism_assessment without method → failure."""
        policy = _good_policy()
        policy["mechanism_assessment"] = {"conclusion": "mar"}
        setup = self._make_missing_setup(tmp_path, policy=policy, miss_ratio=0.10)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "mechanism_assessment_invalid" in codes

    def test_mechanism_assessment_bad_conclusion(self, tmp_path: Path):
        """mechanism_assessment with invalid conclusion → failure."""
        policy = _good_policy()
        policy["mechanism_assessment"] = {
            "method": "Little's MCAR test",
            "conclusion": "random",  # not valid
        }
        setup = self._make_missing_setup(tmp_path, policy=policy, miss_ratio=0.10)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "mechanism_assessment_invalid" in codes

    def test_mnar_sensitivity_required_above_40pct(self, tmp_path: Path):
        """miss >40% without mnar_sensitivity → failure."""
        policy = _good_policy()
        policy["mechanism_assessment"] = {
            "method": "Little's MCAR test",
            "conclusion": "mnar",
        }
        # No mnar_sensitivity
        setup = self._make_missing_setup(tmp_path, policy=policy, miss_ratio=0.50)
        result = self._run(tmp_path, setup)
        assert result.returncode == 2
        report = json.loads((tmp_path / "report.json").read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "mnar_sensitivity_required" in codes

    def test_mnar_sensitivity_valid_passes(self, tmp_path: Path):
        """Valid mnar_sensitivity with >40% miss → pass."""
        policy = _good_policy()
        policy["mechanism_assessment"] = {
            "method": "Little's MCAR test + logistic regression",
            "conclusion": "mnar",
        }
        policy["mnar_sensitivity"] = {
            "performed": True,
            "tipping_point": -0.3,
            "metric": "pr_auc",
            "baseline_score": 0.72,
        }
        setup = self._make_missing_setup(tmp_path, policy=policy, miss_ratio=0.50)
        result = self._run(tmp_path, setup)
        assert result.returncode == 0

    def test_mnar_sensitivity_not_required_below_40pct(self, tmp_path: Path):
        """miss 10% with mechanism_assessment → no mnar_sensitivity needed."""
        policy = _good_policy()
        policy["mechanism_assessment"] = {
            "method": "Little's MCAR test",
            "conclusion": "mar",
        }
        setup = self._make_missing_setup(tmp_path, policy=policy, miss_ratio=0.10)
        result = self._run(tmp_path, setup)
        assert result.returncode == 0
