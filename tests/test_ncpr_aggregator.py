"""Tests for ``scripts/rag/evals/ncpr_aggregator`` (W22-X5).

Coverage:
* Empty input — sane zeros, no NaN/crash.
* 30 synthetic papers — aggregate values within expected bounds and the
  failure-case threshold (0.30) is applied per-paper.
* JSON roundtrip (atomic write + json.loads).
* Markdown report contains the expected section headings and tables.
* Failure-case threshold counts strictly less-than 0.30.
* Atomic-write rejects missing parent directory.
"""
from __future__ import annotations

import json
import random

import pytest

from rag.evals.ncpr_aggregator import (
    FAILURE_F1_THRESHOLD,
    aggregate,
    write_report_md,
    write_results_json,
)


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────


def _make_paper(
    pid: str,
    f1: float,
    *,
    precision: float | None = None,
    recall: float | None = None,
    category_coverage: float = 0.5,
    severities: dict[str, tuple[int, int]] | None = None,
    categories: dict[str, tuple[int, int]] | None = None,
) -> dict:
    if precision is None:
        precision = f1
    if recall is None:
        recall = f1
    severities = severities or {"CRITICAL": (1, 2), "LOW": (1, 1)}
    categories = categories or {"evaluation": (1, 2), "design": (1, 1)}
    return {
        "paper_id": pid,
        "weighted_f1": f1,
        "weighted_precision": precision,
        "weighted_recall": recall,
        "category_coverage": category_coverage,
        "per_severity_matched": {k: m for k, (m, _t) in severities.items()},
        "per_severity_total": {k: t for k, (_m, t) in severities.items()},
        "per_category_matched": {k: m for k, (m, _t) in categories.items()},
        "per_category_total": {k: t for k, (_m, t) in categories.items()},
    }


# ────────────────────────────────────────────────────────────────────────
# 1. Empty input
# ────────────────────────────────────────────────────────────────────────


def test_aggregate_empty_returns_sane_zeros():
    s = aggregate([])
    assert s["n_papers"] == 0
    assert s["macro_weighted_f1"] == 0.0
    assert s["macro_weighted_precision"] == 0.0
    assert s["macro_weighted_recall"] == 0.0
    assert s["macro_category_coverage"] == 0.0
    assert s["per_severity_recall"] == {}
    assert s["per_category_recall"] == {}
    assert s["failure_case_count"] == 0
    assert s["percentiles"] == {"p25": 0.0, "p50": 0.0, "p75": 0.0}
    # JSON-serialisable.
    assert json.loads(json.dumps(s)) == s


# ────────────────────────────────────────────────────────────────────────
# 2. 30 synthetic papers
# ────────────────────────────────────────────────────────────────────────


def test_aggregate_thirty_papers_within_bounds():
    rng = random.Random(20260517)
    papers = [
        _make_paper(f"P{i:03d}", f1=rng.random()) for i in range(30)
    ]
    s = aggregate(papers)
    assert s["n_papers"] == 30
    for k in (
        "macro_weighted_f1",
        "macro_weighted_precision",
        "macro_weighted_recall",
        "macro_category_coverage",
    ):
        assert 0.0 <= s[k] <= 1.0, f"{k} out of [0,1]: {s[k]}"
    for k in ("p25", "p50", "p75"):
        assert 0.0 <= s["percentiles"][k] <= 1.0
    assert s["percentiles"]["p25"] <= s["percentiles"]["p50"] <= s["percentiles"]["p75"]
    # Per-severity / per-category pooled recall in [0, 1].
    for v in s["per_severity_recall"].values():
        assert 0.0 <= v <= 1.0
    for v in s["per_category_recall"].values():
        assert 0.0 <= v <= 1.0
    # Pooled recall for severities we know the per-paper ratios for:
    # CRITICAL was matched 1/2 in every paper, so pooled = 30/60 = 0.5.
    assert s["per_severity_recall"]["CRITICAL"] == pytest.approx(0.5)
    assert s["per_severity_recall"]["LOW"] == pytest.approx(1.0)


def test_pooled_recall_reads_real_per_severity_schema():
    # Production schema (ncpr_severity_score.per_paper_score): per_severity is a
    # dict {sev: {matched, missed, extra_flags}} — NOT the flat
    # per_severity_matched/_total form. recall = matched / (matched + missed);
    # extra_flags (false positives) are excluded. Pre-fix this field was never
    # read, so per_severity_recall came back empty.
    papers = [
        {"paper_id": "P1", "weighted_f1": 0.5, "weighted_precision": 0.5,
         "weighted_recall": 0.5, "category_coverage": 1.0,
         "per_severity": {"CRITICAL": {"matched": 1, "missed": 1, "extra_flags": 3}}},
        {"paper_id": "P2", "weighted_f1": 0.5, "weighted_precision": 0.5,
         "weighted_recall": 0.5, "category_coverage": 1.0,
         "per_severity": {"CRITICAL": {"matched": 2, "missed": 0, "extra_flags": 0}}},
    ]
    s = aggregate(papers)
    # pooled = (1+2) matched / (2+2) total = 0.75; extra_flags ignored
    assert s["per_severity_recall"]["CRITICAL"] == pytest.approx(0.75)


# ────────────────────────────────────────────────────────────────────────
# 3. JSON roundtrip (atomic write)
# ────────────────────────────────────────────────────────────────────────


def test_write_results_json_roundtrip(tmp_path):
    papers = [
        _make_paper("A", 0.8),
        _make_paper("B", 0.1),
        _make_paper("C", 0.55),
    ]
    summary = aggregate(papers)
    out = tmp_path / "results.json"
    write_results_json(papers, summary, out)

    loaded = json.loads(out.read_text(encoding="utf-8"))
    assert set(loaded.keys()) == {"summary", "per_paper"}
    assert loaded["summary"]["n_papers"] == 3
    assert [p["paper_id"] for p in loaded["per_paper"]] == ["A", "B", "C"]
    # No leftover .tmp files in the target dir.
    leftover = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftover == []


def test_write_results_json_rejects_missing_parent(tmp_path):
    bogus = tmp_path / "does-not-exist" / "results.json"
    with pytest.raises(FileNotFoundError):
        write_results_json([], aggregate([]), bogus)


# ────────────────────────────────────────────────────────────────────────
# 4. Markdown report shape
# ────────────────────────────────────────────────────────────────────────


def test_write_report_md_contains_key_sections(tmp_path):
    papers = [
        _make_paper("good-paper", 0.95),
        _make_paper("bad-paper", 0.10),
    ]
    summary = aggregate(papers)
    out = tmp_path / "report.md"
    write_report_md(papers, summary, out)
    text = out.read_text(encoding="utf-8")

    # Headline structure.
    assert "# NCPR v1 Benchmark Report" in text
    assert "## Summary" in text
    assert "## Percentile bands" in text
    assert "## Recall by severity" in text
    assert "## Recall by category" in text
    assert "## Top failure cases" in text

    # Headline metrics rendered.
    assert "macro_weighted_f1" in text
    assert "macro_weighted_precision" in text
    assert "failure_case_count" in text

    # Bad paper appears in the failure-cases table; good one does not.
    assert "bad-paper" in text
    assert "good-paper" not in text


# ────────────────────────────────────────────────────────────────────────
# 5. Failure-case threshold semantics
# ────────────────────────────────────────────────────────────────────────


def test_failure_case_count_threshold_is_strict_less_than():
    # Boundary: 0.30 itself should NOT count as a failure.
    papers = [
        _make_paper("just-at-threshold", FAILURE_F1_THRESHOLD),
        _make_paper("just-below", FAILURE_F1_THRESHOLD - 1e-9),
        _make_paper("clear-fail", 0.05),
        _make_paper("pass", 0.85),
    ]
    s = aggregate(papers)
    assert s["failure_case_count"] == 2


def test_aggregate_ignores_non_finite_per_paper_values():
    # nan/inf should not poison the macro means.
    papers = [
        _make_paper("a", float("nan")),
        _make_paper("b", float("inf")),
        _make_paper("c", 0.5),
    ]
    s = aggregate(papers)
    # nan/inf coerce to 0.0, so mean = (0 + 0 + 0.5) / 3.
    assert s["macro_weighted_f1"] == pytest.approx(0.5 / 3)
    # And the two coerced-to-zero papers count as failures.
    assert s["failure_case_count"] == 2
