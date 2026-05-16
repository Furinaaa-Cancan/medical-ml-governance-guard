"""Shared configuration for the MLGG RAG layer.

This module is the single source of truth for constants used across the RAG
package (``scripts/rag/``). Every other RAG module (``_embeddings``,
``_index_builder``, ``_vector_search``, ``_hybrid_ranker``, ``rag_query``,
``_gate_integration``) imports its constants from here, so changes propagate
consistently.

Design notes:
    * No network side effects at import time. The embedding model name is
      defined here, but loading the model is deferred to ``_embeddings.py``.
    * All filesystem paths are anchored to the repository root computed from
      ``__file__``, so they resolve regardless of the caller's CWD.
    * Hybrid ranking weights sum to ``1.0`` by construction
      (``WEIGHT_DENSE + WEIGHT_BM25 + WEIGHT_TAG_OVERLAP + WEIGHT_SEVERITY``).

See ``/tmp/mlgg_rag_design.md`` for the full design contract.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

# ---------------------------------------------------------------------------
# Path anchoring
# ---------------------------------------------------------------------------
# This file lives at: <repo_root>/scripts/rag/config.py
# So parents[2] resolves to <repo_root> regardless of cwd.
REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# Embedding model configuration
# ---------------------------------------------------------------------------
# Local sentence-transformer model. Chosen for: 384-dim output (small, fast
# cosine search over 817 vectors), strong English retrieval quality on MTEB,
# and no API key requirement. Downloaded once from HuggingFace on first use
# by ``_embeddings.get_model()``; cached by sentence_transformers thereafter.
EMBEDDING_MODEL: Final[str] = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM: Final[int] = 384

# ---------------------------------------------------------------------------
# Cache locations (relative to repo root)
# ---------------------------------------------------------------------------
CACHE_DIR: Final[Path] = REPO_ROOT / ".cache" / "rag"
EMBEDDINGS_CACHE: Final[Path] = CACHE_DIR / "concerns_embeddings.npz"
# SHA256 of the KB file; used by ``_index_builder`` to invalidate the
# embeddings cache automatically when the underlying KB changes.
KB_HASH_CACHE: Final[Path] = CACHE_DIR / "kb_hash.txt"

# ---------------------------------------------------------------------------
# Knowledge base location
# ---------------------------------------------------------------------------
KB_PATH: Final[Path] = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"

# ---------------------------------------------------------------------------
# Hybrid ranking weights
# ---------------------------------------------------------------------------
# Combined score (computed in ``_hybrid_ranker``) is:
#   final = WEIGHT_DENSE * dense_cosine
#         + WEIGHT_BM25 * bm25_normalized
#         + WEIGHT_TAG_OVERLAP * tag_overlap_score
#         + WEIGHT_SEVERITY * severity_boost
# The four weights MUST sum to 1.0.
WEIGHT_DENSE: Final[float] = 0.5         # cosine similarity from dense embeddings
WEIGHT_BM25: Final[float] = 0.3          # from scripts.rag.retrieval.bm25
WEIGHT_TAG_OVERLAP: Final[float] = 0.15  # Q4-canonical-pattern weighted bonus
WEIGHT_SEVERITY: Final[float] = 0.05     # CRITICAL > HIGH > MEDIUM > LOW small boost

# Sanity check (cheap; runs once at import).
assert abs(
    (WEIGHT_DENSE + WEIGHT_BM25 + WEIGHT_TAG_OVERLAP + WEIGHT_SEVERITY) - 1.0
) < 1e-9, "Hybrid ranking weights must sum to 1.0"

# ---------------------------------------------------------------------------
# Query defaults
# ---------------------------------------------------------------------------
# Number of concerns returned by the public API by default.
DEFAULT_TOP_K: Final[int] = 5
# Upper bound on candidates pulled from vector + BM25 before reranking.
DEFAULT_MAX_CANDIDATES_BEFORE_RERANK: Final[int] = 50

# ---------------------------------------------------------------------------
# Severity ordering (used by ``_hybrid_ranker`` for the severity boost)
# ---------------------------------------------------------------------------
# Higher value = stronger boost. Values are intentionally on [0, 1] so the
# weighted contribution stays bounded by WEIGHT_SEVERITY.
SEVERITY_BOOST: Final[dict[str, float]] = {
    "CRITICAL": 1.0,
    "HIGH": 0.66,
    "MEDIUM": 0.33,
    "LOW": 0.0,
}
