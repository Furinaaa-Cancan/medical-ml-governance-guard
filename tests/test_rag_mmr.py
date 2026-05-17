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


def test_mmr_v2_cosine_floor_preserves_distinct_neighbors():
    """W2 fix: cos 0.78-0.82 = semantically related but distinct.
    Should NOT trigger diversity penalty. Only cos >= MMR_COSINE_FLOOR
    (default 0.88) counts as near-duplicate."""
    import numpy as np
    from scripts.rag.retrieval.hybrid import _mmr_rerank

    # Build embeddings: A and B are 0.80 cosine; B and C are 0.95 (near-dup)
    A = np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32)
    B = np.array([0.80, 0.60] + [0.0] * 382, dtype=np.float32)
    B = B / np.linalg.norm(B)
    C = np.array([0.78, 0.626] + [0.0] * 382, dtype=np.float32)
    C = C / np.linalg.norm(C)

    cos_AB = float(np.dot(A, B))
    cos_BC = float(np.dot(B, C))
    assert 0.75 < cos_AB < 0.85, f"setup: AB cos = {cos_AB}"
    assert cos_BC > 0.95, f"setup: BC cos = {cos_BC}"

    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.90, "_dense_embedding": A},
        {"concern_id": "B", "paper_id": "P2", "_final_score": 0.85, "_dense_embedding": B},
        {"concern_id": "C", "paper_id": "P3", "_final_score": 0.83, "_dense_embedding": C},
    ]

    # With floor: B (cos 0.80 to A, BELOW 0.88 floor) should NOT be penalized,
    # so B wins rank 2 (higher relevance than C)
    out = _mmr_rerank(cands, top_k=2, lam=0.5)
    assert out[0]["concern_id"] == "A"
    assert out[1]["concern_id"] == "B", (
        f"with floor, B (distinct, cos 0.80) should win rank 2 over C (near-dup); "
        f"got {out[1]['concern_id']}"
    )


def test_mmr_v2_floor_still_penalizes_near_duplicates():
    """Above the floor (cos >= 0.88), MMR diversity still applies."""
    import numpy as np
    from scripts.rag.retrieval.hybrid import _mmr_rerank

    A = np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32)
    NEAR_DUP = np.array([0.96, 0.28] + [0.0] * 382, dtype=np.float32)
    NEAR_DUP = NEAR_DUP / np.linalg.norm(NEAR_DUP)
    DISTINCT = np.array([0.0, 1.0] + [0.0] * 382, dtype=np.float32)

    assert float(np.dot(A, NEAR_DUP)) > 0.90  # above floor
    assert float(np.dot(A, DISTINCT)) < 0.10  # orthogonal

    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.90, "_dense_embedding": A},
        {"concern_id": "B", "paper_id": "P2", "_final_score": 0.88, "_dense_embedding": NEAR_DUP},  # near-dup
        {"concern_id": "C", "paper_id": "P3", "_final_score": 0.80, "_dense_embedding": DISTINCT},  # orthogonal
    ]
    out = _mmr_rerank(cands, top_k=2, lam=0.5)
    assert out[0]["concern_id"] == "A"
    assert out[1]["concern_id"] == "C", (
        f"near-duplicate B should be penalized, C (distinct) should win rank 2; "
        f"got {out[1]['concern_id']}"
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


def test_mmr_score_consistent_formula_across_ranks():
    """W8-W5: top-1 and subsequent picks should both store
    lam * relevance - (1-lam) * max_sim (with max_sim=0 for top-1)."""
    import numpy as np
    from scripts.rag.retrieval.hybrid import _mmr_rerank

    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9,
         "_dense_embedding": np.array([1.0, 0.0] + [0.0] * 382, dtype=np.float32)},
        {"concern_id": "B", "paper_id": "P2", "_final_score": 0.5,
         "_dense_embedding": np.array([0.0, 1.0] + [0.0] * 382, dtype=np.float32)},
    ]
    out = _mmr_rerank(cands, top_k=2, lam=0.7)
    # Top-1: lam * 0.9 = 0.63 (max_sim is 0 since nothing else selected yet)
    assert abs(out[0]["_mmr_score"] - 0.63) < 0.01, (
        f"top-1 _mmr_score should be lam*rel=0.63, got {out[0]['_mmr_score']}"
    )
    # Top-2: lam * 0.5 - (1-lam) * 0 = 0.35 (cosine to A is 0, orthogonal)
    assert abs(out[1]["_mmr_score"] - 0.35) < 0.01, (
        f"top-2 _mmr_score should be 0.35, got {out[1]['_mmr_score']}"
    )
