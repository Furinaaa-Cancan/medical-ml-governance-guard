"""publication_gate attestation contract requires verified-signature proof (P0.4).

Before P0.4 the contract trusted only policy flags + block presence, so a report
could claim publication-grade attestation without any verified signature (C1).
It now requires positive proof: signature_verification.verified is true AND the
signer is in the trusted_signers allowlist AND --allow-unsigned was not used.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from test_publication_gate import _build_cmd, _make_all_artifacts, _write_json


def _run(tmp_path, paths):
    cmd = _build_cmd(tmp_path, paths)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    report = json.loads((tmp_path / "report.json").read_text())
    return result, report


def _codes(report):
    return [f.get("code") for f in report.get("failures", [])]


def test_good_attestation_passes(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    result, report = _run(tmp_path, paths)
    assert result.returncode == 0
    assert "execution_attestation_signature_unverified" not in _codes(report)
    assert "execution_attestation_signer_untrusted" not in _codes(report)


def test_unverified_signature_fails(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    ea = json.loads(paths["execution_attestation_report"].read_text())
    ea["summary"]["signature_verification"] = {"verified": False}
    _write_json(paths["execution_attestation_report"], ea)

    result, report = _run(tmp_path, paths)
    assert result.returncode == 2
    assert "execution_attestation_signature_unverified" in _codes(report)


def test_real_benchmark_attestation_passes_contract():
    """PRODUCER-LEVEL: the REAL execution_attestation_gate output must satisfy the
    P0.4 contract.

    The first P0.4 version required summary.trust_verification, which the real gate
    does NOT emit on its success path (it lives only on error/early-return paths) —
    so it rejected every legitimately-attested run, making publication-grade
    unreachable. This pins the contract against ACTUAL producer output (a checked-in
    benchmark attestation, status=pass). Signer-trust itself is enforced by the
    attestation gate's own pass/fail, not by this contract.
    """
    import pytest

    from publication_gate import enforce_execution_attestation_publication_contract

    root = Path(__file__).resolve().parents[1]
    real = next(
        (root / f"experiments/{d}-benchmark/evidence/execution_attestation_report.json"
         for d in ("ckd", "rhc", "sepsis", "support2", "nhanes")
         if (root / f"experiments/{d}-benchmark/evidence/execution_attestation_report.json").exists()),
        None,
    )
    if real is None:
        pytest.skip("no checked-in benchmark attestation report available")
    report = json.loads(real.read_text())
    assert str(report.get("status")).lower() == "pass", f"benchmark attestation not pass: {real}"
    assert "trust_verification" not in report.get("summary", {}), (
        "real success-path summary should NOT carry trust_verification — the test premise"
    )
    failures: list = []
    enforce_execution_attestation_publication_contract(report, failures)
    assert failures == [], (
        f"real attestation {real.name} rejected by contract: {[f.get('code') for f in failures]}"
    )
