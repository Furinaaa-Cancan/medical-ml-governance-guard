"""Unit tests for the NCPR v2 diagnostic cosine sweep (W23-C1).

All tests are offline and deterministic. The embedding function is a
hand-rolled lookup that returns fixed vectors keyed on known phrases,
so cosine similarities are computable by hand and the monotonicity
properties of the sweep can be asserted exactly.
"""
from __future__ import annotations

import math
from typing import Iterable

import pytest

from rag.evals.ncpr_diagnostic_sweep import (
    DEFAULT_THRESHOLDS,
    sweep_thresholds,
    write_sweep_report,
)


# ────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────


def _flag(code: str = "x", evidence_text: str = "", category: str = "evaluation"):
    return {
        "code": code,
        "severity": "HIGH",
        "category": category,
        "evidence_text": evidence_text,
    }


def _concern(
    concern_id: str = "c1",
    concern_text: str = "",
    category: str = "evaluation",
    mlgg_gates: Iterable[str] | None = None,
):
    return {
        "concern_id": concern_id,
        "concern_text": concern_text,
        "severity": "HIGH",
        "category": category,
        "mlgg_gates": list(mlgg_gates or []),
    }


def _embed_factory(table: dict[str, list[float]]):
    """Return an embed_fn that maps known normalized text to fixed vectors.

    Unknown text → orthogonal vector so cosine collapses to 0.
    """
    default = [1.0, 0.0, 0.0, 0.0]

    def embed_fn(text: str):
        key = (text or "").strip().lower()
        return table.get(key, default)

    return embed_fn


# ────────────────────────────────────────────────────────────────────────
# Tests
# ────────────────────────────────────────────────────────────────────────


def test_sweep_returns_all_thresholds():
    """sweep_thresholds must produce one entry per requested τ."""
    flags = [_flag(evidence_text="ppv too low")]
    concerns = [_concern(concern_text="ppv too low")]
    embed = _embed_factory({
        "ppv too low": [0.0, 1.0, 0.0, 0.0],
    })
    thresholds = (0.5, 0.6, 0.7, 0.8, 0.9)
    results = sweep_thresholds(flags, concerns, embed, thresholds=thresholds)

    assert set(results.keys()) == {round(t, 4) for t in thresholds}
    for row in results.values():
        for key in ("precision", "recall", "f1", "matched_pairs"):
            assert key in row


def test_monotonic_recall_in_threshold():
    """Recall must be non-increasing as τ rises (higher τ ⇒ fewer matches)."""
    # Two paired flags/concerns at different similarity levels.
    flags = [
        _flag(code="a", evidence_text="strong overlap"),
        _flag(code="b", evidence_text="weak overlap"),
    ]
    concerns = [
        _concern(concern_id="c1", concern_text="strong overlap"),
        _concern(concern_id="c2", concern_text="weak overlap"),
    ]
    embed = _embed_factory({
        # Identical pair → cosine 1.0
        "strong overlap": [1.0, 0.0],
        # Diagonal pair → cosine ≈ 0.6
        "weak overlap":   [0.6, 0.8],
    })
    results = sweep_thresholds(
        flags, concerns, embed,
        thresholds=(0.50, 0.70, 0.95),
    )
    recalls = [results[round(t, 4)]["recall"] for t in (0.50, 0.70, 0.95)]
    # Non-increasing: each subsequent recall ≤ previous.
    for prev, curr in zip(recalls, recalls[1:]):
        assert curr <= prev + 1e-12, f"recall not monotone: {recalls}"


def test_matched_pairs_monotone_in_threshold():
    """Matched-pair count at higher τ never exceeds that at lower τ."""
    flags = [
        _flag(code="a", evidence_text="alpha text"),
        _flag(code="b", evidence_text="beta text"),
    ]
    concerns = [
        _concern(concern_id="c1", concern_text="alpha text"),
        _concern(concern_id="c2", concern_text="beta text"),
    ]
    # Alpha is exact (sim 1.0), beta is mid (sim ≈ 0.78).
    embed = _embed_factory({
        "alpha text": [1.0, 0.0],
        "beta text":  [0.78, 0.6257],   # cos with itself = 1; cross-pair drops
    })
    results = sweep_thresholds(
        flags, concerns, embed,
        thresholds=(0.50, 0.80, 0.99),
    )
    pair_counts = [
        results[round(t, 4)]["matched_pairs"] for t in (0.50, 0.80, 0.99)
    ]
    for prev, curr in zip(pair_counts, pair_counts[1:]):
        assert curr <= prev, f"matched_pairs not monotone: {pair_counts}"


def test_write_sweep_report_creates_valid_markdown(tmp_path):
    """The report must exist, contain a markdown table, and be UTF-8."""
    flags = [_flag(evidence_text="ppv too low")]
    concerns = [_concern(concern_text="ppv too low")]
    embed = _embed_factory({"ppv too low": [0.0, 1.0]})

    results = sweep_thresholds(
        flags, concerns, embed, thresholds=(0.5, 0.7, 0.9),
    )
    out = tmp_path / "sweep.md"
    write_sweep_report(results, out)

    assert out.exists(), "sweep report file was not created"
    text = out.read_text(encoding="utf-8")
    # Markdown table header from the writer.
    assert "| τ (cosine) | precision | recall | F1 | matched pairs |" in text
    # At least one data row for one of the requested thresholds.
    assert "| 0.50 |" in text or "| 0.70 |" in text
    # ASCII curve section present.
    assert "ASCII precision/recall curve" in text


def test_empty_inputs_zeros_no_crash(tmp_path):
    """Empty flags / concerns must yield all-zero rows and write cleanly."""
    embed = _embed_factory({})
    results = sweep_thresholds(
        [], [], embed, thresholds=(0.5, 0.7, 0.9),
    )
    assert set(results.keys()) == {0.5, 0.7, 0.9}
    for row in results.values():
        assert row["precision"] == 0.0
        assert row["recall"] == 0.0
        assert row["f1"] == 0.0
        assert row["matched_pairs"] == 0
        # No NaNs leaking through the safe-divide.
        for k in ("precision", "recall", "f1"):
            assert math.isfinite(row[k])

    # Writer must still succeed.
    out = tmp_path / "empty.md"
    write_sweep_report(results, out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_default_thresholds_constant_matches_spec():
    """DEFAULT_THRESHOLDS must cover the spec grid 0.50 → 0.90 step 0.05."""
    assert DEFAULT_THRESHOLDS == (
        0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90,
    )


def test_perfect_match_yields_unit_precision_recall():
    """When every flag pairs perfectly with one concern, P=R=F1=1 at low τ."""
    flags = [
        _flag(code="a", evidence_text="alpha"),
        _flag(code="b", evidence_text="beta"),
    ]
    concerns = [
        _concern(concern_id="c1", concern_text="alpha"),
        _concern(concern_id="c2", concern_text="beta"),
    ]
    embed = _embed_factory({
        "alpha": [1.0, 0.0],
        "beta":  [0.0, 1.0],
    })
    results = sweep_thresholds(flags, concerns, embed, thresholds=(0.5,))
    row = results[0.5]
    assert row["matched_pairs"] == 2
    assert row["precision"] == pytest.approx(1.0)
    assert row["recall"] == pytest.approx(1.0)
    assert row["f1"] == pytest.approx(1.0)
