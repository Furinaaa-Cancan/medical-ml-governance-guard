"""Enforcement test for `_provenance: "LLM-DRAFT..."` markers.

Addresses INDEPENDENT_REVIEW.md R9 finding:
    `_provenance` marker is performative: `grep -rIn LLM-DRAFT scripts/`
    returns zero hits. No code path refuses LLM-DRAFT entries.

This test makes the marker REAL: it fails CI if any entry in the canonical
KB (`references/case-studies/peer-review-kb.json`) carries an `_provenance`
field whose value contains "LLM-DRAFT". By construction, LLM-DRAFT entries
live in `references/retrieval_eval/MLGG-Bench-v1.0/v1.1_proposed/` as
draft material pending clinical review — promoting them to the canonical
KB without first stripping the marker (and ideally having a clinical-
methodologist sign-off recorded elsewhere) MUST trip this guard.

Behaviour:
    - Loads peer-review-kb.json
    - Walks every entry + every reviewer_concern
    - Fails loudly with a list of offending IDs and their _provenance values
    - Also scans the entry-level _provenance (if present)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
KB_PATH = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"
FORBIDDEN_PROVENANCE_SUBSTRINGS = (
    "LLM-DRAFT",
    "pending-clinical-review",
    "pending_clinical_review",
)


def _collect_offenders(kb: dict) -> list[tuple[str, str, str]]:
    """Return list of (entry_id, concern_id_or_None, provenance_value) tuples
    for every node whose _provenance contains a forbidden substring."""
    offenders: list[tuple[str, str | None, str]] = []
    for entry in kb.get("entries", []):
        eid = entry.get("id", "<no-id>")
        # Entry-level _provenance
        ep = entry.get("_provenance")
        if ep:
            ev = ep if isinstance(ep, str) else json.dumps(ep)
            if any(s in ev for s in FORBIDDEN_PROVENANCE_SUBSTRINGS):
                offenders.append((eid, None, ev))
        # Concern-level _provenance
        for concern in entry.get("reviewer_concerns", []) or []:
            cid = concern.get("concern_id", "<no-cid>")
            cp = concern.get("_provenance")
            if cp:
                cv = cp if isinstance(cp, str) else json.dumps(cp)
                if any(s in cv for s in FORBIDDEN_PROVENANCE_SUBSTRINGS):
                    offenders.append((eid, cid, cv))
    return offenders


def test_kb_contains_no_llm_draft_provenance():
    """The canonical KB must not contain any entry/concern marked as
    LLM-DRAFT or pending clinical review. Draft material lives under
    references/retrieval_eval/MLGG-Bench-v1.0/v1.1_proposed/ until it
    has been reviewed; promotion requires stripping the marker.

    If this test fails: either (a) the promotion happened without
    stripping the marker (revert and re-promote with the marker removed
    + a clinical reviewer's sign-off recorded in the commit message),
    or (b) the marker semantics have changed and this test needs to
    update FORBIDDEN_PROVENANCE_SUBSTRINGS."""
    assert KB_PATH.exists(), f"KB file missing: {KB_PATH}"
    kb = json.loads(KB_PATH.read_text())
    offenders = _collect_offenders(kb)
    assert not offenders, (
        f"FOUND {len(offenders)} LLM-DRAFT entries in the canonical KB. "
        f"Draft material must live under v1.1_proposed/ until clinical "
        f"review. Offenders (entry_id, concern_id, _provenance):\n"
        + "\n".join(f"  - {o}" for o in offenders[:10])
        + (f"\n  ... (+{len(offenders) - 10} more)" if len(offenders) > 10 else "")
    )


def test_guard_actually_detects_a_planted_draft(tmp_path):
    """Sanity test: prove the guard CAN detect a forbidden _provenance
    so that test_kb_contains_no_llm_draft_provenance's pass is meaningful.
    (Without this, a buggy _collect_offenders that always returns [] would
    silently green-light the real test.)"""
    planted = {
        "entries": [
            {
                "id": "FAKE-001",
                "reviewer_concerns": [
                    {
                        "concern_id": "FAKE-001-C01",
                        "_provenance": "LLM-DRAFT-v1.1-pending-clinical-review",
                    }
                ],
            }
        ]
    }
    offenders = _collect_offenders(planted)
    assert len(offenders) == 1
    assert offenders[0][0] == "FAKE-001"
    assert offenders[0][1] == "FAKE-001-C01"
    assert "LLM-DRAFT" in offenders[0][2]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
