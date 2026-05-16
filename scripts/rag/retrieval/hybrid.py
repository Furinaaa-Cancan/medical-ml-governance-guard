"""Hybrid ranker for the MLGG RAG layer.

Located at ``scripts/rag/retrieval/hybrid.py``. Completes the
``retrieval/`` trio (``dense``, ``bm25``, ``hybrid``) by fusing the two
retrieval signals with the canonical-pattern and severity boosts.

Combines four ranking signals over the peer-review knowledge base
(`references/case-studies/peer-review-kb.json`) into a single score per
concern:

    final = WEIGHT_DENSE        * dense_cosine
          + WEIGHT_BM25         * bm25_normalized
          + WEIGHT_TAG_OVERLAP  * tag_overlap_score
          + WEIGHT_SEVERITY     * severity_boost

Signals:
    * **Dense**: cosine similarity from ``retrieval.dense.vector_search``
      over the cached sentence-transformer embeddings produced by
      ``index.builder.build_or_load_index``.
    * **BM25**: keyword-overlap ranking from
      ``scripts.rag.retrieval.bm25.retrieve_for_failure``. Only
      consulted when both ``gate`` and ``failure_codes`` are supplied.
    * **Tag overlap (canonical-pattern boost)**: candidates sharing
      ``canonical_pattern_id`` *and* >=2 tags with another candidate get
      a small bonus, since corroborating reviewer concerns across papers
      strengthen confidence in the pattern.
    * **Severity**: small additive bump so a CRITICAL concern wins a tie
      against a topically equivalent LOW concern.

The module is read-only with respect to the KB. Filesystem side effects
(embedding cache writes) are owned by ``index.builder``.

See ``/tmp/mlgg_rag_design.md`` for the full design contract.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple


from scripts.rag import config
from scripts.rag.retrieval.bm25 import retrieve_for_failure

# ---------------------------------------------------------------------------
# Sibling-module imports with graceful fallback
# ---------------------------------------------------------------------------
# Agents A3 (``index.builder``) and A4 (``retrieval.dense``) land in
# parallel. We resolve them lazily inside ``hybrid_rank`` so that this
# module can still be imported (e.g. for static checks or partial unit
# tests) before they exist on disk.


def _import_sibling_modules() -> Tuple[Callable[..., Any], Callable[..., Any]]:
    """Resolve ``build_or_load_index`` and ``vector_search`` lazily.

    Returns:
        A pair ``(build_or_load_index, vector_search)`` of callables.

    Raises:
        RuntimeError: If either sibling module is missing. The error
            message names which one so the caller can spot a partial
            rollout quickly.
    """

    try:
        from scripts.rag.index.builder import build_or_load_index  # type: ignore[import-not-found]  # noqa: E501
    except Exception as exc:  # pragma: no cover - depends on rollout order
        raise RuntimeError(
            "scripts.rag.index.builder.build_or_load_index is required "
            "by retrieval.hybrid but could not be imported"
        ) from exc

    try:
        from scripts.rag.retrieval.dense import vector_search  # type: ignore[import-not-found]  # noqa: E501
    except Exception as exc:  # pragma: no cover - depends on rollout order
        raise RuntimeError(
            "scripts.rag.retrieval.dense.vector_search is required by "
            "retrieval.hybrid but could not be imported"
        ) from exc

    return build_or_load_index, vector_search


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_bm25(scores: List[float]) -> List[float]:
    """Min-max normalize BM25-style raw scores into ``[0, 1]``.

    BM25 scores from ``retrieve_for_failure`` are integer counts of
    keyword overlap (3x for tag hits, 1x for body hits) and are not
    bounded, so we normalize per-call against the local maximum. A
    degenerate batch with all-equal scores collapses to ``1.0`` for the
    matched concerns (every BM25 hit is informative relative to dense-
    only candidates that scored 0).

    Args:
        scores: Raw BM25 scores in the order the BM25 path returned.

    Returns:
        List of the same length with each value mapped to ``[0, 1]``.
    """

    if not scores:
        return []
    lo = min(scores)
    hi = max(scores)
    if hi <= 0:
        return [0.0 for _ in scores]
    if hi == lo:
        return [1.0 for _ in scores]
    span = hi - lo
    return [(s - lo) / span for s in scores]


def _bm25_raw_score(concern: Dict[str, Any], rank: int, total: int) -> float:
    """Derive a comparable BM25-equivalent score from a ranked concern.

    Since the upstream ``retrieval.bm25._tag_result`` enhancement
    (commit after qa-wave-2026-05-13), ``retrieve_for_failure`` returns each
    concern with a real ``_score`` field (raw keyword-overlap = 3×tag +
    text). We prefer that signal; fall back to rank-based geometric decay
    only when ``_score`` is absent (older callers / older KB cache).

    Args:
        concern: The BM25-returned concern dict.
        rank: 0-based rank from ``retrieve_for_failure`` (0 = top hit).
        total: Total number of BM25 results (used for the legacy fallback).

    Returns:
        A non-negative float; larger = stronger BM25 signal. Caller
        normalizes across all candidates via ``_normalize_bm25``.
    """
    if total <= 0:
        return 0.0
    raw_score = concern.get("_score")
    if isinstance(raw_score, (int, float)) and raw_score >= 0:
        # Real keyword-overlap score from the BM25 retriever — preferred.
        # Severity_fallback returns are tagged 0 here, which naturally
        # gives them a weak BM25 contribution after _normalize_bm25.
        return float(raw_score)
    # Legacy fallback: rank-based geometric decay (pre-_score retriever).
    decay = max(0.1, (total - rank) / total)
    if concern.get("_retrieval_mode") == "severity_fallback":
        return 0.25 * decay
    return decay


def _severity_boost(concern: Dict[str, Any]) -> float:
    """Look up the severity bonus for ``concern``.

    Args:
        concern: KB concern record with a ``severity`` field.

    Returns:
        Boost value in ``[0, 1]`` from ``config.SEVERITY_BOOST``.
        Unknown / missing severity → 0.0.
    """

    sev = concern.get("severity")
    if not isinstance(sev, str):
        return 0.0
    return config.SEVERITY_BOOST.get(sev.upper(), 0.0)


def _concern_id(concern: Dict[str, Any]) -> Optional[str]:
    """Return the canonical concern id, preferring ``concern_id``.

    Some legacy code paths use ``id`` as a fallback; we accept either
    so callers from older modules still dedupe correctly.

    Args:
        concern: KB concern record.

    Returns:
        The string identifier, or ``None`` if neither field is present.
    """

    cid = concern.get("concern_id") or concern.get("id")
    return cid if isinstance(cid, str) else None


def _tag_overlap_scores(
    candidates: List[Dict[str, Any]],
) -> Dict[str, float]:
    """Compute a per-candidate tag-overlap bonus on ``[0, 1]``.

    A candidate gets a boost when another candidate from the **same**
    ``canonical_pattern_id`` shares at least two tags with it. This
    rewards corroborating evidence across reviewer concerns within a
    canonical pattern without amplifying near-duplicate concerns from
    the same paper.

    The score is scaled by the count of qualifying partners, capped
    so the boost stays bounded: ``score = min(1.0, 0.3 * partners)``.

    Args:
        candidates: Concern records (post-union, pre-rerank).

    Returns:
        Mapping ``concern_id -> overlap_score``.
    """

    out: Dict[str, float] = {}
    # Group by canonical_pattern_id (skip null / missing).
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in candidates:
        cp = c.get("canonical_pattern_id")
        if not isinstance(cp, str) or not cp:
            continue
        groups.setdefault(cp, []).append(c)

    for cp, members in groups.items():
        if len(members) < 2:
            continue
        # Pre-compute tag sets to avoid O(n^2) re-tokenization.
        tag_sets: List[Tuple[Optional[str], set]] = []
        for m in members:
            tags = m.get("tags") or []
            tset = {t for t in tags if isinstance(t, str)}
            tag_sets.append((_concern_id(m), tset))

        for i, (cid_i, tags_i) in enumerate(tag_sets):
            if cid_i is None:
                continue
            partners = 0
            for j, (cid_j, tags_j) in enumerate(tag_sets):
                if i == j or cid_j is None:
                    continue
                if len(tags_i & tags_j) >= 2:
                    partners += 1
            if partners > 0:
                out[cid_i] = min(1.0, 0.3 * partners)

    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def hybrid_rank(
    query: str,
    gate: Optional[str] = None,
    failure_codes: Optional[List[str]] = None,
    top_k: int = config.DEFAULT_TOP_K,
) -> List[Dict[str, Any]]:
    """Run the full hybrid retrieval pipeline.

    Pipeline:
        1. Build (or load) the dense index via ``build_or_load_index``.
        2. Run dense vector search for the top
           ``DEFAULT_MAX_CANDIDATES_BEFORE_RERANK`` (default 50).
        3. If both ``gate`` and ``failure_codes`` are supplied, also
           fetch the BM25-style results from
           ``retrieval.bm25.retrieve_for_failure`` and union
           them (dedup by ``concern_id``).
        4. Apply the optional gate filter (drop concerns whose
           ``mlgg_gates`` list does not contain ``gate``).
        5. Compute the canonical-pattern tag-overlap bonus across
           the surviving candidates.
        6. Apply the severity boost.
        7. Combine signals with the weights in ``config`` and
           return the top ``top_k`` records, each annotated with
           ``_dense_score``, ``_bm25_score``, ``_tag_overlap_score``,
           ``_severity_boost``, ``_final_score``, and a human-readable
           ``_match_reasons`` list.

    Args:
        query: Free-text question or failure description.
        gate: Optional MLGG gate name (e.g. ``"evaluation_quality_gate"``).
            When provided, candidates whose ``mlgg_gates`` field does not
            contain this string are filtered out.
        failure_codes: Optional list of gate failure / warning codes.
            Required to engage the BM25 path; ignored unless ``gate`` is
            also set.
        top_k: Number of final results to return. Defaults to
            ``config.DEFAULT_TOP_K``.

    Returns:
        Up to ``top_k`` concern dicts in descending ``_final_score``
        order. Each is a shallow copy of the underlying KB record with
        the scoring metadata fields added (so callers can inspect why
        a concern was surfaced).

    Raises:
        RuntimeError: If the sibling vector-search / index-builder
            modules are not yet available.
        TypeError: If ``query`` is not a string.
    """

    if not isinstance(query, str):
        raise TypeError(
            f"hybrid_rank expected query to be str, got {type(query).__name__}"
        )

    build_or_load_index, vector_search = _import_sibling_modules()

    # ---- 1. Build / load the dense index ---------------------------------
    embeddings, records = build_or_load_index()

    # ---- 2. Dense candidates --------------------------------------------
    dense_top_k = config.DEFAULT_MAX_CANDIDATES_BEFORE_RERANK
    dense_hits: List[Dict[str, Any]] = vector_search(
        query, embeddings, records, top_k=dense_top_k
    )

    # Index dense scores + ranks by concern_id.
    dense_score_by_id: Dict[str, float] = {}
    dense_rank_by_id: Dict[str, int] = {}
    for rank, hit in enumerate(dense_hits):
        cid = _concern_id(hit)
        if cid is None:
            continue
        # Defensive: vector_search must add _dense_score, but tolerate
        # a raw cosine in a 'score' field for forward-compat.
        score = hit.get("_dense_score")
        if score is None:
            score = hit.get("score", 0.0)
        try:
            dense_score_by_id[cid] = float(score)
        except (TypeError, ValueError):
            dense_score_by_id[cid] = 0.0
        dense_rank_by_id[cid] = rank

    # ---- 3. BM25 candidates (optional) ----------------------------------
    bm25_score_by_id: Dict[str, float] = {}
    bm25_records_by_id: Dict[str, Dict[str, Any]] = {}
    if gate and failure_codes:
        bm25_hits = retrieve_for_failure(
            gate,
            failure_codes,
            limit=dense_top_k,
        )
        raw_scores = [
            _bm25_raw_score(c, rank, len(bm25_hits))
            for rank, c in enumerate(bm25_hits)
        ]
        normalized = _normalize_bm25(raw_scores)
        for c, norm in zip(bm25_hits, normalized):
            cid = _concern_id(c)
            if cid is None:
                continue
            bm25_score_by_id[cid] = norm
            bm25_records_by_id[cid] = c

    # ---- 4. Union + dedupe ----------------------------------------------
    # Prefer the dense-side record (it comes directly from the cached
    # KB), then fill in any BM25-only ids using their BM25 record.
    candidates_by_id: Dict[str, Dict[str, Any]] = {}
    for hit in dense_hits:
        cid = _concern_id(hit)
        if cid is None:
            continue
        candidates_by_id.setdefault(cid, dict(hit))
    for cid, hit in bm25_records_by_id.items():
        if cid not in candidates_by_id:
            candidates_by_id[cid] = dict(hit)

    # ---- 5. Gate filter -------------------------------------------------
    if gate:
        gated: Dict[str, Dict[str, Any]] = {}
        for cid, c in candidates_by_id.items():
            gates = c.get("mlgg_gates") or []
            if isinstance(gates, list) and gate in gates:
                gated[cid] = c
        candidates_by_id = gated

    if not candidates_by_id:
        return []

    candidate_list = list(candidates_by_id.values())

    # ---- 6. Tag-overlap (canonical pattern) bonus -----------------------
    tag_overlap_by_id = _tag_overlap_scores(candidate_list)

    # ---- 7. Combine -----------------------------------------------------
    ranked: List[Dict[str, Any]] = []
    for c in candidate_list:
        cid = _concern_id(c)
        if cid is None:
            continue

        d = dense_score_by_id.get(cid, 0.0)
        b = bm25_score_by_id.get(cid, 0.0)
        t = tag_overlap_by_id.get(cid, 0.0)
        s = _severity_boost(c)

        final = (
            config.WEIGHT_DENSE * d
            + config.WEIGHT_BM25 * b
            + config.WEIGHT_TAG_OVERLAP * t
            + config.WEIGHT_SEVERITY * s
        )

        reasons: List[str] = []
        if cid in dense_rank_by_id:
            reasons.append(
                f"dense top-{dense_rank_by_id[cid] + 1} score={d:.2f}"
            )
        if cid in bm25_score_by_id:
            mode = c.get("_retrieval_mode", "BM25 match")
            reasons.append(
                f"BM25 match ({mode}) score={b:.2f}"
            )
        if gate:
            reasons.append(f"gate match: {gate}")
        cp = c.get("canonical_pattern_id")
        if isinstance(cp, str) and cp and t > 0:
            reasons.append(f"canonical pattern {cp} ({t:.2f})")
        sev = c.get("severity")
        if isinstance(sev, str) and s > 0:
            reasons.append(f"severity {sev} (+{s * config.WEIGHT_SEVERITY:.3f})")

        out = dict(c)
        out["_dense_score"] = d
        out["_bm25_score"] = b
        out["_tag_overlap_score"] = t
        out["_severity_boost"] = s
        out["_final_score"] = final
        out["_match_reasons"] = reasons
        ranked.append(out)

    # Stable sort: primary by final score desc; tiebreak by severity then id
    # for deterministic output across runs.
    def _sort_key(rec: Dict[str, Any]) -> Tuple[float, float, str]:
        sev_rank = -_severity_boost(rec)  # higher severity sorts earlier
        cid = _concern_id(rec) or ""
        return (-rec["_final_score"], sev_rank, cid)

    ranked.sort(key=_sort_key)
    return ranked[: max(0, int(top_k))]


__all__ = ["hybrid_rank"]
