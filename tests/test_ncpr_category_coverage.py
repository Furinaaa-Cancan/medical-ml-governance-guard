"""Tests for ``scripts/rag/evals/ncpr_category_coverage.py`` (W22-X3).

Exercises:
- per-paper coverage on a fully-covered synthetic input,
- empty-flags edge case (rate == 0.0),
- *missed-category* detection (reviewer raised, MLGG silent),
- unknown-category-in-flag handling: documented choice is silent skip
  + WARNING log, not raise (matches module docstring),
- aggregation across 3 papers with varying coverage.

All inputs are dict literals, so the suite is offline and deterministic.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import pytest

from scripts.rag.evals.ncpr_category_coverage import (
    CATEGORIES,
    aggregate_coverage,
    category_coverage,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _flag(cat: str, code: str = "x_gate") -> Dict[str, Any]:
    return {"code": code, "severity": "med", "category": cat, "evidence_text": ""}


def _concern(dim: str, cid: str = "c1") -> Dict[str, Any]:
    return {"concern_id": cid, "concern_text": "...", "dimension": dim, "mlgg_gates": []}


@pytest.fixture
def full_coverage_inputs() -> Dict[str, List[Dict[str, Any]]]:
    """One flag + one concern in every one of the five categories."""
    return {
        "flags": [_flag(c) for c in CATEGORIES],
        "concerns": [_concern(c, cid=f"c_{c}") for c in CATEGORIES],
    }


# ---------------------------------------------------------------------------
# Per-paper tests
# ---------------------------------------------------------------------------


def test_full_coverage_synthetic(full_coverage_inputs):
    """All 5 categories covered → rate == 1.0, no missed categories."""
    out = category_coverage(full_coverage_inputs["flags"], full_coverage_inputs["concerns"])
    assert out["coverage_rate"] == pytest.approx(1.0)
    assert all(out["coverage_per_category"].values())
    assert out["missed_categories"] == []
    assert out["concerns_per_category_reviewer"] == {c: 1 for c in CATEGORIES}
    assert out["flags_per_category_mlgg"] == {c: 1 for c in CATEGORIES}


def test_zero_flags_yields_zero_rate():
    """No MLGG flags + reviewer concerns present → rate 0.0, all categories missed."""
    concerns = [_concern(c, cid=f"c_{c}") for c in CATEGORIES]
    out = category_coverage([], concerns)
    assert out["coverage_rate"] == pytest.approx(0.0)
    assert all(v is False for v in out["coverage_per_category"].values())
    assert set(out["missed_categories"]) == set(CATEGORIES)
    # Reviewer side intact; MLGG side all zero.
    assert out["flags_per_category_mlgg"] == {c: 0 for c in CATEGORIES}


def test_missed_category_detection():
    """Reviewer raises 'leakage' but MLGG only fires on 'design' → leakage missed."""
    flags = [_flag("design"), _flag("design", code="other_gate")]
    concerns = [_concern("design"), _concern("leakage", cid="c_leak")]
    out = category_coverage(flags, concerns)

    assert out["coverage_per_category"]["design"] is True
    assert out["coverage_per_category"]["leakage"] is False
    assert out["missed_categories"] == ["leakage"]
    # rate = 1 covered / 5 total
    assert out["coverage_rate"] == pytest.approx(1 / 5)
    # Categories with neither side present are NOT in missed_categories.
    for cat in ("evaluation", "reporting", "external_val"):
        assert cat not in out["missed_categories"]


def test_unknown_category_in_flag_is_warned_not_raised(caplog):
    """Module docstring: unknown category → silent drop + WARNING. Justify:
    diagnostic metric must not block the benchmark on cosmetic label drift;
    the headline matcher (`ncpr_matcher.py`) is the authoritative fail-loud
    surface. A WARNING is loud enough for CI log scraping.
    """
    flags = [
        _flag("design"),  # known, keeps the bucket non-empty
        _flag("bias"),  # unknown — should be dropped
        {"code": "x", "severity": "low", "category": None, "evidence_text": ""},  # missing
    ]
    concerns = [_concern("design"), _concern("evaluation", cid="c_eval")]

    with caplog.at_level(logging.WARNING, logger="scripts.rag.evals.ncpr_category_coverage"):
        out = category_coverage(flags, concerns)

    # Two unknowns ⇒ two warnings.
    warning_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_msgs) == 2
    assert any("category='bias'" in m or "category=" in m for m in warning_msgs)
    # Known flag still counted.
    assert out["flags_per_category_mlgg"]["design"] == 1
    # Unknowns did not invent a key.
    assert set(out["flags_per_category_mlgg"].keys()) == set(CATEGORIES)
    # evaluation was raised by reviewer but MLGG had only design + drops ⇒ missed.
    assert "evaluation" in out["missed_categories"]


def test_aggregate_three_papers_varying_coverage():
    """Aggregate macro-average over 3 papers: full / partial / zero."""
    papers = [
        # Paper 1: full coverage
        category_coverage(
            flags=[_flag(c) for c in CATEGORIES],
            concerns=[_concern(c, cid=f"p1_{c}") for c in CATEGORIES],
        ),
        # Paper 2: covers only 'design' and 'leakage'; misses 'evaluation'.
        category_coverage(
            flags=[_flag("design"), _flag("leakage")],
            concerns=[
                _concern("design", cid="p2_d"),
                _concern("leakage", cid="p2_l"),
                _concern("evaluation", cid="p2_e"),
            ],
        ),
        # Paper 3: zero flags, reviewer raised 'external_val'.
        category_coverage(
            flags=[],
            concerns=[_concern("external_val", cid="p3_x")],
        ),
    ]

    agg = aggregate_coverage(papers)

    assert agg["n_papers"] == 3
    assert agg["papers_with_full_coverage"] == 1
    # Mean of [1.0, 2/5, 0.0] == 1.4/3 ≈ 0.4667
    assert agg["mean_coverage_rate"] == pytest.approx((1.0 + 2 / 5 + 0.0) / 3)

    # Per-category hit rate: 'design' covered by P1 & P2 ⇒ 2/3.
    assert agg["coverage_rate_per_category"]["design"] == pytest.approx(2 / 3)
    # 'leakage' covered by P1 & P2 ⇒ 2/3.
    assert agg["coverage_rate_per_category"]["leakage"] == pytest.approx(2 / 3)
    # 'evaluation' covered only by P1 ⇒ 1/3.
    assert agg["coverage_rate_per_category"]["evaluation"] == pytest.approx(1 / 3)
    # 'external_val' covered only by P1 ⇒ 1/3.
    assert agg["coverage_rate_per_category"]["external_val"] == pytest.approx(1 / 3)

    # Missed counts: 'evaluation' missed in P2; 'external_val' missed in P3.
    assert agg["total_missed_by_category"]["evaluation"] == 1
    assert agg["total_missed_by_category"]["external_val"] == 1
    assert agg["total_missed_by_category"]["design"] == 0
    assert agg["total_missed_by_category"]["leakage"] == 0


def test_aggregate_empty_list_is_safe():
    """Empty input → all-zero result, no exception (documented contract)."""
    out = aggregate_coverage([])
    assert out["n_papers"] == 0
    assert out["mean_coverage_rate"] == 0.0
    assert out["coverage_rate_per_category"] == {c: 0.0 for c in CATEGORIES}
    assert out["papers_with_full_coverage"] == 0
