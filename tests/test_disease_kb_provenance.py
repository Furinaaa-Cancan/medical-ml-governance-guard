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


def test_consumers_propagate_provenance(tmp_path):
    """RegistryCodebook.task_aware_validate (registry-backed, no SQLite) must
    include kb_provenance in issue details when a match is found."""
    import sys

    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
    from codebooks.nhanes_codebook_lookup import RegistryCodebook  # type: ignore

    # Build a tiny in-memory registry so lookup has a variable to match.
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
    assert any(
        "kb_provenance" in (i.get("details") or {})
        for i in issues
    ), f"No issue surfaced kb_provenance. Got: {issues}"
    # The provenance should reflect pending review status.
    for issue in issues:
        prov = (issue.get("details") or {}).get("kb_provenance")
        if prov:
            assert prov["clinician_review_status"] == "pending"
            break


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
