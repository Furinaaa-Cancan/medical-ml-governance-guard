"""P0-2 regression tests for disease KB provenance.

Ensures:
1. Every disease entry has a `provenance` block with required fields.
2. `clinician_review_status` is one of the allowed values.
3. Consumers (task_aware_validate) propagate `kb_provenance` into issue details.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
KB_PATH = PROJECT_ROOT / "references" / "methodology" / "disease-definition-knowledge-base.json"

REQUIRED_PROVENANCE_FIELDS = {
    "source",
    "clinician_review_status",
    "last_reviewed",
    "reviewer",
}
ALLOWED_SOURCES = {"llm_compiled", "guideline_cited", "clinician_reviewed"}
ALLOWED_REVIEW_STATUSES = {"pending", "clinician_reviewed", "guideline_cited"}


@pytest.fixture(scope="module")
def kb() -> dict:
    return json.loads(KB_PATH.read_text(encoding="utf-8"))


def test_kb_has_diseases_dict(kb):
    assert "diseases" in kb
    assert isinstance(kb["diseases"], dict)
    assert len(kb["diseases"]) >= 10


def test_every_disease_has_provenance_block(kb):
    missing = [name for name, entry in kb["diseases"].items() if "provenance" not in entry]
    assert not missing, f"Diseases missing provenance: {missing}"


def test_provenance_has_required_fields(kb):
    bad = []
    for name, entry in kb["diseases"].items():
        prov = entry.get("provenance", {})
        missing = REQUIRED_PROVENANCE_FIELDS - set(prov.keys())
        if missing:
            bad.append((name, sorted(missing)))
    assert not bad, f"Provenance missing fields: {bad}"


def test_provenance_values_are_allowed(kb):
    for name, entry in kb["diseases"].items():
        prov = entry["provenance"]
        assert prov["source"] in ALLOWED_SOURCES, (
            f"{name}: unknown source '{prov['source']}'"
        )
        assert prov["clinician_review_status"] in ALLOWED_REVIEW_STATUSES, (
            f"{name}: unknown review status '{prov['clinician_review_status']}'"
        )


def test_clinician_reviewed_entries_have_reviewer_info(kb):
    """If an entry claims clinician_reviewed, it must carry reviewer+date."""
    for name, entry in kb["diseases"].items():
        prov = entry["provenance"]
        if prov["clinician_review_status"] == "clinician_reviewed":
            assert prov.get("reviewer"), f"{name}: reviewed but no reviewer"
            assert prov.get("last_reviewed"), f"{name}: reviewed but no date"


def test_registry_consumer_propagates_provenance(tmp_path):
    """RegistryCodebook.task_aware_validate (registry-backed, no SQLite) must
    include kb_provenance in issue details when a match is found."""
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from codebooks.nhanes_codebook_lookup import RegistryCodebook  # type: ignore

    fake_registry = {
        "datasets": {
            "synthetic": {
                "variables": {
                    "HBA1C": {
                        "variable": "HBA1C",
                        "label": "Glycated hemoglobin HbA1c",
                        "friendly_names": ["hba1c"],
                    },
                    "age": {"variable": "age", "label": "Age at visit"},
                }
            }
        }
    }
    reg_path = tmp_path / "registry.json"
    reg_path.write_text(json.dumps(fake_registry))

    cb = RegistryCodebook(str(reg_path), "synthetic")
    issues = cb.task_aware_validate(
        column_names=["HBA1C", "age"],
        target_col="y",
        target_disease="type_2_diabetes",
        disease_kb_path=str(KB_PATH),
    )
    assert issues, "Expected at least one definition-variable issue"
    match = next(
        (i for i in issues if "kb_provenance" in (i.get("details") or {})), None
    )
    assert match is not None, f"No issue surfaced kb_provenance. Got: {issues}"
    assert match["details"]["kb_provenance"]["clinician_review_status"] == "pending"
    assert "LLM-compiled" in match["message"]


def test_nhanes_consumer_propagates_provenance(monkeypatch):
    """NHANESCodebook.task_aware_validate (BM25 + SQLite path) must also
    propagate kb_provenance. Stubs the BM25 internals via monkeypatch so the
    test doesn't require an actual NHANES SQLite file.

    Guard for the fix in P0-2 that both consumer paths (registry + NHANES)
    surface kb_provenance identically.
    """
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from codebooks.nhanes_codebook_lookup import NHANESCodebook  # type: ignore

    cb = NHANESCodebook.__new__(NHANESCodebook)
    # Minimal stubs: avoid __init__ which needs a real codebook_dir
    cb._variables = {"LBXGH": {"variable": "LBXGH", "sas_label": "Glycohemoglobin (HbA1c)"}}
    monkeypatch.setattr(cb, "_ensure_index", lambda: None)
    monkeypatch.setattr(cb, "search", lambda term, **kw: [
        {"variable": "LBXGH", "sas_label": "Glycohemoglobin (HbA1c)", "score": 10.0}
    ] if "hba1c" in term.lower() or "glycated" in term.lower() else [])
    monkeypatch.setattr(cb, "_term_overlaps_label", lambda t, l: True)
    monkeypatch.setattr(cb, "_reverse_lookup", lambda t: None)
    monkeypatch.setattr(cb, "lookup", lambda c: cb._variables.get(c))

    issues = cb.task_aware_validate(
        column_names=["LBXGH", "RIDAGEYR"],
        target_col="y",
        target_disease="type_2_diabetes",
        disease_kb_path=str(KB_PATH),
    )
    assert issues, "Expected NHANES match for HbA1c + diabetes"
    match = next(
        (i for i in issues if "kb_provenance" in (i.get("details") or {})), None
    )
    assert match is not None, f"NHANES consumer did not surface kb_provenance. Got: {issues}"
    assert match["details"]["kb_provenance"]["clinician_review_status"] == "pending"
    assert "LLM-compiled" in match["message"]


def test_ukb_consumer_propagates_provenance(monkeypatch, tmp_path):
    """UKBCodebook.task_aware_validate must also propagate kb_provenance.
    Stubs the SQLite connection + parse_ukb_column so the test is self-contained."""
    import sys
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    import codebooks.ukb_codebook_lookup as ukb_mod  # type: ignore

    # Inject a fake ukb_definition_fields into the disease entry so we hit the
    # definition-variable branch. Do this via a wrapped KB copy on disk.
    kb = json.loads(KB_PATH.read_text(encoding="utf-8"))
    kb["diseases"]["type_2_diabetes"]["ukb_definition_fields"] = [130708]  # fake
    fake_kb = tmp_path / "disease_kb.json"
    fake_kb.write_text(json.dumps(kb))

    cb = ukb_mod.UKBCodebook.__new__(ukb_mod.UKBCodebook)
    # Stub _ensure_conn to return an object whose execute() returns an iterable
    # matching what the method expects (fetchone → dict-like row with 'title').
    class _FakeRow(dict):
        def __getitem__(self, k): return super().__getitem__(k)
    class _FakeCursor:
        def __init__(self, rows): self._rows = rows
        def fetchone(self): return self._rows[0] if self._rows else None
        def fetchall(self): return self._rows
    class _FakeConn:
        def execute(self, sql, params=()):
            # Called for both `SELECT title FROM fields` and for encoding_values lookups.
            if "fields" in sql:
                return _FakeCursor([_FakeRow({"title": "Date E11 first reported"})])
            return _FakeCursor([])
    monkeypatch.setattr(cb, "_ensure_conn", lambda: _FakeConn())
    monkeypatch.setattr(ukb_mod, "parse_ukb_column", lambda col: (130708, 0, 0) if col == "p130708_i0" else None)

    issues = cb.task_aware_validate(
        column_names=["p130708_i0", "p21022"],
        target_col="y",
        target_disease="type_2_diabetes",
        disease_kb_path=str(fake_kb),
    )
    assert issues, f"Expected UKB definition-variable match. Got: {issues}"
    match = next(
        (i for i in issues if "kb_provenance" in (i.get("details") or {})), None
    )
    assert match is not None, "UKB consumer did not surface kb_provenance"
    assert match["details"]["kb_provenance"]["clinician_review_status"] == "pending"
    assert "LLM-compiled" in match["message"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
