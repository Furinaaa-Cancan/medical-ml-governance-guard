"""Trusted-signers allowlist loads fail-closed (P0.5).

The allowlist is what makes signature verification a real control: a valid
signature only proves someone held a private key; the allowlist proves that key
is authorized. load_trusted_signers must return None (→ caller fails closed) on
any problem — missing file, bad JSON, wrong shape, or no valid entries — so a
missing/empty allowlist can never be read as "everyone is trusted".
"""
from __future__ import annotations

import json
from pathlib import Path

from execution_attestation_gate import load_trusted_signers

FP = "a" * 64  # a syntactically valid 64-hex fingerprint


def _write(path: Path, obj) -> Path:
    path.write_text(json.dumps(obj), encoding="utf-8")
    return path


def _codes(failures):
    return [f.get("code") for f in failures]


def test_missing_file_fails_closed(tmp_path: Path):
    failures = []
    result = load_trusted_signers(tmp_path / "nope.json", failures)
    assert result is None
    assert "trusted_signers_missing" in _codes(failures)


def test_valid_allowlist_loads(tmp_path: Path):
    failures = []
    p = _write(tmp_path / "ts.json", {"version": "1.0", "signers": [{"fingerprint_sha256": FP, "signer_name": "ci"}]})
    result = load_trusted_signers(p, failures)
    assert result is not None
    assert len(result) == 1
    assert result[0]["fingerprint_sha256"] == FP  # normalized lower-case
    assert failures == []


def test_empty_signers_fails_closed(tmp_path: Path):
    failures = []
    p = _write(tmp_path / "ts.json", {"version": "1.0", "signers": []})
    assert load_trusted_signers(p, failures) is None
    assert "trusted_signers_empty" in _codes(failures)


def test_bad_fingerprint_dropped_then_empty_fails_closed(tmp_path: Path):
    failures = []
    p = _write(tmp_path / "ts.json", {"signers": [{"fingerprint_sha256": "too-short"}]})
    assert load_trusted_signers(p, failures) is None
    assert "trusted_signers_bad_fingerprint" in _codes(failures)
    assert "trusted_signers_empty" in _codes(failures)


def test_invalid_json_fails_closed(tmp_path: Path):
    failures = []
    p = tmp_path / "ts.json"
    p.write_text("{ not json", encoding="utf-8")
    assert load_trusted_signers(p, failures) is None
    assert "trusted_signers_invalid_json" in _codes(failures)


def test_non_object_root_fails_closed(tmp_path: Path):
    failures = []
    p = _write(tmp_path / "ts.json", ["not", "an", "object"])
    assert load_trusted_signers(p, failures) is None
    assert "trusted_signers_invalid_shape" in _codes(failures)
