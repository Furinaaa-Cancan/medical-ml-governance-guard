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


def test_mmr_v2_uses_embedding_cosine_for_cross_paper_dups():
    """v2 MMR: two concerns from DIFFERENT papers with near-identical
    embeddings should still get penalized by the cosine term."""
    import numpy as np
    from scripts.rag.retrieval.hybrid import _mmr_rerank

    # Synthetic L2-normalized vectors. embed_same has unit norm
    # (0.6^2 + 0.8^2 = 1.0). embed_diff is the orthogonal basis vector.
    embed_same = np.array([0.6, 0.8, 0.0] + [0.0] * 381, dtype=np.float32)
    embed_diff = np.array([0.0, 0.0, 1.0] + [0.0] * 381, dtype=np.float32)

    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9,
         "_dense_embedding": embed_same},
        # Cross-paper twin: identical embedding to A but different paper —
        # v1 (paper_id only) would happily pick this second.
        {"concern_id": "B", "paper_id": "P2", "_final_score": 0.88,
         "_dense_embedding": embed_same},
        # Orthogonal: lower relevance but maximally diverse.
        {"concern_id": "C", "paper_id": "P3", "_final_score": 0.85,
         "_dense_embedding": embed_diff},
    ]
    out = _mmr_rerank(cands, top_k=2, lam=0.5)
    assert out[0]["concern_id"] == "A"
    assert out[1]["concern_id"] == "C", (
        f"expected C (orthogonal embedding), got {out[1]['concern_id']} — "
        "v2 MMR should use cosine similarity to suppress cross-paper duplicates"
    )


def test_mmr_v2_falls_back_to_paper_id_when_no_embedding():
    """v2 MMR should still work for candidates missing _dense_embedding
    (e.g. BM25-only hits in the gate-anchored path)."""
    from scripts.rag.retrieval.hybrid import _mmr_rerank
    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9},   # no embedding
        {"concern_id": "B", "paper_id": "P1", "_final_score": 0.88},  # no embedding, same paper
        {"concern_id": "C", "paper_id": "P2", "_final_score": 0.85},  # different paper
    ]
    out = _mmr_rerank(cands, top_k=2, lam=0.5, same_paper_penalty=0.5)
    assert out[0]["concern_id"] == "A"
    assert out[1]["concern_id"] == "C", (
        f"paper_id fallback failed: expected C, got {out[1]['concern_id']}"
    )


def test_mmr_v2_strips_embeddings_from_output():
    """Output to caller should not contain _dense_embedding (internal-only)."""
    import numpy as np
    from scripts.rag.retrieval.hybrid import _mmr_rerank
    emb = np.zeros(384, dtype=np.float32)
    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9,
         "_dense_embedding": emb},
    ]
    # lam=1.0 takes the passthrough branch — make sure it also strips.
    out = _mmr_rerank(cands, top_k=1, lam=1.0)
    assert "_dense_embedding" not in out[0]

    # Standard MMR loop branch — multiple candidates.
    cands2 = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9,
         "_dense_embedding": emb},
        {"concern_id": "B", "paper_id": "P2", "_final_score": 0.8,
         "_dense_embedding": emb},
    ]
    out2 = _mmr_rerank(cands2, top_k=2, lam=0.5)
    for r in out2:
        assert "_dense_embedding" not in r, (
            f"embedding leaked to caller: {r['concern_id']}"
        )
