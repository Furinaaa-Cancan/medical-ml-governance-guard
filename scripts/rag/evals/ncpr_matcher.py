"""NCPR v1 semantic + exact matcher.

Reference implementation of the algorithm pre-registered in
``references/benchmark/ncpr_v1_matcher_spec.md`` (W22-T4). Maps MLGG
flags to reviewer concerns using a ranked precedence of match types so
NCPR precision / recall numbers can be reproduced bit-for-bit by any
third party from the same inputs.

Ranked match types (highest precision first):

    1. ``exact_code``   — flag.code == g for some g in concern.mlgg_gates
    2. ``code_prefix``  — some g in concern.mlgg_gates is a prefix of flag.code
                          (or equals it after stripping the trailing ``_gate``)
    3. ``semantic``     — cosine sim of BGE-small embeddings >= 0.70
    4. ``category``     — flag.category == concern.category (weakest;
                          diagnostic only, not counted toward P/R per spec)
    5. ``none``         — no rule fires

Threshold (0.70) is HARD-CODED per the pre-registration rule in §4 of the
spec — refusing to read it from config in v1 mode prevents post-hoc
tuning that would invalidate the benchmark.

Design choice: flag-to-1-concern (not flag-to-many)
---------------------------------------------------
Each MLGG flag is assigned at most one concern (the best-scoring match
under the precedence rules above). Justification:

- Aligns with the spec's de-duplication intent (§5): a verbose gate
  emitting near-identical flags must not inflate recall.
- Symmetric with concern-side de-dup: ``matched_concerns`` and
  ``matched_flags`` are both cardinalities of distinct ids, so allowing
  a single flag to claim multiple concerns would silently inflate the
  ``matched_concerns`` numerator whenever one broad flag happens to be
  semantically close to two reviewer comments.
- Conservative: precision/recall reported externally will be a lower
  bound on what a more permissive matcher could yield, which is the
  right bias for a pre-registered external benchmark.

A future ``ncpr_v2`` may relax this to flag-to-many once we have a
calibration set; doing it in v1 would be post-hoc tuning.
"""
from __future__ import annotations

import re
from typing import Callable, Literal, Optional, TypedDict

import numpy as np

__all__ = [
    "MlggFlag",
    "ReviewerConcern",
    "MatchType",
    "SEMANTIC_THRESHOLD",
    "match_flag_to_concern",
    "match_all",
]


# Pre-registered, frozen. Do NOT read from config in v1 mode.
SEMANTIC_THRESHOLD: float = 0.70

MatchType = Literal["exact_code", "code_prefix", "semantic", "category", "none"]

# Precedence ordering — index = priority (lower wins). Used for tie-break
# when comparing match types between candidate concerns for the same flag.
_TYPE_PRIORITY: dict[str, int] = {
    "exact_code": 0,
    "code_prefix": 1,
    "semantic": 2,
    "category": 3,
    "none": 4,
}


class MlggFlag(TypedDict):
    code: str            # e.g. "clinical_metrics_ppv_too_low"
    severity: str        # "CRITICAL" | "HIGH" | "MEDIUM" | "LOW"
    category: str        # "evaluation" | "design" | ...
    evidence_text: str   # free text span from MLGG output


class ReviewerConcern(TypedDict):
    concern_id: str
    concern_text: str
    severity: str
    category: str
    mlgg_gates: list[str]  # gate names the reviewer pre-tagged (may be empty)


# ────────────────────────────────────────────────────────────────────────
# Normalization helpers
# ────────────────────────────────────────────────────────────────────────


def _norm_code(code: str) -> str:
    """ASCII lowercase + strip. Codes are already underscore-separated."""
    return (code or "").strip().lower()


def _strip_gate_suffix(code: str) -> str:
    """Strip a single trailing ``_gate`` suffix if present (spec §3.2)."""
    code = _norm_code(code)
    if code.endswith("_gate"):
        return code[: -len("_gate")]
    return code


_WS = re.compile(r"\s+")


def _norm_text(text: str) -> str:
    """Lowercase, strip, collapse internal whitespace (spec §3.3, §6)."""
    if not text:
        return ""
    return _WS.sub(" ", text.strip().lower())


def _cosine(u: np.ndarray, v: np.ndarray) -> float:
    """Cosine similarity computed via dot / norms.

    Uses ``np.linalg.norm`` + ``np.dot`` directly to avoid pulling in
    sklearn (per task rules).
    """
    u = np.asarray(u, dtype=float).ravel()
    v = np.asarray(v, dtype=float).ravel()
    nu = float(np.linalg.norm(u))
    nv = float(np.linalg.norm(v))
    if nu == 0.0 or nv == 0.0:
        return 0.0
    return float(np.dot(u, v) / (nu * nv))


# ────────────────────────────────────────────────────────────────────────
# Single-pair matcher
# ────────────────────────────────────────────────────────────────────────


def match_flag_to_concern(
    flag: MlggFlag,
    concern: ReviewerConcern,
    embed_fn: Optional[Callable[[str], np.ndarray]] = None,
) -> tuple[MatchType, float]:
    """Return ``(match_type, confidence)`` for a single flag-concern pair.

    Tries match types in precedence order and returns the *first* one
    that fires. Confidence is:

    - ``1.0`` for ``exact_code`` and ``code_prefix``
    - cosine similarity ``[0, 1]`` for ``semantic``
    - ``0.5`` for ``category`` (diagnostic-only, weak signal)
    - ``0.0`` for ``none``

    If ``embed_fn is None`` the semantic step is *skipped* (returns to
    the next-lower-precedence type). This keeps unit tests offline and
    deterministic without a real embedding service. The spec (§6)
    requires fail-loud on embedding-service errors in production, but
    that is the *caller*'s responsibility — passing ``embed_fn=None``
    is an explicit opt-out, not a silent failure.
    """
    flag_code = _norm_code(flag.get("code", ""))
    gates = [_norm_code(g) for g in (concern.get("mlgg_gates") or []) if g]

    # 1. Exact code match
    for g in gates:
        if flag_code and flag_code == g:
            return ("exact_code", 1.0)

    # 2. Code-prefix match. The reviewer's gate hint is the *registry*
    #    name (e.g. ``clinical_metrics_gate``); the flag code is a more
    #    specific sub-code (e.g. ``clinical_metrics_ppv_too_low``).
    #    Strip a trailing ``_gate`` from the hint, then check whether
    #    the flag code equals it or starts with ``hint + "_"``.
    if flag_code:
        for g in gates:
            base = _strip_gate_suffix(g)
            if not base:
                continue
            if flag_code == base or flag_code.startswith(base + "_"):
                return ("code_prefix", 1.0)

    # 3. Semantic match
    flag_text = _norm_text(flag.get("evidence_text", ""))
    concern_text = _norm_text(concern.get("concern_text", ""))
    if embed_fn is not None and flag_text and concern_text:
        u = embed_fn(flag_text)
        v = embed_fn(concern_text)
        sim = _cosine(u, v)
        if sim >= SEMANTIC_THRESHOLD:
            return ("semantic", sim)

    # 4. Category fallback (diagnostic; weak)
    flag_cat = (flag.get("category") or "").strip().lower()
    concern_cat = (concern.get("category") or "").strip().lower()
    if flag_cat and concern_cat and flag_cat == concern_cat:
        return ("category", 0.5)

    return ("none", 0.0)


# ────────────────────────────────────────────────────────────────────────
# Bulk matcher
# ────────────────────────────────────────────────────────────────────────


def _better(
    cand: tuple[MatchType, float], best: tuple[MatchType, float]
) -> bool:
    """True iff ``cand`` is a strictly better match than ``best``.

    Better = higher-precedence type, with score as tie-breaker within
    the same type.
    """
    cp = _TYPE_PRIORITY[cand[0]]
    bp = _TYPE_PRIORITY[best[0]]
    if cp < bp:
        return True
    if cp > bp:
        return False
    return cand[1] > best[1]


def match_all(
    flags: list[MlggFlag],
    concerns: list[ReviewerConcern],
    embed_fn: Optional[Callable[[str], np.ndarray]] = None,
) -> dict:
    """Match every flag against every concern, then de-duplicate.

    Returns::

        {
            "matched_pairs":     [{"flag_idx": i, "concern_idx": j,
                                   "type": t, "score": s}, ...],
            "unmatched_flags":   [i, ...],   # MLGG false positives
            "unmatched_concerns":[j, ...],   # MLGG false negatives
        }

    De-duplication strategy (see module docstring):
    - Each flag is assigned at most one concern (its best match).
    - Each concern is assigned at most one flag (the best flag that
      picked it). Other flags that picked the same concern are dropped
      to ``unmatched_flags`` to avoid inflating recall.

    Category matches *are* returned in ``matched_pairs`` (callers that
    compute strict P/R should filter them out; the diagnostic
    ``category_coverage`` metric uses them per spec §3.4).
    """
    # Step 1: each flag picks its single best concern.
    best_for_flag: dict[int, tuple[int, MatchType, float]] = {}
    for i, flag in enumerate(flags):
        best: tuple[MatchType, float] = ("none", 0.0)
        best_j: Optional[int] = None
        for j, concern in enumerate(concerns):
            cand = match_flag_to_concern(flag, concern, embed_fn=embed_fn)
            if cand[0] == "none":
                continue
            if best_j is None or _better(cand, best):
                best = cand
                best_j = j
        if best_j is not None:
            best_for_flag[i] = (best_j, best[0], best[1])

    # Step 2: resolve concern-side conflicts — each concern keeps only
    # the best flag that chose it.
    chosen_per_concern: dict[int, tuple[int, MatchType, float]] = {}
    for i, (j, t, s) in best_for_flag.items():
        existing = chosen_per_concern.get(j)
        if existing is None or _better((t, s), (existing[1], existing[2])):
            chosen_per_concern[j] = (i, t, s)

    winning_flag_ids = {i for (i, _t, _s) in chosen_per_concern.values()}

    matched_pairs = [
        {"flag_idx": i, "concern_idx": j, "type": t, "score": s}
        for j, (i, t, s) in sorted(chosen_per_concern.items())
    ]
    unmatched_flags = [i for i in range(len(flags)) if i not in winning_flag_ids]
    unmatched_concerns = [
        j for j in range(len(concerns)) if j not in chosen_per_concern
    ]

    return {
        "matched_pairs": matched_pairs,
        "unmatched_flags": unmatched_flags,
        "unmatched_concerns": unmatched_concerns,
    }
