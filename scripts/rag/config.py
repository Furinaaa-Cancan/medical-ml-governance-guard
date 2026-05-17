"""Shared configuration for the MLGG RAG layer.

This module is the single source of truth for constants used across the RAG
package (``scripts/rag/``). Every other RAG module (``embeddings``,
``index.builder``, ``retrieval.dense``, ``retrieval.bm25``,
``retrieval.hybrid``, ``query``) imports its constants from here, so
changes propagate consistently. The gate bridge that consumes the RAG
layer lives in :mod:`scripts.core.gate_rag_bridge` and reuses the same
constants.

Design notes:
    * No network side effects at import time. The embedding model name is
      defined here, but loading the model is deferred to ``embeddings.py``.
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
# by ``embeddings.get_model()``; cached by sentence_transformers thereafter.
EMBEDDING_MODEL: Final[str] = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM: Final[int] = 384

# ---------------------------------------------------------------------------
# Cache locations (relative to repo root)
# ---------------------------------------------------------------------------
CACHE_DIR: Final[Path] = REPO_ROOT / ".cache" / "rag"
EMBEDDINGS_CACHE: Final[Path] = CACHE_DIR / "concerns_embeddings.npz"
# SHA256 of the KB file; used by ``index.builder`` to invalidate the
# embeddings cache automatically when the underlying KB changes.
KB_HASH_CACHE: Final[Path] = CACHE_DIR / "kb_hash.txt"

# ---------------------------------------------------------------------------
# Knowledge base location
# ---------------------------------------------------------------------------
KB_PATH: Final[Path] = REPO_ROOT / "references" / "case-studies" / "peer-review-kb.json"

# ---------------------------------------------------------------------------
# Hybrid ranking weights
# ---------------------------------------------------------------------------
# Combined score (computed in ``retrieval.hybrid``) is:
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
# Severity ordering (used by ``retrieval.hybrid`` for the severity boost)
# ---------------------------------------------------------------------------
# Higher value = stronger boost. Values are intentionally on [0, 1] so the
# weighted contribution stays bounded by WEIGHT_SEVERITY.
SEVERITY_BOOST: Final[dict[str, float]] = {
    "CRITICAL": 1.0,
    "HIGH": 0.66,
    "MEDIUM": 0.33,
    "LOW": 0.0,
}

# ---------------------------------------------------------------------------
# Adaptive boost guards (Fix 2 + Fix 3 from 5-agent ranker eval)
# ---------------------------------------------------------------------------
# CP_TAG_BOOST_DENSE_FLOOR — minimum top-1 dense cosine required before the
# canonical-pattern / tag-overlap bonus is applied. When the strongest dense
# candidate scores below this floor the query is "thin" on the KB: pattern
# corroboration becomes noise (it can flip same-pattern siblings past a
# better off-pattern match). Skip the bonus in that regime.
CP_TAG_BOOST_DENSE_FLOOR: Final[float] = 0.70

# SEVERITY_FULL_SPREAD — dense-score spread (max - min within the candidate
# pool) at which the severity boost is applied at full WEIGHT_SEVERITY. When
# the pool is tighter than this threshold (dense scores cluster), the boost
# is linearly scaled down so an off-topic CRITICAL cannot leapfrog an
# on-topic HIGH on a thin topic. Above this spread, the boost is full.
SEVERITY_FULL_SPREAD: Final[float] = 0.20

# TAG_OVERLAP_MIN_SHARED — minimum number of shared tags between two
# concerns in the same canonical pattern before the corroboration bonus
# fires (W7-P0 fix per W6-W2 finding). Default 1.
#
# Background: The original threshold of 2 made the signal architecturally
# dead. Of 12,747 within-CP pairs in the KB, only 23 (0.2%) share >=2
# tags, while 229 (1.8%) share >=1. Most CP clusters contain many
# paper-specific tags ("no_external_validation_for_combined") that
# appear as singletons; the canonical reuse pattern lives at the >=1
# level. Lowering to 1 measured +0.017 on mean_top1_score across the
# hybrid eval with zero coverage / hit@K regression.
TAG_OVERLAP_MIN_SHARED: Final[int] = 1

# ---------------------------------------------------------------------------
# MMR diversity reranking (G4)
# ---------------------------------------------------------------------------
MMR_LAMBDA: Final[float] = 0.7  # 70% relevance, 30% diversity
MMR_SAME_PAPER_PENALTY: Final[float] = 0.5  # extra similarity for same-paper pairs

# MMR cosine penalty floor (W2 fix for Q9 free-text regression)
# Cosine similarities below this are treated as "distinct enough" — no
# diversity penalty applied. Above this, MMR penalizes near-duplicates.
# Default 0.88: BGE-small embeddings of "semantically related but
# distinct" concerns typically cluster at 0.75-0.85; near-duplicates
# (same paper rephrased, copy-paste-similar) sit above 0.90.
MMR_COSINE_FLOOR: Final[float] = 0.88

# ---------------------------------------------------------------------------
# Within-CP dense corroboration (W9-B2 replacement for tag_overlap)
# ---------------------------------------------------------------------------
# W7-P4 + W7-P6 finding: the tag_overlap signal is architecturally weak
# because 89.5% of KB tags are singletons; even with TAG_OVERLAP_MIN_SHARED=1
# 45/49 CPs are DEAD at the tag-overlap signal. The replacement strategy
# uses **within-CP dense cosine corroboration**: for each candidate, find
# its same-canonical_pattern siblings in the pool, average the cosine
# similarity to the top-K most-similar siblings, and use that as the
# corroboration score. This captures "another concern in the same CP that
# is also dense-similar to the query" without depending on shared tags.
#
# When ``USE_DENSE_CORROBORATION`` is True the new signal feeds
# ``_tag_overlap_score`` (kept-name for back-compat with downstream readers
# and ``_match_reasons``); when False, the legacy tag-overlap behaviour
# from W7-P0 is used. The eval harness can A/B these by flipping the flag.
#
# W9-B2 measurement (2026-05-17, references/retrieval_eval/scenarios.json,
# n=30, n_evaluable=26): enabling dense corroboration moves mean_top1_score
# from 0.649 -> 0.698 (+0.049, substantial), keeps mean_hit_at_k pinned at
# 1.0 (already saturated), keeps coverage_rate at 0.867, but DROPS
# mean_tag_precision_at_k from 0.538 -> 0.462 (-0.077). Tag-precision@K is
# the SECONDARY "diversity-aware caveat" metric per W5 (it rewards staying
# in tag clusters, which is exactly what we want to stop privileging), so
# in principle the trade is favourable -- but the -0.077 drop exceeds the
# >0.05 harm threshold gating an enable-by-default rollout. Default is
# kept at False until either (a) a richer eval set demonstrates the trade
# is net-positive on a downstream gate, or (b) we extend the harness with
# a tag-set-aware metric that does not collapse on diversity. Flip to True
# locally to A/B; the framework + test surface ship now so the next eval
# wave does not have to re-litigate the implementation.
USE_DENSE_CORROBORATION: Final[bool] = False
# Average cosine to the top-K most-similar same-CP siblings (capped by the
# number of siblings actually present; siblings include the candidate's
# own embedding minus itself).
DENSE_CORROBORATION_TOP_K: Final[int] = 3
