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


def test_untrusted_signer_fails(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    ea = json.loads(paths["execution_attestation_report"].read_text())
    ea["summary"]["trust_verification"] = {"checked": True, "trusted": False, "allow_unsigned_mode": False}
    _write_json(paths["execution_attestation_report"], ea)

    result, report = _run(tmp_path, paths)
    assert result.returncode == 2
    assert "execution_attestation_signer_untrusted" in _codes(report)


def test_allow_unsigned_mode_fails(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    ea = json.loads(paths["execution_attestation_report"].read_text())
    ea["summary"]["trust_verification"]["allow_unsigned_mode"] = True
    _write_json(paths["execution_attestation_report"], ea)

    result, report = _run(tmp_path, paths)
    assert result.returncode == 2
    assert "execution_attestation_allow_unsigned" in _codes(report)


def test_missing_trust_block_fails(tmp_path: Path):
    paths = _make_all_artifacts(tmp_path)
    ea = json.loads(paths["execution_attestation_report"].read_text())
    del ea["summary"]["trust_verification"]
    _write_json(paths["execution_attestation_report"], ea)

    result, report = _run(tmp_path, paths)
    assert result.returncode == 2
    assert "execution_attestation_trust_missing" in _codes(report)
