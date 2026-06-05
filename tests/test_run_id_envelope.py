"""Run-binding (P0.1b): build_report_envelope stamps run_id from MLGG_RUN_ID.

The orchestrator issues one run_id per pipeline and exports it as MLGG_RUN_ID;
every gate's envelope then carries it so publication_gate's P0.1a check can
verify all reports describe a single run. The field is optional and
backward-compatible (absent env → omitted), and is reserved against `extra`.
"""
from __future__ import annotations

import os
from unittest.mock import patch

from _gate_framework import build_report_envelope


def _env(**kw):
    return build_report_envelope(
        gate_name="g", status="pass", strict_mode=False,
        failures=[], warnings=[], **kw,
    )


def test_run_id_stamped_when_env_set():
    with patch.dict("os.environ", {"MLGG_RUN_ID": "RUN-XYZ-001"}):
        env = _env()
    assert env["run_id"] == "RUN-XYZ-001"


def test_run_id_absent_when_env_unset():
    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop("MLGG_RUN_ID", None)
        env = _env()
    assert "run_id" not in env


def test_run_id_whitespace_treated_as_absent():
    with patch.dict("os.environ", {"MLGG_RUN_ID": "   "}):
        env = _env()
    assert "run_id" not in env


def test_run_id_cannot_be_clobbered_by_extra():
    # run_id is reserved; a gate passing extra={"run_id": ...} cannot override
    # the orchestrator-issued value (no self-stamping a different run).
    with patch.dict("os.environ", {"MLGG_RUN_ID": "REAL"}):
        env = _env(extra={"run_id": "FORGED"})
    assert env["run_id"] == "REAL"
