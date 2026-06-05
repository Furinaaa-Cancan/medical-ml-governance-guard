"""W9-B1: disease KB fail-closed enforcement in publication_gate (W10 finding).

W10 audit (2026-05-17) found 11/11 disease KB entries have
``clinician_review_status == "pending"`` with no named reviewer. Per MLGG's
fail-closed philosophy, publication-grade outputs MUST REFUSE to consume
LLM-compiled phenotype definitions without clinician sign-off.

These tests pin the contract:

1. Default behavior: any unreviewed/missing-provenance entry FAILS the
   publication gate (returncode 2, failure code ``disease_kb_unreviewed``).
2. All-approved KB: passes silently with no warnings.
3. ``--allow-unreviewed-disease-kb`` override: downgrades FAIL to WARNING,
   gate exits 0, but L3 publication-grade tier is still blocked.
4. ``MLGG_ALLOW_UNREVIEWED_DISEASE_KB=1`` env var: same as the flag.
5. ``--skip-disease-kb-check``: bypasses the gate entirely (synthetic-data
   demo escape hatch).
6. Missing KB / invalid JSON / missing diseases block: explicit failure codes.
7. Bundled repo KB (the real one) currently FAILS — proves W10 finding is
   actually enforced, not just declared.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
PUB_GATE = REPO_ROOT / "scripts" / "gates" / "publication_gate.py"
BUNDLED_KB = REPO_ROOT / "references" / "methodology" / "disease-definition-knowledge-base.json"


# ── Helpers ──────────────────────────────────────────────────────────────

def _write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _good_component():
    return {"status": "pass", "strict_mode": True, "failure_count": 0}


def _good_manifest():
    return {
        "status": "pass",
        "strict_mode": True,
        "failure_count": 0,
        "files": [{"path": "train.csv", "sha256": "abc123"}],
        "errors": [],
        "comparison": {"matched": True},
    }


def _good_execution_attestation():
    return {
        "status": "pass",
        "strict_mode": True,
        "failure_count": 0,
        "summary": {
            "key_assurance": {
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
                    "min_witness_count": 3,
                }
            },
            "timestamp_trust": {"present": True},
            "transparency_log": {"present": True},
            "execution_receipt": {"present": True},
            "execution_log_attestation": {"present": True},
            "witness_quorum": {
                "present": True,
                "required": True,
                "validated_witnesses": 3,
                "min_witness_count": 3,
            },
            "authority_role_distinctness": {
                "enforced": True,
                "status": "pass",
            },
            # P0.4: attestation contract now requires verified-signature proof.
            "signature_verification": {"verified": True},
            "trust_verification": {
                "checked": True,
                "trusted": True,
                "allow_unsigned_mode": False,
            },
        },
    }


def _good_metric():
    return {"status": "pass", "strict_mode": True, "failure_count": 0, "actual_metric": 0.85}


# Mirror the COMPONENT_NAMES/ARGS shape from test_publication_gate.py so
# this test stays self-contained.
COMPONENT_NAMES = [
    "request_report", "manifest", "execution_attestation_report",
    "reporting_bias_report", "leakage_report", "split_protocol_report",
    "covariate_shift_report", "definition_report", "lineage_report",
    "imbalance_report", "missingness_report", "tuning_report",
    "model_selection_audit_report", "feature_engineering_audit_report",
    "clinical_metrics_report", "prediction_replay_report",
    "distribution_generalization_report", "generalization_gap_report",
    "robustness_report", "seed_stability_report",
    "external_validation_report", "calibration_dca_report",
    "ci_matrix_report", "metric_report", "evaluation_quality_report",
    "permutation_report", "fairness_equity_report", "sample_size_report",
]
COMPONENT_ARGS = [
    "--request-report", "--manifest", "--execution-attestation-report",
    "--reporting-bias-report", "--leakage-report", "--split-protocol-report",
    "--covariate-shift-report", "--definition-report", "--lineage-report",
    "--imbalance-report", "--missingness-report", "--tuning-report",
    "--model-selection-audit-report", "--feature-engineering-audit-report",
    "--clinical-metrics-report", "--prediction-replay-report",
    "--distribution-generalization-report", "--generalization-gap-report",
    "--robustness-report", "--seed-stability-report",
    "--external-validation-report", "--calibration-dca-report",
    "--ci-matrix-report", "--metric-report", "--evaluation-quality-report",
    "--permutation-report", "--fairness-equity-report", "--sample-size-report",
]


def _seed_components(tmp_path: Path) -> dict:
    paths = {}
    for name in COMPONENT_NAMES:
        if name == "manifest":
            data = _good_manifest()
        elif name == "execution_attestation_report":
            data = _good_execution_attestation()
        elif name == "metric_report":
            data = _good_metric()
        else:
            data = _good_component()
        paths[name] = _write_json(tmp_path / f"{name}.json", data)
    return paths


def _run(
    tmp_path: Path,
    paths: dict,
    *,
    kb_path: Path | None,
    extra: list[str] | None = None,
    env: dict | None = None,
):
    report = tmp_path / "report.json"
    cmd = [sys.executable, str(PUB_GATE), "--report", str(report)]
    for arg, name in zip(COMPONENT_ARGS, COMPONENT_NAMES):
        cmd.extend([arg, str(paths[name])])
    if kb_path is not None:
        cmd.extend(["--disease-kb", str(kb_path)])
    if extra:
        cmd.extend(extra)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
    return proc, report


def _write_kb(path: Path, diseases: dict, *, version: str = "1.0") -> Path:
    path.write_text(
        json.dumps({"version": version, "diseases": diseases}, indent=2),
        encoding="utf-8",
    )
    return path


def _pending_entry():
    return {
        "name": "Pending Disease",
        "provenance": {
            "source": "llm_compiled",
            "clinician_review_status": "pending",
        },
    }


def _approved_entry():
    return {
        "name": "Approved Disease",
        "provenance": {
            "source": "clinician_reviewed",
            "clinician_review_status": "clinician_reviewed",
            "reviewer": "Dr. Test",
            "last_reviewed": "2026-05-17",
            "reviewed_against": "ADA 2025",
        },
    }


# ── Fail-closed behavior ──────────────────────────────────────────────────

class TestPublicationGateFailsClosed:
    def test_publication_gate_fails_when_disease_kb_unreviewed(self, tmp_path: Path):
        """W10: unreviewed KB entries must hard-fail publication gate."""
        paths = _seed_components(tmp_path)
        kb = _write_kb(tmp_path / "kb.json", {
            "type_2_diabetes": _pending_entry(),
            "hypertension": _pending_entry(),
        })

        proc, report_path = _run(tmp_path, paths, kb_path=kb)

        assert proc.returncode == 2, (
            f"Expected fail-closed (rc=2) for unreviewed KB. Got rc={proc.returncode}.\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        report = json.loads(report_path.read_text())
        assert report["status"] == "fail"
        codes = [f["code"] for f in report["failures"]]
        assert "disease_kb_unreviewed" in codes
        # Summary surfaces the pending diseases by name for downstream audit.
        kb_summary = report["summary"]["disease_kb_review"]
        assert set(kb_summary["pending_diseases"]) == {"type_2_diabetes", "hypertension"}
        assert kb_summary["approved_diseases"] == []
        assert kb_summary["allow_unreviewed_override"] is False

    def test_publication_gate_fails_on_bundled_repo_kb_today(self, tmp_path: Path):
        """W10 finding bite: the bundled KB is 11/11 pending RIGHT NOW.

        This test pins the audit finding to behavior. The test SHOULD start
        failing once clinicians sign off on the KB — that's the success
        condition, not a regression.
        """
        if not BUNDLED_KB.exists():
            pytest.skip(f"Bundled KB not present at {BUNDLED_KB}")

        paths = _seed_components(tmp_path)
        proc, report_path = _run(tmp_path, paths, kb_path=BUNDLED_KB)

        assert proc.returncode == 2, (
            "Bundled KB should fail publication gate while entries are pending. "
            "If this test fails because a clinician approved the KB, update "
            "the assertion to expect rc=0."
        )
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "disease_kb_unreviewed" in codes
        kb_summary = report["summary"]["disease_kb_review"]
        # Document the audit finding inline.
        assert kb_summary["approved_diseases"] == [], (
            f"Approved-so-far: {kb_summary['approved_diseases']} — "
            "the W10 audit (2026-05-17) reported 0 approved."
        )
        assert kb_summary["total_diseases"] >= 11


class TestPublicationGatePassesWhenKBReviewed:
    def test_passes_when_all_entries_approved(self, tmp_path: Path):
        paths = _seed_components(tmp_path)
        kb = _write_kb(tmp_path / "kb.json", {
            "d1": _approved_entry(),
            "d2": _approved_entry(),
        })
        proc, report_path = _run(tmp_path, paths, kb_path=kb)
        assert proc.returncode == 0, (
            f"All-approved KB should pass. rc={proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        report = json.loads(report_path.read_text())
        assert report["status"] == "pass"
        codes = [f["code"] for f in report["failures"]]
        assert "disease_kb_unreviewed" not in codes
        warn_codes = [w["code"] for w in report["warnings"]]
        assert "disease_kb_unreviewed" not in warn_codes
        kb_summary = report["summary"]["disease_kb_review"]
        assert set(kb_summary["approved_diseases"]) == {"d1", "d2"}
        assert kb_summary["pending_diseases"] == []
        # L3 should be reachable when KB is approved (other tiers permitting).
        tiers = report["summary"]["compliance_tiers"]
        assert tiers["L3_publication_grade"] is True


class TestOverrideFlag:
    def test_flag_downgrades_fail_to_warning(self, tmp_path: Path):
        paths = _seed_components(tmp_path)
        kb = _write_kb(tmp_path / "kb.json", {"d1": _pending_entry()})

        proc, report_path = _run(
            tmp_path, paths, kb_path=kb,
            extra=["--allow-unreviewed-disease-kb"],
        )

        assert proc.returncode == 0, (
            f"Override should let gate pass (warning only). rc={proc.returncode}\n"
            f"stdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        report = json.loads(report_path.read_text())
        assert report["status"] == "pass"
        warn_codes = [w["code"] for w in report["warnings"]]
        assert "disease_kb_unreviewed" in warn_codes
        fail_codes = [f["code"] for f in report["failures"]]
        assert "disease_kb_unreviewed" not in fail_codes
        kb_summary = report["summary"]["disease_kb_review"]
        assert kb_summary["allow_unreviewed_override"] is True
        # Critical: override lets gate finish, but L3 publication-grade is still BLOCKED.
        # Mirrors: a paper with --no-verify commits is still not publication-grade.
        tiers = report["summary"]["compliance_tiers"]
        assert tiers["L3_publication_grade"] is False
        assert report["summary"]["compliance_level"] != "L3"

    def test_env_var_overrides(self, tmp_path: Path, monkeypatch):
        import os
        paths = _seed_components(tmp_path)
        kb = _write_kb(tmp_path / "kb.json", {"d1": _pending_entry()})

        env = os.environ.copy()
        env["MLGG_ALLOW_UNREVIEWED_DISEASE_KB"] = "1"
        proc, report_path = _run(tmp_path, paths, kb_path=kb, env=env)

        assert proc.returncode == 0
        report = json.loads(report_path.read_text())
        warn_codes = [w["code"] for w in report["warnings"]]
        assert "disease_kb_unreviewed" in warn_codes

    def test_env_var_false_does_not_override(self, tmp_path: Path):
        import os
        paths = _seed_components(tmp_path)
        kb = _write_kb(tmp_path / "kb.json", {"d1": _pending_entry()})

        env = os.environ.copy()
        env["MLGG_ALLOW_UNREVIEWED_DISEASE_KB"] = "0"
        proc, _ = _run(tmp_path, paths, kb_path=kb, env=env)
        assert proc.returncode == 2


class TestSkipFlag:
    def test_skip_disease_kb_check_bypasses_entirely(self, tmp_path: Path):
        """--skip-disease-kb-check is the synthetic-data demo escape hatch.

        Distinct from --allow-unreviewed-disease-kb: skip means the gate did
        not look at the KB at all (so a downstream check still needed). The
        override means we looked and chose to ignore.
        """
        paths = _seed_components(tmp_path)
        kb = _write_kb(tmp_path / "kb.json", {"d1": _pending_entry()})

        proc, report_path = _run(
            tmp_path, paths, kb_path=kb,
            extra=["--skip-disease-kb-check"],
        )
        assert proc.returncode == 0
        report = json.loads(report_path.read_text())
        kb_summary = report["summary"]["disease_kb_review"]
        assert kb_summary["skipped"] is True
        # No KB-related entries should appear in failures or warnings.
        codes = [i["code"] for i in report["failures"] + report["warnings"]]
        assert "disease_kb_unreviewed" not in codes


class TestKBIOFailures:
    def test_missing_kb_fails(self, tmp_path: Path):
        paths = _seed_components(tmp_path)
        proc, report_path = _run(tmp_path, paths, kb_path=tmp_path / "nope.json")
        assert proc.returncode == 2
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "disease_kb_not_found" in codes

    def test_invalid_kb_json_fails(self, tmp_path: Path):
        paths = _seed_components(tmp_path)
        kb = tmp_path / "bad.json"
        kb.write_text("{not valid", encoding="utf-8")
        proc, report_path = _run(tmp_path, paths, kb_path=kb)
        assert proc.returncode == 2
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "disease_kb_invalid_json" in codes

    def test_kb_missing_diseases_block_fails(self, tmp_path: Path):
        paths = _seed_components(tmp_path)
        kb = _write_json(tmp_path / "kb.json", {"version": "1.0"})
        proc, report_path = _run(tmp_path, paths, kb_path=kb)
        assert proc.returncode == 2
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "disease_kb_missing_diseases_block" in codes


class TestSummaryEmbedding:
    def test_summary_includes_disease_kb_block(self, tmp_path: Path):
        """The gate report must surface the disease-KB sub-summary so audit
        consumers (compliance certificate, evidence digest, user summary)
        can render review status without re-reading the KB."""
        paths = _seed_components(tmp_path)
        kb = _write_kb(tmp_path / "kb.json", {
            "approved_one": _approved_entry(),
            "pending_one": _pending_entry(),
            "missing_one": {"name": "No Provenance"},
        })
        proc, report_path = _run(tmp_path, paths, kb_path=kb)
        assert proc.returncode == 2  # one pending + one missing → fail
        report = json.loads(report_path.read_text())
        kb_summary = report["summary"]["disease_kb_review"]
        assert kb_summary["total_diseases"] == 3
        assert kb_summary["approved_diseases"] == ["approved_one"]
        assert kb_summary["pending_diseases"] == ["pending_one"]
        assert kb_summary["missing_provenance_diseases"] == ["missing_one"]
        assert kb_summary["kb_path"].endswith("kb.json")


# ── Direct unit tests (no subprocess) ────────────────────────────────────

class TestEnforceHelperDirect:
    """Direct unit tests on enforce_disease_kb_clinically_reviewed."""

    @pytest.fixture
    def enforce(self):
        # Import via the same path mangling publication_gate uses.
        import sys as _sys
        _sys.path.insert(0, str(REPO_ROOT / "scripts" / "core"))
        _sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))
        _sys.path.insert(0, str(REPO_ROOT / "scripts" / "gates"))
        from publication_gate import enforce_disease_kb_clinically_reviewed
        return enforce_disease_kb_clinically_reviewed

    def test_skip_returns_empty_summary(self, enforce, tmp_path):
        failures, warnings = [], []
        summary = enforce(
            str(tmp_path / "nope.json"),
            failures, warnings,
            skip=True,
        )
        assert summary["skipped"] is True
        assert failures == []
        assert warnings == []

    def test_no_path_fails(self, enforce):
        failures, warnings = [], []
        enforce(None, failures, warnings)
        assert any(f["code"] == "disease_kb_not_found" for f in failures)

    def test_all_approved_silent(self, enforce, tmp_path):
        kb = _write_kb(tmp_path / "kb.json", {"d1": _approved_entry()})
        failures, warnings = [], []
        summary = enforce(str(kb), failures, warnings)
        assert failures == []
        assert warnings == []
        assert summary["approved_diseases"] == ["d1"]


# ── W11-F2: close source-only spoofing hole ─────────────────────────────

class TestW11F2NoSourceOnlyBypass:
    """W11-F2 regression tests.

    Before W11-F2 ``classify_disease`` returned ``approved`` if EITHER
    ``source`` OR ``clinician_review_status`` was in ``APPROVED_STATUSES``.
    That meant a one-line JSON edit (``"source": "approved"``) bypassed the
    entire ``publication_gate`` fail-closed check from W9-B1 (041c663),
    with no binding to a reviewer or review date.

    The new contract: an entry counts as ``approved`` only when ALL of
    (a) clinician_review_status in APPROVED_STATUSES, (b) reviewer
    non-empty, (c) last_reviewed non-empty. Anything else lands outside
    the approved bucket.
    """

    @pytest.fixture
    def classify(self):
        import sys as _sys
        _sys.path.insert(0, str(REPO_ROOT / "scripts" / "core"))
        _sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))
        from disease_kb_review_check import classify_disease
        return classify_disease

    def test_source_only_approval_no_longer_bypasses(self, classify, tmp_path):
        """The W11-F2 spoofing hole: ``"source": "approved"`` alone must
        NOT mark an entry as approved.

        Covers both ends of the contract: (1) the direct unit on
        ``classify_disease`` must NOT return the approved bucket; (2) the
        full publication_gate must still fail-closed because the entry is
        not in the approved set.
        """
        entry = {
            "name": "Spoofed Approval",
            "provenance": {
                # The 1-line spoofing payload from the W10-R2 finding.
                "source": "approved",
                # Status, reviewer, last_reviewed all absent / empty.
            },
        }
        bucket, details = classify("spoofed", entry)
        assert bucket != "approved", (
            "W11-F2 regression: source-only approval bypassed fail-closed gate. "
            f"Got bucket={bucket!r}, details={details!r}."
        )

        # End-to-end: a KB with only a source-spoofed entry must NOT pass
        # the publication gate. The entry should sit in either the
        # missing-provenance or pending bucket, both of which fail-closed.
        paths = _seed_components(tmp_path)
        kb = _write_kb(tmp_path / "kb.json", {"spoofed": entry})
        proc, report_path = _run(tmp_path, paths, kb_path=kb)
        assert proc.returncode == 2, (
            "Publication gate must fail-closed on source-only spoofed entry. "
            f"rc={proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        report = json.loads(report_path.read_text())
        kb_summary = report["summary"]["disease_kb_review"]
        assert "spoofed" not in kb_summary["approved_diseases"]

    @pytest.mark.parametrize(
        "drop_field",
        ["clinician_review_status", "reviewer", "last_reviewed"],
    )
    def test_full_provenance_required(self, classify, drop_field):
        """All three reviewer-binding fields are required for approval.

        Baseline: a fully-provenanced entry IS approved. Dropping ANY one
        of {clinician_review_status, reviewer, last_reviewed} must move
        the entry out of the approved bucket.
        """
        full_prov = {
            "source": "clinician_reviewed",
            "clinician_review_status": "clinician_reviewed",
            "reviewer": "Dr. Test",
            "last_reviewed": "2026-05-17",
            "reviewed_against": "ADA 2025",
        }
        # Baseline: fully-provenanced entry IS approved.
        baseline_bucket, _ = classify(
            "d_full", {"name": "Full", "provenance": dict(full_prov)},
        )
        assert baseline_bucket == "approved", (
            "Sanity: full provenance must remain the approved baseline."
        )

        # Drop one field — must lose the approved bucket.
        broken_prov = dict(full_prov)
        if drop_field == "clinician_review_status":
            # Set status to a non-pending, non-approved value so the
            # PENDING_STATUSES short-circuit doesn't mask the test.
            broken_prov["clinician_review_status"] = ""
        elif drop_field == "reviewer":
            broken_prov["reviewer"] = ""
        elif drop_field == "last_reviewed":
            broken_prov["last_reviewed"] = ""

        bucket, details = classify(
            "d_broken", {"name": "Broken", "provenance": broken_prov},
        )
        assert bucket != "approved", (
            f"Dropping {drop_field!r} must remove entry from approved bucket. "
            f"Got bucket={bucket!r}, details={details!r}."
        )
