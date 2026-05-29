"""DEPRECATED shim — the gate-failure RAG surface has moved.

History: this module used to synthesize a query from a gate failure,
delegate to :func:`scripts.rag.retrieval.hybrid.hybrid_rank`, and render
the result as markdown for a (never-built) gate report renderer. It was
NEVER on the production gate path: the 33-gate runtime populates
``report.json``'s ``peer_review_context`` via
:func:`scripts.core._gate_framework.build_report_envelope`, which calls
``scripts.rag.retrieval.bm25.retrieve_for_failure`` directly (BM25-only,
pure stdlib, deterministic). The hybrid / curated-precedent / off-modality
logic was only ever useful to the OFFLINE paper-audit / eval path.

As of the rag-path-truth-fixes work that value was PROMOTED into the
torch-free :mod:`scripts.rag._enrich` and wired into the live offline path
:func:`scripts.rag.query.rag_query`. The helpers it now owns are
``synthesize_query``, ``is_off_modality_query``, ``curated_precedent_for``
and the ``MODALITY_DENYLIST`` data. The markdown render surface
(``format_for_gate_report``, ``rag_context_for_failure`` and their hedges)
had no production renderer and was deleted rather than relocated.

This module is intentionally left as a near-empty shim (not deleted) so
the import path ``scripts.core.gate_rag_bridge`` does not vanish out from
under any out-of-tree caller mid-migration; it re-exports the promoted
names from their new home. New code should import from
:mod:`scripts.rag._enrich` (or use :func:`scripts.rag.query.rag_query`)
directly.
"""

from __future__ import annotations

# Back-compat re-exports. The implementations now live in the torch-free
# offline-path helper module ``scripts.rag._enrich`` (promoted there by the
# rag-path-truth-fixes Decisions 1-2). Importing them here keeps
# ``from scripts.core.gate_rag_bridge import _is_off_modality_query`` etc.
# working for any straggler caller during migration. The leading-underscore
# aliases preserve the historical names this module exported.
from scripts.rag._enrich import (  # noqa: F401  (re-export shim)
    MODALITY_DENYLIST,
    _normalize_for_denylist,
)
from scripts.rag._enrich import curated_precedent_for as _curated_precedent_for
from scripts.rag._enrich import is_off_modality_query as _is_off_modality_query
from scripts.rag._enrich import synthesize_query as _synthesize_query

__all__ = [
    "MODALITY_DENYLIST",
    "_curated_precedent_for",
    "_is_off_modality_query",
    "_normalize_for_denylist",
    "_synthesize_query",
]
