"""Unit tests for scripts/_gate_framework.py core functions."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch


from _gate_framework import (
    GateIssue,
    Severity,
    build_report_envelope,
    format_issue_line,
    get_remediation,
    register_remediation,
    register_remediations,
    validate_input_files,
    REPORT_ENVELOPE_VERSION,
)


# ────────────────────────────────────────────────────────
# Severity
# ────────────────────────────────────────────────────────

class TestSeverity:
    def test_values(self):
        assert Severity.CRITICAL.value == "critical"
        assert Severity.ERROR.value == "error"
        assert Severity.WARNING.value == "warning"
        assert Severity.INFO.value == "info"

    def test_rank_ordering(self):
        assert Severity.CRITICAL.rank < Severity.ERROR.rank
        assert Severity.ERROR.rank < Severity.WARNING.rank
        assert Severity.WARNING.rank < Severity.INFO.rank

    def test_lt_operator(self):
        assert Severity.CRITICAL < Severity.ERROR
        assert Severity.ERROR < Severity.WARNING
        assert not (Severity.INFO < Severity.WARNING)

    def test_lt_returns_not_implemented_for_non_severity(self):
        result = Severity.CRITICAL.__lt__("not_severity")
        assert result is NotImplemented


# ────────────────────────────────────────────────────────
# GateIssue
# ────────────────────────────────────────────────────────

class TestGateIssue:
    def test_basic_construction(self):
        issue = GateIssue(code="test_code", severity=Severity.ERROR, message="test msg")
        assert issue.code == "test_code"
        assert issue.severity == Severity.ERROR
        assert issue.message == "test msg"
        assert issue.details == {}
        assert issue.remediation is None
        assert issue.source_file is None

    def test_full_construction(self):
        issue = GateIssue(
            code="c", severity=Severity.WARNING, message="m",
            details={"k": 1}, remediation="fix it", source_file="foo.py",
        )
        assert issue.details == {"k": 1}
        assert issue.remediation == "fix it"
        assert issue.source_file == "foo.py"

    def test_to_dict_minimal(self):
        issue = GateIssue(code="c", severity=Severity.ERROR, message="m")
        d = issue.to_dict()
        assert d == {"code": "c", "severity": "error", "message": "m", "details": {}}
        assert "remediation" not in d
        assert "source_file" not in d

    def test_to_dict_with_remediation(self):
        issue = GateIssue(code="c", severity=Severity.ERROR, message="m", remediation="fix")
        d = issue.to_dict()
        assert d["remediation"] == "fix"

    def test_to_dict_with_source_file(self):
        issue = GateIssue(code="c", severity=Severity.ERROR, message="m", source_file="a.py")
        d = issue.to_dict()
        assert d["source_file"] == "a.py"

    def test_from_legacy_basic(self):
        legacy = {"code": "leak", "message": "found leak", "details": {"col": "id"}}
        issue = GateIssue.from_legacy(legacy, Severity.ERROR)
        assert issue.code == "leak"
        assert issue.severity == Severity.ERROR
        assert issue.message == "found leak"
        assert issue.details == {"col": "id"}

    def test_from_legacy_missing_fields(self):
        issue = GateIssue.from_legacy({}, Severity.WARNING)
        assert issue.code == "unknown"
        assert issue.message == ""
        assert issue.details == {}

    def test_from_legacy_non_dict_details(self):
        legacy = {"code": "c", "message": "m", "details": "not_a_dict"}
        issue = GateIssue.from_legacy(legacy, Severity.ERROR)
        assert issue.details == {}


# ────────────────────────────────────────────────────────
# Remediation registry
# ────────────────────────────────────────────────────────

class TestRemediationRegistry:
    def test_register_and_get(self):
        register_remediation("_test_unique_code_1", "hint_1")
        assert get_remediation("_test_unique_code_1") == "hint_1"

    def test_get_missing_returns_none(self):
        assert get_remediation("_nonexistent_code_xyz") is None

    def test_register_remediations_bulk(self):
        register_remediations({
            "_test_bulk_a": "hint_a",
            "_test_bulk_b": "hint_b",
        })
        assert get_remediation("_test_bulk_a") == "hint_a"
        assert get_remediation("_test_bulk_b") == "hint_b"

    def test_overwrite(self):
        register_remediation("_test_overwrite", "old")
        register_remediation("_test_overwrite", "new")
        assert get_remediation("_test_overwrite") == "new"


# ────────────────────────────────────────────────────────
# build_report_envelope
# ────────────────────────────────────────────────────────

class TestBuildReportEnvelope:
    def _make_issues(self, n_fail=1, n_warn=0):
        failures = [
            GateIssue(code=f"f{i}", severity=Severity.ERROR, message=f"fail {i}")
            for i in range(n_fail)
        ]
        warnings = [
            GateIssue(code=f"w{i}", severity=Severity.WARNING, message=f"warn {i}")
            for i in range(n_warn)
        ]
        return failures, warnings

    def test_basic_envelope_structure(self):
        fi, wi = self._make_issues(1, 1)
        env = build_report_envelope(
            gate_name="test_gate", status="fail", strict_mode=True,
            failures=fi, warnings=wi,
        )
        assert env["envelope_version"] == REPORT_ENVELOPE_VERSION
        assert env["gate_name"] == "test_gate"
        assert env["status"] == "fail"
        assert env["strict_mode"] is True
        assert env["failure_count"] == 1
        assert env["warning_count"] == 1
        assert "execution_timestamp_utc" in env
        assert "execution_time_seconds" in env
        assert len(env["failures"]) == 1
        assert len(env["warnings"]) == 1

    def test_envelope_with_summary(self):
        fi, wi = self._make_issues(0, 0)
        env = build_report_envelope(
            gate_name="g", status="pass", strict_mode=False,
            failures=fi, warnings=wi,
            summary={"key": "val"},
        )
        assert env["summary"] == {"key": "val"}

    def test_envelope_without_summary(self):
        fi, wi = self._make_issues(0, 0)
        env = build_report_envelope(
            gate_name="g", status="pass", strict_mode=False,
            failures=fi, warnings=wi,
        )
        assert "summary" not in env

    def test_envelope_with_input_files(self):
        fi, wi = self._make_issues(0, 0)
        env = build_report_envelope(
            gate_name="g", status="pass", strict_mode=False,
            failures=fi, warnings=wi,
            input_files={"train": "/data/train.csv"},
        )
        assert env["input_files"] == {"train": "/data/train.csv"}

    def test_envelope_empty_input_files_not_included(self):
        fi, wi = self._make_issues(0, 0)
        env = build_report_envelope(
            gate_name="g", status="pass", strict_mode=False,
            failures=fi, warnings=wi,
            input_files={},
        )
        assert "input_files" not in env

    def test_envelope_extra_merges_to_top_level(self):
        fi, wi = self._make_issues(0, 0)
        env = build_report_envelope(
            gate_name="g", status="pass", strict_mode=False,
            failures=fi, warnings=wi,
            extra={"normalized_request": {"study_id": "s1"}},
        )
        assert env["normalized_request"] == {"study_id": "s1"}

    def test_envelope_gate_version(self):
        fi, wi = self._make_issues(0, 0)
        env = build_report_envelope(
            gate_name="g", status="pass", strict_mode=False,
            failures=fi, warnings=wi,
            gate_version="2.0.0",
        )
        assert env["gate_version"] == "2.0.0"

    def test_failures_sorted_by_severity(self):
        fi = [
            GateIssue(code="warn_level", severity=Severity.ERROR, message="e"),
            GateIssue(code="crit_level", severity=Severity.CRITICAL, message="c"),
        ]
        env = build_report_envelope(
            gate_name="g", status="fail", strict_mode=True,
            failures=fi, warnings=[],
        )
        assert env["failures"][0]["severity"] == "critical"
        assert env["failures"][1]["severity"] == "error"


# ────────────────────────────────────────────────────────


class TestPeerReviewRetrievalDegradation:
    """Regression: a malformed peer-review-kb must not propagate any
    exception out of build_report_envelope(). The gate's exit code
    contract is 0/2 — an uncaught exception → exit 1 breaks the contract.
    """

    def _make_issues(self, fails: int):
        return [GateIssue(code=f"c{i}", message=f"m{i}", severity=Severity.ERROR)
                for i in range(fails)]

    def test_malformed_kb_does_not_crash_envelope(self, tmp_path, monkeypatch):
        # Point the retrieval module's default KB at a broken file.
        import _peer_review_retrieval as prr
        bad_kb = tmp_path / "peer-review-kb.json"
        bad_kb.write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(prr, "_KB_PATH", bad_kb)
        prr.clear_cache()

        fi = self._make_issues(1)
        env = build_report_envelope(
            gate_name="leakage_gate", status="fail", strict_mode=False,
            failures=fi, warnings=[],
        )
        # Must have landed in the error branch, not propagated.
        assert env["peer_review_context"] == []
        assert env["peer_review_status"].startswith("kb_error:") or \
            env["peer_review_status"] == "kb_unavailable"

    def test_kb_missing_does_not_crash_envelope(self, tmp_path, monkeypatch):
        import _peer_review_retrieval as prr
        monkeypatch.setattr(prr, "_KB_PATH", tmp_path / "does_not_exist.json")
        prr.clear_cache()
        fi = self._make_issues(1)
        env = build_report_envelope(
            gate_name="leakage_gate", status="fail", strict_mode=False,
            failures=fi, warnings=[],
        )
        assert env["peer_review_context"] == []
        assert env["peer_review_status"] == "kb_unavailable"


# ────────────────────────────────────────────────────────
# validate_input_files
# ────────────────────────────────────────────────────────

class TestValidateInputFiles:
    def test_existing_file_no_issues(self, tmp_path):
        f = tmp_path / "data.csv"
        f.write_text("a,b\n1,2\n")
        import argparse
        args = argparse.Namespace(data=str(f))
        issues = validate_input_files(args, ["--data"])
        assert len(issues) == 0

    def test_missing_file_produces_critical(self, tmp_path):
        import argparse
        args = argparse.Namespace(data=str(tmp_path / "nonexistent.csv"))
        issues = validate_input_files(args, ["--data"])
        assert len(issues) == 1
        assert issues[0].code == "file_not_found"
        assert issues[0].severity == Severity.CRITICAL

    def test_directory_produces_not_file(self, tmp_path):
        import argparse
        args = argparse.Namespace(data=str(tmp_path))
        issues = validate_input_files(args, ["--data"])
        assert len(issues) == 1
        assert issues[0].code == "path_not_file"

    def test_none_arg_skipped(self):
        import argparse
        args = argparse.Namespace(data=None)
        issues = validate_input_files(args, ["--data"])
        assert len(issues) == 0


# ────────────────────────────────────────────────────────
# format_issue_line
# ────────────────────────────────────────────────────────

class TestFormatIssueLine:
    def test_basic_format(self):
        issue = GateIssue(code="c", severity=Severity.ERROR, message="m")
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            line = format_issue_line(issue)
        assert "[FAIL]" in line
        assert "c: m" in line

    def test_with_remediation(self):
        issue = GateIssue(code="c", severity=Severity.WARNING, message="m", remediation="do X")
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            line = format_issue_line(issue)
        assert "Fix: do X" in line


# ────────────────────────────────────────────────────────


# ────────────────────────────────────────────────────────
# ────────────────────────────────────────────────────────


class TestFormatIssueLineExtended:
    def test_error_issue_contains_code_and_message(self):
        issue = GateIssue(code="bad_input", severity=Severity.ERROR, message="File is invalid")
        line = format_issue_line(issue)
        assert "bad_input" in line
        assert "File is invalid" in line

    def test_warning_issue_formatted(self):
        issue = GateIssue(code="low_n", severity=Severity.WARNING, message="Sample too small")
        line = format_issue_line(issue)
        assert "low_n" in line
        assert "Sample too small" in line

    def test_details_appended(self):
        issue = GateIssue(
            code="threshold_exceeded",
            severity=Severity.ERROR,
            message="Over limit",
            details={"value": 0.95, "threshold": 0.5},
        )
        line = format_issue_line(issue)
        assert "threshold_exceeded" in line
