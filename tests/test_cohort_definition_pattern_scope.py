"""Regression test for disease-specific pattern scoping in
cohort_definition_gate.COHORT_OUTCOME_DEFINITION_LEAKAGE.

Bug surfaced on SUPPORT2 dogfood (target = 30-day mortality):
  columns matching ['glucose'] were flagged as definition leakage
  because `glucose` was in a flat _DEF_PATTERNS list mixing diabetes-
  specific diagnostic lab names with target-adjacent patterns. For a
  mortality target, `glucose` is a legitimate ICU vital sign.

Fix: split patterns into generic (always fire) + disease-specific
(fire only when target matches disease).
"""
from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
GATE = PROJECT_ROOT / "scripts" / "gates" / "cohort_definition_gate.py"


def _write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)


def _run_gate(data_csv: Path, tmp: Path, target_col: str = "y", id_col: str = "patient_id"):
    report = tmp / "cohort_definition_report.json"
    cmd = [
        sys.executable,
        str(GATE),
        "--data", str(data_csv),
        "--target-col", target_col,
        "--id-col", id_col,
        "--report", str(report),
    ]
    subprocess.run(cmd, check=False, capture_output=True)
    return json.loads(report.read_text()) if report.exists() else {}


def test_glucose_not_flagged_for_mortality_dataset(tmp_path: Path) -> None:
    """Reproduces the SUPPORT2 false-positive: target is mortality, data has
    `glucose` as a vital sign. Must NOT appear in COHORT_OUTCOME_DEFINITION_LEAKAGE
    suspected_columns."""
    csv_path = tmp_path / "mortality_data.csv"
    # Filename has no disease name → no diabetes inference; glucose is vital sign here.
    _write_csv(
        csv_path,
        ["patient_id", "event_time", "y", "glucose", "age", "meanbp"],
        [[i, i, i % 2, 120 + i, 50 + (i % 30), 80 + (i % 20)] for i in range(200)],
    )
    result = _run_gate(csv_path, tmp_path)
    warns = result.get("warnings") or []
    for w in warns:
        if w.get("code") == "COHORT_OUTCOME_DEFINITION_LEAKAGE":
            suspected = (w.get("details") or {}).get("suspected_columns") or []
            assert "glucose" not in suspected, (
                f"glucose should not be flagged for a non-diabetes dataset. "
                f"Suspected: {suspected}. Inferred disease: "
                f"{(w.get('details') or {}).get('inferred_target_disease')}"
            )


def test_glucose_flagged_for_diabetes_filename(tmp_path: Path) -> None:
    """When the dataset filename contains 'diabetes', target-disease inference
    activates the diabetes-specific pattern list and glucose IS flagged."""
    csv_path = tmp_path / "diabetes_cohort.csv"  # filename triggers inference
    _write_csv(
        csv_path,
        ["patient_id", "event_time", "y", "glucose", "age", "bmi"],
        [[i, i, i % 2, 120 + i, 50 + (i % 30), 25 + (i % 10)] for i in range(200)],
    )
    result = _run_gate(csv_path, tmp_path)
    flagged = False
    for w in result.get("warnings") or []:
        if w.get("code") == "COHORT_OUTCOME_DEFINITION_LEAKAGE":
            suspected = (w.get("details") or {}).get("suspected_columns") or []
            if "glucose" in suspected:
                flagged = True
                # Also verify the scope metadata is correct
                assert (w.get("details") or {}).get("inferred_target_disease") == "diabetes"
                break
    assert flagged, (
        "glucose MUST be flagged when the target dataset is diabetes-related; "
        "HbA1c/glucose are canonical diabetes definition variables."
    )


def test_mortality_pattern_always_flagged(tmp_path: Path) -> None:
    """mortality/death/died/readmit etc. are generic outcome-adjacent — fire
    regardless of inferred disease."""
    csv_path = tmp_path / "generic_cohort.csv"
    _write_csv(
        csv_path,
        ["patient_id", "event_time", "y", "mortality_score", "age"],
        [[i, i, i % 2, i * 0.01, 50 + (i % 30)] for i in range(200)],
    )
    result = _run_gate(csv_path, tmp_path)
    found = False
    for w in result.get("warnings") or []:
        if w.get("code") == "COHORT_OUTCOME_DEFINITION_LEAKAGE":
            suspected = (w.get("details") or {}).get("suspected_columns") or []
            if any("mortality" in c.lower() for c in suspected):
                found = True
                break
    assert found, "Generic pattern 'mortality' must be flagged for any dataset"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
