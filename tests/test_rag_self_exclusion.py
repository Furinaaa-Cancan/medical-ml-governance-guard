"""RAG leave-one-paper-out / self-retrieval guard (excluded_paper_ids).

The peer-review KB is both the RAG index AND the source of ground-truth
reviewer concerns. When a paper that lives in the KB is the one being reviewed
(any leave-one-paper-out evaluation, or `mlgg llm-audit` on an in-KB paper),
the retriever must not be able to surface that paper's OWN concerns — otherwise
it reads its own answer key.

Build-time dense exclusion (index.builder) only filters the dense index; the
BM25 hits that hybrid_rank unions in afterwards carry no exclusion signal. These
tests pin the RUNTIME filter that closes that gap at the post-union chokepoint,
covering both paths, with no index rebuild.
"""
from __future__ import annotations

import inspect
import math

import numpy as np
import pytest

pytest.importorskip("scripts.rag.retrieval.hybrid")

import scripts.rag.retrieval.hybrid as hybrid_mod  # noqa: E402
from scripts.rag.query import rag_query  # noqa: E402
from scripts.rag.retrieval.hybrid import (  # noqa: E402
    _candidate_paper_id,
    _drop_excluded_papers,
    _normalize_excluded,
)


# ── pure helpers (no dense stack) ────────────────────────────────────────────

def test_normalize_excluded_variants():
    assert _normalize_excluded(None) == frozenset()
    assert _normalize_excluded([]) == frozenset()
    assert _normalize_excluded("PR-001") == frozenset({"PR-001"})
    assert _normalize_excluded({"PR-001"}) == frozenset({"PR-001"})
    # filters out empties / None / whitespace, stringifies
    assert _normalize_excluded(["PR-001", "PR-002", "", None, "  "]) == frozenset(
        {"PR-001", "PR-002"}
    )


def test_exclusion_normalization_agrees_on_both_sides():
    # Caller-side and candidate-side must strip identically, else a
    # whitespace-padded id slips past the filter (adversarial-review finding).
    assert _normalize_excluded([" PR-001 "]) == frozenset({"PR-001"})
    cands = {"a": {"paper_id": " PR-001"}, "b": {"_paper_id": "PR-001 "}}
    out = _drop_excluded_papers(cands, _normalize_excluded(["PR-001"]))
    assert out == {}, "whitespace-padded paper ids must still be excluded"


def test_drop_excluded_papers_filters_by_paper_id():
    cands = {
        "a": {"paper_id": "P1"},        # dense-style field
        "b": {"paper_id": "P2"},
        "c": {"_paper_id": "P1"},       # BM25-style field (underscore)
        "d": {},                        # no id → never excluded
    }
    out = _drop_excluded_papers(cands, frozenset({"P1"}))
    # Both the dense ('a') AND the BM25-style ('c') P1 candidates are dropped.
    assert set(out) == {"b", "d"}
    # empty exclusion is a pass-through
    assert _drop_excluded_papers(cands, frozenset()) == cands


def test_drop_excluded_papers_filters_by_doi_aliases():
    cands = {
        "a": {"paper_doi": "10.1/self"},   # dense-style DOI field
        "b": {"_paper_doi": "10.1/self"},  # BM25-style DOI field
        "c": {"_paper_doi": "10.1/other"},
    }
    out = _drop_excluded_papers(cands, frozenset({"10.1/self"}))
    assert set(out) == {"c"}


# ── hybrid_rank integration: closes the BM25-union leak (no torch) ───────────

def _rec(cid: str, paper_id: str, gate: str, id_field: str = "paper_id") -> dict:
    # id_field mirrors the real producers: the dense builder injects 'paper_id'
    # (index.builder), the BM25 enricher injects '_paper_id' (retrieval.bm25).
    return {
        "concern_id": cid,
        id_field: paper_id,
        "mlgg_gates": [gate],
        "severity": "HIGH",
        "category": "preprocessing_leakage",
        "concern_text": f"concern {cid}",
        "canonical_pattern_id": None,
    }


def _patch_retrieval(monkeypatch, dense_recs, bm25_recs):
    """Replace the dense index + BM25 retriever with in-memory fakes."""
    def fake_import():
        def build_or_load_index(**_kwargs):
            return (np.zeros((len(dense_recs), 3), dtype="float32"), dense_recs)

        def vector_search(query, embeddings, records, top_k=5):
            return [dict(r, _dense_score=0.9) for r in records[:top_k]]

        return build_or_load_index, vector_search

    monkeypatch.setattr(hybrid_mod, "_import_sibling_modules", fake_import)
    monkeypatch.setattr(
        hybrid_mod, "retrieve_for_failure", lambda g, codes, limit=50: list(bm25_recs)
    )


def test_hybrid_rank_excludes_paper_from_both_dense_and_bm25(monkeypatch):
    gate = "leakage_gate"
    # P_self appears via dense (c1, 'paper_id') AND via the BM25 union (c2,
    # '_paper_id') — the c2 path with the underscore field is exactly what a
    # paper_id-only filter would miss, so this pins the two-field fix.
    dense = [_rec("P_self-c1", "P_self", gate), _rec("P_other-c1", "P_other", gate)]
    bm25 = [
        _rec("P_self-c2", "P_self", gate, id_field="_paper_id"),
        _rec("P_other-c2", "P_other", gate, id_field="_paper_id"),
    ]
    _patch_retrieval(monkeypatch, dense, bm25)

    base = hybrid_mod.hybrid_rank(
        "scaler fit before split", gate=gate, failure_codes=["P01"], top_k=10
    )
    assert {_candidate_paper_id(r) for r in base} == {"P_self", "P_other"}

    excluded = hybrid_mod.hybrid_rank(
        "scaler fit before split", gate=gate, failure_codes=["P01"], top_k=10,
        excluded_paper_ids={"P_self"},
    )
    papers = {_candidate_paper_id(r) for r in excluded}
    assert "P_self" not in papers, "self-paper concern leaked (dense or BM25)"
    assert "P_other" in papers
    # specifically the BM25-only concern of the excluded paper (underscore
    # field) is gone — the case a paper_id-only filter would have missed
    assert "P_self-c2" not in {r["concern_id"] for r in excluded}


def test_hybrid_rank_threads_exclusion_to_dense_index_builder(monkeypatch):
    """Dense retrieval must build against the holdout-excluded index."""
    seen = {}
    gate = "leakage_gate"
    dense = [_rec("P_other-c1", "P_other", gate)]

    def fake_import():
        def build_or_load_index(**kwargs):
            seen["excluded"] = kwargs.get("excluded_paper_ids")
            return (np.zeros((len(dense), 3), dtype="float32"), dense)

        def vector_search(query, embeddings, records, top_k=5):
            return [dict(r, _dense_score=0.9) for r in records[:top_k]]

        return build_or_load_index, vector_search

    monkeypatch.setattr(hybrid_mod, "_import_sibling_modules", fake_import)
    monkeypatch.setattr(hybrid_mod, "retrieve_for_failure", lambda g, codes, limit=50: [])

    hybrid_mod.hybrid_rank(
        "q",
        gate=gate,
        failure_codes=["P01"],
        top_k=5,
        excluded_paper_ids=["P_self", "10.1/self"],
    )

    assert seen["excluded"] == ["P_self", "10.1/self"]


# ── public API threads the param ─────────────────────────────────────────────

def test_rag_query_exposes_excluded_paper_ids():
    assert "excluded_paper_ids" in inspect.signature(rag_query).parameters
    # empty query short-circuits before any retrieval → safe, torch-free
    assert rag_query("", excluded_paper_ids=["PR-001"]) == []


def test_rag_query_threads_exclusion_to_hybrid_rank(monkeypatch):
    seen = {}

    def fake_hybrid_rank(*, query, gate=None, failure_codes=None, top_k=5,
                         excluded_paper_ids=None):
        seen["excluded"] = excluded_paper_ids
        return []

    # patch where rag_query imports it (lazy import inside the function)
    monkeypatch.setattr(hybrid_mod, "hybrid_rank", fake_hybrid_rank)
    rag_query("post-index feature leakage", gate="leakage_gate",
              excluded_paper_ids=["PR-009"])
    assert seen["excluded"] == ["PR-009"]


# ── NaN/Inf safety (strict-review batch 2) ───────────────────────────────────

def test_hybrid_rank_tolerates_nonfinite_dense_score(monkeypatch):
    gate = "leakage_gate"
    recs = [_rec("c1", "P1", gate), _rec("c2", "P2", gate)]

    def fake_import():
        def build_or_load_index():
            return (np.zeros((len(recs), 3), dtype="float32"), recs)

        def vector_search(query, embeddings, records, top_k=5):
            # Feed a NaN and an Inf dense score — must not poison the ranking.
            bad = [float("nan"), float("inf")]
            return [dict(r, _dense_score=bad[k]) for k, r in enumerate(records[:top_k])]

        return build_or_load_index, vector_search

    monkeypatch.setattr(hybrid_mod, "_import_sibling_modules", fake_import)
    monkeypatch.setattr(hybrid_mod, "retrieve_for_failure", lambda g, codes, limit=50: [])
    out = hybrid_mod.hybrid_rank("q", gate=gate, failure_codes=["P01"], top_k=5)
    for r in out:  # no crash; non-finite dense -> 0.0, so every score is finite
        assert math.isfinite(r.get("_final_score", 0.0))


def test_mmr_rerank_tolerates_nonfinite_relevance_and_embedding():
    nan_emb = np.array([float("nan"), 1.0], dtype="float32")
    ok_emb = np.array([1.0, 0.0], dtype="float32")
    cands = [
        {"concern_id": "A", "paper_id": "P1", "_final_score": float("nan"), "_dense_embedding": nan_emb},
        {"concern_id": "B", "paper_id": "P2", "_final_score": "not-a-number", "_dense_embedding": ok_emb},
        {"concern_id": "C", "paper_id": "P3", "_final_score": 0.7, "_dense_embedding": ok_emb},
    ]
    # Must not raise (non-numeric/NaN relevance) or loop on a NaN cosine.
    out = hybrid_mod._mmr_rerank(cands, top_k=3)
    assert len(out) == 3
