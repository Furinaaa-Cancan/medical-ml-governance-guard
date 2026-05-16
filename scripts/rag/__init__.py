"""MLGG RAG layer over the peer-review knowledge base.

This package retrieves and ranks reviewer concerns relevant to a gate
failure or free-text query, combining four signals (dense embeddings,
BM25, canonical-pattern tag overlap, severity boost).

Public API (re-exported here for convenience):
    rag_query              -- free-text or gate-anchored query (CLI + Python)
    rag_context_for_failure -- gate-failure → ranked concerns (the gate hook)
    format_for_gate_report  -- markdown rendering of concerns

For programmatic use::

    from scripts.rag import rag_query
    results = rag_query("missing calibration", gate="evaluation_quality_gate")

For the gate-failure path see ``scripts.core.gate_rag_bridge``
(re-exported here for convenience).

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
from scripts.core.gate_rag_bridge import (
    rag_context_for_failure,
    format_for_gate_report,
)

__all__ = [
    "rag_query",
    "rag_context_for_failure",
    "format_for_gate_report",
]
