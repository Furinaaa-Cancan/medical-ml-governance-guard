"""Tests for MMR diversity pass (G4, addresses E1 Q11 finding)."""
import pytest
pytest.importorskip("sentence_transformers")


def test_mmr_lam_one_is_passthrough():
    from scripts.rag.retrieval.hybrid import _mmr_rerank
    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9},
        {"concern_id": "B", "paper_id": "P1", "_final_score": 0.8},
        {"concern_id": "C", "paper_id": "P2", "_final_score": 0.7},
    ]
    out = _mmr_rerank(cands, top_k=3, lam=1.0)
    assert [c["concern_id"] for c in out] == ["A", "B", "C"]


def test_mmr_same_paper_penalty():
    """At lambda=0.5, same-paper second candidate should lose to cross-paper third."""
    from scripts.rag.retrieval.hybrid import _mmr_rerank
    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.90},
        {"concern_id": "B", "paper_id": "P1", "_final_score": 0.88},  # same as A
        {"concern_id": "C", "paper_id": "P2", "_final_score": 0.85},  # different
    ]
    out = _mmr_rerank(cands, top_k=2, lam=0.5, same_paper_penalty=0.5)
    assert out[0]["concern_id"] == "A"
    # MMR: relevance(B)*0.5 - 0.5*0.5 = 0.19 vs relevance(C)*0.5 - 0 = 0.425
    assert out[1]["concern_id"] == "C", f"expected C, got {out[1]['concern_id']}"


def test_mmr_e1_regression_query():
    """E1 Q11: 'code and data not available' should not have >2 same-paper hits."""
    from scripts.rag import rag_query
    results = rag_query("code and data not available for replication", top_k=5)
    paper_counts = {}
    for r in results:
        p = r.get("paper_id")
        paper_counts[p] = paper_counts.get(p, 0) + 1
    max_same = max(paper_counts.values()) if paper_counts else 0
    assert max_same <= 2, f"MMR diversity failed: {paper_counts}"
