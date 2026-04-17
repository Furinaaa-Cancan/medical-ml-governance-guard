"""Regression tests for the 2026-04-17 RAG retrieval precision fix.

Covers two bugs:

1. Warning-only gates (strict-mode-upgrade pattern) previously got 0
   peer_review_context. `_gate_framework.build_report_envelope` now
   triggers retrieval for both failures AND warnings.

2. `retrieve_by_gate(gate_name)` filtered by mlgg_gates then sorted by
   severity, giving ~20% precision — CRITICAL-severity topically-unrelated
   concerns bubbled above lower-severity on-target ones.
   `retrieve_for_failure(gate_name, issue_codes)` re-ranks by issue-code
   keyword overlap with concern tags/text.

These tests lock in behavior so the regression on failure-specific
relevance doesn't silently return.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "core"))

from _peer_review_retrieval import (  # noqa: E402
    _issue_code_keywords,
    retrieve_by_gate,
    retrieve_for_failure,
)


def test_issue_code_keywords_extract_meaningful_tokens() -> None:
    codes = ["clinical_floor_sensitivity_not_met", "clinical_floor_ppv_not_met"]
    kws = _issue_code_keywords(codes)
    # 'clinical', 'floor', 'sensitivity', 'ppv' expected; 'not', 'met'
    # filtered as stopwords.
    assert kws == {"clinical", "floor", "sensitivity", "ppv"}


def test_issue_code_keywords_filters_short_and_stopwords() -> None:
    codes = ["baseline_improvement_insufficient", "cv_strategy_required"]
    kws = _issue_code_keywords(codes)
    assert "baseline" in kws
    assert "improvement" in kws
    assert "strategy" in kws
    # 'cv' is 2 chars → dropped; 'required' / 'insufficient' are stopwords.
    assert "cv" not in kws
    assert "required" not in kws
    assert "insufficient" not in kws


def test_issue_code_keywords_handles_empty_and_malformed_input() -> None:
    assert _issue_code_keywords([]) == set()
    assert _issue_code_keywords([None, 42, ""]) == set()  # type: ignore[list-item]


def test_retrieve_for_failure_surfaces_failure_specific_concern() -> None:
    """Gate: clinical_metrics_gate. Failure: PPV-related.
    Expect at least one PPV-tagged concern in the top 5 results (there
    are 13 ppv-tagged concerns mapped to clinical_metrics_gate in the KB).
    """
    results = retrieve_for_failure(
        "clinical_metrics_gate",
        ["clinical_floor_ppv_not_met", "clinical_floor_sensitivity_not_met"],
        limit=5,
    )
    assert results, "Retrieval returned no concerns for clinical_metrics_gate"
    # At least one top-5 concern should have a ppv-related tag.
    def _has_ppv_or_sensitivity(c: dict) -> bool:
        tags = " ".join(str(t).lower() for t in (c.get("tags") or []))
        return "ppv" in tags or "sensitivity" in tags or "low_precision" in tags

    assert any(_has_ppv_or_sensitivity(c) for c in results), (
        "Expected at least one ppv/sensitivity-tagged concern in top 5 after "
        "re-ranking. Got tags: "
        f"{[c.get('tags') for c in results]}"
    )


def test_retrieve_for_failure_surfaces_baseline_concern() -> None:
    """Gate: evaluation_quality_gate. Failure: baseline_improvement_insufficient.
    KB has 3 concerns mapped to evaluation_quality_gate with 'baseline'-related
    tags. Before the fix, retrieve_by_gate returned them only if CRITICAL.
    """
    results = retrieve_for_failure(
        "evaluation_quality_gate",
        ["baseline_improvement_insufficient"],
        limit=5,
    )
    assert results

    def _has_baseline(c: dict) -> bool:
        tags = " ".join(str(t).lower() for t in (c.get("tags") or []))
        text = (c.get("concern_text") or "").lower()
        return "baseline" in tags or "baseline" in text[:500]

    assert any(_has_baseline(c) for c in results), (
        f"No baseline-related concern in top 5 for evaluation_quality_gate + "
        f"baseline_improvement_insufficient. Tags: "
        f"{[c.get('tags') for c in results]}"
    )


def test_retrieve_for_failure_falls_back_when_no_keyword_match() -> None:
    """Even when keywords miss the KB entirely, retrieval should still return
    top-N severity-ranked concerns (never empty if the gate has any mapped
    concerns). Ensures we don't create a "silent zero-hit" regression."""
    results = retrieve_for_failure(
        "clinical_metrics_gate",
        # Intentionally garbage codes that won't match any tag/text keyword.
        ["zzz_nonexistent_yyy_xxx"],
        limit=5,
    )
    assert len(results) > 0, "Fallback must not return empty when gate has mapped concerns"


def test_retrieve_for_failure_matches_old_retrieve_by_gate_when_codes_empty() -> None:
    """With no issue codes, behavior should match retrieve_by_gate (severity-only)."""
    old = retrieve_by_gate("clinical_metrics_gate", limit=5)
    new = retrieve_for_failure("clinical_metrics_gate", [], limit=5)
    assert [c.get("concern_id") for c in new] == [c.get("concern_id") for c in old]


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
