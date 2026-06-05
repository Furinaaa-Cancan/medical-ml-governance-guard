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


def test_seal_survives_real_write_json_roundtrip_with_nan_and_numpy(tmp_path):
    """THE PRODUCTION PATH: build_report_envelope -> write_json -> json.load -> verify.

    write_json runs _sanitize_for_json before persisting (NaN/Inf->null, numpy->
    python, set/tuple->list, bytes->str), so the seal MUST canonicalize the same
    way or a legitimate report — one whose summary holds a NaN/Inf metric or an
    unsanitized numpy/set value, endemic in sklearn/pandas output — false-rejects
    its OWN seal at publication_gate. This round-trips the real producer + the real
    persistence; it FAILS if the seal is computed over un-sanitized bytes.
    """
    import json as _json

    import numpy as np

    from _gate_utils import write_json

    with patch.dict("os.environ", {"MLGG_RUN_KEY": KEY}):
        env = build_report_envelope(
            gate_name="calibration_dca_gate", status="pass", strict_mode=True,
            failures=[], warnings=[],
            summary={
                "ece": float("nan"),
                "slope": float("inf"),
                "n_events": np.int64(42),
                "auroc": np.float32(0.876),
                "fold_ids": {3, 1, 2},
                "raw": b"bytes-value",
            },
        )
    path = tmp_path / "calibration_dca_report.json"
    write_json(path, env)
    loaded = _json.loads(path.read_text(encoding="utf-8"))
    assert verify_envelope_seal(loaded, KEY) is True
