#!/usr/bin/env python3
"""NCPR v1 — Category-coverage diagnostic metric (W22-X3).

Companion metric to the NCPR semantic matcher
(`ncpr_v1_matcher_spec.md` §3, type-4 "category match"). Unlike the
precision / recall pair that drive headline NCPR numbers, *category
coverage* is a diagnostic, **not** a benchmark KPI. It answers a single
question per paper:

    For each of the five standard NCPR concern dimensions
    (evaluation, design, reporting, external_val, leakage), did MLGG
    raise at least one flag that lines up — by dimension label alone —
    with at least one reviewer concern in that dimension?

This is intentionally weaker than the matcher's type 1-3 rules: it
ignores gate codes and embedding similarity and only looks at the
coarse ``category`` / ``dimension`` label. The value is operational:
it lets us see at-a-glance whether MLGG has *any* coverage of, say,
"external_val" complaints, even when the specific gate codes do not
line up. A category with reviewer concerns and zero MLGG flags is a
hard miss; a category with MLGG flags but zero reviewer concerns is
fine (no penalty — we only report it as a side fact).

Pre-registration note
---------------------
The five-category list below (`CATEGORIES`) is frozen for NCPR v1. Any
addition / removal / rename requires the same ADR + version-bump
treatment described in `ncpr_v1_matcher_spec.md` §9.

Unknown-category handling
-------------------------
A flag whose ``category`` is not one of the five frozen categories is
**silently dropped from per-category accounting** but logged via the
standard :mod:`logging` machinery at WARNING level. We deliberately do
*not* raise:

- The headline matcher (`ncpr_matcher.py`) is the authoritative source
  of fail-loud behaviour for the benchmark. Category coverage is a
  diagnostic, so raising here would block legitimate benchmark runs on
  cosmetic label drift (e.g. a new gate emitting `category="bias"`
  before this list is bumped to v2).
- A WARNING is loud enough for CI log scraping and for the aggregator
  (`aggregate_coverage`) to surface drift, without breaking the run.
- Reviewer-side unknown dimensions are handled identically (warn +
  drop) for symmetry; there is no asymmetry the caller has to
  remember.

This file is READ-ONLY with respect to the matcher and the rest of the
RAG stack — it does not import retrieval, embedding, or KB modules,
and it has no side effects beyond logging.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

__all__ = [
    "CATEGORIES",
    "category_coverage",
    "aggregate_coverage",
]

# Frozen for NCPR v1. See module docstring + ncpr_v1_matcher_spec.md §9.
CATEGORIES: List[str] = [
    "evaluation",
    "design",
    "reporting",
    "external_val",
    "leakage",
]

_CATEGORY_SET = frozenset(CATEGORIES)

_logger = logging.getLogger(__name__)


def _bucket(
    items: List[Dict[str, Any]],
    field: str,
    *,
    side: str,
) -> Dict[str, List[Dict[str, Any]]]:
    """Group ``items`` by their ``field`` value, keeping only known categories.

    Items whose ``field`` value is not in :data:`CATEGORIES` are dropped
    from the result and a WARNING is logged. Items missing ``field``
    entirely are treated the same as having an unknown value.

    Parameters
    ----------
    items:
        List of flag dicts (MLGG side, ``field="category"``) or concern
        dicts (reviewer side, ``field="dimension"``).
    field:
        Name of the category-bearing key on each item.
    side:
        Either ``"mlgg"`` or ``"reviewer"``. Used only in the warning
        message so log scrapers can tell which side drifted.

    Returns
    -------
    dict
        Mapping from category name (one of :data:`CATEGORIES`) to the
        list of items in that bucket. All five categories appear as
        keys even if their bucket is empty, so downstream code does not
        need to ``setdefault``.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {c: [] for c in CATEGORIES}
    for item in items:
        raw = item.get(field)
        # Normalize: lowercase + strip; non-strings become "" and get
        # treated as unknown.
        cat = raw.strip().lower() if isinstance(raw, str) else ""
        if cat in _CATEGORY_SET:
            buckets[cat].append(item)
        else:
            _logger.warning(
                "ncpr_category_coverage: dropping %s item with unknown "
                "category=%r (known=%s)",
                side,
                raw,
                CATEGORIES,
            )
    return buckets


def category_coverage(
    flags: List[Dict[str, Any]],
    concerns: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compute category-coverage diagnostic for one paper.

    For each of the five frozen NCPR categories, mark the category as
    "covered" when **both** sides have at least one item in that
    bucket. A category that has reviewer concerns but no MLGG flags is
    a *missed category*. A category with neither side present is
    neither covered nor missed (it just was not in scope for this
    paper).

    Parameters
    ----------
    flags:
        MLGG flag dicts. Each should carry a ``category`` field
        matching :data:`CATEGORIES`. Unknown categories are dropped
        with a WARNING (see module docstring).
    concerns:
        Reviewer concern dicts. Each should carry a ``dimension``
        field matching :data:`CATEGORIES`. Unknown dimensions are
        dropped with a WARNING.

    Returns
    -------
    dict
        Keys:

        - ``coverage_per_category`` (dict[str, bool]) — per-category
          covered flag.
        - ``coverage_rate`` (float) — fraction of the five categories
          marked covered. Always denominator = 5 (not "categories in
          scope"); this keeps the metric comparable across papers.
        - ``missed_categories`` (list[str]) — categories where the
          reviewer raised ≥1 concern but MLGG raised 0 flags. Sorted
          in the canonical :data:`CATEGORIES` order for reproducibility.
        - ``concerns_per_category_reviewer`` (dict[str, int]) — count
          of reviewer concerns in each known category.
        - ``flags_per_category_mlgg`` (dict[str, int]) — count of MLGG
          flags in each known category.
    """
    flag_buckets = _bucket(flags or [], "category", side="mlgg")
    concern_buckets = _bucket(concerns or [], "dimension", side="reviewer")

    coverage_per_category: Dict[str, bool] = {}
    missed: List[str] = []
    for cat in CATEGORIES:
        has_flag = bool(flag_buckets[cat])
        has_concern = bool(concern_buckets[cat])
        covered = has_flag and has_concern
        coverage_per_category[cat] = covered
        if has_concern and not has_flag:
            missed.append(cat)

    coverage_rate = sum(coverage_per_category.values()) / len(CATEGORIES)

    return {
        "coverage_per_category": coverage_per_category,
        "coverage_rate": coverage_rate,
        "missed_categories": missed,
        "concerns_per_category_reviewer": {
            cat: len(concern_buckets[cat]) for cat in CATEGORIES
        },
        "flags_per_category_mlgg": {
            cat: len(flag_buckets[cat]) for cat in CATEGORIES
        },
    }


def aggregate_coverage(
    per_paper_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Macro-average category coverage across N papers.

    Parameters
    ----------
    per_paper_results:
        List of dicts as returned by :func:`category_coverage`. An
        empty list yields all-zero rates and ``n_papers=0`` (no
        exception) so callers can pipe a filtered subset (e.g. only
        papers with ≥1 reviewer concern) without special-casing the
        empty branch.

    Returns
    -------
    dict
        Keys:

        - ``n_papers`` (int) — number of papers aggregated.
        - ``coverage_rate_per_category`` (dict[str, float]) — per
          category, fraction of papers that covered it. This is the
          headline diagnostic surface: a 0.0 here means MLGG never
          caught a concern in that category across the whole eval.
        - ``mean_coverage_rate`` (float) — macro-average of the
          per-paper ``coverage_rate`` values.
        - ``papers_with_full_coverage`` (int) — papers where all five
          categories were covered.
        - ``total_missed_by_category`` (dict[str, int]) — per category,
          number of papers where it was a *missed category* (reviewer
          raised, MLGG silent). Useful for prioritizing gate work.
    """
    n = len(per_paper_results)
    if n == 0:
        return {
            "n_papers": 0,
            "coverage_rate_per_category": {c: 0.0 for c in CATEGORIES},
            "mean_coverage_rate": 0.0,
            "papers_with_full_coverage": 0,
            "total_missed_by_category": {c: 0 for c in CATEGORIES},
        }

    per_cat_hits: Dict[str, int] = {c: 0 for c in CATEGORIES}
    per_cat_missed: Dict[str, int] = {c: 0 for c in CATEGORIES}
    sum_rate = 0.0
    full_coverage = 0

    for paper in per_paper_results:
        per_cat = paper.get("coverage_per_category", {})
        for cat in CATEGORIES:
            if per_cat.get(cat):
                per_cat_hits[cat] += 1
        for cat in paper.get("missed_categories", []):
            if cat in _CATEGORY_SET:
                per_cat_missed[cat] += 1
        sum_rate += float(paper.get("coverage_rate", 0.0))
        if all(per_cat.get(cat) for cat in CATEGORIES):
            full_coverage += 1

    return {
        "n_papers": n,
        "coverage_rate_per_category": {
            cat: per_cat_hits[cat] / n for cat in CATEGORIES
        },
        "mean_coverage_rate": sum_rate / n,
        "papers_with_full_coverage": full_coverage,
        "total_missed_by_category": per_cat_missed,
    }
