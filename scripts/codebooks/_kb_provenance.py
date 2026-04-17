"""Shared provenance helper for disease-KB consumers (P0-2 follow-up).

NHANES + UKB + Registry codebook `task_aware_validate` methods all emit
`CODEBOOK_DEFINITION_VARIABLE` / `CODEBOOK_SELF_REPORT_LEAKAGE` issues and
need to propagate the source disease entry's `provenance` block to let
users arbitrate false positives from LLM-compiled KB entries. Claude's
2026-04-17 code review flagged the 3 inline copies; this module dedupes.
"""
from __future__ import annotations

from typing import Any, Mapping


# Allowed values for `disease_entry.provenance.clinician_review_status`.
# Kept in sync with tests/test_disease_kb_provenance.py::ALLOWED_REVIEW_STATUSES.
REVIEW_STATUS_PENDING = "pending"
REVIEW_STATUS_CLINICIAN_REVIEWED = "clinician_reviewed"
REVIEW_STATUS_GUIDELINE_CITED = "guideline_cited"
ALLOWED_REVIEW_STATUSES = frozenset({
    REVIEW_STATUS_PENDING,
    REVIEW_STATUS_CLINICIAN_REVIEWED,
    REVIEW_STATUS_GUIDELINE_CITED,
})

# User-facing hint appended to issue messages when the backing KB entry has
# not been clinician-reviewed. The exact wording is asserted by tests, so
# don't change it without updating test_disease_kb_provenance.py.
_PENDING_HINT = " [KB entry is LLM-compiled and not yet clinician-reviewed.]"


def extract_kb_provenance(disease_entry: Mapping[str, Any] | None) -> tuple[dict[str, Any], str]:
    """Return `(kb_provenance_dict, user_hint_string)` for a disease KB entry.

    `kb_provenance_dict` is a 3-field snapshot safe to embed in issue details.
    `user_hint_string` is appended to issue messages (empty if clinician-reviewed).

    Missing or non-dict `disease_entry` → `(unknown-everything, no hint)`.
    Missing `provenance` sub-block → `(unknown, unknown, None)` with empty hint.
    """
    prov: Mapping[str, Any] = {}
    if isinstance(disease_entry, Mapping):
        _p = disease_entry.get("provenance")
        if isinstance(_p, Mapping):
            prov = _p

    status = prov.get("clinician_review_status", "unknown")
    kb_provenance = {
        "source": prov.get("source", "unknown"),
        "clinician_review_status": status,
        "last_reviewed": prov.get("last_reviewed"),
    }
    hint = _PENDING_HINT if status == REVIEW_STATUS_PENDING else ""
    return kb_provenance, hint
