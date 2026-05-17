"""W13-C1: behavioral verification of W11-F2 stricter classify_disease.

The bundled KB today has 0 approved entries (all pending review), so F2's
new strictness has no measurable behavioral diff today. This file constructs
the FUTURE failure modes F2 is designed to catch and verifies each.

Future regressions to watch:
- Someone sets source='approved' without filling reviewer/last_reviewed
- Someone sets clinician_review_status='approved' without reviewer trace
- Migration script copies status='approved' from another file but loses
  reviewer metadata

Bucket naming note
------------------
``classify_disease`` returns one of three buckets: ``approved``, ``pending``,
``missing``. The "incomplete provenance" case (source-only approval, status
approved without reviewer/last_reviewed) lands in ``missing`` — surfaced by
publication_gate under the ``missing_provenance_diseases`` summary key and
the ``disease_kb_unreviewed`` failure code. The W13-C1 task spec referred to
this informally as ``provenance_incomplete``; the actual bucket name is
``missing``. These tests assert against the real bucket name plus the
behavioral contract (not approved → publication gate fails closed).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent.parent
PUB_GATE = REPO_ROOT / "scripts" / "gates" / "publication_gate.py"


# ── Shared fixtures: import classify_disease through the same sys.path
#     mangling that publication_gate uses (mirrors test_disease_kb_fail_closed).

@pytest.fixture
def classify():
    import sys as _sys
    _sys.path.insert(0, str(REPO_ROOT / "scripts" / "core"))
    _sys.path.insert(0, str(REPO_ROOT / "scripts" / "diagnostics"))
    from disease_kb_review_check import classify_disease
    return classify_disease


# ── Helpers reused from test_disease_kb_fail_closed.py shape ────────────

def _write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


def _write_kb(path: Path, diseases: dict, *, version: str = "1.0") -> Path:
    path.write_text(
        json.dumps({"version": version, "diseases": diseases}, indent=2),
        encoding="utf-8",
    )
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
        },
    }


def _good_metric():
    return {"status": "pass", "strict_mode": True, "failure_count": 0, "actual_metric": 0.85}


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


def _run_pub_gate(
    tmp_path: Path,
    paths: dict,
    *,
    kb_path: Path,
):
    report = tmp_path / "report.json"
    cmd = [sys.executable, str(PUB_GATE), "--report", str(report)]
    for arg, name in zip(COMPONENT_ARGS, COMPONENT_NAMES):
        cmd.extend([arg, str(paths[name])])
    cmd.extend(["--disease-kb", str(kb_path)])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return proc, report


# ── Entry-shape helpers ──────────────────────────────────────────────────
#
# ``classify_disease`` reads from ``entry["provenance"]``. The W13-C1 task
# spec described entries with flat ``source/clinician_review_status/...``
# keys; we honor the real on-disk shape (nested under ``provenance``) since
# that's what the function actually evaluates and what a future stale-source
# regression would look like in the real KB file.

def _entry(name: str, provenance: dict) -> dict:
    return {"name": name, "provenance": provenance}


# ────────────────────────────────────────────────────────────────────────
# Unit tests: classify_disease must refuse stale-source entries
# ────────────────────────────────────────────────────────────────────────

class TestStaleSourceRejected:
    """Direct unit assertions on ``classify_disease`` against the future
    failure modes W11-F2 was written to catch."""

    def test_source_approved_without_reviewer_is_rejected(self, classify):
        """source='approved' alone must not yield the approved bucket.

        This is the exact W11-F2 spoofing payload: a one-line edit to the
        ``provenance.source`` field. With no reviewer/last_reviewed binding,
        the entry must land in the ``missing`` (incomplete provenance)
        bucket so publication_gate fail-closes via
        ``disease_kb_unreviewed``.
        """
        entry = _entry("Stale Source Disease", {
            "source": "approved",
            "clinician_review_status": "pending",
            "reviewer": None,
            "last_reviewed": None,
        })
        bucket, details = classify("stale_x", entry)
        assert bucket != "approved", (
            f"source-only approval bypassed F2. bucket={bucket!r}, details={details!r}"
        )
        # PENDING_STATUSES short-circuit means a status of 'pending' makes
        # this land in the 'pending' bucket (the explicit pending override
        # wins over source). Either 'pending' or 'missing' satisfies the
        # contract — both fail-close the gate. We document both as valid.
        assert bucket in {"pending", "missing"}, (
            f"Expected pending/missing for stale-source+pending entry, got {bucket!r}"
        )

    def test_clinician_review_status_approved_without_reviewer_is_rejected(self, classify):
        """clinician_review_status='approved' without reviewer trace fails.

        Migration / hand-edit scenario: someone flipped the status field
        without filling reviewer or last_reviewed. F2 requires the binding
        triple; status alone must not be sufficient.
        """
        entry = _entry("Status-Only Approved", {
            "source": "llm_compiled",
            "clinician_review_status": "approved",
            "reviewer": None,
            "last_reviewed": None,
        })
        bucket, details = classify("status_only", entry)
        assert bucket != "approved", (
            f"status-only approval bypassed F2. bucket={bucket!r}, details={details!r}"
        )
        # Status is APPROVED-class (not PENDING) and source is not in
        # APPROVED_STATUSES, so the entry lands in 'missing' via the
        # incomplete-provenance path. Lock that behavior.
        assert bucket == "missing", (
            f"Expected 'missing' (incomplete provenance) bucket, got {bucket!r}. "
            f"details={details!r}"
        )
        # Detail message must surface the specific missing fields so reviewers
        # can fix the entry. We expect 'reviewer' and 'last_reviewed' to be
        # called out.
        reason = details.get("reason", "")
        assert "reviewer" in reason and "last_reviewed" in reason, (
            f"missing-fields reason should call out reviewer and last_reviewed. "
            f"Got: {reason!r}"
        )

    def test_full_provenance_approved(self, classify):
        """Sanity baseline: a fully-provenanced entry IS approved.

        Without this baseline, the rejection tests above could pass for the
        wrong reason (e.g. classify_disease always returning non-approved).
        """
        entry = _entry("Fully Approved", {
            "source": "clinician_reviewed",
            "clinician_review_status": "approved",
            "reviewer": "Dr. Smith",
            "last_reviewed": "2026-04-01",
        })
        bucket, details = classify("full_x", entry)
        assert bucket == "approved", (
            f"Full provenance should be approved. bucket={bucket!r}, details={details!r}"
        )

    def test_empty_string_reviewer_rejected(self, classify):
        """reviewer="" (empty string, not None) must NOT count as approved.

        Catches: someone runs ``jq '.reviewer=""'`` on a real entry, or a
        merge tool collapses a None to "". F2 must treat empty-string the
        same as missing.
        """
        entry = _entry("Empty Reviewer", {
            "source": "clinician_reviewed",
            "clinician_review_status": "approved",
            "reviewer": "",
            "last_reviewed": "2026-04-01",
        })
        bucket, details = classify("empty_reviewer", entry)
        assert bucket != "approved", (
            f"Empty-string reviewer must not be approved. "
            f"bucket={bucket!r}, details={details!r}"
        )
        assert bucket == "missing"

    def test_empty_string_last_reviewed_rejected(self, classify):
        """last_reviewed="" (empty string) must NOT count as approved."""
        entry = _entry("Empty Date", {
            "source": "clinician_reviewed",
            "clinician_review_status": "approved",
            "reviewer": "Dr. Smith",
            "last_reviewed": "",
        })
        bucket, details = classify("empty_date", entry)
        assert bucket != "approved", (
            f"Empty-string last_reviewed must not be approved. "
            f"bucket={bucket!r}, details={details!r}"
        )
        assert bucket == "missing"


# ────────────────────────────────────────────────────────────────────────
# End-to-end: publication_gate must fail-close on stale-source entries
# ────────────────────────────────────────────────────────────────────────

class TestPublicationGateBlocksStaleSource:
    def test_publication_gate_blocks_stale_source_entry(self, tmp_path: Path):
        """A KB containing a stale-source entry must fail the gate.

        Wires up: classify_disease → enforce_disease_kb_clinically_reviewed
        → publication_gate failure code ``disease_kb_unreviewed``. This
        verifies the W11-F2 strictness actually propagates through the gate,
        not just the unit-level classifier.

        The stale-source entry uses status='approved' (not 'pending') so it
        bypasses the PENDING_STATUSES short-circuit and exercises the
        incomplete-provenance ('missing') path — which surfaces under
        ``missing_provenance_diseases`` in the gate summary.
        """
        paths = _seed_components(tmp_path)
        stale_entry = _entry("Stale Source Hypertension", {
            "source": "approved",
            "clinician_review_status": "approved",
            "reviewer": None,
            "last_reviewed": None,
        })
        kb = _write_kb(tmp_path / "stale_kb.json", {"stale_disease": stale_entry})

        proc, report_path = _run_pub_gate(tmp_path, paths, kb_path=kb)

        assert proc.returncode == 2, (
            f"Publication gate must fail-close on stale-source entry. "
            f"rc={proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
        report = json.loads(report_path.read_text())
        codes = [f["code"] for f in report["failures"]]
        assert "disease_kb_unreviewed" in codes, (
            f"Expected 'disease_kb_unreviewed' in failures, got: {codes}"
        )
        # The stale entry should surface in the unreviewed list. The exact
        # sub-list depends on bucket: incomplete provenance lands in
        # ``missing_provenance_diseases``.
        kb_summary = report["summary"]["disease_kb_review"]
        all_unreviewed = (
            kb_summary.get("pending_diseases", [])
            + kb_summary.get("missing_provenance_diseases", [])
        )
        assert "stale_disease" in all_unreviewed, (
            f"Stale-source disease must appear in unreviewed list. "
            f"summary={kb_summary!r}"
        )
        assert "stale_disease" not in kb_summary["approved_diseases"], (
            f"Stale-source disease must NOT appear in approved list. "
            f"approved={kb_summary['approved_diseases']!r}"
        )


# ────────────────────────────────────────────────────────────────────────
# Migration scenario: status copied from old KB but reviewer dropped
# ────────────────────────────────────────────────────────────────────────

class TestMigrationDropsReviewer:
    def test_migration_from_old_kb_loses_reviewer_caught(self, classify):
        """Simulate a migration that copies the ``status`` field forward
        but drops the ``reviewer`` field along the way.

        Real-world scenario: a one-off script reshapes the KB schema (e.g.,
        renames keys, splits provenance into nested objects) and silently
        omits ``reviewer`` from the new shape. F2 must catch the resulting
        entry as not-approved even though the migration "looks" successful.
        """
        # Old KB (pre-migration) — fully provenanced, would be approved.
        old_entry_prov = {
            "source": "clinician_reviewed",
            "clinician_review_status": "approved",
            "reviewer": "Dr. Old",
            "last_reviewed": "2025-12-01",
            "reviewed_against": "ADA 2024",
        }

        # Simulate migration: copy 'status' and 'source' but drop 'reviewer'
        # and 'last_reviewed'. This is the realistic data-loss pattern.
        migrated_prov = {
            "source": old_entry_prov["source"],
            "clinician_review_status": old_entry_prov["clinician_review_status"],
            # reviewer + last_reviewed dropped by buggy migration
        }
        migrated_entry = _entry("Migrated Disease", migrated_prov)

        # Pre-migration sanity: would have been approved.
        pre_bucket, _ = classify("d_pre", _entry("Pre", dict(old_entry_prov)))
        assert pre_bucket == "approved", (
            "Sanity: pre-migration full provenance should be approved."
        )

        # Post-migration: F2 must catch the missing reviewer/date.
        post_bucket, post_details = classify("d_post", migrated_entry)
        assert post_bucket != "approved", (
            "F2 must reject migrated entry that lost reviewer metadata. "
            f"bucket={post_bucket!r}, details={post_details!r}"
        )
        assert post_bucket == "missing", (
            f"Expected 'missing' for incomplete-provenance migration result, "
            f"got {post_bucket!r}"
        )
