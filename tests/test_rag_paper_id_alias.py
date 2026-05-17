"""W20-F1 regression: MMR same-paper penalty must read ``_paper_id``.

W18-D3 finding: ``scripts/rag/retrieval/bm25.py:_enrich_concern`` writes
``_paper_id`` (underscore prefix, line ~336), while the MMR re-rank in
``scripts/rag/retrieval/hybrid.py`` (line ~465) historically read
``paper_id`` (no underscore). The attribute mismatch silently disabled
the same-paper diversity penalty on every gate-anchored query: 10/10
W18-D3 sample queries reported ``blocker_reason={"none":50, "cosine":0,
"same_paper":0}``.

These tests pin the alias contract so the bug cannot silently re-emerge.
They sit in a dedicated file (instead of being appended to
``test_rag_mmr.py``) because parallel sessions sometimes race appends
to the larger MMR test module.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sentence_transformers")


def test_mmr_same_paper_penalty_reads_underscore_paper_id():
    """Mirrors real BM25 output: only ``_paper_id`` is present.

    With the alias in place, the same-paper penalty fires; B (same
    paper as A, higher relevance than C) loses rank 2 to C, and B's
    breakdown records the blocker reason. Without the alias, the
    penalty silently no-op's and B would win rank 2 with
    ``blocker_reason="none"``.
    """
    from scripts.rag.retrieval.hybrid import _mmr_rerank

    cands = [
        {"concern_id": "A", "_paper_id": "P1", "_final_score": 0.90},
        {"concern_id": "B", "_paper_id": "P1", "_final_score": 0.88},
        {"concern_id": "C", "_paper_id": "P2", "_final_score": 0.85},
    ]
    out = _mmr_rerank(cands, top_k=3, lam=0.5, same_paper_penalty=0.5)

    assert out[0]["concern_id"] == "A"
    assert out[1]["concern_id"] == "C", (
        "_paper_id alias missing: expected C (cross-paper) at rank 2; "
        f"got {out[1]['concern_id']} — same-paper penalty did not fire"
    )
    assert out[2]["concern_id"] == "B"
    assert out[2]["_mmr_breakdown"]["blocker_reason"] == "same_paper", (
        "B's breakdown should name A as a same-paper blocker; got "
        f"{out[2]['_mmr_breakdown']['blocker_reason']} — penalty silently skipped"
    )
    assert out[2]["_mmr_breakdown"]["blocker_id"] == "A"


def test_mmr_same_paper_penalty_mixed_paper_id_keys():
    """Belt-and-suspenders: alias must also work when one side carries
    ``paper_id`` and the other ``_paper_id``. This covers the real
    fusion path where dense candidates (carrying ``paper_id`` from
    ``index.builder``) and BM25 candidates (carrying ``_paper_id`` from
    ``_enrich_concern``) are merged into a single candidate list.
    """
    from scripts.rag.retrieval.hybrid import _mmr_rerank

    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": 0.90},
        {"concern_id": "B", "_paper_id": "P1", "_final_score": 0.88},
        {"concern_id": "C", "_paper_id": "P2", "_final_score": 0.85},
    ]
    out = _mmr_rerank(cands, top_k=3, lam=0.5, same_paper_penalty=0.5)

    assert out[0]["concern_id"] == "A"
    assert out[1]["concern_id"] == "C", (
        "mixed paper_id/_paper_id keys must still match: expected C; "
        f"got {out[1]['concern_id']}"
    )
    assert out[2]["concern_id"] == "B"
    assert out[2]["_mmr_breakdown"]["blocker_reason"] == "same_paper"
