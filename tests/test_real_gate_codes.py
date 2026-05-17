"""Smoke tests for the W8-W7 real-gate-code harvester."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "diagnostics" / "harvest_real_gate_codes.py"
HARVEST_JSON = REPO / "references" / "retrieval_eval" / "real_gate_codes_harvest.json"


def test_harvester_script_runs(tmp_path: Path) -> None:
    """End-to-end: script exits cleanly and prints the headline summary.

    Writes to tmp_path so the committed harvest JSON (curated from a
    full-corpus run) stays intact — CI's reduced experiments/ slice
    cannot regenerate it, and clobbering it breaks
    ``test_harvested_json_is_valid_and_nonempty``.
    """
    out = tmp_path / "harvest.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(out)],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "harvested codes for" in result.stdout


def test_harvested_json_is_valid_and_nonempty() -> None:
    """The output file is valid JSON and (when experiments/ has data) non-empty."""
    if not HARVEST_JSON.exists():
        pytest.skip("harvest not yet run")
    data = json.loads(HARVEST_JSON.read_text())
    assert isinstance(data, dict)
    # If experiments/ has any reports, there should be at least one gate
    experiments_has_reports = any(
        (REPO / "experiments").rglob("*report*.json")
    )
    if experiments_has_reports:
        assert data, "expected at least one gate with codes"
        for gate, codes in data.items():
            assert isinstance(gate, str) and gate
            assert isinstance(codes, dict)
            for code, count in codes.items():
                assert isinstance(code, str) and code
                assert isinstance(count, int) and count > 0


def test_harvester_handles_mixed_shapes(tmp_path: Path) -> None:
    """Unit test: walker collects both `failures[].code` and `failure_codes[]`."""
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        import harvest_real_gate_codes as mod
    finally:
        sys.path.pop(0)

    sample = {
        "gate_name": "leakage_gate",
        "failures": [
            {"code": "temporal_overlap"},
            {"code": "patient_overlap"},
        ],
        "nested": {
            "gate_name": "clinical_metrics_gate",
            "failure_codes": ["clinical_floor_ppv_not_met"],
        },
    }
    result = mod.harvest.__wrapped__ if hasattr(mod.harvest, "__wrapped__") else None
    # Use the lower-level walker directly for unit-level coverage.
    from collections import Counter, defaultdict

    acc: dict[str, Counter] = defaultdict(Counter)
    mod._walk(sample, acc)
    assert acc["leakage_gate"]["temporal_overlap"] == 1
    assert acc["leakage_gate"]["patient_overlap"] == 1
    assert acc["clinical_metrics_gate"]["clinical_floor_ppv_not_met"] == 1
