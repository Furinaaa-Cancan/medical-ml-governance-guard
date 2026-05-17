"""W9-B2 tests for within-CP dense corroboration + MMR breakdown.

Covers two architectural additions in ``scripts.rag.retrieval.hybrid``:

1. ``_dense_corroboration_scores`` — the proposed replacement for
   ``_tag_overlap_scores`` (W7-P4: tag_overlap signal is DEAD on 45/49
   CPs at ``TAG_OVERLAP_MIN_SHARED>=2``, only marginally rescued at >=1
   because 89.5% of KB tags are singletons / W7-P6). The new signal
   computes the average cosine similarity to the top-K most-similar
   same-CP siblings, so a CP cluster fires corroboration *purely from
   the embeddings* without depending on the sparse tag set.

2. ``_mmr_breakdown`` — W5 deep audit. ``_mmr_score`` is a scalar; it
   does not say *which* already-selected candidate caused the diversity
   penalty. The breakdown dict surfaces ``blocker_id`` + ``blocker_reason``
   so retrieval audits can answer "why did B place where it did?".

These tests are deliberately self-contained (synthetic embeddings, no
KB load, no sentence_transformer download) so they run in CI without
the heavy ``BAAI/bge-small-en-v1.5`` dependency. The integration angle
(does the signal actually move retrieval metrics?) lives in the
``scripts/rag/evals/run_eval.py`` harness, not here.
"""

from __future__ import annotations

import numpy as np
import pytest

from scripts.rag import config
from scripts.rag.retrieval.hybrid import (
    _dense_corroboration_scores,
    _mmr_rerank,
    _tag_overlap_scores,
)


# ---------------------------------------------------------------------------
# Helpers — synthetic candidate builders
# ---------------------------------------------------------------------------


def _unit(vec: list[float]) -> np.ndarray:
    """L2-normalize a python list into a float32 numpy vector."""
    arr = np.array(vec, dtype=np.float32)
    norm = float(np.linalg.norm(arr))
    if norm == 0.0:
        return arr
    return arr / norm


def _emb(*head: float) -> np.ndarray:
    """Synthetic 384-dim embedding: ``head`` values, then zeros, L2-normalized."""
    pad = [0.0] * (config.EMBEDDING_DIM - len(head))
    return _unit(list(head) + pad)


def _cand(
    cid: str,
    *,
    cp: str | None = "CP-001",
    tags: list[str] | None = None,
    paper_id: str = "P0",
    final_score: float = 0.5,
    embedding: np.ndarray | None = None,
) -> dict:
    rec: dict = {
        "concern_id": cid,
        "paper_id": paper_id,
        "_final_score": final_score,
        "tags": list(tags or []),
    }
    if cp is not None:
        rec["canonical_pattern_id"] = cp
    if embedding is not None:
        rec["_dense_embedding"] = embedding
    return rec


# ---------------------------------------------------------------------------
# 1. Within-CP dense corroboration
# ---------------------------------------------------------------------------


class TestDenseCorroborationSignal:
    """Unit-level coverage of ``_dense_corroboration_scores``."""

    def test_singleton_cp_yields_zero(self) -> None:
        """A CP with only one candidate has no siblings -> score 0."""
        cands = [_cand("A", cp="CP-001", embedding=_emb(1.0, 0.0))]
        out = _dense_corroboration_scores(cands)
        assert out == {}

    def test_missing_embedding_yields_zero(self) -> None:
        """BM25-only candidates (no _dense_embedding) score 0."""
        cands = [
            _cand("A", cp="CP-001", embedding=None),
            _cand("B", cp="CP-001", embedding=None),
        ]
        out = _dense_corroboration_scores(cands)
        assert out == {}

    def test_missing_cp_skipped(self) -> None:
        """Candidates without canonical_pattern_id are skipped entirely."""
        cands = [
            _cand("A", cp=None, embedding=_emb(1.0, 0.0)),
            _cand("B", cp=None, embedding=_emb(1.0, 0.0)),
        ]
        out = _dense_corroboration_scores(cands)
        assert out == {}

    def test_signal_fires_on_cp_cluster_with_disjoint_tags(self) -> None:
        """W9-B2 (P4+P6): within-CP dense cosine should fire on CP clusters
        where tag_overlap was dead.

        Setup: three concerns all under CP-001, all with *singleton* tags
        (no tag intersection at all). Tag overlap returns {} — the legacy
        signal is dead. Dense corroboration must still fire because the
        embeddings are similar.
        """
        # Near-cluster embeddings (cosine ~ 0.97-1.0 between pairs).
        A = _emb(1.00, 0.00)
        B = _emb(0.97, 0.24)
        C = _emb(0.95, 0.31)
        cands = [
            _cand("A", cp="CP-001", tags=["alpha"], embedding=A),
            _cand("B", cp="CP-001", tags=["beta"], embedding=B),
            _cand("C", cp="CP-001", tags=["gamma"], embedding=C),
        ]

        # Legacy tag_overlap: every pair shares 0 tags -> dead signal.
        legacy = _tag_overlap_scores(cands)
        assert legacy == {}, (
            f"setup invariant: tag_overlap must be dead here, got {legacy}"
        )

        new = _dense_corroboration_scores(cands)
        assert set(new.keys()) == {"A", "B", "C"}
        for cid, score in new.items():
            assert score > 0.9, (
                f"{cid} should have strong dense corroboration "
                f"(near-cluster cosines ~0.97), got {score:.3f}"
            )

    def test_signal_does_not_leak_across_cps(self) -> None:
        """A candidate's siblings must come from its own CP only."""
        # Near-identical embeddings but DIFFERENT canonical patterns.
        emb = _emb(1.0, 0.0)
        cands = [
            _cand("A", cp="CP-001", embedding=emb),
            _cand("B", cp="CP-002", embedding=emb),
        ]
        out = _dense_corroboration_scores(cands)
        # Each is a singleton in its own CP -> no corroboration.
        assert out == {}

    def test_top_k_caps_the_average(self) -> None:
        """With one strong sibling and many weak ones, top-K=1 should pin
        the score at the strong cosine; raising K dilutes it."""
        A = _emb(1.0, 0.0)
        # Strong sibling (cos ~ 0.97 to A).
        strong = _emb(0.97, 0.24)
        # Weak siblings (cos ~ 0.0 to A; orthogonal axis).
        weak = _emb(0.0, 0.0, 1.0)

        cands = [
            _cand("A", cp="CP-001", embedding=A),
            _cand("strong", cp="CP-001", embedding=strong),
            _cand("w1", cp="CP-001", embedding=weak),
            _cand("w2", cp="CP-001", embedding=weak),
        ]

        # top_k=1 -> A picks only its strongest sibling.
        out_k1 = _dense_corroboration_scores(cands, top_k=1)
        # top_k=3 -> A averages strong + two weak ~= 0.97/3.
        out_k3 = _dense_corroboration_scores(cands, top_k=3)

        assert out_k1["A"] > 0.9, out_k1
        assert out_k3["A"] < out_k1["A"], (
            f"larger top_k should dilute the average; "
            f"k=1 -> {out_k1['A']:.3f}, k=3 -> {out_k3['A']:.3f}"
        )

    def test_default_top_k_uses_config(self) -> None:
        """top_k=None must read config.DENSE_CORROBORATION_TOP_K."""
        # Just make sure the lookup doesn't blow up and produces a value.
        A = _emb(1.0, 0.0)
        B = _emb(0.9, 0.1)
        cands = [
            _cand("A", cp="CP-001", embedding=A),
            _cand("B", cp="CP-001", embedding=B),
        ]
        out = _dense_corroboration_scores(cands, top_k=None)
        assert "A" in out and "B" in out

    def test_score_bounded_to_unit_interval(self) -> None:
        """Even with degenerate inputs the score must stay in [0, 1]."""
        # Identical embeddings -> cosine 1.0 for every pair.
        A = _emb(1.0, 0.0)
        cands = [
            _cand("A", cp="CP-001", embedding=A),
            _cand("B", cp="CP-001", embedding=A.copy()),
            _cand("C", cp="CP-001", embedding=A.copy()),
        ]
        out = _dense_corroboration_scores(cands)
        for cid, score in out.items():
            assert 0.0 <= score <= 1.0, f"{cid} = {score} out of [0,1]"


# ---------------------------------------------------------------------------
# 2. MMR breakdown (W5 deep audit)
# ---------------------------------------------------------------------------


class TestMMRBreakdown:
    """Cover the new ``_mmr_breakdown`` audit dict on MMR output."""

    def test_mmr_breakdown_captures_blocker(self) -> None:
        """W9-B2 (W5 deep): _mmr_breakdown should record which candidate
        caused the penalty.

        Setup: A dominates by relevance; B is a near-cosine duplicate of
        A (cos ~ 0.95, above MMR_COSINE_FLOOR=0.88); C is orthogonal.
        The MMR loop should pick A first, then C (B penalized by A).
        Either way, B's _mmr_breakdown must blame A via blocker_id="A"
        and blocker_reason="cosine".
        """
        A_emb = _emb(1.0, 0.0)
        # cos(A,B) = 0.95 (near-dup, above floor).
        B_emb = _emb(0.95, 0.31)
        C_emb = _emb(0.0, 1.0)

        # Sanity: verify cos(A,B) is actually above the floor.
        cos_ab = float(np.dot(A_emb, B_emb))
        assert cos_ab >= config.MMR_COSINE_FLOOR, (
            f"setup: cos(A,B)={cos_ab:.3f} must clear "
            f"MMR_COSINE_FLOOR={config.MMR_COSINE_FLOOR}"
        )

        cands = [
            {"concern_id": "A", "paper_id": "P1", "_final_score": 0.90,
             "_dense_embedding": A_emb},
            {"concern_id": "B", "paper_id": "P2", "_final_score": 0.85,
             "_dense_embedding": B_emb},
            {"concern_id": "C", "paper_id": "P3", "_final_score": 0.80,
             "_dense_embedding": C_emb},
        ]
        out = _mmr_rerank(cands, top_k=3, lam=0.5)

        # Every picked candidate must carry a breakdown dict.
        for r in out:
            assert "_mmr_breakdown" in r, (
                f"{r['concern_id']} missing _mmr_breakdown"
            )

        # B must blame A via cosine.
        b = next(c for c in out if c["concern_id"] == "B")
        assert b["_mmr_breakdown"]["blocker_id"] == "A", (
            f"B should be blocked by A; got {b['_mmr_breakdown']}"
        )
        assert b["_mmr_breakdown"]["blocker_reason"] == "cosine", (
            f"B blocker_reason should be 'cosine'; got {b['_mmr_breakdown']}"
        )
        assert b["_mmr_breakdown"]["max_sim"] >= config.MMR_COSINE_FLOOR

    def test_top1_breakdown_has_no_blocker(self) -> None:
        """Top-1 is picked before anything else is selected -> no blocker."""
        A = _emb(1.0, 0.0)
        B = _emb(0.0, 1.0)
        cands = [
            {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9,
             "_dense_embedding": A},
            {"concern_id": "B", "paper_id": "P2", "_final_score": 0.5,
             "_dense_embedding": B},
        ]
        out = _mmr_rerank(cands, top_k=2, lam=0.7)
        assert out[0]["concern_id"] == "A"
        bd = out[0]["_mmr_breakdown"]
        assert bd["blocker_id"] is None
        assert bd["blocker_reason"] == "none"
        assert bd["max_sim"] == 0.0
        assert abs(bd["relevance"] - 0.9) < 1e-6

    def test_same_paper_blocker_reason(self) -> None:
        """When the diversity penalty comes from paper_id match (no
        embedding cosine above the floor), blocker_reason must be
        'same_paper' and the blocker_id must point to the same-paper pick.
        """
        cands = [
            # No embeddings -> only the paper_id penalty path can fire.
            {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9},
            {"concern_id": "B", "paper_id": "P1", "_final_score": 0.85},
            {"concern_id": "C", "paper_id": "P2", "_final_score": 0.80},
        ]
        out = _mmr_rerank(cands, top_k=3, lam=0.5, same_paper_penalty=0.5)
        # MMR picks A first, then C (B is same-paper-penalized), then B.
        b = next(c for c in out if c["concern_id"] == "B")
        assert b["_mmr_breakdown"]["blocker_reason"] == "same_paper"
        assert b["_mmr_breakdown"]["blocker_id"] == "A"

    def test_distinct_candidates_get_none_blocker(self) -> None:
        """An orthogonal cross-paper candidate has no penalty source ->
        blocker_id None, blocker_reason 'none'."""
        A = _emb(1.0, 0.0)
        C = _emb(0.0, 1.0)  # orthogonal to A
        cands = [
            {"concern_id": "A", "paper_id": "P1", "_final_score": 0.9,
             "_dense_embedding": A},
            {"concern_id": "C", "paper_id": "P2", "_final_score": 0.5,
             "_dense_embedding": C},
        ]
        out = _mmr_rerank(cands, top_k=2, lam=0.5)
        c = next(r for r in out if r["concern_id"] == "C")
        assert c["_mmr_breakdown"]["blocker_id"] is None
        assert c["_mmr_breakdown"]["blocker_reason"] == "none"
        assert c["_mmr_breakdown"]["max_sim"] == 0.0


# ---------------------------------------------------------------------------
# 3. Config sanity for the new flags
# ---------------------------------------------------------------------------


class TestCorroborationConfig:
    """Pin the new config surface area."""

    def test_use_dense_corroboration_is_bool(self) -> None:
        assert isinstance(config.USE_DENSE_CORROBORATION, bool)

    def test_top_k_is_positive_int(self) -> None:
        assert isinstance(config.DENSE_CORROBORATION_TOP_K, int)
        assert config.DENSE_CORROBORATION_TOP_K >= 1

    def test_legacy_tag_overlap_still_present(self) -> None:
        """The legacy signal must remain importable behind the flag so an
        A/B rollback is one config edit, not a code revert."""
        # Just calling the function with an empty list must not raise.
        assert _tag_overlap_scores([]) == {}
