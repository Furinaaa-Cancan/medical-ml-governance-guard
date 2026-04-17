"""Unit tests for `scripts/codebooks/_kb_provenance.extract_kb_provenance`,
the shared helper deduplicated out of NHANES + UKB + Registry consumers
(Claude review 2026-04-17 minor #1)."""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "codebooks"))

from _kb_provenance import (  # noqa: E402
    ALLOWED_REVIEW_STATUSES,
    REVIEW_STATUS_CLINICIAN_REVIEWED,
    REVIEW_STATUS_GUIDELINE_CITED,
    REVIEW_STATUS_PENDING,
    extract_kb_provenance,
)


def test_allowed_review_statuses_complete() -> None:
    assert ALLOWED_REVIEW_STATUSES == {
        REVIEW_STATUS_PENDING,
        REVIEW_STATUS_CLINICIAN_REVIEWED,
        REVIEW_STATUS_GUIDELINE_CITED,
    }


def test_pending_entry_yields_hint() -> None:
    entry = {
        "provenance": {
            "source": "llm_compiled",
            "clinician_review_status": REVIEW_STATUS_PENDING,
            "last_reviewed": None,
        }
    }
    prov, hint = extract_kb_provenance(entry)
    assert prov["source"] == "llm_compiled"
    assert prov["clinician_review_status"] == REVIEW_STATUS_PENDING
    assert prov["last_reviewed"] is None
    assert "LLM-compiled" in hint
    assert hint.startswith(" [") and hint.endswith("]")


def test_clinician_reviewed_entry_no_hint() -> None:
    entry = {
        "provenance": {
            "source": REVIEW_STATUS_CLINICIAN_REVIEWED,
            "clinician_review_status": REVIEW_STATUS_CLINICIAN_REVIEWED,
            "last_reviewed": "2026-04-17",
        }
    }
    prov, hint = extract_kb_provenance(entry)
    assert hint == ""
    assert prov["clinician_review_status"] == REVIEW_STATUS_CLINICIAN_REVIEWED


def test_missing_provenance_block_defaults_to_unknown() -> None:
    entry = {"name": "some disease", "icd10": ["E11"]}
    prov, hint = extract_kb_provenance(entry)
    assert prov == {
        "source": "unknown",
        "clinician_review_status": "unknown",
        "last_reviewed": None,
    }
    assert hint == ""


def test_none_entry_does_not_crash() -> None:
    prov, hint = extract_kb_provenance(None)
    assert prov["source"] == "unknown"
    assert hint == ""


def test_non_dict_entry_treated_as_empty() -> None:
    for bad in [42, "string", [1, 2], ()]:
        prov, hint = extract_kb_provenance(bad)
        assert prov["source"] == "unknown"
        assert hint == ""


def test_non_dict_provenance_block_tolerated() -> None:
    entry = {"provenance": "not a dict"}
    prov, hint = extract_kb_provenance(entry)
    assert prov["source"] == "unknown"
    assert hint == ""


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
