#!/usr/bin/env python3
"""NCPR v1 — Severity-Weighted F1 Scoring (W22-X2).

Computes the headline NCPR v1 metric: a severity-weighted F1 over
reviewer concerns vs. MLGG flags. Consumes the deterministic match
output produced by W22-X1's ``ncpr_matcher.match_all`` and turns it
into wTP / wFN / wFP, per-paper precision/recall/F1, and a macro
average across papers.

This module IS NOT the matcher — it scores on top of matcher output.
Sibling W22-X1 owns ``scripts/rag/evals/ncpr_matcher.py``. We stub
the import with ``try/except ImportError`` so this module is testable
in isolation before the matcher lands.

Spec: ``references/benchmark/ncpr_v1_severity_rationale.md``.
Frozen for NCPR v1; any weight change requires a new ADR + v2 bump.
"""
from __future__ import annotations

import warnings
from typing import Any, Callable, Iterable, Literal, TypedDict

# ---------------------------------------------------------------------------
# Frozen weighting scheme (NCPR v1 — see severity rationale doc, table 2).
# Geometric progression with common ratio 2: one CRITICAL miss ~= two HIGH
# misses ~= four MEDIUM misses ~= eight LOW misses. Frozen for v1.
# ---------------------------------------------------------------------------
SEVERITY_WEIGHTS: dict[str, float] = {
    "CRITICAL": 4.0,
    "HIGH": 2.0,
    "MEDIUM": 1.0,
    "LOW": 0.5,
}

# Constant FP discount per spec section 4: over-flagging is half as costly
# as under-flagging at publication-grade review.
_FP_DISCOUNT: float = 0.5

SeverityLiteral = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


# ---------------------------------------------------------------------------
# Typed result shapes
# ---------------------------------------------------------------------------
class WeightedCounts(TypedDict):
    """Per-paper weighted confusion-matrix sums + derived rates."""

    wTP: float
    wFN: float
    wFP: float
    wPrecision: float
    wRecall: float
    weighted_f1: float


# ---------------------------------------------------------------------------
# Severity lookup
# ---------------------------------------------------------------------------
def severity_weight(sev: str) -> float:
    """Look up the weight for a severity label.

    Args:
        sev: Severity string. Case-insensitive; whitespace stripped.

    Returns:
        The frozen NCPR v1 weight for that severity.

    Raises:
        ValueError: if ``sev`` is None, empty, or not in
            ``SEVERITY_WEIGHTS``. We fail loud rather than silently
            scoring a 0 — an unknown severity in the reviewer KB is a
            label-quality bug and must surface immediately.
    """
    if sev is None:
        raise ValueError("severity is None (expected one of: "
                         f"{sorted(SEVERITY_WEIGHTS)})")
    if not isinstance(sev, str):
        raise ValueError(f"severity must be str, got {type(sev).__name__}: {sev!r}")
    key = sev.strip().upper()
    if not key:
        raise ValueError("severity is empty (expected one of: "
                         f"{sorted(SEVERITY_WEIGHTS)})")
    if key not in SEVERITY_WEIGHTS:
        raise ValueError(
            f"unknown severity {sev!r}; expected one of "
            f"{sorted(SEVERITY_WEIGHTS)}"
        )
    return SEVERITY_WEIGHTS[key]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _safe_div(num: float, denom: float) -> float:
    """Divide with a guard: 0/0 -> 0.0 rather than NaN.

    The severity rationale (section 4) defines wP := 1.0 when no flags
    exist, but for the headline F1 we use the conservative "no signal
    -> 0" convention so a system with zero flags does not score a
    free F1 = 1.0. Empty-paper aggregation is handled separately by
    ``macro_average`` (excluded per spec section 5).
    """
    if denom <= 0:
        return 0.0
    return num / denom


def _f1(precision: float, recall: float) -> float:
    """Harmonic mean with zero-protection (NaN-safe)."""
    if precision <= 0 or recall <= 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


# Matcher-output keys we know about. Real W22-X1 matcher uses
# ``matched_pairs`` with index fields; the lexical stub uses
# ``matches`` with id fields. We accept both.
_PAIR_KEYS = ("matched_pairs", "matches")

# Spec section 3.4: category matches are diagnostic-only and MUST NOT
# count toward precision/recall. Filter them out here.
_NON_COUNTING_TYPES = frozenset({"category", "none"})


def _extract_matched_idx_sets(
    match_result: dict,
    flags: list[dict],
    concerns: list[dict],
) -> tuple[set[int], set[int]]:
    """Pull matched flag-index / concern-index sets from matcher output.

    Handles both the W22-X1 reference shape (``matched_pairs`` with
    ``flag_idx`` / ``concern_idx`` / ``type``) and our lexical-stub
    shape (``matches`` with ``flag_id`` / ``concern_id`` / optional
    ``match_type``). Tuples are also accepted for forward compat.

    Filters out match types in ``_NON_COUNTING_TYPES`` per spec §3.4
    (category matches are diagnostic only, not counted toward P/R).

    Returns:
        (matched_flag_idx, matched_concern_idx).
    """
    # Build id -> idx lookups so we can normalize id-keyed outputs.
    flag_id_to_idx = {_flag_id(f, j): j for j, f in enumerate(flags)}
    concern_id_to_idx = {_concern_id(c, i): i for i, c in enumerate(concerns)}

    matched_flag_idx: set[int] = set()
    matched_concern_idx: set[int] = set()

    pairs: Iterable = []
    for key in _PAIR_KEYS:
        if key in match_result:
            pairs = match_result[key]
            break

    for p in pairs:
        if isinstance(p, dict):
            mtype = p.get("type") or p.get("match_type")
            if mtype in _NON_COUNTING_TYPES:
                continue
            # Prefer index keys (real matcher), fall back to id keys (stub).
            f_idx = p.get("flag_idx")
            c_idx = p.get("concern_idx")
            if f_idx is None:
                f_idx = flag_id_to_idx.get(p.get("flag_id"))
            if c_idx is None:
                c_idx = concern_id_to_idx.get(p.get("concern_id"))
        else:  # tuple / list — (flag_ref, concern_ref, [type, ...])
            try:
                f_ref, c_ref = p[0], p[1]
                mtype = p[2] if len(p) > 2 else None
            except (IndexError, TypeError):
                continue
            if mtype in _NON_COUNTING_TYPES:
                continue
            f_idx = f_ref if isinstance(f_ref, int) else flag_id_to_idx.get(f_ref)
            c_idx = c_ref if isinstance(c_ref, int) else concern_id_to_idx.get(c_ref)

        if f_idx is not None and 0 <= f_idx < len(flags):
            matched_flag_idx.add(f_idx)
        if c_idx is not None and 0 <= c_idx < len(concerns):
            matched_concern_idx.add(c_idx)

    return matched_flag_idx, matched_concern_idx


def _concern_id(concern: dict, idx: int) -> str:
    """Best-effort concern id (mirrors matcher convention)."""
    cid = concern.get("concern_id")
    return cid if cid is not None else f"_concern_{idx}"


def _flag_id(flag: dict, idx: int) -> str:
    """Best-effort flag id."""
    fid = flag.get("flag_id") or flag.get("id")
    return fid if fid is not None else f"_flag_{idx}"


# ---------------------------------------------------------------------------
# Core scorer
# ---------------------------------------------------------------------------
def weighted_tp_fn_fp(
    match_result: dict,
    flags: list[dict],
    concerns: list[dict],
) -> WeightedCounts:
    """Compute weighted TP / FN / FP and derived rates for one paper.

    Args:
        match_result: Output of W22-X1's ``match_all``. Expected key
            ``"matches"`` is an iterable of ``(flag_id, concern_id,
            match_type)`` tuples (or dicts with the same fields).
        flags: The original MLGG flag list passed to the matcher.
            Each flag is a dict with at least ``severity`` and an id
            (``flag_id`` or ``id``).
        concerns: The original reviewer concern list. Each concern is
            a dict with at least ``severity`` and ``concern_id``.

    Returns:
        ``WeightedCounts`` — wTP / wFN / wFP and the derived
        precision / recall / F1.

    Raises:
        ValueError: on unknown severity in any concern or any
            unmatched flag (the concern_id / flag_id is included in
            the message). Matched-flag severity is not used, so a
            matched flag with bad severity does not raise.
    """
    matched_flag_idx, matched_concern_idx = _extract_matched_idx_sets(
        match_result, flags, concerns
    )

    # wTP / wFN — reviewer side, reviewer severity (spec section 3).
    w_tp = 0.0
    w_fn = 0.0
    for i, concern in enumerate(concerns):
        cid = _concern_id(concern, i)
        sev = concern.get("severity")
        try:
            w = severity_weight(sev)
        except ValueError as e:
            raise ValueError(
                f"concern {cid!r}: {e}"
            ) from e
        if i in matched_concern_idx:
            w_tp += w
        else:
            w_fn += w

    # wFP — flag side, MLGG severity, halved (spec section 4).
    w_fp = 0.0
    for j, flag in enumerate(flags):
        fid = _flag_id(flag, j)
        if j in matched_flag_idx:
            continue
        sev = flag.get("severity")
        try:
            w = severity_weight(sev)
        except ValueError as e:
            raise ValueError(
                f"flag {fid!r}: {e}"
            ) from e
        w_fp += w * _FP_DISCOUNT

    w_p = _safe_div(w_tp, w_tp + w_fp)
    w_r = _safe_div(w_tp, w_tp + w_fn)
    f1 = _f1(w_p, w_r)

    return WeightedCounts(
        wTP=w_tp,
        wFN=w_fn,
        wFP=w_fp,
        wPrecision=w_p,
        wRecall=w_r,
        weighted_f1=f1,
    )


# ---------------------------------------------------------------------------
# Matcher stub (W22-X1 not yet landed)
# ---------------------------------------------------------------------------
def _stub_match_all(
    flags: list[dict],
    concerns: list[dict],
    embed_fn: Callable | None = None,
) -> dict:
    """Conservative offline matcher used when W22-X1 is unavailable.

    Implements only types 1 + 2 from the matcher spec (exact code
    match and code-prefix match) — both lexical, no embedder
    required. Type 3 (semantic) is skipped because we deliberately
    refuse to ship a second embedding path; scoring runs that exercise
    semantic matching MUST import the real matcher.

    This keeps tests deterministic and offline while still letting
    ``per_paper_score`` produce a sane end-to-end signal pre-X1.
    """
    matched_pairs: list[dict] = []
    claimed_concerns: set[int] = set()
    for j, flag in enumerate(flags):
        flag_code = (flag.get("code") or "").strip().lower()
        if not flag_code:
            continue
        for i, concern in enumerate(concerns):
            if i in claimed_concerns:
                continue
            gates = [
                (g or "").strip().lower()
                for g in concern.get("mlgg_gates") or []
            ]
            matched = False
            mtype = None
            for g in gates:
                if not g:
                    continue
                if flag_code == g:
                    matched, mtype = True, "exact_code"
                    break
                # strip trailing _gate per spec section 3.2 example
                g_norm = g[:-5] if g.endswith("_gate") else g
                if flag_code == g_norm or flag_code.startswith(g_norm + "_"):
                    matched, mtype = True, "code_prefix"
                    break
            if matched:
                matched_pairs.append(
                    {"flag_idx": j, "concern_idx": i, "type": mtype, "score": 1.0}
                )
                claimed_concerns.add(i)
                break  # one concern per flag at the stub level
    matched_flag_idx = {p["flag_idx"] for p in matched_pairs}
    matched_concern_idx = {p["concern_idx"] for p in matched_pairs}
    return {
        "matched_pairs": matched_pairs,
        "unmatched_flags": [j for j in range(len(flags)) if j not in matched_flag_idx],
        "unmatched_concerns": [
            i for i in range(len(concerns)) if i not in matched_concern_idx
        ],
        "matcher": "stub_lexical_only",
    }


def _get_matcher() -> Callable:
    """Return W22-X1's ``match_all`` if importable, else the stub."""
    try:
        from scripts.rag.evals.ncpr_matcher import match_all  # type: ignore
        return match_all
    except ImportError:
        try:
            from ncpr_matcher import match_all  # type: ignore  # noqa: F401
            return match_all
        except ImportError:
            return _stub_match_all


# ---------------------------------------------------------------------------
# End-to-end per-paper scorer
# ---------------------------------------------------------------------------
def per_paper_score(
    paper_id: str,
    flags: list[dict],
    concerns: list[dict],
    embed_fn: Callable | None = None,
) -> dict:
    """End-to-end scorer for one paper.

    Pipeline:
        1. Invoke W22-X1's matcher (or stub if not yet importable).
        2. Compute weighted TP / FN / FP and rates.
        3. Add per-severity breakdown of matched / missed concerns
           and extra flags for failure-mode analysis.
        4. Apply spec section 4 empty-paper convention: if a paper has
           zero reviewer concerns, ``weighted_f1`` is reported as 0.0
           with ``paper_excluded=True`` so ``macro_average`` can drop it.

    Args:
        paper_id: stable identifier for the paper.
        flags: MLGG flags for that paper.
        concerns: reviewer concerns for that paper.
        embed_fn: optional embedder injected into the matcher (only
            used if the real matcher accepts it; ignored by the stub).

    Returns:
        Dict with paper_id, totals (``WeightedCounts``), per-severity
        breakdown, matcher name, and the ``paper_excluded`` flag.
    """
    matcher = _get_matcher()
    # Real matcher signature includes embed_fn; stub accepts/ignores it.
    try:
        match_result = matcher(flags, concerns, embed_fn=embed_fn)
    except TypeError:
        # matcher does not accept the kwarg
        match_result = matcher(flags, concerns)

    counts = weighted_tp_fn_fp(match_result, flags, concerns)

    matched_flag_idx, matched_concern_idx = _extract_matched_idx_sets(
        match_result, flags, concerns
    )

    # Per-severity breakdown — useful for the failure-mode analysis
    # called out in spec section 6 (under-rated CRITICAL detection).
    by_sev: dict[str, dict[str, int]] = {
        sev: {"matched": 0, "missed": 0, "extra_flags": 0}
        for sev in SEVERITY_WEIGHTS
    }
    for i, concern in enumerate(concerns):
        key = (concern.get("severity") or "").strip().upper()
        if key not in by_sev:
            continue  # already raised in weighted_tp_fn_fp; defensive
        if i in matched_concern_idx:
            by_sev[key]["matched"] += 1
        else:
            by_sev[key]["missed"] += 1
    for j, flag in enumerate(flags):
        if j in matched_flag_idx:
            continue
        key = (flag.get("severity") or "").strip().upper()
        if key in by_sev:
            by_sev[key]["extra_flags"] += 1

    paper_excluded = len(concerns) == 0  # spec section 5: drop in macro

    return {
        "paper_id": paper_id,
        "n_flags": len(flags),
        "n_concerns": len(concerns),
        "matcher": match_result.get("matcher", "unknown"),
        "totals": dict(counts),
        "per_severity": by_sev,
        "paper_excluded": paper_excluded,
    }


# ---------------------------------------------------------------------------
# Cross-paper aggregation
# ---------------------------------------------------------------------------
def macro_average(per_paper_results: list[dict]) -> dict:
    """Macro-average per-paper weighted F1 across N papers.

    Per spec section 5, each paper is weighted equally regardless of
    its concern count. Papers with zero reviewer concerns
    (``paper_excluded=True``) are dropped from the denominator —
    a paper that no reviewer flagged provides no signal about
    MLGG's recall ceiling.

    Args:
        per_paper_results: list of dicts returned by ``per_paper_score``.

    Returns:
        Dict with macro-averaged precision / recall / F1, paper count,
        and an aggregated per-severity matched/missed breakdown.

    Raises:
        Never. Empty input emits a warning and returns zeros; this is
        a benchmark-runner convenience that lets the caller distinguish
        "ran with no papers" from "ran and got 0.0".
    """
    if not per_paper_results:
        warnings.warn(
            "macro_average called with empty per_paper_results; "
            "returning zeros. Did the benchmark wave produce no papers?",
            RuntimeWarning,
            stacklevel=2,
        )
        return {
            "n_papers": 0,
            "n_papers_excluded": 0,
            "macro_wPrecision": 0.0,
            "macro_wRecall": 0.0,
            "macro_weighted_f1": 0.0,
            "per_severity_totals": {
                sev: {"matched": 0, "missed": 0, "extra_flags": 0}
                for sev in SEVERITY_WEIGHTS
            },
        }

    included = [r for r in per_paper_results if not r.get("paper_excluded")]
    excluded_count = len(per_paper_results) - len(included)

    if not included:
        warnings.warn(
            f"all {len(per_paper_results)} papers were excluded "
            "(zero reviewer concerns); returning zeros.",
            RuntimeWarning,
            stacklevel=2,
        )
        macro_p = macro_r = macro_f1 = 0.0
    else:
        n = len(included)
        macro_p = sum(r["totals"]["wPrecision"] for r in included) / n
        macro_r = sum(r["totals"]["wRecall"] for r in included) / n
        macro_f1 = sum(r["totals"]["weighted_f1"] for r in included) / n

    agg_sev: dict[str, dict[str, int]] = {
        sev: {"matched": 0, "missed": 0, "extra_flags": 0}
        for sev in SEVERITY_WEIGHTS
    }
    for r in per_paper_results:
        for sev, counts in r.get("per_severity", {}).items():
            if sev not in agg_sev:
                continue
            for k in ("matched", "missed", "extra_flags"):
                agg_sev[sev][k] += counts.get(k, 0)

    return {
        "n_papers": len(included),
        "n_papers_excluded": excluded_count,
        "macro_wPrecision": macro_p,
        "macro_wRecall": macro_r,
        "macro_weighted_f1": macro_f1,
        "per_severity_totals": agg_sev,
    }


__all__ = [
    "SEVERITY_WEIGHTS",
    "WeightedCounts",
    "severity_weight",
    "weighted_tp_fn_fp",
    "per_paper_score",
    "macro_average",
]
