"""Run-scoped report seal primitive (asymmetric two-tier, P0.2/P0.3).

The seal is a keyed HMAC over a report's canonical bytes. It lets
publication_gate detect a hand-edited gate report: tampering changes the
canonical bytes, and the editor cannot recompute a valid seal without the
per-run key (which the orchestrator never writes to disk).
"""
from __future__ import annotations

from _security import (
    canonical_report_bytes,
    compute_envelope_seal,
    verify_envelope_seal,
)

KEY = "0123456789abcdef0123456789abcdef"


def _report():
    return {
        "gate_name": "leakage_gate",
        "status": "pass",
        "failure_count": 0,
        "run_id": "RUN-1",
        "summary": {"k": "v"},
    }


def test_seal_is_deterministic():
    r = _report()
    assert compute_envelope_seal(r, KEY) == compute_envelope_seal(dict(r), KEY)


def test_seal_excludes_itself():
    r = _report()
    bare = compute_envelope_seal(r, KEY)
    r["seal"] = bare
    # adding the seal field must not change the computed seal
    assert compute_envelope_seal(r, KEY) == bare


def test_canonical_bytes_order_independent():
    a = {"b": 2, "a": 1, "seal": "x"}
    b = {"a": 1, "b": 2}
    assert canonical_report_bytes(a) == canonical_report_bytes(b)


def test_verify_true_for_sealed_report():
    r = _report()
    r["seal"] = compute_envelope_seal(r, KEY)
    assert verify_envelope_seal(r, KEY) is True


def test_verify_false_on_content_tamper():
    r = _report()
    r["seal"] = compute_envelope_seal(r, KEY)
    r["status"] = "fail"  # flip after sealing → seal no longer matches
    assert verify_envelope_seal(r, KEY) is False


def test_verify_false_on_wrong_key():
    r = _report()
    r["seal"] = compute_envelope_seal(r, KEY)
    assert verify_envelope_seal(r, "f" * 32) is False


def test_verify_false_when_seal_missing():
    assert verify_envelope_seal(_report(), KEY) is False


def test_str_and_bytes_key_equivalent():
    r = _report()
    assert compute_envelope_seal(r, KEY) == compute_envelope_seal(r, KEY.encode("utf-8"))
