#!/usr/bin/env python3
"""
MLGG Compliance Certificate Generator.

Bundles all gate report JSON files into a single signed compliance certificate
that can be submitted alongside a manuscript for independent verification.

Usage:
    # Generate certificate from an evidence directory
    python3 scripts/generate_compliance_certificate.py \
        --evidence-dir evidence/ \
        --request configs/request.json \
        --output certificate.json

    # Verify an existing certificate
    python3 scripts/generate_compliance_certificate.py \
        --verify certificate.json \
        --request configs/request.json

    # Print certificate summary in human-readable form
    python3 scripts/generate_compliance_certificate.py \
        --verify certificate.json --summary
"""

from __future__ import annotations

import sys as _sys; from pathlib import Path as _Path; _CORE_DIR = str(_Path(__file__).resolve().parent.parent / "core"); _sys.path.insert(0, _CORE_DIR) if _CORE_DIR not in _sys.path else None  # noqa: E702

import argparse
import hashlib
import hmac
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from _gate_registry import GATE_REGISTRY


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MLGG_STANDARD_VERSION = "1.0.0"
MLGG_SCHEMA_VERSION = "1.0.0"
CERTIFICATE_EXPIRY_YEARS = 2

# Minimum signing-key length in bytes (HMAC-SHA256 block/key strength).
SIGNING_KEY_MIN_BYTES = 32


class SigningKeyError(RuntimeError):
    """Raised when the configured signing key is set but invalid (fail-closed)."""

# Gate name -> report filename mapping. This must stay registry-derived so the
# certificate cannot drift behind the fail-closed DAG when gates are added.
GATE_NAME_TO_REPORT = {
    gate_name: spec.report_output for gate_name, spec in GATE_REGISTRY.items()
}
GATE_REPORT_FILENAMES = list(GATE_NAME_TO_REPORT.values())

# L1 required gates
L1_REQUIRED_GATES = {
    "request_contract_gate", "manifest_lock", "leakage_gate",
    "split_protocol_gate", "definition_variable_guard",
    "feature_lineage_gate", "imbalance_policy_gate",
    "missingness_policy_gate", "tuning_leakage_gate",
    "model_selection_audit_gate", "feature_engineering_audit_gate",
    "clinical_metrics_gate",
}

# L2 required gates (cumulative)
L2_REQUIRED_GATES = L1_REQUIRED_GATES | {
    "execution_attestation_gate", "covariate_shift_gate",
    "reporting_bias_gate", "calibration_dca_gate",
    "ci_matrix_gate", "distribution_generalization_gate",
    "evaluation_quality_gate", "fairness_equity_gate",
    "generalization_gap_gate", "metric_consistency_gate",
    "permutation_significance_gate", "sample_size_gate",
    "seed_stability_gate",
}

# L3 = all 33 gates
L3_REQUIRED_GATES = set(GATE_NAME_TO_REPORT.keys())


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    """Return hex SHA-256 of a file's contents."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_str(data: str) -> str:
    """Return hex SHA-256 of a UTF-8 string."""
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def hmac_sign(body: str, key: bytes) -> str:
    """Return HMAC-SHA256 hex signature of body string."""
    return hmac.new(key, body.encode("utf-8"), hashlib.sha256).hexdigest()


def hmac_verify(body: str, key: bytes, expected_sig: str) -> bool:
    """Verify HMAC-SHA256 signature in constant time."""
    actual = hmac_sign(body, key)
    return hmac.compare_digest(actual, expected_sig)


def _get_signing_key() -> bytes:
    """
    Get or derive the HMAC signing key (fail-closed).

    Priority:
    1. MLGG_SIGNING_KEY environment variable (hex-encoded, >= 32 bytes).
       If the variable is SET but invalid (not hex) or too short, this is a
       configuration error and we raise SigningKeyError rather than silently
       falling back to a guessable derived key.
    2. Derive from machine-specific entropy ONLY when MLGG_SIGNING_KEY is
       wholly unset. This fallback is NOT secure for cross-machine
       verification, so a clear warning is emitted to stderr.

    Raises:
        SigningKeyError: MLGG_SIGNING_KEY is set but is not valid hex or
            decodes to fewer than SIGNING_KEY_MIN_BYTES bytes.
    """
    # Only an absent (unset) env var triggers the fallback. A set-but-empty or
    # set-but-invalid value is a configuration error and must fail closed.
    if "MLGG_SIGNING_KEY" in os.environ:
        env_key = os.environ["MLGG_SIGNING_KEY"].strip()
        if not env_key:
            raise SigningKeyError(
                "MLGG_SIGNING_KEY is set but empty. Unset it to use the local "
                "derived key, or set it to a hex-encoded key of at least "
                f"{SIGNING_KEY_MIN_BYTES} bytes ({SIGNING_KEY_MIN_BYTES * 2} hex chars)."
            )
        try:
            key = bytes.fromhex(env_key)
        except ValueError as exc:
            raise SigningKeyError(
                "MLGG_SIGNING_KEY is set but is not valid hex. Provide a "
                f"hex-encoded key of at least {SIGNING_KEY_MIN_BYTES} bytes "
                f"({SIGNING_KEY_MIN_BYTES * 2} hex chars)."
            ) from exc
        if len(key) < SIGNING_KEY_MIN_BYTES:
            raise SigningKeyError(
                f"MLGG_SIGNING_KEY decodes to {len(key)} byte(s); at least "
                f"{SIGNING_KEY_MIN_BYTES} bytes are required for HMAC-SHA256."
            )
        return key

    # Env var wholly unset: derive a deterministic local key, warn loudly.
    import socket
    print(
        "WARNING: MLGG_SIGNING_KEY is not set; deriving a machine-local signing "
        "key from hostname+user. This key is NOT secure and NOT portable across "
        "machines. Set MLGG_SIGNING_KEY (hex, >= "
        f"{SIGNING_KEY_MIN_BYTES} bytes) for verifiable certificates.",
        file=sys.stderr,
    )
    seed = f"mlgg-v1-{socket.gethostname()}-{os.getenv('USER', 'unknown')}"
    return hashlib.sha256(seed.encode()).digest()


# ---------------------------------------------------------------------------
# Gate report loading
# ---------------------------------------------------------------------------

def load_gate_report(path: Path) -> Optional[Dict[str, Any]]:
    """Load a gate report JSON, returning None if missing or malformed."""
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError, ValueError):
        return None


def get_gate_status(report: Optional[Dict[str, Any]]) -> str:
    """Extract status from a gate report. Returns 'missing' if report is None."""
    if report is None:
        return "missing"
    return str(report.get("status", "unknown")).lower()


def get_self_critique_scores(evidence_dir: Path) -> Optional[Dict[str, Any]]:
    """Extract the self-critique quality score (0-100) from self_critique_report.json.

    The gate emits a single clamped ``summary.quality_score`` (self_critique_gate
    clamps it to [0, 100]); it has NO per-dimension breakdown. Earlier code read
    non-existent ``dimension_scores``/``scores`` keys, so ``score_total`` was always
    None and the certificate's L3 score floor was silently inert. Return the real
    score under a stable key so ``sum(...)`` yields the quality_score.
    """
    report = load_gate_report(evidence_dir / "self_critique_report.json")
    if report is None:
        return None
    summary = report.get("summary", {})
    qs = summary.get("quality_score") if isinstance(summary, dict) else None
    if not isinstance(qs, (int, float)):
        return None
    return {"quality_score": float(qs)}


def get_reporting_bias_summary(evidence_dir: Path) -> Dict[str, Any]:
    """Extract TRIPOD+AI and PROBAST+AI coverage from reporting_bias_report.json."""
    report_path = evidence_dir / "reporting_bias_report.json"
    report = load_gate_report(report_path)
    if report is None:
        return {}
    summary = report.get("summary", {})
    return {
        "tripod_true_count": summary.get("tripod_true_count", 0),
        "tripod_required_count": summary.get("tripod_required_count", 0),
        "probast_true_count": summary.get("probast_true_count", 0),
        "probast_required_count": summary.get("probast_required_count", 0),
        "overall_risk_of_bias": summary.get("overall_risk_of_bias", "unknown"),
        "claim_level": summary.get("claim_level", "unknown"),
    }


def get_key_metrics(evidence_dir: Path) -> Dict[str, Any]:
    """Extract key performance metrics from publication_gate_report.json or eval report."""
    pub_path = evidence_dir / "publication_gate_report.json"
    pub_report = load_gate_report(pub_path)
    if pub_report:
        summary = pub_report.get("summary", {})
        metrics = summary.get("primary_metrics", summary.get("metrics", {}))
        if metrics:
            return metrics
    return {}


# ---------------------------------------------------------------------------
# publication_gate sealed-verdict consumption (the certifier's root of trust)
# ---------------------------------------------------------------------------

# publication_gate emits summary.compliance_level in {"l1","l2","l3","none"}.
_PUB_LEVEL_TO_CONFORMANCE = {
    "none": "BELOW_L1",
    "l1": "L1-Leakage-Audited",
    "l2": "L2-Statistically-Valid",
    "l3": "L3-Publication-Grade",
}
_CONFORMANCE_RANK = {
    "BELOW_L1": 0,
    "L1-Leakage-Audited": 1,
    "L2-Statistically-Valid": 2,
    "L3-Publication-Grade": 3,
}


def get_publication_gate_verdict(evidence_dir: Path) -> Dict[str, Any]:
    """Load publication_gate's OWN sealed verdict and verify its run-scoped seal.

    The certificate's authority derives from publication_gate, whose
    ``summary.compliance_level`` already folds in component seal verification,
    the LLM advisory floor, the disease-KB block, run-binding and the
    execution-attestation contract. Recomputing tiers here from raw, unsigned
    gate ``status`` fields (as the certificate historically did) bypasses ALL of
    that — an agent able to write ``evidence/*.json`` could mint L3.

    Returns a dict:
        present:           publication_gate_report.json was found
        compliance_level:  mapped to the certificate vocabulary, or None
        seal_active:       MLGG_RUN_KEY is set (sealing is in force)
        seal_verified:     the report carries a valid run-scoped seal
        reason:            human note on trust status
    """
    out: Dict[str, Any] = {
        "present": False,
        "compliance_level": None,
        "seal_active": bool(os.environ.get("MLGG_RUN_KEY")),
        "seal_verified": False,
        "reason": "",
    }
    report = load_gate_report(evidence_dir / "publication_gate_report.json")
    if report is None:
        out["reason"] = "publication_gate_report.json missing or unreadable"
        return out
    out["present"] = True

    summary = report.get("summary", {})
    raw_level = str(summary.get("compliance_level", "")).strip().lower() if isinstance(summary, dict) else ""
    out["compliance_level"] = _PUB_LEVEL_TO_CONFORMANCE.get(raw_level)
    if out["compliance_level"] is None:
        out["reason"] = f"publication_gate compliance_level unrecognized: {raw_level!r}"

    run_key = os.environ.get("MLGG_RUN_KEY")
    if run_key and run_key.strip():
        try:
            from _security import verify_envelope_seal
            if verify_envelope_seal(report, run_key.strip()):
                out["seal_verified"] = True
                out["reason"] = out["reason"] or "run-scoped seal verified"
            else:
                out["reason"] = "publication_gate report seal missing/invalid under active MLGG_RUN_KEY"
        except Exception as exc:  # _security unavailable → cannot verify → untrusted
            out["reason"] = f"seal verification unavailable: {exc}"
    else:
        out["reason"] = out["reason"] or "MLGG_RUN_KEY not set — verdict consumed but NOT cryptographically verified"
    return out


def cap_conformance_to_publication_gate(
    self_level: str, pub_verdict: Dict[str, Any]
) -> Tuple[str, List[str]]:
    """Cap a self-computed conformance level to publication_gate's sealed verdict.

    Rules (fail-closed):
      1. Missing/unsealed/tampered/unverifiable publication_gate verdict →
         refuse outright (BELOW_L1): its verdict cannot be trusted.
      2. No publication_gate verdict at all → BELOW_L1: the certifier has no
         authority to certify above the floor without it.
      3. Otherwise cap to min(self, publication_gate) by tier rank.
    """
    if not pub_verdict["seal_verified"]:
        return "BELOW_L1", [
            "publication_gate verdict requires a verified run seal before any "
            f"certificate tier can be granted: {pub_verdict['reason']}"
        ]

    pub_level = pub_verdict["compliance_level"]
    if pub_level is None:
        return "BELOW_L1", [
            "publication_gate sealed verdict absent — certificate authority requires it"
        ]

    reasons: List[str] = []
    level = self_level
    if _CONFORMANCE_RANK[pub_level] < _CONFORMANCE_RANK[level]:
        reasons.append(f"capped to publication_gate sealed verdict: {pub_level}")
        level = pub_level

    return level, reasons


# ---------------------------------------------------------------------------
# Conformance level determination
# ---------------------------------------------------------------------------

def determine_conformance_level(
    gate_outcomes: Dict[str, str],
    strict_mode: bool,
    score_10dim: Optional[float],
    reporting_summary: Dict[str, Any],
) -> Tuple[str, List[str]]:
    """
    Determine the highest achievable conformance level.

    Returns (level_id, list_of_reasons_for_not_higher).
    """
    reasons_not_l3: List[str] = []
    reasons_not_l2: List[str] = []

    passed = {g for g, s in gate_outcomes.items() if s == "pass"}

    # Check L1
    l1_missing = L1_REQUIRED_GATES - passed
    if l1_missing:
        return "BELOW_L1", [f"L1 gates not passed: {sorted(l1_missing)}"]

    # Check L2
    l2_missing = L2_REQUIRED_GATES - passed
    if l2_missing:
        reasons_not_l2.append(f"L2 gates not passed: {sorted(l2_missing)}")

    tripod_count = reporting_summary.get("tripod_true_count", 0)
    tripod_required = reporting_summary.get("tripod_required_count", 17)
    if tripod_count < 17:
        reasons_not_l2.append(
            f"TRIPOD+AI coverage {tripod_count}/{tripod_required} < 17/27 minimum for L2"
        )

    if reasons_not_l2:
        return "L1-Leakage-Audited", reasons_not_l2

    # Check L3
    l3_missing = L3_REQUIRED_GATES - passed
    if l3_missing:
        reasons_not_l3.append(f"L3 gates not passed: {sorted(l3_missing)}")

    if not strict_mode:
        reasons_not_l3.append("strict_mode=false — L3 requires all gates passed in strict mode")

    if tripod_count < 23:
        reasons_not_l3.append(
            f"TRIPOD+AI coverage {tripod_count}/{tripod_required} < 23/27 minimum for L3"
        )

    rob = reporting_summary.get("overall_risk_of_bias", "unknown")
    if rob != "low":
        reasons_not_l3.append(f"PROBAST+AI overall_risk_of_bias='{rob}' — L3 requires 'low'")

    if score_10dim is not None and score_10dim < 90:
        reasons_not_l3.append(
            f"10-dimension score {score_10dim:.1f}/100 < 90 minimum for L3"
        )

    if reasons_not_l3:
        return "L2-Statistically-Valid", reasons_not_l3

    return "L3-Publication-Grade", []


# ---------------------------------------------------------------------------
# Certificate generation
# ---------------------------------------------------------------------------

def generate_certificate(
    evidence_dir: Path,
    request_path: Optional[Path],
    output_path: Path,
) -> int:
    """Generate an MLGG compliance certificate from gate reports."""
    now = datetime.now(timezone.utc)
    # Safe year addition: handles Feb 29 → Feb 28 for non-leap target years
    try:
        expiry = now.replace(year=now.year + CERTIFICATE_EXPIRY_YEARS)
    except ValueError:
        expiry = now.replace(year=now.year + CERTIFICATE_EXPIRY_YEARS, day=28)

    # Load request.json for study metadata
    study_meta: Dict[str, Any] = {}
    if request_path and request_path.exists():
        try:
            with request_path.open("r", encoding="utf-8") as fh:
                study_meta = json.load(fh)
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    # Collect gate outcomes and evidence hashes
    gate_outcomes: Dict[str, str] = {}
    evidence_manifest: Dict[str, str] = {}
    strict_modes: List[bool] = []

    for gate_name, report_filename in GATE_NAME_TO_REPORT.items():
        report_path = evidence_dir / report_filename
        report = load_gate_report(report_path)
        gate_outcomes[gate_name] = get_gate_status(report)
        if report_path.exists():
            evidence_manifest[report_filename] = sha256_file(report_path)
            if report and isinstance(report.get("strict_mode"), bool):
                strict_modes.append(report["strict_mode"])

    strict_mode = all(strict_modes) if strict_modes else False
    passed_count = sum(1 for s in gate_outcomes.values() if s == "pass")
    failed_count = sum(1 for s in gate_outcomes.values() if s == "fail")
    missing_count = sum(1 for s in gate_outcomes.values() if s == "missing")

    # Scores and summaries
    scores_raw = get_self_critique_scores(evidence_dir)
    score_total: Optional[float] = None
    if scores_raw:
        try:
            score_total = float(sum(scores_raw.values())) if isinstance(scores_raw, dict) else None
        except (TypeError, ValueError):
            score_total = None

    reporting_summary = get_reporting_bias_summary(evidence_dir)
    key_metrics = get_key_metrics(evidence_dir)

    # Determine conformance level
    conformance_level, reasons_for_not_higher = determine_conformance_level(
        gate_outcomes, strict_mode, score_total, reporting_summary
    )

    # Cap to publication_gate's sealed verdict (the certifier's root of trust).
    # The certificate must never grant a tier higher than publication_gate's own
    # sealed decision — which already enforces seal verification, the LLM
    # advisory floor, the disease-KB block and the execution-attestation
    # contract. Without this cap, recomputing tiers from raw gate statuses lets
    # anyone who can write evidence/*.json mint L3.
    pub_verdict = get_publication_gate_verdict(evidence_dir)
    conformance_level, cap_reasons = cap_conformance_to_publication_gate(
        conformance_level, pub_verdict
    )
    reasons_for_not_higher = cap_reasons + reasons_for_not_higher

    conformance_descriptions = {
        "BELOW_L1": "Pipeline does not meet minimum L1 requirements. Results cannot be presented without major remediation.",
        "L1-Leakage-Audited": "Passed all anti-leakage and data integrity gates. Suitable for conference presentations with caveats.",
        "L2-Statistically-Valid": "Passed all statistical validation gates. Suitable for specialist journal submission.",
        "L3-Publication-Grade": "All 33 gates passed in strict mode. Meets Nature Medicine / Lancet Digital Health / JAMA / BMJ requirements.",
    }

    # Build TRIPOD+AI coverage string
    tripod_count = reporting_summary.get("tripod_true_count", 0)
    tripod_req = reporting_summary.get("tripod_required_count", 0)
    tripod_coverage = f"{tripod_count}/{tripod_req}" if tripod_req else "unknown"

    # Build certificate body (without signature)
    certificate_body: Dict[str, Any] = {
        "certificate_id": str(uuid.uuid4()),
        "mlgg_standard_version": MLGG_STANDARD_VERSION,
        "mlgg_schema_version": MLGG_SCHEMA_VERSION,
        "conformance_level": conformance_level,
        "conformance_level_description": conformance_descriptions.get(conformance_level, ""),
        "reasons_for_not_higher_level": reasons_for_not_higher,

        "study": {
            "study_id": study_meta.get("study_id", "unknown"),
            "run_id": study_meta.get("run_id", "unknown"),
            "target_name": study_meta.get("target_name", "unknown"),
            "prediction_unit": study_meta.get("prediction_unit", "unknown"),
            "prediction_type": study_meta.get("prediction_type", "binary"),
        },

        "issuance": {
            "issued_at": now.isoformat(),
            "expires_at": expiry.isoformat(),
            "generator_version": f"mlgg-governance-guard v{MLGG_STANDARD_VERSION}",
            "generation_script": "scripts/generate_compliance_certificate.py",
            "evidence_directory": str(evidence_dir),
        },

        "gates_summary": {
            "total_gates": len(GATE_NAME_TO_REPORT),
            "passed": passed_count,
            "failed": failed_count,
            "missing": missing_count,
            "strict_mode": strict_mode,
            "gate_outcomes": gate_outcomes,
        },

        "publication_gate_verdict": {
            "sealed_compliance_level": pub_verdict["compliance_level"],
            "seal_active": pub_verdict["seal_active"],
            "seal_verified": pub_verdict["seal_verified"],
            "trust_note": pub_verdict["reason"],
        },

        "scores": {
            "score_10dim_total": score_total,
            "score_10dim_breakdown": scores_raw or {},
        },

        "reporting_standards": {
            "tripod_ai_version": "2024",
            "tripod_ai_coverage": tripod_coverage,
            "tripod_ai_required_items_satisfied": tripod_count >= 17,
            "probast_ai_version": "2025",
            "probast_overall_rob": reporting_summary.get("overall_risk_of_bias", "unknown"),
            "probast_domain_rob": reporting_summary.get("probast_domain_rob", {}),
        },

        "key_performance_metrics": key_metrics,

        "evidence_manifest": {
            "manifest_generated_at": now.isoformat(),
            "files": evidence_manifest,
        },
    }

    # Sign the certificate body (fail-closed on a set-but-invalid signing key)
    try:
        signing_key = _get_signing_key()
    except SigningKeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    body_canonical = json.dumps(certificate_body, sort_keys=True, separators=(",", ":"))
    signature = hmac_sign(body_canonical, signing_key)

    certificate_body["integrity"] = {
        "signature_algorithm": "HMAC-SHA256",
        "signature_scope": "All fields except this integrity block",
        "signature": signature,
        "body_sha256": sha256_str(body_canonical),
        "verification_command": (
            f"python3 scripts/generate_compliance_certificate.py "
            f"--verify {output_path} --request {request_path or 'configs/request.json'}"
        ),
    }

    # Write certificate
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(certificate_body, fh, indent=2, ensure_ascii=False)

    # Print summary
    _print_certificate_summary(certificate_body)

    print(f"\n  Certificate written to: {output_path}")
    return 0


# ---------------------------------------------------------------------------
# Certificate verification
# ---------------------------------------------------------------------------

def verify_certificate(
    certificate_path: Path,
    print_summary: bool = False,
) -> int:
    """Verify an MLGG compliance certificate's signature and integrity."""
    if not certificate_path.exists():
        print(f"ERROR: Certificate file not found: {certificate_path}", file=sys.stderr)
        return 2

    try:
        with certificate_path.open("r", encoding="utf-8") as fh:
            cert = json.load(fh)
    except Exception as exc:
        print(f"ERROR: Cannot parse certificate JSON: {exc}", file=sys.stderr)
        return 2

    integrity = cert.get("integrity", {})
    stored_sig = integrity.get("signature", "")
    stored_body_sha256 = integrity.get("body_sha256", "")

    # Reconstruct body without integrity block
    cert_body = {k: v for k, v in cert.items() if k != "integrity"}
    body_canonical = json.dumps(cert_body, sort_keys=True, separators=(",", ":"))

    # Check body hash
    actual_body_sha256 = sha256_str(body_canonical)
    if actual_body_sha256 != stored_body_sha256:
        print("VERIFICATION FAILED: Certificate body has been tampered with.", file=sys.stderr)
        print(f"  Expected body SHA-256: {stored_body_sha256}", file=sys.stderr)
        print(f"  Actual body SHA-256:   {actual_body_sha256}", file=sys.stderr)
        return 2

    # Check HMAC signature (fail-closed on a set-but-invalid signing key)
    try:
        signing_key = _get_signing_key()
    except SigningKeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not hmac_verify(body_canonical, signing_key, stored_sig):
        print(
            "VERIFICATION FAILED: HMAC signature is invalid.\n"
            "  Note: Cross-machine verification requires the same MLGG_SIGNING_KEY env var.",
            file=sys.stderr,
        )
        return 2

    # Don't overclaim authenticity when the signature was made under the
    # machine-derived fallback key: anyone on the same host/user can recompute
    # it, so the signature proves integrity locally but is NOT independent proof.
    cert_id = cert.get("certificate_id", "?")
    if os.environ.get("MLGG_SIGNING_KEY"):
        print(f"VERIFICATION PASSED: Certificate {cert_id} signature is valid (portable key).")
    else:
        print(
            f"VERIFICATION PASSED (LOCAL KEY): Certificate {cert_id} signature is valid under a "
            "machine-derived key — integrity checked locally, but NOT independently verifiable. "
            "Set MLGG_SIGNING_KEY for portable, third-party-verifiable proof."
        )
    print(f"  Conformance level: {cert.get('conformance_level', 'unknown')}")
    print(f"  Study ID:          {cert.get('study', {}).get('study_id', 'unknown')}")
    print(f"  Issued at:         {cert.get('issuance', {}).get('issued_at', 'unknown')}")
    print(f"  Expires at:        {cert.get('issuance', {}).get('expires_at', 'unknown')}")

    if print_summary:
        _print_certificate_summary(cert)

    return 0


# ---------------------------------------------------------------------------
# Summary printing
# ---------------------------------------------------------------------------

def _print_certificate_summary(cert: Dict[str, Any]) -> None:
    """Print a human-readable certificate summary to stdout."""
    level = cert.get("conformance_level", "unknown")
    study = cert.get("study", {})
    gates = cert.get("gates_summary", {})
    scores = cert.get("scores", {})
    reporting = cert.get("reporting_standards", {})

    level_icons = {
        "L3-Publication-Grade": "★★★",
        "L2-Statistically-Valid": "★★☆",
        "L1-Leakage-Audited": "★☆☆",
        "BELOW_L1": "✗✗✗",
    }

    print("\n" + "=" * 68)
    print(" MLGG COMPLIANCE CERTIFICATE SUMMARY")
    print("=" * 68)
    print(f"  Study ID:          {study.get('study_id', 'unknown')}")
    print(f"  Prediction type:   {study.get('prediction_type', 'binary')}")
    print(f"  MLGG Version:      v{cert.get('mlgg_standard_version', '?')}")
    print()
    print(f"  Conformance Level: {level_icons.get(level, '?')} {level}")
    print(f"  {cert.get('conformance_level_description', '')}")
    print()
    print(f"  Gates passed:  {gates.get('passed', 0)}/{gates.get('total_gates', 33)}")
    print(f"  Gates failed:  {gates.get('failed', 0)}")
    print(f"  Gates missing: {gates.get('missing', 0)}")
    print(f"  Strict mode:   {'YES' if gates.get('strict_mode') else 'NO'}")
    print()

    score_total = scores.get("score_10dim_total")
    if score_total is not None:
        print(f"  10-dim Score:  {score_total:.1f}/100")

    tripod = reporting.get("tripod_ai_coverage", "?")
    rob = reporting.get("probast_overall_rob", "?")
    print(f"  TRIPOD+AI:     {tripod} items satisfied")
    print(f"  PROBAST ROB:   {rob}")
    print()

    reasons = cert.get("reasons_for_not_higher_level", [])
    if reasons:
        print("  Gaps (reasons for not reaching next level):")
        for r in reasons[:5]:
            print(f"    - {r}")
        if len(reasons) > 5:
            print(f"    ... and {len(reasons) - 5} more")
        print()

    print(f"  Certificate ID: {cert.get('certificate_id', 'unknown')}")
    print("=" * 68)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MLGG Compliance Certificate Generator and Verifier.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command")

    # generate (default when --evidence-dir given)
    gen = subparsers.add_parser("generate", help="Generate compliance certificate")
    gen.add_argument("--evidence-dir", required=True, help="Directory containing gate report JSONs")
    gen.add_argument("--request", help="Path to request.json (for study metadata)")
    gen.add_argument("--output", default="mlgg-compliance-certificate.json",
                     help="Output certificate path (default: mlgg-compliance-certificate.json)")

    # verify
    ver = subparsers.add_parser("verify", help="Verify an existing certificate")
    ver.add_argument("certificate", help="Path to certificate JSON to verify")
    ver.add_argument("--summary", action="store_true", help="Print full summary")
    ver.add_argument("--request", help="Path to request.json (unused, for API symmetry)")

    # Support flat flags for backward compatibility
    parser.add_argument("--evidence-dir", help=argparse.SUPPRESS)
    parser.add_argument("--request", help=argparse.SUPPRESS)
    parser.add_argument("--output", help=argparse.SUPPRESS)
    parser.add_argument("--verify", help=argparse.SUPPRESS)
    parser.add_argument("--summary", action="store_true", help=argparse.SUPPRESS)

    return parser.parse_args()


def main() -> int:
    """Entry point."""
    args = parse_args()

    # Handle flat flags (legacy interface)
    if args.verify:
        return verify_certificate(
            Path(args.verify).expanduser().resolve(),
            print_summary=bool(args.summary),
        )

    if args.evidence_dir:
        evidence_dir = Path(args.evidence_dir).expanduser().resolve()
        request_path = Path(args.request).expanduser().resolve() if args.request else None
        output_path = Path(args.output or "mlgg-compliance-certificate.json").expanduser().resolve()
        return generate_certificate(evidence_dir, request_path, output_path)

    # Handle subcommands
    if args.command == "generate":
        evidence_dir = Path(args.evidence_dir).expanduser().resolve()
        request_path = Path(args.request).expanduser().resolve() if args.request else None
        output_path = Path(args.output).expanduser().resolve()
        return generate_certificate(evidence_dir, request_path, output_path)

    if args.command == "verify":
        return verify_certificate(
            Path(args.certificate).expanduser().resolve(),
            print_summary=bool(args.summary),
        )

    print("Usage: python3 scripts/generate_compliance_certificate.py --evidence-dir <dir> --output <out.json>")
    print("       python3 scripts/generate_compliance_certificate.py --verify <certificate.json>")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
