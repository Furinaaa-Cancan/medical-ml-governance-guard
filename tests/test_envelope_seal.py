"""Producer-side run-scoped seal (P0.3b): build_report_envelope seals on write.

When the orchestrator has issued MLGG_RUN_KEY, every gate envelope is sealed
with a keyed HMAC over its complete content. The seal verifies for the
untouched report and fails after any post-write tamper. Backward-compatible:
no key → no seal field.
"""
from __future__ import annotations

import os
from unittest.mock import patch

from _gate_framework import build_report_envelope
from _security import verify_envelope_seal

KEY = "a" * 64


def _env(**kw):
    return build_report_envelope(
        gate_name="leakage_gate", status="pass", strict_mode=True,
        failures=[], warnings=[], summary={"x": 1}, **kw,
    )


def test_envelope_sealed_and_verifiable_when_key_set():
    with patch.dict("os.environ", {"MLGG_RUN_KEY": KEY}):
        env = _env()
    assert "seal" in env
    assert verify_envelope_seal(env, KEY) is True


def test_no_seal_when_key_absent():
    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop("MLGG_RUN_KEY", None)
        env = _env()
    assert "seal" not in env


def test_seal_detects_post_write_tamper():
    with patch.dict("os.environ", {"MLGG_RUN_KEY": KEY}):
        env = _env()
    env["status"] = "fail"  # flip after sealing
    assert verify_envelope_seal(env, KEY) is False


def test_seal_and_run_id_coexist():
    with patch.dict("os.environ", {"MLGG_RUN_KEY": KEY, "MLGG_RUN_ID": "R-1"}):
        env = _env()
    assert env["run_id"] == "R-1"
    assert verify_envelope_seal(env, KEY) is True


def test_extra_cannot_preset_seal():
    # a gate passing extra={"seal": ...} cannot forge it; the real seal wins.
    with patch.dict("os.environ", {"MLGG_RUN_KEY": KEY}):
        env = _env(extra={"seal": "forged"})
    assert env["seal"] != "forged"
    assert verify_envelope_seal(env, KEY) is True
