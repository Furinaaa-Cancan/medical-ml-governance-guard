"""Adversarial tests: the compliance certificate must consume publication_gate's
SEALED verdict and never grant a tier higher than it.

Threat model: an agent/user able to write evidence/*.json sets every gate
status to "pass" and tries to mint a compliance tier. The certificate must
refuse unless publication_gate's own sealed verdict (which already enforces
seal verification, the LLM advisory floor, the disease-KB block and the
execution-attestation contract) grants it under a cryptographically verified
run seal.

This is the real-producer round-trip the prior security-review gap called for:
forged evidence in → certificate refuses, sealed verdict in → certificate caps.
"""
from __future__ import annotations

import json
from pathlib import Path

import generate_compliance_certificate as gcc

# A deterministic 32-byte run key (hex) standing in for the orchestrator's
# MLGG_RUN_KEY. An attacker editing evidence/*.json does not hold it.
RUN_KEY = "ab" * 32
WRONG_KEY = "cd" * 32


def _seal(report: dict, key: str) -> dict:
    """Attach a valid run-scoped seal computed with `key` (mirrors the gate)."""
    from _security import compute_envelope_seal

    sealed = dict(report)
    sealed["seal"] = compute_envelope_seal(sealed, key)
    return sealed


def _build_evidence(
    evidence_dir: Path,
    *,
    pub_compliance_level: str | None = "l3",
    seal_pub_with: str | None = None,
    full_l3_self: bool = True,
) -> None:
    """Write an all-pass evidence dir.

    pub_compliance_level: value for publication_gate summary.compliance_level
        ("l1"/"l2"/"l3"/"none"); None omits the field entirely.
    seal_pub_with: if set, seal the publication_gate report with this key.
    full_l3_self: also write reporting_bias + self_critique rich enough that the
        certificate's OWN (pre-cap) self-level reaches L3, so a test isolates the
        cap rather than the self-level.
    """
    evidence_dir.mkdir(parents=True, exist_ok=True)
    base = {"status": "pass", "failure_count": 0, "strict_mode": True}
    for fname in gcc.GATE_REPORT_FILENAMES:
        (evidence_dir / fname).write_text(json.dumps(base))

    if full_l3_self:
        (evidence_dir / "reporting_bias_report.json").write_text(json.dumps({
            "status": "pass", "strict_mode": True,
            "summary": {
                "tripod_true_count": 25, "tripod_required_count": 27,
                "overall_risk_of_bias": "low",
            },
        }))
        (evidence_dir / "self_critique_report.json").write_text(json.dumps({
            "status": "pass", "strict_mode": True,
            "summary": {"quality_score": 95.0},
        }))

    pub = {
        "status": "pass", "strict_mode": True, "gate_name": "publication_gate",
        "summary": {},
    }
    if pub_compliance_level is not None:
        pub["summary"]["compliance_level"] = pub_compliance_level
    if seal_pub_with is not None:
        pub = _seal(pub, seal_pub_with)
    (evidence_dir / "publication_gate_report.json").write_text(json.dumps(pub))


def _gen(evidence_dir: Path, tmp_path: Path) -> dict:
    out = tmp_path / "cert.json"
    rc = gcc.generate_certificate(evidence_dir, None, out)
    assert rc == 0
    return json.loads(out.read_text())


# ── get_publication_gate_verdict ─────────────────────────────────────────────

class TestPublicationGateVerdict:
    def test_sealed_report_with_correct_key_verifies(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MLGG_RUN_KEY", RUN_KEY)
        _build_evidence(tmp_path, pub_compliance_level="l3", seal_pub_with=RUN_KEY)
        v = gcc.get_publication_gate_verdict(tmp_path)
        assert v["present"] and v["seal_active"] and v["seal_verified"]
        assert v["compliance_level"] == "L3-Publication-Grade"

    def test_wrong_key_seal_fails_verification(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MLGG_RUN_KEY", RUN_KEY)
        _build_evidence(tmp_path, pub_compliance_level="l3", seal_pub_with=WRONG_KEY)
        v = gcc.get_publication_gate_verdict(tmp_path)
        assert v["seal_active"] and v["seal_verified"] is False
        assert "invalid" in v["reason"].lower() or "missing" in v["reason"].lower()

    def test_unsealed_under_active_key_not_verified(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MLGG_RUN_KEY", RUN_KEY)
        _build_evidence(tmp_path, pub_compliance_level="l3", seal_pub_with=None)
        v = gcc.get_publication_gate_verdict(tmp_path)
        assert v["seal_active"] and v["seal_verified"] is False

    def test_no_run_key_consumes_but_not_verified(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MLGG_RUN_KEY", raising=False)
        _build_evidence(tmp_path, pub_compliance_level="l2", seal_pub_with=None)
        v = gcc.get_publication_gate_verdict(tmp_path)
        assert v["seal_active"] is False and v["seal_verified"] is False
        assert v["compliance_level"] == "L2-Statistically-Valid"

    def test_missing_report(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MLGG_RUN_KEY", raising=False)
        v = gcc.get_publication_gate_verdict(tmp_path)  # empty dir
        assert v["present"] is False and v["compliance_level"] is None


# ── cap_conformance_to_publication_gate ──────────────────────────────────────

class TestCapConformance:
    def _verdict(self, **kw):
        base = {"present": True, "compliance_level": "L3-Publication-Grade",
                "seal_active": True, "seal_verified": True, "reason": ""}
        base.update(kw)
        return base

    def test_active_key_unverified_refuses(self):
        v = self._verdict(seal_verified=False, reason="seal invalid")
        level, reasons = gcc.cap_conformance_to_publication_gate("L3-Publication-Grade", v)
        assert level == "BELOW_L1"
        assert any("requires a verified run seal" in r for r in reasons)

    def test_absent_verdict_refuses(self):
        v = self._verdict(compliance_level=None, seal_active=False, seal_verified=False)
        level, _ = gcc.cap_conformance_to_publication_gate("L3-Publication-Grade", v)
        assert level == "BELOW_L1"

    def test_caps_to_lower_sealed_verdict(self):
        v = self._verdict(compliance_level="L1-Leakage-Audited")
        level, reasons = gcc.cap_conformance_to_publication_gate("L3-Publication-Grade", v)
        assert level == "L1-Leakage-Audited"
        assert any("capped" in r for r in reasons)

    def test_l3_granted_when_self_and_verdict_agree_and_sealed(self):
        v = self._verdict(compliance_level="L3-Publication-Grade", seal_verified=True)
        level, reasons = gcc.cap_conformance_to_publication_gate("L3-Publication-Grade", v)
        assert level == "L3-Publication-Grade"
        assert reasons == []

    def test_unverified_verdict_refused_without_run_key(self):
        # no run key → verdict is unsigned/unverified, so no certification tier is trusted
        v = self._verdict(seal_active=False, seal_verified=False)
        level, reasons = gcc.cap_conformance_to_publication_gate("L3-Publication-Grade", v)
        assert level == "BELOW_L1"
        assert any("requires a verified run seal" in r for r in reasons)


# ── end-to-end: generate_certificate refuses forged evidence ─────────────────

class TestCertificateEndToEnd:
    def test_forged_all_pass_l3_without_seal_is_refused(self, tmp_path, monkeypatch):
        """The headline attack: forge every gate pass + publication_gate 'l3' but
        with NO valid seal, under an active run key → must NOT certify L3."""
        monkeypatch.setenv("MLGG_RUN_KEY", RUN_KEY)
        evidence = tmp_path / "evidence"
        _build_evidence(evidence, pub_compliance_level="l3", seal_pub_with=None)
        cert = _gen(evidence, tmp_path)
        assert cert["conformance_level"] == "BELOW_L1"
        assert cert["publication_gate_verdict"]["seal_verified"] is False

    def test_forged_l3_sealed_with_attacker_key_is_refused(self, tmp_path, monkeypatch):
        """Attacker seals their forged 'l3' with a key they hold, but it's not the
        orchestrator's MLGG_RUN_KEY → seal verification fails → refused."""
        monkeypatch.setenv("MLGG_RUN_KEY", RUN_KEY)
        evidence = tmp_path / "evidence"
        _build_evidence(evidence, pub_compliance_level="l3", seal_pub_with=WRONG_KEY)
        cert = _gen(evidence, tmp_path)
        assert cert["conformance_level"] == "BELOW_L1"

    def test_forged_l2_without_run_key_is_refused(self, tmp_path, monkeypatch):
        """No active run key means publication_gate's level is unverified.

        Without this guard an offline attacker can forge every gate pass plus
        publication_gate "l2" and mint an L2 certificate from unsigned JSON.
        """
        monkeypatch.delenv("MLGG_RUN_KEY", raising=False)
        evidence = tmp_path / "evidence"
        _build_evidence(evidence, pub_compliance_level="l2", seal_pub_with=None)
        cert = _gen(evidence, tmp_path)
        assert cert["conformance_level"] == "BELOW_L1"
        assert cert["publication_gate_verdict"]["seal_verified"] is False

    def test_caps_to_sealed_l1_even_when_all_gates_pass(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MLGG_RUN_KEY", RUN_KEY)
        evidence = tmp_path / "evidence"
        _build_evidence(evidence, pub_compliance_level="l1", seal_pub_with=RUN_KEY)
        cert = _gen(evidence, tmp_path)
        assert cert["conformance_level"] == "L1-Leakage-Audited"

    def test_absent_compliance_level_floors_below_l1(self, tmp_path, monkeypatch):
        monkeypatch.delenv("MLGG_RUN_KEY", raising=False)
        evidence = tmp_path / "evidence"
        _build_evidence(evidence, pub_compliance_level=None, seal_pub_with=None)
        cert = _gen(evidence, tmp_path)
        assert cert["conformance_level"] == "BELOW_L1"

    def test_happy_path_sealed_l3_is_granted(self, tmp_path, monkeypatch):
        """Positive control: a genuinely sealed L3 verdict + full L3 self-evidence
        + verified run seal → the certificate DOES grant L3 (fix isn't over-blocking)."""
        monkeypatch.setenv("MLGG_RUN_KEY", RUN_KEY)
        evidence = tmp_path / "evidence"
        _build_evidence(evidence, pub_compliance_level="l3", seal_pub_with=RUN_KEY,
                        full_l3_self=True)
        cert = _gen(evidence, tmp_path)
        assert cert["conformance_level"] == "L3-Publication-Grade"
        assert cert["publication_gate_verdict"]["seal_verified"] is True
