"""Dependency-light enrichment helpers for the OFFLINE rag_query path.

Promoted (W-rag-path-truth-fixes) from ``scripts.core.gate_rag_bridge``,
which is 100% dead in production (the 33-gate runtime is BM25-only via
``scripts.core._gate_framework.build_report_envelope`` ->
``scripts.rag.retrieval.bm25.retrieve_for_failure``). This module lifts the
three pieces of orphan value that *should* shape the offline paper-audit /
eval path into ``scripts.rag`` so ``scripts.rag.query.rag_query`` and the
eval harnesses can share them:

1. :func:`synthesize_query` -- snake_case -> space normalization so the
   embedding model (trained on natural language, not snake_case) gets a
   clean dense signal. Replaces the weaker bare ``f"{gate} {' '.join(codes)}"``
   join in ``scripts/rag/evals/harness.py`` and ``run_eval.py``.
2. :func:`is_off_modality_query` (+ :data:`MODALITY_DENYLIST`) -- whole-word
   off-MLGG-scope detection (omics / CV / NLP / survival), so rag_query can
   attach an ``_off_modality`` advisory flag to each record.
3. :func:`curated_precedent_for` -- injects the curated MLGG-P01/P04
   fit-before-split precedent at top-1 for known RAG blind spots; honors
   ``MLGG_RAG_DISABLE_CURATED=1`` for A/B regression.

IMPORT DISCIPLINE: this module imports only ``os`` and ``re`` from the
stdlib. It MUST NOT import torch / sentence_transformers / the dense index,
so ``import scripts.rag._enrich`` stays cheap and torch-free (the gate path
and ``--help`` rely on the rag package not pulling torch at import).
"""

from __future__ import annotations

import os
import re
from typing import Any, Optional

# ---------------------------------------------------------------------------
# (a) Query synthesis -- snake_case -> space normalization
# ---------------------------------------------------------------------------


def synthesize_query(
    failure_codes: Optional[list[str]],
    query_hint: Optional[str] = None,
    gate_name: Optional[str] = None,
) -> str:
    """Build a free-text query from failure codes + optional hint.

    Underscores in failure codes (e.g. ``missing_calibration``) are turned
    into spaces because the embedding model was trained on natural-language
    text, not snake_case tokens; this materially improves dense recall.

    Args:
        failure_codes: Symbolic failure tokens emitted by a gate, e.g.
            ``["missing_calibration", "no_ci"]``.  May be empty / ``None``.
        query_hint: Optional free-text hint from the caller, typically a
            short human description of the failing scenario.
        gate_name: Fallback source for the synthesised query when both
            ``failure_codes`` and ``query_hint`` are empty.  Required by
            ``hybrid_rank`` which rejects empty queries (cosine of a
            zero vector is meaningless).

    Returns:
        A whitespace-trimmed query string with underscores normalised to
        spaces.  Guaranteed non-empty when ``gate_name`` is supplied.
    """
    code_text = " ".join(failure_codes or [])
    raw = f"{code_text} {query_hint or ''}".strip()
    # Normalise snake_case -> space-separated for better embedding quality.
    synthesised = raw.replace("_", " ").strip()
    if synthesised:
        return synthesised
    # Empty-input fallback: use the gate name itself.  Without this the
    # caller would hit ``ValueError`` inside ``vector_search`` (cosine
    # cannot rank against an empty query).
    if gate_name:
        return gate_name.replace("_", " ").strip()
    return ""


# ---------------------------------------------------------------------------
# (b) Off-MLGG-modality detection
# ---------------------------------------------------------------------------
# MLGG scope is retrospective cohort binary classification (tabular EHR /
# registry / case-control / cross-sectional). Queries about generative
# models, NLP, CV, federated learning, survival analysis, etc. fall
# outside scope; their BGE embeddings retrieve "plausible but wrong"
# MLGG concerns. The denylist catches them via query tokens.
MODALITY_DENYLIST: frozenset[str] = frozenset([
    # Generative models
    "vae", "gan", "diffusion", "generative",
    # NLP architectures
    "bert", "gpt", "transformer", "tokenization", "attention",
    "natural_language", "nlp",
    # CV architectures
    "unet", "resnet", "vgg", "yolo", "segmentation", "image_patch",
    # Domain
    "federated", "quantum", "reinforcement", "graph_neural", "message_passing",
    # Time-to-event / survival (different statistical paradigm)
    "cox", "hazard", "survival", "kaplan_meier",
    # Omics (different modality)
    "rnaseq", "scrnaseq", "scrna", "omics", "genomics", "transcriptom",
    "gene_expression", "single_cell",
])


def _normalize_for_denylist(s: str) -> str:
    """Lower-case and collapse non-alphanumeric runs (incl. ``_``) to spaces.

    Both the query and each denylist token are passed through this
    transform so whole-word matching reduces to a space-padded substring
    check (``" {token} " in " {normalised_query} "``). Underscores,
    hyphens, punctuation and arbitrary whitespace all collapse to a
    single space, so ``"graph_neural"``, ``"graph-neural"`` and
    ``"graph neural"`` are equivalent. Empty / ``None`` inputs return
    ``""`` so the caller can pad-and-check safely without a branch.
    """
    if not s:
        return ""
    # ``[\W_]+`` includes underscore because ``\w`` keeps it as a
    # word-char; without explicit ``_`` the token "graph_neural" would
    # survive intact and never match "graph neural".
    return re.sub(r"[\W_]+", " ", s.lower()).strip()


# Pre-normalise the denylist ONCE at import time. Each entry is wrapped
# in single spaces so the membership test below becomes a whole-word
# substring check: ``" vae "`` is NOT a substring of ``" variational
# autoencoder "``, but IS a substring of ``" vae loss curve "``.
_NORMALISED_DENYLIST: frozenset[str] = frozenset(
    f" {_normalize_for_denylist(tok)} " for tok in MODALITY_DENYLIST
)


def is_off_modality_query(query: str) -> bool:
    """Return True iff ``query`` carries an off-MLGG-scope modality token.

    Whole-word match (token boundaries on both sides) so ``"vae"`` matches
    ``"vae loss"`` but not ``"variational"``. Both the query and every
    denylist token are passed through :func:`_normalize_for_denylist`
    (which collapses all non-alphanumerics -- including underscores -- to
    single spaces). Empty / ``None`` queries return ``False``.
    """
    if not query:
        return False
    padded = f" {_normalize_for_denylist(query)} "
    if padded == "  ":
        return False
    return any(tok in padded for tok in _NORMALISED_DENYLIST)


# ---------------------------------------------------------------------------
# (c) Curated fit-before-split precedent (MLGG-P01 / P04 RAG blind spot)
# ---------------------------------------------------------------------------
# The peer-review-kb has near-zero coverage of MLGG-P01's canonical failure
# pattern -- "fit a scaler / encoder / imputer / PCA on full pool BEFORE
# train/test split". Until KB curation closes the gap, this curated map
# injects a CRITICAL concern that fires BEFORE hybrid_rank so the offline
# paper-audit carries authoritative MLGG-P01 precedent rather than off-topic
# split-protocol fallbacks.
#
# Disable via env-var ``MLGG_RAG_DISABLE_CURATED=1`` for A/B / regression
# eval; the bypass restores pre-patch behaviour exactly.
_CURATED_PRECEDENT_FIT_BEFORE_SPLIT: dict[str, Any] = {
    "concern_id": "MLGG-CURATED-P01-fit_before_split",
    "paper_id": "MLGG-CURATED",
    "severity": "CRITICAL",
    "category": "preprocessing_leakage",
    "mlgg_dimension": 3,
    "mlgg_gates": ["split_protocol_gate", "feature_engineering_audit_gate"],
    "mlgg_rules": ["MLGG-P01"],
    "canonical_pattern_id": "CP-MLGG-P01",
    "tags": [
        "fit_on_full_data_before_split",
        "scaler_leakage",
        "preprocessing_split_leakage",
        "transform_fit_leakage",
    ],
    "concern_text": (
        "MLGG-P01 non-negotiable: ALL fit() calls (scaler, encoder, "
        "imputer, PCA, target encoder, feature selector, calibration) "
        "MUST run on the training fold only. Fitting on the full pool "
        "before train/test split — e.g. `StandardScaler().fit(X)` then "
        "splitting — leaks test-set statistics (mean, std, quantiles, "
        "principal components, target means) into the training pipeline "
        "and inflates internal-validation performance with optimistic "
        "bias that does not generalise. The KB has weak sibling "
        "precedent: PR-003-C03 (validation-cohort imputation, MLGG-P04), "
        "PR-113-C01 (SMOTE before split), PR-EXP-0155-C04 "
        "(preprocessing_before_split tag on tile filtering). Treat any "
        "manuscript whose preprocessing pipeline is unclear about "
        "fit-vs-transform ordering as a CRITICAL fail until pipeline "
        "audit confirms train-fold-only fit (sklearn Pipeline + CV is "
        "the canonical mitigation)."
    ),
    "author_response": "",
    "resolved": False,
    "_dense_score": 1.0,
    "_bm25_score": 1.0,
    "_tag_overlap_score": 1.0,
    "_tag_overlap_raw": 1.0,
    "_severity_boost": 1.0,
    "_severity_scale": 1.0,
    "_final_score": 1.0,
    "_match_reasons": ["curated_fallback:MLGG-P01"],
    "_synthetic_curated": True,
}

# Curated map: (rule_code, gate_name) -> curated record. Extend here when
# other MLGG non-negotiables surface as RAG blind spots. For now scoped to
# P01 / P04 (imputation-before-split shares the same precedent).
_CURATED_PRECEDENT_BY_KEY: dict[tuple[str, str], dict[str, Any]] = {
    ("MLGG-P01", "split_protocol_gate"): _CURATED_PRECEDENT_FIT_BEFORE_SPLIT,
    ("MLGG-P01", "feature_engineering_audit_gate"): _CURATED_PRECEDENT_FIT_BEFORE_SPLIT,
    ("MLGG-P04", "split_protocol_gate"): _CURATED_PRECEDENT_FIT_BEFORE_SPLIT,
    ("MLGG-P04", "feature_engineering_audit_gate"): _CURATED_PRECEDENT_FIT_BEFORE_SPLIT,
}

# Lexical triggers for free-text queries that name the failure mode
# without carrying an explicit MLGG rule code. Two-set matcher: at least
# one operation token AND at least one split-ordering token must hit.
_FIT_BEFORE_SPLIT_OP_TOKENS: frozenset[str] = frozenset([
    "scaler", "standardscaler", "minmax", "standardize", "standardise",
    "normalize", "normalise", "normalization", "normalisation",
    "z-score", "zscore", "impute", "imputer", "imputation",
    "pca", "encoder", "target_encoder", "target encoder",
    "fit_transform", "preprocess", "preprocessing",
])
_FIT_BEFORE_SPLIT_ORDER_TOKENS: frozenset[str] = frozenset([
    "before split", "before splitting", "prior to split",
    "before the split", "fit on full", "fit on all",
    "fit on the entire", "on full data", "on all data",
    "on entire dataset", "on the whole dataset",
    "full dataset before", "all data before",
])


def curated_precedent_for(
    gate_name: Optional[str],
    failure_codes: Optional[list[str]],
    query: Optional[str],
) -> Optional[dict[str, Any]]:
    """Return the curated concern for known RAG blind spots, or None.

    Resolution order:
      1. (rule_code, gate_name) exact match in :data:`_CURATED_PRECEDENT_BY_KEY`.
      2. Lexical: query carries an operation token AND a split-ordering
         token (L27-style free-text without an explicit code).

    Disabled when ``MLGG_RAG_DISABLE_CURATED=1`` (regression-eval bypass).
    Always returns a FRESH dict (callers may mutate / prepend).
    """
    if os.environ.get("MLGG_RAG_DISABLE_CURATED") == "1":
        return None
    # (1) code-based
    for code in failure_codes or []:
        key = (code, gate_name)
        if key in _CURATED_PRECEDENT_BY_KEY:
            return dict(_CURATED_PRECEDENT_BY_KEY[key])
    # (2) lexical free-text trigger
    q = (query or "").lower()
    if not q:
        return None
    has_op = any(tok in q for tok in _FIT_BEFORE_SPLIT_OP_TOKENS)
    has_order = any(tok in q for tok in _FIT_BEFORE_SPLIT_ORDER_TOKENS)
    if has_op and has_order:
        return dict(_CURATED_PRECEDENT_FIT_BEFORE_SPLIT)
    return None
