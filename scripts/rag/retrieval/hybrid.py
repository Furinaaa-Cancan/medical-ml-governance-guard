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
          + WEIGHT_SEVERITY_EFF * severity_boost

Signals:
    * **Dense**: cosine similarity from ``retrieval.dense.vector_search``
      over the cached sentence-transformer embeddings produced by
      ``index.builder.build_or_load_index``.
    * **BM25**: keyword-overlap ranking from
      ``scripts.rag.retrieval.bm25.retrieve_for_failure``. Only
      consulted when both ``gate`` and ``failure_codes`` are supplied.
    * **Tag overlap (canonical-pattern boost)**: candidates sharing
      ``canonical_pattern_id`` *and* >=``config.TAG_OVERLAP_MIN_SHARED``
      tags (default 1, per W7-P0 fix from W6-W2 finding) with another
      candidate get a small bonus, since corroborating reviewer concerns
      across papers strengthen confidence in the pattern.
    * **Severity**: small additive bump so a CRITICAL concern wins a tie
      against a topically equivalent LOW concern.

Adaptive behaviour (5-agent ranker eval, 2026-05-16):

    * **Free-text re-normalization** — when BM25 does not fire (no
      ``gate`` + ``failure_codes``), the remaining active weights
      (``WEIGHT_DENSE + WEIGHT_TAG_OVERLAP + WEIGHT_SEVERITY = 0.55``;
      see ``config.py``) are scaled to sum to ``1.0``. With the current
      post-W13 weights (``WEIGHT_DENSE=0.10``, ``WEIGHT_TAG_OVERLAP=0.30``,
      ``WEIGHT_SEVERITY=0.15``) the effective free-text weights become
      ``dense=0.10/0.55≈0.182``, ``tag=0.30/0.55≈0.545``,
      ``sev=0.15/0.55≈0.273``. Without this rescale, free-text
      ``_final_score`` is capped at ``WEIGHT_BM25``-below-1.0 even on
      perfect matches.
      Every result is marked with
      ``_match_reasons += ["bm25_inactive_free_text"]``.
    * **CP/tag bonus gating** — the canonical-pattern tag-overlap bonus
      is skipped entirely when the top-1 dense candidate scores below
      ``config.CP_TAG_BOOST_DENSE_FLOOR`` (0.70). On thin topics, weak
      dense signal cannot trust pattern corroboration: a +0.09 tag
      bonus would otherwise flip same-pattern siblings past a better
      off-pattern hit.
    * **Severity scaling by dense spread** — the severity additive
      bonus is multiplied by ``min(1, dense_spread / SEVERITY_FULL_SPREAD)``
      where ``dense_spread = max(dense) - min(dense)``. Tight pools
      (spread < 0.20) get a fractional severity weight; wide pools get
      the full ``WEIGHT_SEVERITY``. Prevents off-topic CRITICALs from
      leapfrogging on-topic HIGHs on uniformly weak dense pools.
    * **top_k uncap** — ``dense_top_k = max(DEFAULT_MAX_CANDIDATES_BEFORE_RERANK,
      top_k)``. Callers requesting ``top_k=200`` no longer silently
      receive 50 results.

The module is read-only with respect to the KB. Filesystem side effects
(embedding cache writes) are owned by ``index.builder``.

See ``/tmp/mlgg_rag_design.md`` for the full design contract.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


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
    ``canonical_pattern_id`` shares at least ``config.TAG_OVERLAP_MIN_SHARED``
    tags with it. This rewards corroborating evidence across reviewer
    concerns within a canonical pattern without amplifying near-duplicate
    concerns from the same paper.

    The score is scaled by the count of qualifying partners, capped
    so the boost stays bounded: ``score = min(1.0, 0.3 * partners)``.

    Args:
        candidates: Concern records (post-union, pre-rerank).

    Returns:
        Mapping ``concern_id -> overlap_score``.
    """

    out: Dict[str, float] = {}
    min_shared = max(1, int(config.TAG_OVERLAP_MIN_SHARED))
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
                if len(tags_i & tags_j) >= min_shared:
                    partners += 1
            if partners > 0:
                out[cid_i] = min(1.0, 0.3 * partners)

    return out


def _dense_corroboration_scores(
    candidates: List[Dict[str, Any]],
    *,
    top_k: Optional[int] = None,
) -> Dict[str, float]:
    """Within-CP dense-cosine corroboration score on ``[0, 1]``.

    For each candidate, compute the **average cosine similarity to the
    top-K most-similar OTHER candidates from the same ``canonical_pattern_id``**.
    This rewards "the KB has multiple concerns in this same CP that are
    densely similar to the query result", which is the actual signal
    ``_tag_overlap_scores`` tried (and largely failed) to capture: 89.5% of
    KB tags are singletons (W7-P6), so tag-set intersection is sparse, but
    embeddings of same-CP siblings reliably cluster.

    The score is the **mean** cosine to the top-``top_k`` same-CP siblings
    (or fewer if the CP has <``top_k`` siblings), already in ``[0, 1]``
    since the source embeddings are L2-normalized. Candidates without an
    embedding, without a CP, or in a singleton CP cluster get 0.0.

    Args:
        candidates: Concern records (post-union, pre-rerank). Each may
            carry an ``_dense_embedding`` (L2-normalized numpy array) from
            ``retrieval.dense.vector_search``. Records without an embedding
            (e.g. BM25-only hits) are skipped in the cosine math but their
            presence in the CP group is still counted toward other members.
        top_k: How many same-CP siblings to average over. ``None`` ->
            ``config.DENSE_CORROBORATION_TOP_K``.

    Returns:
        Mapping ``concern_id -> corroboration_score`` in ``[0, 1]``.
    """
    import numpy as np

    if top_k is None:
        top_k = config.DENSE_CORROBORATION_TOP_K
    top_k = max(1, int(top_k))

    out: Dict[str, float] = {}
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for c in candidates:
        cp = c.get("canonical_pattern_id")
        if not isinstance(cp, str) or not cp:
            continue
        groups.setdefault(cp, []).append(c)

    for cp, members in groups.items():
        if len(members) < 2:
            continue
        # Pre-extract embeddings + ids to avoid repeated dict lookups.
        ids: List[Optional[str]] = []
        embs: List[Optional[Any]] = []
        for m in members:
            ids.append(_concern_id(m))
            emb = m.get("_dense_embedding")
            embs.append(emb if emb is not None else None)

        for i, cid_i in enumerate(ids):
            if cid_i is None or embs[i] is None:
                continue
            # Cosine to every OTHER same-CP member that has an embedding.
            sims: List[float] = []
            for j, emb_j in enumerate(embs):
                if i == j or emb_j is None:
                    continue
                sims.append(float(np.dot(embs[i], emb_j)))
            if not sims:
                continue
            # Average over the top-K most-similar siblings only. Clamp
            # negatives to 0 so an antipodal sibling can't drag the score
            # below 0 (in practice BGE-small cosines are >= 0).
            sims.sort(reverse=True)
            top = sims[:top_k]
            mean = sum(max(0.0, s) for s in top) / len(top)
            # Already in [0, 1] for normalized embeddings; clamp defensively.
            out[cid_i] = float(min(1.0, max(0.0, mean)))

    return out


def _mmr_rerank(
    candidates: List[Dict[str, Any]],
    *,
    top_k: int,
    lam: Optional[float] = None,
    same_paper_penalty: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Re-rank candidates using Maximal Marginal Relevance (v2).

    Preserves the top-1 candidate (highest relevance always wins first slot).
    Subsequent picks balance relevance with diversity from already-picked.

    Per-pair similarity is the **maximum** of:
      - Embedding cosine similarity: dot product of the L2-normalized
        ``_dense_embedding`` vectors when both candidates carry one.
        Suppresses cross-paper near-duplicates that v1 (paper_id only)
        could not catch.
      - Same-paper penalty (``same_paper_penalty``): applied whenever
        ``paper_id`` matches between two candidates. Still catches the
        BM25-only fallback path where embeddings are absent.

    Output strips the internal ``_dense_embedding`` field so callers do
    not receive 384-dim numpy arrays in their result dicts.

    Args:
        candidates: List sorted by _final_score desc.
        top_k: How many to return.
        lam: Relevance vs diversity weight in [0, 1]. None → config.MMR_LAMBDA.
        same_paper_penalty: Similarity boost for same-paper pairs in [0, 1].
            None → config.MMR_SAME_PAPER_PENALTY.

    Returns:
        Re-ranked list of length min(top_k, len(candidates)). Each picked
        dict gains:
          * ``_mmr_score`` (float): the MMR objective value used at pick time.
          * ``_mmr_breakdown`` (dict, W9-B2 / W5 deep audit signal): records
            ``{"relevance", "max_sim", "blocker_id", "blocker_reason"}``
            where ``blocker_id`` names the *already-selected* candidate that
            contributed ``max_sim`` (i.e. the diversity penalty source), and
            ``blocker_reason`` is one of ``"cosine"`` (embedding near-dup),
            ``"same_paper"`` (paper_id penalty), or ``"none"`` (no
            diversity penalty applied — typically the top-1 pick).
        ``_dense_embedding`` is removed before return.
    """
    import numpy as np

    if lam is None:
        lam = config.MMR_LAMBDA
    if same_paper_penalty is None:
        same_paper_penalty = config.MMR_SAME_PAPER_PENALTY

    if not candidates or top_k <= 0:
        return []
    if len(candidates) == 1 or lam >= 1.0:
        # passthrough: pure relevance — still strip embedding before return.
        # W11-F3: also attach the _mmr_score / _mmr_breakdown schema fields
        # so downstream consumers (audit, eval, ranking diff) can rely on a
        # uniform contract regardless of which branch produced the list.
        # No MMR re-weighting happens here, so _mmr_score == _final_score
        # and the breakdown records zero diversity penalty.
        passthrough = [dict(c) for c in candidates[:top_k]]
        for r in passthrough:
            r.pop("_dense_embedding", None)
            relevance = float(r.get("_final_score", 0.0))
            r["_mmr_score"] = relevance
            r["_mmr_breakdown"] = {
                "relevance": relevance,
                "max_sim": 0.0,
                "blocker_id": None,
                "blocker_reason": "none",
            }
        return passthrough

    selected = [dict(candidates[0])]  # always take top-1
    # W8-W5: store the MMR objective consistently across all ranks so
    # provenance is auditable. For top-1 the max similarity to already-
    # selected is 0 (nothing selected yet), so the formula
    #   _mmr_score = lam * relevance - (1 - lam) * max_sim
    # collapses to lam * relevance. Subsequent picks (below) store the
    # same expression evaluated against the running ``selected`` set.
    top1_relevance = float(selected[0].get("_final_score", 0.0))
    selected[0]["_mmr_score"] = float(lam * top1_relevance)
    # W9-B2: surface the per-pick MMR decision in a structured form so
    # downstream audit can answer "why did B place where it did?". For the
    # top-1 there is no blocker (nothing selected yet); the dict still
    # records relevance + zero max_sim for uniform schema.
    selected[0]["_mmr_breakdown"] = {
        "relevance": top1_relevance,
        "max_sim": 0.0,
        "blocker_id": None,
        "blocker_reason": "none",
    }
    remaining = list(candidates[1:])

    while remaining and len(selected) < top_k:
        best_score = -float("inf")
        best_idx = 0
        # Track the winning candidate's MMR breakdown so we can attach it
        # to ``chosen`` below. Recomputing in a second pass would diverge
        # from the actual decision if the iteration ever became
        # non-deterministic.
        best_breakdown: Dict[str, Any] = {
            "relevance": 0.0,
            "max_sim": 0.0,
            "blocker_id": None,
            "blocker_reason": "none",
        }
        for i, cand in enumerate(remaining):
            relevance = cand.get("_final_score", 0.0)
            max_sim = 0.0
            blocker_id: Optional[str] = None
            blocker_reason = "none"
            cand_emb = cand.get("_dense_embedding")
            # W20-F1 / W18-D3: BM25 enrichment writes ``_paper_id`` (see
            # scripts/rag/retrieval/bm25.py:_enrich_concern), while
            # ``index.builder`` and synthetic test fixtures supply
            # ``paper_id``. Read both so the same-paper penalty actually
            # fires in gate-anchored retrieval instead of silently
            # no-op'ing on every gate hit (W18-D3: 10/10 sample queries
            # had blocker_reason same_paper=0).
            cand_pid = cand.get("paper_id") or cand.get("_paper_id")
            for sel_idx, sel in enumerate(selected):
                # Same-paper penalty (always applied; catches BM25-only
                # candidates that lack an embedding).
                sel_pid = sel.get("paper_id") or sel.get("_paper_id")
                if cand_pid and cand_pid == sel_pid:
                    if same_paper_penalty > max_sim:
                        max_sim = same_paper_penalty
                        # W11-F3: maintain the invariant that whenever
                        # blocker_reason != "none", blocker_id is a
                        # non-empty string. Fall back to a positional
                        # surrogate when _concern_id returns None so
                        # downstream audits never see a null/empty id
                        # paired with a real reason.
                        blocker_id = (
                            _concern_id(sel)
                            or f"<unidentified_record_{sel_idx}>"
                        )
                        blocker_reason = "same_paper"
                # Embedding cosine similarity (preferred when both sides
                # have an L2-normalized vector; dot product == cosine).
                sel_emb = sel.get("_dense_embedding")
                if cand_emb is not None and sel_emb is not None:
                    cos = float(np.dot(cand_emb, sel_emb))
                    # Only treat near-duplicates as "similar enough to
                    # penalize" (W2 fix for Q9 free-text regression).
                    # Below the floor, two concerns are considered
                    # distinct and no diversity penalty applies.
                    if cos >= config.MMR_COSINE_FLOOR and cos > max_sim:
                        max_sim = cos
                        blocker_id = (
                            _concern_id(sel)
                            or f"<unidentified_record_{sel_idx}>"
                        )
                        blocker_reason = "cosine"
            mmr_score = lam * relevance - (1.0 - lam) * max_sim
            if mmr_score > best_score:
                best_score = mmr_score
                best_idx = i
                best_breakdown = {
                    "relevance": float(relevance),
                    "max_sim": float(max_sim),
                    "blocker_id": blocker_id,
                    "blocker_reason": blocker_reason,
                }
        chosen = dict(remaining.pop(best_idx))
        chosen["_mmr_score"] = float(best_score)
        chosen["_mmr_breakdown"] = best_breakdown
        selected.append(chosen)

    # Strip the internal embedding field so user-facing callers don't get
    # 384-dim numpy arrays in their result dicts.
    for r in selected:
        r.pop("_dense_embedding", None)

    return selected


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _normalize_excluded(excluded_paper_ids: Optional[Iterable[str]]) -> frozenset:
    """Normalize an exclusion set to a frozenset of non-empty ``str`` paper ids.

    Accepts a single id, any iterable of ids, or ``None``. ``None`` / empty →
    empty frozenset (no exclusion). Mirrors ``index.builder._normalize_excluded``
    so the runtime filter and the build-time filter agree on what an exclusion
    set means.
    """
    if not excluded_paper_ids:
        return frozenset()
    if isinstance(excluded_paper_ids, str):
        excluded_paper_ids = [excluded_paper_ids]
    return frozenset(
        str(p).strip() for p in excluded_paper_ids if p is not None and str(p).strip()
    )


def _candidate_paper_id(candidate: Dict[str, Any]) -> str:
    """Return a candidate's paper id, tolerating both producers' field names.

    The dense index builder injects ``paper_id`` (``index.builder``); the BM25
    enricher injects ``_paper_id`` (``retrieval.bm25``). A post-union candidate
    may come from either path, so BOTH must be checked — otherwise BM25-only
    hits slip past the exclusion filter (the dense field alone misses them).
    """
    return str(candidate.get("paper_id") or candidate.get("_paper_id") or "")


def _drop_excluded_papers(
    candidates: Dict[str, Dict[str, Any]],
    excluded: frozenset,
) -> Dict[str, Dict[str, Any]]:
    """Drop candidates whose paper id is in ``excluded`` (leave-one-paper-out).

    Applied post-union so it covers BOTH the dense and the BM25 retrieval paths
    at a single chokepoint: build-time dense exclusion (``index.builder``) cannot
    reach the BM25 hits that ``hybrid_rank`` unions in afterwards, so this runtime
    filter is what actually guarantees a paper never retrieves its own reviewer
    concerns (the self-leak that would inflate any leave-one-paper-out eval).
    """
    if not excluded:
        return candidates
    return {
        cid: c
        for cid, c in candidates.items()
        if _candidate_paper_id(c) not in excluded
    }


def hybrid_rank(
    query: str,
    gate: Optional[str] = None,
    failure_codes: Optional[List[str]] = None,
    top_k: int = config.DEFAULT_TOP_K,
    excluded_paper_ids: Optional[Iterable[str]] = None,
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
        excluded_paper_ids: Optional paper ids to exclude from the results
            (leave-one-paper-out). Any candidate whose ``paper_id`` is in this
            set is dropped post-union — covering both the dense and BM25 paths —
            so a paper can never retrieve its own reviewer concerns. ``None``
            (default) disables exclusion.

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
    # Fix 4: grow the candidate pool with the caller's request so a
    # ``top_k=200`` query is not silently capped at 50.
    requested_top_k = max(0, int(top_k))
    dense_top_k = max(
        config.DEFAULT_MAX_CANDIDATES_BEFORE_RERANK, requested_top_k
    )
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

    # ---- 4b. Leave-one-paper-out exclusion (self-retrieval guard) -------
    # Drop candidates from excluded papers BEFORE any scoring/rerank so they
    # can never occupy a result slot. Done post-union so it covers the BM25
    # hits too (build-time dense exclusion in index.builder cannot).
    excluded = _normalize_excluded(excluded_paper_ids)
    if excluded:
        candidates_by_id = _drop_excluded_papers(candidates_by_id, excluded)

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

    # ---- 6. CP corroboration bonus --------------------------------------
    # W9-B2: replace the tag-overlap signal with a within-CP dense-cosine
    # corroboration signal when ``USE_DENSE_CORROBORATION`` is enabled.
    # Rationale: 89.5% of KB tags are singletons (W7-P6), so tag-set
    # intersection misses the canonical reuse pattern even with
    # ``TAG_OVERLAP_MIN_SHARED=1``; embeddings of same-CP siblings, by
    # contrast, reliably cluster. The new signal also degrades gracefully
    # for BM25-only candidates (it skips them) and for singleton CP groups
    # (it returns 0.0). The kept-name ``_tag_overlap_score`` keeps
    # downstream readers / audit consumers stable. Flip the config flag
    # to ``False`` to A/B against the legacy tag-overlap path.
    corroboration_signal: str
    if config.USE_DENSE_CORROBORATION:
        tag_overlap_by_id = _dense_corroboration_scores(candidate_list)
        corroboration_signal = "dense_corroboration"
    else:
        tag_overlap_by_id = _tag_overlap_scores(candidate_list)
        corroboration_signal = "tag_overlap"

    # ---- 7. Adaptive weight setup ---------------------------------------
    # Fix 1 — BM25 inactive in free-text path. When BM25 did not fire
    # (no gate / no failure_codes), the nominal ``config.WEIGHT_BM25``
    # (0.45 since W13-P0) is dead weight: every BM25 contribution is 0
    # and the maximum attainable ``_final_score`` collapses from 1.0 to
    # the sum of the active weights (0.55). Re-normalize
    # the *active* weights to sum to 1.0 so a perfect dense match still
    # tops out near 1.0 in free-text mode. Gate-anchored mode is
    # unchanged (BM25 contributes; full weight applies).
    bm25_active = bool(gate and failure_codes)
    if bm25_active:
        weight_dense_eff = config.WEIGHT_DENSE
        weight_bm25_eff = config.WEIGHT_BM25
        weight_tag_eff = config.WEIGHT_TAG_OVERLAP
        weight_sev_nominal = config.WEIGHT_SEVERITY
    else:
        active_sum = (
            config.WEIGHT_DENSE
            + config.WEIGHT_TAG_OVERLAP
            + config.WEIGHT_SEVERITY
        )
        # active_sum is 0.7 with default config; guard against future
        # reconfig that zeros it.
        if active_sum <= 0.0:
            weight_dense_eff = config.WEIGHT_DENSE
            weight_bm25_eff = 0.0
            weight_tag_eff = config.WEIGHT_TAG_OVERLAP
            weight_sev_nominal = config.WEIGHT_SEVERITY
        else:
            weight_dense_eff = config.WEIGHT_DENSE / active_sum
            weight_bm25_eff = 0.0
            weight_tag_eff = config.WEIGHT_TAG_OVERLAP / active_sum
            weight_sev_nominal = config.WEIGHT_SEVERITY / active_sum

    # Fix 2 — Gate the CP / tag-overlap bonus on a top-1 dense floor. On
    # thin topics the strongest dense candidate is itself weak; a
    # +0.09 tag bonus then flips same-pattern siblings past a better
    # off-pattern match. ``CP_TAG_BOOST_DENSE_FLOOR`` (0.70) keeps the
    # bonus active only when the dense signal is strong enough to trust
    # corroboration.
    top1_dense = max(dense_score_by_id.values(), default=0.0)
    apply_tag_boost = top1_dense >= config.CP_TAG_BOOST_DENSE_FLOOR

    # Fix 3 — Scale the severity bonus by the dense spread within the
    # candidate pool. Tight pools (spread < SEVERITY_FULL_SPREAD) shrink
    # the severity weight linearly so off-topic CRITICALs cannot
    # leapfrog on-topic HIGHs when every dense score is clustered.
    if dense_score_by_id:
        dense_pool = list(dense_score_by_id.values())
        dense_spread = max(dense_pool) - min(dense_pool)
    else:
        dense_spread = 0.0
    if config.SEVERITY_FULL_SPREAD > 0.0:
        severity_scale = min(
            1.0, dense_spread / config.SEVERITY_FULL_SPREAD
        )
    else:
        severity_scale = 1.0
    weight_sev_eff = weight_sev_nominal * severity_scale

    # ---- 8. Combine -----------------------------------------------------
    ranked: List[Dict[str, Any]] = []
    for c in candidate_list:
        cid = _concern_id(c)
        if cid is None:
            continue

        d = dense_score_by_id.get(cid, 0.0)
        b = bm25_score_by_id.get(cid, 0.0)
        t_raw = tag_overlap_by_id.get(cid, 0.0)
        t = t_raw if apply_tag_boost else 0.0
        s = _severity_boost(c)

        final = (
            weight_dense_eff * d
            + weight_bm25_eff * b
            + weight_tag_eff * t
            + weight_sev_eff * s
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
        if not bm25_active:
            reasons.append("bm25_inactive_free_text")
        if gate:
            reasons.append(f"gate match: {gate}")
        cp = c.get("canonical_pattern_id")
        if isinstance(cp, str) and cp and t > 0:
            reasons.append(
                f"canonical pattern {cp} ({corroboration_signal}={t:.2f})"
            )
        if (
            isinstance(cp, str)
            and cp
            and t_raw > 0
            and not apply_tag_boost
        ):
            reasons.append(
                f"cp_bonus_suppressed top1_dense={top1_dense:.2f}"
                f"<{config.CP_TAG_BOOST_DENSE_FLOOR:.2f}"
            )
        sev = c.get("severity")
        if isinstance(sev, str) and s > 0:
            reasons.append(
                f"severity {sev} (+{s * weight_sev_eff:.3f}"
                f"; scale={severity_scale:.2f})"
            )

        out = dict(c)
        out["_dense_score"] = d
        out["_bm25_score"] = b
        out["_tag_overlap_score"] = t
        out["_tag_overlap_raw"] = t_raw
        out["_severity_boost"] = s
        out["_severity_scale"] = severity_scale
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
    ranked = _mmr_rerank(ranked, top_k=requested_top_k)
    return ranked  # already truncated to top_k by MMR


__all__ = ["hybrid_rank"]
