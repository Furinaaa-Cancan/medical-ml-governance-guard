"""MLGG RAG layer over the peer-review knowledge base.

This package retrieves and ranks reviewer concerns relevant to a gate
failure or free-text query, combining four signals (dense embeddings,
BM25, canonical-pattern tag overlap, severity boost).

Public API:
    rag_query  --  free-text or gate-anchored query (CLI + Python)

For programmatic use::

    from scripts.rag import rag_query
    results = rag_query("missing calibration", gate="evaluation_quality_gate")

The offline paper-audit / eval path shapes ``rag_query``'s results with
three torch-free enrichment helpers in ``scripts.rag._enrich``
(``synthesize_query``, ``is_off_modality_query``, ``curated_precedent_for``).
These were promoted (rag-path-truth-fixes) out of the now-dead
``scripts.core.gate_rag_bridge`` orchestrator + markdown renderer; that
module is a thin back-compat shim today. The 33-gate runtime does NOT use
this package — it retrieves via the BM25-only
``scripts.rag.retrieval.bm25.retrieve_for_failure`` from
``scripts.core._gate_framework.build_report_envelope``.

Re-exporting bridge symbols from here would create a circular import (the
old bridge imported `scripts.rag.retrieval.hybrid`, which would re-enter
this `__init__.py` mid-load).  Keep imports explicit.

Internal modules:
    config             -- shared constants (weights, paths, model name)
    embeddings         -- sentence-transformer wrapper
    query              -- public query API + CLI entry
    retrieval/dense    -- dense vector search
    retrieval/bm25     -- keyword retrieval
    retrieval/hybrid   -- 4-signal fusion (the workhorse)
    index/builder      -- KB → embedding matrix
    index/cache        -- atomic cache I/O primitives
    evals/harness      -- retrieval evaluation harness
"""

from scripts.rag.query import rag_query

__all__ = ["rag_query"]
