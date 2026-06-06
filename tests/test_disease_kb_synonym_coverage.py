"""Regression lock for the disease-KB synonym-coverage audit (v1.3, 2026-06-06).

The audit added common abbreviation/spell-out synonyms of already-represented
definition variables across 11 diseases, adversarially vetted for false-positive
collision risk. These tests pin a representative sample so a future edit that drops
them fails CI, and prove end-to-end that definition_variable_guard now catches a
feature column named with one of the new synonyms.

It also pins the GUARDRAIL: the four deferred clinical-review candidates
(albuminuria / bdi / bdiii / afburden) must NOT silently enter the KB without
clinician sign-off (CLAUDE.md S1 + disease-kb-clinical-review-queue.md).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
KB_PATH = REPO_ROOT / "references" / "methodology" / "disease-definition-knowledge-base.json"
GUARD = REPO_ROOT / "scripts" / "gates" / "definition_variable_guard.py"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


@pytest.fixture(scope="module")
def kb():
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


# A representative new synonym per disease -> the existing canonical var it abbreviates.
EXPECTED = {
    "type_2_diabetes": ["a1c", "glycated_hemoglobin", "fasting_blood_glucose", "t2dm"],
    "hypertension": ["systolic_bp", "diastolic_bp"],
    "coronary_heart_disease": ["ctni", "ctnt"],
    "chronic_kidney_disease": ["gfr", "estimated_gfr"],
    "heart_failure": ["brain_natriuretic_peptide", "left_ventricular_ejection_fraction"],
    "stroke": ["nihss", "cerebrovascular_accident"],
    "copd": ["fev1_fvc", "pefr"],
    "major_depressive_disorder": ["phq9", "cesd"],
    "atrial_fibrillation": ["ekg", "afib"],
    "readmission_30day": ["readmitted", "time_to_readmission"],
}


def test_kb_version_bumped(kb):
    assert kb["version"] == "1.3"
    assert kb["change_log"][-1]["version"] == "1.3"


def test_synonyms_present(kb):
    for disease, toks in EXPECTED.items():
        present = {_norm(x) for x in kb["diseases"][disease]["definition_variables_to_exclude"]}
        for t in toks:
            assert _norm(t) in present, f"{disease} missing synonym {t}"


def test_deferred_candidates_not_silently_added(kb):
    """The four clinical-review-queue candidates must stay OUT of the KB until a
    clinician approves them (no synonym audit may slip a new defining variable in)."""
    t2d = {_norm(x) for x in kb["diseases"]["chronic_kidney_disease"]["definition_variables_to_exclude"]}
    assert _norm("albuminuria") not in t2d
    mdd = {_norm(x) for x in kb["diseases"]["major_depressive_disorder"]["definition_variables_to_exclude"]}
    assert _norm("bdi") not in mdd and _norm("bdiii") not in mdd
    af = {_norm(x) for x in kb["diseases"]["atrial_fibrillation"]["definition_variables_to_exclude"]}
    assert _norm("afburden") not in af


def test_guard_catches_new_synonym_end_to_end(tmp_path):
    """End-to-end: a feature column named with a new synonym ('a1c') is flagged as
    definition leakage for diabetes via the real disease-KB-derived spec path."""
    # minimal phenotype spec sourced from the live KB
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    spec = {"targets": {"dm": {"defining_variables": kb["diseases"]["type_2_diabetes"]["definition_variables_to_exclude"]}}}
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    csv_path = tmp_path / "train.csv"
    csv_path.write_text("age,a1c,bmi,y\n50,5.1,22,0\n", encoding="utf-8")
    report_path = tmp_path / "report.json"

    proc = subprocess.run(
        [sys.executable, str(GUARD), "--target", "dm", "--definition-spec", str(spec_path),
         "--train", str(csv_path), "--target-col", "y", "--cross-sectional", "--report", str(report_path)],
        capture_output=True, text=True, timeout=60, cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 2  # fail-closed on detected leakage
    report = json.loads(report_path.read_text(encoding="utf-8"))
    hits = [h["feature"] for f in report.get("failures", []) if f.get("code") == "definition_variable_leakage"
            for h in f.get("details", {}).get("hits", [])]
    assert "a1c" in hits
