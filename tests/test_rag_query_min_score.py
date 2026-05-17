"""Unit tests for the W27-R2 ``min_score`` opt-in on ``rag_query``.

All tests mock the underlying ``hybrid_rank`` so they are fast,
offline, and don't depend on a live KB or embeddings cache.
"""
from __future__ import annotations

from unittest import mock

from scripts.rag.query import rag_query


def _rec(cid: str, score: float) -> dict:
    """Minimal hybrid_rank-shaped record."""
    return {
        "concern_id": cid,
        "concern_text": f"concern {cid}",
        "_final_score": score,
    }


def test_rag_query_min_score_default_zero_is_passthrough():
    """W27-R2 back-compat: default min_score=0.0 returns every record the
    ranker produced, in the same order, with no filtering."""
    records = [_rec("a", 0.9), _rec("b", 0.3), _rec("c", 0.05)]
    with mock.patch(
        "scripts.rag.retrieval.hybrid.hybrid_rank", return_value=records
    ):
        out = rag_query("any query", top_k=5)
    assert [r["concern_id"] for r in out] == ["a", "b", "c"]


def test_rag_query_min_score_drops_below_threshold():
    """W27-R2: with min_score=0.4, only records scoring >= 0.4 survive."""
    records = [_rec("a", 0.9), _rec("b", 0.4), _rec("c", 0.39), _rec("d", 0.0)]
    with mock.patch(
        "scripts.rag.retrieval.hybrid.hybrid_rank", return_value=records
    ):
        out = rag_query("any query", top_k=5, min_score=0.4)
    assert [r["concern_id"] for r in out] == ["a", "b"]


def test_rag_query_min_score_keeps_records_without_score():
    """W27-R2 defensive: a record missing ``_final_score`` is kept regardless
    of threshold — the score-bearing ranker is the authority, not absence.
    """
    records = [
        _rec("scored_high", 0.9),
        {"concern_id": "unscored", "concern_text": "no score key"},
        _rec("scored_low", 0.1),
    ]
    with mock.patch(
        "scripts.rag.retrieval.hybrid.hybrid_rank", return_value=records
    ):
        out = rag_query("any query", top_k=5, min_score=0.5)
    assert [r["concern_id"] for r in out] == ["scored_high", "unscored"]


def test_rag_query_min_score_empty_results_short_circuit():
    """W27-R2: filter never runs (and never crashes) when the ranker
    returned an empty list."""
    with mock.patch(
        "scripts.rag.retrieval.hybrid.hybrid_rank", return_value=[]
    ):
        out = rag_query("any query", top_k=5, min_score=0.9)
    assert out == []
