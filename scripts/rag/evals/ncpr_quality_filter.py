#!/usr/bin/env python3
"""NCPR v2 — Quality Filter for Premium Holdout Pool (W23-C3).

Implements the pre-registered W23-B5 quality floor that gates which
``references/case-studies/peer-review-kb.json`` entries are eligible
for the NCPR v2 holdout sampler. Two stacked floors:

* **Paper-level**: does this paper belong in the pool at all? (PDF,
  ≥5 concerns, ≥1 CRITICAL, ≥3 categories, key methodology issues
  populated, author response present, year ≥ 2023.)
* **Concern-level**: does this individual concern carry signal?
  (text ≥30 chars, severity labelled, category labelled, ≥1 mlgg
  gate, author response matched.)

Concern-level rejection cascades up — a paper whose qualifying concern
count drops below 5 after concern filtering is itself rejected, even if
its paper-level score originally passed.

Spec: ``references/benchmark/ncpr_v2_quality_floor.md``.
Threshold weights and defaults frozen for v2 — any change requires a
new ADR + spec bump.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paper-level scoring weights (W23-B5 table).
# Sum of weights = 9; default pass threshold = 7 (premium tier).
# ---------------------------------------------------------------------------
_PAPER_WEIGHT_HAS_PDF = 0  # implicit precondition; tracked but not scored
_PAPER_WEIGHT_MIN_CONCERNS = 2
_PAPER_WEIGHT_HAS_CRITICAL = 2
_PAPER_WEIGHT_DISTINCT_CATEGORIES = 1
_PAPER_WEIGHT_KEY_METHOD_ISSUES = 2
_PAPER_WEIGHT_AUTHOR_RESPONSE = 1
_PAPER_WEIGHT_YEAR_2023 = 1

_PAPER_MIN_CONCERNS = 5
_PAPER_MIN_CRITICAL = 1
_PAPER_MIN_DISTINCT_CATEGORIES = 3
_PAPER_MIN_YEAR = 2023
_KEY_METHOD_MIN_LEN = 20

# ---------------------------------------------------------------------------
# Concern-level scoring weights (W23-B5 table). Sum = 5; default pass = 3.
# ---------------------------------------------------------------------------
_CONCERN_TEXT_MIN_LEN = 30
_VALID_SEVERITIES = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
# Note: spec doc lists 5 NCPR dimensions; KB entries use richer category
# names (e.g. "study_design", "data_leakage"). For the quality filter we
# only check that a non-empty, non-sentinel category label is present.
_INVALID_CATEGORY_SENTINELS = {"", "other", "unknown", "null", "none"}
_INVALID_RESPONSE_SENTINELS = {"", "[pending]", "tbd", "n/a", "none"}


def score_concern(concern: dict[str, Any]) -> dict[str, Any]:
    """Score a single reviewer concern against the W23-B5 floor.

    Args:
        concern: a single entry from a paper's ``reviewer_concerns`` list.

    Returns:
        ``{'score': int, 'rejection_reasons': [str, ...]}``. Score is
        the sum of satisfied criteria weights (max 5). ``rejection_reasons``
        lists every criterion that failed, even if the overall score still
        passes — useful for audit-log transparency.
    """
    score = 0
    reasons: list[str] = []

    text = (concern.get("concern_text") or "").strip()
    if len(text) >= _CONCERN_TEXT_MIN_LEN:
        score += 1
    else:
        reasons.append(
            f"concern_text length {len(text)} < {_CONCERN_TEXT_MIN_LEN}"
        )

    severity = (concern.get("severity") or "").strip().upper()
    if severity in _VALID_SEVERITIES:
        score += 1
    else:
        reasons.append(f"severity not in {sorted(_VALID_SEVERITIES)}: {severity!r}")

    category = (concern.get("category") or "").strip().lower()
    if category and category not in _INVALID_CATEGORY_SENTINELS:
        score += 1
    else:
        reasons.append(f"category unlabelled or sentinel: {category!r}")

    gates = concern.get("mlgg_gates") or []
    if isinstance(gates, list) and len(gates) >= 1:
        score += 1
    else:
        reasons.append("mlgg_gates empty or not a list")

    response = (concern.get("author_response") or "").strip().lower()
    if response and response not in _INVALID_RESPONSE_SENTINELS:
        score += 1
    else:
        reasons.append("author_response missing or sentinel")

    return {"score": score, "rejection_reasons": reasons}


def score_paper(
    paper_entry: dict[str, Any],
    pdf_available: bool = True,
) -> dict[str, Any]:
    """Score a KB paper entry against the W23-B5 paper-level floor.

    Args:
        paper_entry: a single entry from ``peer-review-kb.json``'s
            ``entries`` list.
        pdf_available: whether a real PDF / methods text is resolvable
            for this paper. Caller (sampler / orchestrator) supplies the
            availability map; default ``True`` keeps the function pure
            and testable in isolation. A ``False`` value short-circuits
            to a hard rejection regardless of other criteria.

    Returns:
        ``{'score': int, 'breakdown': {criterion_name: bool, ...},
        'rejection_reasons': [str, ...]}``. Score is the weighted sum
        of satisfied criteria (max 9).
    """
    breakdown: dict[str, bool] = {}
    reasons: list[str] = []
    score = 0

    # 1. PDF availability — precondition, not scored, but tracked.
    breakdown["has_pdf"] = bool(pdf_available)
    if not pdf_available:
        reasons.append("no PDF available (W23-A1 inventory miss)")

    concerns = paper_entry.get("reviewer_concerns") or []
    n_concerns = len(concerns)

    # 2. ≥5 reviewer concerns (+2).
    if n_concerns >= _PAPER_MIN_CONCERNS:
        score += _PAPER_WEIGHT_MIN_CONCERNS
        breakdown["min_concerns"] = True
    else:
        breakdown["min_concerns"] = False
        reasons.append(f"only {n_concerns} concerns, need >= {_PAPER_MIN_CONCERNS}")

    # 3. ≥1 CRITICAL severity concern (+2).
    n_critical = sum(
        1 for c in concerns if (c.get("severity") or "").strip().upper() == "CRITICAL"
    )
    if n_critical >= _PAPER_MIN_CRITICAL:
        score += _PAPER_WEIGHT_HAS_CRITICAL
        breakdown["has_critical"] = True
    else:
        breakdown["has_critical"] = False
        reasons.append(f"only {n_critical} CRITICAL, need >= {_PAPER_MIN_CRITICAL}")

    # 4. ≥3 distinct categories represented (+1).
    cats = {
        (c.get("category") or "").strip().lower()
        for c in concerns
        if (c.get("category") or "").strip()
    }
    cats.discard("")
    cats -= _INVALID_CATEGORY_SENTINELS
    if len(cats) >= _PAPER_MIN_DISTINCT_CATEGORIES:
        score += _PAPER_WEIGHT_DISTINCT_CATEGORIES
        breakdown["distinct_categories"] = True
    else:
        breakdown["distinct_categories"] = False
        reasons.append(
            f"only {len(cats)} distinct categories, need >= {_PAPER_MIN_DISTINCT_CATEGORIES}"
        )

    # 5. key_methodology_issues populated, ≥1 entry of ≥20 chars (+2).
    issues = paper_entry.get("key_methodology_issues") or []
    has_substantive_issue = isinstance(issues, list) and any(
        isinstance(s, str) and len(s.strip()) >= _KEY_METHOD_MIN_LEN for s in issues
    )
    if has_substantive_issue:
        score += _PAPER_WEIGHT_KEY_METHOD_ISSUES
        breakdown["key_methodology_issues"] = True
    else:
        breakdown["key_methodology_issues"] = False
        reasons.append(
            f"key_methodology_issues empty or no entry >= {_KEY_METHOD_MIN_LEN} chars"
        )

    # 6. author_response present for ≥1 concern (+1).
    has_response = any(
        (c.get("author_response") or "").strip().lower()
        not in _INVALID_RESPONSE_SENTINELS
        for c in concerns
    )
    if has_response:
        score += _PAPER_WEIGHT_AUTHOR_RESPONSE
        breakdown["author_response"] = True
    else:
        breakdown["author_response"] = False
        reasons.append("no concern has matched author_response")

    # 7. publication year ≥ 2023 (+1).
    year = paper_entry.get("year") or paper_entry.get("publication_year")
    if isinstance(year, int) and year >= _PAPER_MIN_YEAR:
        score += _PAPER_WEIGHT_YEAR_2023
        breakdown["year_2023"] = True
    else:
        breakdown["year_2023"] = False
        reasons.append(f"year {year!r} < {_PAPER_MIN_YEAR}")

    return {"score": score, "breakdown": breakdown, "rejection_reasons": reasons}


def filter_holdout_pool(
    kb_entries: list[dict[str, Any]],
    min_paper_score: int = 7,
    min_concern_score: int = 3,
    pdf_availability: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Apply both floors to a full KB entries list.

    Process per spec section "Concern-level rejection cascades up":

    1. Score every concern; drop concerns with ``score < min_concern_score``.
    2. Score the paper, gated on PDF availability and on its **post-prune**
       qualifying concern count (criterion 2 must still hold).
    3. Keep papers whose final paper-score ≥ ``min_paper_score`` AND whose
       PDF is available AND whose post-prune concern count ≥ 5.

    Args:
        kb_entries: ``json.load(...)['entries']`` from ``peer-review-kb.json``.
        min_paper_score: paper-level pass threshold (default 7 per W23-B5).
        min_concern_score: concern-level pass threshold (default 3).
        pdf_availability: ``{paper_id: bool}`` from W23-A1 inventory; missing
            keys default to ``True`` (assume PDF present — the audit log will
            surface mis-mapped IDs separately).

    Returns:
        ``{
          'eligible': [paper_entry_with_pruned_concerns, ...],
          'rejected': [{'paper_id', 'reasons': [...]}, ...],
          'concerns_filtered': int,  # total dropped concerns
        }``
    """
    pdf_map = pdf_availability or {}
    eligible: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    concerns_filtered = 0

    for entry in kb_entries:
        paper_id = entry.get("id") or entry.get("paper_id") or "<unknown>"
        pdf_ok = pdf_map.get(paper_id, True)

        original_concerns = entry.get("reviewer_concerns") or []
        kept_concerns: list[dict[str, Any]] = []
        dropped_reasons: list[dict[str, Any]] = []
        for c in original_concerns:
            cscore = score_concern(c)
            if cscore["score"] >= min_concern_score:
                kept_concerns.append(c)
            else:
                concerns_filtered += 1
                dropped_reasons.append(
                    {
                        "concern_id": c.get("concern_id"),
                        "score": cscore["score"],
                        "reasons": cscore["rejection_reasons"],
                    }
                )

        # Re-evaluate paper with pruned concern set.
        pruned_entry = {**entry, "reviewer_concerns": kept_concerns}
        pscore = score_paper(pruned_entry, pdf_available=pdf_ok)

        passes = (
            pdf_ok
            and pscore["score"] >= min_paper_score
            and len(kept_concerns) >= _PAPER_MIN_CONCERNS
        )
        if passes:
            eligible.append(pruned_entry)
        else:
            reasons = list(pscore["rejection_reasons"])
            if not pdf_ok:
                reasons.append("pdf_unavailable (hard fail)")
            if len(kept_concerns) < _PAPER_MIN_CONCERNS:
                reasons.append(
                    f"only {len(kept_concerns)} concerns survived concern-level prune, "
                    f"need >= {_PAPER_MIN_CONCERNS}"
                )
            rejected.append(
                {
                    "paper_id": paper_id,
                    "score": pscore["score"],
                    "reasons": reasons,
                    "dropped_concerns": dropped_reasons,
                }
            )

    return {
        "eligible": eligible,
        "rejected": rejected,
        "concerns_filtered": concerns_filtered,
    }


def write_audit_log(filter_result: dict[str, Any], out_path: Path) -> None:
    """Append a JSONL transparency log of every rejection.

    One line per rejected paper, plus one line per dropped concern. CI can
    grep this file to enforce the W23-B5 transparency clause (no paper
    rejected on a criterion not listed in the spec).

    Args:
        filter_result: return value of :func:`filter_holdout_pool`.
        out_path: target path (default per spec: ``/tmp/W23_quality_rejects.jsonl``).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as fh:
        for r in filter_result.get("rejected", []):
            fh.write(
                json.dumps(
                    {
                        "kind": "paper",
                        "paper_id": r["paper_id"],
                        "score": r.get("score"),
                        "reasons": r.get("reasons", []),
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            for dc in r.get("dropped_concerns", []):
                fh.write(
                    json.dumps(
                        {
                            "kind": "concern",
                            "paper_id": r["paper_id"],
                            "concern_id": dc.get("concern_id"),
                            "score": dc.get("score"),
                            "reasons": dc.get("reasons", []),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )


__all__ = [
    "score_paper",
    "score_concern",
    "filter_holdout_pool",
    "write_audit_log",
]
