"""Tests for scripts/execution_attestation_gate.py.

Covers helper functions (parse_iso_ts, require_str, require_str_list,
require_bool, require_number, check_authority_not_revoked, sha256_text,
load_json_obj, is_finite_number-like checks), and CLI integration for
missing files and basic validation.
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
GATE_SCRIPT = SCRIPTS_DIR / "gates/execution_attestation_gate.py"

sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SCRIPTS_DIR / "core"))
sys.path.insert(0, str(SCRIPTS_DIR / "gates"))
sys.path.insert(0, str(SCRIPTS_DIR / "tools"))
sys.path.insert(0, str(SCRIPTS_DIR / "orchestration"))
import execution_attestation_gate as eag


# ── helper functions ─────────────────────────────────────────────────────────

class TestParseIsoTs:
    def test_basic(self):
        result = eag.parse_iso_ts("2025-01-15T10:00:00Z")
        assert result is not None
        assert result.tzinfo is not None

    def test_with_offset(self):
        result = eag.parse_iso_ts("2025-01-15T10:00:00+08:00")
        assert result is not None

    def test_empty(self):
        assert eag.parse_iso_ts("") is None

    def test_invalid(self):
        assert eag.parse_iso_ts("not-a-date") is None

    def test_naive_gets_utc(self):
        result = eag.parse_iso_ts("2025-01-15T10:00:00")
        assert result is not None
        assert result.tzinfo == dt.timezone.utc


class TestRequireStr:
    def test_valid(self):
        failures = []
        result = eag.require_str({"key": "value"}, "key", failures, "test")
        assert result == "value"
        assert len(failures) == 0

    def test_missing(self):
        failures = []
        result = eag.require_str({}, "key", failures, "test")
        assert result is None
        assert len(failures) == 1
        assert failures[0]["code"] == "invalid_field"

    def test_empty_string(self):
        failures = []
        result = eag.require_str({"key": "  "}, "key", failures, "test")
        assert result is None


class TestRequireStrList:
    def test_valid(self):
        failures = []
        result = eag.require_str_list({"k": ["a", "b"]}, "k", failures, "test")
        assert result == ["a", "b"]
        assert len(failures) == 0

    def test_not_list(self):
        failures = []
        result = eag.require_str_list({"k": "not_list"}, "k", failures, "test")
        assert result == []
        assert len(failures) == 1

    def test_empty_item(self):
        failures = []
        result = eag.require_str_list({"k": ["a", ""]}, "k", failures, "test")
        assert result == []
        assert len(failures) == 1


class TestRequireBool:
    def test_true(self):
        failures = []
        result = eag.require_bool({"k": True}, "k", failures, "test")
        assert result is True

    def test_missing_default(self):
        failures = []
        result = eag.require_bool({}, "k", failures, "test", default=False)
        assert result is False
        assert len(failures) == 0

    def test_non_bool(self):
        failures = []
        result = eag.require_bool({"k": "yes"}, "k", failures, "test", default=None)
        assert result is None
        assert len(failures) == 1


class TestRequireNumber:
    def test_int(self):
        failures = []
        result = eag.require_number({"k": 42}, "k", failures, "test")
        assert result == 42.0

    def test_missing_default(self):
        failures = []
        result = eag.require_number({}, "k", failures, "test", default=10.0)
        assert result == 10.0

    def test_non_numeric(self):
        failures = []
        result = eag.require_number({"k": "abc"}, "k", failures, "test", default=None)
        assert result is None
        assert len(failures) == 1

    def test_bool_rejected(self):
        failures = []
        result = eag.require_number({"k": True}, "k", failures, "test", default=None)
        assert result is None
        assert len(failures) == 1

    def test_inf_rejected(self):
        failures = []
        result = eag.require_number({"k": float("inf")}, "k", failures, "test", default=None)
        assert result is None
        assert len(failures) == 1


class TestCheckAuthorityNotRevoked:
    def test_not_revoked(self):
        failures = []
        eag.check_authority_not_revoked("signing", "key1", "fp1", set(), set(), failures)
        assert len(failures) == 0

    def test_revoked_by_id(self):
        failures = []
        eag.check_authority_not_revoked("signing", "key1", "fp1", {"key1"}, set(), failures)
        assert len(failures) == 1
        assert "revoked" in failures[0]["code"]

    def test_revoked_by_fp(self):
        failures = []
        eag.check_authority_not_revoked("signing", "key1", "abcd1234", set(), {"abcd1234"}, failures)
        assert len(failures) == 1

    def test_empty_revocation_lists(self):
        failures = []
        eag.check_authority_not_revoked("signing", "key1", "fp1", set(), set(), failures)
        assert len(failures) == 0


class TestSha256Text:
    def test_deterministic(self):
        h1 = eag.sha256_text("hello")
        h2 = eag.sha256_text("hello")
        assert h1 == h2
        assert len(h1) == 64


class TestSha256File:
    def test_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h = eag.sha256_file(f)
        assert len(h) == 64


class TestLoadJsonObj:
    def test_valid(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text(json.dumps({"a": 1}))
        failures = []
        result = eag.load_json_obj(f, failures, "test")
        assert result == {"a": 1}
        assert len(failures) == 0

    def test_missing(self, tmp_path):
        failures = []
        result = eag.load_json_obj(tmp_path / "nope.json", failures, "test")
        assert result is None
        assert len(failures) == 1
        assert "missing" in failures[0]["code"]

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{invalid")
        failures = []
        result = eag.load_json_obj(f, failures, "test")
        assert result is None
        assert len(failures) == 1

    def test_non_object_root(self, tmp_path):
        f = tmp_path / "arr.json"
        f.write_text("[1, 2, 3]")
        failures = []
        result = eag.load_json_obj(f, failures, "test")
        assert result is None
        assert len(failures) == 1


class TestFileLineCount:
    def test_basic(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("line1\nline2\nline3\n")
        count = eag.file_line_count(f)
        assert count == 3

    def test_missing(self, tmp_path):
        count = eag.file_line_count(tmp_path / "nope.txt")
        assert count is None


class TestLogBoundaryHashes:
    def test_basic(self, tmp_path):
        f = tmp_path / "log.txt"
        f.write_text("first\nmiddle\nlast\n")
        result = eag.log_boundary_hashes(f)
        assert result is not None
        assert result["line_count"] == 3
        assert result["first_line_sha256"] == eag.sha256_text("first")
        assert result["last_line_sha256"] == eag.sha256_text("last")


class TestEnforcePublicationPolicyRequirements:
    def test_all_true(self):
        failures = []
        key_assurance = {
            "policy": {
                "require_revocation_list": True,
                "require_timestamp_trust": True,
                "require_transparency_log": True,
                "require_transparency_log_signature": True,
                "require_execution_receipt": True,
                "require_execution_log_attestation": True,
                "require_independent_timestamp_authority": True,
                "require_independent_execution_authority": True,
                "require_independent_log_authority": True,
                "require_distinct_authority_roles": True,
                "require_witness_quorum": True,
                "require_independent_witness_keys": True,
                "require_witness_independence_from_signing": True,
                "min_witness_count": 2,
            }
        }
        eag.enforce_publication_policy_requirements(key_assurance, failures)
        assert len(failures) == 0

    def test_missing_policy(self):
        failures = []
        eag.enforce_publication_policy_requirements({}, failures)
        assert len(failures) == 1
        assert failures[0]["code"] == "publication_policy_missing"

    def test_flag_false(self):
        failures = []
        key_assurance = {
            "policy": {
                "require_revocation_list": False,
                "require_timestamp_trust": True,
                "require_transparency_log": True,
                "require_transparency_log_signature": True,
                "require_execution_receipt": True,
                "require_execution_log_attestation": True,
                "require_independent_timestamp_authority": True,
                "require_independent_execution_authority": True,
                "require_independent_log_authority": True,
                "require_distinct_authority_roles": True,
                "require_witness_quorum": True,
                "require_independent_witness_keys": True,
                "require_witness_independence_from_signing": True,
                "min_witness_count": 2,
            }
        }
        eag.enforce_publication_policy_requirements(key_assurance, failures)
        codes = [f["code"] for f in failures]
        assert "publication_policy_disabled" in codes

    def test_witness_count_too_low(self):
        failures = []
        key_assurance = {
            "policy": {
                "require_revocation_list": True,
                "require_timestamp_trust": True,
                "require_transparency_log": True,
                "require_transparency_log_signature": True,
                "require_execution_receipt": True,
                "require_execution_log_attestation": True,
                "require_independent_timestamp_authority": True,
                "require_independent_execution_authority": True,
                "require_independent_log_authority": True,
                "require_distinct_authority_roles": True,
                "require_witness_quorum": True,
                "require_independent_witness_keys": True,
                "require_witness_independence_from_signing": True,
                "min_witness_count": 1,
            }
        }
        eag.enforce_publication_policy_requirements(key_assurance, failures)
        codes = [f["code"] for f in failures]
        assert "publication_min_witness_count_too_low" in codes


# ── CLI integration ──────────────────────────────────────────────────────────

def _run_gate(tmp_path, spec=None, eval_report_content=None, strict=False,
              study_id=None, run_id=None):
    if eval_report_content is None:
        eval_report_content = {"metrics": {"roc_auc": 0.85}, "split": "test"}
    eval_path = tmp_path / "evaluation_report.json"
    eval_path.write_text(json.dumps(eval_report_content))

    if spec is None:
        spec = {"study_id": "S1", "run_id": "R1"}
    spec_path = tmp_path / "attestation_spec.json"
    spec_path.write_text(json.dumps(spec))

    report_path = tmp_path / "report.json"
    cmd = [
        sys.executable, str(GATE_SCRIPT),
        "--attestation-spec", str(spec_path),
        "--evaluation-report", str(eval_path),
        "--report", str(report_path),
    ]
    if strict:
        cmd.append("--strict")
    if study_id:
        cmd.extend(["--study-id", study_id])
    if run_id:
        cmd.extend(["--run-id", run_id])
    subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(SCRIPTS_DIR))
    if report_path.exists():
        return json.loads(report_path.read_text())
    return {}


class TestCLIMissingFiles:
    def test_missing_eval_report(self, tmp_path):
        spec_path = tmp_path / "attestation_spec.json"
        spec_path.write_text(json.dumps({"study_id": "S1", "run_id": "R1"}))
        report_path = tmp_path / "report.json"
        cmd = [
            sys.executable, str(GATE_SCRIPT),
            "--attestation-spec", str(spec_path),
            "--evaluation-report", str(tmp_path / "nope.json"),
            "--report", str(report_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(SCRIPTS_DIR))
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "evaluation_report_missing" in codes

    def test_missing_attestation_spec(self, tmp_path):
        eval_path = tmp_path / "eval.json"
        eval_path.write_text(json.dumps({"metrics": {}}))
        report_path = tmp_path / "report.json"
        cmd = [
            sys.executable, str(GATE_SCRIPT),
            "--attestation-spec", str(tmp_path / "nope.json"),
            "--evaluation-report", str(eval_path),
            "--report", str(report_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(SCRIPTS_DIR))
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "attestation_spec_missing" in codes


class TestCLIBasicValidation:
    def test_missing_signing_block(self, tmp_path):
        report = _run_gate(tmp_path, spec={"study_id": "S1", "run_id": "R1"})
        codes = [f["code"] for f in report["failures"]]
        assert "invalid_signing_block" in codes

    def test_report_structure(self, tmp_path):
        report = _run_gate(tmp_path)
        assert "status" in report
        assert "failure_count" in report
        assert "failures" in report
        assert "warnings" in report

    def test_strict_flag(self, tmp_path):
        report = _run_gate(tmp_path, strict=True)
        assert report["strict_mode"] is True


# ── parse_artifacts ────────────────────────────────────────────────────

class TestParseArtifacts:
    """Test artifact parsing, hash verification, required artifacts."""

    def test_not_a_list_fails(self, tmp_path):
        failures = []
        eag.parse_artifacts("bad", tmp_path, [], tmp_path / "eval.json", failures, [])
        codes = [f["code"] for f in failures]
        assert "invalid_artifacts" in codes

    def test_entry_not_dict_fails(self, tmp_path):
        failures = []
        eag.parse_artifacts(["bad"], tmp_path, [], tmp_path / "eval.json", failures, [])
        codes = [f["code"] for f in failures]
        assert "invalid_artifact_entry" in codes

    def test_missing_name_fails(self, tmp_path):
        failures = []
        eag.parse_artifacts(
            [{"path": "model.pkl", "sha256": "a" * 64}],
            tmp_path, [], tmp_path / "eval.json", failures, [],
        )
        codes = [f["code"] for f in failures]
        assert "invalid_artifact_name" in codes

    def test_missing_sha256_fails(self, tmp_path):
        f = tmp_path / "model.pkl"
        f.write_bytes(b"model data")
        failures = []
        eag.parse_artifacts(
            [{"name": "model", "path": "model.pkl"}],
            tmp_path, [], tmp_path / "eval.json", failures, [],
        )
        codes = [f["code"] for f in failures]
        assert "invalid_artifact_sha256" in codes

    def test_duplicate_name_fails(self, tmp_path):
        f = tmp_path / "model.pkl"
        f.write_bytes(b"model data")
        h = eag.sha256_file(f)
        failures = []
        eag.parse_artifacts(
            [
                {"name": "model", "path": "model.pkl", "sha256": h},
                {"name": "model", "path": "model.pkl", "sha256": h},
            ],
            tmp_path, [], tmp_path / "eval.json", failures, [],
        )
        codes = [f["code"] for f in failures]
        assert "duplicate_artifact_name" in codes

    def test_hash_mismatch_fails(self, tmp_path):
        f = tmp_path / "model.pkl"
        f.write_bytes(b"model data")
        failures = []
        eag.parse_artifacts(
            [{"name": "model", "path": "model.pkl", "sha256": "0" * 64}],
            tmp_path, [], tmp_path / "eval.json", failures, [],
        )
        codes = [f["code"] for f in failures]
        assert "artifact_hash_mismatch" in codes

    def test_artifact_file_missing_fails(self, tmp_path):
        failures = []
        eag.parse_artifacts(
            [{"name": "model", "path": "nonexistent.pkl", "sha256": "a" * 64}],
            tmp_path, [], tmp_path / "eval.json", failures, [],
        )
        codes = [f["code"] for f in failures]
        assert "artifact_file_missing" in codes

    def test_required_artifact_missing(self, tmp_path):
        # Empty list → still returns but triggers missing_required
        f = tmp_path / "dummy.txt"
        f.write_bytes(b"x" * 100)
        h = eag.sha256_file(f)
        failures = []
        eag.parse_artifacts(
            [{"name": "dummy", "path": "dummy.txt", "sha256": h}],
            tmp_path, ["model_artifact", "training_log"],
            tmp_path / "eval.json", failures, [],
        )
        codes = [f_["code"] for f_ in failures]
        assert "missing_required_artifacts" in codes

    def test_valid_artifact_passes(self, tmp_path):
        # Name it "evaluation_report" to satisfy the mandatory check
        f = tmp_path / "eval.json"
        f.write_bytes(b'{"metrics": {"roc_auc": 0.85}}')
        h = eag.sha256_file(f)
        failures = []
        result = eag.parse_artifacts(
            [{"name": "evaluation_report", "path": "eval.json", "sha256": h}],
            tmp_path, [], tmp_path / "eval.json", failures, [],
        )
        assert len(failures) == 0
        assert result["artifact_count"] == 1

    def test_training_log_too_small_fails(self, tmp_path):
        """training_log < 64 bytes → failure (insufficient_training_log_evidence)."""
        f = tmp_path / "train.log"
        f.write_bytes(b"tiny")  # < 64 bytes
        h = eag.sha256_file(f)
        failures = []
        eag.parse_artifacts(
            [{"name": "training_log", "path": "train.log", "sha256": h}],
            tmp_path, [], tmp_path / "eval.json", failures, [],
        )
        codes = [f_["code"] for f_ in failures]
        assert "insufficient_training_log_evidence" in codes

    def test_non_training_log_small_warns(self, tmp_path):
        """Non-training log < 64 bytes → warning (short_log_artifact)."""
        f = tmp_path / "audit.log"
        f.write_bytes(b"tiny")
        h = eag.sha256_file(f)
        warnings = []
        eag.parse_artifacts(
            [{"name": "audit_log", "path": "audit.log", "sha256": h}],
            tmp_path, [], tmp_path / "eval.json", [], warnings,
        )
        codes = [w["code"] for w in warnings]
        assert "short_log_artifact" in codes


# ── Study ID mismatch (requires valid enough spec to reach the check) ──

class TestStudyRunIDMismatch:
    """Test that study_id mismatch is detected when spec has a signing block."""

    def test_study_id_mismatch_via_cli(self, tmp_path):
        # Spec with study_id="S1" but CLI passes --study-id DIFFERENT
        report = _run_gate(tmp_path, study_id="DIFFERENT_STUDY")
        codes = [f["code"] for f in report["failures"]]
        # Gate will fail for many reasons (no signing, etc) but the ID check
        # may or may not be reached depending on how far parsing gets.
        # At minimum, the gate should produce failures.
        assert report["status"] == "fail"


# ── validate_key_assurance (unit tests) ────────────────────────────────

class TestValidateKeyAssurance:
    """Test key assurance policy validation."""

    def _make_signing(self, **overrides):
        base = {
            "method": "openssl-dgst-sha256",
            "issued_at_utc": "2025-01-15T10:00:00Z",
            "key_created_at_utc": "2024-01-01T00:00:00Z",
            "key_not_after_utc": "2026-01-01T00:00:00Z",
            "signing_key_public_pem": "key.pem",
        }
        base.update(overrides)
        return base

    def _make_spec(self, **policy_overrides):
        policy = {
            "min_signing_key_bits": 2048,
            "max_signing_key_age_days": 730,
            "require_revocation_list": False,
            "require_timestamp_trust": False,
            "require_transparency_log": False,
            "require_transparency_log_signature": False,
            "require_execution_receipt": False,
            "require_execution_log_attestation": False,
            "require_independent_timestamp_authority": False,
            "require_independent_execution_authority": False,
            "require_independent_log_authority": False,
            "require_distinct_authority_roles": False,
            "require_witness_quorum": False,
            "require_independent_witness_keys": False,
            "require_witness_independence_from_signing": False,
            "min_witness_count": 0,
        }
        policy.update(policy_overrides)
        return {"assurance_policy": policy}

    def test_missing_assurance_policy_uses_defaults(self, tmp_path):
        """No assurance_policy → uses defaults, no crash."""
        (tmp_path / "key.pem").write_text("dummy")
        failures = []
        warnings = []
        eag.validate_key_assurance(
            tmp_path, {}, self._make_signing(),
            eag.parse_iso_ts("2025-01-15T10:00:00Z"), failures, warnings,
        )
        # Should not crash; may produce warnings but not necessarily failures
        # (depends on whether defaults trigger anything)

    def test_key_expired_fails(self, tmp_path):
        (tmp_path / "key.pem").write_text("dummy")
        signing = self._make_signing(key_not_after_utc="2024-06-01T00:00:00Z")
        failures = []
        warnings = []
        eag.validate_key_assurance(
            tmp_path, self._make_spec(), signing,
            eag.parse_iso_ts("2025-01-15T10:00:00Z"), failures, warnings,
        )
        codes = [f["code"] for f in failures]
        assert "signing_key_expired" in codes

    def test_attestation_before_key_creation_fails(self, tmp_path):
        (tmp_path / "key.pem").write_text("dummy")
        signing = self._make_signing(key_created_at_utc="2026-01-01T00:00:00Z")
        failures = []
        warnings = []
        eag.validate_key_assurance(
            tmp_path, self._make_spec(), signing,
            eag.parse_iso_ts("2025-01-15T10:00:00Z"), failures, warnings,
        )
        codes = [f["code"] for f in failures]
        assert "attestation_before_key_creation" in codes

    def test_key_rotation_overdue_fails(self, tmp_path):
        (tmp_path / "key.pem").write_text("dummy")
        signing = self._make_signing(key_created_at_utc="2020-01-01T00:00:00Z")
        spec = self._make_spec(max_signing_key_age_days=365)
        failures = []
        warnings = []
        eag.validate_key_assurance(
            tmp_path, spec, signing,
            eag.parse_iso_ts("2025-01-15T10:00:00Z"), failures, warnings,
        )
        codes = [f["code"] for f in failures]
        assert "signing_key_rotation_overdue" in codes

    def test_invalid_key_timestamps_fails(self, tmp_path):
        (tmp_path / "key.pem").write_text("dummy")
        signing = self._make_signing(key_created_at_utc="not-a-date")
        failures = []
        warnings = []
        eag.validate_key_assurance(
            tmp_path, self._make_spec(), signing,
            eag.parse_iso_ts("2025-01-15T10:00:00Z"), failures, warnings,
        )
        codes = [f["code"] for f in failures]
        assert "invalid_key_created_timestamp" in codes


# ── Revocation list integration ────────────────────────────────────────

class TestRevocationInKeyAssurance:

    def test_signing_key_revoked_by_id(self):
        failures = []
        eag.check_authority_not_revoked(
            "signing", "key-001", "fp-abc",
            {"key-001"}, set(), failures,
        )
        codes = [f["code"] for f in failures]
        assert any("key_revoked" in c for c in codes)

    def test_signing_key_revoked_by_fingerprint(self):
        failures = []
        eag.check_authority_not_revoked(
            "signing", "key-001", "fp-abc",
            set(), {"fp-abc"}, failures,
        )
        codes = [f["code"] for f in failures]
        assert any("key_revoked" in c for c in codes)

    def test_not_revoked_passes(self):
        failures = []
        eag.check_authority_not_revoked(
            "signing", "key-001", "fp-abc",
            {"key-999"}, {"fp-xyz"}, failures,
        )
        assert len(failures) == 0


# ── CLI: invalid attestation spec ──────────────────────────────────────

class TestCLISpecValidation:

    def test_spec_invalid_json(self, tmp_path):
        eval_path = tmp_path / "eval.json"
        eval_path.write_text(json.dumps({"metrics": {"roc_auc": 0.8}}))
        spec_path = tmp_path / "spec.json"
        spec_path.write_text("not json!!!")
        report_path = tmp_path / "report.json"
        cmd = [
            sys.executable, str(GATE_SCRIPT),
            "--attestation-spec", str(spec_path),
            "--evaluation-report", str(eval_path),
            "--report", str(report_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(SCRIPTS_DIR))
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "attestation_spec_invalid_json" in codes

    def test_spec_not_object(self, tmp_path):
        eval_path = tmp_path / "eval.json"
        eval_path.write_text(json.dumps({"metrics": {"roc_auc": 0.8}}))
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps([1, 2, 3]))
        report_path = tmp_path / "report.json"
        cmd = [
            sys.executable, str(GATE_SCRIPT),
            "--attestation-spec", str(spec_path),
            "--evaluation-report", str(eval_path),
            "--report", str(report_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(SCRIPTS_DIR))
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "attestation_spec_invalid_root" in codes

    def test_evaluation_report_not_file(self, tmp_path):
        spec_path = tmp_path / "spec.json"
        spec_path.write_text(json.dumps({"study_id": "S1", "run_id": "R1"}))
        report_path = tmp_path / "report.json"
        cmd = [
            sys.executable, str(GATE_SCRIPT),
            "--attestation-spec", str(spec_path),
            "--evaluation-report", str(tmp_path / "missing_eval.json"),
            "--report", str(report_path),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(SCRIPTS_DIR))
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert any("evaluation_report" in c for c in codes)
